# SPDX-License-Identifier: MPL-2.0
"""Hardware-free tests for OpenZilo Connect API v2 host mode and ConnectClient."""

from __future__ import annotations

import asyncio
from collections import defaultdict
import contextlib
import io
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

import libopenzilo as native

from openzilo import (
    ButtonDoubleClickGesture,
    ButtonSingleClickGesture,
    CONNECT_API_VERSION,
    ConnectClient,
    ConnectHost,
    DoubleTapGesture,
    LiveAudioEnded,
    LiveAudioFrame,
    LiveAudioStarted,
    Packet,
    RingAxisPresetKind,
    SensorGesture,
    _cli as cli,
)
from openzilo._compatibility import DeviceCapabilities, FeatureVersion, RecordingLimits
from openzilo._connect_calibration import ConnectCalibrationStore
from openzilo._connect_protocol import (
    OPERATION_SCOPES,
    SCOPES,
    TOPIC_SCOPES,
    command_topic,
    decode_bytes,
    encode_bytes,
    require_scopes,
)
from openzilo._device import SystemInfo


def _make_system_info_body(
    *,
    fw: str = "V2.001.0002.0001",
    model: str = "Open Zilo",
    sn: str = "SYNTH-SN-001",
    cpuid: str = "SYNTH-CPU-001",
    battery: int = 85,
    charging: bool = False,
) -> bytes:
    def _str(s: str) -> bytes:
        b = s.encode("utf-8")
        return struct.pack(">H", len(b)) + b

    return (
        _str(fw)
        + struct.pack(">IIIBB", 1_700_000_000, 1024, 512, battery, 1 if charging else 0)
        + _str(sn)
        + _str(cpuid)
        + _str(model)
    )


def _make_imu_batch_body(seq_start: int, count: int, *, ax: int = 0, ay: int = 0, az: int = 4096, gx: int = 0, gy: int = 0, gz: int = 0) -> bytes:
    header = struct.pack(">HIHH", 0, seq_start, count, 16)
    samples = bytearray()
    for i in range(count):
        ts = (seq_start + i) * 10
        samples.extend(struct.pack(">Ihhhhhh", ts, ax, ay, az, gx, gy, gz))
    return header + bytes(samples)


class _FakeRingClient:
    """In-memory stand-in for OpenZiloClient used to drive ConnectHost without BLE."""

    def __init__(self, **_kwargs) -> None:
        self.is_connected = False
        self._disconnected = asyncio.Event()
        self._disconnected.set()
        self._handlers: dict[int, list] = defaultdict(list)
        self.sent_requests: list[tuple[int, int | None, bytes]] = []
        self.capabilities = DeviceCapabilities(
            source="device",
            firmware_version="V2.001.0002.0001",
            model="Open Zilo",
            board_target="openzilo_ring_v1",
            features=(
                FeatureVersion("imu", 2, 0),
                FeatureVersion("live_audio", 1, 0),
                FeatureVersion("recording_control", 1, 0),
                FeatureVersion("connection_rssi", 1, 0),
            ),
            recording_limits=RecordingLimits(16000, 20, 3, 7, 3, 16000, 64000, 0, 1024, 20, 60000, 20),
        )
        self.info = SystemInfo(
            firmware_version="V2.001.0002.0001",
            system_time=1_700_000_000,
            audio_storage_total=1024,
            audio_storage_available=512,
            battery_percent=85,
            battery_charging=False,
            sn="SYNTH-SN-001",
            cpuid="SYNTH-CPU-001",
            model="Open Zilo",
        )
        self.imu_running = False
        self.recording_session_id = 0

    async def connect(self) -> None:
        self.is_connected = True
        self._disconnected.clear()

    async def disconnect(self) -> None:
        self.is_connected = False
        self._disconnected.set()

    def add_packet_handler(self, command: int, handler, *, queue_packets: bool = True) -> None:
        self._handlers[int(command)].append(handler)

    def remove_packet_handler(self, command: int, handler) -> None:
        if handler in self._handlers[int(command)]:
            self._handlers[int(command)].remove(handler)

    def emit(self, command: int, body: bytes) -> None:
        packet = Packet(command=command, body=body, version=4, body_crc=0)
        for handler in list(self._handlers.get(command, [])):
            handler(packet)

    async def send_command(self, command: int, body: bytes = b"") -> None:
        self.sent_requests.append((int(command), None, bytes(body)))

    async def request(self, command: int, response_command: int, body: bytes = b"", *, timeout_s: float | None = None) -> Packet:
        cmd = int(command)
        resp = int(response_command)
        self.sent_requests.append((cmd, resp, bytes(body)))
        if cmd == 0x0101:
            return Packet(command=resp, body=_make_system_info_body(), version=4, body_crc=0)
        if cmd == 0x0105:
            # Minimal valid capabilities response: ok(0) + schema(1)
            return Packet(command=resp, body=b"\x00\x00\x01", version=4, body_crc=0)
        if cmd == 0x0107:
            return Packet(command=resp, body=struct.pack(">Hb", 0, -52), version=4, body_crc=0)
        if cmd == 0x0501:
            return Packet(command=resp, body=struct.pack(">HI", 0, 3), version=4, body_crc=0)
        if cmd == 0x050D:
            return Packet(command=resp, body=struct.pack(">HB", 0, body[0]), version=4, body_crc=0)
        if cmd == 0x0514:
            self.recording_session_id = 42
            return Packet(command=resp, body=struct.pack(">HI", 0, 42), version=4, body_crc=0)
        if cmd == 0x0516:
            self.recording_session_id = 0
            return Packet(command=resp, body=struct.pack(">H", 0), version=4, body_crc=0)
        if cmd == 0x0518:
            state = 2 if self.recording_session_id else 0
            return Packet(command=resp, body=struct.pack(">HIBIII", 0, self.recording_session_id, state, 0, 0, 0), version=4, body_crc=0)
        if cmd == 0x0601:
            self.imu_running = True
            return Packet(command=resp, body=struct.pack(">HHHH", 0, 100, 8, 2000), version=4, body_crc=0)
        if cmd == 0x0603:
            self.imu_running = False
            return Packet(command=resp, body=struct.pack(">H", 0), version=4, body_crc=0)
        if cmd == 0x050D:
            return Packet(command=resp, body=struct.pack(">H", 0), version=4, body_crc=0)
        return Packet(command=resp, body=struct.pack(">H", 0), version=4, body_crc=0)


class ConnectPolicyAndCalibrationTests(unittest.TestCase):
    def test_policy_matches_android_contract(self) -> None:
        self.assertEqual(SCOPES, {"info", "recording", "audio", "sensors", "logs", "time", "firmware"})
        self.assertEqual(set(TOPIC_SCOPES.keys()), {"status", "imu", "gesture", "live", "audio", "recording", "time"})
        self.assertEqual(command_topic(0x0605), "imu")
        self.assertEqual(command_topic(0x0701), "gesture")
        self.assertEqual(command_topic(0x0704), "gesture")
        self.assertEqual(command_topic(0x050F), "live")
        self.assertEqual(command_topic(0x0511), "live")
        self.assertEqual(command_topic(0x050A), "recording")
        self.assertEqual(command_topic(0x0504), "audio")
        self.assertEqual(command_topic(0x0401), "time")
        self.assertIsNone(command_topic(0x0101))
        for op, scope in OPERATION_SCOPES.items():
            self.assertIn(scope, SCOPES, msg=op)
        with self.assertRaises(ValueError):
            require_scopes(set())
        with self.assertRaises(ValueError):
            require_scopes({"nonexistent"})

    def test_calibration_store_persists_gyro_and_mount(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cal.json"
            store = ConnectCalibrationStore(path)
            info = native.DeviceInfo(
                firmware_version="V2.001.0002.0001",
                system_time=100,
                audio_storage_total=100,
                audio_storage_available=50,
                battery_percent=90,
                battery_charging=False,
                sn="SYNTH-SN",
                cpuid="SYNTH-CPU",
                model="Open Zilo",
            )
            cfg = native.ImuConfig(sample_rate_hz=100, accel_range_g=8, gyro_range_dps=2000)
            features = [native.FeatureVersion(name="imu", major=2, minor=0)]
            samples = [
                native.ImuSample(timestamp_ms=i * 10, accel_x=0, accel_y=0, accel_z=4096, gyro_x=16, gyro_y=-16, gyro_z=32)
                for i in range(250)
            ]
            window = native.analyze_imu_static_window(samples, cfg, True)
            store.save_gyro_bias_window(info, cfg, features, window)
            store.save_mount_alignment(info, native.Quaternion(w=1.0, x=0.0, y=0.0, z=0.0))

            reloaded = ConnectCalibrationStore(path)
            self.assertEqual(reloaded.calibrated_components(info), ["gyro", "mount"])
            self.assertIsNotNone(reloaded.gyro_bias_dps(info))
            self.assertIsNotNone(reloaded.load_mount_alignment(info))

            reloaded.reset_calibration(info)
            self.assertEqual(reloaded.calibrated_components(info), [])
            self.assertIsNone(reloaded.gyro_bias_dps(info))


class ConnectHostEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fake_ring = _FakeRingClient()
        self.cal_store = ConnectCalibrationStore(Path(self._tmp.name) / "cal.json")

        self._patches = contextlib.ExitStack()
        self.addCleanup(self._patches.close)
        self._patches.enter_context(
            mock.patch("openzilo._connect_host.get_system_info", new=mock.AsyncMock(return_value=self.fake_ring.info))
        )
        self._patches.enter_context(
            mock.patch("openzilo._connect_host.get_device_capabilities", new=mock.AsyncMock(return_value=self.fake_ring.capabilities))
        )
        self._patches.enter_context(
            mock.patch("openzilo._connect_host.enable_time_sync")
        )

    async def _start_host(self, **kwargs) -> tuple[ConnectHost, int]:
        host = ConnectHost(
            address="SYNTH-ADDR",
            auto_reconnect=False,
            calibration_store=self.cal_store,
            client_factory=lambda **_kw: self.fake_ring,
            **kwargs,
        )
        _, port = await host.start_tcp("127.0.0.1", 0)
        self.addAsyncCleanup(host.stop)
        return host, port

    async def test_status_and_authorization_with_token(self) -> None:
        host, port = await self._start_host(
            allowed_scopes={"info", "sensors"},
            require_authorization=True,
            token="secret-token",
        )
        async with ConnectClient(port=port, token="secret-token", client_name="pose-app") as client:
            with self.assertRaisesRegex(RuntimeError, "Permission not granted"):
                await client.status()
            with self.assertRaisesRegex(RuntimeError, "Invalid host authorization token"):
                await client.request_authorization(["info"], token="wrong")

            auth = await client.request_authorization(["info", "sensors", "audio"])
            self.assertEqual(auth["apiVersion"], CONNECT_API_VERSION)
            self.assertEqual(auth["grantedScopes"], ["info", "sensors"])
            self.assertEqual(auth["deniedScopes"], ["audio"])

            st = await client.ring_status()
            self.assertEqual(st.phase, "disconnected")

            await client.subscribe(["status"])
            await host.connect_ring()

            ev_connecting = (await asyncio.wait_for(anext(client.events), timeout=2.0)).status_snapshot()
            self.assertIsNotNone(ev_connecting)
            assert ev_connecting is not None
            self.assertEqual(ev_connecting.phase, "connecting")

            event = await asyncio.wait_for(anext(client.events), timeout=2.0)
            connected = event.status_snapshot()
            self.assertIsNotNone(connected)
            assert connected is not None
            self.assertEqual(connected.phase, "connected")
            self.assertEqual(connected.model, "Open Zilo")
            self.assertEqual(connected.battery_percent, 85)
            self.assertIsNotNone(connected.ring_key)

            # Denied scope cannot execute audio operation
            reply = await client.execute("audio.count")
            self.assertFalse(reply["ok"])
            self.assertEqual(reply["error"], "permission_denied")

    async def test_multi_client_imu_lease_attitude_and_calibration(self) -> None:
        host, port = await self._start_host()
        await host.connect_ring()

        async with ConnectClient(port=port) as c1, ConnectClient(port=port) as c2:
            await c1.subscribe(["imu", "gesture"])
            await c2.subscribe(["imu"])

            cfg1 = await c1.start_imu()
            cfg2 = await c2.start_imu()
            self.assertEqual((cfg1.sample_rate_hz, cfg1.accel_range_g, cfg1.gyro_range_dps), (100, 8, 2000))
            self.assertEqual(cfg1, cfg2)
            # Hardware START_IMU (0x0601) sent only once for both clients
            start_cmds = [req for req in self.fake_ring.sent_requests if req[0] == 0x0601]
            self.assertEqual(len(start_cmds), 1)

            self.fake_ring.emit(0x0605, _make_imu_batch_body(0, 4))
            ev1 = await asyncio.wait_for(anext(c1.events), timeout=2.0)
            ev2 = await asyncio.wait_for(anext(c2.events), timeout=2.0)
            batch1 = ev1.imu_batch()
            batch2 = ev2.imu_batch()
            self.assertIsNotNone(batch1)
            self.assertIsNotNone(batch2)
            assert batch1 is not None and batch1.attitude is not None
            self.assertEqual(len(batch1.samples), 4)
            self.assertEqual(len(batch1.attitude.opengl_matrix), 16)
            self.assertIsNotNone(batch1.trajectory_quaternions)

            await c1.zero_attitude_heading()
            await c1.configure_attitude_axes(RingAxisPresetKind.SWAPPED_XY, True)
            upright = await c1.calibrate_upright_reference()
            self.assertIn("mount", upright["calibratedComponents"])
            reset = await c1.reset_imu_calibration()
            self.assertEqual(reset["calibratedComponents"], [])

            # Gesture enrichment
            self.fake_ring.emit(0x0701, struct.pack(">I", 1234))
            self.fake_ring.emit(0x0702, struct.pack(">IB", 1235, 1))
            self.fake_ring.emit(0x0703, struct.pack(">I", 1236))
            self.fake_ring.emit(0x0704, struct.pack(">I", 1237))
            g1 = (await asyncio.wait_for(anext(c1.events), timeout=2.0)).gesture_event()
            g2 = (await asyncio.wait_for(anext(c1.events), timeout=2.0)).gesture_event()
            g3 = (await asyncio.wait_for(anext(c1.events), timeout=2.0)).gesture_event()
            g4 = (await asyncio.wait_for(anext(c1.events), timeout=2.0)).gesture_event()
            self.assertEqual(g1, DoubleTapGesture(timestamp=1234))
            self.assertIsInstance(g2, SensorGesture)
            self.assertEqual(g3, ButtonDoubleClickGesture(timestamp=1236))
            self.assertEqual(g4, ButtonSingleClickGesture(timestamp=1237))

            # First client stops IMU -> hardware stays running because c2 holds a lease
            await c1.stop_imu()
            stop_cmds = [req for req in self.fake_ring.sent_requests if req[0] == 0x0603]
            self.assertEqual(len(stop_cmds), 0)

            # Second client stops IMU -> hardware stops
            await c2.stop_imu()
            stop_cmds = [req for req in self.fake_ring.sent_requests if req[0] == 0x0603]
            self.assertEqual(len(stop_cmds), 1)

    async def test_live_audio_ownership_and_disconnect_cleanup(self) -> None:
        host, port = await self._start_host()
        await host.connect_ring()

        c1 = ConnectClient(port=port)
        c2 = ConnectClient(port=port)
        await c1.connect()
        await c2.connect()
        try:
            await c1.subscribe(["live"])
            await c2.subscribe(["live"])

            r1 = await c1.execute("live.subscribe", {"enabled": True})
            self.assertTrue(r1["ok"])

            # c2 cannot take over live stream while c1 owns it
            r2 = await c2.execute("live.subscribe", {"enabled": True})
            self.assertFalse(r2["ok"])
            self.assertEqual(r2["error"], "operation_failed")

            # Emit live audio start, frame, end -> only c1 receives them
            opus = b"\xfc\xff\xfe"
            self.fake_ring.emit(0x050F, struct.pack(">IIIIHBB", 7, 0, 1_700_000_000, 0, 16000, 2, 3))
            self.fake_ring.emit(0x0510, struct.pack(">IIIH", 7, 0, 0, len(opus)) + opus)
            self.fake_ring.emit(0x0511, struct.pack(">HIIIII", 0, 7, 0, len(opus), len(opus), 0))

            ev_start = (await asyncio.wait_for(anext(c1.events), timeout=2.0)).live_audio()
            ev_frame = (await asyncio.wait_for(anext(c1.events), timeout=2.0)).live_audio()
            ev_end = (await asyncio.wait_for(anext(c1.events), timeout=2.0)).live_audio()
            self.assertEqual(ev_start, LiveAudioStarted(session_id=7, sample_rate=16000, channels=2))
            self.assertEqual(ev_frame, LiveAudioFrame(session_id=7, sequence=0, data=opus))
            self.assertEqual(ev_end, LiveAudioEnded(session_id=7, byte_count=len(opus)))

            # Closing c1 releases live control and sends LiveSubscribe(False)
            await c1.close()
            await asyncio.sleep(0.05)
            unsub_cmds = [req for req in self.fake_ring.sent_requests if req[0] == 0x050D and req[2] == b"\x00"]
            self.assertGreaterEqual(len(unsub_cmds), 1)

            # Now c2 can acquire live control
            r2_after = await c2.execute("live.subscribe", {"enabled": True})
            self.assertTrue(r2_after["ok"])
        finally:
            await c1.close()
            await c2.close()

    async def test_audio_clear_gate_and_firmware_requires_key(self) -> None:
        host, port = await self._start_host()
        await host.connect_ring()

        async with ConnectClient(port=port) as client:
            bad_clear = await client.execute("audio.clear", {"confirmed": False})
            self.assertFalse(bad_clear["ok"])
            self.assertEqual(bad_clear["error"], "invalid_arguments")

            ok_clear = await client.execute("audio.clear", {"confirmed": True})
            self.assertTrue(ok_clear["ok"])

            no_key_ota = await client.execute("firmware.upgrade", {"firmware": encode_bytes(b"zip")})
            self.assertFalse(no_key_ota["ok"])
            self.assertEqual(no_key_ota["error"], "operation_failed")

            rssi = await client.execute("connection.rssi")
            self.assertTrue(rssi["ok"])
            self.assertEqual(decode_bytes(rssi["body"]), struct.pack(">Hb", 0, -52))

    @unittest.skipUnless(hasattr(os, "AF_UNIX") or hasattr(asyncio, "start_unix_server"), "Unix sockets unavailable")
    async def test_unix_socket_transport(self) -> None:
        sock_path = Path(self._tmp.name) / "connect.sock"
        host = ConnectHost(
            address="SYNTH-ADDR",
            auto_reconnect=False,
            calibration_store=self.cal_store,
            client_factory=lambda **_kw: self.fake_ring,
        )
        await host.start_unix(sock_path)
        self.addAsyncCleanup(host.stop)
        await host.connect_ring()

        self.assertEqual(sock_path.stat().st_mode & 0o777, 0o600)
        async with ConnectClient(socket_path=sock_path) as client:
            st = await client.ring_status()
            self.assertEqual(st.phase, "connected")
            self.assertEqual(st.model, "Open Zilo")


class ConnectHostCliParserTests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_host_parser_and_validation(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args([
            "host",
            "--address", "SYNTH-ADDR",
            "--host", "127.0.0.1",
            "--port", "7421",
            "--scopes", "info,sensors",
            "--require-authorization",
            "--no-reconnect",
        ])
        self.assertEqual(args.command, "host")
        self.assertEqual(args.port, 7421)
        self.assertTrue(args.require_authorization)
        self.assertTrue(args.no_reconnect)

        bad_args = parser.parse_args(["host", "--address", "SYNTH-ADDR", "--stdio", "--socket", "/tmp/a.sock"])
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "--stdio cannot be combined with --socket"):
                await cli.dispatch(bad_args)

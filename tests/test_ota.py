# SPDX-License-Identifier: MPL-2.0
"""OTA client checks using synthetic bytes and a simulated BLE peer."""
import asyncio
import binascii
import hashlib
import io
import json
import zipfile
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from openzilo._firmware_bundle import DOMAIN

import openzilo as sdk
from openzilo import _cli as cli

TARGET = "V2.001.0002.0000"
OLD = "V2.000.0002.0001"
_SYNTHETIC = bytes(range(256)) * 35 + b"tail"
PACKAGE = b"RINGENC1" + struct.pack("<II", 1, len(_SYNTHETIC) - 32) + b"0" * 16 + _SYNTHETIC[32:]
KEY = ec.generate_private_key(ec.SECP256R1())
PUBLIC_KEY = KEY.public_key().public_bytes(serialization.Encoding.PEM,
                                          serialization.PublicFormat.SubjectPublicKeyInfo)


def make_bundle(payload=PACKAGE, *, version=TARGET, model="Test Ring"):
    meta = dict(schema=1, algorithm="ECDSA-P256-SHA256", image="app", version=version,
        model=model, board="synthetic/board", profile="production", security_version=1,
        source_versions=[], key_id=hashlib.sha256(KEY.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest(),
        payload=dict(file="app.ota.bin", format="RINGENC1", size=len(payload),
                     sha256=hashlib.sha256(payload).hexdigest()))
    raw = json.dumps(meta).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", raw)
        archive.writestr("manifest.sig", KEY.sign(DOMAIN + raw, ec.ECDSA(hashes.SHA256())))
        archive.writestr("app.ota.bin", payload)
    return output.getvalue()


def text_field(value):
    raw = value.encode()
    return struct.pack(">H", len(raw)) + raw


class RingPeer:
    def __init__(self, package=PACKAGE):
        self.package = package
        self.is_connected = False
        self.rx = None
        self.disconnected = None
        self.commands = []
        self.responses = []
        self.notify_body = None
        self.version = OLD
        self.identity = "synthetic-test-device"
        self.model = "Test Ring"
        self.window = 4096
        self.start = 0
        self.next_request = None
        self.final_body = b"\x00\x00"
        self.do_reboot = True
        self.running_version = TARGET
        self.running_identity = self.identity
        self.connect_count = 0
        self.fail_reconnect = 0
        self.optional_ack = False
        self.begin = None
        self.repeat_once = False
        self.repeated = False

    def set_rx_callback(self, callback):
        self.rx = callback

    def _set_disconnect_callback(self, callback):
        self.disconnected = callback

    async def connect(self):
        self.connect_count += 1
        if self.connect_count > 1 and self.fail_reconnect:
            self.fail_reconnect -= 1
            raise sdk.TransportError("Synthetic reconnect failure")
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False
        if self.disconnected:
            self.disconnected()

    def emit(self, command, body):
        packet = sdk.encode_packet(command, body)
        # Notifications can split a protocol header/body at arbitrary boundaries.
        for offset in range(0, len(packet), 7):
            self.rx(packet[offset:offset + 7])

    def request(self, offset, window=None, kind=0, error=0):
        self.emit(2001, struct.pack(">HHII", error, kind, offset,
                                    self.window if window is None else window))

    async def write(self, data):
        await asyncio.sleep(0)
        packet = sdk.decode_packet(data)
        self.commands.append(packet.command)
        if packet.command == 0x0101:
            body = (b"\x00\x00" + text_field(self.version)
                    + struct.pack(">IIIHB", 0, 100, 50, 80, 0)
                    + text_field("") + text_field(self.identity) + text_field(self.model))
            self.emit(0x0102, body)
        elif packet.command == 0x0105:
            fields = {1: self.version.encode(), 2: self.model.encode(), 3: b"synthetic/board",
                      4: b"12345678", 5: b"synthetic-build", 6: b"\x00\x04", 0x109: b"\x01\x00"}
            body = b"\x00\x00\x01" + b"".join(struct.pack(">HH", t, len(v)) + v for t, v in fields.items())
            self.emit(0x0106, body)
        elif packet.command == 1005:
            self.notify_body = packet.body
            if self.begin is not None:
                self.begin(self)
            else:
                if self.optional_ack:
                    self.emit(1105, b"\x00\x00")
                self.request(self.start, kind=2)
        elif packet.command == 2101:
            error, offset, size = struct.unpack(">HII", packet.body[:10])
            chunk = packet.body[10:]
            if error or size != len(chunk) or chunk != self.package[offset:offset + size]:
                raise AssertionError("Invalid packet contents sent to peer")
            self.responses.append((offset, chunk))
            if self.next_request is not None:
                self.next_request(self, offset, chunk)
            elif self.repeat_once and not self.repeated:
                self.repeated = True
                self.request(offset)
            elif offset + size < len(self.package):
                self.request(offset + size)
            else:
                self.emit(2201, self.final_body)
                if self.do_reboot:
                    self.version = self.running_version
                    self.identity = self.running_identity
                    # Deliver terminal status and disconnect in the same turn.
                    self.is_connected = False
                    self.disconnected()


class FirmwareUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.peer = RingPeer()
        self.client = sdk.OpenZiloClient(transport=self.peer)
        await self.client.connect()

    async def asyncTearDown(self):
        await self.client.disconnect()

    async def update(self, **kwargs):
        version = kwargs.pop("version", TARGET)
        model = kwargs.pop("expected_model", "Test Ring")
        options = dict(trusted_public_key=PUBLIC_KEY, timeout_s=0.5,
                       total_timeout_s=2.0, reboot_timeout_s=0.5)
        options.update(kwargs)
        return await sdk.update_firmware(self.client, make_bundle(self.peer.package, version=version, model=model), **options)

    def assert_clean(self):
        self.assertFalse(self.client._firmware_update_active)
        for command in (1105, 2001, 2201):
            self.assertEqual(self.client._handlers[command], [])
            self.assertTrue(self.client._queues[command].empty())

    async def test_upload_without_start_ack_and_verify_after_immediate_reboot(self):
        progress = []
        info = await self.update(progress=lambda n, total: progress.append((n, total)),
                                 expected_model="Test Ring")
        self.assertEqual(info.firmware_version, TARGET)
        self.assertEqual(self.peer.connect_count, 2)
        self.assertEqual(b"".join(data for _, data in self.peer.responses), PACKAGE)
        self.assertEqual([len(data) for _, data in self.peer.responses], [4096, 4096, 772])
        expected = (struct.pack(">II", 2, len(TARGET)) + TARGET.encode()
                    + struct.pack(">IH", len(PACKAGE), binascii.crc_hqx(PACKAGE, 0xFFFF)))
        self.assertEqual(self.peer.notify_body, expected)
        self.assertEqual(progress[0], (0, len(PACKAGE)))
        self.assertEqual(progress[-1], (len(PACKAGE), len(PACKAGE)))
        self.assert_clean()

    async def test_negotiated_session_rediscovers_after_firmware_reboot(self):
        self.client.capabilities = sdk.DeviceCapabilities(
            "device", OLD, "Test Ring", "synthetic/board",
            features=(sdk.FeatureVersion("ota", 1, 0),))
        info = await self.update()
        self.assertIsNotNone(self.client.capabilities)
        self.assertEqual(self.client.capabilities.source, "device")
        self.assertEqual(self.client.capabilities.firmware_version, info.firmware_version)

    async def test_build_suffix_is_transmitted_and_verified_exactly(self):
        target = TARGET + "-prod-1234abcd"
        self.peer.running_version = target
        info = await self.update(version=target)
        self.assertEqual(info.firmware_version, target)
        self.assertIn(target.encode(), self.peer.notify_body)
        # A different build of the same base version must not count as success.
        with self.assertRaisesRegex(sdk.ProtocolError, "version verification failed"):
            await self.update(version=TARGET + "-prod-1234abce")
        self.assert_clean()

    async def test_optional_ack_repeated_request_and_monotonic_progress(self):
        self.peer.optional_ack = True
        self.peer.repeat_once = True
        progress = []
        await self.update(progress=lambda n, _: progress.append(n))
        self.assertEqual(self.peer.responses[0], self.peer.responses[1])
        self.assertEqual(progress, sorted(set(progress)))
        self.assert_clean()

    async def test_device_selected_resume_offset_and_short_final_packet(self):
        self.peer.start = 4000
        self.peer.window = 3000
        await self.update()
        self.assertEqual(self.peer.responses[0][0], 4000)
        self.assertEqual(b"".join(data for _, data in self.peer.responses), PACKAGE[4000:])

    async def test_changed_window_and_overlapping_retry(self):
        self.peer.window = 1000
        def follow(peer, offset, data):
            if len(peer.responses) == 1:
                peer.request(500, window=2000)
            else:
                peer.next_request = None
                peer.request(offset + len(data))
        self.peer.next_request = follow
        await self.update()
        self.assertEqual(self.peer.responses[1], (500, PACKAGE[500:2500]))

    async def test_invalid_inputs_do_not_start_update(self):
        cases = [dict(version="bad"), dict(version="V1.2.3.4\x00"),
                 dict(timeout_s=0), dict(total_timeout_s=float("inf")),
                 dict(reboot_timeout_s=-1)]
        for options in cases:
            with self.subTest(options=options), self.assertRaises(ValueError):
                await self.update(**options)
        with self.assertRaises(ValueError):
            await sdk.update_firmware(self.client, b"", trusted_public_key=PUBLIC_KEY)
        self.assertEqual(self.peer.commands, [])
        self.assert_clean()

    async def test_model_mismatch_and_already_running_version_do_not_notify(self):
        with self.assertRaisesRegex(sdk.ProtocolError, "model"):
            await self.update(expected_model="Another Ring")
        self.peer.version = TARGET
        with self.assertRaisesRegex(sdk.ProtocolError, "already"):
            await self.update()
        self.assertNotIn(1005, self.peer.commands)
        self.assert_clean()

    async def test_disconnected_client_rejected(self):
        await self.client.disconnect()
        with self.assertRaises(sdk.TransportError):
            await self.update()
        self.assertEqual(self.peer.commands, [])

    async def test_notify_and_result_errors_preserve_device_error(self):
        for command in (1105, 2201):
            self.peer.begin = lambda p, command=command: p.emit(command, b"\xff\xff")
            with self.subTest(command=command), self.assertRaises(sdk.DeviceError) as error:
                await self.update()
            self.assertEqual(error.exception.error_code, 65535)
            self.assert_clean()

    async def test_malformed_status_and_request_rejected(self):
        for command, body in [(1105, b"\x00"), (2201, b"\x00\x00\x00"),
                              (2001, b"\x00" * 11), (2001, b"\x00" * 13)]:
            self.peer.begin = lambda p, command=command, body=body: p.emit(command, body)
            with self.subTest(command=command, size=len(body)), self.assertRaises(sdk.ProtocolError):
                await self.update()
            self.assert_clean()

    async def test_invalid_offsets_windows_and_boot_requests_rejected(self):
        for offset, window, kind in [(0, 0, 2), (0, 4097, 2), (len(PACKAGE), 10, 2),
                                     (0xFFFFFFFF, 10, 2), (0, 10, 1)]:
            self.peer.begin = lambda p: p.request(offset, window, kind)
            with self.subTest(offset=offset, window=window, kind=kind), self.assertRaises(sdk.ProtocolError):
                await self.update()
            self.assertEqual(self.peer.responses, [])

    async def test_offset_gap_after_first_packet_rejected(self):
        self.peer.next_request = lambda p, offset, data: p.request(offset + len(data) + 1)
        with self.assertRaisesRegex(sdk.ProtocolError, "skipped"):
            await self.update()
        self.assert_clean()

    async def test_premature_success_is_not_installation_success(self):
        self.peer.begin = lambda p: p.emit(2201, b"\x00\x00")
        with self.assertRaisesRegex(sdk.ProtocolError, "before"):
            await self.update()
        self.assertEqual(self.peer.connect_count, 1)

    async def test_idle_timeout_and_hung_write_are_bounded(self):
        self.peer.begin = lambda p: None
        with self.assertRaises(sdk.TimeoutError):
            await self.update(timeout_s=0.01)
        original_write = self.peer.write
        async def hang(data):
            if sdk.decode_packet(data).command == 1005:
                await asyncio.Event().wait()
            await original_write(data)
        self.peer.write = hang
        with self.assertRaises(sdk.TimeoutError):
            await self.update(timeout_s=0.01)
        self.assert_clean()

    async def test_repeated_requests_cannot_extend_total_deadline(self):
        self.peer.next_request = lambda p, offset, data: p.request(0)
        with self.assertRaises(sdk.TimeoutError):
            await self.update(total_timeout_s=0.03)
        self.assert_clean()

    async def test_disconnect_before_final_status_never_succeeds(self):
        def disconnect(peer, offset, data):
            peer.is_connected = False
            peer.disconnected()
        self.peer.next_request = disconnect
        with self.assertRaisesRegex(sdk.TransportError, "unconfirmed"):
            await self.update()
        self.assert_clean()

    async def test_final_result_without_reboot_does_not_succeed(self):
        self.peer.do_reboot = False
        with self.assertRaisesRegex(sdk.TimeoutError, "reboot"):
            await self.update(reboot_timeout_s=0.01)
        self.assert_clean()

    async def test_wrong_running_version_does_not_succeed(self):
        self.peer.running_version = OLD
        with self.assertRaisesRegex(sdk.ProtocolError, "version verification"):
            await self.update()
        self.assert_clean()

    async def test_different_device_does_not_succeed(self):
        self.peer.running_identity = "different-synthetic-device"
        with self.assertRaisesRegex(sdk.ProtocolError, "identity"):
            await self.update()
        self.assert_clean()

    async def test_reconnection_failure_is_bounded(self):
        self.peer.fail_reconnect = 100
        with self.assertRaisesRegex(sdk.TimeoutError, "reconnect"):
            await self.update(reboot_timeout_s=0.01)
        self.assert_clean()

    async def test_transient_reconnection_failure_retries(self):
        self.peer.fail_reconnect = 1
        info = await self.update(reboot_timeout_s=1.5)
        self.assertEqual(info.firmware_version, TARGET)
        self.assertEqual(self.peer.connect_count, 3)
        self.assert_clean()

    async def test_response_queue_overflow_fails_before_sending_data(self):
        def flood(peer):
            for _ in range(17):
                peer.request(0)
        self.peer.begin = flood
        with self.assertRaisesRegex(sdk.ProtocolError, "overflow"):
            await self.update()
        self.assertEqual(self.peer.responses, [])
        self.assert_clean()

    async def test_disconnect_cleanup_after_device_reboot_skips_gatt_operations(self):
        transport = sdk.NusClient(address="AA:BB:CC:DD:EE:FF")
        backend = Mock(is_connected=False, stop_notify=AsyncMock(), disconnect=AsyncMock())
        transport._client = backend
        transport._notify_started = True
        await transport.disconnect()
        backend.stop_notify.assert_not_awaited()
        backend.disconnect.assert_not_awaited()
        self.assertIsNone(transport._client)
        self.assertFalse(transport._notify_started)

    async def test_bad_packet_crc_fails(self):
        def corrupt(peer):
            packet = bytearray(sdk.encode_packet(2001, struct.pack(">HHII", 0, 2, 0, 1024)))
            packet[-1] ^= 1
            peer.rx(packet)
        self.peer.begin = corrupt
        with self.assertRaises(sdk.ProtocolError):
            await self.update()
        self.assert_clean()

    async def test_concurrent_update_rejected_and_cancellation_cleans_up(self):
        started = asyncio.Event()
        self.peer.begin = lambda p: started.set()
        first = asyncio.create_task(self.update())
        await started.wait()
        with self.assertRaisesRegex(sdk.ProtocolError, "already running"):
            await self.update()
        with self.assertRaisesRegex(sdk.ProtocolError, "owns this connection"):
            await sdk.get_system_info(self.client)
        with self.assertRaisesRegex(sdk.ProtocolError, "owns this connection"):
            await sdk.receive_auto_audio_file(self.client)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assert_clean()
        self.assertFalse(any(task is not asyncio.current_task() and not task.done()
                             for task in asyncio.all_tasks()))

    async def test_progress_callback_failure_cleans_up(self):
        def fail(sent, total):
            raise RuntimeError("callback failed")
        with self.assertRaisesRegex(RuntimeError, "callback failed"):
            await self.update(progress=fail)
        self.assert_clean()

    async def test_packet_writes_do_not_interleave(self):
        active = 0
        overlap = False
        async def slow_write(data):
            nonlocal active, overlap
            active += 1
            overlap |= active > 1
            await asyncio.sleep(0.001)
            active -= 1
        self.peer.write = slow_write
        await asyncio.gather(self.client.send_command(0x0402, b"a"),
                             self.client.send_command(2101, b"b"))
        self.assertFalse(overlap)


class OtaCliTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_bin_rejected_before_ble_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.ota.bin"
            path.write_bytes(PACKAGE)
            public = Path(directory) / "public.pem"
            public.write_bytes(PUBLIC_KEY)
            args = cli.build_parser().parse_args([
                "ota-update", str(path), "--public-key", str(public),
            ])
            with patch.object(cli, "OpenZiloClient") as client:
                with self.assertRaises(ValueError):
                    await args.func(args)
                client.assert_not_called()

    def test_public_api_exported(self):
        self.assertIn("update_firmware", sdk.__all__)

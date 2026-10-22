# SPDX-License-Identifier: MPL-2.0
import asyncio
from dataclasses import replace
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest import mock

import openzilo as sdk
from openzilo import _compatibility as compat
from openzilo import _cli as cli

VECTOR = bytes.fromhex((Path(__file__).parent / "fixtures/capabilities-v1.hex").read_text())
LEGACY = "V2.001.0002.0001-prod-7fd1dfc9"


def tlv(tag, value):
    return struct.pack(">HH", tag, len(value)) + value


def info_body(version):
    def text(value):
        raw = value.encode()
        return struct.pack(">H", len(raw)) + raw
    return b"\0\0" + text(version) + struct.pack(">IIIHB", 1, 2, 1, 90, 0) + text("synthetic") * 2 + text("Open Zilo")


class Peer:
    is_connected = False
    version = "V2.001.0002.0001"
    mode = "device"

    def __init__(self):
        self.writes = []

    def set_rx_callback(self, callback):
        self.rx = callback

    def _set_disconnect_callback(self, callback):
        self.disconnected = callback

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False
        self.disconnected()

    async def write(self, data):
        packet = sdk.decode_packet(data)
        self.writes.append(packet)
        if packet.command == 0x0101:
            self.rx(sdk.encode_packet(0x0102, info_body(self.version)))
        elif packet.command == 0x0105 and self.mode == "device":
            self.rx(sdk.encode_packet(0x0106, VECTOR))
        elif self.mode == "unsupported":
            self.rx(sdk.encode_packet(0x01FF, struct.pack(">HH", packet.command, 5)))


class CapabilityParserTests(unittest.TestCase):
    def test_firmware_golden_vector_and_combinations(self):
        caps = sdk.parse_device_capabilities(VECTOR)
        self.assertEqual(caps.boot_id, "0102030405060708")
        self.assertTrue(caps.supports("imu"))
        self.assertFalse(caps.supports("imu", major=1))
        self.assertFalse(caps.supports("gesture"))
        self.assertFalse(caps.supports("recording_control", min_minor=1))
        caps.recording_limits.validate(sdk.AudioRecordingConfig())
        with self.assertRaises(sdk.CompatibilityError):
            replace(caps.recording_limits, channels_mask=2).validate(sdk.AudioRecordingConfig())
        with self.assertRaises(sdk.CompatibilityError):
            replace(caps.recording_limits, continue_outputs_mask=0).validate(
                sdk.AudioRecordingConfig(output=sdk.AudioOutput.FLASH,
                    disconnect_policy=sdk.AudioDisconnectPolicy.CONTINUE_SAVING))

    def test_unknown_optional_tlv_and_feature_are_forward_compatible(self):
        caps = sdk.parse_device_capabilities(VECTOR + tlv(0x300, b"future") + tlv(0x10C, b"\1\0"))
        self.assertTrue(caps.supports("recording_control"))
        self.assertTrue(caps.supports("unknown_12", major=1))
        with self.assertRaises(sdk.CompatibilityError):
            sdk.parse_device_capabilities(VECTOR + tlv(0x8001, b"required"))

    def test_malformed_or_duplicate_fields_do_not_silently_downgrade(self):
        for value in (VECTOR[:-1], VECTOR + b"x", VECTOR + tlv(1, b"duplicate"),
                      VECTOR.replace(b"\1\6\0\2\2\0", b"\1\6\0\2\0\0"),
                      VECTOR.replace(b"Open Zilo", b"Open Zil\xff"), b"\0\0\1"):
            with self.subTest(value=value[-8:]), self.assertRaises(sdk.ProtocolError):
                sdk.parse_device_capabilities(value)

    def test_schema_and_feature_major_are_independent(self):
        with self.assertRaises(sdk.CompatibilityError):
            sdk.parse_device_capabilities(VECTOR[:2] + b"\2" + VECTOR[3:])
        caps = sdk.parse_device_capabilities(VECTOR.replace(b"\1\4\0\2\1\0", b"\1\4\0\2\2\0"))
        self.assertFalse(caps.supports("recording_control"))
        self.assertTrue(caps.supports("imu"))

    def test_only_documented_frame_version_is_accepted(self):
        for version in (0, 1, 3, 5):
            frame = bytearray(sdk.encode_packet(0x0101))
            struct.pack_into(">H", frame, 1, version)
            with self.assertRaises(sdk.ProtocolError):
                sdk.decode_packet(frame)

    def test_sdk_identity_is_reproducible_and_matches_distribution(self):
        from importlib.metadata import version
        first = sdk.get_sdk_identity()
        self.assertEqual(first, sdk.get_sdk_identity())
        self.assertEqual(first.version, version("OpenZilo"))
        self.assertEqual(len(first.source_sha256), 64)


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.peer = Peer()
        self.client = sdk.OpenZiloClient(transport=self.peer)
        await self.client.connect()

    async def asyncTearDown(self):
        await self.client.disconnect()

    async def discover(self, **kwargs):
        return await sdk.get_device_capabilities(self.client, timeout_s=.03, **kwargs)

    async def test_discovery_is_cached_and_serialized(self):
        first, second = await asyncio.gather(self.discover(), self.discover())
        self.assertIs(first, second)
        self.assertEqual([p.command for p in self.peer.writes], [0x0101, 0x0105])
        await self.discover(refresh=True)
        self.assertEqual(len(self.peer.writes), 4)

    async def test_exact_legacy_build_fallback_for_silent_and_explicit_rejection(self):
        for mode in ("silent", "unsupported"):
            self.peer.mode, self.peer.version = mode, LEGACY
            caps = await self.discover()
            self.assertEqual(caps.source, "legacy_profile")
            self.assertEqual(caps.board_target, "ring_dvt2/nrf54l15/cpuapp")
            self.assertTrue(caps.supports("recording_control"))
            self.assertFalse(caps.supports("gesture"))
            with self.assertRaisesRegex(sdk.CompatibilityError, "Reconnect"):
                await self.discover(refresh=True)
            await self.client.disconnect()
            await self.client.connect()

    async def test_unknown_or_different_customer_build_is_not_inferred_from_order(self):
        self.peer.mode = "silent"
        for version in ("V2.001.0002.9999", LEGACY + "-modified", "V2.001.0003.0001-prod-7fd1dfc9"):
            self.peer.version = version
            caps = await self.discover()
            self.assertEqual(caps.source, "unknown")
            self.assertIn("unknown", caps.reason)
            writes = len(self.peer.writes)
            with self.assertRaises(sdk.CompatibilityError):
                await sdk.start_audio_recording(self.client)
            self.assertEqual(len(self.peer.writes), writes)
            self.assertFalse(self.client._recording_active)
            await self.client.disconnect()
            await self.client.connect()

    async def test_explicit_unknown_opt_in_does_not_override_declared_incompatibility(self):
        self.peer.mode = "silent"
        caps = await self.discover()
        self.client.allow_unverified_features = True
        await self.client.send_command(0x0516)
        self.client.capabilities = replace(caps, source="device")
        with self.assertRaises(sdk.CompatibilityError):
            await self.client.send_command(0x0516)

    async def test_refresh_failure_does_not_leave_stale_capabilities(self):
        await self.discover()
        self.peer.version = "mismatch"
        with self.assertRaises(sdk.ProtocolError):
            await self.discover(refresh=True)
        self.assertIsNone(self.client.capabilities)
        with self.assertRaises(sdk.CompatibilityError):
            await sdk.start_audio_recording(self.client)

    async def test_enhanced_commands_cannot_race_discovery(self):
        async with self.client._capability_lock:
            with self.assertRaisesRegex(sdk.ProtocolError, "discovery"):
                await sdk.start_audio_recording(self.client)
        self.assertEqual(self.peer.writes, [])
        self.assertFalse(self.client._recording_active)

    async def test_absent_gesture_contract_fails_before_waiting_for_event(self):
        await self.discover()
        with self.assertRaises(sdk.CompatibilityError):
            await sdk.wait_sensor_gesture_event(self.client, timeout_s=.01)

    async def test_reconnect_invalidates_capability_cache(self):
        await self.discover()
        await self.client.disconnect()
        self.assertIsNone(self.client.capabilities)
        await self.client.connect()
        self.peer.mode = "silent"
        self.assertEqual((await self.discover()).source, "unknown")

    async def test_mismatched_identity_is_not_legacy_fallback(self):
        self.peer.version = "different"
        with self.assertRaises(sdk.ProtocolError):
            await self.discover()
        self.assertIsNone(self.client.capabilities)

    async def test_connection_change_during_discovery_does_not_cache(self):
        original = self.peer.write
        async def write(data):
            await original(data)
            if sdk.decode_packet(data).command == 0x0105:
                self.client._connection_token = object()
        self.peer.write = write
        with self.assertRaises(sdk.TransportError):
            await self.discover()
        self.assertIsNone(self.client.capabilities)

    async def test_remote_error_is_matched_to_its_request_amid_concurrency(self):
        self.peer.mode = "silent"
        one = asyncio.create_task(self.client.request(0x1010, 0x1011, timeout_s=.3))
        two = asyncio.create_task(self.client.request(0x1020, 0x1021, timeout_s=.3))
        while len(self.peer.writes) < 2:
            await asyncio.sleep(0)
        self.peer.rx(sdk.encode_packet(0x01FF, struct.pack(">HH", 0x1010, 5)))
        self.peer.rx(sdk.encode_packet(0x1021, b"ok"))
        with self.assertRaises(sdk.DeviceError) as error:
            await one
        self.assertEqual(error.exception.error_code, 5)
        self.assertEqual((await two).body, b"ok")
        self.assertEqual(self.client._request_errors, {})

    async def test_cancellation_cleans_pending_errors_and_ignores_late_rejection(self):
        self.peer.mode = "silent"
        operation = asyncio.create_task(self.client.request(0x1010, 0x1011))
        while not self.peer.writes:
            await asyncio.sleep(0)
        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await operation
        self.assertEqual(self.client._request_errors, {})
        self.peer.rx(sdk.encode_packet(0x01FF, struct.pack(">HH", 0x1010, 5)))
        self.peer.mode = "device"
        self.assertEqual((await self.client.request(0x0101, 0x0102)).command, 0x0102)

    async def test_same_command_cannot_have_concurrent_different_response_waiters(self):
        self.peer.mode = "silent"
        one = asyncio.create_task(self.client.request(0x1010, 0x1011))
        while not self.peer.writes:
            await asyncio.sleep(0)
        with self.assertRaisesRegex(sdk.ProtocolError, "ambiguous"):
            await self.client.request(0x1010, 0x1021)
        self.assertEqual(len(self.peer.writes), 1)
        self.peer.rx(sdk.encode_packet(0x1011, b"ok"))
        self.assertEqual((await one).body, b"ok")

    async def test_immediate_error_and_malformed_error_do_not_timeout(self):
        self.peer.mode = "unsupported"
        with self.assertRaises(sdk.DeviceError):
            await self.client.request(0x1010, 0x1011, timeout_s=.1)
        async def malformed(_data):
            self.peer.rx(sdk.encode_packet(0x01FF, b"bad"))
        self.peer.write = malformed
        with self.assertRaises(sdk.ProtocolError):
            await self.client.request(0x1010, 0x1011, timeout_s=.1)

    async def test_non_unsupported_error_is_not_hidden_by_fallback(self):
        original = self.peer.write
        async def write(data):
            if sdk.decode_packet(data).command == 0x0105:
                self.peer.rx(sdk.encode_packet(0x01FF, struct.pack(">HH", 0x0105, 2)))
            else:
                await original(data)
        self.peer.write = write
        with self.assertRaises(sdk.DeviceError) as error:
            await self.discover()
        self.assertEqual(error.exception.error_code, 2)

    async def test_helper_negotiates_and_cleans_up_on_failure(self):
        with mock.patch("openzilo._device.OpenZiloClient", return_value=self.client):
            self.assertIs(await sdk.connect_ring(), self.client)
            self.assertEqual(self.client.capabilities.source, "device")
            self.peer.version = "mismatched"
            with self.assertRaises(sdk.ProtocolError):
                await sdk.connect_ring()
        self.assertFalse(self.client.is_connected)

    async def test_cli_diagnostics_are_json_and_read_only(self):
        for argv in (["device", "capabilities"], ["doctor"]):
            args = cli.build_parser().parse_args([*argv, "--address", "synthetic"])
            with mock.patch.object(cli, "OpenZiloClient", return_value=self.client), mock.patch("builtins.print") as output:
                await args.func(args)
            import json
            result = json.loads(output.call_args.args[0])
            self.assertEqual(result["device"]["source"], "device")
        self.assertTrue(all(p.command in (0x0101, 0x0105) for p in self.peer.writes))

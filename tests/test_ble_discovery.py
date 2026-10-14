# SPDX-License-Identifier: MPL-2.0
import asyncio
import dataclasses
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import openzilo as sdk
from openzilo import _transport as transport
from openzilo import _cli as cli

ADDRESS = "AA:BB:CC:DD:EE:FF"
UUID = transport.NUS_SERVICE_UUID


def device(address=ADDRESS, name=None):
    return NS(address=address, name=name)


def adv(name=None, uuids=(), data=None, rssi=-60):
    return NS(local_name=name, service_uuids=uuids, service_data=data or {}, rssi=rssi)


class Scanner:
    events = []
    instances = []
    fail_start = False

    def __init__(self, detection_callback, **kwargs):
        self.callback = detection_callback
        self.kwargs = kwargs
        self.stopped = False
        self.tasks = []
        self.instances.append(self)

    async def __aenter__(self):
        if self.fail_start:
            raise RuntimeError("adapter unavailable")
        for delay, dev, advertisement in self.events:
            async def emit(delay=delay, dev=dev, advertisement=advertisement):
                await asyncio.sleep(delay)
                self.callback(dev, advertisement)
            self.tasks.append(asyncio.create_task(emit()))
        return self

    async def __aexit__(self, *_args):
        await self.stop()

    async def stop(self):
        self.stopped = True
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


class Link:
    instances = []
    fail_notify = False
    invalid_service = False
    invalid_rx = False
    invalid_tx = False
    hang_connect = False

    def __init__(self, target, **kwargs):
        self.target = target
        self.is_connected = False
        self.order = []
        self.instances.append(self)
        rx = NS(properties=[] if self.invalid_rx else ["write-without-response", "write"])
        tx = NS(properties=[] if self.invalid_tx else ["notify"])
        service = NS(get_characteristic=lambda uuid: rx if uuid == transport.NUS_RX_UUID else tx)
        self.services = NS(get_service=lambda _uuid: None if self.invalid_service else service)

    async def connect(self):
        if self.hang_connect:
            await asyncio.Event().wait()
        self.is_connected = True
        self.order.append("connect")

    async def start_notify(self, _uuid, callback):
        self.callback = callback
        self.order.append("notify")
        if self.fail_notify:
            raise RuntimeError("notify failed")

    async def stop_notify(self, *_args):
        self.order.append("stop_notify")

    async def disconnect(self):
        self.order.append("disconnect")
        self.is_connected = False

    async def write_gatt_char(self, data, *_args, **_kwargs):
        self.order.append("write")


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        Scanner.events = []
        Scanner.instances = []
        Scanner.fail_start = False
        Link.instances = []
        Link.fail_notify = Link.invalid_service = Link.invalid_rx = Link.invalid_tx = Link.hang_connect = False
        self.bleak = patch.dict(sys.modules, {"bleak": NS(BleakScanner=Scanner, BleakClient=Link)})
        self.bleak.start()
        self.addCleanup(self.bleak.stop)

    async def test_nameless_service_immediate_merge_name_rssi_and_service_data(self):
        native = device()
        Scanner.events = [(0, native, adv(uuids=[UUID])),
                          (0.001, device(name="fallback"), adv(name="Open Zilo-test", rssi=-40)),
                          (0.002, device(), adv(rssi=-50))]
        snapshots = []
        results = await sdk.scan_rings(timeout_s=0.02, on_devices_changed=snapshots.append)
        self.assertIsNone(snapshots[0][0].name)
        self.assertTrue(snapshots[0][0].matched_service)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Open Zilo-test")
        self.assertEqual(results[0].rssi, -50)
        self.assertIn(UUID.lower(), results[0].service_uuids)
        self.assertEqual(len(snapshots), 2)  # immediate then final, throttled updates
        self.assertEqual(Scanner.instances[0].kwargs, {"scanning_mode": "active"})
        self.assertTrue(Scanner.instances[0].stopped)
        self.assertNotIn("_native_device", dataclasses.asdict(results[0]))
        self.assertNotIn("_native_device", repr(results[0]))

    async def test_name_rules_service_data_and_sorting(self):
        names = [" ring ", "OPEN ZILO", "prefix Open Zilo-abc", "earring", "ringing", "Open Zilo- "]
        Scanner.events = [(0, device(str(i)), adv(name=n)) for i,n in enumerate(names)]
        Scanner.events += [(0, device("service"), adv(data={UUID: b""}, rssi=-90))]
        results = await sdk.scan_rings(timeout_s=0.01)
        self.assertEqual(len(results), 4)
        self.assertEqual(results[0].address, "service")

    async def test_known_address_early_without_candidate_metadata(self):
        Scanner.events = [(0, device(), adv())]
        start = asyncio.get_running_loop().time()
        results = await sdk.scan_rings(address="aa-bb-cc-dd-ee-ff", timeout_s=10)
        self.assertLess(asyncio.get_running_loop().time()-start, 1)
        self.assertEqual(results[0].address, ADDRESS)
        self.assertTrue(Scanner.instances[0].stopped)

    async def test_macos_identifier(self):
        address = "12345678-1234-1234-1234-123456789012"
        Scanner.events = [(0, device(address), adv())]
        self.assertEqual((await sdk.scan_rings(address=address, timeout_s=0.02))[0].address, address)

    async def test_timeout_does_not_implicitly_connect(self):
        ring = sdk.NusClient(address=ADDRESS, scan_timeout_s=0.01)
        with self.assertRaisesRegex(sdk.TransportError, "SCANNING.*timeout"):
            await ring.connect()
        self.assertEqual(Link.instances, [])

    async def test_callback_failure_does_not_leak_scanner(self):
        Scanner.events = [(0, device(), adv(uuids=[UUID]))]
        def broken(_devices):
            raise RuntimeError("UI failure")
        with self.assertLogs("openzilo", "ERROR"):
            await sdk.scan_rings(timeout_s=0.01, on_devices_changed=broken)
        self.assertTrue(Scanner.instances[0].stopped)

    async def test_cancel_final_snapshot_old_callback_and_duplicate_scan(self):
        snapshots = []
        task = asyncio.create_task(sdk.scan_rings(timeout_s=10, on_devices_changed=snapshots.append))
        await asyncio.sleep(0)
        with self.assertRaisesRegex(sdk.TransportError, "another SDK scan"):
            await sdk.scan_rings(timeout_s=0.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        old = Scanner.instances[0]
        self.assertTrue(old.stopped)
        old.callback(device(), adv(uuids=[UUID]))
        self.assertEqual(snapshots, [[]])
        self.assertEqual(await sdk.scan_rings(timeout_s=0.01), [])

    async def test_start_failure_cleanup_and_next_session(self):
        Scanner.fail_start = True
        with self.assertRaisesRegex(sdk.TransportError, "SCANNING.*adapter"):
            await sdk.scan_rings(timeout_s=0.01)
        self.assertTrue(Scanner.instances[0].stopped)
        Scanner.fail_start = False
        self.assertEqual(await sdk.scan_rings(timeout_s=0.01), [])

    async def test_object_reuse_readiness_and_reconnect_rescans(self):
        native = device()
        selected = sdk.BleDeviceInfo(None, ADDRESS, _native_device=native)
        ring = sdk.NusClient(device=selected)
        with patch.object(transport, "DEFAULT_CONNECTION_STABILIZATION_S", 0.02):
            task = asyncio.create_task(ring.connect())
            while not ring._notify_started:
                await asyncio.sleep(0)
            with self.assertRaisesRegex(sdk.TransportError, "not ready"):
                await ring.write(b"command")
            await task
            self.assertIs(Link.instances[0].target, native)
            self.assertEqual(Scanner.instances, [])
            self.assertEqual(Link.instances[0].order, ["connect", "notify"])
            await ring.write(b"command")
            await ring.disconnect()
            Scanner.events = [(0, device(), adv())]
            await ring.connect()
            self.assertEqual(len(Scanner.instances), 1)
            await ring.disconnect()

    async def test_notify_failure_cleans_up_with_stage(self):
        Link.fail_notify = True
        ring = sdk.NusClient(device=sdk.BleDeviceInfo(None, ADDRESS, _native_device=device()))
        with self.assertRaisesRegex(sdk.TransportError, "SUBSCRIBING"):
            await ring.connect()
        self.assertIn("disconnect", Link.instances[0].order)
        self.assertIsNone(ring._client)

    async def test_nus_validation(self):
        for attribute in ["invalid_service", "invalid_rx", "invalid_tx"]:
            with self.subTest(attribute=attribute):
                setattr(Link, attribute, True)
                ring = sdk.NusClient(device=sdk.BleDeviceInfo(None, ADDRESS, _native_device=device()))
                with self.assertRaisesRegex(sdk.TransportError, "CONNECTING.*NUS"):
                    await ring.connect()
                self.assertFalse(Link.instances[-1].is_connected)
                setattr(Link, attribute, False)

    async def test_cancel_during_stabilization_cleans_notifications(self):
        ring = sdk.NusClient(device=sdk.BleDeviceInfo(None, ADDRESS, _native_device=device()))
        task = asyncio.create_task(ring.connect())
        while not ring._notify_started:
            await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(Link.instances[0].order[-2:], ["stop_notify", "disconnect"])
        self.assertFalse(ring.is_connected)

    async def test_stabilization_disconnect_is_failure(self):
        ring = sdk.NusClient(device=sdk.BleDeviceInfo(None, ADDRESS, _native_device=device()))
        with patch.object(transport, "DEFAULT_CONNECTION_STABILIZATION_S", 0.01):
            task = asyncio.create_task(ring.connect())
            while not ring._notify_started:
                await asyncio.sleep(0)
            Link.instances[0].is_connected = False
            with self.assertRaisesRegex(sdk.TransportError, "STABILIZING"):
                await task
        self.assertIsNone(ring._client)

    async def test_connect_timeout_and_missing_target(self):
        Link.hang_connect = True
        ring = sdk.NusClient(device=sdk.BleDeviceInfo(None, ADDRESS, _native_device=device()), connect_timeout_s=0.01)
        with self.assertRaisesRegex(sdk.TransportError, "CONNECTING"):
            await ring.connect()
        with self.assertRaisesRegex(sdk.TransportError, "identifier"):
            await sdk.connect_ring()
        with self.assertRaises(ValueError):
            sdk.OpenZiloClient(address="other", device=sdk.BleDeviceInfo(None, ADDRESS))

    async def test_custom_transport_bypasses_ble_arguments(self):
        custom = NS(connect=AsyncMock(), set_rx_callback=lambda cb: None, is_connected=True)
        ring = sdk.OpenZiloClient(transport=custom, address="other", device=sdk.BleDeviceInfo(None, ADDRESS))
        await ring.connect()
        custom.connect.assert_awaited_once()
        self.assertEqual(Scanner.instances, [])

    async def test_helper_and_cli_parameters(self):
        Scanner.events = [(0, device(), adv())]
        with patch.object(transport, "DEFAULT_CONNECTION_STABILIZATION_S", 0):
            ring = await sdk.connect_ring(address=ADDRESS, scan_timeout_s=0.05, connect_timeout_s=0.1)
        self.assertEqual(ring.transport.scan_timeout_s, 0.05)
        await ring.disconnect()
        args = cli.build_parser().parse_args(["connect", "--address", ADDRESS, "--scan-timeout", "12"])
        self.assertEqual(args.scan_timeout, 12)
        self.assertEqual(cli.build_parser().parse_args(["scan"]).timeout, 30)

    async def test_timeouts_reject_invalid_values(self):
        for value in [0, -1, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                await sdk.scan_rings(timeout_s=value)

    async def test_object_connection_requires_scan_cleanup_first(self):
        scan = asyncio.create_task(sdk.scan_rings(timeout_s=10))
        await asyncio.sleep(0)
        ring = sdk.NusClient(device=sdk.BleDeviceInfo(None, ADDRESS, _native_device=device()))
        try:
            with self.assertRaisesRegex(sdk.TransportError, "cancel and await"):
                await ring.connect()
            self.assertEqual(Link.instances, [])
        finally:
            scan.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await scan
        with patch.object(transport, "DEFAULT_CONNECTION_STABILIZATION_S", 0):
            await ring.connect()
        await ring.disconnect()

    async def test_cached_device_from_other_loop_is_rediscovered(self):
        selected = sdk.BleDeviceInfo(None, ADDRESS, _native_device=device())
        object.__setattr__(selected, "_native_loop", object())
        fresh = device()
        Scanner.events = [(0, fresh, adv())]
        with patch.object(transport, "DEFAULT_CONNECTION_STABILIZATION_S", 0):
            ring = await sdk.connect_ring(device=selected)
        self.assertIs(Link.instances[0].target, fresh)
        self.assertEqual(len(Scanner.instances), 1)
        await ring.disconnect()

    async def test_stale_disconnect_does_not_clear_new_connection(self):
        ring = sdk.NusClient(device=sdk.BleDeviceInfo(None, ADDRESS, _native_device=device()))
        with patch.object(transport, "DEFAULT_CONNECTION_STABILIZATION_S", 0):
            await ring.connect()
        ring._handle_disconnect(object())
        self.assertTrue(ring._ready)
        await ring.disconnect()

    async def test_old_notifications_cannot_reach_reconnected_session(self):
        ring = sdk.NusClient(device=sdk.BleDeviceInfo(None, ADDRESS, _native_device=device()))
        seen = []
        ring.set_rx_callback(seen.append)
        with patch.object(transport, "DEFAULT_CONNECTION_STABILIZATION_S", 0):
            await ring.connect()
            old = Link.instances[0]
            await ring.disconnect()
            Scanner.events = [(0, device(), adv())]
            await ring.connect()
        old.callback(None, bytearray(b"stale"))
        Link.instances[-1].callback(None, bytearray(b"current"))
        self.assertEqual(seen, [b"current"])
        await ring.disconnect()

# SPDX-License-Identifier: MPL-2.0
"""Automatic time replies across connection setup, failure and reconnection."""

import asyncio
import struct
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import openzilo as sdk
from openzilo import _transport


class GatedTransport:
    def __init__(self):
        self.is_connected = False
        self.ready = False
        self.writes = []
        self.disconnected = lambda: None
        self.reset_gate()

    def reset_gate(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.fail = False

    def set_rx_callback(self, callback):
        self.receive = callback

    def _set_disconnect_callback(self, callback):
        self.disconnected = callback

    async def connect(self):
        self.is_connected = True
        self.ready = False
        self.started.set()
        try:
            await self.release.wait()
            if self.fail:
                raise sdk.TransportError("connection setup failed")
            self.ready = True
        except BaseException:
            self.is_connected = False
            raise

    async def disconnect(self):
        self.ready = self.is_connected = False
        self.disconnected()

    async def write(self, data):
        if not self.ready:
            raise sdk.TransportError("BLE client is not ready")
        self.writes.append(sdk.decode_packet(data))

    def request_time(self, value):
        self.receive(sdk.encode_packet(0x0401, struct.pack(">I", value)))


class TimeSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.transport = GatedTransport()
        self.client = sdk.OpenZiloClient(transport=self.transport)
        self.now = 1000
        self.clock = mock.patch("openzilo._device.time.time", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.addAsyncCleanup(self.client.disconnect)

    async def connect(self):
        self.transport.release.set()
        await self.client.connect()

    async def flush(self):
        await asyncio.wait_for(asyncio.gather(*[
            task for task in self.client._callback_tasks if not task.cancelled()
        ]), 1)

    def reply(self, index=-1):
        packet = self.transport.writes[index]
        self.assertEqual(packet.command, 0x0402)
        return struct.unpack(">III", packet.body)

    async def test_request_during_setup_waits_and_preserves_receive_time(self):
        sdk.enable_time_sync(self.client)
        connecting = asyncio.create_task(self.client.connect())
        await self.transport.started.wait()
        self.transport.request_time(42)
        await asyncio.sleep(0)
        self.assertEqual(self.transport.writes, [])
        self.now = 1003
        self.transport.release.set()
        await connecting
        await self.flush()
        self.assertEqual(self.reply(), (42, 1000, 1003))

    async def test_send_timestamp_is_taken_after_waiting_for_write_lock(self):
        await self.connect()
        sdk.enable_time_sync(self.client)
        async with self.client._write_lock:
            self.transport.request_time(43)
            await asyncio.sleep(0)
            self.now = 1007
            self.assertEqual(self.transport.writes, [])
        await self.flush()
        self.assertEqual(self.reply(), (43, 1000, 1007))

    async def test_reconnect_waits_again_and_enable_is_idempotent(self):
        await self.connect()
        sdk.enable_time_sync(self.client)
        sdk.enable_time_sync(self.client)
        self.transport.request_time(1)
        await self.flush()
        self.assertEqual(len(self.transport.writes), 1)
        await self.client.disconnect()
        self.transport.reset_gate()
        connecting = asyncio.create_task(self.client.connect())
        await self.transport.started.wait()
        sdk.enable_time_sync(self.client)
        self.transport.request_time(2)
        await asyncio.sleep(0)
        self.assertEqual(len(self.transport.writes), 1)
        self.transport.release.set()
        await connecting
        await self.flush()
        self.assertEqual(len(self.transport.writes), 2)
        self.assertEqual(self.reply()[0], 2)

    async def test_failed_setup_cancels_reply_and_does_not_replay_on_reconnect(self):
        sdk.enable_time_sync(self.client)
        connecting = asyncio.create_task(self.client.connect())
        await self.transport.started.wait()
        self.transport.request_time(10)
        pending = list(self.client._callback_tasks)
        self.transport.fail = True
        self.transport.release.set()
        with self.assertRaisesRegex(sdk.TransportError, "setup failed"):
            await connecting
        await asyncio.gather(*pending, return_exceptions=True)
        self.assertTrue(all(task.cancelled() for task in pending))
        self.transport.reset_gate()
        await self.connect()
        self.assertEqual(self.transport.writes, [])
        self.transport.request_time(11)
        await self.flush()
        self.assertEqual(self.reply()[0], 11)

    async def test_cancelled_setup_cancels_waiting_reply(self):
        sdk.enable_time_sync(self.client)
        connecting = asyncio.create_task(self.client.connect())
        await self.transport.started.wait()
        self.transport.request_time(12)
        pending = list(self.client._callback_tasks)
        connecting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await connecting
        await asyncio.gather(*pending, return_exceptions=True)
        self.assertTrue(all(task.cancelled() for task in pending))
        self.assertEqual(self.transport.writes, [])

    async def test_disconnect_drops_queued_reply_without_poisoning_new_connection(self):
        await self.connect()
        sdk.enable_time_sync(self.client)
        async with self.client._write_lock:
            self.transport.request_time(20)
            await asyncio.sleep(0)
            pending = list(self.client._callback_tasks)
            await self.client.disconnect()
            self.transport.reset_gate()
            await self.connect()
        await asyncio.gather(*pending, return_exceptions=True)
        self.assertEqual(self.transport.writes, [])
        self.transport.request_time(21)
        await self.flush()
        self.assertEqual(self.reply()[0], 21)
        self.assertFalse(self.client._write_interrupted)

    async def test_expired_connection_is_checked_after_write_lock(self):
        await self.connect()
        old_connection = self.client._connection_token
        async with self.client._write_lock:
            reply = asyncio.create_task(self.client._send_when_ready(
                0x0402, lambda: struct.pack(">III", 30, 1000, 1000), old_connection,
            ))
            await asyncio.sleep(0)
            # This task is not in the client's owned callbacks; even without
            # cancellation the connection guard must reject its stale reply.
            await self.client.disconnect()
            self.transport.reset_gate()
            await self.connect()
        await reply
        self.assertEqual(self.transport.writes, [])

    async def test_manual_reply_remains_immediate_and_preserves_explicit_times(self):
        await self.connect()
        await sdk.send_time_response(self.client, 40, response_time=2000, send_time=2001)
        self.assertEqual(self.reply(), (40, 2000, 2001))

    async def test_cancelled_old_write_cannot_mark_new_connection_interrupted(self):
        await self.connect()
        sdk.enable_time_sync(self.client)
        writing, cancelling, finish_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original_write = self.transport.write

        async def delayed_write(_data):
            writing.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelling.set()
                await finish_cleanup.wait()
                raise

        self.transport.write = delayed_write
        self.transport.request_time(45)
        await writing.wait()
        old_tasks = list(self.client._callback_tasks)
        self.transport.is_connected = False
        self.transport.disconnected()
        await cancelling.wait()
        self.transport.reset_gate()
        await self.connect()
        finish_cleanup.set()
        await asyncio.gather(*old_tasks, return_exceptions=True)
        self.assertFalse(self.client._write_interrupted)
        self.transport.write = original_write
        await sdk.send_time_response(self.client, 46)
        self.assertEqual(self.reply()[0], 46)

    async def test_connect_helper_registers_before_early_notification(self):
        with mock.patch("openzilo._device.OpenZiloClient", return_value=self.client):
            connecting = asyncio.create_task(sdk.connect_ring(auto_time_sync=True, negotiate_capabilities=False))
            await self.transport.started.wait()
            self.transport.request_time(50)
            self.transport.release.set()
            self.assertIs(await connecting, self.client)
        await self.flush()
        self.assertEqual(self.reply()[0], 50)

    async def test_disconnect_during_setup_never_marks_connection_ready(self):
        sdk.enable_time_sync(self.client)
        connecting = asyncio.create_task(self.client.connect())
        await self.transport.started.wait()
        self.transport.request_time(51)
        pending = list(self.client._callback_tasks)
        self.transport.disconnected()
        self.transport.release.set()
        with self.assertRaisesRegex(sdk.TransportError, "before the connection became ready"):
            await connecting
        await asyncio.gather(*pending, return_exceptions=True)
        self.assertFalse(self.client._connection_ready.is_set())
        self.assertEqual(self.transport.writes, [])

    async def test_real_nus_setup_handles_immediate_notification_without_background_error(self):
        replies = []
        stream = sdk.PacketStream()

        class EarlyLink:
            def __init__(self, _device, *, disconnected_callback, **_kwargs):
                self.is_connected = False
                self.disconnected_callback = disconnected_callback
                service = SimpleNamespace(get_characteristic=lambda uuid: SimpleNamespace(
                    properties=["notify"] if uuid == _transport.NUS_TX_UUID else ["write-without-response"],
                ))
                self.services = SimpleNamespace(get_service=lambda _uuid: service)

            async def connect(self):
                self.is_connected = True

            async def start_notify(self, _uuid, callback):
                callback(None, bytearray(sdk.encode_packet(0x0401, struct.pack(">I", 60))))
                await asyncio.sleep(0)

            async def write_gatt_char(self, _uuid, data, **_kwargs):
                replies.extend(stream.feed(data))

            async def stop_notify(self, _uuid):
                pass

            async def disconnect(self):
                self.is_connected = False
                self.disconnected_callback(self)

        device = sdk.BleDeviceInfo("synthetic", "synthetic-device", _native_device=object())
        client = sdk.OpenZiloClient(device=device)
        sdk.enable_time_sync(client)
        with mock.patch.dict(sys.modules, {"bleak": SimpleNamespace(BleakClient=EarlyLink)}), \
                mock.patch.object(_transport, "DEFAULT_CONNECTION_STABILIZATION_S", .01), \
                self.assertNoLogs("openzilo", level="ERROR"):
            async with client:
                await asyncio.wait_for(asyncio.gather(*list(client._callback_tasks)), 1)
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0].command, 0x0402)
        self.assertEqual(struct.unpack(">III", replies[0].body), (60, 1000, 1000))

# SPDX-License-Identifier: MPL-2.0
import asyncio
import struct
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import openzilo as sdk
from openzilo import _cli as cli


class ProtocolTests(unittest.TestCase):
    def test_packet_encode_decode_round_trip(self) -> None:
        encoded = sdk.encode_packet(0x1234, b"payload")
        packet = sdk.decode_packet(encoded)
        self.assertEqual((packet.command, packet.body), (0x1234, b"payload"))
        self.assertEqual(packet.body_crc, sdk.crc16_compute(b"payload"))

    def test_packet_stream_reconstructs_fragmented_packet(self) -> None:
        encoded = sdk.encode_packet(0x0505, b"fragmented")
        stream = sdk.PacketStream()
        self.assertEqual(stream.feed(encoded[:3]), [])
        self.assertEqual(stream.feed(encoded[3:9]), [])
        packets = stream.feed(encoded[9:])
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].body, b"fragmented")

    def test_binary_reader_writer_round_trip(self) -> None:
        data = sdk.BinaryWriter().u8(1).u16(0x0203).i16(-4).u32(5).bytes(b"x").build()
        reader = sdk.BinaryReader(data)
        self.assertEqual(reader.u8(), 1)
        self.assertEqual(reader.u16(), 0x0203)
        self.assertEqual(reader.i16(), -4)
        self.assertEqual(reader.u32(), 5)
        self.assertEqual(reader.bytes(1), b"x")
        self.assertEqual(reader.remaining, 0)

    def test_crc_rejects_tampered_packet(self) -> None:
        encoded = bytearray(sdk.encode_packet(0x1234, b"payload"))
        encoded[-1] ^= 0xFF
        with self.assertRaises(sdk.ProtocolError):
            sdk.decode_packet(encoded)


class AudioTests(unittest.TestCase):
    def test_wav_header_and_pcm_output(self) -> None:
        pcm = b"\x00\x00\x01\x00"
        wav = sdk.build_wav_from_pcm(pcm)
        self.assertTrue(sdk.is_wav(wav))
        self.assertEqual(len(wav), 44 + len(pcm))
        self.assertEqual(wav[44:], pcm)
        self.assertEqual(struct.unpack_from("<I", wav, 40)[0], len(pcm))


class CliSafetyTests(unittest.TestCase):
    def test_audio_clear_requires_yes_before_ble(self) -> None:
        args = SimpleNamespace(yes=False, address="AA:BB:CC:DD:EE:FF")
        with self.assertRaisesRegex(SystemExit, "without --yes"):
            asyncio.run(cli.cmd_audio_clear(args))


class CompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def test_single_and_batch_imu_have_the_same_sample_values(self):
        sample = struct.pack(">I6h", 1000, -32768, -2, 3, 4, 5, 32767)
        single = sdk.parse_sensor_data_batch(struct.pack(">HI", 0, 42) + sample)
        batch = sdk.parse_sensor_data_batch(struct.pack(">HIHH", 0, 42, 1, 16) + sample)
        self.assertEqual(single, batch)
        self.assertEqual(single.samples[0].timestamp_ms, 1000)
        self.assertEqual(single.samples[0].accel_x, -32768)

    async def test_same_response_requests_cannot_clear_each_others_packets(self):
        writes = []
        first_write, second_write = asyncio.Event(), asyncio.Event()

        async def write(data):
            writes.append(sdk.decode_packet(data))
            (first_write if len(writes) == 1 else second_write).set()

        client = sdk.OpenZiloClient(transport=SimpleNamespace(is_connected=True, write=write))
        client._disconnected.clear()
        first = asyncio.create_task(client.request(0x0101, 0x0102))
        await asyncio.wait_for(first_write.wait(), 1)
        second = asyncio.create_task(client.request(0x0101, 0x0102))
        await asyncio.sleep(0)
        self.assertEqual(len(writes), 1)
        client._on_rx(sdk.encode_packet(0x0102, b"first"))
        self.assertEqual((await first).body, b"first")
        await asyncio.wait_for(second_write.wait(), 1)
        client._on_rx(sdk.encode_packet(0x0102, b"second"))
        self.assertEqual((await second).body, b"second")

    async def test_request_timeout_covers_a_hung_write(self):
        async def write(_data):
            await asyncio.Event().wait()

        client = sdk.OpenZiloClient(transport=SimpleNamespace(is_connected=True, write=write))
        client._disconnected.clear()
        with self.assertRaises(sdk.TimeoutError):
            await asyncio.wait_for(client.request(0x0101, 0x0102, timeout_s=0.02), 1)
        with self.assertRaisesRegex(sdk.TransportError, "interrupted"):
            await client.send_command(0x0101)

    async def test_failing_handler_does_not_drop_later_packets(self):
        client = sdk.OpenZiloClient()
        seen = []

        def broken(_packet):
            raise RuntimeError("application callback failed")

        client.add_packet_handler(0x0701, broken)
        client.add_packet_handler(0x0703, lambda packet: seen.append(packet.command))
        with self.assertLogs("openzilo", "ERROR"):
            client._on_rx(sdk.encode_packet(0x0701, b"") + sdk.encode_packet(0x0703, b""))
        self.assertEqual(seen, [0x0703])

    async def test_notify_failure_disconnects_the_new_ble_link(self):
        links = []

        class FakeBleakClient:
            def __init__(self, *_args, **_kwargs):
                self.disconnected = False
                self.is_connected = True
                service = SimpleNamespace(get_characteristic=lambda uuid: SimpleNamespace(
                    properties=["write-without-response", "notify"]))
                self.services = SimpleNamespace(get_service=lambda uuid: service)
                links.append(self)

            async def connect(self):
                pass

            async def start_notify(self, *_args):
                raise RuntimeError("notify failed")

            async def disconnect(self):
                self.disconnected = True

        fake_bleak = SimpleNamespace(BleakClient=FakeBleakClient)
        with mock.patch.dict(sys.modules, {"bleak": fake_bleak}):
            transport = sdk.NusClient(device=sdk.BleDeviceInfo(
                None, "00:00:00:00:00:01", _native_device=object()))
            with self.assertRaises(sdk.TransportError):
                await transport.connect()
        self.assertTrue(links[0].disconnected)
        self.assertIsNone(transport._client)

    async def test_callback_only_delivery_and_queue_overflow_are_explicit(self):
        client = sdk.OpenZiloClient(receive_queue_size=2)
        client._disconnected.clear()
        received = []
        handler = received.append
        client.add_packet_handler(0x0605, handler, queue_packets=False)
        packet = sdk.encode_packet(0x0605, b"sample")
        for _ in range(100):
            client._on_rx(packet)
        self.assertEqual(len(received), 100)
        self.assertTrue(client._queues[0x0605].empty())
        with self.assertRaisesRegex(sdk.ProtocolError, "callback-only"):
            await client.wait_for_command(0x0605)
        client.remove_packet_handler(0x0605, handler)
        for _ in range(3):
            client._on_rx(packet)
        self.assertLessEqual(client._queues[0x0605].qsize(), 2)
        with self.assertRaisesRegex(sdk.ProtocolError, "overflow"):
            await client.wait_for_command(0x0605)

    async def test_cancelled_download_closes_session_and_rejects_competing_operations(self):
        commands = []
        reading = asyncio.Event()

        async def write(data):
            packet = sdk.decode_packet(data)
            commands.append(packet.command)
            if packet.command == 0x0503:
                client._on_rx(sdk.encode_packet(0x0504, struct.pack(">HIII", 0, 7, 0, 16)))
            elif packet.command == 0x0506:
                reading.set()
            elif packet.command == 0x0507:
                client._on_rx(sdk.encode_packet(0x0508, struct.pack(">HI", 0, 7)))

        client = sdk.OpenZiloClient(transport=SimpleNamespace(is_connected=True, write=write))
        client._disconnected.clear()
        download = asyncio.create_task(sdk.download_audio_file(client, 7, quick=False))
        await asyncio.wait_for(reading.wait(), 1)
        with self.assertRaisesRegex(sdk.ProtocolError, "audio operation"):
            await sdk.receive_auto_audio_file(client)
        with self.assertRaisesRegex(sdk.ProtocolError, "active audio"):
            await sdk.update_firmware(client, b"synthetic", version="V2.001.0002.0000")
        download.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(download, 1)
        self.assertEqual(commands, [0x0503, 0x0506, 0x0507])
        self.assertIsNone(client._audio_owner)

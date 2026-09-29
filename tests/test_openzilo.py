# SPDX-License-Identifier: MPL-2.0
import asyncio
import struct
import unittest
from types import SimpleNamespace

import openzilo as sdk


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
            asyncio.run(sdk.cmd_audio_clear(args))

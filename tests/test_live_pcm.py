# SPDX-License-Identifier: MPL-2.0
"""Stream lifecycle and incremental decoding using synthetic audio only."""

import asyncio
import importlib.util
import math
import shutil
import struct
import unittest
from fractions import Fraction
from unittest import mock

import openzilo as sdk
from test_audio_stream import AudioPeer, OPUS

HAS_AV = importlib.util.find_spec("av") is not None


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_opus_stream_orders_metadata_frames_and_end(self):
        peer = AudioPeer()
        async with sdk.open_live_audio_stream(peer.client, output="opus", timeout_s=1) as stream:
            events = [event async for event in stream]
            self.assertIsInstance(events[0], sdk.LiveAudioStart)
            self.assertEqual([e.sequence for e in events[1:-1]], [0, 1, 2])
            self.assertIsInstance(events[-1], sdk.LiveAudioEnd)
            self.assertTrue(stream.complete)
            self.assertIs(stream.end, events[-1])
        self.assertFalse(peer.client._live_audio_subscribed)
        self.assertIsNone(peer.client._audio_owner)
        self.assertFalse(peer.client._callback_only)

    async def test_early_exit_releases_subscription_and_ownership(self):
        peer = AudioPeer("cancel")
        async with sdk.open_live_audio_stream(peer.client, output="opus", timeout_s=1) as stream:
            async for event in stream:
                self.assertIsInstance(event, sdk.LiveAudioStart)
                break
        self.assertFalse(stream.complete)
        self.assertEqual(peer.commands[-1], (0x050D, b"\x00"))
        self.assertIsNone(peer.client._audio_owner)
        self.assertFalse(peer.client._callback_only)
        with self.assertRaises(sdk.ProtocolError):
            await anext(stream)

    async def test_cancellation_during_iteration_is_preserved(self):
        peer = AudioPeer("cancel")
        entered = asyncio.Event()

        async def consume():
            async with sdk.open_live_audio_stream(peer.client, output="opus", timeout_s=1) as stream:
                entered.set()
                async for _ in stream:
                    pass

        task = asyncio.create_task(consume())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(peer.client._live_audio_subscribed)
        self.assertIsNone(peer.client._audio_owner)
        self.assertFalse(peer.client._callback_only)

    async def test_cancel_during_subscription_cleans_up_before_entry_returns(self):
        peer = AudioPeer("cancel")
        enabling = asyncio.Event()
        write = peer.write

        async def delayed_write(data):
            packet = sdk.decode_packet(data)
            if packet.command == 0x050D and packet.body == b"\x01":
                enabling.set()
                # Write finished, but firmware has not acknowledged subscribe.
                return
            await write(data)

        peer.write = delayed_write

        async def consume():
            async with sdk.open_live_audio_stream(peer.client, output="opus", timeout_s=1):
                self.fail("subscription has not been acknowledged")

        task = asyncio.create_task(consume())
        await enabling.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(peer.client._live_audio_subscribed)
        self.assertIsNone(peer.client._audio_owner)
        self.assertFalse(peer.client._callback_only)

    async def test_failed_streams_never_emit_successful_end(self):
        for fault, error in (("gap", sdk.ProtocolError), ("length", sdk.ProtocolError),
                             ("session", sdk.ProtocolError), ("device", sdk.DeviceError),
                             ("mtu", sdk.DeviceError), ("disconnect", sdk.TransportError),
                             ("overflow", sdk.ProtocolError)):
            peer = AudioPeer(fault)
            events = []
            with self.subTest(fault=fault), self.assertRaises(error):
                async with sdk.open_live_audio_stream(peer.client, output="opus", timeout_s=0.1) as stream:
                    async for event in stream:
                        events.append(event)
            self.assertFalse(any(isinstance(e, sdk.LiveAudioEnd) for e in events))
            self.assertIsNone(peer.client._audio_owner)
            self.assertFalse(peer.client._callback_only)

    async def test_slow_consumer_fails_instead_of_losing_frames(self):
        peer = AudioPeer()
        with self.assertRaisesRegex(sdk.ProtocolError, "consumer queue overflow"):
            async with sdk.open_live_audio_stream(peer.client, output="opus", queue_size=2,
                                                  timeout_s=1) as stream:
                # Wait for the producer, without consuming, so Windows timer
                # granularity cannot let the consumer drain the queue early.
                await asyncio.wait_for(stream._done.wait(), timeout=2)
                async for _ in stream:
                    pass
        self.assertFalse(stream.complete)
        self.assertFalse(peer.client._live_audio_subscribed)

    async def test_competing_audio_operation_is_rejected(self):
        peer = AudioPeer("cancel")
        async with sdk.open_live_audio_stream(peer.client, output="opus", timeout_s=1):
            with self.assertRaises(sdk.ProtocolError):
                await sdk.download_audio_file(peer.client, 4)
            with self.assertRaises(sdk.ProtocolError):
                async with sdk.open_live_audio_stream(peer.client, output="opus", timeout_s=1):
                    pass
            self.assertTrue(peer.client._live_audio_subscribed)

    async def test_missing_pcm_dependency_does_not_subscribe(self):
        peer = AudioPeer()
        with mock.patch.dict("sys.modules", {"av": None}):
            with self.assertRaises(sdk.OpusDecoderUnavailable):
                async with sdk.open_live_audio_stream(peer.client, timeout_s=1):
                    pass
        self.assertEqual(peer.commands, [])
        self.assertIsNone(peer.client._audio_owner)

    async def test_timeout_and_single_consumer(self):
        peer = AudioPeer("cancel")
        with self.assertRaises(sdk.TimeoutError):
            async with sdk.open_live_audio_stream(peer.client, output="opus", timeout_s=1,
                                                  recording_timeout_s=0.05) as stream:
                await anext(stream)
                waiter = asyncio.create_task(anext(stream))
                await asyncio.sleep(0)
                with self.assertRaises(sdk.ProtocolError):
                    await anext(stream)
                await waiter
        self.assertFalse(peer.client._live_audio_subscribed)

    async def test_unsubscribe_finishes_after_end_before_exit(self):
        peer = AudioPeer()
        write = peer.write
        disabled = asyncio.Event()

        async def delayed_write(data):
            if sdk.decode_packet(data).body == b"\x00":
                await asyncio.sleep(0.02)
                disabled.set()
            await write(data)

        peer.write = delayed_write
        async with sdk.open_live_audio_stream(peer.client, output="opus", timeout_s=1) as stream:
            async for _ in stream:
                pass
        self.assertTrue(disabled.is_set())
        self.assertFalse(peer.client._live_audio_subscribed)


@unittest.skipUnless(HAS_AV, "install the optional pcm extra")
class PcmTests(unittest.IsolatedAsyncioTestCase):
    async def test_pcm_arrives_before_end_and_flush_preserves_length(self):
        peer = AudioPeer("cancel")
        async with sdk.open_live_audio_stream(peer.client, timeout_s=1) as stream:
            self.assertIsInstance(await anext(stream), sdk.LiveAudioStart)
            for i in range(2):
                peer.emit((0x0510, struct.pack(">IIIH", 7, i, i * 3, 3) + OPUS))
            first = await asyncio.wait_for(anext(stream), 1)
            self.assertIsInstance(first, sdk.LivePcmFrame)
            self.assertEqual((first.sample_offset, first.sample_count, len(first.data)), (0, 320, 1280))
            self.assertEqual(first.pcm_config, sdk.PcmConfig(16000, 2, 16))
            self.assertIsNone(stream.end)
            peer.emit((0x0511, struct.pack(">HIIIII", 0, 7, 0, 6, 6, 0)))
            tail = [e async for e in stream]
            self.assertEqual(tail[0].sample_offset, 320)
            self.assertEqual(len(first.data) + len(tail[0].data), 2 * 320 * 4)
            self.assertIsInstance(tail[-1], sdk.LiveAudioEnd)
            self.assertTrue(stream.complete)

    async def test_partial_pcm_is_not_success_when_end_reports_loss(self):
        peer = AudioPeer("cancel")
        with self.assertRaises(sdk.ProtocolError):
            async with sdk.open_live_audio_stream(peer.client, timeout_s=1) as stream:
                await anext(stream)
                for i in range(2):
                    peer.emit((0x0510, struct.pack(">IIIH", 7, i, i * 3, 3) + OPUS))
                self.assertIsInstance(await anext(stream), sdk.LivePcmFrame)
                peer.emit((0x0511, struct.pack(">HIIIII", 0, 7, 0, 6, 6, 1)))
                async for _ in stream:
                    pass
        self.assertFalse(stream.complete)
        self.assertIsNone(stream.end)
        self.assertFalse(peer.client._live_audio_subscribed)

    async def test_empty_recording_has_no_pcm_frames(self):
        peer = AudioPeer("cancel")
        async with sdk.open_live_audio_stream(peer.client, timeout_s=1) as stream:
            self.assertIsInstance(await anext(stream), sdk.LiveAudioStart)
            peer.emit((0x0511, struct.pack(">HIIIII", 0, 7, 0, 0, 0, 0)))
            events = [e async for e in stream]
            self.assertEqual(len(events), 1)
            self.assertIsInstance(events[0], sdk.LiveAudioEnd)
            self.assertTrue(stream.complete)

    async def test_decode_error_releases_live_subscription(self):
        peer = AudioPeer()
        with mock.patch("openzilo._pcm._OpusPcmDecoder.decode", side_effect=sdk.AudioDecodeError("bad audio")):
            with self.assertRaises(sdk.AudioDecodeError):
                async with sdk.open_live_audio_stream(peer.client, timeout_s=1) as stream:
                    async for _ in stream:
                        pass
        self.assertFalse(peer.client._live_audio_subscribed)
        self.assertIsNone(peer.client._audio_owner)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg reference decoder is optional")
    def test_stateful_non_silent_decode_matches_file_decoder_and_resets(self):
        import av
        from openzilo._pcm import _OpusPcmDecoder

        encoder = av.CodecContext.create("libopus", "w")
        encoder.sample_rate = 48000
        encoder.layout = "stereo"
        encoder.format = "s16"
        encoder.bit_rate = 24000
        encoder.options = {"vbr": "off"}
        encoder.open()
        packets = []
        for n in range(8):
            frame = av.AudioFrame(format="s16", layout="stereo", samples=960)
            frame.sample_rate = 48000
            frame.pts = n * 960
            frame.time_base = Fraction(1, 48000)
            samples = [v for i in range(n * 960, (n + 1) * 960) for v in (
                int(8000 * math.sin(i * 2 * math.pi * 440 / 48000)),
                int(4000 * math.sin(i * 2 * math.pi * 660 / 48000)),
            )]
            frame.planes[0].update(struct.pack("<" + "h" * len(samples), *samples))
            packets.extend(bytes(p) for p in encoder.encode(frame))
        packets.extend(bytes(p) for p in encoder.encode(None))
        reference = sdk.decode_opus_to_pcm(sdk.build_opus_recording(packets)).pcm_bytes
        for _ in range(2):
            decoder = _OpusPcmDecoder()
            blocks = [block for packet in packets for block in decoder.decode(packet)]
            # Enough output has arrived to use the stream before flushing.
            self.assertGreater(len(blocks), 0)
            blocks.extend(decoder.flush())
            pcm = b"".join(blocks)
            self.assertEqual(len(pcm), len(packets) * 1280)
            # Different FFmpeg builds may round individual samples differently.
            actual = struct.unpack("<" + "h" * (len(pcm) // 2), pcm)
            expected = struct.unpack("<" + "h" * (len(reference) // 2), reference)
            self.assertLessEqual(max(abs(a - b) for a, b in zip(actual, expected)), 2)
            self.assertNotEqual(actual[::2], actual[1::2])

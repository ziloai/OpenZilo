# SPDX-License-Identifier: MPL-2.0
"""The SDK delegates platform-independent semantics to libopenzilo."""
import asyncio
import hashlib
import io
import struct
import subprocess
import sys
import unittest
import wave

import libopenzilo as native
import openzilo as sdk
from openzilo import _transport as transport
from test_audio_stream import AudioPeer, OPUS, RECORDING


class SharedCoreTests(unittest.IsolatedAsyncioTestCase):
    def test_core_contract_and_shared_semantics(self):
        self.assertEqual(native.library_info().api_contract, 1)
        self.assertEqual(sdk.ProtocolError.__mro__[1], sdk.OpenZiloError)
        self.assertEqual(transport.NUS_SERVICE_UUID, native.ble_transport_spec().service_uuid)
        for code in range(10):
            self.assertEqual(sdk._errors.ERROR_MESSAGES[sdk._errors.ErrorCode(code)],
                             native.device_error_message(code))
        self.assertEqual(sdk.imu_device_key("  AA:BB "), hashlib.sha256(b"aa:bb").hexdigest())
        self.assertEqual(sdk.imu_device_key("AA:BB"), native.local_device_key("aa:bb"))

    def test_runtime_does_not_import_cryptography(self):
        code = "import sys, openzilo; sys.exit('cryptography' in sys.modules)"
        self.assertEqual(subprocess.run([sys.executable, "-c", code]).returncode, 0)

    def test_opus_decodes_to_wav_without_external_decoders(self):
        raw = sdk.build_opus_recording([OPUS] * 5)
        result = sdk.decode_opus_to_pcm(raw)
        self.assertEqual((result.pcm_config.channels, result.packet_count, len(result.pcm_bytes)),
                         (2, 5, 5 * 320 * 4))
        playable = sdk.build_playable_audio(raw, ffmpeg_path="/nonexistent/ffmpeg")
        with wave.open(io.BytesIO(playable.bytes)) as wav:
            self.assertEqual((wav.getnchannels(), wav.getframerate(), wav.getnframes()), (2, 16000, 1600))

    async def test_live_pcm_stream_without_pyav(self):
        peer = AudioPeer()
        async with sdk.open_live_audio_stream(peer.client, timeout_s=1) as stream:
            events = [event async for event in stream]
        self.assertEqual(sum(isinstance(e, sdk.LivePcmFrame) for e in events), 3)
        self.assertTrue(stream.complete)

    async def test_quick_download_assembles_frames_without_end_acknowledgement(self):
        peer = AudioPeer()
        write = peer.write

        async def quick_write(data):
            packet = sdk.decode_packet(data)
            if packet.command == 0x0509:
                peer.commands.append((packet.command, packet.body))
                peer.emit((0x0504, struct.pack(">HIII", 0, 4, 100, len(RECORDING))))
                for offset in range(0, len(RECORDING), 7):
                    chunk = RECORDING[offset:offset + 7]
                    peer.emit((0x0505, struct.pack(">HIIIB", 0, 4, offset, len(chunk),
                                                   offset + len(chunk) == len(RECORDING)) + chunk))
            else:
                await write(data)

        peer.write = quick_write
        progress = []
        info, data = await sdk.download_audio_file(
            peer.client, 4, progress=lambda a, b: progress.append((a, b)), timeout_s=1)
        self.assertEqual((info.file_index, data), (4, RECORDING))
        self.assertEqual(progress[-1], (len(RECORDING), len(RECORDING)))
        self.assertNotIn(0x0507, [command for command, _ in peer.commands])

    def test_legacy_speex_decodes_natively_in_every_container_form(self):
        fmt = sdk.PcmConfig(16000, 1, 16)
        packet = b"\x00" * 20  # a silent 20 ms wideband frame
        forms = {
            "ogg-speex": sdk.build_ogg_speex([packet] * 3, pcm_config=fmt),
            "packet-speex": b"".join(struct.pack("<H", 20) + packet for _ in range(3)) + b"\0\0",
            "raw-speex": packet * 3,
        }
        for kind, source in forms.items():
            with self.subTest(kind=kind):
                result = sdk.decode_speex_to_pcm(source, pcm_config=fmt)
                self.assertEqual((result.source_type, len(result.pcm_bytes)), (kind, 3 * 640))
        playable = sdk.build_playable_audio(forms["packet-speex"], pcm_config=fmt,
                                            ffmpeg_path="/nonexistent/ffmpeg")
        self.assertTrue(sdk.is_wav(playable.bytes))
        stereo = sdk.decode_speex_to_pcm(forms["raw-speex"], pcm_config=sdk.PcmConfig(16000, 2, 16))
        self.assertEqual(len(stereo.pcm_bytes), 3 * 1280)
        seen = []
        custom = sdk.SpeexDecodeResult(b"", fmt)
        self.assertIs(sdk.decode_speex_to_pcm(
            b"abc", speex_decoder=lambda data, options: seen.append(data) or custom), custom)
        self.assertEqual(seen, [b"abc"])
        with self.assertRaises(sdk.AudioDecodeError):
            sdk.decode_speex_to_pcm(b"")
        with self.assertRaises(sdk.AudioDecodeError):
            sdk.decode_speex_to_pcm(b"\xff" * 7)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: MPL-2.0
import io
import importlib.util
import asyncio
from types import SimpleNamespace
from unittest import mock
import shutil
import struct
import unittest
import wave

import openzilo as sdk
from openzilo._recording import _config_body
from test_audio_stream import AudioPeer

PROFILE = struct.pack(">BBBBBBBHBHH", 3, 1, 1, 1, 0, 0, 0, 3001, 16, 100, 2048)


class RecordingPeer:
    is_connected = True

    def __init__(self):
        self.client = sdk.OpenZiloClient(transport=self, command_timeout_s=0.05)
        self.client._disconnected.clear()
        self.config = sdk.AudioRecordingConfig()
        self.session = self.state = self.error = self.index = 0
        self.saved = False
        self.commands = []
        self.fault = None

    def emit(self, cmd, body):
        self.client._on_rx(sdk.encode_packet(cmd, body))

    async def write(self, raw):
        p = sdk.decode_packet(raw)
        self.commands.append((p.command, p.body))
        if p.command == 0x0512:
            self.emit(0x0513, b"\0\0" + _config_body(self.config) + struct.pack(">HH", 16000, 20) + PROFILE)
        elif p.command == 0x0514:
            assert len(p.body) == 14 and p.body[0] == 1
            if self.state in (1, 2, 3):
                self.emit(0x0515, struct.pack(">H", 2))
            else:
                self.config = sdk.AudioRecordingConfig(*struct.unpack(">BBBBIHHH", p.body)[1:])
                body = b"\0\0" + _config_body(self.config) + struct.pack(">HH", 16000, 20) + PROFILE
                self.emit(0x0515, body if self.fault != "readback" else body[:5] + b"\x01" + body[6:])
        elif p.command == 0x0516:
            if self.state in (1, 2, 3):
                self.emit(0x0517, struct.pack(">H", 2))
            else:
                self.session += 1
                self.state = 1
                if self.fault != "lost_start":
                    self.emit(0x0517, struct.pack(">HI", 0, self.session))
        elif p.command == 0x0518:
            session, cancel = struct.unpack(">IB", p.body)
            if session != self.session:
                self.emit(0x0519, struct.pack(">H", 7))
            else:
                self.state = 6 if cancel else 3
                self.emit(0x0519, struct.pack(">HI", 0, session))
        elif p.command == 0x051A:
            self.emit(0x051B, struct.pack(">HIBBHI", 0, self.session, self.state,
                                         self.saved, self.error, self.index))


class RecordingControlTests(unittest.IsolatedAsyncioTestCase):
    def test_invalid_parameters_rejected(self):
        for changes in ({"channels": 3}, {"channels": True}, {"bitrate": 32001},
                        {"bitrate": 7999}, {"gain_left_q8": -1}, {"gain_right_q8": 1025},
                        {"max_duration_ms": 21}, {"max_duration_ms": 60020},
                        {"sample_rate": 48000}, {"frame_duration_ms": 10},
                        {"output": 2, "disconnect_policy": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                sdk.AudioRecordingConfig(**changes)

    async def test_configuration_wire_and_verified_readback(self):
        peer = RecordingPeer()
        actual = await sdk.get_audio_recording_config(peer.client)
        self.assertEqual(actual, sdk.AudioRecordingConfig())
        self.assertEqual((actual.codec, actual.complexity, actual.vbr, actual.signal, actual.application),
                         (3, 1, 1, 3001, 2048))
        config = sdk.AudioRecordingConfig(sdk.AudioOutput.LIVE_AND_FLASH,
                                          sdk.AudioDisconnectPolicy.CONTINUE_SAVING,
                                          1, 16000, 512, 0, 1000)
        self.assertEqual(await sdk.set_audio_recording_config(peer.client, config), config)
        self.assertEqual(peer.commands[-1], (0x0514, bytes.fromhex("0103010100003e800200000003e8")))
        peer.fault = "readback"
        with self.assertRaises(sdk.ProtocolError):
            await sdk.set_audio_recording_config(peer.client, sdk.AudioRecordingConfig())

    async def test_stop_ack_is_not_completion_and_index_zero_is_valid(self):
        peer = RecordingPeer()
        session = await sdk.start_audio_recording(peer.client)
        self.assertEqual(session, 1)
        self.assertTrue(peer.client._recording_active)
        with self.assertRaises(sdk.DeviceError):
            await sdk.set_audio_recording_config(peer.client, sdk.AudioRecordingConfig())
        await sdk.stop_audio_recording(peer.client, session)
        status = await sdk.get_audio_recording_status(peer.client)
        self.assertEqual(status.state, sdk.AudioRecordingState.FINALIZING)
        self.assertFalse(status.finished)
        self.assertIsNone(status.file_index)
        peer.state = 4
        peer.saved = True
        final = await sdk.wait_audio_recording_finished(peer.client, session)
        self.assertEqual(final.file_index, 0)
        self.assertFalse(peer.client._recording_active)

    async def test_cancel_and_stale_session(self):
        peer = RecordingPeer()
        session = await sdk.start_audio_recording(peer.client)
        with self.assertRaises(sdk.DeviceError):
            await sdk.stop_audio_recording(peer.client, session + 1)
        await sdk.stop_audio_recording(peer.client, session, cancel=True)
        status = await sdk.wait_audio_recording_finished(peer.client, session)
        self.assertEqual(status.state, sdk.AudioRecordingState.CANCELLED)
        self.assertFalse(status.saved)
        with self.assertRaises(sdk.ProtocolError):
            await sdk.wait_audio_recording_finished(peer.client, session + 1)

    async def test_lost_start_ack_recovered_by_status_without_restarting(self):
        peer = RecordingPeer()
        peer.fault = "lost_start"
        with self.assertRaises(sdk.TimeoutError):
            await sdk.start_audio_recording(peer.client)
        self.assertTrue(peer.client._recording_active)
        self.assertEqual((await sdk.get_audio_recording_status(peer.client)).session_id, 1)
        self.assertEqual(sum(c == 0x0516 for c, _ in peer.commands), 1)

    async def test_failure_and_timeout_do_not_claim_saved_file(self):
        peer = RecordingPeer()
        session = await sdk.start_audio_recording(peer.client)
        with self.assertRaises(sdk.TimeoutError):
            await sdk.wait_audio_recording_finished(peer.client, session, timeout_s=0.025, poll_interval_s=0.01)
        peer.state = 5
        peer.error = 8
        with self.assertRaises(sdk.DeviceError):
            await sdk.wait_audio_recording_finished(peer.client, session)

    async def test_bad_status_and_stop_inputs(self):
        peer = RecordingPeer()
        for value in (0, -1, True, 0x100000000):
            with self.assertRaises(ValueError):
                await sdk.stop_audio_recording(peer.client, value)
        peer.session = 1
        peer.state = 9
        with self.assertRaises(sdk.ProtocolError):
            await sdk.get_audio_recording_status(peer.client)
        peer.state = 5
        with self.assertRaises(sdk.ProtocolError):
            await sdk.get_audio_recording_status(peer.client)

    async def test_mono_live_receive_and_file_format(self):
        peer = AudioPeer()
        original = peer.emit

        def mono_emit(*packets):
            converted = []
            for command, body in packets:
                if command == 0x050F:
                    body = body[:18] + b"\x01" + body[19:]
                elif command == 0x0510:
                    body = body[:14] + b"\xf8" + body[15:]
                converted.append((command, body))
            original(*converted)

        peer.emit = mono_emit
        recording = await sdk.receive_live_audio_file(peer.client)
        self.assertEqual(recording.start.channels, 1)
        self.assertEqual(struct.unpack_from("<H", recording.data, 6)[0], 1)
        self.assertEqual(len(sdk.parse_opus_recording(recording.data)), 3)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is optional")
    def test_mono_file_decodes_to_mono_wav(self):
        playable = sdk.build_playable_audio(sdk.build_opus_recording([b"\xf8\xff\xfe"] * 5, channels=1))
        with wave.open(io.BytesIO(playable.bytes)) as wav:
            self.assertEqual((wav.getnchannels(), wav.getframerate(), wav.getnframes()), (1, 16000, 1600))

    def test_public_exports(self):
        for name in ("AudioOutput", "AudioRecordingConfig", "start_audio_recording",
                     "get_audio_recording_status", "wait_audio_recording_finished"):
            self.assertIn(name, sdk.__all__)

    async def test_active_recording_blocks_ota(self):
        from test_ota import make_bundle, PUBLIC_KEY
        peer = RecordingPeer()
        await sdk.start_audio_recording(peer.client)
        with self.assertRaises(sdk.ProtocolError):
            await sdk.update_firmware(peer.client, make_bundle(), trusted_public_key=PUBLIC_KEY)
        self.assertFalse(any(cmd == 1005 for cmd, _ in peer.commands))

    async def test_cli_remote_record_flash_and_both(self):
        from openzilo import _cli as cli
        for destination in ("flash", "both"):
            with self.subTest(destination=destination):
                peer = RecordingPeer()
                stopped = asyncio.Event()
                write = peer.write

                async def finish_write(raw):
                    await write(raw)
                    if sdk.decode_packet(raw).command == 0x0518:
                        peer.state = 4
                        peer.saved = True
                        stopped.set()

                peer.write = finish_write

                class Context:
                    async def __aenter__(self):
                        return peer.client

                    async def __aexit__(self, *args):
                        return False

                raw = sdk.build_opus_recording([b"\xfc\xff\xfe"])

                async def receive(client, *, on_subscribed):
                    await on_subscribed()
                    await stopped.wait()
                    return SimpleNamespace(data=raw)

                args = cli.build_parser().parse_args([
                    "audio-record", "--address", "synthetic", "--seconds", "0.02",
                    "--destination", destination, "synthetic.bin",
                ])
                with mock.patch.object(cli, "OpenZiloClient", return_value=Context()), \
                        mock.patch.object(cli, "get_device_capabilities", new=mock.AsyncMock()), \
                        mock.patch.object(cli, "receive_live_audio_file", side_effect=receive), \
                        mock.patch.object(cli, "download_audio_file", new=mock.AsyncMock(return_value=(None, raw))), \
                        mock.patch.object(cli, "save_audio_bundle", return_value=SimpleNamespace(raw_path="raw", play_path="wav")) as save, \
                        mock.patch("builtins.print"):
                    await args.func(args)
                    self.assertEqual(save.call_args.kwargs["data"], raw)
                self.assertEqual(peer.config.output, sdk.AudioOutput.FLASH if destination == "flash" else sdk.AudioOutput.LIVE_AND_FLASH)
                self.assertEqual(sum(cmd == 0x0516 for cmd, _ in peer.commands), 1)

    @unittest.skipUnless(importlib.util.find_spec("av"), "PCM extra is optional")
    def test_mono_incremental_pcm_decoder(self):
        from openzilo._pcm import _OpusPcmDecoder
        decoder = _OpusPcmDecoder(channels=1)
        blocks = []
        for _ in range(7):
            blocks.extend(decoder.decode(b"\xf8\xff\xfe"))
        blocks.extend(decoder.flush())
        self.assertEqual(len(blocks), 7)
        self.assertTrue(all(len(block) == 640 for block in blocks))

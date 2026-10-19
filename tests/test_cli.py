# SPDX-License-Identifier: MPL-2.0
"""Hardware-free CLI workflows and resource cleanup."""

import argparse
import asyncio
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from openzilo import _cli as cli, _cli_config as config
from openzilo import ProtocolError, SensorDataBatch, TimeoutError


class CliTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        contexts = contextlib.ExitStack()
        self.addCleanup(contexts.close)
        directory = contexts.enter_context(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "preferences" / "config.json"
        contexts.enter_context(mock.patch.dict(os.environ, {"OPENZILO_CONFIG": str(self.path)}, clear=True))
        contexts.enter_context(contextlib.redirect_stdout(io.StringIO()))
        contexts.enter_context(contextlib.redirect_stderr(io.StringIO()))

    async def dispatch(self, words, **kwargs):
        await cli.dispatch(cli.build_parser().parse_args(words), **kwargs)

    async def test_selection_and_forget(self):
        await self.dispatch(["device", "use", "synthetic-device"])
        self.assertEqual(config.load_address(), "synthetic-device")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        await self.dispatch(["device", "forget"])
        self.assertIsNone(config.load_address())

    async def test_scan_and_choose_does_not_connect(self):
        devices = [SimpleNamespace(name="Ring", address="synthetic-device", rssi=-50)]
        with mock.patch.object(cli, "scan_rings", new=mock.AsyncMock(return_value=devices)), \
                mock.patch("builtins.input", return_value="1"), \
                mock.patch.object(cli, "OpenZiloClient") as connect:
            await self.dispatch(["device", "use"])
        self.assertEqual(config.load_address(), "synthetic-device")
        connect.assert_not_called()

    async def test_invalid_selection_preserves_default(self):
        config.save_address("existing")
        devices = [SimpleNamespace(name="Ring", address="synthetic-device", rssi=-50)]
        with mock.patch.object(cli, "scan_rings", new=mock.AsyncMock(return_value=devices)), \
                mock.patch("builtins.input", return_value="2"):
            with self.assertRaisesRegex(ValueError, "Invalid device number"):
                await self.dispatch(["device", "use"])
        self.assertEqual(config.load_address(), "existing")

    async def test_address_precedence(self):
        config.save_address("saved")
        handler = mock.AsyncMock()
        for explicit, fallback, environment, expected in (
            ("explicit", "shell", "environment", "explicit"),
            (None, "shell", "environment", "shell"),
            (None, None, "environment", "environment"),
            (None, None, "", "saved"),
        ):
            with self.subTest(expected=expected):
                os.environ["OPENZILO_ADDRESS"] = environment
                args = argparse.Namespace(needs_device=True, address=explicit, func=handler)
                await cli.dispatch(args, fallback_address=fallback)
                self.assertEqual(args.address, expected)

    async def test_missing_device_never_connects(self):
        with mock.patch.object(cli, "OpenZiloClient") as connect:
            with self.assertRaisesRegex(ValueError, "No device selected"):
                await self.dispatch(["info"])
        connect.assert_not_called()

    async def test_corrupt_config_recovery_and_explicit_override(self):
        self.path.parent.mkdir()
        self.path.write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid CLI config"):
            config.load_address()
        handler = mock.AsyncMock()
        await cli.dispatch(argparse.Namespace(needs_device=True, address="override", func=handler))
        handler.assert_awaited_once()
        await self.dispatch(["device", "forget"])
        self.assertIsNone(config.load_address())

    async def test_help_does_not_read_config(self):
        with mock.patch.object(cli, "load_address", side_effect=AssertionError):
            with self.assertRaises(SystemExit) as result:
                cli.build_parser().parse_args(["--help"])
        self.assertEqual(result.exception.code, 0)

    async def test_shell_recovers_from_errors_and_updates_device(self):
        commands = ["unknown", "help info", "'bad quote", "info", "device use synthetic", "info", "exit"]
        handler = mock.AsyncMock()
        with mock.patch("builtins.input", side_effect=commands), \
                mock.patch.object(cli, "cmd_info", handler):
            await self.dispatch(["shell"])
        handler.assert_awaited_once()
        self.assertEqual(handler.call_args.args[0].address, "synthetic")

    async def test_clear_still_requires_confirmation(self):
        config.save_address("synthetic")
        with mock.patch.object(cli, "OpenZiloClient") as connect:
            with self.assertRaisesRegex(SystemExit, "--yes"):
                await self.dispatch(["audio-clear"])
        connect.assert_not_called()

    async def test_invalid_sensor_duration(self):
        for duration in ("0", "-1", "nan", "inf"):
            with self.subTest(duration=duration), self.assertRaises(SystemExit):
                cli.build_parser().parse_args(["sensor-stream", "--seconds", duration])

    async def test_sensor_output_and_stop_on_timeout_failure_or_cancel(self):
        for error in (TimeoutError("end"), ProtocolError("bad packet"), asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__):
                output = self.path.parent / "samples.jsonl"
                client = mock.AsyncMock()
                client.__aenter__.return_value = client
                stop = mock.AsyncMock()
                batch = SensorDataBatch(sequence_start=3, frame_count=0, sample_size=16, samples=())
                with mock.patch.object(cli, "OpenZiloClient", return_value=client), \
                        mock.patch.object(cli, "enable_time_sync"), \
                        mock.patch.object(cli, "get_device_capabilities", new=mock.AsyncMock()), \
                        mock.patch.object(cli, "start_sensor_report", new=mock.AsyncMock()), \
                        mock.patch.object(cli, "wait_sensor_data", new=mock.AsyncMock(side_effect=[batch, error])), \
                        mock.patch.object(cli, "stop_sensor_report", stop):
                    operation = self.dispatch(["sensor-stream", "--address", "synthetic", "--output", str(output)])
                    if isinstance(error, TimeoutError):
                        await operation
                    else:
                        with self.assertRaises(type(error)):
                            await operation
                stop.assert_awaited_once_with(client)
                client.__aexit__.assert_awaited_once()
                self.assertEqual(json.loads(output.read_text())["sequence_start"], 3)

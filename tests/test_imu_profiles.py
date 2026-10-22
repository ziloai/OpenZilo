# SPDX-License-Identifier: MPL-2.0
import asyncio
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import openzilo as sdk


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.config = sdk.SensorStartInfo(100, 16, 2000)
        self.profile = sdk.ImuCalibrationProfile(sdk.imu_device_key('SYNTHETIC-DEVICE'), 'fw', 'test',
                                                 sdk.ImuCalibration.identity(self.config), True)

    def test_roundtrip_atomic_failure_and_no_plain_identifier(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'imu.json'
            sdk.save_imu_calibration_profile(self.profile, path)
            old = path.read_bytes()
            self.assertNotIn(b'SYNTHETIC-DEVICE', old)
            self.assertEqual(sdk.load_imu_calibration_profile(path), self.profile)
            with patch('openzilo._imu_profiles.os.replace', side_effect=OSError('failed rename')):
                with self.assertRaises(OSError):
                    sdk.save_imu_calibration_profile(replace(self.profile, model='new'), path)
            self.assertEqual(path.read_bytes(), old)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_strict_schema_units_parameters_and_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'imu.json'
            sdk.save_imu_calibration_profile(self.profile, path)
            original = json.loads(path.read_text())
            mutations = [('schema_version', 2), ('schema_version', True), ('application', 'firmware'),
                         ('input_domain', 'already_corrected'), ('scale_unit', 'ratio'),
                         ('gyro_validated', 'false'), ('accel_validated', False)]
            for key, value in mutations:
                data = {**original, key: value}
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError): sdk.load_imu_calibration_profile(path)
            data = json.loads(json.dumps(original))
            data['calibration']['accel_scale_ppm'] = [0, 1, 1]
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError): sdk.load_imu_calibration_profile(path)

    def test_device_firmware_model_bindings(self):
        self.profile.check_device('synthetic-device', 'fw', 'test')
        for values in [('another', 'fw', 'test'), ('synthetic-device', 'new', 'test'),
                       ('synthetic-device', 'fw', 'another')]:
            with self.assertRaises(sdk.CompatibilityError): self.profile.check_device(*values)

    def test_unvalidated_components_cannot_apply_hidden_offsets(self):
        with self.assertRaises(ValueError):
            replace(self.profile, calibration=replace(self.profile.calibration, gyro_bias_udps=(100000, 0, 0)))
        sample = sdk.SensorDataSample(0, 2048, 0, 0, 160, 0, 0)
        raw = sdk.SensorDataBatch(0, 1, 16, (sample,))
        corrected = self.profile.apply(raw, self.config)
        self.assertEqual(corrected.applied_components, ('accel',))
        self.assertAlmostEqual(corrected.samples[0].gyro_dps[0], 160*2000/32768)

    def test_invalid_statistics_never_pass_validation(self):
        with self.assertRaises(ValueError): sdk.ImuStaticWindow((float('nan'), 0, 1), (0, 0, 0), 0, 0, 100)


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.config = sdk.SensorStartInfo(100, 16, 2000)
        self.profile = sdk.ImuCalibrationProfile(sdk.imu_device_key('synthetic'), 'fw', 'test',
                                                 sdk.ImuCalibration.identity(self.config), True)
        self.client = SimpleNamespace(_connection_token=object(), transport=SimpleNamespace(address='synthetic'),
                                      _drain_queue=lambda cmd: None)
        self.start = AsyncMock(return_value=self.config)
        self.stop = AsyncMock()
        self.raw = sdk.SensorDataBatch(3, 1, 16, (sdk.SensorDataSample(42, 2048, 0, 0, 16, 0, 0),))
        self.patches = [
            patch('openzilo._imu_profiles.require_software_imu_source', AsyncMock()),
            patch('openzilo._imu_profiles.get_system_info', AsyncMock(return_value=SimpleNamespace(firmware_version='fw', model='test'))),
            patch('openzilo._imu_profiles.start_sensor_report', self.start),
            patch('openzilo._imu_profiles.stop_sensor_report', self.stop),
            patch('openzilo._imu_profiles.wait_sensor_data', AsyncMock(return_value=self.raw)),
        ]
        for item in self.patches: item.start(); self.addCleanup(item.stop)

    async def test_context_applies_and_stops_after_break(self):
        async with sdk.open_calibrated_imu_stream(self.client, self.profile) as stream:
            batch = await anext(stream)
            self.assertEqual(batch.samples[0].accel_g, (1, 0, 0))
            self.assertEqual(batch.samples[0].timestamp_ms, 42)
            self.assertEqual(batch.applied_components, ('accel',))
        self.stop.assert_awaited_once()
        with self.assertRaises(StopAsyncIteration): await anext(stream)

    async def test_binding_failure_before_capture(self):
        with self.assertRaises(sdk.CompatibilityError):
            async with sdk.open_calibrated_imu_stream(self.client, self.profile, device_id='wrong'):
                self.fail('Should not enter')
        self.start.assert_not_awaited()
        self.stop.assert_not_awaited()

    async def test_range_mismatch_stops_capture(self):
        self.start.return_value = replace(self.config, accel_range_g=8)
        with self.assertRaises(sdk.CompatibilityError):
            async with sdk.open_calibrated_imu_stream(self.client, self.profile): pass
        self.stop.assert_awaited_once()

    async def test_start_timeout_attempts_cleanup(self):
        self.start.side_effect = sdk.TimeoutError('lost acknowledgement')
        with self.assertRaises(sdk.TimeoutError):
            async with sdk.open_calibrated_imu_stream(self.client, self.profile): pass
        self.stop.assert_awaited_once()

    async def test_reconnect_invalidates_stream_without_stopping_new_session(self):
        async with sdk.open_calibrated_imu_stream(self.client, self.profile) as stream:
            self.client._connection_token = object()
            with self.assertRaises(sdk.TransportError): await anext(stream)
        self.stop.assert_not_awaited()

    async def test_second_software_consumer_is_rejected(self):
        async with sdk.open_calibrated_imu_stream(self.client, self.profile):
            with self.assertRaises(sdk.ProtocolError):
                async with sdk.open_calibrated_imu_stream(self.client, self.profile): pass
        self.stop.assert_awaited_once()

    async def test_cancellation_stops_capture(self):
        with self.assertRaises(asyncio.CancelledError):
            async with sdk.open_calibrated_imu_stream(self.client, self.profile):
                raise asyncio.CancelledError
        self.stop.assert_awaited_once()

class SoftwareStreamCliTests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_marks_units_domain_and_components(self):
        from contextlib import asynccontextmanager, ExitStack
        import io
        from openzilo import _cli
        config = sdk.SensorStartInfo(100, 16, 2000)
        raw = sdk.SensorDataBatch(4, 1, 16, (sdk.SensorDataSample(50, 2048, 0, 0, 0, 0, 0),))
        batch = sdk.apply_imu_calibration(raw, config, sdk.ImuCalibration.identity(config), gyro=False)
        class Stream:
            def __init__(self): self.config=config; self.sent=False
            async def __anext__(self):
                if self.sent: raise sdk.TimeoutError('end test stream')
                self.sent=True
                return batch
        closed=[]
        @asynccontextmanager
        async def opened(*args, **kwargs):
            try: yield Stream()
            finally: closed.append(True)
        class Client:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
        args = SimpleNamespace(output=None, address='synthetic', scan_timeout=1,
                               connect_timeout=1, calibrated=True, calibration_profile=None, seconds=1)
        output=io.StringIO()
        with ExitStack() as stack:
            for name, value in {'OpenZiloClient':lambda **kw:Client(),
                                'get_device_capabilities':AsyncMock(), 'enable_time_sync':lambda c:None,
                                'open_calibrated_imu_stream':opened}.items():
                stack.enter_context(patch('openzilo._cli.'+name,value))
            stack.enter_context(patch('sys.stdout',output))
            stack.enter_context(patch('sys.stderr',io.StringIO()))
            await _cli.cmd_sensor_stream(args)
        row=json.loads(output.getvalue())
        self.assertEqual(row['data_domain'],'software_calibrated')
        self.assertEqual(row['accel_unit'],'g')
        self.assertEqual(row['gyro_unit'],'deg/s')
        self.assertEqual(row['applied_components'],['accel'])
        self.assertEqual(row['samples'][0]['accel_g'],[1,0,0])
        self.assertEqual(closed,[True])

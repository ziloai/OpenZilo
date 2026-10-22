# SPDX-License-Identifier: MPL-2.0
from dataclasses import replace
import math
import unittest
from unittest.mock import patch, AsyncMock
import openzilo as sdk
from openzilo._cli import build_parser

class CalibrationMathTests(unittest.TestCase):
    def setUp(self):
        self.cal = sdk.ImuCalibration(1, 16, 2000)
        self.config = sdk.SensorStartInfo(100, 16, 2000)

    def samples(self, acc=(0, 0, 1), gyro=(0.5, -0.2, 0.1), count=500):
        return [sdk.SensorDataSample(n*10, *(round(v*32768/16) for v in acc),
                                    *(round(v*32768/2000) for v in gyro)) for n in range(count)]

    def test_static_bias_and_roundtrip(self):
        w = sdk.analyze_imu_static_window(self.samples(), self.config)
        result = sdk.fit_imu_gyro_bias(self.cal, w)
        self.assertAlmostEqual(result.gyro_bias_udps[0]/1e6, 0.5, delta=0.031)
        sample = self.samples()[0]
        batch = sdk.SensorDataBatch(7, 1, 16, (sample,))
        corrected = sdk.apply_imu_calibration(batch, self.config, result)
        self.assertAlmostEqual(corrected.samples[0].gyro_dps[0], 0, delta=1e-6)
        self.assertEqual(batch.samples[0], sample)
        self.assertEqual(corrected.sequence_start, 7)
        with self.assertRaises(ValueError):
            sdk.apply_imu_calibration(corrected, self.config, result)

    def test_motion_clipping_and_missing_data_rejected(self):
        for samples in (self.samples(count=100), self.samples(acc=(0, 0, 0)),
                        self.samples(gyro=(25, 0, 0)),
                        self.samples()[:250] + self.samples(acc=(0.1, 0, 1))[:250],
                        [sdk.SensorDataSample(i, 32767, 0, 0, 0, 0, 0) for i in range(500)]):
            with self.assertRaises(ValueError):
                sdk.analyze_imu_static_window(samples, self.config)

    def test_slow_bias_drift_is_rejected_even_with_low_noise(self):
        rows = [sdk.SensorDataSample(i*10, 0, 0, 2048, 0,
                                    round((-0.5*i/1999)*32768/2000), 0) for i in range(2000)]
        with self.assertRaisesRegex(ValueError, 'Readings are still drifting'):
            sdk.analyze_imu_static_window(rows, self.config)

    def test_six_faces_with_tilt_and_inverted_order(self):
        bias, gain = (0.02, -0.03, 0.01), (1.03, 0.98, 1.01)
        windows = []
        for axis in (2, 0, 1):
            for sign in (-1, 1):
                vector = [0.04, -0.06, 0.03]
                vector[axis] = sign*math.sqrt(1-sum(v*v for i, v in enumerate(vector) if i != axis))
                observed = tuple(vector[i]/gain[i]+bias[i] for i in range(3))
                windows.append(sdk.ImuStaticWindow(observed, (0.4, -0.2, 0.1), 0.001, 0.03, 500))
        result = sdk.fit_imu_six_face_calibration(self.cal, windows)
        for i in range(3):
            self.assertAlmostEqual(result.accel_bias_ug[i]/1e6, bias[i], places=5)
            self.assertAlmostEqual(result.accel_scale_ppm[i]/1e6, gain[i], places=5)
        with self.assertRaises(ValueError):
            sdk.fit_imu_six_face_calibration(self.cal, windows[:-1]+windows[:1])
        self.assertEqual(result.gyro_bias_udps, self.cal.gyro_bias_udps)

    def test_independent_validation_rejects_residual(self):
        w = sdk.ImuStaticWindow((0, 0, 1), (0.01, 0, 0), 0.001, 0.01, 500)
        sdk.validate_imu_calibration([w], full=False)
        with self.assertRaises(ValueError):
            sdk.validate_imu_calibration([replace(w, gyro_dps=(0.2, 0, 0))], full=False)
        with self.assertRaises(ValueError):
            sdk.validate_imu_calibration([w, w, w], full=True)

    def test_accel_stage_ignores_gyro_bias_but_final_gyro_validation_does_not(self):
        w = sdk.analyze_imu_static_window(self.samples(gyro=(30, 0, 0)), self.config, check_gyro=False)
        poses = [replace(w, accel_g=tuple(1 if i == axis else 0 for i in range(3))) for axis in range(3)]
        sdk.validate_imu_calibration(poses, full=True, component='accel')
        with self.assertRaises(ValueError):
            sdk.validate_imu_calibration(poses, full=True)

    def test_large_static_bias_is_not_misreported_as_motion(self):
        w = sdk.analyze_imu_static_window(self.samples(gyro=(2, -17, -3)), self.config)
        self.assertAlmostEqual(w.gyro_dps[1], -17, delta=0.031)

    def test_untrusted_parameters_rejected(self):
        for fields in ({'accel_scale_ppm': (0, 1, 1)}, {'gyro_bias_udps': (2**31, 0, 0)},
                       {'accel_bias_ug': (float('nan'), 0, 0)}):
            with self.assertRaises(ValueError): replace(self.cal, **fields)

    def test_physical_units_partial_application_and_range_guard(self):
        cal = replace(self.cal, accel_bias_ug=(100000, 0, 0), accel_scale_ppm=(1100000, 1000000, 1000000),
                      gyro_bias_udps=(1000000, 0, 0))
        raw = sdk.SensorDataBatch(1, 1, 16, (sdk.SensorDataSample(22, 2048, 0, -2048, 16, 0, 0),))
        result = sdk.apply_imu_calibration(raw, self.config, cal, gyro=False)
        self.assertAlmostEqual(result.samples[0].accel_g[0], .99)
        self.assertAlmostEqual(result.samples[0].gyro_dps[0], 16*2000/32768)
        self.assertEqual(result.applied_components, ('accel',))
        self.assertEqual(result.samples[0].timestamp_ms, 22)
        with self.assertRaises(ValueError):
            sdk.apply_imu_calibration(raw, replace(self.config, accel_range_g=8), cal)

    def test_cli(self):
        for action in ('show', 'accel', 'quick', 'full', 'reset'):
            self.assertEqual(build_parser().parse_args(['imu-calibrate', action]).action, action)

class CalibrationSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_sequence_gap_is_rejected(self):
        config = sdk.SensorStartInfo(10, 16, 2000)
        sample = sdk.SensorDataSample(0, 0, 0, 2048, 0, 0, 0)
        batches = [sdk.SensorDataBatch(0, 10, 16, (sample,)*10),
                   sdk.SensorDataBatch(11, 10, 16, (sample,)*10)]
        class Client:
            def _drain_queue(self, command): pass
        with patch('openzilo._imu_calibration.wait_sensor_data', AsyncMock(side_effect=batches)):
            with self.assertRaisesRegex(ValueError, 'Sample sequence gap'):
                await sdk.collect_imu_static_window(Client(), config, seconds=2, settle_seconds=0)

    async def test_firmware_correction_contract_is_rejected(self):
        from openzilo._imu_profiles import require_software_imu_source
        for major in (1, 2):
            caps = sdk.DeviceCapabilities('device', 'future', 'test', features=(
                sdk.FeatureVersion('imu', 2, 0), sdk.FeatureVersion('imu_calibration', major, 0)))
            with patch('openzilo._imu_profiles.get_device_capabilities', AsyncMock(return_value=caps)):
                with self.assertRaises(sdk.CompatibilityError):
                    await require_software_imu_source(object())


class CalibrationCliWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, *, failed_validation=False, failed_save=False, action='full'):
        from contextlib import ExitStack
        from openzilo._cli_calibration import cmd_imu_calibration
        from types import SimpleNamespace
        from pathlib import Path
        import tempfile
        import io
        config = sdk.SensorStartInfo(100, 16, 2000)
        raw = sdk.ImuStaticWindow((0, 0, 1), (0.4, -0.2, 0.1), 0.001, 0.02, 500)
        bias = (0.02, -0.01, 0.03)
        faces = []
        for axis in range(3):
            for sign in (-1, 1):
                a = list(bias); a[axis] += sign
                faces.append(replace(raw, accel_g=tuple(a)))
        verify = [replace(raw, accel_g=tuple(bias[i]+(1 if i == axis else 0) for i in range(3)))
                  for axis in range(3)]
        gyro_verify = replace(raw, gyro_dps=(0.8, -0.2, 0.1) if failed_validation else (.41, -.19, .11))
        class Client:
            request = AsyncMock(side_effect=AssertionError('Firmware writes are forbidden'))
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def _drain_queue(self, cmd): pass
        client = Client()
        prefix = 'openzilo._cli_calibration.'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'profile.json'
            original = sdk.ImuCalibrationProfile(sdk.imu_device_key('test-device'), 'fw', 'ring',
                                                 sdk.ImuCalibration.identity(config), True)
            sdk.save_imu_calibration_profile(original, path)
            before = path.read_bytes()
            args = SimpleNamespace(address='test-device', scan_timeout=1, connect_timeout=1,
                                   action=action, seconds=5, profile=path)
            windows = (faces+verify if action != 'quick' else []) + ([raw]*4+[gyro_verify] if action != 'accel' else [])
            with ExitStack() as stack:
                for name, value in {
                    'OpenZiloClient': lambda **kw: client,
                    'require_software_imu_source': AsyncMock(),
                    'get_system_info': AsyncMock(return_value=SimpleNamespace(firmware_version='fw', model='ring')),
                    'enable_time_sync': lambda c: None,
                    'start_sensor_report': AsyncMock(return_value=config),
                    'stop_sensor_report': AsyncMock(), '_prompt': AsyncMock(return_value=''),
                    'collect_imu_static_window': AsyncMock(side_effect=windows),
                }.items(): stack.enter_context(patch(prefix+name, value))
                if failed_save:
                    stack.enter_context(patch(prefix+'save_imu_calibration_profile', side_effect=OSError('disk failure')))
                stack.enter_context(patch('sys.stdout', io.StringIO()))
                if failed_validation:
                    with self.assertRaises(ValueError): await cmd_imu_calibration(args)
                elif failed_save:
                    with self.assertRaises(OSError): await cmd_imu_calibration(args)
                else:
                    await cmd_imu_calibration(args)
            client.request.assert_not_called()
            if failed_validation or failed_save:
                self.assertEqual(path.read_bytes(), before)
            return sdk.load_imu_calibration_profile(path)

    async def test_full_saves_only_to_host_after_software_validation(self):
        profile = await self.exercise()
        self.assertTrue(profile.accel_validated and profile.gyro_validated)
        self.assertEqual(profile.calibration.accel_bias_ug, (20000, -10000, 30000))
        self.assertEqual(profile.calibration.gyro_bias_udps, (400000, -200000, 100000))
        self.assertEqual(profile.calibration.sensor_type, 0)

    async def test_accel_only_does_not_wait_for_gyro(self):
        profile = await self.exercise(action='accel')
        self.assertTrue(profile.accel_validated)
        self.assertFalse(profile.gyro_validated)
        self.assertEqual(profile.calibration.gyro_bias_udps, (0, 0, 0))

    async def test_quick_preserves_acceleration(self):
        profile = await self.exercise(action='quick')
        self.assertTrue(profile.accel_validated and profile.gyro_validated)
        self.assertEqual(profile.calibration.accel_bias_ug, (0, 0, 0))

    async def test_validation_failure_preserves_old_file(self):
        await self.exercise(failed_validation=True)

    async def test_disk_failure_preserves_old_file(self):
        await self.exercise(failed_save=True)

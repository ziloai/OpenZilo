# SPDX-License-Identifier: MPL-2.0
"""Software IMU calibration in physical units. No gyro scale or axis rotation fit."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import math
from typing import Sequence

from ._client import OpenZiloClient
from ._core import native, call_value
from ._sensor import SensorDataBatch, SensorDataSample, SensorStartInfo, wait_sensor_data


@dataclass(frozen=True)
class ImuCalibration:
    """Board-frame physical biases and diagonal accel gains; gyro gain stays unchanged."""
    sensor_type: int
    accel_range_g: int
    gyro_range_dps: int
    accel_bias_ug: tuple[int, int, int] = (0, 0, 0)
    accel_scale_ppm: tuple[int, int, int] = (1000000, 1000000, 1000000)
    gyro_bias_udps: tuple[int, int, int] = (0, 0, 0)

    def __post_init__(self) -> None:
        if any(type(v) is not int for v in (self.sensor_type, self.accel_range_g, self.gyro_range_dps)):
            raise ValueError('Invalid sensor identity or ranges')
        for values in (self.accel_bias_ug, self.accel_scale_ppm, self.gyro_bias_udps):
            if len(values) != 3 or any(type(v) is not int for v in values):
                raise ValueError('Calibration parameters exceed supported bounds')
        for name in ('accel_bias_ug', 'accel_scale_ppm', 'gyro_bias_udps'):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        call_value(native.validate_imu_parameters, _to_native_calibration(self, validate=False))

    @classmethod
    def identity(cls, config: SensorStartInfo) -> ImuCalibration:
        """Unknown chip type is 0; never guess a chip identity on legacy firmware."""
        identity = call_value(native.identity_imu_calibration, _native_config(config))
        return cls(identity.sensor_type, identity.accel_range_g, identity.gyro_range_dps,
                   tuple(identity.accel_bias_ug), tuple(identity.accel_scale_ppm),
                   tuple(identity.gyro_bias_udps))


def _native_config(config: SensorStartInfo) -> native.ImuConfig:
    return native.ImuConfig(sample_rate_hz=config.sample_rate_hz, accel_range_g=config.accel_range_g,
                            gyro_range_dps=config.gyro_range_dps)


def _to_native_calibration(c: ImuCalibration, validate: bool = True) -> native.ImuCalibration:
    return native.ImuCalibration(
        sensor_type=c.sensor_type, accel_range_g=c.accel_range_g, gyro_range_dps=c.gyro_range_dps,
        accel_bias_ug=list(c.accel_bias_ug), accel_scale_ppm=list(c.accel_scale_ppm),
        gyro_bias_udps=list(c.gyro_bias_udps))


def _from_native_calibration(c: native.ImuCalibration) -> ImuCalibration:
    return ImuCalibration(c.sensor_type, c.accel_range_g, c.gyro_range_dps, tuple(c.accel_bias_ug),
                          tuple(c.accel_scale_ppm), tuple(c.gyro_bias_udps))


def _native_sample(s: SensorDataSample) -> native.ImuSample:
    return native.ImuSample(timestamp_ms=s.timestamp_ms, accel_x=s.accel_x, accel_y=s.accel_y,
                            accel_z=s.accel_z, gyro_x=s.gyro_x, gyro_y=s.gyro_y, gyro_z=s.gyro_z)


def _native_window(w: ImuStaticWindow) -> native.ImuStaticWindow:
    return native.ImuStaticWindow(accel_g=list(w.accel_g), gyro_dps=list(w.gyro_dps),
                                  accel_std_g=w.accel_std_g, gyro_std_dps=w.gyro_std_dps,
                                  samples=w.samples)


def _window(w: native.ImuStaticWindow) -> ImuStaticWindow:
    return ImuStaticWindow(tuple(w.accel_g), tuple(w.gyro_dps), w.accel_std_g, w.gyro_std_dps,
                           w.samples)


@dataclass(frozen=True)
class CalibratedImuSample:
    timestamp_ms: int
    accel_g: tuple[float, float, float]
    gyro_dps: tuple[float, float, float]


@dataclass(frozen=True)
class CalibratedImuBatch:
    sequence_start: int
    frame_count: int
    samples: tuple[CalibratedImuSample, ...]
    applied_components: tuple[str, ...]


def apply_imu_calibration(batch: SensorDataBatch, config: SensorStartInfo,
                          calibration: ImuCalibration, *, accel: bool = True,
                          gyro: bool = True) -> CalibratedImuBatch:
    """Apply to RAW board-frame ADC counts, returning new physical-unit samples.

    Original samples remain untouched. Device/profile/source checks belong to
    open_calibrated_imu_stream(); offline callers must supply original raw data.
    """
    if not isinstance(batch, SensorDataBatch):
        raise ValueError('Expected raw SensorDataBatch, not already calibrated data')
    if any(type(v) is not int or not -32768 <= v <= 32767 for sample in batch.samples
           for v in (sample.accel_x, sample.accel_y, sample.accel_z,
                     sample.gyro_x, sample.gyro_y, sample.gyro_z)):
        raise ValueError('Expected signed i16 raw sensor counts')
    result = call_value(
        native.apply_imu_calibration,
        native.ImuBatch(sequence_start=batch.sequence_start, frame_count=batch.frame_count,
                        sample_size=batch.sample_size,
                        samples=[_native_sample(s) for s in batch.samples]),
        _native_config(config), _to_native_calibration(calibration), accel, gyro)
    return CalibratedImuBatch(
        result.sequence_start, result.frame_count,
        tuple(CalibratedImuSample(s.timestamp_ms, tuple(s.accel_g), tuple(s.gyro_dps))
              for s in result.samples),
        tuple(result.applied_components))


@dataclass(frozen=True)
class ImuStaticWindow:
    accel_g: tuple[float, float, float]
    gyro_dps: tuple[float, float, float]
    accel_std_g: float
    gyro_std_dps: float
    samples: int

    def __post_init__(self) -> None:
        for name in ('accel_g', 'gyro_dps'):
            values = tuple(getattr(self, name))
            if len(values) != 3 or any(not math.isfinite(v) for v in values):
                raise ValueError('Static window must contain finite three-axis values')
            object.__setattr__(self, name, values)
        if (not math.isfinite(self.accel_std_g) or self.accel_std_g < 0 or
                not math.isfinite(self.gyro_std_dps) or self.gyro_std_dps < 0 or
                type(self.samples) is not int or self.samples < 1):
            raise ValueError('Invalid static window statistics')

    @property
    def face(self) -> str:
        return call_value(native.imu_window_face, _native_window(self))


def analyze_imu_static_window(samples: Sequence[SensorDataSample], config: SensorStartInfo, *,
                              check_gyro: bool = True) -> ImuStaticWindow:
    """Reject motion, clipping and insufficient data; thresholds await ring validation."""
    return _window(call_value(native.analyze_imu_static_window, [_native_sample(s) for s in samples],
                              _native_config(config), check_gyro))


async def collect_imu_static_window(client: OpenZiloClient, config: SensorStartInfo, *,
                                     seconds: float = 5.0, settle_seconds: float = 1.0,
                                     check_gyro: bool = True) -> ImuStaticWindow:
    """Collect fresh contiguous samples after a settling period; no raw captures saved."""
    if not math.isfinite(seconds) or not 2 <= seconds <= 120:
        raise ValueError('seconds must be between 2 and 120')
    if not math.isfinite(settle_seconds) or not 0 <= settle_seconds <= 30:
        raise ValueError('Invalid settling time')
    if not 1 <= config.sample_rate_hz <= 1000:
        raise ValueError('Unsupported sampling rate')
    client._drain_queue(0x0605)
    collector = call_value(native.ImuStaticCollector, _native_config(config), round(seconds * 1000),
                           round(settle_seconds * 1000), check_gyro)
    loop = asyncio.get_running_loop()
    call_value(collector.begin, int(loop.time() * 1000))
    while True:
        deadline = collector.next_deadline()
        if deadline is None:
            break
        remaining = (deadline - int(loop.time() * 1000)) / 1000
        if remaining <= 0:
            raise ValueError('Sampling timed out; check the Bluetooth connection')
        batch = await wait_sensor_data(client, timeout_s=min(remaining, 5))
        progress = call_value(collector.accept, native.ImuBatch(
            sequence_start=batch.sequence_start, frame_count=batch.frame_count,
            sample_size=batch.sample_size, samples=[_native_sample(s) for s in batch.samples]),
            int(loop.time() * 1000))
        if progress.phase == native.ImuCollectionPhase.COMPLETE:
            break
    return _window(call_value(collector.finish))


def fit_imu_gyro_bias(previous: ImuCalibration, window: ImuStaticWindow) -> ImuCalibration:
    """Input window must contain RAW samples, not previously corrected samples."""
    return _from_native_calibration(call_value(
        native.fit_imu_gyro_bias, _to_native_calibration(previous), _native_window(window)))


def fit_imu_six_face_calibration(previous: ImuCalibration,
                                 windows: Sequence[ImuStaticWindow]) -> ImuCalibration:
    """Fit a diagonal ellipsoid to six RAW static positions; no cross-axis fit.

    Preserves gyro bias: estimate it from a fresh static window after the faces.
    Uses gravity magnitude, so small fixture tilt is allowed. Six distinct
    dominant signed axes are required; independent validation is mandatory.
    """
    return _from_native_calibration(call_value(
        native.fit_imu_six_face_calibration, _to_native_calibration(previous),
        [_native_window(w) for w in windows]))


def validate_imu_calibration(windows: Sequence[ImuStaticWindow], *, full: bool,
                             component: str = "all") -> dict[str, float]:
    """Validate NEW corrected samples, separate from fitting samples."""
    kinds = {'all': native.CalibrationComponent.ALL, 'accel': native.CalibrationComponent.ACCEL,
             'gyro': native.CalibrationComponent.GYRO}
    if component not in kinds:
        raise ValueError('Unknown validation component')
    result = call_value(native.validate_imu_calibration, [_native_window(w) for w in windows],
                        full, kinds[component])
    return {'max_gravity_error_g': result.max_gravity_error_g,
            'max_gyro_residual_dps': result.max_gyro_residual_dps}

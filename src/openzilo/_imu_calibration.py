# SPDX-License-Identifier: MPL-2.0
"""Software IMU calibration in physical units. No gyro scale or axis rotation fit."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import math
from statistics import mean, pstdev
from typing import Sequence

from ._client import OpenZiloClient
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
        if (any(type(v) is not int for v in (self.sensor_type, self.accel_range_g, self.gyro_range_dps)) or
                self.sensor_type not in (0, 1, 2, 3) or self.accel_range_g not in (2, 4, 8, 16) or
                self.gyro_range_dps not in (0, 125, 250, 500, 1000, 2000)):
            raise ValueError('Invalid sensor identity or ranges')
        for values, low, high in ((self.accel_bias_ug, -200000, 200000),
                                  (self.accel_scale_ppm, 800000, 1200000),
                                  (self.gyro_bias_udps, -20000000, 20000000)):
            if len(values) != 3 or any(type(v) is not int or not low <= v <= high for v in values):
                raise ValueError('Calibration parameters exceed supported bounds')
        for name in ('accel_bias_ug', 'accel_scale_ppm', 'gyro_bias_udps'):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not self.gyro_range_dps and any(self.gyro_bias_udps):
            raise ValueError('Accelerometer-only sensor cannot have gyro bias')

    @classmethod
    def identity(cls, config: SensorStartInfo) -> ImuCalibration:
        """Unknown chip type is 0; never guess a chip identity on legacy firmware."""
        return cls(0, config.accel_range_g, config.gyro_range_dps)


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
    if (config.accel_range_g != calibration.accel_range_g or
            config.gyro_range_dps != calibration.gyro_range_dps):
        raise ValueError('Calibration ranges differ from active IMU configuration')
    if batch.frame_count != len(batch.samples) or batch.sample_size != 16:
        raise ValueError('Invalid raw IMU batch')
    converted = []
    for sample in batch.samples:
        a = (sample.accel_x, sample.accel_y, sample.accel_z)
        g = (sample.gyro_x, sample.gyro_y, sample.gyro_z)
        if any(type(v) is not int or not -32768 <= v <= 32767 for v in (*a, *g)):
            raise ValueError('Expected signed i16 raw sensor counts')
        converted.append(CalibratedImuSample(
            sample.timestamp_ms,
            tuple((v*config.accel_range_g/32768 - (calibration.accel_bias_ug[i]/1e6 if accel else 0)) *
                  (calibration.accel_scale_ppm[i]/1e6 if accel else 1) for i, v in enumerate(a)),
            tuple(v*config.gyro_range_dps/32768 - (calibration.gyro_bias_udps[i]/1e6 if gyro else 0)
                  for i, v in enumerate(g)),
        ))
    components = tuple(name for name, enabled in (('accel', accel), ('gyro', gyro and bool(config.gyro_range_dps)))
                       if enabled)
    return CalibratedImuBatch(batch.sequence_start, batch.frame_count, tuple(converted), components)


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
        axis = max(range(3), key=lambda i: abs(self.accel_g[i]))
        norm = math.sqrt(sum(v*v for v in self.accel_g))
        if not norm or abs(self.accel_g[axis])/norm < 0.8:
            raise ValueError('Orientation is ambiguous between two axes; adjust the case and let it settle')
        return 'XYZ'[axis] + ('+' if self.accel_g[axis] > 0 else '-')


def analyze_imu_static_window(samples: Sequence[SensorDataSample], config: SensorStartInfo, *,
                              check_gyro: bool = True) -> ImuStaticWindow:
    """Reject motion, clipping and insufficient data; thresholds await ring validation."""
    if config.sample_rate_hz <= 0 or config.accel_range_g <= 0:
        raise ValueError('Invalid IMU sampling configuration')
    if len(samples) < max(20, config.sample_rate_hz * 2):
        raise ValueError('Not enough valid samples; keep the ring still for longer')
    axes = [(s.accel_x, s.accel_y, s.accel_z, s.gyro_x, s.gyro_y, s.gyro_z) for s in samples]
    if any(abs(v) >= 32760 for row in axes for v in (row if check_gyro else row[:3])):
        raise ValueError('Sensor data is saturated; calibration cannot proceed')
    acc = [tuple(row[i] * config.accel_range_g/32768 for row in axes) for i in range(3)]
    gyr = [tuple(row[i+3] * config.gyro_range_dps/32768 for row in axes) for i in range(3)]
    a, g = tuple(map(mean, acc)), tuple(map(mean, gyr))
    ast, gst = max(map(pstdev, acc)), max(map(pstdev, gyr))
    if not 0.7 < math.sqrt(sum(v*v for v in a)) < 1.3:
        raise ValueError('Acceleration magnitude is not near gravity; check mounting, units and sensor ranges')
    if check_gyro and max(map(abs, g)) > 20:
        raise ValueError('Stationary angular velocity exceeds the supported bias range; check mounting, ranges and the sensor')
    if (ast > 0.008 or (check_gyro and gst > 0.3) or
            any(max(v)-min(v) > 0.06 for v in acc)):
        raise ValueError(f'Motion or vibration detected: accel standard deviation {ast:.4f} g, gyro standard deviation {gst:.3f} deg/s, '
                         f'accel peak-to-peak {max(max(v)-min(v) for v in acc):.4f} g. Keep the ring still and retry')
    # Detect slow drift/heating within the window, not just high-frequency noise.
    half = len(samples)//2
    if any(abs(mean(v[:half])-mean(v[half:])) > 0.003 for v in acc) or (check_gyro and any(
            abs(mean(v[:half])-mean(v[half:])) > 0.15 for v in gyr)):
        raise ValueError('Readings are still drifting; wait for them to stabilize and retry')
    return ImuStaticWindow(a, g, ast, gst, len(samples))


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
    skip, target = math.ceil(settle_seconds*config.sample_rate_hz), math.ceil(seconds*config.sample_rate_hz)
    samples: list[SensorDataSample] = []
    sequence = None
    deadline = asyncio.get_running_loop().time() + settle_seconds + seconds + 10
    while len(samples) < target:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise ValueError('Sampling timed out; check the Bluetooth connection')
        batch = await wait_sensor_data(client, timeout_s=min(remaining, 5))
        if not batch.samples:
            raise ValueError('Received an empty sensor batch')
        if sequence is not None and batch.sequence_start != sequence:
            raise ValueError('Sample sequence gap detected; ensure a stable connection and retry')
        sequence = (batch.sequence_start + batch.frame_count) & 0xFFFFFFFF
        for sample in batch.samples:
            if skip:
                skip -= 1
            elif len(samples) < target:
                samples.append(sample)
    return analyze_imu_static_window(samples, config, check_gyro=check_gyro)


def fit_imu_gyro_bias(previous: ImuCalibration, window: ImuStaticWindow) -> ImuCalibration:
    """Input window must contain RAW samples, not previously corrected samples."""
    if not previous.gyro_range_dps:
        raise ValueError('This sensor has no gyroscope')
    result = replace(previous, gyro_bias_udps=tuple(round(v*1000000) for v in window.gyro_dps))
    return result


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    n = len(rhs)
    m = [list(row)+[value] for row, value in zip(matrix, rhs)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-7:
            raise ValueError('Six-face data does not support a stable fit; collect the faces again')
        m[col], m[pivot] = m[pivot], m[col]
        scale = m[col][col]
        m[col] = [v/scale for v in m[col]]
        for row in range(n):
            if row == col:
                continue
            factor = m[row][col]
            m[row] = [a-factor*b for a, b in zip(m[row], m[col])]
    return [row[-1] for row in m]


def fit_imu_six_face_calibration(previous: ImuCalibration,
                                 windows: Sequence[ImuStaticWindow]) -> ImuCalibration:
    """Fit a diagonal ellipsoid to six RAW static positions; no cross-axis fit.

    Preserves gyro bias: estimate it from a fresh static window after the faces.
    Uses gravity magnitude, so small fixture tilt is allowed. Six distinct
    dominant signed axes are required; independent validation is mandatory.
    """
    if len(windows) != 6 or {w.face for w in windows} != {'X+', 'X-', 'Y+', 'Y-', 'Z+', 'Z-'}:
        raise ValueError('Six distinct orientations are required, each with a stable data window')
    rows = [[*(v*v for v in w.accel_g), *w.accel_g] for w in windows]
    q = _solve(rows, [1.0]*6)
    if any(v <= 0 or not math.isfinite(v) for v in q[:3]):
        raise ValueError('Calibration fit is invalid; check the six-face recordings')
    bias = [-q[i+3]/(2*q[i]) for i in range(3)]
    denominator = 1 + sum(q[i]*bias[i]*bias[i] for i in range(3))
    gains = [math.sqrt(q[i]/denominator) for i in range(3)]
    result = replace(previous,
                     accel_bias_ug=tuple(round(v*1000000) for v in bias),
                     accel_scale_ppm=tuple(round(v*1000000) for v in gains))
    return result


def validate_imu_calibration(windows: Sequence[ImuStaticWindow], *, full: bool,
                             component: str = "all") -> dict[str, float]:
    """Validate NEW corrected samples, separate from fitting samples."""
    if component not in ('all', 'accel', 'gyro'):
        raise ValueError('Unknown validation component')
    if len(windows) < (3 if full else 1):
        raise ValueError('Not enough independent validation data')
    if full:
        if len({w.face for w in windows}) < 3:
            raise ValueError('Use at least three distinct orientations for validation')
        if len({w.face[0] for w in windows}) < 3:
            raise ValueError('Validation must cover all three axes')
    gravity_error = max(abs(math.sqrt(sum(v*v for v in w.accel_g))-1) for w in windows)
    gyro_error = max(abs(v) for w in windows for v in w.gyro_dps)
    if ((component != 'gyro' and (full or component == 'accel') and gravity_error > 0.015) or
            (component != 'accel' and gyro_error > 0.15)):
        raise ValueError(f'Validation failed: gravity magnitude error {gravity_error:.4f} g, gyro residual {gyro_error:.3f} deg/s')
    return {'max_gravity_error_g': gravity_error, 'max_gyro_residual_dps': gyro_error}

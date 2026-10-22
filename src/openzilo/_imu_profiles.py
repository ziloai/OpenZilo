# SPDX-License-Identifier: MPL-2.0
"""Local software profiles and an explicit calibrated IMU stream. No device writes."""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import AsyncIterator

from ._cli_config import config_path
from ._client import OpenZiloClient
from ._compatibility import get_device_capabilities
from ._device import get_system_info
from ._errors import CompatibilityError, ProtocolError, TransportError
from ._imu_calibration import CalibratedImuBatch, ImuCalibration, apply_imu_calibration
from ._sensor import SensorStartInfo, start_sensor_report, stop_sensor_report, wait_sensor_data


def imu_device_key(device_id: str) -> str:
    """Local binding key; identifiers are hashed rather than embedded in profiles."""
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError('A device address/identifier is required')
    return hashlib.sha256(device_id.strip().casefold().encode('utf-8')).hexdigest()


def imu_calibration_path(device_id: str) -> Path:
    """Per-device profile next to CLI preferences, outside the source checkout."""
    return config_path().parent / 'imu' / (imu_device_key(device_id) + '.json')


@dataclass(frozen=True)
class ImuCalibrationProfile:
    device_key: str
    firmware_version: str
    model: str
    calibration: ImuCalibration
    accel_validated: bool = False
    gyro_validated: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if (not isinstance(self.device_key, str) or len(self.device_key) != 64 or
                any(c not in '0123456789abcdef' for c in self.device_key)):
            raise ValueError('Invalid profile device key')
        if not isinstance(self.firmware_version, str) or not self.firmware_version:
            raise ValueError('Missing firmware identity')
        if not isinstance(self.model, str) or not self.model:
            raise ValueError('Missing device model')
        if not isinstance(self.calibration, ImuCalibration):
            raise ValueError('Invalid calibration parameters')
        if type(self.accel_validated) is not bool or type(self.gyro_validated) is not bool:
            raise ValueError('Invalid component validation flags')
        if not (self.accel_validated or self.gyro_validated):
            raise ValueError('A profile must have at least one validated component')
        c = self.calibration
        if not self.accel_validated and (any(c.accel_bias_ug) or c.accel_scale_ppm != (1000000,)*3):
            raise ValueError('Unvalidated accelerometer parameters must be identity')
        if not self.gyro_validated and any(c.gyro_bias_udps):
            raise ValueError('Unvalidated gyro parameters must be zero')
        if self.gyro_validated and not c.gyro_range_dps:
            raise ValueError('Cannot validate gyro on an accelerometer-only sensor')
        try:
            if datetime.fromisoformat(self.created_at).tzinfo is None:
                raise ValueError('Profile date must include timezone')
        except (TypeError, ValueError) as exc:
            raise ValueError('Invalid profile creation date') from exc

    def check_device(self, device_id: str, firmware_version: str, model: str) -> None:
        if self.device_key != imu_device_key(device_id):
            raise CompatibilityError('IMU profile belongs to another device')
        if self.firmware_version != firmware_version or self.model != model:
            raise CompatibilityError('IMU profile firmware/model differs; recalibrate after upgrading')

    def apply(self, batch, config: SensorStartInfo) -> CalibratedImuBatch:
        return apply_imu_calibration(batch, config, self.calibration,
                                     accel=self.accel_validated, gyro=self.gyro_validated)


def save_imu_calibration_profile(profile: ImuCalibrationProfile, path: Path) -> None:
    """Atomically replace a local profile. Call only after independent validation."""
    path = Path(path)
    payload = {'schema_version': 1, 'application': 'software', 'input_domain': 'board_adc_counts',
               'bias_accel_unit': 'micro_g', 'bias_gyro_unit': 'micro_deg_per_s',
               'scale_unit': 'ppm', **asdict(profile)}
    encoded = json.dumps(payload, indent=2, allow_nan=False) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.imu-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_imu_calibration_profile(path: Path) -> ImuCalibrationProfile:
    """Strict schema/units checking; malformed profiles never silently disable correction."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        metadata = {'schema_version': 1, 'application': 'software', 'input_domain': 'board_adc_counts',
                    'bias_accel_unit': 'micro_g', 'bias_gyro_unit': 'micro_deg_per_s', 'scale_unit': 'ppm'}
        if not isinstance(data, dict) or type(data.get('schema_version')) is not int:
            raise ValueError('Invalid profile object')
        for key, expected in metadata.items():
            if data.pop(key, None) != expected:
                raise ValueError(f'Unsupported IMU profile {key}')
        c = data.pop('calibration')
        if not isinstance(c, dict):
            raise ValueError('Invalid calibration record')
        for key in ('accel_bias_ug', 'accel_scale_ppm', 'gyro_bias_udps'):
            c[key] = tuple(c[key])
        return ImuCalibrationProfile(calibration=ImuCalibration(**c), **data)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f'Invalid IMU calibration profile: {exc}') from exc


async def require_software_imu_source(client: OpenZiloClient) -> None:
    """Only consume supported raw IMU contracts; refuse firmware calibration layers."""
    caps = await get_device_capabilities(client)
    caps.require('imu')
    if any(f.name in ('imu_calibration', 'unknown_11') for f in caps.features):
        raise CompatibilityError('Firmware advertises IMU calibration; software correction is disabled '
                                 'until an explicit raw-data contract is supported')


class CalibratedImuStream:
    """Physical-unit view of raw batches; only valid inside its opening context."""
    def __init__(self, client, config, profile):
        self.config = config
        self.profile = profile
        self._client = client
        self._connection = client._connection_token
        self._closed = False

    def __aiter__(self):
        return self

    async def __anext__(self) -> CalibratedImuBatch:
        if self._closed:
            raise StopAsyncIteration
        if self._client._connection_token is not self._connection:
            raise TransportError('Connection changed; reopen the calibrated IMU stream')
        batch = await wait_sensor_data(self._client)
        if self._client._connection_token is not self._connection:
            raise TransportError('Connection changed while receiving IMU data')
        return self.profile.apply(batch, self.config)


@asynccontextmanager
async def open_calibrated_imu_stream(client: OpenZiloClient, profile: ImuCalibrationProfile | None = None,
                                     *, device_id: str | None = None) -> AsyncIterator[CalibratedImuStream]:
    """Start/stop a software-corrected stream using a matching local profile.

    No calibration commands are sent. Old raw APIs remain unchanged. Do not run
    another IMU consumer on the same connection while this context owns reports.
    """
    if getattr(client, '_software_imu_stream_active', False):
        raise ProtocolError('A software IMU stream already owns this client')
    client._software_imu_stream_active = True
    stream = None
    started = False
    connection = client._connection_token
    try:
        await require_software_imu_source(client)
        identifier = device_id or getattr(client.transport, 'address', None)
        if profile is None:
            profile = load_imu_calibration_profile(imu_calibration_path(identifier))
        info = await get_system_info(client)
        profile.check_device(identifier, info.firmware_version, info.model)
        started = True
        config = await start_sensor_report(client)
        if (config.accel_range_g != profile.calibration.accel_range_g or
                config.gyro_range_dps != profile.calibration.gyro_range_dps):
            raise CompatibilityError('IMU profile range differs from device configuration')
        if connection is not client._connection_token:
            raise TransportError('Connection changed while opening IMU stream')
        client._drain_queue(0x0605)
        stream = CalibratedImuStream(client, config, profile)
        yield stream
    finally:
        if stream:
            stream._closed = True
        try:
            if started and connection is client._connection_token:
                await stop_sensor_report(client)
        finally:
            client._software_imu_stream_active = False

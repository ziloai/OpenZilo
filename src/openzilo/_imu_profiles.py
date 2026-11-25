# SPDX-License-Identifier: MPL-2.0
"""Local software profiles and an explicit calibrated IMU stream. No device writes."""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
from typing import AsyncIterator

from ._cli_config import config_path
from ._client import OpenZiloClient
from ._compatibility import get_device_capabilities, _native_features
from ._core import native, call, call_value
from ._device import get_system_info
from ._errors import CompatibilityError, ProtocolError, TransportError
from ._imu_calibration import (
    CalibratedImuBatch, ImuCalibration, _from_native_calibration, _to_native_calibration,
    apply_imu_calibration,
)
from ._sensor import SensorStartInfo, start_sensor_report, stop_sensor_report, wait_sensor_data


def imu_device_key(device_id: str) -> str:
    """Local binding key; identifiers are hashed rather than embedded in profiles."""
    if not isinstance(device_id, str):
        raise ValueError('A device address/identifier is required')
    return call_value(native.local_device_key, device_id)


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
        if not isinstance(self.device_key, str):
            raise ValueError('Invalid profile device key')
        if not isinstance(self.firmware_version, str) or not self.firmware_version:
            raise ValueError('Missing firmware identity')
        if not isinstance(self.model, str) or not self.model:
            raise ValueError('Missing device model')
        if not isinstance(self.calibration, ImuCalibration):
            raise ValueError('Invalid calibration parameters')
        if type(self.accel_validated) is not bool or type(self.gyro_validated) is not bool:
            raise ValueError('Invalid component validation flags')
        if not isinstance(self.created_at, str):
            raise ValueError('Invalid profile creation date')
        call_value(native.validate_calibration_profile, self._native())

    def _native(self) -> native.CalibrationProfile:
        return native.CalibrationProfile(
            binding=native.ProfileBinding.LOCAL_LOCATOR, device_key=self.device_key,
            firmware_version=self.firmware_version, model=self.model,
            calibration=_to_native_calibration(self.calibration),
            accel_validated=self.accel_validated, gyro_validated=self.gyro_validated,
            created_at=self.created_at)

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
    encoded = call_value(native.serialize_calibration_profile, profile._native())
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
        text = Path(path).read_text(encoding='utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError(f'Invalid IMU calibration profile: {exc}') from exc
    try:
        parsed = native.parse_calibration_profile(text)
        if parsed.binding != native.ProfileBinding.LOCAL_LOCATOR:
            raise ValueError('Portable device-identity profiles are not supported here')
        return ImuCalibrationProfile(
            parsed.device_key, parsed.firmware_version, parsed.model,
            _from_native_calibration(parsed.calibration), parsed.accel_validated,
            parsed.gyro_validated, parsed.created_at)
    except (native.CoreError, ValueError) as exc:
        raise ValueError(f'Invalid IMU calibration profile: {exc}') from exc


async def require_software_imu_source(client: OpenZiloClient) -> None:
    """Only consume supported raw IMU contracts; refuse firmware calibration layers."""
    caps = await get_device_capabilities(client)
    caps.require('imu')
    call(native.require_raw_imu_source, _native_features(caps.features))


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

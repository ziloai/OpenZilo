# SPDX-License-Identifier: MPL-2.0
"""Host-managed IMU calibration repository for Connect host mode.

Mirrors OpenZilo Connect's CalibrationStore: keyed by ``stable_device_key(info)``
so every authorized client receives consistent calibrated physical IMU streams
(``g`` and ``deg/s``) without exposing raw serial numbers or CPU IDs.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

from ._cli_config import config_path
from ._core import native


def default_calibration_store_path() -> Path:
    return config_path().parent / "connect" / "imu-calibrations.json"


class ConnectCalibrationStore:
    """Thread-safe local JSON repository for host IMU calibration & mount alignment."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else default_calibration_store_path()
        self._lock = threading.RLock()
        self._data: dict[str, Any] = self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, UnicodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".connect-cal-", dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self._data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    @staticmethod
    def _device_key(info: native.DeviceInfo | None) -> str | None:
        if info is None:
            return None
        try:
            return native.stable_device_key(info)
        except Exception:
            return None

    def active_profile(
        self,
        info: native.DeviceInfo,
        config: native.ImuConfig,
        features: list[native.FeatureVersion],
    ) -> native.CalibrationProfile | None:
        with self._lock:
            key = self._device_key(info)
            if not key:
                return None
            profile_json = self._data.get(key)
            if not isinstance(profile_json, str):
                return None
            try:
                profile = native.parse_calibration_profile(profile_json)
                native.check_profile_device(profile, info, None, config, features)
                return profile
            except Exception:
                return None

    def calibrated_components(self, info: native.DeviceInfo | None) -> list[str]:
        with self._lock:
            key = self._device_key(info)
            if not key or info is None:
                return []
            has_mount = f"mount:{key}" in self._data
            has_direct_gyro = f"gyro_bias:{key}" in self._data
            profile_json = self._data.get(key)
            profile = None
            if isinstance(profile_json, str):
                try:
                    parsed = native.parse_calibration_profile(profile_json)
                    if parsed.model == info.model and parsed.firmware_version == info.firmware_version:
                        profile = parsed
                except Exception:
                    profile = None
            components: list[str] = []
            if profile is not None and profile.accel_validated:
                components.append("accel")
            if (profile is not None and profile.gyro_validated) or has_direct_gyro:
                components.append("gyro")
            if has_mount:
                components.append("mount")
            return components

    def _load_direct_gyro_bias(self, key: str) -> list[float] | None:
        raw = self._data.get(f"gyro_bias:{key}")
        if not isinstance(raw, list) or len(raw) != 3:
            return None
        try:
            values = [float(v) for v in raw]
        except (TypeError, ValueError):
            return None
        if all(math.isfinite(v) and abs(v) <= 60.0 for v in values):
            return values
        return None

    def gyro_bias_dps(self, info: native.DeviceInfo | None) -> list[float] | None:
        with self._lock:
            key = self._device_key(info)
            if not key or info is None:
                return None
            direct = self._load_direct_gyro_bias(key)
            if direct is not None:
                return direct
            profile_json = self._data.get(key)
            if not isinstance(profile_json, str):
                return None
            try:
                profile = native.parse_calibration_profile(profile_json)
            except Exception:
                return None
            if (
                not profile.gyro_validated
                or profile.model != info.model
                or profile.firmware_version != info.firmware_version
            ):
                return None
            return [profile.calibration.gyro_bias_udps[i] / 1_000_000.0 for i in range(3)]

    def save_mount_alignment(self, info: native.DeviceInfo, mount: native.Quaternion) -> None:
        with self._lock:
            key = native.stable_device_key(info)
            self._data[f"mount:{key}"] = [float(mount.w), float(mount.x), float(mount.y), float(mount.z)]
            self._save()

    def load_mount_alignment(self, info: native.DeviceInfo | None) -> native.Quaternion | None:
        with self._lock:
            key = self._device_key(info)
            if not key:
                return None
            raw = self._data.get(f"mount:{key}")
            if not isinstance(raw, list) or len(raw) != 4:
                return None
            try:
                return native.Quaternion(
                    w=float(raw[0]),
                    x=float(raw[1]),
                    y=float(raw[2]),
                    z=float(raw[3]),
                )
            except (TypeError, ValueError):
                return None

    def reset_calibration(self, info: native.DeviceInfo) -> None:
        with self._lock:
            key = native.stable_device_key(info)
            self._data.pop(key, None)
            self._data.pop(f"mount:{key}", None)
            self._data.pop(f"gyro_bias:{key}", None)
            self._save()

    def apply_or_convert(
        self,
        batch: native.ImuBatch,
        info: native.DeviceInfo | None,
        config: native.ImuConfig,
        features: list[native.FeatureVersion],
    ) -> native.PhysicalImuBatch:
        with self._lock:
            profile = self.active_profile(info, config, features) if info is not None else None
            if profile is not None:
                return native.apply_imu_calibration(
                    batch,
                    config,
                    profile.calibration,
                    profile.accel_validated,
                    profile.gyro_validated,
                )
            raw_physical = native.raw_imu_to_physical(batch, config)
            key = self._device_key(info)
            direct_bias = self._load_direct_gyro_bias(key) if key else None
            if direct_bias is None:
                return raw_physical
            adjusted = [
                native.PhysicalImuSample(
                    timestamp_ms=s.timestamp_ms,
                    accel_g=list(s.accel_g),
                    gyro_dps=[
                        s.gyro_dps[0] - direct_bias[0],
                        s.gyro_dps[1] - direct_bias[1],
                        s.gyro_dps[2] - direct_bias[2],
                    ],
                )
                for s in raw_physical.samples
            ]
            applied = list(dict.fromkeys([*raw_physical.applied_components, "gyro"]))
            return native.PhysicalImuBatch(
                sequence_start=raw_physical.sequence_start,
                frame_count=raw_physical.frame_count,
                samples=adjusted,
                applied_components=applied,
            )

    def save_gyro_bias_window(
        self,
        info: native.DeviceInfo,
        config: native.ImuConfig,
        features: list[native.FeatureVersion],
        window: native.ImuStaticWindow,
    ) -> None:
        with self._lock:
            key = native.stable_device_key(info)
            self._data[f"gyro_bias:{key}"] = [
                float(window.gyro_dps[0]),
                float(window.gyro_dps[1]),
                float(window.gyro_dps[2]),
            ]
            try:
                existing = self.active_profile(info, config, features)
                base_cal = existing.calibration if existing is not None else native.identity_imu_calibration(config)
                updated_cal = native.fit_imu_gyro_bias(base_cal, window)
                now_rfc3339 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                profile = native.CalibrationProfile(
                    binding=native.ProfileBinding.DEVICE_IDENTITY,
                    device_key=key,
                    firmware_version=info.firmware_version,
                    model=info.model,
                    calibration=updated_cal,
                    accel_validated=existing.accel_validated if existing is not None else False,
                    gyro_validated=True,
                    created_at=now_rfc3339,
                )
                self._data[key] = native.serialize_calibration_profile(profile)
            except Exception:
                pass
            self._save()

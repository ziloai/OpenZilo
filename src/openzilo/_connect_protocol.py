# SPDX-License-Identifier: MPL-2.0
"""OpenZilo Connect API v2 contract, policy tables, and typed payloads."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import Enum
from typing import Any

API_VERSION = 2
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7420
MAX_ARGUMENTS_BYTES = 5120
MAX_PACKET_BODY_BYTES = 5120
MAX_FIRMWARE_BYTES = 600 * 1024
MAX_ACTIVE_OPS_PER_CLIENT = 4
MAX_ACTIVE_OPS_TOTAL = 32
MAX_SUBSCRIPTIONS_TOTAL = 32
EVENT_QUEUE_SIZE = 64

SCOPES: frozenset[str] = frozenset({
    "info",
    "recording",
    "audio",
    "sensors",
    "logs",
    "time",
    "firmware",
})

OPERATION_SCOPES: dict[str, str] = {
    "system.info": "info",
    "capabilities": "info",
    "connection.rssi": "info",
    "recording.config": "recording",
    "recording.configure": "recording",
    "recording.start": "recording",
    "recording.stop": "recording",
    "recording.status": "recording",
    "audio.count": "audio",
    "audio.info": "audio",
    "audio.quick": "audio",
    "audio.read": "audio",
    "audio.end": "audio",
    "audio.clear": "audio",
    "live.subscribe": "audio",
    "imu.start": "sensors",
    "imu.stop": "sensors",
    "imu.attitude.zero": "sensors",
    "imu.attitude.mapping": "sensors",
    "imu.calibration": "sensors",
    "imu.calibrate.gyro": "sensors",
    "imu.calibrate.upright": "sensors",
    "imu.calibration.reset": "sensors",
    "logs.storage": "logs",
    "logs.read": "logs",
    "time.reply": "time",
    "firmware.upgrade": "firmware",
}

TOPIC_SCOPES: dict[str, str] = {
    "status": "info",
    "imu": "sensors",
    "gesture": "sensors",
    "live": "audio",
    "audio": "audio",
    "recording": "recording",
    "time": "time",
}


def require_scopes(requested: set[str]) -> set[str]:
    if not requested or len(requested) > len(SCOPES) or not requested.issubset(SCOPES):
        raise ValueError("Unknown or empty permissions")
    return set(requested)


def operation_scope(operation: str) -> str:
    scope = OPERATION_SCOPES.get(operation)
    if scope is None:
        raise ValueError(f"Unknown operation: {operation}")
    return scope


def topic_scope(topic: str) -> str:
    scope = TOPIC_SCOPES.get(topic)
    if scope is None:
        raise ValueError(f"Unknown topic: {topic}")
    return scope


def command_topic(command: int) -> str | None:
    if command == 0x0605:
        return "imu"
    if 0x0701 <= command <= 0x0704:
        return "gesture"
    if 0x050F <= command <= 0x0511:
        return "live"
    if command == 0x050A:
        return "recording"
    if command in (0x0504, 0x0505, 0x0508):
        return "audio"
    if command == 0x0401:
        return "time"
    return None


def encode_bytes(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def decode_bytes(value: str | bytes | bytearray) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if not isinstance(value, str):
        raise ValueError("Expected base64 string for binary field")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except Exception as exc:
        raise ValueError("Invalid base64 binary payload") from exc


class RingPostureKind(str, Enum):
    HORIZONTAL_UPRIGHT = "HORIZONTAL_UPRIGHT"
    HORIZONTAL_FLIPPED = "HORIZONTAL_FLIPPED"
    VERTICAL_STANDING_EDGE = "VERTICAL_STANDING_EDGE"
    VERTICAL_BORE_AXIS = "VERTICAL_BORE_AXIS"
    TILTED = "TILTED"
    DYNAMIC_MOTION = "DYNAMIC_MOTION"


class RingAxisPresetKind(str, Enum):
    STANDARD = "STANDARD"
    SWAPPED_XY = "SWAPPED_XY"
    Z_BORE = "Z_BORE"


@dataclass(frozen=True)
class ConnectStatus:
    phase: str
    device_name: str
    model: str | None
    firmware_version: str | None
    board_target: str | None
    battery_percent: int | None
    charging: bool
    ring_key: str | None
    calibrated_components: tuple[str, ...]
    gyro_bias_dps: tuple[float, ...] | None
    message: str | None
    firmware_progress: int | None = None

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> "ConnectStatus":
        if data.get("apiVersion") != API_VERSION:
            raise ValueError("Unsupported Connect API version")
        battery = data.get("batteryPercent")
        gyro_bias = data.get("gyroBiasDps")
        return cls(
            phase=str(data.get("phase") or "disconnected"),
            device_name=str(data.get("deviceName") or ""),
            model=data.get("model"),
            firmware_version=data.get("firmwareVersion"),
            board_target=data.get("boardTarget"),
            battery_percent=int(battery) if battery is not None else None,
            charging=bool(data.get("charging", False)),
            ring_key=data.get("ringKey"),
            calibrated_components=tuple(data.get("calibratedComponents") or ()),
            gyro_bias_dps=tuple(float(v) for v in gyro_bias) if gyro_bias is not None else None,
            message=data.get("message"),
            firmware_progress=int(data["firmwareProgress"]) if data.get("firmwareProgress") is not None else None,
        )


@dataclass(frozen=True)
class ImuConfigInfo:
    sample_rate_hz: int
    accel_range_g: int
    gyro_range_dps: int


@dataclass(frozen=True)
class ImuSampleData:
    timestamp_ms: int
    ax_g: float
    ay_g: float
    az_g: float
    gx_dps: float
    gy_dps: float
    gz_dps: float


@dataclass(frozen=True)
class ImuAttitudeData:
    qw: float
    qx: float
    qy: float
    qz: float
    roll_deg: float
    pitch_deg: float
    yaw_deg: float
    tilt_from_zenith_deg: float
    posture: RingPostureKind
    opengl_matrix: tuple[float, ...]
    stationary: bool
    wx_dps: float = 0.0
    wy_dps: float = 0.0
    wz_dps: float = 0.0


@dataclass(frozen=True)
class ImuBatchEvent:
    sequence_start: int
    samples: tuple[ImuSampleData, ...]
    applied_components: tuple[str, ...]
    attitude: ImuAttitudeData | None
    trajectory_quaternions: tuple[float, ...] | None = None


@dataclass(frozen=True)
class DoubleTapGesture:
    timestamp: int


@dataclass(frozen=True)
class SensorGesture:
    timestamp: int
    gesture_id: int
    name: str


@dataclass(frozen=True)
class ButtonDoubleClickGesture:
    timestamp: int


@dataclass(frozen=True)
class ButtonSingleClickGesture:
    timestamp: int


RingGestureEvent = (
    DoubleTapGesture | SensorGesture | ButtonDoubleClickGesture | ButtonSingleClickGesture
)


@dataclass(frozen=True)
class LiveAudioStarted:
    session_id: int
    sample_rate: int
    channels: int


@dataclass(frozen=True)
class LiveAudioFrame:
    session_id: int
    sequence: int
    data: bytes


@dataclass(frozen=True)
class LiveAudioEnded:
    session_id: int
    byte_count: int


@dataclass(frozen=True)
class LiveAudioInterrupted:
    pass


LiveAudioEvent = LiveAudioStarted | LiveAudioFrame | LiveAudioEnded | LiveAudioInterrupted


@dataclass(frozen=True)
class ConnectEvent:
    topic: str
    data: dict[str, Any]

    def live_audio(self) -> LiveAudioEvent | None:
        if self.topic != "live":
            return None
        if self.data.get("apiVersion") != API_VERSION:
            raise ValueError("Unsupported Connect API version")
        kind = self.data.get("type")
        if kind == "started":
            session_id = int(self.data["sessionId"])
            sample_rate = int(self.data["sampleRate"])
            channels = int(self.data["channels"])
            if session_id <= 0 or sample_rate != 16000 or channels not in (1, 2):
                raise ValueError("Invalid live audio started event")
            return LiveAudioStarted(session_id=session_id, sample_rate=sample_rate, channels=channels)
        if kind == "frame":
            session_id = int(self.data["sessionId"])
            sequence = int(self.data.get("sequence", -1))
            raw = decode_bytes(self.data["data"])
            if session_id <= 0 or sequence < 0 or not (1 <= len(raw) <= 100):
                raise ValueError("Invalid live audio frame event")
            return LiveAudioFrame(session_id=session_id, sequence=sequence, data=raw)
        if kind == "ended":
            session_id = int(self.data["sessionId"])
            byte_count = int(self.data.get("byteCount", -1))
            if session_id <= 0 or byte_count < 0:
                raise ValueError("Invalid live audio ended event")
            return LiveAudioEnded(session_id=session_id, byte_count=byte_count)
        if kind == "interrupted":
            return LiveAudioInterrupted()
        raise ValueError(f"Unknown live audio event: {kind!r}")

    def imu_batch(self) -> ImuBatchEvent | None:
        if self.topic != "imu":
            return None
        if self.data.get("apiVersion") != API_VERSION:
            raise ValueError("Unsupported Connect API version")
        ts = self.data.get("timestampsMs")
        accel = self.data.get("accelG")
        gyro = self.data.get("gyroDps")
        if not isinstance(ts, list) or not isinstance(accel, list) or not isinstance(gyro, list):
            return None
        if len(accel) != len(ts) * 3 or len(gyro) != len(ts) * 3:
            return None
        samples = tuple(
            ImuSampleData(
                timestamp_ms=int(ts[i]),
                ax_g=float(accel[i * 3]),
                ay_g=float(accel[i * 3 + 1]),
                az_g=float(accel[i * 3 + 2]),
                gx_dps=float(gyro[i * 3]),
                gy_dps=float(gyro[i * 3 + 1]),
                gz_dps=float(gyro[i * 3 + 2]),
            )
            for i in range(len(ts))
        )
        q = self.data.get("quaternion")
        euler = self.data.get("eulerDeg")
        gyro_body = self.data.get("gyroBodyDps")
        gl_mat = self.data.get("openGlMatrix")
        posture_name = self.data.get("posture")
        attitude: ImuAttitudeData | None = None
        if (
            isinstance(q, list) and len(q) == 4
            and isinstance(euler, list) and len(euler) == 3
            and isinstance(gl_mat, list) and len(gl_mat) == 16
            and isinstance(posture_name, str)
        ):
            try:
                posture = RingPostureKind(posture_name)
            except ValueError:
                posture = RingPostureKind.TILTED
            attitude = ImuAttitudeData(
                qw=float(q[0]),
                qx=float(q[1]),
                qy=float(q[2]),
                qz=float(q[3]),
                roll_deg=float(euler[0]),
                pitch_deg=float(euler[1]),
                yaw_deg=float(euler[2]),
                tilt_from_zenith_deg=float(self.data.get("tiltFromZenithDeg", 0.0)),
                posture=posture,
                opengl_matrix=tuple(float(v) for v in gl_mat),
                stationary=bool(self.data.get("stationary", False)),
                wx_dps=float(gyro_body[0]) if isinstance(gyro_body, list) and len(gyro_body) >= 1 else 0.0,
                wy_dps=float(gyro_body[1]) if isinstance(gyro_body, list) and len(gyro_body) >= 2 else 0.0,
                wz_dps=float(gyro_body[2]) if isinstance(gyro_body, list) and len(gyro_body) >= 3 else 0.0,
            )
        traj = self.data.get("trajectoryQuaternions")
        traj_tuple = (
            tuple(float(v) for v in traj)
            if isinstance(traj, list) and len(traj) == len(samples) * 4
            else None
        )
        return ImuBatchEvent(
            sequence_start=int(self.data.get("sequenceStart", 0)),
            samples=samples,
            applied_components=tuple(self.data.get("appliedComponents") or ()),
            attitude=attitude,
            trajectory_quaternions=traj_tuple,
        )

    def gesture_event(self) -> RingGestureEvent | None:
        if self.topic != "gesture":
            return None
        if self.data.get("apiVersion") != API_VERSION:
            raise ValueError("Unsupported Connect API version")
        command = int(self.data.get("command", 0))
        if "timestamp" in self.data:
            ts = int(self.data["timestamp"])
        else:
            body_raw = self.data.get("body")
            if body_raw is None:
                return None
            body = decode_bytes(body_raw)
            if len(body) < 4:
                return None
            ts = int.from_bytes(body[:4], "big")
        if command == 0x0701:
            return DoubleTapGesture(timestamp=ts)
        if command == 0x0702:
            return SensorGesture(
                timestamp=ts,
                gesture_id=int(self.data.get("gestureId", 0)),
                name=str(self.data.get("gestureName") or "unknown"),
            )
        if command == 0x0703:
            return ButtonDoubleClickGesture(timestamp=ts)
        if command == 0x0704:
            return ButtonSingleClickGesture(timestamp=ts)
        return None

    def status_snapshot(self) -> ConnectStatus | None:
        if self.topic != "status":
            return None
        return ConnectStatus.from_payload(self.data)

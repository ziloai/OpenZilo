# SPDX-License-Identifier: MPL-2.0
"""IMU reports and gesture/button events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from ._errors import ProtocolError
from ._protocol import SensorCommand
from ._client import OpenZiloClient
from ._core import native, call


class SensorGestureId(IntEnum):
    IDLE = 0
    ROTATE_BACK = 1
    ROTATE_FRONT = 2
    WAVE = 3


@dataclass(frozen=True)
class SensorStartInfo:
    sample_rate_hz: int
    accel_range_g: int
    gyro_range_dps: int


@dataclass(frozen=True)
class SensorStopInfo:
    pass


@dataclass(frozen=True)
class SensorDataSample:
    timestamp_ms: int
    accel_x: int
    accel_y: int
    accel_z: int
    gyro_x: int
    gyro_y: int
    gyro_z: int


@dataclass(frozen=True)
class SensorDataBatch:
    sequence_start: int
    frame_count: int
    sample_size: int
    samples: tuple[SensorDataSample, ...]


@dataclass(frozen=True)
class SensorDoubleTapEvent:
    timestamp_ms: int


@dataclass(frozen=True)
class SensorGestureEvent:
    timestamp_ms: int
    gesture_id: int


@dataclass(frozen=True)
class SensorKeyDoublePressEvent:
    timestamp_ms: int


@dataclass(frozen=True)
class SensorKeySinglePressEvent:
    timestamp_ms: int


async def start_sensor_report(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> SensorStartInfo:
    """Start IMU reports. single-sample IMU firmware starts capture; gesture firmware requires
    gesture mode first. Both single-sample and batch reports are supported.
    """
    packet = await client.request(
        SensorCommand.START_REPORT,
        SensorCommand.START_REPORT_RESP,
        timeout_s=timeout_s,
    )
    return SensorStartInfo(**vars(call(native.parse_imu_config, bytes(packet.body))))


async def stop_sensor_report(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> SensorStopInfo:
    """Stop reports; single-sample IMU firmware also stops capture, gesture firmware may retain it."""
    packet = await client.request(
        SensorCommand.STOP_REPORT,
        SensorCommand.STOP_REPORT_RESP,
        timeout_s=timeout_s,
    )
    call(native.parse_success, bytes(packet.body))
    return SensorStopInfo()


async def wait_sensor_data(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> SensorDataBatch:
    """Wait for one 0x0605 batch after start_sensor_report() succeeds."""
    packet = await client.wait_for_command(SensorCommand.DATA_FRAME, timeout_s=timeout_s)
    return parse_sensor_data_batch(packet.body)


def parse_sensor_data_batch(body: bytes) -> SensorDataBatch:
    batch = call(native.parse_imu, bytes(body))
    return SensorDataBatch(
        sequence_start=batch.sequence_start, frame_count=batch.frame_count,
        sample_size=batch.sample_size,
        samples=tuple(SensorDataSample(**vars(sample)) for sample in batch.samples),
    )


def parse_sensor_double_tap_event(body: bytes) -> SensorDoubleTapEvent:
    return SensorDoubleTapEvent(timestamp_ms=call(native.parse_device_event, 0x0701, bytes(body)).timestamp)


def parse_sensor_gesture_event(body: bytes) -> SensorGestureEvent:
    event = call(native.parse_device_event, 0x0702, bytes(body))
    return SensorGestureEvent(timestamp_ms=event.timestamp, gesture_id=event.gesture_id)


def sensor_gesture_name(gesture_id: int | SensorGestureId) -> str:
    value = int(gesture_id)
    return native.sensor_gesture_name(value) if 0 <= value <= 255 else f"unknown({value})"


def parse_sensor_key_double_press_event(body: bytes) -> SensorKeyDoublePressEvent:
    return SensorKeyDoublePressEvent(timestamp_ms=call(native.parse_device_event, 0x0703, bytes(body)).timestamp)


def parse_sensor_key_single_press_event(body: bytes) -> SensorKeySinglePressEvent:
    return SensorKeySinglePressEvent(timestamp_ms=call(native.parse_device_event, 0x0704, bytes(body)).timestamp)


async def wait_sensor_double_tap_event(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> SensorDoubleTapEvent:
    packet = await client.wait_for_command(SensorCommand.DOUBLE_TAP, timeout_s=timeout_s)
    return parse_sensor_double_tap_event(packet.body)


async def wait_sensor_gesture_event(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> SensorGestureEvent:
    packet = await client.wait_for_command(SensorCommand.GESTURE, timeout_s=timeout_s)
    return parse_sensor_gesture_event(packet.body)


async def wait_sensor_key_double_press_event(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> SensorKeyDoublePressEvent:
    packet = await client.wait_for_command(
        SensorCommand.KEY_DOUBLE_PRESS,
        timeout_s=timeout_s,
    )
    return parse_sensor_key_double_press_event(packet.body)


async def wait_sensor_key_single_press_event(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> SensorKeySinglePressEvent:
    packet = await client.wait_for_command(
        SensorCommand.KEY_SINGLE_PRESS,
        timeout_s=timeout_s,
    )
    return parse_sensor_key_single_press_event(packet.body)

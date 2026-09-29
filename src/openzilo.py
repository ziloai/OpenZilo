# SPDX-License-Identifier: MPL-2.0
"""Single-file OpenZilo Python SDK and command-line tool.

The public helpers cover BLE discovery/connection, system information, ring
logs, time sync, six-axis sensor reporting, and audio file operations.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
from typing import Any, DefaultDict

__version__ = "0.5.0"

NUS_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
NUS_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
NUS_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

DEFAULT_SCAN_TIMEOUT_S = 25.0
DEFAULT_COMMAND_TIMEOUT_S = 10.0
_NUS_WRITE_CHUNK_SIZE = 20

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1
DEFAULT_BIT_DEPTH = 16
DEFAULT_SPEEX_FRAME_SIZE = 320
DEFAULT_SPEEX_MAX_PACKET_SIZE = 540
DEFAULT_SPEEX_QUALITY = 3
LEGACY_OUTER_FRAME_SIZE = 1026
SPEEX_BITS_SIZE_BY_QUALITY = {
    1: 10,
    2: 15,
    3: 20,
    4: 20,
    5: 28,
    6: 28,
    7: 38,
    8: 38,
    9: 46,
    10: 46,
}

HEADER_MAGIC = 0x3F
PROTOCOL_VERSION = 4
HEADER_SIZE = 11
MAX_BODY_LENGTH = 5120
_HEADER_STRUCT = struct.Struct(">BHHIH")


class OpenZiloError(Exception):
    """Base exception for OpenZilo errors."""


class TransportError(OpenZiloError):
    """BLE transport failed."""


class ProtocolError(OpenZiloError):
    """Packet framing, CRC, or body parsing failed."""


class TimeoutError(OpenZiloError):
    """A device response did not arrive in time."""


class DeviceError(OpenZiloError):
    """The device returned a non-zero protocol error code."""

    def __init__(self, error_code: int, message: str | None = None) -> None:
        self.error_code = error_code
        super().__init__(message or f"Device returned error code {error_code}")


class AudioDecodeError(OpenZiloError):
    """Audio data could not be decoded into a playable WAV file."""


class SpeexDecoderUnavailable(AudioDecodeError):
    """The configured Speex decoder is unavailable."""


class ErrorCode(IntEnum):
    SUCCESS = 0
    UNKNOWN = 1
    DEVICE_BUSY = 2
    FILE_NOT_EXIST = 3
    CMD_GROUP_NOT_EXIST = 4
    CMD_NOT_EXIST = 5
    TIMEOUT = 6
    PARAM_INVALID = 7
    COMMUNICATION = 8


ERROR_MESSAGES = {
    ErrorCode.SUCCESS: "success",
    ErrorCode.UNKNOWN: "unknown error",
    ErrorCode.DEVICE_BUSY: "device busy",
    ErrorCode.FILE_NOT_EXIST: "file not exist",
    ErrorCode.CMD_GROUP_NOT_EXIST: "command group not exist",
    ErrorCode.CMD_NOT_EXIST: "command not exist",
    ErrorCode.TIMEOUT: "operation timeout",
    ErrorCode.PARAM_INVALID: "invalid parameter",
    ErrorCode.COMMUNICATION: "communication error",
}


class SystemCommand(IntEnum):
    GET_INFO = 0x0101
    INFO_RESP = 0x0102


class LogCommand(IntEnum):
    GET_STORAGE = 0x0301
    STORAGE_RESP = 0x0302
    GET_LOG = 0x0303
    LOG_RESP = 0x0304


class TimeCommand(IntEnum):
    REQUEST = 0x0401
    RESPONSE = 0x0402


class AudioCommand(IntEnum):
    GET_LIST = 0x0501
    LIST_RESP = 0x0502
    START_EXTRACT = 0x0503
    FILE_INFO_RESP = 0x0504
    DATA_FRAME = 0x0505
    NEXT_FRAME = 0x0506
    END_EXTRACT = 0x0507
    EXTRACT_DONE = 0x0508
    START_EXTRACT_QUICK = 0x0509
    CLEAR_ALL = 0x050B
    CLEAR_ALL_RESP = 0x050C


class SensorCommand(IntEnum):
    START_REPORT = 0x0601
    START_REPORT_RESP = 0x0602
    STOP_REPORT = 0x0603
    STOP_REPORT_RESP = 0x0604
    DATA_FRAME = 0x0605
    DOUBLE_TAP = 0x0701
    GESTURE = 0x0702
    KEY_DOUBLE_PRESS = 0x0703
    KEY_SINGLE_PRESS = 0x0704


class SensorGestureId(IntEnum):
    IDLE = 0
    ROTATE_BACK = 1
    ROTATE_FRONT = 2
    WAVE = 3


_SENSOR_GESTURE_NAMES: dict[int, str] = {
    int(SensorGestureId.IDLE): "idle",
    int(SensorGestureId.ROTATE_BACK): "rotate_back",
    int(SensorGestureId.ROTATE_FRONT): "rotate_front",
    int(SensorGestureId.WAVE): "wave",
}


@dataclass(frozen=True)
class BleDeviceInfo:
    name: str | None
    address: str
    rssi: int | None = None


@dataclass(frozen=True)
class Packet:
    command: int
    body: bytes
    version: int = PROTOCOL_VERSION
    body_crc: int = 0


@dataclass(frozen=True)
class SystemInfo:
    firmware_version: str
    system_time: int
    audio_storage_total: int
    audio_storage_available: int
    battery_percent: int
    battery_charging: bool
    sn: str
    cpuid: str
    model: str


@dataclass(frozen=True)
class LogStorageInfo:
    page_size: int
    total_len: int


@dataclass(frozen=True)
class AudioFileInfo:
    file_index: int
    record_time: int
    data_size: int


@dataclass(frozen=True)
class AudioDataFrame:
    file_index: int
    frame_offset: int
    frame_size: int
    is_end: bool
    data: bytes


@dataclass(frozen=True)
class PcmConfig:
    sample_rate: int = DEFAULT_SAMPLE_RATE
    channels: int = DEFAULT_CHANNELS
    bit_depth: int = DEFAULT_BIT_DEPTH


@dataclass(frozen=True)
class SpeexDecodeResult:
    pcm_bytes: bytes
    pcm_config: PcmConfig
    source_type: str = "speex"
    source_extension: str = "spx"
    packet_count: int = 0


@dataclass(frozen=True)
class PlayableAudio:
    bytes: bytes
    extension: str
    mime: str
    play_mode: str
    label: str
    pcm_config: PcmConfig | None = None
    source_type: str = "raw"
    source_extension: str = "bin"
    source_mime: str = "application/octet-stream"
    description: str = ""


@dataclass(frozen=True)
class AudioBundle:
    raw_path: Path
    raw_file_name: str
    play_path: Path
    play_file_name: str
    play_mode: str
    format_label: str
    play_description: str
    pcm_summary: str
    raw_size: int
    play_size: int
    source_type: str
    source_extension: str


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


class BinaryReader:
    def __init__(self, data: bytes | bytearray | memoryview) -> None:
        self._data = memoryview(bytes(data))
        self.offset = 0

    @property
    def remaining(self) -> int:
        return len(self._data) - self.offset

    def require(self, size: int) -> None:
        if self.remaining < size:
            raise ProtocolError(f"Need {size} bytes, only {self.remaining} left")

    def u8(self) -> int:
        self.require(1)
        value = self._data[self.offset]
        self.offset += 1
        return int(value)

    def u16(self) -> int:
        self.require(2)
        value = struct.unpack_from(">H", self._data, self.offset)[0]
        self.offset += 2
        return int(value)

    def i16(self) -> int:
        self.require(2)
        value = struct.unpack_from(">h", self._data, self.offset)[0]
        self.offset += 2
        return int(value)

    def u32(self) -> int:
        self.require(4)
        value = struct.unpack_from(">I", self._data, self.offset)[0]
        self.offset += 4
        return int(value)

    def bytes(self, size: int) -> bytes:
        self.require(size)
        value = self._data[self.offset : self.offset + size].tobytes()
        self.offset += size
        return value

    def string_u16(self, encoding: str = "utf-8") -> str:
        size = self.u16()
        return self.bytes(size).decode(encoding, errors="replace")


class BinaryWriter:
    def __init__(self) -> None:
        self._data = bytearray()

    def u8(self, value: int) -> "BinaryWriter":
        self._data += struct.pack(">B", value & 0xFF)
        return self

    def u16(self, value: int) -> "BinaryWriter":
        self._data += struct.pack(">H", value & 0xFFFF)
        return self

    def i16(self, value: int) -> "BinaryWriter":
        self._data += struct.pack(">h", value)
        return self

    def u32(self, value: int) -> "BinaryWriter":
        self._data += struct.pack(">I", value & 0xFFFFFFFF)
        return self

    def bytes(self, value: bytes | bytearray | memoryview) -> "BinaryWriter":
        self._data += bytes(value)
        return self

    def string_u32(self, value: str, encoding: str = "utf-8") -> "BinaryWriter":
        raw = value.encode(encoding)
        self.u32(len(raw))
        self.bytes(raw)
        return self

    def build(self) -> bytes:
        return bytes(self._data)


def crc16_compute(data: bytes | bytearray | memoryview, initial: int = 0xFFFF) -> int:
    crc = initial & 0xFFFF
    for byte in bytes(data):
        crc = ((crc >> 8) | ((crc << 8) & 0xFFFF)) & 0xFFFF
        crc ^= byte
        crc &= 0xFFFF
        crc ^= (crc & 0xFF) >> 4
        crc &= 0xFFFF
        crc ^= (crc << 8) << 4
        crc &= 0xFFFF
        crc ^= ((crc & 0xFF) << 4) << 1
        crc &= 0xFFFF
    return crc


def encode_packet(command: int, body: bytes | bytearray | memoryview = b"") -> bytes:
    payload = bytes(body)
    body_crc = crc16_compute(payload) if payload else 0
    header = _HEADER_STRUCT.pack(
        HEADER_MAGIC,
        PROTOCOL_VERSION,
        int(command) & 0xFFFF,
        len(payload),
        body_crc,
    )
    return header + payload


def decode_packet(data: bytes | bytearray | memoryview) -> Packet:
    raw = bytes(data)
    if len(raw) < HEADER_SIZE:
        raise ProtocolError(f"Packet too short: {len(raw)} bytes")

    magic, version, command, body_length, body_crc = _HEADER_STRUCT.unpack(
        raw[:HEADER_SIZE]
    )
    if magic != HEADER_MAGIC:
        raise ProtocolError(f"Invalid packet magic: 0x{magic:02X}")
    if version > PROTOCOL_VERSION:
        raise ProtocolError(f"Unsupported protocol version: {version}")
    if body_length > MAX_BODY_LENGTH:
        raise ProtocolError(f"Body too large: {body_length} bytes")
    if len(raw) < HEADER_SIZE + body_length:
        raise ProtocolError(
            f"Incomplete packet: need {HEADER_SIZE + body_length}, got {len(raw)}"
        )

    body = raw[HEADER_SIZE : HEADER_SIZE + body_length]
    if body_length:
        actual_crc = crc16_compute(body)
        if actual_crc != body_crc:
            raise ProtocolError(
                f"Body CRC mismatch: expected 0x{body_crc:04X}, got 0x{actual_crc:04X}"
            )

    return Packet(command=command, body=body, version=version, body_crc=body_crc)


def peek_body_length(data: bytes | bytearray | memoryview) -> int:
    if len(data) < HEADER_SIZE:
        raise ProtocolError("Not enough bytes to read packet header")
    _, _, _, body_length, _ = _HEADER_STRUCT.unpack(bytes(data[:HEADER_SIZE]))
    return body_length


class PacketStream:
    """Accumulates BLE chunks and emits complete protocol packets."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def clear(self) -> None:
        self._buffer.clear()

    def feed(self, data: bytes | bytearray | memoryview) -> list[Packet]:
        self._buffer.extend(data)
        packets: list[Packet] = []

        while True:
            if not self._buffer:
                return packets

            magic_index = self._buffer.find(bytes([HEADER_MAGIC]))
            if magic_index < 0:
                self._buffer.clear()
                return packets
            if magic_index:
                del self._buffer[:magic_index]

            if len(self._buffer) < HEADER_SIZE:
                return packets

            body_length = peek_body_length(self._buffer)
            if body_length > MAX_BODY_LENGTH:
                self._buffer.clear()
                raise ProtocolError(f"Body too large: {body_length} bytes")

            packet_length = HEADER_SIZE + body_length
            if len(self._buffer) < packet_length:
                return packets

            packet_bytes = bytes(self._buffer[:packet_length])
            del self._buffer[:packet_length]
            packets.append(decode_packet(packet_bytes))

    def __len__(self) -> int:
        return len(self._buffer)


def read_error(reader: BinaryReader) -> int:
    return reader.u16()


def ensure_success(error_code: int) -> None:
    if error_code == int(ErrorCode.SUCCESS):
        return
    try:
        message = ERROR_MESSAGES[ErrorCode(error_code)]
    except ValueError:
        message = f"device error {error_code}"
    raise DeviceError(error_code, message)


RxCallback = Callable[[bytes], None | Awaitable[None]]
DisconnectCallback = Callable[[], None | Awaitable[None]]
PacketHandler = Callable[[Packet], None | Awaitable[None]]
AudioProgressCallback = Callable[[int, int], None]
SpeexDecoder = Callable[[bytes, Mapping[str, Any]], SpeexDecodeResult]


def _normalize_ble_address(address: str | None) -> str:
    return "".join(ch for ch in str(address or "") if ch.isalnum()).lower()


def _address_matches(candidate: object, expected: str | None) -> bool:
    expected_norm = _normalize_ble_address(expected)
    if not expected_norm:
        return True
    return _normalize_ble_address(str(candidate or "")) == expected_norm


class NusClient:
    """Cross-platform BLE/NUS client using bleak."""

    def __init__(
        self,
        *,
        address: str | None = None,
        service_uuid: str = NUS_SERVICE_UUID,
        tx_uuid: str = NUS_TX_UUID,
        rx_uuid: str = NUS_RX_UUID,
        scan_timeout_s: float = DEFAULT_SCAN_TIMEOUT_S,
        write_with_response: bool = False,
    ) -> None:
        self.address = address
        self.service_uuid = service_uuid
        self.tx_uuid = tx_uuid
        self.rx_uuid = rx_uuid
        self.scan_timeout_s = scan_timeout_s
        self.write_with_response = write_with_response
        self._client: Any | None = None
        self._rx_callback: RxCallback | None = None
        self._disconnect_callback: DisconnectCallback | None = None
        self._notify_started = False

    @staticmethod
    async def discover(
        *,
        address: str | None = None,
        timeout_s: float = DEFAULT_SCAN_TIMEOUT_S,
    ) -> list[BleDeviceInfo]:
        try:
            from bleak import BleakScanner
        except ImportError as exc:
            raise TransportError("Install bleak to use BLE transport") from exc

        devices = await BleakScanner.discover(
            timeout=timeout_s,
            return_adv=False,
        )

        results: list[BleDeviceInfo] = []
        for dev in devices:
            device_address = str(getattr(dev, "address", ""))
            if not _address_matches(device_address, address):
                continue
            results.append(
                BleDeviceInfo(
                    name=getattr(dev, "name", None),
                    address=device_address,
                    rssi=getattr(dev, "rssi", None),
                )
            )
        return results

    def set_rx_callback(self, callback: RxCallback | None) -> None:
        self._rx_callback = callback

    def _set_disconnect_callback(self, callback: DisconnectCallback | None) -> None:
        self._disconnect_callback = callback

    @property
    def is_connected(self) -> bool:
        return bool(self._client and self._client.is_connected)

    async def connect(self) -> None:
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError as exc:
            raise TransportError("Install bleak to use BLE transport") from exc

        if self.address is None:
            raise TransportError("BLE address is required; pass address='AA:BB:CC:DD:EE:FF'")

        target: Any = await BleakScanner.find_device_by_filter(
            lambda dev, _adv: _address_matches(getattr(dev, "address", ""), self.address),
            timeout=self.scan_timeout_s,
        )
        if target is None:
            target = self.address

        self._client = BleakClient(target, disconnected_callback=self._handle_disconnect)
        try:
            await self._client.connect()
            await self._client.start_notify(self.tx_uuid, self._handle_notify)
            self._notify_started = True
        except Exception as exc:
            self._client = None
            raise TransportError(
                f"BLE connect failed for address={self.address!r}. "
                "The device was not found during scanning, then direct address connect also failed."
            ) from exc

    async def disconnect(self) -> None:
        if self._client is None:
            return
        try:
            if self._notify_started:
                await self._client.stop_notify(self.tx_uuid)
        finally:
            self._notify_started = False
            if self._client.is_connected:
                await self._client.disconnect()
            self._client = None

    async def write(self, data: bytes | bytearray | memoryview) -> None:
        if self._client is None or not self._client.is_connected:
            raise TransportError("BLE client is not connected")

        payload = bytes(data)
        for offset in range(0, len(payload), _NUS_WRITE_CHUNK_SIZE):
            chunk = payload[offset : offset + _NUS_WRITE_CHUNK_SIZE]
            await self._client.write_gatt_char(
                self.rx_uuid,
                chunk,
                response=self.write_with_response,
            )
            await asyncio.sleep(0)

    async def __aenter__(self) -> "NusClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.disconnect()

    def _handle_notify(self, _sender: Any, data: bytearray) -> None:
        callback = self._rx_callback
        if callback is None:
            return

        result = callback(bytes(data))
        if asyncio.iscoroutine(result):
            asyncio.create_task(result)

    def _handle_disconnect(self, _client: Any) -> None:
        self._notify_started = False
        callback = self._disconnect_callback
        if callback is None:
            return

        result = callback()
        if asyncio.iscoroutine(result):
            asyncio.create_task(result)


class OpenZiloClient:
    """High-level BLE protocol client."""

    def __init__(
        self,
        *,
        address: str | None = None,
        command_timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S,
        transport: NusClient | None = None,
    ) -> None:
        self.command_timeout_s = command_timeout_s
        self.transport = transport or NusClient(address=address)
        self._stream = PacketStream()
        self._queues: DefaultDict[int, asyncio.Queue[Packet]] = defaultdict(
            asyncio.Queue
        )
        self._handlers: DefaultDict[int, list[PacketHandler]] = defaultdict(list)
        self._protocol_errors: asyncio.Queue[ProtocolError] = asyncio.Queue()
        self._disconnected = asyncio.Event()
        self._disconnected.set()

    @staticmethod
    async def discover(*args: Any, **kwargs: Any) -> list[BleDeviceInfo]:
        return await NusClient.discover(*args, **kwargs)

    @property
    def is_connected(self) -> bool:
        return self.transport.is_connected

    async def connect(self) -> None:
        self._clear_receive_state()
        self._disconnected.clear()
        self.transport.set_rx_callback(self._on_rx)
        set_disconnect_callback = getattr(
            self.transport,
            "_set_disconnect_callback",
            None,
        )
        if callable(set_disconnect_callback):
            set_disconnect_callback(self._on_disconnect)
        try:
            await self.transport.connect()
        except Exception:
            self._disconnected.set()
            raise

    async def disconnect(self) -> None:
        try:
            await self.transport.disconnect()
        finally:
            self._on_disconnect()

    async def send_command(self, command: int | IntEnum, body: bytes = b"") -> None:
        await self.transport.write(encode_packet(int(command), body))

    async def request(
        self,
        command: int | IntEnum,
        response_command: int | IntEnum,
        body: bytes = b"",
        *,
        timeout_s: float | None = None,
    ) -> Packet:
        response_id = int(response_command)
        self._drain_queue(response_id)
        self._drain_protocol_errors()
        await self.send_command(command, body)
        return await self.wait_for_command(response_id, timeout_s=timeout_s)

    async def wait_for_command(
        self,
        command: int | IntEnum,
        *,
        timeout_s: float | None = None,
    ) -> Packet:
        command_id = int(command)
        timeout = self.command_timeout_s if timeout_s is None else timeout_s
        if self._disconnected.is_set():
            raise TransportError(
                f"BLE disconnected while waiting for command 0x{command_id:04X}"
            )

        packet_task = asyncio.create_task(self._queues[command_id].get())
        error_task = asyncio.create_task(self._protocol_errors.get())
        disconnect_task = asyncio.create_task(self._disconnected.wait())
        tasks = {packet_task, error_task, disconnect_task}
        try:
            done, _pending = await asyncio.wait(
                tasks,
                timeout=max(0.0, timeout),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise TimeoutError(
                    f"Timed out waiting for command 0x{command_id:04X}"
                )
            if error_task in done:
                raise error_task.result()
            if disconnect_task in done:
                raise TransportError(
                    f"BLE disconnected while waiting for command 0x{command_id:04X}"
                )
            return packet_task.result()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def add_packet_handler(self, command: int | IntEnum, handler: PacketHandler) -> None:
        self._handlers[int(command)].append(handler)

    def remove_packet_handler(
        self,
        command: int | IntEnum,
        handler: PacketHandler,
    ) -> None:
        self._handlers[int(command)].remove(handler)

    async def __aenter__(self) -> "OpenZiloClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.disconnect()

    def _on_rx(self, data: bytes) -> None:
        try:
            packets = self._stream.feed(data)
        except ProtocolError as exc:
            self._stream.clear()
            self._protocol_errors.put_nowait(exc)
            return

        for packet in packets:
            self._queues[packet.command].put_nowait(packet)
            for handler in list(self._handlers.get(packet.command, [])):
                result = handler(packet)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)

    def _on_disconnect(self) -> None:
        self._disconnected.set()
        self._clear_receive_state()

    def _drain_queue(self, command: int) -> None:
        queue = self._queues[command]
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return

    def _drain_protocol_errors(self) -> None:
        while True:
            try:
                self._protocol_errors.get_nowait()
            except asyncio.QueueEmpty:
                return

    def _clear_receive_state(self) -> None:
        self._stream.clear()
        for command in list(self._queues):
            self._drain_queue(command)
        self._drain_protocol_errors()


class ProgressPrinter:
    def __init__(self, *, prefix: str = "progress") -> None:
        self.prefix = prefix
        self._last_percent = -1

    def __call__(self, current: int, total: int) -> None:
        percent = int(current * 100 / total) if total else 0
        if percent == self._last_percent:
            return
        self._last_percent = percent
        print(f"{self.prefix}: {current}/{total} bytes ({percent}%)")


def _ensure_bytes(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    return bytes(value)


def _pad2(value: int) -> str:
    return str(int(value)).zfill(2)


def normalize_pcm_config(config: PcmConfig | Mapping[str, Any] | None = None) -> PcmConfig:
    if isinstance(config, PcmConfig):
        return config
    source = dict(config or {})
    sample_rate = int(
        source.get("sampleRate", source.get("sample_rate", DEFAULT_SAMPLE_RATE))
        or DEFAULT_SAMPLE_RATE
    )
    channels = int(source.get("channels", DEFAULT_CHANNELS) or DEFAULT_CHANNELS)
    bit_depth = int(
        source.get("bitDepth", source.get("bit_depth", DEFAULT_BIT_DEPTH))
        or DEFAULT_BIT_DEPTH
    )
    return PcmConfig(
        sample_rate=max(1, sample_rate),
        channels=2 if channels > 1 else 1,
        bit_depth=8 if bit_depth == 8 else 16,
    )


def format_pcm_config(config: PcmConfig | Mapping[str, Any] | None = None) -> str:
    value = normalize_pcm_config(config)
    return f"{value.sample_rate}Hz / {value.channels}ch / {value.bit_depth}bit"


def build_base_name(
    file_index: int,
    metadata: Mapping[str, Any] | None = None,
    *,
    now_ms: int | None = None,
) -> str:
    source = metadata or {}
    record_time = int(source.get("recordTime", source.get("record_time", 0)) or 0)
    base_time_ms = (
        record_time * 1000
        if record_time
        else int(now_ms if now_ms is not None else time.time() * 1000)
    )
    date = datetime.fromtimestamp(base_time_ms / 1000.0)
    suffix_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    return (
        f"openzilo-{int(file_index):03d}-"
        f"{date.year}{_pad2(date.month)}{_pad2(date.day)}-"
        f"{_pad2(date.hour)}{_pad2(date.minute)}{_pad2(date.second)}-"
        f"{suffix_ms}"
    )


def build_audio_bundle_paths(
    file_index: int,
    metadata: Mapping[str, Any] | None = None,
    *,
    output_path: str | os.PathLike[str] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
    now_ms: int | None = None,
) -> tuple[Path, Path]:
    if output_path:
        path = Path(output_path)
        suffix = path.suffix.lower()
        if suffix == ".wav":
            return path.with_suffix(".bin"), path
        if suffix == ".bin":
            return path, path.with_suffix(".wav")
        return path.with_suffix(".bin"), path.with_suffix(".wav")

    base_dir = Path(output_dir or ".")
    base_name = build_base_name(file_index, metadata, now_ms=now_ms)
    return base_dir / f"{base_name}.bin", base_dir / f"{base_name}.wav"


def build_wav_from_pcm(
    input_bytes: Any,
    config: PcmConfig | Mapping[str, Any] | None = None,
) -> bytes:
    pcm_bytes = _ensure_bytes(input_bytes)
    pcm_config = normalize_pcm_config(config)
    block_align = (pcm_config.channels * pcm_config.bit_depth) // 8
    byte_rate = pcm_config.sample_rate * block_align
    header = bytearray(44)
    header[0:4] = b"RIFF"
    struct.pack_into("<I", header, 4, 36 + len(pcm_bytes))
    header[8:12] = b"WAVE"
    header[12:16] = b"fmt "
    struct.pack_into("<I", header, 16, 16)
    struct.pack_into("<H", header, 20, 1)
    struct.pack_into("<H", header, 22, pcm_config.channels)
    struct.pack_into("<I", header, 24, pcm_config.sample_rate)
    struct.pack_into("<I", header, 28, byte_rate)
    struct.pack_into("<H", header, 32, block_align)
    struct.pack_into("<H", header, 34, pcm_config.bit_depth)
    header[36:40] = b"data"
    struct.pack_into("<I", header, 40, len(pcm_bytes))
    return bytes(header) + pcm_bytes


def _read_ascii(data: bytes, start: int, length: int) -> str:
    return data[start : start + length].decode("ascii", errors="ignore")


def _find_ascii(data: bytes, target: str, max_scan_length: int | None = None) -> int:
    limit = min(len(data), max_scan_length or len(data))
    return data[:limit].find(target.encode("ascii"))


def is_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def is_ogg_speex(data: bytes) -> bool:
    return len(data) >= 36 and data[:4] == b"OggS" and (
        _read_ascii(data, 28, 8) == "Speex   "
        or _find_ascii(data, "Speex   ", 128) != -1
    )


def pick_speex_mode(sample_rate: int) -> int:
    if sample_rate <= 8000:
        return 0
    if sample_rate <= 16000:
        return 1
    return 2


def pick_frame_size(sample_rate: int) -> int:
    if sample_rate <= 8000:
        return 160
    if sample_rate <= 16000:
        return 320
    return 640


def pick_bits_size(
    quality: int = DEFAULT_SPEEX_QUALITY,
    bits_size: int | None = None,
) -> int:
    if bits_size and bits_size > 0:
        return int(bits_size)
    return SPEEX_BITS_SIZE_BY_QUALITY.get(int(quality or DEFAULT_SPEEX_QUALITY), 20)


def _is_padding_byte(value: int) -> bool:
    return value in (0x00, 0xFF)


def parse_packetized_speex_stream(
    data: Any,
    *,
    max_packet_size: int = DEFAULT_SPEEX_MAX_PACKET_SIZE,
    allow_framed_blocks: bool = True,
    framed_block_size: int = LEGACY_OUTER_FRAME_SIZE,
) -> list[bytes] | None:
    source = _ensure_bytes(data)
    max_size = max(1, int(max_packet_size or DEFAULT_SPEEX_MAX_PACKET_SIZE))

    def parse_block(start: int, end: int) -> list[bytes] | None:
        packets: list[bytes] = []
        offset = start
        while offset + 2 <= end:
            packet_length = struct.unpack_from("<H", source, offset)[0]
            if not packet_length:
                break
            if packet_length > max_size or offset + 2 + packet_length > end:
                return None
            packets.append(source[offset + 2 : offset + 2 + packet_length])
            offset += 2 + packet_length
        if not packets:
            return None
        if any(not _is_padding_byte(item) for item in source[offset:end]):
            return None
        return packets

    direct = parse_block(0, len(source))
    if direct:
        return direct
    if not allow_framed_blocks:
        return None

    block_size = max(1, int(framed_block_size or LEGACY_OUTER_FRAME_SIZE))
    if len(source) <= block_size:
        return None

    packets: list[bytes] = []
    for start in range(0, len(source), block_size):
        block = parse_block(start, min(len(source), start + block_size))
        if not block:
            return None
        packets.extend(block)
    return packets


def split_raw_speex_packets(
    data: Any,
    *,
    quality: int = DEFAULT_SPEEX_QUALITY,
    bits_size: int | None = None,
) -> list[bytes] | None:
    source = _ensure_bytes(data)
    size = pick_bits_size(quality=quality, bits_size=bits_size)
    if len(source) < size or len(source) % size != 0:
        return None
    return [source[offset : offset + size] for offset in range(0, len(source), size)]


def _ogg_crc(data: bytes) -> int:
    crc = 0
    for value in data:
        crc ^= value << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc & 0xFFFFFFFF


def _packet_lacing(packet: bytes) -> list[int]:
    length = len(packet)
    lacing: list[int] = []
    while length >= 255:
        lacing.append(255)
        length -= 255
    lacing.append(length)
    return lacing


def _build_ogg_page(
    packet: bytes,
    *,
    header_type: int,
    granule_position: int,
    serial: int,
    sequence: int,
) -> bytes:
    lacing = _packet_lacing(packet)
    if len(lacing) > 255:
        raise ValueError("single Ogg page cannot contain this packet")
    header = bytearray(
        struct.pack(
            "<4sBBQIIIB",
            b"OggS",
            0,
            header_type & 0xFF,
            max(0, int(granule_position)),
            serial & 0xFFFFFFFF,
            sequence & 0xFFFFFFFF,
            0,
            len(lacing),
        )
    )
    page = bytes(header) + bytes(lacing) + packet
    checksum = _ogg_crc(page)
    return page[:22] + struct.pack("<I", checksum) + page[26:]


def build_ogg_speex(
    packets: list[bytes],
    *,
    pcm_config: PcmConfig | Mapping[str, Any] | None = None,
    serial: int = 0x564F5247,
) -> bytes:
    config = normalize_pcm_config(pcm_config)
    frame_size = pick_frame_size(config.sample_rate)
    mode = pick_speex_mode(config.sample_rate)
    version = b"speex-1.2.1"
    version = version + b"\x00" * (20 - len(version))
    speex_header = struct.pack(
        "<8s20s13i",
        b"Speex   ",
        version,
        1,
        80,
        config.sample_rate,
        mode,
        4,
        1,
        -1,
        frame_size,
        0,
        1,
        0,
        0,
        0,
    )
    vendor = b"openzilo-python"
    comments = struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", 0)

    pages = [
        _build_ogg_page(
            speex_header,
            header_type=2,
            granule_position=0,
            serial=serial,
            sequence=0,
        ),
        _build_ogg_page(
            comments,
            header_type=0,
            granule_position=0,
            serial=serial,
            sequence=1,
        ),
    ]

    granule = 0
    for index, packet in enumerate(packets):
        granule += frame_size
        pages.append(
            _build_ogg_page(
                packet,
                header_type=4 if index == len(packets) - 1 else 0,
                granule_position=granule,
                serial=serial,
                sequence=index + 2,
            )
        )
    return b"".join(pages)


def normalize_decoded_speex_pcm(
    pcm_bytes: bytes,
    *,
    packet_count: int,
    pcm_config: PcmConfig | Mapping[str, Any] | None = None,
) -> bytes:
    config = normalize_pcm_config(pcm_config)
    count = max(0, int(packet_count or 0))
    if not pcm_bytes or count <= 0:
        return pcm_bytes

    bytes_per_sample = max(1, config.bit_depth // 8)
    frame_bytes = pick_frame_size(config.sample_rate) * config.channels * bytes_per_sample
    expected_bytes = frame_bytes * count
    if frame_bytes <= 0 or len(pcm_bytes) <= expected_bytes:
        return pcm_bytes

    decoded_bytes_per_packet = len(pcm_bytes) // count
    if len(pcm_bytes) % count != 0 or decoded_bytes_per_packet % frame_bytes != 0:
        return pcm_bytes

    return b"".join(
        pcm_bytes[offset : offset + frame_bytes]
        for offset in range(0, len(pcm_bytes), decoded_bytes_per_packet)
    )


def decode_ogg_speex_with_ffmpeg(
    ogg_bytes: bytes,
    *,
    pcm_config: PcmConfig | Mapping[str, Any] | None = None,
    ffmpeg_path: str = "ffmpeg",
) -> bytes:
    config = normalize_pcm_config(pcm_config)
    if not shutil.which(ffmpeg_path) and os.path.sep not in ffmpeg_path:
        raise SpeexDecoderUnavailable(
            "ffmpeg is required to decode Speex. Install ffmpeg or pass --ffmpeg."
        )
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "ogg",
        "-i",
        "pipe:0",
        "-f",
        "s16le" if config.bit_depth == 16 else "u8",
        "-ac",
        str(config.channels),
        "-ar",
        str(config.sample_rate),
        "pipe:1",
    ]
    try:
        completed = subprocess.run(
            command,
            input=ogg_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SpeexDecoderUnavailable(
            "ffmpeg is required to decode Speex. Install ffmpeg or pass --ffmpeg."
        ) from exc

    if completed.returncode != 0:
        error_text = completed.stderr.decode("utf-8", errors="replace").strip()
        raise AudioDecodeError(f"ffmpeg Speex decode failed: {error_text[:500]}")
    return completed.stdout


def decode_speex_to_pcm(
    data: Any,
    *,
    pcm_config: PcmConfig | Mapping[str, Any] | None = None,
    quality: int = DEFAULT_SPEEX_QUALITY,
    bits_size: int | None = None,
    allow_framed_blocks: bool = False,
    ffmpeg_path: str = "ffmpeg",
    speex_decoder: SpeexDecoder | None = None,
) -> SpeexDecodeResult:
    source = _ensure_bytes(data)
    if not source:
        raise AudioDecodeError("Speex data is empty")

    config = normalize_pcm_config(pcm_config)
    options = {
        "pcm_config": config,
        "quality": quality,
        "bits_size": bits_size,
        "allow_framed_blocks": allow_framed_blocks,
        "ffmpeg_path": ffmpeg_path,
    }
    if speex_decoder:
        return speex_decoder(source, options)

    if is_ogg_speex(source):
        pcm = decode_ogg_speex_with_ffmpeg(
            source,
            pcm_config=config,
            ffmpeg_path=ffmpeg_path,
        )
        return SpeexDecodeResult(
            pcm_bytes=pcm,
            pcm_config=config,
            source_type="ogg-speex",
            source_extension="spx",
        )

    packets = parse_packetized_speex_stream(
        source,
        allow_framed_blocks=allow_framed_blocks,
    )
    source_type = "packet-speex"
    if not packets:
        packets = split_raw_speex_packets(
            source,
            quality=quality,
            bits_size=bits_size,
        )
        source_type = "raw-speex"
    if not packets:
        raise AudioDecodeError("bin data does not look like packetized or raw Speex")

    ogg = build_ogg_speex(packets, pcm_config=config)
    pcm = decode_ogg_speex_with_ffmpeg(ogg, pcm_config=config, ffmpeg_path=ffmpeg_path)
    pcm = normalize_decoded_speex_pcm(pcm, packet_count=len(packets), pcm_config=config)
    return SpeexDecodeResult(
        pcm_bytes=pcm,
        pcm_config=config,
        source_type=source_type,
        source_extension="spx",
        packet_count=len(packets),
    )


def build_playable_audio(
    data: Any,
    *,
    pcm_config: PcmConfig | Mapping[str, Any] | None = None,
    quality: int = DEFAULT_SPEEX_QUALITY,
    bits_size: int | None = None,
    allow_framed_blocks: bool = False,
    ffmpeg_path: str = "ffmpeg",
    speex_decoder: SpeexDecoder | None = None,
) -> PlayableAudio:
    source = _ensure_bytes(data)
    if is_wav(source):
        return PlayableAudio(
            bytes=source,
            extension="wav",
            mime="audio/wav",
            play_mode="direct",
            label="WAV",
            source_type="wav",
            source_extension="wav",
            source_mime="audio/wav",
            description="Detected WAV audio; saved directly.",
        )

    decoded = decode_speex_to_pcm(
        source,
        pcm_config=pcm_config,
        quality=quality,
        bits_size=bits_size,
        allow_framed_blocks=allow_framed_blocks,
        ffmpeg_path=ffmpeg_path,
        speex_decoder=speex_decoder,
    )
    wav_bytes = build_wav_from_pcm(decoded.pcm_bytes, decoded.pcm_config)
    return PlayableAudio(
        bytes=wav_bytes,
        extension="wav",
        mime="audio/wav",
        play_mode="speex-decode",
        label="WAV",
        pcm_config=decoded.pcm_config,
        source_type=decoded.source_type,
        source_extension=decoded.source_extension,
        source_mime="audio/x-speex",
        description=f"Decoded Speex and wrapped as WAV. {format_pcm_config(decoded.pcm_config)}",
    )


def decode_audio_to_wav(
    data: Any,
    *,
    pcm_config: PcmConfig | Mapping[str, Any] | None = None,
    quality: int = DEFAULT_SPEEX_QUALITY,
    bits_size: int | None = None,
    allow_framed_blocks: bool = False,
    ffmpeg_path: str = "ffmpeg",
    speex_decoder: SpeexDecoder | None = None,
) -> bytes:
    """Decode ring recording bytes into WAV bytes."""
    return build_playable_audio(
        data,
        pcm_config=pcm_config,
        quality=quality,
        bits_size=bits_size,
        allow_framed_blocks=allow_framed_blocks,
        ffmpeg_path=ffmpeg_path,
        speex_decoder=speex_decoder,
    ).bytes


def save_audio_bundle(
    *,
    file_index: int,
    data: Any,
    metadata: Mapping[str, Any] | None = None,
    output_path: str | os.PathLike[str] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
    pcm_config: PcmConfig | Mapping[str, Any] | None = None,
    quality: int = DEFAULT_SPEEX_QUALITY,
    bits_size: int | None = None,
    allow_framed_blocks: bool = False,
    ffmpeg_path: str = "ffmpeg",
    speex_decoder: SpeexDecoder | None = None,
) -> AudioBundle:
    raw_bytes = _ensure_bytes(data)
    raw_path, play_path = build_audio_bundle_paths(
        file_index,
        metadata,
        output_path=output_path,
        output_dir=output_dir,
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    play_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw_bytes)

    playable = build_playable_audio(
        raw_bytes,
        pcm_config=pcm_config,
        quality=quality,
        bits_size=bits_size,
        allow_framed_blocks=allow_framed_blocks,
        ffmpeg_path=ffmpeg_path,
        speex_decoder=speex_decoder,
    )
    play_path.write_bytes(playable.bytes)

    return AudioBundle(
        raw_path=raw_path,
        raw_file_name=raw_path.name,
        play_path=play_path,
        play_file_name=play_path.name,
        play_mode=playable.play_mode,
        format_label=playable.label,
        play_description=playable.description,
        pcm_summary=format_pcm_config(playable.pcm_config or pcm_config),
        raw_size=len(raw_bytes),
        play_size=len(playable.bytes),
        source_type=playable.source_type,
        source_extension=playable.source_extension,
    )


async def scan_rings(
    *,
    address: str | None = None,
    timeout_s: float = DEFAULT_SCAN_TIMEOUT_S,
) -> list[BleDeviceInfo]:
    """Scan nearby BLE devices and optionally filter by MAC address."""
    return await OpenZiloClient.discover(
        address=address,
        timeout_s=timeout_s,
    )


async def connect_ring(
    *,
    address: str | None = None,
    command_timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S,
    auto_time_sync: bool = False,
) -> OpenZiloClient:
    """Create and connect a OpenZiloClient."""
    client = OpenZiloClient(
        address=address,
        command_timeout_s=command_timeout_s,
    )
    await client.connect()
    if auto_time_sync:
        enable_time_sync(client)
    return client


async def get_system_info(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> SystemInfo:
    packet = await client.request(
        SystemCommand.GET_INFO,
        SystemCommand.INFO_RESP,
        timeout_s=timeout_s,
    )
    return parse_system_info(packet.body)


def parse_system_info(body: bytes) -> SystemInfo:
    reader = BinaryReader(body)
    ensure_success(read_error(reader))
    firmware_version = reader.string_u16()
    system_time = reader.u32()
    audio_storage_total = reader.u32()
    audio_storage_available = reader.u32()
    battery_percent = reader.u16()
    battery_charging = bool(reader.u8())
    sn = reader.string_u16()
    cpuid = reader.string_u16()
    model = reader.string_u16()
    return SystemInfo(
        firmware_version=firmware_version,
        system_time=system_time,
        audio_storage_total=audio_storage_total,
        audio_storage_available=audio_storage_available,
        battery_percent=battery_percent,
        battery_charging=battery_charging,
        sn=sn,
        cpuid=cpuid,
        model=model,
    )


async def send_time_response(
    client: OpenZiloClient,
    request_time: int,
    *,
    response_time: int | None = None,
    send_time: int | None = None,
) -> None:
    """Reply to a device time-sync request."""
    now = int(time.time())
    body = (
        BinaryWriter()
        .u32(request_time)
        .u32(now if response_time is None else response_time)
        .u32(now if send_time is None else send_time)
        .build()
    )
    await client.send_command(TimeCommand.RESPONSE, body)


def enable_time_sync(client: OpenZiloClient) -> None:
    """Automatically respond to device time-sync requests."""

    async def handle_time_request(packet: Packet) -> None:
        reader = BinaryReader(packet.body)
        await send_time_response(client, reader.u32())

    client.add_packet_handler(TimeCommand.REQUEST, handle_time_request)


async def get_log_storage(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> LogStorageInfo:
    packet = await client.request(
        LogCommand.GET_STORAGE,
        LogCommand.STORAGE_RESP,
        timeout_s=timeout_s,
    )
    reader = BinaryReader(packet.body)
    ensure_success(read_error(reader))
    return LogStorageInfo(page_size=reader.u32(), total_len=reader.u32())


async def read_log_chunk(
    client: OpenZiloClient,
    index: int,
    offset: int,
    size: int,
    *,
    timeout_s: float | None = None,
) -> bytes:
    body = BinaryWriter().u32(index).u32(offset).u32(size).build()
    packet = await client.request(
        LogCommand.GET_LOG,
        LogCommand.LOG_RESP,
        body,
        timeout_s=timeout_s,
    )
    reader = BinaryReader(packet.body)
    ensure_success(read_error(reader))
    data_len = reader.u32()
    return reader.bytes(min(data_len, reader.remaining))


async def get_audio_file_count(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> int:
    packet = await client.request(
        AudioCommand.GET_LIST,
        AudioCommand.LIST_RESP,
        timeout_s=timeout_s,
    )
    reader = BinaryReader(packet.body)
    ensure_success(read_error(reader))
    return reader.u32()


async def get_audio_file_info(
    client: OpenZiloClient,
    file_index: int,
    *,
    timeout_s: float | None = None,
) -> AudioFileInfo:
    """Start the normal 0x0503 extraction flow and return recording metadata."""
    body = BinaryWriter().u16(0).u32(file_index).build()
    packet = await client.request(
        AudioCommand.START_EXTRACT,
        AudioCommand.FILE_INFO_RESP,
        body,
        timeout_s=timeout_s,
    )
    return parse_audio_file_info(packet.body)


async def read_audio_frame(
    client: OpenZiloClient,
    file_index: int,
    frame_offset: int,
    *,
    timeout_s: float | None = None,
) -> AudioDataFrame:
    body = _audio_frame_request_body(file_index, frame_offset)
    packet = await client.request(
        AudioCommand.NEXT_FRAME,
        AudioCommand.DATA_FRAME,
        body,
        timeout_s=timeout_s,
    )
    return parse_audio_data_frame(packet.body)


async def end_audio_extract(
    client: OpenZiloClient,
    file_index: int,
    *,
    timeout_s: float | None = None,
    ignore_timeout: bool = True,
) -> None:
    body = BinaryWriter().u16(0).u32(file_index).build()
    try:
        packet = await client.request(
            AudioCommand.END_EXTRACT,
            AudioCommand.EXTRACT_DONE,
            body,
            timeout_s=timeout_s,
        )
    except TimeoutError:
        if ignore_timeout:
            return
        raise
    reader = BinaryReader(packet.body)
    ensure_success(read_error(reader))


def _audio_frame_request_body(file_index: int, frame_offset: int) -> bytes:
    # Keep the reserved bytes required by the 12-byte 0x0506 request body.
    return BinaryWriter().u16(0).u32(file_index).u32(frame_offset).u16(0).build()


async def _wait_audio_data_frame(
    client: OpenZiloClient,
    file_index: int,
    *,
    timeout_s: float | None = None,
) -> AudioDataFrame:
    timeout = client.command_timeout_s if timeout_s is None else timeout_s
    deadline = asyncio.get_running_loop().time() + max(0.001, timeout)
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError(
                f"Timed out waiting for audio frame for file_index={file_index}"
            )
        packet = await client.wait_for_command(
            AudioCommand.DATA_FRAME,
            timeout_s=remaining,
        )
        frame = parse_audio_data_frame(packet.body)
        if frame.file_index == file_index:
            return frame


async def _request_audio_retry(
    client: OpenZiloClient,
    file_index: int,
    frame_offset: int,
) -> None:
    await client.send_command(
        AudioCommand.NEXT_FRAME,
        _audio_frame_request_body(file_index, frame_offset),
    )


async def receive_auto_audio_file(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> tuple[int, bytes]:
    """Receive one recording that the ring pushes as consecutive 0x0505 frames.

    The current firmware starts this stream after a recording is saved. It does
    not send 0x0504 metadata first, so this function returns only the file index
    and assembled recording bytes. A continuous stream sends no request command.
    Recovery obtains the exact file size before requesting a missing offset.

    Do not run this function concurrently with ``download_audio_file()`` or
    ``read_audio_frame()`` because all of them consume the same 0x0505 queue.
    """
    if not client.is_connected:
        raise TransportError("BLE client is not connected")

    packet = await client.wait_for_command(
        AudioCommand.DATA_FRAME,
        timeout_s=timeout_s,
    )
    frame = parse_audio_data_frame(packet.body)
    file_index = frame.file_index
    received = bytearray()
    pending: dict[int, AudioDataFrame] = {}
    end_offset: int | None = None
    expected_size: int | None = None
    recovery_attempts = 0

    def add_frame(current: AudioDataFrame) -> bool:
        nonlocal end_offset

        if current.file_index != file_index:
            raise ProtocolError(
                f"Audio file index mismatch: expected {file_index}, "
                f"got {current.file_index}"
            )

        if expected_size is not None and current.frame_offset > expected_size:
            raise ProtocolError(
                f"Audio frame offset {current.frame_offset} exceeds "
                f"file size {expected_size}"
            )

        frame_data = current.data
        if expected_size is not None:
            remaining = max(0, expected_size - current.frame_offset)
            frame_data = frame_data[:remaining]

        frame_end = current.frame_offset + len(frame_data)
        if current.is_end and expected_size is None:
            if end_offset is not None and end_offset != frame_end:
                raise ProtocolError(
                    "Conflicting audio end offsets: "
                    f"{end_offset} and {frame_end}"
                )
            end_offset = frame_end

        previous_size = len(received)
        if frame_end <= previous_size:
            overlap_size = len(frame_data)
            if received[current.frame_offset:frame_end] != frame_data[:overlap_size]:
                raise ProtocolError(
                    f"Conflicting audio data at offset {current.frame_offset}"
                )
            return False
        if current.frame_offset <= previous_size:
            overlap = previous_size - current.frame_offset
            if received[current.frame_offset:previous_size] != frame_data[:overlap]:
                raise ProtocolError(
                    f"Conflicting audio overlap at offset {current.frame_offset}"
                )
            received.extend(frame_data[overlap:])
            return len(received) > previous_size

        existing = pending.get(current.frame_offset)
        if existing is None or len(existing.data) < len(current.data):
            pending[current.frame_offset] = current
        return False

    async def ensure_recovery_metadata() -> None:
        nonlocal end_offset, expected_size

        if expected_size is not None:
            return
        info = await get_audio_file_info(
            client,
            file_index,
            timeout_s=timeout_s,
        )
        if info.file_index != file_index:
            raise ProtocolError(
                f"Audio metadata index mismatch: expected {file_index}, "
                f"got {info.file_index}"
            )
        if info.data_size <= 0:
            raise ProtocolError(
                f"Audio metadata has invalid data_size={info.data_size}"
            )
        expected_size = info.data_size
        end_offset = expected_size
        if len(received) > expected_size:
            del received[expected_size:]
        for offset in list(pending):
            if offset >= expected_size:
                pending.pop(offset)

    def append_pending() -> bool:
        grew = False
        while pending:
            offset = min(pending)
            if offset > len(received):
                break
            current = pending.pop(offset)
            if add_frame(current):
                grew = True
        return grew

    while True:
        grew = add_frame(frame)
        if append_pending():
            grew = True
        if grew:
            recovery_attempts = 0

        if end_offset is not None and len(received) >= end_offset:
            return file_index, bytes(received[:end_offset])

        has_gap = bool(pending) and min(pending) > len(received)
        if has_gap:
            recovery_attempts += 1
            if recovery_attempts > 3:
                raise ProtocolError(
                    "Audio frame gap: "
                    f"unable to recover offset {len(received)}"
                )
            await ensure_recovery_metadata()
            if expected_size is not None and len(received) >= expected_size:
                return file_index, bytes(received[:expected_size])
            await _request_audio_retry(client, file_index, len(received))

        while True:
            try:
                frame = await _wait_audio_data_frame(
                    client,
                    file_index,
                    timeout_s=timeout_s,
                )
                break
            except (TimeoutError, ProtocolError) as exc:
                recovery_attempts += 1
                if recovery_attempts > 3:
                    raise ProtocolError(
                        "Audio stream stalled: "
                        f"unable to recover offset {len(received)}"
                    ) from exc
                await ensure_recovery_metadata()
                if expected_size is not None and len(received) >= expected_size:
                    return file_index, bytes(received[:expected_size])
                await _request_audio_retry(client, file_index, len(received))


async def _download_audio_file_quick(
    client: OpenZiloClient,
    file_index: int,
    *,
    progress: AudioProgressCallback | None = None,
    timeout_s: float | None = None,
) -> tuple[AudioFileInfo, bytes]:
    client._drain_queue(int(AudioCommand.FILE_INFO_RESP))
    client._drain_queue(int(AudioCommand.DATA_FRAME))
    await client.send_command(
        AudioCommand.START_EXTRACT_QUICK,
        BinaryWriter().u16(0).u32(file_index).build(),
    )

    info_packet = await client.wait_for_command(
        AudioCommand.FILE_INFO_RESP,
        timeout_s=timeout_s,
    )
    info = parse_audio_file_info(info_packet.body)
    if info.file_index != file_index:
        raise ProtocolError(
            f"Audio metadata index mismatch: expected {file_index}, got {info.file_index}"
        )
    received = bytearray()
    gap_retries = 0

    while True:
        try:
            frame = await _wait_audio_data_frame(
                client,
                file_index,
                timeout_s=timeout_s,
            )
        except TimeoutError as exc:
            gap_retries += 1
            if gap_retries > 3:
                raise ProtocolError(
                    f"Audio stream stalled at offset {len(received)}"
                ) from exc
            await _request_audio_retry(client, file_index, len(received))
            frame = await _wait_audio_data_frame(
                client,
                file_index,
                timeout_s=timeout_s,
            )

        if frame.frame_offset > len(received):
            gap_retries += 1
            if gap_retries > 3:
                raise ProtocolError(
                    "Audio frame gap: "
                    f"expected offset {len(received)}, got {frame.frame_offset}"
                )
            await _request_audio_retry(client, file_index, len(received))
            continue

        overlap = len(received) - frame.frame_offset
        overlap_size = min(overlap, len(frame.data))
        if overlap_size > 0:
            existing = received[
                frame.frame_offset : frame.frame_offset + overlap_size
            ]
            if existing != frame.data[:overlap_size]:
                raise ProtocolError(
                    f"Conflicting audio overlap at offset {frame.frame_offset}"
                )
        if overlap < len(frame.data):
            new_data = frame.data[overlap:]
            if info.data_size > 0:
                new_data = new_data[: max(0, info.data_size - len(received))]
            received.extend(new_data)

        if overlap < len(frame.data):
            gap_retries = 0

        if progress:
            progress(len(received), info.data_size)
        if info.data_size > 0 and len(received) >= info.data_size:
            break
        if frame.is_end:
            gap_retries += 1
            if gap_retries > 3:
                raise ProtocolError(
                    f"Audio stream ended at {len(received)} of {info.data_size} bytes"
                )
            await _request_audio_retry(client, file_index, len(received))
        elif not frame.data:
            raise ProtocolError(
                f"Empty audio frame at offset {frame.frame_offset} before end"
            )

    data = bytes(received[: info.data_size] if info.data_size > 0 else received)
    return info, data


async def clear_audio_files(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> None:
    packet = await client.request(
        AudioCommand.CLEAR_ALL,
        AudioCommand.CLEAR_ALL_RESP,
        timeout_s=timeout_s,
    )
    reader = BinaryReader(packet.body)
    ensure_success(read_error(reader))


async def download_audio_file(
    client: OpenZiloClient,
    file_index: int,
    *,
    progress: AudioProgressCallback | None = None,
    timeout_s: float | None = None,
    quick: bool = True,
) -> tuple[AudioFileInfo, bytes]:
    if quick:
        return await _download_audio_file_quick(
            client,
            file_index,
            progress=progress,
            timeout_s=timeout_s,
        )

    info = await get_audio_file_info(
        client,
        file_index,
        timeout_s=timeout_s,
    )
    if info.file_index != file_index:
        raise ProtocolError(
            f"Audio metadata index mismatch: expected {file_index}, got {info.file_index}"
        )
    received = bytearray()

    while True:
        frame = await read_audio_frame(
            client,
            file_index,
            len(received),
            timeout_s=timeout_s,
        )
        if frame.frame_offset > len(received):
            raise ProtocolError(
                f"Audio frame gap: expected offset {len(received)}, "
                f"got {frame.frame_offset}"
            )
        overlap = len(received) - frame.frame_offset
        overlap_size = min(overlap, len(frame.data))
        if overlap_size > 0:
            existing = received[
                frame.frame_offset : frame.frame_offset + overlap_size
            ]
            if existing != frame.data[:overlap_size]:
                raise ProtocolError(
                    f"Conflicting audio overlap at offset {frame.frame_offset}"
                )
        new_data = frame.data[overlap:]
        if info.data_size > 0:
            new_data = new_data[: max(0, info.data_size - len(received))]
        received.extend(new_data)
        if progress:
            progress(len(received), info.data_size)
        if info.data_size > 0 and len(received) >= info.data_size:
            break
        if frame.is_end:
            raise ProtocolError(
                f"Audio stream ended at {len(received)} of {info.data_size} bytes"
            )
        if not new_data:
            raise ProtocolError(
                f"Audio transfer made no progress at offset {len(received)}"
            )

    await end_audio_extract(client, file_index, timeout_s=timeout_s, ignore_timeout=False)
    data = bytes(received[: info.data_size] if info.data_size > 0 else received)
    return info, data


def parse_audio_file_info(body: bytes) -> AudioFileInfo:
    reader = BinaryReader(body)
    ensure_success(read_error(reader))
    info = AudioFileInfo(
        file_index=reader.u32(),
        record_time=reader.u32(),
        data_size=reader.u32(),
    )
    if reader.remaining:
        raise ProtocolError(
            f"Unexpected trailing audio file info bytes: {reader.remaining}"
        )
    return info


def parse_audio_data_frame(body: bytes) -> AudioDataFrame:
    reader = BinaryReader(body)
    ensure_success(read_error(reader))
    file_index = reader.u32()
    frame_offset = reader.u32()
    frame_size = reader.u32()
    is_end = bool(reader.u8())
    if reader.remaining != frame_size:
        raise ProtocolError(
            f"Audio frame size mismatch: declared {frame_size}, "
            f"got {reader.remaining}"
        )
    data = reader.bytes(frame_size)
    return AudioDataFrame(
        file_index=file_index,
        frame_offset=frame_offset,
        frame_size=frame_size,
        is_end=is_end,
        data=data,
    )


async def start_sensor_report(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> SensorStartInfo:
    """Enable 0x0605 BLE reports after the ring has entered gesture mode.

    This sends 0x0601 but does not start the IMU. The current firmware starts
    local IMU capture when the user switches the ring into gesture mode. In
    recording mode the device responds with DEVICE_BUSY.
    """
    packet = await client.request(
        SensorCommand.START_REPORT,
        SensorCommand.START_REPORT_RESP,
        timeout_s=timeout_s,
    )
    reader = BinaryReader(packet.body)
    ensure_success(read_error(reader))
    return SensorStartInfo(
        sample_rate_hz=reader.u16(),
        accel_range_g=reader.u16(),
        gyro_range_dps=reader.u16(),
    )


async def stop_sensor_report(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> SensorStopInfo:
    """Disable 0x0605 BLE reports without stopping gesture-mode IMU capture."""
    packet = await client.request(
        SensorCommand.STOP_REPORT,
        SensorCommand.STOP_REPORT_RESP,
        timeout_s=timeout_s,
    )
    reader = BinaryReader(packet.body)
    ensure_success(read_error(reader))
    return SensorStopInfo()


async def wait_sensor_data(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> SensorDataBatch:
    """Wait for one 0x0605 batch after start_sensor_report() succeeds."""
    packet = await client.wait_for_command(SensorCommand.DATA_FRAME, timeout_s=timeout_s)
    return parse_sensor_data_batch(packet.body)


def _read_sensor_sample(reader: BinaryReader) -> SensorDataSample:
    return SensorDataSample(
        timestamp_ms=reader.u32(),
        accel_x=reader.i16(),
        accel_y=reader.i16(),
        accel_z=reader.i16(),
        gyro_x=reader.i16(),
        gyro_y=reader.i16(),
        gyro_z=reader.i16(),
    )


def parse_sensor_data_batch(body: bytes) -> SensorDataBatch:
    reader = BinaryReader(body)
    ensure_success(read_error(reader))
    sequence_start = reader.u32()
    frame_count = reader.u16()
    sample_size = reader.u16()
    if sample_size != 16:
        raise ProtocolError(f"Unsupported sensor sample size: {sample_size}")
    expected_remaining = frame_count * sample_size
    if reader.remaining != expected_remaining:
        raise ProtocolError(
            f"Sensor batch length mismatch: expected {expected_remaining} sample bytes, "
            f"got {reader.remaining}"
        )
    samples = tuple(_read_sensor_sample(reader) for _ in range(frame_count))
    return SensorDataBatch(
        sequence_start=sequence_start,
        frame_count=frame_count,
        sample_size=sample_size,
        samples=samples,
    )


def parse_sensor_double_tap_event(body: bytes) -> SensorDoubleTapEvent:
    reader = BinaryReader(body)
    event = SensorDoubleTapEvent(timestamp_ms=reader.u32())
    if reader.remaining:
        raise ProtocolError(f"Unexpected trailing double-tap event bytes: {reader.remaining}")
    return event


def parse_sensor_gesture_event(body: bytes) -> SensorGestureEvent:
    reader = BinaryReader(body)
    event = SensorGestureEvent(timestamp_ms=reader.u32(), gesture_id=reader.u8())
    if reader.remaining:
        raise ProtocolError(f"Unexpected trailing gesture event bytes: {reader.remaining}")
    return event


def sensor_gesture_name(gesture_id: int | SensorGestureId) -> str:
    value = int(gesture_id)
    return _SENSOR_GESTURE_NAMES.get(value, f"unknown({value})")


def parse_sensor_key_double_press_event(body: bytes) -> SensorKeyDoublePressEvent:
    reader = BinaryReader(body)
    event = SensorKeyDoublePressEvent(timestamp_ms=reader.u32())
    if reader.remaining:
        raise ProtocolError(
            f"Unexpected trailing key double-press event bytes: {reader.remaining}"
        )
    return event


def parse_sensor_key_single_press_event(body: bytes) -> SensorKeySinglePressEvent:
    reader = BinaryReader(body)
    event = SensorKeySinglePressEvent(timestamp_ms=reader.u32())
    if reader.remaining:
        raise ProtocolError(
            f"Unexpected trailing key single-press event bytes: {reader.remaining}"
        )
    return event


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


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--address", required=True, help="BLE MAC address of the ring.")


def add_audio_decode_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg executable path.")
    parser.add_argument("--pcm-sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument("--pcm-channels", type=int, default=DEFAULT_CHANNELS, choices=(1, 2))
    parser.add_argument("--pcm-bit-depth", type=int, default=DEFAULT_BIT_DEPTH, choices=(8, 16))
    parser.add_argument("--speex-quality", type=int, default=DEFAULT_SPEEX_QUALITY)
    parser.add_argument("--speex-bits-size", type=int, default=None)
    parser.add_argument(
        "--allow-framed-blocks",
        action="store_true",
        help="Allow legacy 1026-byte outer blocks when parsing Speex packets.",
    )


def pcm_config_from_args(args: argparse.Namespace) -> PcmConfig:
    return PcmConfig(
        sample_rate=args.pcm_sample_rate,
        channels=args.pcm_channels,
        bit_depth=args.pcm_bit_depth,
    )


async def cmd_scan(args: argparse.Namespace) -> None:
    devices = await scan_rings(address=args.address, timeout_s=args.timeout)
    if not devices:
        print("No matching devices found.")
        return
    for device in devices:
        print(f"name={device.name!r} address={device.address} rssi={device.rssi}")


async def cmd_connect(args: argparse.Namespace) -> None:
    client = await connect_ring(address=args.address)
    try:
        print(f"connected: {client.is_connected}")
    finally:
        await client.disconnect()


async def cmd_info(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address) as client:
        enable_time_sync(client)
        info = await get_system_info(client)

    print(f"firmware_version: {info.firmware_version}")
    print(f"system_time: {info.system_time}")
    print(f"audio_storage_total: {info.audio_storage_total}")
    print(f"audio_storage_available: {info.audio_storage_available}")
    print(f"battery_percent: {info.battery_percent}")
    print(f"battery_charging: {info.battery_charging}")
    print(f"sn: {info.sn}")
    print(f"cpuid: {info.cpuid}")
    print(f"model: {info.model}")


async def cmd_time_sync(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address) as client:
        enable_time_sync(client)
        print(f"time sync auto-response enabled for {args.seconds:g}s")
        await asyncio.sleep(args.seconds)
    print("time sync session ended")


async def cmd_audio_count(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address) as client:
        count = await get_audio_file_count(client)
    print(f"audio file count: {count}")


async def cmd_audio_download(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address) as client:
        count = await get_audio_file_count(client)
        print(f"audio file count: {count}")
        info, data = await download_audio_file(
            client,
            args.file_index,
            progress=ProgressPrinter(prefix="audio"),
            timeout_s=args.timeout,
        )

    bundle = save_audio_bundle(
        file_index=args.file_index,
        data=data,
        metadata={"record_time": info.record_time},
        output_path=args.output,
        pcm_config=pcm_config_from_args(args),
        quality=args.speex_quality,
        bits_size=args.speex_bits_size,
        allow_framed_blocks=args.allow_framed_blocks,
        ffmpeg_path=args.ffmpeg,
    )
    print(f"raw recording saved: {bundle.raw_path} ({bundle.raw_size} bytes)")
    print(f"decoded recording saved: {bundle.play_path} ({bundle.play_size} bytes)")
    print(f"audio format: {bundle.play_description or bundle.format_label}")
    print(f"file info: {info}")


async def cmd_audio_decode(args: argparse.Namespace) -> None:
    data = args.input.read_bytes()
    playable = build_playable_audio(
        data,
        pcm_config=pcm_config_from_args(args),
        quality=args.speex_quality,
        bits_size=args.speex_bits_size,
        allow_framed_blocks=args.allow_framed_blocks,
        ffmpeg_path=args.ffmpeg,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(playable.bytes)
    print(f"decoded recording saved: {args.output} ({len(playable.bytes)} bytes)")
    print(f"audio format: {playable.description or playable.label}")


async def cmd_audio_clear(args: argparse.Namespace) -> None:
    if not args.yes:
        raise SystemExit("Refusing to clear audio files without --yes.")

    async with OpenZiloClient(address=args.address) as client:
        await clear_audio_files(client)
    print("audio files cleared")


async def cmd_log_storage(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address) as client:
        storage = await get_log_storage(client)
    print(f"page_size: {storage.page_size}")
    print(f"total_len: {storage.total_len}")


async def cmd_log_read(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address) as client:
        data = await read_log_chunk(client, args.index, args.offset, args.size)

    if args.output:
        args.output.write_bytes(data)
        print(f"wrote {len(data)} bytes to {args.output}")
        return

    if args.text:
        print(data.decode(args.encoding, errors="replace"))
    else:
        print(data.hex(" "))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenZilo SDK tool.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Scan nearby devices.")
    scan.add_argument("--address", default=None, help="BLE MAC address to filter.")
    scan.add_argument("--timeout", type=float, default=DEFAULT_SCAN_TIMEOUT_S)
    scan.set_defaults(func=cmd_scan)

    connect = subparsers.add_parser("connect", help="Connect and disconnect once.")
    add_connection_args(connect)
    connect.set_defaults(func=cmd_connect)

    info = subparsers.add_parser("info", help="Print system information.")
    add_connection_args(info)
    info.set_defaults(func=cmd_info)

    time_sync = subparsers.add_parser(
        "time-sync",
        help="Auto-respond to device time-sync requests.",
    )
    add_connection_args(time_sync)
    time_sync.add_argument("--seconds", type=float, default=30.0)
    time_sync.set_defaults(func=cmd_time_sync)

    audio_count = subparsers.add_parser(
        "audio-count",
        help="Print stored audio file count.",
    )
    add_connection_args(audio_count)
    audio_count.set_defaults(func=cmd_audio_count)

    audio_download = subparsers.add_parser(
        "audio-download",
        help="Download one audio file.",
    )
    add_connection_args(audio_download)
    audio_download.add_argument("file_index", type=int)
    audio_download.add_argument("output", type=Path)
    audio_download.add_argument("--timeout", type=float, default=30.0)
    add_audio_decode_args(audio_download)
    audio_download.set_defaults(func=cmd_audio_download)

    audio_decode = subparsers.add_parser(
        "audio-decode",
        help="Decode a downloaded recording bin into WAV.",
    )
    audio_decode.add_argument("input", type=Path)
    audio_decode.add_argument("output", type=Path)
    add_audio_decode_args(audio_decode)
    audio_decode.set_defaults(func=cmd_audio_decode)

    audio_clear = subparsers.add_parser(
        "audio-clear",
        help="Clear all stored audio files.",
    )
    add_connection_args(audio_clear)
    audio_clear.add_argument("--yes", action="store_true", help="Confirm clearing.")
    audio_clear.set_defaults(func=cmd_audio_clear)

    log_storage = subparsers.add_parser("log-storage", help="Print log storage info.")
    add_connection_args(log_storage)
    log_storage.set_defaults(func=cmd_log_storage)

    log_read = subparsers.add_parser("log-read", help="Read one log chunk.")
    add_connection_args(log_read)
    log_read.add_argument("index", type=int)
    log_read.add_argument("offset", type=int)
    log_read.add_argument("size", type=int)
    log_read.add_argument("--output", type=Path, default=None)
    log_read.add_argument("--text", action="store_true", help="Decode as text.")
    log_read.add_argument("--encoding", default="utf-8")
    log_read.set_defaults(func=cmd_log_read)

    return parser


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    await args.func(args)


if __name__ == "__main__":
    asyncio.run(main())


__all__ = [
    "AudioDataFrame",
    "AudioBundle",
    "AudioDecodeError",
    "AudioFileInfo",
    "BinaryReader",
    "BinaryWriter",
    "BleDeviceInfo",
    "DeviceError",
    "LogStorageInfo",
    "NusClient",
    "Packet",
    "PacketStream",
    "PcmConfig",
    "PlayableAudio",
    "ProgressPrinter",
    "ProtocolError",
    "OpenZiloClient",
    "OpenZiloError",
    "SensorDataBatch",
    "SensorDataSample",
    "SensorDoubleTapEvent",
    "SensorGestureEvent",
    "SensorGestureId",
    "SensorKeyDoublePressEvent",
    "SensorKeySinglePressEvent",
    "SensorStartInfo",
    "SensorStopInfo",
    "SpeexDecodeResult",
    "SpeexDecoderUnavailable",
    "SystemInfo",
    "TimeoutError",
    "TransportError",
    "build_audio_bundle_paths",
    "build_base_name",
    "build_ogg_speex",
    "build_playable_audio",
    "build_wav_from_pcm",
    "clear_audio_files",
    "connect_ring",
    "crc16_compute",
    "decode_audio_to_wav",
    "decode_ogg_speex_with_ffmpeg",
    "decode_packet",
    "decode_speex_to_pcm",
    "download_audio_file",
    "enable_time_sync",
    "encode_packet",
    "end_audio_extract",
    "format_pcm_config",
    "get_audio_file_count",
    "get_audio_file_info",
    "get_log_storage",
    "get_system_info",
    "is_ogg_speex",
    "is_wav",
    "normalize_decoded_speex_pcm",
    "normalize_pcm_config",
    "parse_audio_data_frame",
    "parse_audio_file_info",
    "parse_packetized_speex_stream",
    "parse_sensor_data_batch",
    "parse_sensor_double_tap_event",
    "parse_sensor_gesture_event",
    "parse_sensor_key_double_press_event",
    "parse_sensor_key_single_press_event",
    "parse_system_info",
    "pick_bits_size",
    "pick_frame_size",
    "pick_speex_mode",
    "read_audio_frame",
    "read_log_chunk",
    "receive_auto_audio_file",
    "scan_rings",
    "save_audio_bundle",
    "send_time_response",
    "sensor_gesture_name",
    "split_raw_speex_packets",
    "start_sensor_report",
    "stop_sensor_report",
    "wait_sensor_data",
    "wait_sensor_double_tap_event",
    "wait_sensor_gesture_event",
    "wait_sensor_key_double_press_event",
    "wait_sensor_key_single_press_event",
]

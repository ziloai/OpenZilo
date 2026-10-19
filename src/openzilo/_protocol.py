# SPDX-License-Identifier: MPL-2.0
"""Protocol v4 framing, command numbers and binary field helpers."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

from ._errors import DeviceError, ERROR_MESSAGES, ErrorCode, ProtocolError


HEADER_MAGIC = 0x3F
PROTOCOL_VERSION = 4
SUPPORTED_PROTOCOL_VERSIONS = frozenset({4})
HEADER_SIZE = 11
MAX_BODY_LENGTH = 5120
_HEADER_STRUCT = struct.Struct(">BHHIH")


class SystemCommand(IntEnum):
    GET_INFO = 0x0101
    INFO_RESP = 0x0102
    GET_CAPABILITIES = 0x0105
    CAPABILITIES_RESP = 0x0106
    ERROR_RESP = 0x01FF


class _OtaCommand(IntEnum):
    NOTIFY = 1005
    NOTIFY_RESP = 1105
    GET_PACKET = 2001
    PACKET_RESP = 2101
    UPDATE_RESULT = 2201


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
    RECORD_RESULT = 0x050A
    LIVE_SUBSCRIBE = 0x050D
    LIVE_SUBSCRIBE_RESP = 0x050E
    LIVE_START = 0x050F
    LIVE_DATA = 0x0510
    LIVE_END = 0x0511
    CLEAR_ALL = 0x050B
    CLEAR_ALL_RESP = 0x050C
    GET_RECORDING_CONFIG = 0x0512
    RECORDING_CONFIG = 0x0513
    SET_RECORDING_CONFIG = 0x0514
    RECORDING_CONFIG_SET = 0x0515
    START_RECORDING = 0x0516
    RECORDING_STARTED = 0x0517
    STOP_RECORDING = 0x0518
    RECORDING_STOPPED = 0x0519
    GET_RECORDING_STATUS = 0x051A
    RECORDING_STATUS = 0x051B


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


@dataclass(frozen=True)
class Packet:
    command: int
    body: bytes
    version: int = PROTOCOL_VERSION
    body_crc: int = 0


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
    if version not in SUPPORTED_PROTOCOL_VERSIONS:
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

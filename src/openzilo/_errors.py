# SPDX-License-Identifier: MPL-2.0
"""Exception types and device error codes."""

from __future__ import annotations

from enum import IntEnum


class OpenZiloError(Exception):
    """Base exception for OpenZilo errors."""


class TransportError(OpenZiloError):
    """BLE transport failed."""


class ProtocolError(OpenZiloError):
    """Packet framing, CRC, or body parsing failed."""


class CompatibilityError(OpenZiloError):
    """Required device contract is unsupported or has not been verified."""


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


class OpusDecoderUnavailable(AudioDecodeError):
    """No Opus decoder is available."""


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
    UNSUPPORTED_SCHEMA = 9


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
    ErrorCode.UNSUPPORTED_SCHEMA: "unsupported schema",
}

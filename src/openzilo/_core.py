# SPDX-License-Identifier: MPL-2.0
"""Private bridge to the shared native core, preserving Python's exception types."""
from __future__ import annotations

import libopenzilo as native

from ._errors import (
    AudioDecodeError, CompatibilityError, DeviceError, ProtocolError, TimeoutError, TransportError,
)

CoreError = native.CoreError


def _detail(exc: BaseException) -> str:
    return getattr(exc, "detail", None) or str(exc)


def call(function, *args, **kwargs):
    """Run a core call; core failures become the SDK's protocol-level exceptions."""
    try:
        return function(*args, **kwargs)
    except CoreError.Device as exc:
        raise DeviceError(exc.code, native.device_error_message(exc.code)) from exc
    except CoreError.Incompatible as exc:
        raise CompatibilityError(_detail(exc)) from exc
    except CoreError.Timeout as exc:
        raise TimeoutError("Request timed out") from exc
    except CoreError.Disconnected as exc:
        raise TransportError("Transport disconnected") from exc
    except CoreError as exc:
        raise ProtocolError(_detail(exc)) from exc


def call_value(function, *args, **kwargs):
    """Run a core call for offline data validation, which raises ValueError."""
    try:
        return function(*args, **kwargs)
    except CoreError.Incompatible as exc:
        raise CompatibilityError(_detail(exc)) from exc
    except CoreError.Device as exc:
        raise DeviceError(exc.code, native.device_error_message(exc.code)) from exc
    except CoreError as exc:
        raise ValueError(_detail(exc)) from exc


def call_audio(function, *args, **kwargs):
    """Run a core call for audio containers, which raises AudioDecodeError."""
    try:
        return function(*args, **kwargs)
    except CoreError as exc:
        raise AudioDecodeError(_detail(exc)) from exc


def native_packet(packet):
    return native.Packet(command=packet.command, body=bytes(packet.body), version=packet.version,
                         body_crc=packet.body_crc)

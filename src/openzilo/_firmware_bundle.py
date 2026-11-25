# SPDX-License-Identifier: MPL-2.0
"""Strict, bounded verification of ring_sound distribution bundles."""
from __future__ import annotations

from dataclasses import dataclass
import json

from ._core import native, call_value

DOMAIN = b"OpenZilo firmware bundle v1\x00"


@dataclass(frozen=True)
class FirmwareBundle:
    """Verified metadata and immutable encrypted OTA bytes; no device checks yet."""
    version: str
    model: str
    board: str
    profile: str
    security_version: int
    source_versions: tuple[str, ...]
    payload: bytes
    signing_key_id: str

    @property
    def manifest(self) -> dict:
        """A fresh JSON-compatible copy of all verified manifest fields."""
        return json.loads(call_value(native.firmware_bundle_manifest_json, native.FirmwareBundle(
            version=self.version, model=self.model, board=self.board, profile=self.profile,
            security_version=self.security_version, source_versions=list(self.source_versions),
            payload=self.payload, signing_key_id=self.signing_key_id)))


def _pem(trusted_public_key: bytes | bytearray | memoryview | str) -> str:
    if isinstance(trusted_public_key, str):
        return trusted_public_key
    try:
        return bytes(trusted_public_key).decode("utf-8")
    except (TypeError, UnicodeDecodeError) as exc:
        raise ValueError("Expected a trusted P-256 public key") from exc


def inspect_firmware_bundle(bundle: bytes, *, trusted_public_key: bytes) -> FirmwareBundle:
    """Verify a ZIP using an independently trusted PEM P-256 public key.

    The archive cannot supply its own trust anchor. Only the returned payload
    goes over BLE. Device compatibility remains an update-time check.
    """
    if not isinstance(bundle, (bytes, bytearray, memoryview)):
        raise TypeError("bundle must contain ZIP bytes")
    result = call_value(native.inspect_firmware_bundle, bytes(bundle), _pem(trusted_public_key))
    return FirmwareBundle(result.version, result.model, result.board, result.profile,
                          result.security_version, tuple(result.source_versions),
                          bytes(result.payload), result.signing_key_id)

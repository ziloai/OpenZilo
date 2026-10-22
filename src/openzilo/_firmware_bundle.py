# SPDX-License-Identifier: MPL-2.0
"""Strict, bounded verification of ring_sound distribution bundles."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import re
import struct
import zipfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

DOMAIN = b"OpenZilo firmware bundle v1\x00"
MAX_PAYLOAD = 0x7A000 + 32
VERSION = r"V[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(?:-(?:debug|prod)-[0-9a-fA-F]{8})?"


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
        return {
            "schema": 1, "algorithm": "ECDSA-P256-SHA256", "image": "app",
            "version": self.version, "model": self.model, "board": self.board,
            "profile": self.profile, "security_version": self.security_version,
            "source_versions": list(self.source_versions), "key_id": self.signing_key_id,
            "payload": {"file": "app.ota.bin", "format": "RINGENC1", "size": len(self.payload),
                        "sha256": hashlib.sha256(self.payload).hexdigest()},
        }


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate manifest field")
        result[key] = value
    return result


def inspect_firmware_bundle(bundle: bytes, *, trusted_public_key: bytes) -> FirmwareBundle:
    """Verify a ZIP using an independently trusted PEM P-256 public key.

    The archive cannot supply its own trust anchor. Only the returned payload
    goes over BLE. Device compatibility remains an update-time check.
    """
    if not isinstance(bundle, (bytes, bytearray, memoryview)):
        raise TypeError("bundle must contain ZIP bytes")
    if not 0 < len(bundle) <= MAX_PAYLOAD + 32768:
        raise ValueError("Firmware bundle size exceeds limit")
    try:
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            entries = archive.infolist()
            limits = {"manifest.json": 16384, "manifest.sig": 80, "app.ota.bin": MAX_PAYLOAD}
            if len(entries) != 3 or {e.filename for e in entries} != set(limits):
                raise ValueError("Bundle must contain exactly manifest.json, manifest.sig, app.ota.bin")
            for entry in entries:
                if (entry.flag_bits & 1 or entry.compress_type != zipfile.ZIP_STORED
                        or not 0 < entry.file_size <= limits[entry.filename]
                        or entry.compress_size != entry.file_size):
                    raise ValueError("Invalid bundle member size or compression")
            raw, signature, payload = (archive.read(name) for name in limits)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as exc:
        raise ValueError("Invalid firmware ZIP") from exc
    key = serialization.load_pem_public_key(trusted_public_key)
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("Expected a trusted P-256 public key")
    try:
        key.verify(signature, DOMAIN + raw, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise ValueError("Firmware bundle signature verification failed") from exc
    try:
        meta = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid firmware manifest JSON") from exc
    fields = {"schema", "algorithm", "key_id", "image", "version", "model", "board",
              "profile", "security_version", "source_versions", "payload"}
    if not isinstance(meta, dict) or set(meta) != fields:
        raise ValueError("Invalid firmware manifest fields")
    key_id = hashlib.sha256(key.public_bytes(serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
    if (type(meta["schema"]) is not int or meta["schema"] != 1
            or meta["algorithm"] != "ECDSA-P256-SHA256" or meta["image"] != "app"
            or meta["key_id"] != key_id):
        raise ValueError("Unsupported firmware manifest or signing key ID")
    for name in ("version", "model", "board", "profile"):
        if not isinstance(meta[name], str) or not meta[name] or len(meta[name]) > 128:
            raise ValueError(f"Invalid manifest {name}")
    if not re.fullmatch(VERSION, meta["version"]) or len(meta["version"]) > 63:
        raise ValueError("Invalid manifest version")
    if meta["profile"] not in ("test", "production"):
        raise ValueError("Invalid manifest profile")
    if type(meta["security_version"]) is not int or not 1 <= meta["security_version"] <= 0x7FFFFFFF:
        raise ValueError("Invalid manifest security version")
    sources = meta["source_versions"]
    if not isinstance(sources, list) or len(sources) > 64 or any(
            not isinstance(v, str) or len(v) > 63 or not re.fullmatch(VERSION, v) for v in sources):
        raise ValueError("Invalid manifest source versions")
    info = meta["payload"]
    if (not isinstance(info, dict) or set(info) != {"file", "size", "sha256", "format"}
            or info["file"] != "app.ota.bin" or info["format"] != "RINGENC1"
            or type(info["size"]) is not int or info["size"] != len(payload)
            or info["sha256"] != hashlib.sha256(payload).hexdigest()):
        raise ValueError("Firmware payload size or SHA-256 mismatch")
    if (len(payload) <= 32 or payload[:8] != b"RINGENC1"
            or struct.unpack_from("<II", payload, 8) != (1, len(payload) - 32)):
        raise ValueError("Invalid encrypted APP header")
    return FirmwareBundle(meta["version"], meta["model"], meta["board"], meta["profile"],
                          meta["security_version"], tuple(sources), payload, key_id)

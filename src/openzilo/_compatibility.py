# SPDX-License-Identifier: MPL-2.0
"""Capability discovery v1. Product release strings are opaque identifiers."""
from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import TYPE_CHECKING

from ._errors import CompatibilityError, DeviceError, ProtocolError, TimeoutError, TransportError
from ._protocol import BinaryReader, SystemCommand, ensure_success

if TYPE_CHECKING:
    from ._client import OpenZiloClient
    from ._recording import AudioRecordingConfig

# These are contract versions, not firmware versions. IMU v2 starts capture on
# subscription; v1 required a separate gesture mode and is not interchangeable.
FEATURE_MAJORS = {"system": 1, "time_sync": 1, "audio_files": 1,
                  "recording_control": 1, "live_audio": 1, "imu": 2,
                  "key_events": 1, "double_tap": 1, "ota": 1, "gesture": 1}
FEATURE_NAMES = {1: "system", 2: "time_sync", 3: "audio_files", 4: "recording_control",
                 5: "live_audio", 6: "imu", 7: "key_events", 8: "double_tap",
                 9: "ota", 10: "gesture"}
_LIMITS = struct.Struct(">HHBBBBIIHHHHH")


@dataclass(frozen=True)
class FeatureVersion:
    name: str
    major: int
    minor: int


@dataclass(frozen=True)
class RecordingLimits:
    sample_rate_hz: int
    frame_duration_ms: int
    channels_mask: int
    outputs_mask: int
    continue_outputs_mask: int
    bitrate_min: int
    bitrate_max: int
    gain_min_q8: int
    gain_max_q8: int
    duration_min_ms: int
    duration_max_ms: int
    duration_step_ms: int

    def validate(self, config: AudioRecordingConfig) -> None:
        c = config
        if not (c.sample_rate == self.sample_rate_hz and c.frame_duration_ms == self.frame_duration_ms
                and 0 <= c.channels < 8 and self.channels_mask & (1 << c.channels)
                and 0 <= int(c.output) < 8 and self.outputs_mask & (1 << int(c.output))
                and self.bitrate_min <= c.bitrate <= self.bitrate_max
                and self.gain_min_q8 <= c.gain_left_q8 <= self.gain_max_q8
                and self.gain_min_q8 <= c.gain_right_q8 <= self.gain_max_q8
                and self.duration_min_ms <= c.max_duration_ms <= self.duration_max_ms
                and c.max_duration_ms % self.duration_step_ms == 0
                and (int(c.disconnect_policy) == 0 or
                     self.continue_outputs_mask & (1 << int(c.output)))):
            raise CompatibilityError("Recording configuration exceeds device capabilities")


@dataclass(frozen=True)
class DeviceCapabilities:
    source: str  # device, legacy_profile, unknown
    firmware_version: str
    model: str
    board_target: str | None = None
    build_id: str | None = None
    boot_id: str | None = None
    protocol_versions: tuple[int, ...] = ()
    features: tuple[FeatureVersion, ...] = ()
    recording_limits: RecordingLimits | None = None
    reason: str | None = None

    def supports(self, name: str, *, major: int | None = None, min_minor: int = 0) -> bool:
        expected = FEATURE_MAJORS.get(name) if major is None else major
        return any(f.name == name and f.major == expected and f.minor >= min_minor
                   for f in self.features)

    def require(self, name: str) -> None:
        if not self.supports(name):
            raise CompatibilityError(
                f"{name} contract is unavailable or unknown on {self.firmware_version} "
                f"(source={self.source}); inspect device capabilities or upgrade firmware"
            )


def parse_device_capabilities(body: bytes) -> DeviceCapabilities:
    reader = BinaryReader(body)
    ensure_success(reader.u16())
    if reader.u8() != 1:
        raise CompatibilityError("Unsupported capability schema; SDK upgrade required")
    fields: dict[int, bytes] = {}
    while reader.remaining:
        tag, size = reader.u16(), reader.u16()
        value = reader.bytes(size)
        if tag & 0x8000:
            raise CompatibilityError(f"Unknown required capability tag 0x{tag:04X}")
        if tag in fields:
            raise ProtocolError(f"Duplicate capability tag 0x{tag:04X}")
        fields[tag] = value
    for tag in (1, 2, 3, 4, 5, 6):
        if not fields.get(tag):
            raise ProtocolError(f"Missing capability tag {tag}")
    try:
        firmware, model, board, build = (fields[t].decode("utf-8", errors="strict")
                                         for t in (1, 2, 3, 5))
    except UnicodeDecodeError as exc:
        raise ProtocolError("Invalid UTF-8 capability identity") from exc
    if len(fields[4]) != 8 or len(fields[6]) % 2:
        raise ProtocolError("Invalid boot identity or protocol list")
    protocols = tuple(v[0] for v in struct.iter_unpack(">H", fields[6]))
    if 4 not in protocols:
        raise CompatibilityError("Device does not advertise protocol v4")
    features = []
    for tag, value in fields.items():
        if 0x100 < tag <= 0x1FF:
            if len(value) != 2 or value[0] == 0:
                raise ProtocolError("Invalid feature contract")
            name = FEATURE_NAMES.get(tag - 0x100, f"unknown_{tag - 0x100}")
            features.append(FeatureVersion(name, *value))
    limits = None
    if 0x204 in fields:
        if len(fields[0x204]) != _LIMITS.size:
            raise ProtocolError("Invalid recording limits length")
        rate, frame, channels, outputs, continuing, reserved, *ranges = _LIMITS.unpack(fields[0x204])
        limits = RecordingLimits(rate, frame, channels, outputs, continuing, *ranges)
        if (reserved or not rate or not frame or not channels or not outputs
                or continuing & ~outputs or not limits.duration_step_ms
                or limits.bitrate_min > limits.bitrate_max
                or limits.gain_min_q8 > limits.gain_max_q8
                or limits.duration_min_ms > limits.duration_max_ms):
            raise ProtocolError("Invalid recording limits")
    if any(f.name == "recording_control" and f.major == 1 for f in features):
        if limits is None:
            raise ProtocolError("Recording control v1 requires limits")
        if limits.sample_rate_hz != 16000 or limits.frame_duration_ms != 20:
            raise CompatibilityError("Recording contract v1 requires 16 kHz / 20 ms")
    return DeviceCapabilities("device", firmware, model, board, build, fields[4].hex(),
                              protocols, tuple(features), limits)


def _legacy_capabilities(firmware: str, model: str, reason: str) -> DeviceCapabilities:
    # Exact released product build, validated in the 0001 hardware test report.
    # No prefix/range matching: customer IDs are not semantic patch versions.
    if firmware == "V2.001.0002.0001-prod-7fd1dfc9" and model == "Open Zilo":
        return DeviceCapabilities(
            "legacy_profile", firmware, model, build_id="7fd1dfc9e9c698c47b91e100580deddde66f210e",
            protocol_versions=(4,),
            features=tuple(FeatureVersion(n, m, 0) for n, m in (
                ("system", 1), ("time_sync", 1), ("audio_files", 1), ("recording_control", 1),
                ("live_audio", 1), ("imu", 2), ("key_events", 1), ("double_tap", 1), ("ota", 1))),
            recording_limits=RecordingLimits(16000, 20, 6, 15, 10, 8000, 32000, 0, 1024, 20, 60000, 20),
            reason=reason,
        )
    return DeviceCapabilities("unknown", firmware, model, reason=reason)


async def get_device_capabilities(
    client: OpenZiloClient, *, timeout_s: float | None = None, refresh: bool = False,
) -> DeviceCapabilities:
    """Discover once per connection. Timeout is unknown, never unsupported.

    Legacy requests lack transaction IDs. Discovery is serialized and timeout
    fallback is cached until reconnect to avoid same-connection retry ambiguity.
    """
    from ._device import get_system_info
    async with client._capability_lock:
        if client.capabilities is not None and not refresh:
            return client.capabilities
        if client.capabilities is not None and client.capabilities.source != "device":
            raise CompatibilityError("Reconnect before retrying legacy/unknown discovery")
        client._capability_check_required = True
        client.capabilities = None
        connection = client._connection_token
        info = await get_system_info(client, timeout_s=timeout_s)
        try:
            packet = await client.request(SystemCommand.GET_CAPABILITIES,
                                          SystemCommand.CAPABILITIES_RESP, timeout_s=timeout_s)
        except TimeoutError:
            result = _legacy_capabilities(info.firmware_version, info.model,
                                          "Capability discovery timed out; support is unknown")
        except DeviceError as exc:
            if exc.error_code != 5:  # existing CMD_NOT_EXIST
                raise
            result = _legacy_capabilities(info.firmware_version, info.model,
                                          "Device explicitly rejected capability discovery")
        else:
            result = parse_device_capabilities(packet.body)
            if result.firmware_version != info.firmware_version or result.model != info.model:
                raise ProtocolError("Capability identity differs from system information")
        if connection is None or connection is not client._connection_token:
            raise TransportError("Connection changed during capability discovery")
        client.capabilities = result
        return result


# Only enhanced commands are guarded. Basic info, logs, file retrieval and time
# replies retain their existing baseline behaviour on unrecognized old devices.
COMMAND_FEATURES = {**{c: "recording_control" for c in (0x0512, 0x0514, 0x0516, 0x0518, 0x051A)},
                    0x050D: "live_audio", 0x0601: "imu", 0x0603: "imu", 0x0605: "imu",
                    0x0701: "double_tap", 0x0702: "gesture",
                    0x0703: "key_events", 0x0704: "key_events", 1005: "ota"}

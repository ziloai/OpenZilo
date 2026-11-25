# SPDX-License-Identifier: MPL-2.0
"""Capability discovery v1. Product release strings are opaque identifiers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._core import native, call
from ._errors import CompatibilityError, DeviceError, ProtocolError, TimeoutError, TransportError
from ._protocol import SystemCommand

if TYPE_CHECKING:
    from ._client import OpenZiloClient
    from ._recording import AudioRecordingConfig

# These are contract versions, not firmware versions. IMU v2 starts capture on
# subscription; v1 required a separate gesture mode and is not interchangeable.
FEATURE_MAJORS = {f.name: f.major for f in native.feature_contracts()}


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
        if (config.sample_rate, config.frame_duration_ms) != (self.sample_rate_hz, self.frame_duration_ms):
            raise CompatibilityError("Recording configuration exceeds device capabilities")
        call(native.validate_recording_config,
             native.RecordingConfig(**{name: int(getattr(config, name)) for name in (
                 "output", "disconnect_policy", "channels", "bitrate", "gain_left_q8",
                 "gain_right_q8", "max_duration_ms")}),
             native.RecordingLimits(**vars(self)))


def _native_features(features) -> list:
    return [native.FeatureVersion(name=f.name, major=f.major, minor=f.minor) for f in features]


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
        if expected is None:
            return False
        return native.supports_feature(_native_features(self.features), name, expected, min_minor)

    def require(self, name: str) -> None:
        if not self.supports(name):
            raise CompatibilityError(
                f"{name} contract is unavailable or unknown on {self.firmware_version} "
                f"(source={self.source}); inspect device capabilities or upgrade firmware"
            )


def _from_native(caps, source: str, reason: str | None = None) -> DeviceCapabilities:
    limits = caps.recording_limits
    return DeviceCapabilities(
        source, caps.firmware_version, caps.model, caps.board_target or None, caps.build_id or None,
        caps.boot_id or None, tuple(caps.protocol_versions),
        tuple(FeatureVersion(f.name, f.major, f.minor) for f in caps.features),
        None if limits is None else RecordingLimits(**vars(limits)), reason,
    )


def parse_device_capabilities(body: bytes) -> DeviceCapabilities:
    return _from_native(call(native.parse_capabilities, bytes(body)), "device")


def _legacy_capabilities(firmware: str, model: str, reason: str) -> DeviceCapabilities:
    # Exact verified released builds only; customer IDs are not semantic patch versions.
    profile = native.legacy_capability_profile(native.DeviceInfo(
        firmware_version=firmware, system_time=0, audio_storage_total=0, audio_storage_available=0,
        battery_percent=0, battery_charging=False, sn="", cpuid="", model=model), reason)
    if profile.source == native.CapabilitySource.VERIFIED_LEGACY_PROFILE and profile.capabilities:
        return _from_native(profile.capabilities, "legacy_profile", reason)
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
            if (result.firmware_version != info.firmware_version or result.model != info.model
                    or 4 not in result.protocol_versions):
                raise ProtocolError("Capability identity differs from system information")
        if connection is None or connection is not client._connection_token:
            raise TransportError("Connection changed during capability discovery")
        client.capabilities = result
        return result


# Only enhanced commands are guarded. Basic info, logs, file retrieval and time
# replies retain their existing baseline behaviour on unrecognized old devices.
COMMAND_FEATURES = {
    command: contract.feature
    for command in (0x0107, 0x0512, 0x0514, 0x0516, 0x0518, 0x051A, 0x050D, 0x0601, 0x0603, 0x0605,
                    0x0701, 0x0702, 0x0703, 0x0704, 1005)
    if (contract := native.command_contract(command)) is not None and contract.enhanced
}

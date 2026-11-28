# SPDX-License-Identifier: MPL-2.0
"""Recording control extension; requires firmware implementing 0x0512..0x051B."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from enum import IntEnum

from ._client import OpenZiloClient
from ._core import native, call
from ._errors import ProtocolError, TimeoutError
from ._protocol import AudioCommand


class AudioOutput(IntEnum):
    AUTO = 0
    FLASH = 1
    LIVE = 2
    LIVE_AND_FLASH = 3


class AudioDisconnectPolicy(IntEnum):
    STOP = 0
    CONTINUE_SAVING = 1


class AudioRecordingState(IntEnum):
    IDLE = 0
    QUEUED = 1
    CAPTURING = 2
    FINALIZING = 3
    COMPLETE = 4
    FAILED = 5
    CANCELLED = 6


@dataclass(frozen=True)
class AudioRecordingConfig:
    output: AudioOutput = AudioOutput.AUTO
    disconnect_policy: AudioDisconnectPolicy = AudioDisconnectPolicy.STOP
    channels: int = 2
    bitrate: int = 32000
    gain_left_q8: int = 256
    gain_right_q8: int = 256
    max_duration_ms: int = 60000
    sample_rate: int = 16000
    frame_duration_ms: int = 20
    codec: int = 3
    complexity: int = 1
    vbr: int = 1
    constrained_vbr: int = 1
    dtx: int = 0
    fec: int = 0
    packet_loss_percent: int = 0
    signal: int = 3001
    bit_depth: int = 16
    max_packet_size: int = 100
    application: int = 2048

    def __post_init__(self) -> None:
        for name in ("output", "disconnect_policy", "channels", "bitrate", "gain_left_q8",
                     "gain_right_q8", "max_duration_ms", "sample_rate", "frame_duration_ms",
                     "codec", "complexity", "vbr", "constrained_vbr", "dtx", "fec",
                     "packet_loss_percent", "signal", "bit_depth", "max_packet_size", "application"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        object.__setattr__(self, "output", AudioOutput(self.output))
        object.__setattr__(self, "disconnect_policy", AudioDisconnectPolicy(self.disconnect_policy))
        if self.channels not in (1, 2) or not 8000 <= self.bitrate <= 32000:
            raise ValueError("Supported audio is mono/stereo at 8000..32000 bits/s")
        if not 0 <= self.gain_left_q8 <= 1024 or not 0 <= self.gain_right_q8 <= 1024:
            raise ValueError("Digital gains must be 0..1024 (256 = unity)")
        if self.max_duration_ms != 0 and (not 20 <= self.max_duration_ms <= 60000 or self.max_duration_ms % 20):
            raise ValueError("max_duration_ms must be 0 or 20..60000 in 20 ms increments")
        if (self.sample_rate, self.frame_duration_ms) != (16000, 20):
            raise ValueError("This firmware supports 16000 Hz and 20 ms frames")
        if (self.codec, self.complexity, self.vbr, self.constrained_vbr, self.dtx,
                self.fec, self.packet_loss_percent, self.signal, self.bit_depth,
                self.max_packet_size, self.application) != (3, 1, 1, 1, 0, 0, 0, 3001, 16, 100, 2048):
            raise ValueError("This firmware's fixed Opus profile is read-only")
        if (self.disconnect_policy == AudioDisconnectPolicy.CONTINUE_SAVING
                and self.output not in (AudioOutput.FLASH, AudioOutput.LIVE_AND_FLASH)):
            raise ValueError("CONTINUE_SAVING requires FLASH or LIVE_AND_FLASH")


@dataclass(frozen=True)
class AudioRecordingStatus:
    session_id: int
    state: AudioRecordingState
    saved: bool
    error_code: int
    file_index: int | None

    @property
    def finished(self) -> bool:
        return self.state in (AudioRecordingState.COMPLETE, AudioRecordingState.FAILED,
                              AudioRecordingState.CANCELLED)


def _config_body(config: AudioRecordingConfig) -> bytes:
    return bytes(call(native.recording_config_body, native.RecordingConfig(
        output=int(config.output), disconnect_policy=int(config.disconnect_policy),
        channels=config.channels, bitrate=config.bitrate, gain_left_q8=config.gain_left_q8,
        gain_right_q8=config.gain_right_q8, max_duration_ms=config.max_duration_ms)))


def _parse_config(body: bytes) -> AudioRecordingConfig:
    # The core validates the fixed firmware Opus profile, then Python re-checks its dataclass.
    c = call(native.parse_recording_config, bytes(body))
    try:
        return AudioRecordingConfig(c.output, c.disconnect_policy, c.channels, c.bitrate,
                                    c.gain_left_q8, c.gain_right_q8, c.max_duration_ms)
    except ValueError as exc:
        raise ProtocolError(str(exc)) from exc


async def get_audio_recording_config(
    client: OpenZiloClient, *, timeout_s: float | None = None,
) -> AudioRecordingConfig:
    packet = await client.request(AudioCommand.GET_RECORDING_CONFIG, AudioCommand.RECORDING_CONFIG,
                                  timeout_s=timeout_s)
    return _parse_config(packet.body)


async def set_audio_recording_config(
    client: OpenZiloClient, config: AudioRecordingConfig, *, timeout_s: float | None = None,
) -> AudioRecordingConfig:
    """Set volatile defaults while idle; return verified device readback.

    These settings survive a BLE reconnect, but reset on device reboot. A live
    output still needs live subscription before starting. Gains are digital;
    mono averages the independently scaled left/right samples before saturation.
    """
    if not isinstance(config, AudioRecordingConfig):
        raise TypeError("config must be AudioRecordingConfig")
    if client.capabilities is not None and client.capabilities.recording_limits is not None:
        client.capabilities.recording_limits.validate(config)
    async with client._recording_control_lock:
        packet = await client.request(AudioCommand.SET_RECORDING_CONFIG, AudioCommand.RECORDING_CONFIG_SET,
                                      _config_body(config), timeout_s=timeout_s)
        applied = _parse_config(packet.body)
        if applied != config:
            raise ProtocolError("Audio configuration readback does not match request")
        return applied


def _session_ack(body: bytes) -> int:
    return call(native.parse_session_ack, bytes(body))


async def start_audio_recording(
    client: OpenZiloClient, *, timeout_s: float | None = None,
) -> int:
    """Queue a remote recording and return its session id, not completion.

    Register the live receiver first when using LIVE or LIVE_AND_FLASH. A lost
    ACK leaves the outcome unknown: query status instead of retrying START.
    """
    async with client._recording_control_lock:
        client._check_command_access(AudioCommand.START_RECORDING)
        client._recording_active = True  # conservative if the ACK is lost
        packet = await client.request(AudioCommand.START_RECORDING, AudioCommand.RECORDING_STARTED,
                                      timeout_s=timeout_s)
        return _session_ack(packet.body)


async def stop_audio_recording(
    client: OpenZiloClient, session_id: int, *, cancel: bool = False,
    timeout_s: float | None = None,
) -> int:
    """Request graceful stop or discard; ACK is not a saved-file confirmation.

    Repeated graceful stops of the same session are safe. A stale session id
    cannot stop a newer recording. Query/wait for terminal status afterwards.
    """
    if isinstance(session_id, bool) or not isinstance(session_id, int) or not 1 <= session_id <= 0xFFFFFFFF:
        raise ValueError("session_id must be a nonzero u32")
    if not isinstance(cancel, bool):
        raise ValueError("cancel must be a bool")
    async with client._recording_control_lock:
        packet = await client.request(AudioCommand.STOP_RECORDING, AudioCommand.RECORDING_STOPPED,
                                      call(native.prepare_request, native.DeviceRequest.STOP_RECORDING(
                                          session_id=session_id, cancel=cancel)).body, timeout_s=timeout_s)
        returned = _session_ack(packet.body)
        if returned != session_id:
            raise ProtocolError("Recording stop response belongs to another session")
        return returned


async def get_audio_recording_status(
    client: OpenZiloClient, *, timeout_s: float | None = None,
) -> AudioRecordingStatus:
    packet = await client.request(AudioCommand.GET_RECORDING_STATUS, AudioCommand.RECORDING_STATUS,
                                  timeout_s=timeout_s)
    parsed = call(native.parse_recording_status, bytes(packet.body))
    status = AudioRecordingStatus(parsed.session_id, AudioRecordingState(parsed.state), parsed.saved,
                                  parsed.error_code, parsed.file_index)
    state = parsed.state
    client._recording_active = state in (1, 2, 3)
    return status


async def wait_audio_recording_finished(
    client: OpenZiloClient, session_id: int, *, timeout_s: float = 75.0,
    poll_interval_s: float = 0.2,
) -> AudioRecordingStatus:
    """Wait for capture and local file commit; raise on a failed or replaced session."""
    if isinstance(session_id, bool) or not isinstance(session_id, int) or not 1 <= session_id <= 0xFFFFFFFF:
        raise ValueError("session_id must be a nonzero u32")
    if not math.isfinite(timeout_s) or timeout_s <= 0 or not math.isfinite(poll_interval_s) or poll_interval_s <= 0:
        raise ValueError("Timeout and poll interval must be finite and positive")
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError("Recording completion is unconfirmed")
        status = await get_audio_recording_status(client, timeout_s=min(client.command_timeout_s, remaining))
        completion = call(native.recording_completion, native.RecordingStatus(
            session_id=status.session_id, state=int(status.state), saved=status.saved,
            error_code=status.error_code, file_index=status.file_index), session_id)
        if completion != native.RecordingCompletion.PENDING:
            return status
        await asyncio.sleep(min(poll_interval_s, max(0.0, deadline - asyncio.get_running_loop().time())))

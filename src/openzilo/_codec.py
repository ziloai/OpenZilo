# SPDX-License-Identifier: MPL-2.0
"""Recording formats (Speex, OP2C Opus) and WAV conversion."""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ._core import native, call_audio
from ._errors import AudioDecodeError, OpusDecoderUnavailable, SpeexDecoderUnavailable


_FFMPEG_TIMEOUT_S = 30.0
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
class OpusDecodeResult:
    pcm_bytes: bytes
    pcm_config: PcmConfig
    source_type: str = "opus-stereo"
    source_extension: str = "op2c"
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


SpeexDecoder = Callable[[bytes, Mapping[str, Any]], SpeexDecodeResult]


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
    return call_audio(native.export_wav_pcm, pcm_bytes, native.PcmFormat(
        sample_rate_hz=pcm_config.sample_rate, channels=pcm_config.channels,
        bit_depth=pcm_config.bit_depth))


def _read_ascii(data: bytes, start: int, length: int) -> str:
    return data[start : start + length].decode("ascii", errors="ignore")


def _find_ascii(data: bytes, target: str, max_scan_length: int | None = None) -> int:
    limit = min(len(data), max_scan_length or len(data))
    return data[:limit].find(target.encode("ascii"))


def is_wav(data: bytes) -> bool:
    return native.is_wav(bytes(data))


def is_ogg_speex(data: bytes) -> bool:
    return native.is_ogg_speex(bytes(data))


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
    return call_audio(native.speex_packet_size, _quality(quality), None)


def _quality(quality: int) -> int:
    value = int(quality or DEFAULT_SPEEX_QUALITY)
    return value if 0 <= value <= 255 else DEFAULT_SPEEX_QUALITY


def parse_packetized_speex_stream(
    data: Any,
    *,
    max_packet_size: int = DEFAULT_SPEEX_MAX_PACKET_SIZE,
    allow_framed_blocks: bool = True,
    framed_block_size: int = LEGACY_OUTER_FRAME_SIZE,
) -> list[bytes] | None:
    source = _ensure_bytes(data)
    max_size = max(1, int(max_packet_size or DEFAULT_SPEEX_MAX_PACKET_SIZE))
    block = max(1, int(framed_block_size or LEGACY_OUTER_FRAME_SIZE)) if allow_framed_blocks else None
    packets = call_audio(native.parse_packetized_speex_stream, source, max_size, block)
    return None if packets is None else [bytes(p) for p in packets]


def split_raw_speex_packets(
    data: Any,
    *,
    quality: int = DEFAULT_SPEEX_QUALITY,
    bits_size: int | None = None,
) -> list[bytes] | None:
    source = _ensure_bytes(data)
    size = pick_bits_size(quality=quality, bits_size=bits_size)
    packets = call_audio(native.split_raw_speex_packets, source, _quality(quality), size)
    return None if packets is None else [bytes(p) for p in packets]


def build_ogg_speex(
    packets: list[bytes],
    *,
    pcm_config: PcmConfig | Mapping[str, Any] | None = None,
    serial: int = 0x564F5247,
) -> bytes:
    config = normalize_pcm_config(pcm_config)
    rate = 8000 if config.sample_rate <= 8000 else 16000 if config.sample_rate <= 16000 else 32000
    return bytes(call_audio(native.export_ogg_speex, [bytes(p) for p in packets], rate,
                            serial & 0xFFFFFFFF))


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
    if config.sample_rate in (8000, 16000, 32000) and count <= 0xFFFFFFFF:
        return bytes(call_audio(native.normalize_decoded_speex_pcm, bytes(pcm_bytes), count,
                                native.PcmFormat(sample_rate_hz=config.sample_rate,
                                                 channels=config.channels,
                                                 bit_depth=config.bit_depth)))

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


def _decode_ogg_with_ffmpeg(
    ogg_bytes: bytes,
    *,
    pcm_config: PcmConfig | Mapping[str, Any] | None = None,
    ffmpeg_path: str = "ffmpeg",
    codec: str = "Speex",
) -> bytes:
    config = normalize_pcm_config(pcm_config)
    unavailable = SpeexDecoderUnavailable if codec == "Speex" else OpusDecoderUnavailable
    if not shutil.which(ffmpeg_path) and os.path.sep not in ffmpeg_path:
        raise unavailable(
            f"ffmpeg is required to decode {codec}. Install ffmpeg or pass --ffmpeg."
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
    if codec == "Opus":
        command.insert(1, "-xerror")
    try:
        completed = subprocess.run(
            command,
            input=ogg_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=_FFMPEG_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioDecodeError(f"ffmpeg {codec} decode timed out after {_FFMPEG_TIMEOUT_S:g} seconds") from exc
    except FileNotFoundError as exc:
        raise unavailable(
            f"ffmpeg is required to decode {codec}. Install ffmpeg or pass --ffmpeg."
        ) from exc

    if completed.returncode != 0:
        error_text = completed.stderr.decode("utf-8", errors="replace").strip()
        raise AudioDecodeError(f"ffmpeg {codec} decode failed: {error_text[:500]}")
    return completed.stdout


def decode_ogg_speex_with_ffmpeg(
    ogg_bytes: bytes,
    *,
    pcm_config: PcmConfig | Mapping[str, Any] | None = None,
    ffmpeg_path: str = "ffmpeg",
) -> bytes:
    return _decode_ogg_with_ffmpeg(ogg_bytes, pcm_config=pcm_config, ffmpeg_path=ffmpeg_path)


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

    decoded = call_audio(
        native.decode_speex_pcm,
        source,
        native.PcmFormat(sample_rate_hz=config.sample_rate, channels=config.channels,
                         bit_depth=config.bit_depth),
        _quality(quality),
        int(bits_size) if bits_size and bits_size > 0 else None,
        DEFAULT_SPEEX_MAX_PACKET_SIZE,
        LEGACY_OUTER_FRAME_SIZE if allow_framed_blocks else None,
    )
    return SpeexDecodeResult(
        pcm_bytes=bytes(decoded.pcm_bytes),
        pcm_config=config,
        source_type=decoded.source_type,
        source_extension="spx",
        packet_count=decoded.packet_count,
    )


def _validate_opus_packet(packet: bytes, *, channels: int = 2) -> None:
    if isinstance(channels, bool) or channels not in (1, 2):
        raise AudioDecodeError("Opus packet channels do not match the recording")
    call_audio(native.validate_opus_packet, bytes(packet), channels)


def _opus_recording_channels(source: bytes) -> int:
    return call_audio(native.parse_opus_recording, bytes(source)).channels


def parse_opus_recording(data: Any) -> list[bytes]:
    """Parse version-1, 16 kHz mono/stereo OP2C; reject truncation and padding."""
    recording = call_audio(native.parse_opus_recording, _ensure_bytes(data))
    return [bytes(packet) for packet in recording.packets]


def build_opus_recording(packets: list[bytes], *, channels: int = 2) -> bytes:
    """Package consecutive mono/stereo 20 ms Opus packets as an OP2C file."""
    if isinstance(channels, bool) or channels not in (1, 2):
        raise ValueError("channels must be 1 or 2")
    return bytes(call_audio(native.build_opus_recording, [bytes(p) for p in packets], channels))


def decode_opus_to_pcm(data: Any, *, ffmpeg_path: str = "ffmpeg") -> OpusDecodeResult:
    """Decode OP2C into 16 kHz mono/stereo signed 16-bit PCM (no external decoder needed)."""
    source = _ensure_bytes(data)
    recording = call_audio(native.parse_opus_recording, source)
    channels = recording.channels
    config = PcmConfig(sample_rate=16000, channels=channels, bit_depth=16)
    pcm = bytes(call_audio(native.decode_opus_pcm, source))
    return OpusDecodeResult(pcm, config, packet_count=len(recording.packets),
                            source_type="opus-mono" if channels == 1 else "opus-stereo")


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

    if source.startswith(b"OP2C"):
        decoded_opus = decode_opus_to_pcm(source, ffmpeg_path=ffmpeg_path)
        return PlayableAudio(
            bytes=build_wav_from_pcm(decoded_opus.pcm_bytes, decoded_opus.pcm_config),
            extension="wav", mime="audio/wav", play_mode="opus-decode", label="WAV",
            pcm_config=decoded_opus.pcm_config, source_type=decoded_opus.source_type,
            source_extension="op2c", source_mime="application/octet-stream",
            description=f"Decoded Opus as 16 kHz, {decoded_opus.pcm_config.channels}-channel, 16-bit WAV.",
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

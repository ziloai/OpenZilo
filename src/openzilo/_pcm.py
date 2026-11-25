# SPDX-License-Identifier: MPL-2.0
"""Stateful Opus-to-PCM decoding backed by the shared native core (no ffmpeg or PyAV)."""

from __future__ import annotations

from ._core import native, call_audio
from ._errors import OpusDecoderUnavailable


class _OpusPcmDecoder:
    """One decoder per recording; output is s16le mono or stereo, 20 ms per packet."""

    def __init__(self, *, channels: int = 2) -> None:
        if isinstance(channels, bool) or channels not in (1, 2):
            raise ValueError("channels must be 1 or 2")
        self._channels = channels
        try:
            self._decoder = native.RingOpusDecoder(channels)
        except native.CoreError as exc:
            raise OpusDecoderUnavailable("Could not initialize the live Opus decoder") from exc

    def decode(self, packet: bytes) -> list[bytes]:
        return [bytes(call_audio(self._decoder.decode_packet, bytes(packet)))]

    def flush(self) -> list[bytes]:
        # The decoder emits exactly one block per packet; nothing is buffered.
        return []

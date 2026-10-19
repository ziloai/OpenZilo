# SPDX-License-Identifier: MPL-2.0
"""Optional, stateful Opus-to-PCM decoding without an ffmpeg subprocess."""

from __future__ import annotations

import struct
import sys
from typing import Any

from ._errors import AudioDecodeError, OpusDecoderUnavailable


class _OpusPcmDecoder:
    """One decoder/resampler per recording; output is s16le mono or stereo."""

    def __init__(self, *, channels: int = 2) -> None:
        if channels not in (1, 2):
            raise ValueError("channels must be 1 or 2")
        self._channels = channels
        self._layout = "mono" if channels == 1 else "stereo"
        self._block_bytes = 320 * channels * 2
        try:
            import av
        except ImportError as exc:
            raise OpusDecoderUnavailable(
                "Install live PCM decoding with: uv sync --extra pcm"
            ) from exc
        self._av = av
        try:
            self._codec = av.CodecContext.create("opus", "r")
            # OP2C has no pre-skip or gain metadata. Preserve all samples.
            self._codec.extradata = struct.pack(
                "<8sBBHIhB", b"OpusHead", 1, channels, 0, 16000, 0, 0,
            )
            self._codec.open()
            self._resampler = av.AudioResampler(format="s16", layout=self._layout, rate=16000)
        except Exception as exc:
            raise OpusDecoderUnavailable("Could not initialize the live Opus decoder") from exc
        self._pending = bytearray()
        self._packets = 0
        self._samples = 0

    def _convert(self, frames: Any) -> None:
        for frame in frames:
            if (frame.sample_rate, frame.layout.name, frame.format.name) != (16000, self._layout, "s16"):
                raise AudioDecodeError("Unexpected live PCM format")
            # AV planes include alignment padding; expose only actual samples.
            pcm = bytes(frame.planes[0])[:frame.samples * self._channels * 2]
            if sys.byteorder != "little":
                from array import array
                samples = array("h", pcm)
                samples.byteswap()
                pcm = samples.tobytes()
            self._pending.extend(pcm)

    def _blocks(self) -> list[bytes]:
        blocks = []
        while len(self._pending) >= self._block_bytes:
            blocks.append(bytes(self._pending[:self._block_bytes]))
            del self._pending[:self._block_bytes]
            self._samples += 320
        return blocks

    def decode(self, packet: bytes) -> list[bytes]:
        try:
            for frame in self._codec.decode(self._av.Packet(packet)):
                self._convert(self._resampler.resample(frame))
            self._packets += 1
            return self._blocks()
        except AudioDecodeError:
            raise
        except Exception as exc:
            raise AudioDecodeError("Live Opus decoding failed") from exc

    def flush(self) -> list[bytes]:
        try:
            for frame in self._codec.decode(None):
                self._convert(self._resampler.resample(frame))
            self._convert(self._resampler.resample(None))
            blocks = self._blocks()
            if self._pending or self._samples != self._packets * 320:
                raise AudioDecodeError("Live Opus decoder returned an unexpected PCM length")
            return blocks
        except AudioDecodeError:
            raise
        except Exception as exc:
            raise AudioDecodeError("Could not flush the live Opus decoder") from exc

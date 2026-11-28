# SPDX-License-Identifier: MPL-2.0
"""Live recording subscription and streaming receive."""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import struct
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from ._core import native, call, native_packet
from ._errors import AudioDecodeError, ProtocolError, TimeoutError
from ._protocol import AudioCommand, ensure_success
from ._client import OpenZiloClient
from ._codec import PcmConfig, _validate_opus_packet, build_opus_recording
from ._audio import _audio_operation, _PacketInbox
from ._tasks import await_before

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveAudioSubscription:
    enabled: bool


@dataclass(frozen=True)
class LiveAudioStart:
    session_id: int
    record_time: int
    sample_rate: int
    channels: int
    codec: int


@dataclass(frozen=True)
class LiveAudioData:
    session_id: int
    sequence: int
    byte_offset: int
    data: bytes


@dataclass(frozen=True)
class LiveAudioEnd:
    error_code: int
    session_id: int
    produced_bytes: int
    sent_bytes: int
    dropped_frames: int


@dataclass(frozen=True)
class LiveAudioRecording:
    start: LiveAudioStart
    end: LiveAudioEnd
    data: bytes  # Complete OP2C file, suitable for decode_audio_to_wav().


async def set_live_audio_subscription(
    client: OpenZiloClient, enabled: bool, *, timeout_s: float | None = None,
) -> LiveAudioSubscription:
    """Enable BLE output for subsequent recordings.

    AUTO/legacy output is live-only when subscribed. Extended firmware can be
    configured as LIVE_AND_FLASH to retain a complete local backup.

    Enabling requires NUS notifications and ATT MTU >= 128. Firmware is the
    authority on MTU readiness. Disabling aborts an active live recording;
    disconnect clears the subscription. This never presses the record button.
    """
    if enabled and client._audio_owner not in (None, asyncio.current_task()):
        raise ProtocolError("Another audio operation is already active")
    timeout = client.command_timeout_s if timeout_s is None else timeout_s
    deadline = asyncio.get_running_loop().time() + max(0.0, timeout)
    return await await_before(
        _set_live_audio_subscription(client, enabled, timeout), deadline,
        "Timed out waiting for live subscription response",
    )


async def _set_live_audio_subscription(
    client: OpenZiloClient, enabled: bool, timeout_s: float,
) -> LiveAudioSubscription:
    async with client._live_subscription_lock:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a bool")
        client._check_command_access(AudioCommand.LIVE_SUBSCRIBE)
        # If an enable response is lost, conservatively require disable/reconnect
        # before OTA rather than assuming the device still saves to Flash.
        if enabled:
            client._live_audio_subscribed = True
        packet = await client.request(
            AudioCommand.LIVE_SUBSCRIBE, AudioCommand.LIVE_SUBSCRIBE_RESP,
            bytes([int(enabled)]), timeout_s=timeout_s,
        )
        if len(packet.body) == 3 and packet.body[2] in (0, 1):
            error = struct.unpack_from(">H", packet.body)[0]
            client._live_audio_subscribed = bool(packet.body[2])
            ensure_success(error)
        client._live_audio_subscribed = call(native.parse_live_subscription, bytes(packet.body))
        if client._live_audio_subscribed != enabled:
            raise ProtocolError("Live subscription response does not match request")
        return LiveAudioSubscription(client._live_audio_subscribed)


def parse_live_audio_start(body: bytes) -> LiveAudioStart:
    return LiveAudioStart(**vars(call(native.parse_live_start, bytes(body))))


def parse_live_audio_data(body: bytes, *, channels: int = 2) -> LiveAudioData:
    if isinstance(channels, bool) or channels not in (1, 2):
        raise ProtocolError("Opus packet channels do not match the recording")
    value = call(native.parse_live_data, bytes(body), channels)
    return LiveAudioData(value.session_id, value.sequence, value.byte_offset, bytes(value.data))


def parse_live_audio_end(body: bytes) -> LiveAudioEnd:
    return LiveAudioEnd(**vars(call(native.parse_live_end, bytes(body))))


@dataclass(frozen=True)
class LivePcmFrame:
    """20 ms of signed 16-bit little-endian mono/stereo PCM.

    Offsets and counts are samples per channel, not bytes or BLE timestamps.
    """

    session_id: int
    sample_offset: int
    sample_count: int
    data: bytes
    pcm_config: PcmConfig = PcmConfig(16000, 2, 16)


class LiveAudioStream:
    """A single recording's bounded START/DATA/END async event stream.

    Use open_live_audio_stream() and async with. Iteration has one consumer.
    Frames are provisional until a verified END; slow consumers fail explicitly.
    """

    def __init__(
        self, client: OpenZiloClient, *, output: Literal["opus", "pcm"],
        queue_size: int, timeout_s: float, recording_timeout_s: float,
    ) -> None:
        if output not in ("opus", "pcm"):
            raise ValueError("output must be 'opus' or 'pcm'")
        if isinstance(queue_size, bool) or not isinstance(queue_size, int) or queue_size < 1:
            raise ValueError("queue_size must be a positive integer")
        for value in (timeout_s, recording_timeout_s):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Live audio timeouts must be finite and positive")
        self._client = client
        self._output = output
        self._timeout = timeout_s
        self._recording_timeout = recording_timeout_s
        self._queue: asyncio.Queue[LiveAudioStart | LiveAudioData | LivePcmFrame | LiveAudioEnd] = (
            asyncio.Queue(maxsize=queue_size)
        )
        self._ready = asyncio.Event()
        self._done = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._decoder: Any = None
        self._error: Exception | None = None
        self._start: LiveAudioStart | None = None
        self._end: LiveAudioEnd | None = None
        self._deadline = 0.0
        self._sample_offset = 0
        self._entered = False
        self._active = False
        self._iterating = False
        self._ended = False

    @property
    def start(self) -> LiveAudioStart | None:
        return self._start

    @property
    def end(self) -> LiveAudioEnd | None:
        return self._end

    @property
    def complete(self) -> bool:
        return self._end is not None

    async def __aenter__(self) -> LiveAudioStream:
        if self._entered:
            raise ProtocolError("A live audio stream cannot be reused")
        self._entered = True
        if self._output == "pcm":
            from ._pcm import _OpusPcmDecoder
            # Fail before subscribing if the optional decoder is unavailable.
            self._decoder = _OpusPcmDecoder()
        self._active = True
        self._task = asyncio.create_task(self._run(), name="openzilo-live-audio")
        try:
            await self._ready.wait()
            if self._error is not None:
                raise self._error
            return self
        except BaseException:
            await self._close()
            raise

    async def _close(self) -> None:
        self._active = False
        if self._task is not None:
            if not self._task.done() and not self.complete:
                self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._decoder = None
        # Release queued frames on early exit; no complete recording is retained.
        while not self._queue.empty():
            self._queue.get_nowait()

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self._close()
        if exc_type is None and self._error is not None:
            raise self._error

    def __aiter__(self) -> LiveAudioStream:
        return self

    async def __anext__(self) -> LiveAudioStart | LiveAudioData | LivePcmFrame | LiveAudioEnd:
        if not self._active:
            raise ProtocolError("Consume live audio inside its async with block")
        if self._iterating:
            raise ProtocolError("A live audio stream allows only one consumer")
        self._iterating = True
        try:
            if self._error is not None:
                raise self._error
            if self._ended:
                raise StopAsyncIteration
            if self._queue.empty():
                if self._done.is_set():
                    raise StopAsyncIteration
                item = asyncio.create_task(self._queue.get())
                done = asyncio.create_task(self._done.wait())
                try:
                    await asyncio.wait({item, done}, return_when=asyncio.FIRST_COMPLETED)
                    if self._error is not None:
                        raise self._error
                    if item.done():
                        event = item.result()
                    elif not self._queue.empty():
                        event = self._queue.get_nowait()
                    else:
                        raise StopAsyncIteration
                finally:
                    for task in (item, done):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(item, done, return_exceptions=True)
            else:
                event = self._queue.get_nowait()
            if isinstance(event, LiveAudioEnd):
                self._ended = True
            return event
        finally:
            self._iterating = False

    def _emit(self, event: LiveAudioStart | LiveAudioData | LivePcmFrame | LiveAudioEnd) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull as exc:
            raise ProtocolError("Live audio consumer queue overflow; recording is incomplete") from exc

    async def _decode(self, function: Callable[..., list[bytes]], *args: Any) -> None:
        # Sequential worker calls preserve decoder state and keep BLE callbacks free.
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            blocks = await asyncio.shield(task)
        except asyncio.CancelledError:
            # A native decoder call cannot be cancelled. Join before releasing it.
            await asyncio.gather(task, return_exceptions=True)
            raise
        if asyncio.get_running_loop().time() >= self._deadline:
            raise TimeoutError("Live recording exceeded its time limit")
        for block in blocks:
            assert self._start is not None
            self._emit(LivePcmFrame(self._start.session_id, self._sample_offset, 320, block,
                                   PcmConfig(16000, self._start.channels, 16)))
            self._sample_offset += 320

    async def _run(self) -> None:
        try:
            await self._receive_owned(self._client, self)
        except Exception as exc:
            self._error = exc
        finally:
            self._ready.set()
            self._done.set()

    @staticmethod
    @_audio_operation
    async def _receive_owned(client: OpenZiloClient, stream: LiveAudioStream) -> None:
        if client._live_audio_subscribed:
            raise ProtocolError("Disable the existing live subscription before starting a managed recording")
        commands = (AudioCommand.LIVE_START, AudioCommand.LIVE_DATA, AudioCommand.LIVE_END)
        for command in commands:
            client._drain_queue(int(command))
        try:
            with _PacketInbox(client, commands) as inbox:
                await set_live_audio_subscription(client, True, timeout_s=stream._timeout)
                stream._ready.set()
                first = await inbox.wait(stream._timeout)
                if first.command != AudioCommand.LIVE_START:
                    raise ProtocolError("Live recording did not begin with START")
                validator = native.LiveValidator()
                started = call(validator.accept, native_packet(first))
                stream._start = LiveAudioStart(**vars(started.value))
                if stream._decoder is not None and stream._start.channels == 1:
                    from ._pcm import _OpusPcmDecoder
                    stream._decoder = _OpusPcmDecoder(channels=1)
                stream._deadline = asyncio.get_running_loop().time() + stream._recording_timeout
                stream._emit(stream._start)
                while True:
                    remaining = stream._deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise TimeoutError("Live recording exceeded its time limit")
                    packet = await inbox.wait(min(5.0, remaining))
                    # The core owns session, sequence, offset, size and END-counter validation.
                    event = call(validator.accept, native_packet(packet))
                    if isinstance(event, native.LiveEvent.DATA):
                        frame = LiveAudioData(event.value.session_id, event.value.sequence,
                                              event.value.byte_offset, bytes(event.value.data))
                        if stream._decoder is None:
                            stream._emit(frame)
                        else:
                            await stream._decode(stream._decoder.decode, frame.data)
                    elif isinstance(event, native.LiveEvent.END):
                        end = LiveAudioEnd(**vars(event.value))
                        if stream._decoder is not None and end.sent_bytes:
                            await stream._decode(stream._decoder.flush)
                        stream._emit(end)
                        stream._end = end
                        return
                    else:
                        raise ProtocolError("Unexpected START during live recording")
        finally:
            if client.is_connected and client._live_audio_subscribed:
                try:
                    await set_live_audio_subscription(client, False, timeout_s=2.0)
                except Exception as exc:
                    _logger.warning("Could not unsubscribe live audio; disconnect before reuse: %s", exc)

def open_live_audio_stream(
    client: OpenZiloClient, *, output: Literal["opus", "pcm"] = "pcm",
    queue_size: int = 64, timeout_s: float = 60.0, recording_timeout_s: float = 70.0,
) -> LiveAudioStream:
    """Open one button-triggered recording as ordered START/frame/END events.

    Entry confirms subscription, not recording start. PCM needs the ``pcm``
    extra; Opus requires only the base SDK. Flash retention follows device
    configuration; this iterator does not buffer the entire recording.
    Context exit aborts unfinished capture and attempts bounded unsubscribe.
    """
    return LiveAudioStream(client, output=output, queue_size=queue_size,
                           timeout_s=timeout_s, recording_timeout_s=recording_timeout_s)


async def receive_live_audio_file(
    client: OpenZiloClient, *, on_packet: Callable[[LiveAudioData], Any] | None = None,
    on_subscribed: Callable[[], Any] | None = None,
    timeout_s: float = 60.0, recording_timeout_s: float = 70.0,
) -> LiveAudioRecording:
    """Collect the verified Opus event stream into one complete OP2C recording.

    Callbacks may be sync or async and must return promptly. Slow callbacks
    fail with a bounded queue overflow rather than silently dropping audio.
    """
    packets: list[bytes] = []
    async with open_live_audio_stream(
        client, output="opus", queue_size=client._receive_queue_size,
        timeout_s=timeout_s, recording_timeout_s=recording_timeout_s,
    ) as stream:
        if on_subscribed is not None:
            result = on_subscribed()
            if inspect.isawaitable(result):
                await await_before(result, asyncio.get_running_loop().time() + timeout_s,
                                   "on_subscribed callback timed out")
        async for event in stream:
            if isinstance(event, LiveAudioData):
                packets.append(event.data)
                if on_packet is not None:
                    result = on_packet(event)
                    if inspect.isawaitable(result):
                        await await_before(result, stream._deadline,
                                           "Live recording exceeded its time limit")
        assert stream.start is not None and stream.end is not None
        return LiveAudioRecording(stream.start, stream.end,
                                  build_opus_recording(packets, channels=stream.start.channels))

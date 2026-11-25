# SPDX-License-Identifier: MPL-2.0
"""Saved recording transfer: listing, downloading and automatic receive."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import IntEnum
from functools import wraps
from typing import Any

import struct

from ._core import native, call, native_packet
from ._errors import DeviceError, ProtocolError, TimeoutError, TransportError
from ._protocol import AudioCommand, Packet, SystemCommand
from ._client import OpenZiloClient


@dataclass(frozen=True)
class AudioFileInfo:
    file_index: int
    record_time: int
    data_size: int


@dataclass(frozen=True)
class AudioDataFrame:
    file_index: int
    frame_offset: int
    frame_size: int
    is_end: bool
    data: bytes


@dataclass(frozen=True)
class AudioRecordResult:
    file_index: int


AudioProgressCallback = Callable[[int, int], None]


class ProgressPrinter:
    def __init__(self, *, prefix: str = "progress") -> None:
        self.prefix = prefix
        self._last_percent = -1

    def __call__(self, current: int, total: int) -> None:
        percent = int(current * 100 / total) if total else 0
        if percent == self._last_percent:
            return
        self._last_percent = percent
        print(f"{self.prefix}: {current}/{total} bytes ({percent}%)")


def _audio_operation(function: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    @wraps(function)
    async def guarded(client: OpenZiloClient, *args: Any, **kwargs: Any) -> Any:
        task = asyncio.current_task()
        if client._firmware_update_active:
            raise ProtocolError("Firmware update owns this connection")
        if client._audio_owner is not None and client._audio_owner is not task:
            raise ProtocolError("Another audio operation is already active")
        nested = client._audio_owner is task
        client._audio_owner = task
        try:
            return await function(client, *args, **kwargs)
        finally:
            if not nested:
                client._audio_owner = None
    return guarded


class _PacketInbox:
    """Temporarily own several commands in notification order, without duplicate queues."""

    def __init__(self, client: OpenZiloClient, commands: tuple[IntEnum, ...]) -> None:
        self.client = client
        self.commands = commands
        self.queue: asyncio.Queue[Packet] = asyncio.Queue(maxsize=client._receive_queue_size)
        self.error: ProtocolError | None = None
        self.registered: list[IntEnum] = []

    def _receive(self, packet: Packet) -> None:
        if self.queue.full():
            self.error = ProtocolError("Audio receive queue overflow; recording is incomplete")
        else:
            self.queue.put_nowait(packet)

    def __enter__(self) -> "_PacketInbox":
        try:
            for command in self.commands:
                if self.client._handlers[int(command)]:
                    raise ProtocolError("Audio command already has a packet handler")
            for command in self.commands:
                pending = self.client._queues[int(command)]
                while not pending.empty():
                    self._receive(pending.get_nowait())
                self.client.add_packet_handler(command, self._receive, queue_packets=False)
                self.registered.append(command)
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_args: Any) -> None:
        for command in self.registered:
            self.client.remove_packet_handler(command, self._receive)
        # A legacy automatic upload may arrive entirely in one notification.
        # Return its remaining frames to the ordinary queue after selecting the first.
        while not self.queue.empty():
            packet = self.queue.get_nowait()
            if not self.client.is_connected:
                continue
            if packet.command == SystemCommand.ERROR_RESP:
                continue
            target = self.client._queues[packet.command]
            if target.full():
                self.client._report_protocol_error(ProtocolError("Audio receive queue overflow"))
            else:
                target.put_nowait(packet)

    async def wait(self, timeout_s: float | None) -> Packet:
        if self.error is not None:
            raise self.error
        timeout = self.client.command_timeout_s if timeout_s is None else timeout_s
        if self.client._disconnected.is_set() and self.queue.empty():
            raise TransportError("BLE disconnected while receiving audio")
        packet_task = asyncio.create_task(self.queue.get())
        error_task = asyncio.create_task(self.client._protocol_errors.get())
        disconnected = asyncio.create_task(self.client._disconnected.wait())
        tasks = {packet_task, error_task, disconnected}
        try:
            done, _ = await asyncio.wait(tasks, timeout=max(0.0, timeout),
                                         return_when=asyncio.FIRST_COMPLETED)
            if self.error is not None:
                raise self.error
            if error_task in done:
                raise error_task.result()
            if packet_task in done:
                return packet_task.result()
            if disconnected in done:
                raise TransportError("BLE disconnected while receiving audio")
            raise TimeoutError("Timed out waiting for recording data or completion")
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


_MAX_AUDIO_BYTES = 64 * 1024 * 1024
_EXTRACT_COMMANDS = (0x0503, 0x0506, 0x0507, 0x0509)


def parse_audio_record_result(body: bytes) -> AudioRecordResult:
    return AudioRecordResult(call(native.parse_audio_record_result, bytes(body)))


def parse_audio_file_info(body: bytes) -> AudioFileInfo:
    return AudioFileInfo(**vars(call(native.parse_audio_info, bytes(body))))


def parse_audio_data_frame(body: bytes) -> AudioDataFrame:
    frame = call(native.parse_audio_frame, bytes(body))
    return AudioDataFrame(frame.file_index, frame.frame_offset, frame.frame_size, frame.is_end,
                          bytes(frame.data))


async def _send_spec(client: OpenZiloClient, spec: Any) -> None:
    await client.send_command(spec.command, bytes(spec.body))


def _prepare(request: Any) -> Any:
    return call(native.prepare_request, request)


@_audio_operation
async def wait_audio_record_result(
    client: OpenZiloClient, *, timeout_s: float | None = None,
) -> AudioRecordResult:
    """Wait for 050A local-save completion; does not download or start recording."""
    packet = await client.wait_for_command(AudioCommand.RECORD_RESULT, timeout_s=timeout_s)
    return parse_audio_record_result(packet.body)


async def get_audio_file_count(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> int:
    packet = await client.request(
        AudioCommand.GET_LIST,
        AudioCommand.LIST_RESP,
        timeout_s=timeout_s,
    )
    return call(native.parse_audio_count, bytes(packet.body))


@_audio_operation
async def get_audio_file_info(
    client: OpenZiloClient,
    file_index: int,
    *,
    timeout_s: float | None = None,
) -> AudioFileInfo:
    """Start the normal 0x0503 extraction flow and return recording metadata."""
    spec = _prepare(native.DeviceRequest.AUDIO_INFO(file_index=file_index))
    packet = await client.request(
        AudioCommand.START_EXTRACT,
        AudioCommand.FILE_INFO_RESP,
        bytes(spec.body),
        timeout_s=timeout_s,
    )
    return parse_audio_file_info(packet.body)


@_audio_operation
async def read_audio_frame(
    client: OpenZiloClient,
    file_index: int,
    frame_offset: int,
    *,
    timeout_s: float | None = None,
) -> AudioDataFrame:
    spec = _prepare(native.DeviceRequest.AUDIO_READ(file_index=file_index, offset=frame_offset))
    packet = await client.request(
        AudioCommand.NEXT_FRAME,
        AudioCommand.DATA_FRAME,
        bytes(spec.body),
        timeout_s=timeout_s,
    )
    return parse_audio_data_frame(packet.body)


@_audio_operation
async def end_audio_extract(
    client: OpenZiloClient,
    file_index: int,
    *,
    timeout_s: float | None = None,
    ignore_timeout: bool = True,
) -> None:
    spec = _prepare(native.DeviceRequest.AUDIO_END(file_index=file_index))
    try:
        packet = await client.request(
            AudioCommand.END_EXTRACT,
            AudioCommand.EXTRACT_DONE,
            bytes(spec.body),
            timeout_s=timeout_s,
        )
    except TimeoutError:
        if ignore_timeout:
            return
        raise
    call(native.parse_audio_end, bytes(packet.body))


@_audio_operation
async def clear_audio_files(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> None:
    spec = _prepare(native.DeviceRequest.CLEAR_AUDIO(confirmed=True))
    packet = await client.request(
        AudioCommand.CLEAR_ALL,
        AudioCommand.CLEAR_ALL_RESP,
        bytes(spec.body),
        timeout_s=timeout_s,
    )
    call(native.parse_success, bytes(packet.body))


def _now_ms() -> int:
    return int(asyncio.get_running_loop().time() * 1000)


def _relevant(packet: Packet) -> bool:
    """Standard error replies for other commands are not ours to interpret."""
    if packet.command != SystemCommand.ERROR_RESP:
        return True
    return len(packet.body) >= 2 and struct.unpack_from(">H", packet.body)[0] in _EXTRACT_COMMANDS


async def _drive(client: OpenZiloClient, transfer: Any, step: Any, inbox: _PacketInbox,
                 timeout: float, progress: AudioProgressCallback | None = None,
                 on_packet: Callable[[Packet], None] | None = None) -> Any:
    """Run a core transfer state machine until it reports COMPLETE."""
    last = -1
    while True:
        if progress is not None and step.received != last:
            last = step.received
            progress(step.received, step.total or 0)
        if step.phase == native.DownloadPhase.COMPLETE:
            return step
        if step.request is not None:
            await _send_spec(client, step.request)
        deadline = transfer.next_deadline()
        remaining = timeout if deadline is None else max(0.0, (deadline - _now_ms()) / 1000)
        try:
            packet = await inbox.wait(remaining)
        except TimeoutError:
            step = call(transfer.tick, _now_ms())
            continue
        if not _relevant(packet):
            continue
        if on_packet is not None:
            on_packet(packet)
        step = call(transfer.accept, native_packet(packet), _now_ms())


async def _best_effort_end(client: OpenZiloClient, file_index: int) -> None:
    if not client.is_connected:
        return
    spec = _prepare(native.DeviceRequest.AUDIO_END(file_index=file_index))
    try:
        await asyncio.wait_for(client.request(
            AudioCommand.END_EXTRACT, AudioCommand.EXTRACT_DONE, bytes(spec.body), timeout_s=2.0,
        ), timeout=2.0)
    except (Exception, asyncio.CancelledError):
        pass


def _timeouts(client: OpenZiloClient, timeout_s: float | None) -> tuple[float, int, int]:
    timeout = client.command_timeout_s if timeout_s is None else timeout_s
    return timeout, max(1, int(timeout * 1000)), max(1, int(max(600.0, timeout) * 1000))


@_audio_operation
async def receive_auto_audio_file(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> tuple[int, bytes]:
    """Receive one saved recording from either firmware generation.

    Legacy firmware pushes 0505; new firmware sends 050A and the SDK downloads
    that file explicitly. Returns (file_index, original bytes), which may be
    Speex or OP2C. Live-only recordings use receive_live_audio_file instead.
    Competing audio operations are rejected.
    """
    if not client.is_connected:
        raise TransportError("BLE client is not connected")
    timeout, idle_ms, total_ms = _timeouts(client, timeout_s)
    transfer = call(native.AutoAudioTransfer, _MAX_AUDIO_BYTES, idle_ms, total_ms)
    commands = (AudioCommand.RECORD_RESULT, AudioCommand.FILE_INFO_RESP, AudioCommand.DATA_FRAME,
                AudioCommand.EXTRACT_DONE, SystemCommand.ERROR_RESP)
    delegated = {"index": None}

    def remember(packet: Packet) -> None:
        if packet.command == AudioCommand.RECORD_RESULT and delegated["index"] is None:
            delegated["index"] = parse_audio_record_result(packet.body).file_index

    try:
        with _PacketInbox(client, commands) as inbox:
            step = call(transfer.begin, _now_ms())
            step = await _drive(client, transfer, step, inbox, timeout, on_packet=remember)
        return step.file_index, bytes(call(transfer.finish))
    except (Exception, asyncio.CancelledError):
        transfer.cancel()
        if delegated["index"] is not None:
            await _best_effort_end(client, delegated["index"])
        raise


async def _download_audio_file_quick(
    client: OpenZiloClient,
    file_index: int,
    *,
    progress: AudioProgressCallback | None = None,
    timeout_s: float | None = None,
) -> tuple[AudioFileInfo, bytes]:
    """Fast extraction: the device pushes frames and sends no END acknowledgement."""
    timeout, _, _ = _timeouts(client, timeout_s)
    commands = (AudioCommand.FILE_INFO_RESP, AudioCommand.DATA_FRAME, SystemCommand.ERROR_RESP)

    def check_error(packet: Packet) -> None:
        if packet.command == SystemCommand.ERROR_RESP:
            command, code = struct.unpack_from(">HH", packet.body)
            raise DeviceError(code, native.device_error_message(code))

    async def next_packet(wanted: int | None = None) -> Packet:
        while True:
            packet = await inbox.wait(timeout)
            if not _relevant(packet):
                continue
            check_error(packet)
            if wanted is None or packet.command == wanted:
                return packet

    with _PacketInbox(client, commands) as inbox:
        await _send_spec(client, _prepare(native.DeviceRequest.AUDIO_QUICK(file_index=file_index)))
        info = parse_audio_file_info((await next_packet(AudioCommand.FILE_INFO_RESP)).body)
        if info.file_index != file_index:
            raise ProtocolError(
                f"Audio metadata index mismatch: expected {file_index}, got {info.file_index}"
            )
        assembler = call(native.AudioAssembler, file_index, info.data_size, _MAX_AUDIO_BYTES)
        retries = 0
        received = 0

        async def retry(reason: str) -> None:
            nonlocal retries
            retries += 1
            if retries > 3:
                raise ProtocolError(reason)
            offset = assembler.missing_offset() or 0
            await _send_spec(client, _prepare(
                native.DeviceRequest.AUDIO_READ(file_index=file_index, offset=offset)))

        while assembler.missing_offset() is not None:
            try:
                packet = await next_packet(AudioCommand.DATA_FRAME)
            except TimeoutError:
                await retry(f"Audio stream stalled at offset {received}")
                continue
            frame = parse_audio_data_frame(packet.body)
            if frame.file_index != file_index:
                continue
            missing = assembler.missing_offset()
            if frame.frame_offset > missing:
                await retry(f"Audio frame gap: expected offset {missing}, got {frame.frame_offset}")
                continue
            data = frame.data[:max(0, info.data_size - frame.frame_offset)]
            previous = received
            received = call(assembler.push, native.AudioFrame(
                file_index=frame.file_index, frame_offset=frame.frame_offset,
                frame_size=len(data), is_end=frame.is_end, data=data))
            if received > previous:
                retries = 0
            if progress:
                progress(received, info.data_size)
            if assembler.missing_offset() is None:
                break
            if frame.is_end:
                await retry(f"Audio stream ended at {received} of {info.data_size} bytes")
            elif not frame.data:
                raise ProtocolError(f"Empty audio frame at offset {frame.frame_offset} before end")
    return info, bytes(call(assembler.finish))


@_audio_operation
async def download_audio_file(
    client: OpenZiloClient,
    file_index: int,
    *,
    progress: AudioProgressCallback | None = None,
    timeout_s: float | None = None,
    quick: bool = True,
) -> tuple[AudioFileInfo, bytes]:
    if quick:
        return await _download_audio_file_quick(
            client, file_index, progress=progress, timeout_s=timeout_s,
        )
    timeout, idle_ms, total_ms = _timeouts(client, timeout_s)
    transfer = call(native.DownloadTransfer, file_index, _MAX_AUDIO_BYTES, False, idle_ms, total_ms)
    commands = (AudioCommand.FILE_INFO_RESP, AudioCommand.DATA_FRAME, AudioCommand.EXTRACT_DONE,
                SystemCommand.ERROR_RESP)
    started = False
    try:
        with _PacketInbox(client, commands) as inbox:
            step = call(transfer.begin, _now_ms())
            started = True
            await _drive(client, transfer, step, inbox, timeout, progress)
        info = transfer.info()
        return AudioFileInfo(**vars(info)), bytes(call(transfer.finish))
    except (Exception, asyncio.CancelledError):
        transfer.cancel()
        if started:
            await _best_effort_end(client, file_index)
        raise

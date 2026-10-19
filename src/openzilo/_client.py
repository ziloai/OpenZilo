# SPDX-License-Identifier: MPL-2.0
"""Protocol session: request/response matching and packet dispatch."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from enum import IntEnum
from typing import Any, DefaultDict

from ._errors import CompatibilityError, DeviceError, ProtocolError, TimeoutError, TransportError
from ._tasks import acquire_before, await_before, start_background_task
from ._protocol import BinaryReader, encode_packet, Packet, PacketStream, SystemCommand, TimeCommand
from ._compatibility import COMMAND_FEATURES, DeviceCapabilities
from ._transport import BleDeviceInfo, DEFAULT_SCAN_TIMEOUT_S, NusClient

_logger = logging.getLogger(__name__)
DEFAULT_COMMAND_TIMEOUT_S = 10.0
_ota_context: ContextVar[object | None] = ContextVar("openzilo_ota", default=None)
PacketHandler = Callable[[Packet], None | Awaitable[None]]


class OpenZiloClient:
    """High-level BLE protocol client."""

    def __init__(
        self,
        *,
        address: str | None = None,
        device: BleDeviceInfo | None = None,
        scan_timeout_s: float = DEFAULT_SCAN_TIMEOUT_S,
        connect_timeout_s: float = 30.0,
        command_timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S,
        transport: NusClient | None = None,
        receive_queue_size: int = 256,
        allow_unverified_features: bool = False,
    ) -> None:
        if not isinstance(receive_queue_size, int) or receive_queue_size < 1:
            raise ValueError("receive_queue_size must be a positive integer")
        self._capability_check_required = False
        self.capabilities: DeviceCapabilities | None = None
        self.allow_unverified_features = allow_unverified_features
        self._capability_lock = asyncio.Lock()
        self._request_errors: dict[int, asyncio.Future[DeviceError]] = {}
        self.command_timeout_s = command_timeout_s
        self.transport = transport if transport is not None else NusClient(
            address=address, device=device, scan_timeout_s=scan_timeout_s,
            connect_timeout_s=connect_timeout_s,
        )
        self._stream = PacketStream()
        self._queues: DefaultDict[int, asyncio.Queue[Packet]] = defaultdict(
            lambda: asyncio.Queue(maxsize=receive_queue_size)
        )
        self._handlers: DefaultDict[int, list[PacketHandler]] = defaultdict(list)
        self._protocol_errors: asyncio.Queue[ProtocolError] = asyncio.Queue(maxsize=1)
        self._request_locks: DefaultDict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._callback_only: set[int] = set()
        self._audio_owner: asyncio.Task[Any] | None = None
        self._firmware_update_owner: object | None = None
        self._live_audio_subscribed = False
        self._recording_active = False
        self._recording_control_lock = asyncio.Lock()
        self._live_subscription_lock = asyncio.Lock()
        self._receive_queue_size = receive_queue_size
        self._disconnected = asyncio.Event()
        self._disconnected.set()
        self._connection_ready = asyncio.Event()
        self._connection_token: object | None = None
        self._time_sync_enabled = False
        self._write_lock = asyncio.Lock()
        self._write_interrupted = False
        self._callback_tasks: set[asyncio.Task[Any]] = set()
        self._firmware_update_active = False

    @staticmethod
    async def discover(*args: Any, **kwargs: Any) -> list[BleDeviceInfo]:
        return await NusClient.discover(*args, **kwargs)

    @property
    def is_connected(self) -> bool:
        return self.transport.is_connected

    async def connect(self) -> None:
        self._capability_check_required = False
        self.capabilities = None
        self._clear_receive_state()
        self._connection_token = object()
        self._connection_ready = asyncio.Event()
        self._write_interrupted = False
        self._disconnected.clear()
        self.transport.set_rx_callback(self._on_rx)
        set_disconnect_callback = getattr(
            self.transport,
            "_set_disconnect_callback",
            None,
        )
        if callable(set_disconnect_callback):
            set_disconnect_callback(self._on_disconnect)
        try:
            await self.transport.connect()
            if self._disconnected.is_set() or not self.is_connected:
                raise TransportError("BLE disconnected before the connection became ready")
            self._connection_ready.set()
        except BaseException:
            self._on_disconnect()
            raise

    async def disconnect(self) -> None:
        # Stop automatic replies before stop_notify/disconnect starts closing BLE.
        self._on_disconnect()
        try:
            await self.transport.disconnect()
        finally:
            self._on_disconnect()

    def _check_command_access(self, command: int | IntEnum) -> None:
        feature = COMMAND_FEATURES.get(int(command))
        if feature and self._capability_lock.locked():
            raise ProtocolError("Wait for capability discovery before enhanced commands")
        if feature and self._capability_check_required and self.capabilities is None:
            raise CompatibilityError("Capability discovery failed; rediscover before enhanced commands")
        if feature and self.capabilities is not None and not (
            self.allow_unverified_features and self.capabilities.source == "unknown"
        ):
            self.capabilities.require(feature)
        if (self._firmware_update_active
                and _ota_context.get() is not self._firmware_update_owner
                and int(command) != int(TimeCommand.RESPONSE)):
            raise ProtocolError("Firmware update owns this connection")

    async def send_command(self, command: int | IntEnum, body: bytes = b"") -> None:
        await self._send_command(command, lambda: body)

    async def _send_when_ready(
        self, command: int | IntEnum, body: Callable[[], bytes], connection: object | None,
    ) -> None:
        """Defer an automatic reply, keeping it scoped to its originating connection."""
        if connection is None or connection is not self._connection_token:
            return
        await self._connection_ready.wait()
        await self._send_command(command, body, connection=connection)

    async def _send_command(
        self, command: int | IntEnum, body: Callable[[], bytes], *, connection: object | None = None,
    ) -> None:
        self._check_command_access(command)
        # Keep fragmented writes (including automatic time replies) contiguous.
        async with self._write_lock:
            if connection is not None and (
                connection is not self._connection_token or self._disconnected.is_set()
            ):
                return
            self._check_command_access(command)
            if self._write_interrupted:
                raise TransportError("A previous BLE write was interrupted; reconnect before sending")
            write_connection = self._connection_token
            try:
                # Build time-sensitive bodies only after acquiring the write lock.
                await self.transport.write(encode_packet(int(command), body()))
            except asyncio.CancelledError:
                # A fragmented packet may be half-sent; another packet would desynchronize the device.
                if write_connection is self._connection_token:
                    self._write_interrupted = True
                raise

    async def request(
        self,
        command: int | IntEnum,
        response_command: int | IntEnum,
        body: bytes = b"",
        *,
        timeout_s: float | None = None,
    ) -> Packet:
        self._check_command_access(command)
        response_id = int(response_command)
        if response_id in self._callback_only:
            raise ProtocolError("Response command is owned by a callback-only handler")
        timeout = self.command_timeout_s if timeout_s is None else timeout_s
        deadline = asyncio.get_running_loop().time() + max(0.0, timeout)
        message = f"Timed out waiting for command 0x{response_id:04X}"
        lock = self._request_locks[response_id]
        await acquire_before(lock, deadline, message)
        error_future: asyncio.Future[DeviceError] | None = None
        try:
            self._check_command_access(command)
            if int(command) in self._request_errors:
                raise ProtocolError("Concurrent requests for the same command are ambiguous")
            error_future = asyncio.get_running_loop().create_future()
            self._request_errors[int(command)] = error_future
            self._drain_queue(response_id)
            self._drain_protocol_errors()
            await await_before(self.send_command(command, body), deadline, message)
            return await self._wait_for_command(
                response_id, timeout_s=deadline - asyncio.get_running_loop().time(),
                request_error=error_future,
            )
        finally:
            if error_future is not None:
                self._request_errors.pop(int(command), None)
                error_future.cancel()
            lock.release()

    async def wait_for_command(
        self,
        command: int | IntEnum,
        *,
        timeout_s: float | None = None,
    ) -> Packet:
        return await self._wait_for_command(command, timeout_s=timeout_s)

    async def _wait_for_command(
        self, command: int | IntEnum, *, timeout_s: float | None = None,
        request_error: asyncio.Future[DeviceError] | None = None,
    ) -> Packet:
        self._check_command_access(command)
        command_id = int(command)
        if command_id in self._callback_only:
            raise ProtocolError("Command is owned by a callback-only handler")
        timeout = self.command_timeout_s if timeout_s is None else timeout_s
        if self._disconnected.is_set():
            raise TransportError(
                f"BLE disconnected while waiting for command 0x{command_id:04X}"
            )

        packet_task = asyncio.create_task(self._queues[command_id].get())
        error_task = asyncio.create_task(self._protocol_errors.get())
        disconnect_task = asyncio.create_task(self._disconnected.wait())
        tasks = {packet_task, error_task, disconnect_task}
        if request_error is not None:
            tasks.add(request_error)
        try:
            done, _pending = await asyncio.wait(
                tasks,
                timeout=max(0.0, timeout),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise TimeoutError(
                    f"Timed out waiting for command 0x{command_id:04X}"
                )
            if request_error is not None and request_error in done:
                raise request_error.result()
            if error_task in done:
                raise error_task.result()
            if disconnect_task in done:
                raise TransportError(
                    f"BLE disconnected while waiting for command 0x{command_id:04X}"
                )
            return packet_task.result()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def add_packet_handler(
        self, command: int | IntEnum, handler: PacketHandler, *, queue_packets: bool = True,
    ) -> None:
        """Register a handler; queue_packets=False gives it exclusive packet delivery."""
        command_id = int(command)
        if command_id in self._callback_only or (not queue_packets and self._handlers[command_id]):
            raise ProtocolError("Callback-only delivery requires an exclusive handler")
        if not queue_packets:
            self._callback_only.add(command_id)
            self._drain_queue(command_id)
        self._handlers[command_id].append(handler)

    def remove_packet_handler(
        self,
        command: int | IntEnum,
        handler: PacketHandler,
    ) -> None:
        self._handlers[int(command)].remove(handler)
        self._callback_only.discard(int(command))

    async def __aenter__(self) -> "OpenZiloClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.disconnect()

    def _on_rx(self, data: bytes) -> None:
        try:
            packets = self._stream.feed(data)
        except ProtocolError as exc:
            self._stream.clear()
            self._report_protocol_error(exc)
            return

        for packet in packets:
            if packet.command == SystemCommand.ERROR_RESP:
                try:
                    reader = BinaryReader(packet.body)
                    failed_command, code = reader.u16(), reader.u16()
                    if reader.remaining or not code:
                        raise ProtocolError("Invalid standard error response")
                except ProtocolError as exc:
                    self._report_protocol_error(exc)
                    continue
                pending = self._request_errors.get(failed_command)
                if pending is not None and not pending.done():
                    pending.set_result(DeviceError(code,
                        f"Command 0x{failed_command:04X} rejected with error {code}"))
                continue
            if packet.command not in self._callback_only:
                queue = self._queues[packet.command]
                if queue.full():
                    self._drain_queue(packet.command)
                    self._report_protocol_error(ProtocolError(
                        f"Receive queue overflow for command 0x{packet.command:04X}; data was lost"
                    ))
                queue.put_nowait(packet)
            for handler in list(self._handlers.get(packet.command, [])):
                try:
                    result = handler(packet)
                except Exception:
                    _logger.exception("Packet handler for 0x%04X failed", packet.command)
                    continue
                if inspect.isawaitable(result):
                    start_background_task(
                        self._callback_tasks, result, f"Packet handler for 0x{packet.command:04X}",
                    )

    def _report_protocol_error(self, error: ProtocolError) -> None:
        if not self._protocol_errors.full():
            self._protocol_errors.put_nowait(error)

    def _on_disconnect(self) -> None:
        self.capabilities = None
        self._connection_token = None
        self._connection_ready.clear()
        self._disconnected.set()
        self._clear_receive_state()
        for task in list(self._callback_tasks):
            task.cancel()

    def _drain_queue(self, command: int) -> None:
        queue = self._queues[command]
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return

    def _drain_protocol_errors(self) -> None:
        while True:
            try:
                self._protocol_errors.get_nowait()
            except asyncio.QueueEmpty:
                return

    def _clear_receive_state(self) -> None:
        self._live_audio_subscribed = False
        self._stream.clear()
        for command in list(self._queues):
            self._drain_queue(command)
        self._drain_protocol_errors()

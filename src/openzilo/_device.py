# SPDX-License-Identifier: MPL-2.0
"""Connection helpers and device-level operations: system info, logs and time sync."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ._core import native, call
from ._protocol import (
    BinaryReader,
    BinaryWriter,
    ensure_success,
    LogCommand,
    Packet,
    read_error,
    SystemCommand,
    TimeCommand,
)
from ._transport import BleDeviceInfo, DEFAULT_SCAN_TIMEOUT_S
from ._client import DEFAULT_COMMAND_TIMEOUT_S, OpenZiloClient
from ._errors import ProtocolError, TimeoutError, TransportError


@dataclass(frozen=True)
class SystemInfo:
    firmware_version: str
    system_time: int
    audio_storage_total: int
    audio_storage_available: int
    battery_percent: int
    battery_charging: bool
    sn: str
    cpuid: str
    model: str


@dataclass(frozen=True)
class LogStorageInfo:
    page_size: int
    total_len: int


async def scan_rings(
    *,
    address: str | None = None,
    timeout_s: float = DEFAULT_SCAN_TIMEOUT_S,
    on_devices_changed: Callable[[list[BleDeviceInfo]], None] | None = None,
) -> list[BleDeviceInfo]:
    """Scan ring candidates, or locate an explicit device address/identifier."""
    return await OpenZiloClient.discover(
        address=address,
        timeout_s=timeout_s,
        on_devices_changed=on_devices_changed,
    )


async def connect_ring(
    *,
    address: str | None = None,
    device: BleDeviceInfo | None = None,
    scan_timeout_s: float = DEFAULT_SCAN_TIMEOUT_S,
    connect_timeout_s: float = 30.0,
    command_timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S,
    auto_time_sync: bool = False,
    negotiate_capabilities: bool = True,
    allow_unverified_features: bool = False,
) -> OpenZiloClient:
    """Create and connect a OpenZiloClient."""
    client = OpenZiloClient(
        address=address,
        device=device,
        scan_timeout_s=scan_timeout_s,
        connect_timeout_s=connect_timeout_s,
        command_timeout_s=command_timeout_s,
        allow_unverified_features=allow_unverified_features,
    )
    if auto_time_sync:
        enable_time_sync(client)
    await client.connect()
    try:
        if negotiate_capabilities:
            from ._compatibility import get_device_capabilities
            await get_device_capabilities(client, timeout_s=min(command_timeout_s, 3.0))
    except BaseException:
        await client.disconnect()
        raise
    return client


async def get_system_info(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> SystemInfo:
    packet = await client.request(
        SystemCommand.GET_INFO,
        SystemCommand.INFO_RESP,
        timeout_s=timeout_s,
    )
    return parse_system_info(packet.body)


async def get_connection_rssi(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> int:
    """Read the ring's received connection signal strength in dBm."""
    from ._compatibility import get_device_capabilities
    if timeout_s is not None and (not math.isfinite(timeout_s) or timeout_s <= 0):
        raise ValueError("timeout_s must be finite and positive")
    await get_device_capabilities(client, timeout_s=timeout_s)
    async with client._rssi_lock:
        connection = client._connection_token
        if connection is not None and client._rssi_failed_connection is connection:
            raise TransportError("Reconnect before retrying an ambiguous RSSI query")
        try:
            packet = await client.request(
                SystemCommand.GET_RSSI, SystemCommand.RSSI_RESP, timeout_s=timeout_s,
            )
            if connection is None or connection is not client._connection_token:
                raise TransportError("Connection changed during RSSI query")
            rssi = call(native.parse_connection_rssi, bytes(packet.body))
            return rssi
        except (TimeoutError, ProtocolError, TransportError, asyncio.CancelledError):
            # No transaction ID distinguishes a late reply from a new query.
            client._rssi_failed_connection = connection
            raise


def parse_system_info(body: bytes) -> SystemInfo:
    return SystemInfo(**vars(call(native.parse_system_info, bytes(body))))


async def send_time_response(
    client: OpenZiloClient,
    request_time: int,
    *,
    response_time: int | None = None,
    send_time: int | None = None,
) -> None:
    """Reply to a device time-sync request."""
    now = int(time.time())
    body = (
        BinaryWriter()
        .u32(request_time)
        .u32(now if response_time is None else response_time)
        .u32(now if send_time is None else send_time)
        .build()
    )
    await client.send_command(TimeCommand.RESPONSE, body)


def enable_time_sync(client: OpenZiloClient) -> None:
    """Automatically respond once per request, after its connection is ready."""
    if client._time_sync_enabled:
        return

    def handle_time_request(packet: Packet) -> Awaitable[None]:
        # Automatic replies consume these requests; do not retain queue copies.
        client._drain_queue(int(TimeCommand.REQUEST))
        request_time = call(native.parse_time_request, bytes(packet.body))
        response_time = int(time.time())

        def body() -> bytes:
            return (BinaryWriter().u32(request_time).u32(response_time)
                    .u32(int(time.time())).build())

        return client._send_when_ready(TimeCommand.RESPONSE, body, client._connection_token)

    client.add_packet_handler(TimeCommand.REQUEST, handle_time_request)
    client._time_sync_enabled = True


async def get_log_storage(
    client: OpenZiloClient,
    *,
    timeout_s: float | None = None,
) -> LogStorageInfo:
    packet = await client.request(
        LogCommand.GET_STORAGE,
        LogCommand.STORAGE_RESP,
        timeout_s=timeout_s,
    )
    return LogStorageInfo(**vars(call(native.parse_log_storage, bytes(packet.body))))


async def read_log_chunk(
    client: OpenZiloClient,
    index: int,
    offset: int,
    size: int,
    *,
    timeout_s: float | None = None,
) -> bytes:
    body = BinaryWriter().u32(index).u32(offset).u32(size).build()
    packet = await client.request(
        LogCommand.GET_LOG,
        LogCommand.LOG_RESP,
        body,
        timeout_s=timeout_s,
    )
    return bytes(call(native.parse_log_chunk, bytes(packet.body), size))

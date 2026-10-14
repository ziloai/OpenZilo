# SPDX-License-Identifier: MPL-2.0
"""Connection helpers and device-level operations: system info, logs and time sync."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

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
) -> OpenZiloClient:
    """Create and connect a OpenZiloClient."""
    client = OpenZiloClient(
        address=address,
        device=device,
        scan_timeout_s=scan_timeout_s,
        connect_timeout_s=connect_timeout_s,
        command_timeout_s=command_timeout_s,
    )
    await client.connect()
    if auto_time_sync:
        enable_time_sync(client)
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


def parse_system_info(body: bytes) -> SystemInfo:
    reader = BinaryReader(body)
    ensure_success(read_error(reader))
    firmware_version = reader.string_u16()
    system_time = reader.u32()
    audio_storage_total = reader.u32()
    audio_storage_available = reader.u32()
    battery_percent = reader.u16()
    battery_charging = bool(reader.u8())
    sn = reader.string_u16()
    cpuid = reader.string_u16()
    model = reader.string_u16()
    return SystemInfo(
        firmware_version=firmware_version,
        system_time=system_time,
        audio_storage_total=audio_storage_total,
        audio_storage_available=audio_storage_available,
        battery_percent=battery_percent,
        battery_charging=battery_charging,
        sn=sn,
        cpuid=cpuid,
        model=model,
    )


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
    """Automatically respond to device time-sync requests."""

    def handle_time_request(packet: Packet) -> Awaitable[None]:
        # Automatic replies consume these requests; do not retain queue copies.
        client._drain_queue(int(TimeCommand.REQUEST))
        reader = BinaryReader(packet.body)
        return send_time_response(client, reader.u32())

    client.add_packet_handler(TimeCommand.REQUEST, handle_time_request)


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
    reader = BinaryReader(packet.body)
    ensure_success(read_error(reader))
    return LogStorageInfo(page_size=reader.u32(), total_len=reader.u32())


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
    reader = BinaryReader(packet.body)
    ensure_success(read_error(reader))
    data_len = reader.u32()
    return reader.bytes(min(data_len, reader.remaining))

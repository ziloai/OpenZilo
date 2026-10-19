# SPDX-License-Identifier: MPL-2.0
"""Application firmware update over BLE."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from collections.abc import Awaitable, Callable
from typing import Any

from ._errors import ProtocolError, TimeoutError, TransportError
from ._protocol import (
    _OtaCommand,
    BinaryReader,
    BinaryWriter,
    crc16_compute,
    ensure_success,
    Packet,
)
from ._client import _ota_context, OpenZiloClient
from ._device import get_system_info, SystemInfo
from ._tasks import await_before


def _validate_firmware_package(
    firmware: bytes,
    version: str,
    sha256: str | None,
) -> bytes:
    if not isinstance(firmware, (bytes, bytearray, memoryview)):
        raise TypeError("firmware must contain the update package bytes")
    data = bytes(firmware)
    if not data or len(data) > 0xFFFFFFFF:
        raise ValueError("Firmware package size must be between 1 and 4294967295 bytes")
    version_pattern = r"V[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(?:-(?:debug|prod)-[0-9a-fA-F]{8})?"
    if not re.fullmatch(version_pattern, version) or len(version) > 63:
        raise ValueError(
            "version must be Vx.xxx.xxxx.xxxx with an optional "
            "-debug/prod-8hex suffix, at most 63 bytes"
        )
    if sha256 is not None:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
            raise ValueError("sha256 must contain exactly 64 hexadecimal characters")
        if hashlib.sha256(data).hexdigest() != sha256.lower():
            raise ValueError("Firmware package SHA-256 mismatch")
    return data


async def _ota_timed(operation: Awaitable[Any], timeout: float, phase: str) -> Any:
    deadline = asyncio.get_running_loop().time() + max(0.0, timeout)
    message = f"Firmware update timed out during {phase}; installation is unconfirmed"
    return await await_before(operation, deadline, message)


async def _wait_ota_packet(
    client: OpenZiloClient,
    queue: asyncio.Queue[Packet],
    timeout: float,
) -> Packet:
    # Notifications and the reboot disconnect may arrive in the same event-loop turn.
    # The local queue survives disconnect, unlike the ordinary command queues.
    if not client._protocol_errors.empty():
        raise client._protocol_errors.get_nowait()
    if not queue.empty():
        return queue.get_nowait()
    packet_task = asyncio.create_task(queue.get())
    error_task = asyncio.create_task(client._protocol_errors.get())
    disconnect_task = asyncio.create_task(client._disconnected.wait())
    tasks = {packet_task, error_task, disconnect_task}
    try:
        done, _ = await asyncio.wait(tasks, timeout=max(0.0, timeout),
                                     return_when=asyncio.FIRST_COMPLETED)
        if error_task in done:
            raise error_task.result()
        if packet_task in done:
            return packet_task.result()
        if disconnect_task in done:
            raise TransportError("BLE disconnected before OTA transfer confirmation; installation is unconfirmed")
        raise TimeoutError("Timed out waiting for OTA data request or result; installation is unconfirmed")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _verify_firmware_restart(
    client: OpenZiloClient,
    before: SystemInfo,
    version: str,
    timeout_s: float,
    reboot_timeout_s: float,
) -> SystemInfo:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + reboot_timeout_s
    await _ota_timed(client._disconnected.wait(), reboot_timeout_s, "waiting for device reboot")
    last_error: Exception | None = None
    while loop.time() < deadline:
        remaining = min(timeout_s, deadline - loop.time())
        try:
            await _ota_timed(client.disconnect(), remaining, "connection cleanup")
            await _ota_timed(client.connect(), min(timeout_s, deadline - loop.time()), "reconnection")
            after = await _ota_timed(
                get_system_info(client, timeout_s=timeout_s),
                min(timeout_s, deadline - loop.time()), "version verification",
            )
        except (TransportError, TimeoutError, OSError) as exc:
            last_error = exc
            await asyncio.sleep(min(1.0, max(0.0, deadline - loop.time())))
            continue
        if after.model != before.model or (before.cpuid and after.cpuid != before.cpuid) or (
            before.sn and after.sn != before.sn
        ):
            raise ProtocolError("Reconnected device identity differs; installation is unconfirmed")
        if after.firmware_version != version:
            raise ProtocolError(
                f"Firmware version verification failed: expected {version}, "
                f"device reports {after.firmware_version}"
            )
        return after
    raise TimeoutError("Could not reconnect and verify the new firmware; installation is unconfirmed") from last_error


async def update_firmware(
    client: OpenZiloClient,
    firmware: bytes,
    *,
    version: str,
    sha256: str | None = None,
    expected_model: str | None = None,
    progress: Callable[[int, int], None] | None = None,
    timeout_s: float = 30.0,
    total_timeout_s: float = 600.0,
    reboot_timeout_s: float = 90.0,
) -> SystemInfo:
    """Upload an official APP package, await reboot, and verify its running version.

    Use this connected client exclusively until the call finishes. Stop recording
    and IMU streaming first. Package bytes are transmitted unchanged. The caller
    must select a release compatible with the device and its starting version.
    ``progress(sent, total)`` reports transfer progress, not installation success.
    The return value is system information read after reboot. A timeout or
    disconnect before confirmation never implies a successful installation.
    """
    data = _validate_firmware_package(firmware, version, sha256)
    for name, value in (("timeout_s", timeout_s), ("total_timeout_s", total_timeout_s),
                        ("reboot_timeout_s", reboot_timeout_s)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and greater than zero")
    if client._firmware_update_active:
        raise ProtocolError("A firmware update is already running on this client")
    if client._recording_active:
        raise ProtocolError("Confirm recording completion with get_audio_recording_status before OTA")
    if client._live_audio_subscribed:
        raise ProtocolError("Disable live audio subscription before updating firmware")
    if (client._audio_owner is not None or client._write_lock.locked()
            or any(lock.locked() for lock in client._request_locks.values())):
        raise ProtocolError("Finish active audio operations and requests before updating firmware")
    if not client.is_connected:
        raise TransportError("Connect the client before updating firmware")

    commands = (_OtaCommand.NOTIFY_RESP, _OtaCommand.GET_PACKET, _OtaCommand.UPDATE_RESULT)
    if any(int(command) in client._callback_only for command in commands):
        raise ProtocolError("Remove callback-only OTA handlers before updating firmware")
    queue: asyncio.Queue[Packet] = asyncio.Queue(maxsize=16)
    queue_error: ProtocolError | None = None

    def on_packet(packet: Packet) -> None:
        nonlocal queue_error
        # This session owns OTA responses, so do not accumulate duplicate copies.
        client._drain_queue(int(packet.command))
        if queue.full():
            queue_error = ProtocolError("OTA response queue overflow")
        else:
            queue.put_nowait(packet)

    had_capabilities = client.capabilities is not None
    client._firmware_update_active = True
    client._firmware_update_owner = object()
    ota_token = _ota_context.set(client._firmware_update_owner)
    for command in commands:
        client._drain_queue(int(command))
        client.add_packet_handler(command, on_packet)
    client._drain_protocol_errors()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + total_timeout_s

    def remaining() -> float:
        budget = deadline - loop.time()
        if budget <= 0:
            raise TimeoutError("Firmware transfer exceeded total_timeout_s; installation is unconfirmed")
        return min(timeout_s, budget)

    try:
        budget = remaining()
        before = await _ota_timed(get_system_info(client, timeout_s=timeout_s), budget, "device check")
        if expected_model is not None and before.model != expected_model:
            raise ProtocolError("Device model does not match expected_model")
        if before.firmware_version == version:
            raise ProtocolError("Device already reports the target version; no update was started")
        notify = (BinaryWriter().u32(2).string_u32(version).u32(len(data))
                  .u16(crc16_compute(data)).build())
        while not queue.empty():
            queue.get_nowait()
        budget = remaining()
        await _ota_timed(client.send_command(_OtaCommand.NOTIFY, notify), budget, "update request")
        sent_end: int | None = None
        if progress is not None:
            progress(0, len(data))
        while True:
            if queue_error is not None:
                raise queue_error
            packet = await _wait_ota_packet(client, queue, remaining())
            if queue_error is not None:
                raise queue_error
            reader = BinaryReader(packet.body)
            if packet.command in (_OtaCommand.NOTIFY_RESP, _OtaCommand.UPDATE_RESULT):
                if len(packet.body) != 2:
                    raise ProtocolError("Invalid OTA status response length")
                ensure_success(reader.u16())
                if packet.command == _OtaCommand.UPDATE_RESULT:
                    if sent_end != len(data):
                        raise ProtocolError("OTA success arrived before the package was transferred")
                    break
                continue
            if len(packet.body) != 12:
                raise ProtocolError("Invalid OTA data request length")
            ensure_success(reader.u16())
            upgrade_type, offset, window = reader.u16(), reader.u32(), reader.u32()
            # Subsequent requests use type 0; type 2 denotes the user application.
            if upgrade_type not in (0, 2):
                raise ProtocolError("Unexpected OTA upgrade type")
            if not 1 <= window <= 4096 or offset >= len(data):
                raise ProtocolError("Invalid OTA offset or window size")
            if sent_end is not None and offset > sent_end:
                raise ProtocolError("OTA request skipped bytes that were never sent")
            # A nonzero first offset is the device's continuation point. Repeated
            # requests are answered from the same immutable package bytes.
            end = min(offset + window, len(data))
            body = BinaryWriter().u16(0).u32(offset).u32(end - offset).bytes(data[offset:end]).build()
            budget = remaining()
            await _ota_timed(client.send_command(_OtaCommand.PACKET_RESP, body), budget, "data transfer")
            previous = sent_end or 0
            sent_end = max(previous, end)
            if progress is not None and sent_end > previous:
                progress(sent_end, len(data))
        info = await _verify_firmware_restart(client, before, version, timeout_s, reboot_timeout_s)
        if had_capabilities:
            from ._compatibility import get_device_capabilities
            await get_device_capabilities(client, timeout_s=min(timeout_s, 3.0))
        return info
    finally:
        for command in commands:
            client.remove_packet_handler(command, on_packet)
            client._drain_queue(int(command))
        client._firmware_update_active = False
        client._firmware_update_owner = None
        _ota_context.reset(ota_token)

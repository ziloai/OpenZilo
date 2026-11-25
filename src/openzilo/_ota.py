# SPDX-License-Identifier: MPL-2.0
"""Application firmware update over BLE."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from typing import Any

from ._core import native, call
from ._firmware_bundle import _pem, inspect_firmware_bundle
from ._errors import ProtocolError, TimeoutError, TransportError
from ._protocol import _OtaCommand, Packet
from ._client import _ota_context, OpenZiloClient
from ._device import get_system_info, SystemInfo
from ._tasks import await_before


def _native_info(info: SystemInfo) -> native.DeviceInfo:
    return native.DeviceInfo(
        firmware_version=info.firmware_version, system_time=info.system_time,
        audio_storage_total=info.audio_storage_total,
        audio_storage_available=info.audio_storage_available, battery_percent=info.battery_percent,
        battery_charging=info.battery_charging, sn=info.sn, cpuid=info.cpuid, model=info.model)


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
    transfer: Any,
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
        call(transfer.verify_running, _native_info(after))
        return after
    raise TimeoutError("Could not reconnect and verify the new firmware; installation is unconfirmed") from last_error


async def update_firmware(
    client: OpenZiloClient,
    firmware: bytes,
    *,
    trusted_public_key: bytes,
    allow_test_firmware: bool = False,
    progress: Callable[[int, int], None] | None = None,
    timeout_s: float = 30.0,
    total_timeout_s: float = 600.0,
    reboot_timeout_s: float = 90.0,
) -> SystemInfo:
    """Upload an official APP package, await reboot, and verify its running version.

    Use this connected client exclusively until the call finishes. Stop recording
    and IMU streaming first. Signed ZIPs require an independently trusted PEM
    public key; only the verified payload is transmitted. Raw BIN inputs are
    rejected. Version and compatibility come only from signed metadata.
    ``progress(sent, total)`` reports transfer progress, not installation success.
    The return value is system information read after reboot. A timeout or
    disconnect before confirmation never implies a successful installation.
    """
    bundle = inspect_firmware_bundle(firmware, trusted_public_key=trusted_public_key)
    if bundle.profile == "test" and not allow_test_firmware:
        raise ValueError("Test firmware requires allow_test_firmware=True")
    version, data = bundle.version, bundle.payload
    transfer = None
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
        from ._compatibility import get_device_capabilities
        capabilities = await _ota_timed(
            get_device_capabilities(client, timeout_s=timeout_s), remaining(), "board check")
        # The core owns model, board, source-version, test-profile and target checks, framing,
        # offsets, windows and result ordering.
        transfer = call(native.OtaTransfer, bytes(firmware), _pem(trusted_public_key),
                        _native_info(before), capabilities.board_target or "", allow_test_firmware)
        notify = call(native.decode_packet, call(transfer.begin))
        while not queue.empty():
            queue.get_nowait()
        budget = remaining()
        await _ota_timed(client.send_command(notify.command, notify.body), budget, "update request")
        sent_end = 0
        if progress is not None:
            progress(0, len(data))
        while True:
            if queue_error is not None:
                raise queue_error
            packet = await _wait_ota_packet(client, queue, remaining())
            if queue_error is not None:
                raise queue_error
            step = call(transfer.handle, native.Packet(
                command=packet.command, body=bytes(packet.body), version=packet.version,
                body_crc=packet.body_crc))
            if step.frame is not None:
                outgoing = call(native.decode_packet, step.frame)
                await _ota_timed(client.send_command(outgoing.command, outgoing.body), remaining(),
                                 "data transfer")
            if progress is not None and step.sent > sent_end:
                progress(step.sent, step.total)
            sent_end = max(sent_end, step.sent)
            if step.transfer_complete:
                break
        info = await _verify_firmware_restart(client, transfer, timeout_s, reboot_timeout_s)
        if had_capabilities:
            from ._compatibility import get_device_capabilities
            await get_device_capabilities(client, timeout_s=min(timeout_s, 3.0))
        return info
    finally:
        if transfer is not None and transfer.phase() != native.OtaPhase.VERIFIED:
            transfer.cancel()
        for command in commands:
            client.remove_packet_handler(command, on_packet)
            client._drain_queue(int(command))
        client._firmware_update_active = False
        client._firmware_update_owner = None
        _ota_context.reset(ota_token)

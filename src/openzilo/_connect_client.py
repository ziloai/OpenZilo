# SPDX-License-Identifier: MPL-2.0
"""Async Python ConnectClient mirroring OpenZilo Connect's Android ConnectClient."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
import json
from pathlib import Path
from typing import Any
import uuid

from ._connect_protocol import (
    API_VERSION,
    DEFAULT_HOST,
    DEFAULT_PORT,
    EVENT_QUEUE_SIZE,
    MAX_ACTIVE_OPS_PER_CLIENT,
    ConnectEvent,
    ConnectStatus,
    ImuConfigInfo,
    RingAxisPresetKind,
    decode_bytes,
)

_MAX_LINE_BYTES = 1024 * 1024


class ConnectClient:
    """Async client for ``openzilo host`` (Connect API v2).

    Mirrors Android's ``com.openzilo.connect.api.ConnectClient`` without requiring
    Bluetooth or direct BLE transport ownership in the client process.
    """

    API_VERSION = API_VERSION

    def __init__(
        self,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        socket_path: str | Path | None = None,
        token: str | None = None,
        client_name: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._socket_path = Path(socket_path).expanduser() if socket_path is not None else None
        self._token = token
        self._client_name = client_name
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[Any] | None = None
        self._write_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._event_queue: asyncio.Queue[ConnectEvent | BaseException | None] = asyncio.Queue(
            maxsize=EVENT_QUEUE_SIZE
        )
        self._closed = False
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and not self._closed

    async def connect(self, timeout_s: float = 2.0) -> "ConnectClient":
        if self._closed:
            raise RuntimeError("Client is closed")
        if self._connected:
            return self
        async with asyncio.timeout(timeout_s):
            if self._socket_path is not None:
                reader, writer = await asyncio.open_unix_connection(
                    str(self._socket_path), limit=_MAX_LINE_BYTES
                )
            else:
                reader, writer = await asyncio.open_connection(
                    self._host, self._port, limit=_MAX_LINE_BYTES
                )
        self._reader = reader
        self._writer = writer
        self._connected = True
        self._reader_task = asyncio.create_task(self._read_loop())
        return self

    async def __aenter__(self) -> "ConnectClient":
        return await self.connect()

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    @property
    def events(self) -> AsyncIterator[ConnectEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[ConnectEvent]:
        while True:
            item = await self._event_queue.get()
            if item is None:
                return
            if isinstance(item, BaseException):
                raise item
            yield item

    def _ensure_connected(self) -> None:
        if self._closed:
            raise RuntimeError("Client is closed")
        if not self._connected or self._writer is None:
            raise RuntimeError("Call connect() before using ConnectClient")

    async def _send_raw(self, payload: dict[str, Any]) -> None:
        self._ensure_connected()
        assert self._writer is not None
        line = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        async with self._write_lock:
            self._writer.write(line)
            await self._writer.drain()

    async def _rpc(
        self,
        method: str,
        fields: dict[str, Any] | None = None,
        *,
        timeout_s: float = 30.0,
        request_id: str | None = None,
        cancel_on_timeout: bool = False,
    ) -> dict[str, Any]:
        if not (0 < timeout_s <= 600.0):
            raise ValueError("timeout_s must be in (0, 600]")
        self._ensure_connected()
        req_id = request_id or uuid.uuid4().hex
        if len(self._pending) >= MAX_ACTIVE_OPS_PER_CLIENT and method == "execute":
            raise RuntimeError("Too many requests")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[req_id] = future
        delivered = False
        try:
            body: dict[str, Any] = {"id": req_id, "method": method}
            if fields:
                body.update(fields)
            async with asyncio.timeout(timeout_s):
                await self._send_raw(body)
                result = await future
                delivered = True
                return result
        finally:
            self._pending.pop(req_id, None)
            if not future.done():
                future.cancel()
            if cancel_on_timeout and not delivered and self.is_connected:
                try:
                    await self._send_raw({
                        "id": uuid.uuid4().hex,
                        "method": "cancel",
                        "targetRequestId": req_id,
                    })
                except Exception:
                    pass

    async def request_authorization(
        self,
        scopes: Iterable[str],
        *,
        token: str | None = None,
        client_name: str | None = None,
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {"scopes": list(scopes)}
        effective_token = token if token is not None else self._token
        if effective_token is not None:
            fields["token"] = effective_token
        effective_name = client_name if client_name is not None else self._client_name
        if effective_name is not None:
            fields["clientName"] = effective_name
        reply = await self._rpc("requestAuthorization", fields)
        if not reply.get("ok"):
            raise RuntimeError(reply.get("detail") or reply.get("error") or "requestAuthorization failed")
        return reply

    async def status(self) -> dict[str, Any]:
        reply = await self._rpc("getStatus")
        if not reply.get("ok"):
            raise RuntimeError(reply.get("detail") or reply.get("error") or "getStatus failed")
        return reply

    async def ring_status(self) -> ConnectStatus:
        return ConnectStatus.from_payload(await self.status())

    async def execute(
        self,
        operation: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout_s: float = 30.0,
    ) -> dict[str, Any]:
        req_id = uuid.uuid4().hex
        return await self._rpc(
            "execute",
            {"requestId": req_id, "operation": operation, "arguments": arguments or {}},
            timeout_s=timeout_s,
            request_id=req_id,
            cancel_on_timeout=True,
        )

    async def cancel(self, request_id: str) -> None:
        reply = await self._rpc("cancel", {"targetRequestId": request_id})
        if not reply.get("ok"):
            raise RuntimeError(reply.get("detail") or reply.get("error") or "cancel failed")

    async def subscribe(self, topics: Iterable[str]) -> None:
        reply = await self._rpc("subscribe", {"topics": list(topics)})
        if not reply.get("ok"):
            raise RuntimeError(reply.get("detail") or reply.get("error") or "subscribe failed")

    async def unsubscribe(self) -> None:
        reply = await self._rpc("unsubscribe")
        if not reply.get("ok"):
            raise RuntimeError(reply.get("detail") or reply.get("error") or "unsubscribe failed")

    async def start_imu(self) -> ImuConfigInfo:
        reply = await self.execute("imu.start")
        if not reply.get("ok"):
            raise RuntimeError(reply.get("detail") or reply.get("error") or "imu.start failed")
        if "sampleRateHz" in reply:
            return ImuConfigInfo(
                sample_rate_hz=int(reply["sampleRateHz"]),
                accel_range_g=int(reply["accelRangeG"]),
                gyro_range_dps=int(reply["gyroRangeDps"]),
            )
        body = decode_bytes(reply["body"])
        if len(body) != 8:
            raise ValueError("Invalid 0x0602 response size")
        if int.from_bytes(body[0:2], "big") != 0:
            raise RuntimeError("Device rejected IMU start")
        return ImuConfigInfo(
            sample_rate_hz=int.from_bytes(body[2:4], "big"),
            accel_range_g=int.from_bytes(body[4:6], "big"),
            gyro_range_dps=int.from_bytes(body[6:8], "big"),
        )

    async def stop_imu(self) -> None:
        reply = await self.execute("imu.stop")
        if not reply.get("ok"):
            raise RuntimeError(reply.get("detail") or reply.get("error") or "imu.stop failed")

    async def zero_attitude_heading(self) -> None:
        reply = await self.execute("imu.attitude.zero")
        if not reply.get("ok"):
            raise RuntimeError(reply.get("detail") or reply.get("error") or "imu.attitude.zero failed")

    async def configure_attitude_axes(
        self, preset: RingAxisPresetKind, invert_radial_z: bool
    ) -> None:
        reply = await self.execute(
            "imu.attitude.mapping",
            {"preset": preset.value, "invertRadialZ": bool(invert_radial_z)},
        )
        if not reply.get("ok"):
            raise RuntimeError(reply.get("detail") or reply.get("error") or "imu.attitude.mapping failed")

    async def calibrate_gyro_bias(
        self, duration_ms: int = 3_000, *, align_flat: bool = True
    ) -> dict[str, Any]:
        reply = await self.execute(
            "imu.calibrate.gyro",
            {"durationMs": int(duration_ms), "alignFlat": bool(align_flat)},
            timeout_s=(duration_ms + 15_000) / 1000.0,
        )
        if not reply.get("ok"):
            raise RuntimeError(reply.get("detail") or reply.get("error") or "imu.calibrate.gyro failed")
        return reply

    async def calibrate_upright_reference(self) -> dict[str, Any]:
        reply = await self.execute("imu.calibrate.upright")
        if not reply.get("ok"):
            raise RuntimeError(reply.get("detail") or reply.get("error") or "imu.calibrate.upright failed")
        return reply

    async def reset_imu_calibration(self) -> dict[str, Any]:
        reply = await self.execute("imu.calibration.reset")
        if not reply.get("ok"):
            raise RuntimeError(reply.get("detail") or reply.get("error") or "imu.calibration.reset failed")
        return reply

    async def _read_loop(self) -> None:
        assert self._reader is not None
        error: BaseException | None = None
        try:
            while not self._closed:
                raw_line = await self._reader.readline()
                if not raw_line:
                    error = RuntimeError("Connect host disconnected")
                    break
                message = json.loads(raw_line.decode("utf-8"))
                msg_type = message.get("type")
                if msg_type == "result":
                    req_id = message.get("requestId")
                    future = self._pending.pop(req_id, None)
                    if future is not None and not future.done():
                        future.set_result(message.get("result") or {})
                elif msg_type == "event":
                    event = ConnectEvent(
                        topic=str(message.get("topic") or ""),
                        data=message.get("data") or {},
                    )
                    try:
                        self._event_queue.put_nowait(event)
                    except asyncio.QueueFull:
                        error = RuntimeError("Connect event consumer is too slow")
                        break
        except asyncio.CancelledError:
            return
        except Exception as exc:
            error = exc
        finally:
            self._fail_connection(error)

    def _fail_connection(self, error: BaseException | None) -> None:
        self._connected = False
        failure = error or RuntimeError("Client is closed")
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(failure)
        self._pending.clear()
        try:
            self._event_queue.put_nowait(error if error is not None else None)
        except asyncio.QueueFull:
            pass

    async def close(self) -> None:
        if self._closed:
            return
        if self._connected and self._writer is not None:
            try:
                await self._send_raw({"id": uuid.uuid4().hex, "method": "closeClient"})
            except Exception:
                pass
        self._closed = True
        self._connected = False
        if self._reader_task is not None:
            self._reader_task.cancel()
            await asyncio.gather(self._reader_task, return_exceptions=True)
            self._reader_task = None
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._reader = None
        self._fail_connection(None)

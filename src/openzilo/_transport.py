# SPDX-License-Identifier: MPL-2.0
"""BLE Nordic UART Service transport built on bleak."""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import re
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import InitVar, dataclass
from typing import Any

from ._errors import TransportError
from ._tasks import start_background_task


NUS_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
NUS_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
NUS_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
DEFAULT_SCAN_TIMEOUT_S = 30.0
DEFAULT_CONNECTION_STABILIZATION_S = 3.0
_logger = logging.getLogger(__name__)
_scan_sessions: weakref.WeakKeyDictionary[Any, object] = weakref.WeakKeyDictionary()


def _positive_timeout(value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Timeout must be a finite positive number")


def _compatible_name(name: str | None) -> bool:
    name = (name or "").strip().casefold()
    return name in {"ring", "open zilo"} or bool(re.search(r"open zilo-\S+", name))
_NUS_WRITE_CHUNK_SIZE = 20


@dataclass(frozen=True)
class BleDeviceInfo:
    name: str | None
    address: str
    rssi: int | None = None
    service_uuids: tuple[str, ...] = ()
    matched_service: bool = False
    matched_name: bool = False
    # InitVar keeps native backend objects out of repr, equality and asdict().
    _native_device: InitVar[Any] = None

    def __post_init__(self, _native_device: Any) -> None:
        object.__setattr__(self, "_native_device", _native_device)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        object.__setattr__(self, "_native_loop", loop)


RxCallback = Callable[[bytes], None | Awaitable[None]]
DisconnectCallback = Callable[[], None | Awaitable[None]]


def _normalize_ble_address(address: str | None) -> str:
    return "".join(ch for ch in str(address or "") if ch.isalnum()).lower()


def _address_matches(candidate: object, expected: str | None) -> bool:
    expected_norm = _normalize_ble_address(expected)
    if not expected_norm:
        return True
    return _normalize_ble_address(str(candidate or "")) == expected_norm


class NusClient:
    """Cross-platform BLE/NUS client using bleak."""

    def __init__(
        self,
        *,
        address: str | None = None,
        device: BleDeviceInfo | None = None,
        connect_timeout_s: float = 30.0,
        service_uuid: str = NUS_SERVICE_UUID,
        tx_uuid: str = NUS_TX_UUID,
        rx_uuid: str = NUS_RX_UUID,
        scan_timeout_s: float = DEFAULT_SCAN_TIMEOUT_S,
        write_with_response: bool = False,
    ) -> None:
        if device is not None and address is not None and not _address_matches(device.address, address):
            raise ValueError("address and device must identify the same device")
        _positive_timeout(scan_timeout_s)
        _positive_timeout(connect_timeout_s)
        self.address = address if address is not None else (device.address if device else None)
        self.device = device
        self.connect_timeout_s = connect_timeout_s
        self._ready = False
        self._connecting = False
        self.service_uuid = service_uuid
        self.tx_uuid = tx_uuid
        self.rx_uuid = rx_uuid
        self.scan_timeout_s = scan_timeout_s
        self.write_with_response = write_with_response
        self._client: Any | None = None
        self._rx_callback: RxCallback | None = None
        self._disconnect_callback: DisconnectCallback | None = None
        self._notify_started = False
        self._callback_tasks: set[asyncio.Task[Any]] = set()

    @staticmethod
    async def discover(
        *,
        address: str | None = None,
        timeout_s: float = DEFAULT_SCAN_TIMEOUT_S,
        on_devices_changed: Callable[[list[BleDeviceInfo]], None] | None = None,
        _scan_stats: dict[str, Any] | None = None,
    ) -> list[BleDeviceInfo]:
        """Report ring candidates immediately; an explicit address bypasses candidate filtering.

        Cancellation propagates after cleanup and a final callback snapshot.
        Only one SDK scan may run in an event loop at a time.
        """
        _positive_timeout(timeout_s)
        if address is not None and not _normalize_ble_address(address):
            raise ValueError("address must be a nonempty device identifier")
        try:
            from bleak import BleakScanner
        except ImportError as exc:
            raise TransportError("Install bleak to use BLE transport") from exc
        loop = asyncio.get_running_loop()
        if loop in _scan_sessions:
            raise TransportError("SCANNING: another SDK scan is active; cancel and await it first")
        session = object()
        _scan_sessions[loop] = session
        active = True
        found = asyncio.Event()
        results: dict[str, BleDeviceInfo] = {}
        counts = dict(broadcasts=0, service=0, name=0, filtered=0)
        started = loop.time()
        first_found: float | None = None
        last_report = -float("inf")
        timer: asyncio.TimerHandle | None = None

        def snapshot() -> list[BleDeviceInfo]:
            return sorted(results.values(), key=lambda d: (
                not d.matched_service, -(d.rssi if d.rssi is not None else -1000), d.address,
            ))

        def report() -> None:
            nonlocal last_report, timer
            if timer is not None:
                timer.cancel()
                timer = None
            last_report = loop.time()
            if on_devices_changed is not None:
                try:
                    on_devices_changed(snapshot())
                except Exception:
                    _logger.exception("Scan result callback failed")

        def detected(dev: Any, adv: Any) -> None:
            nonlocal first_found, timer
            if not active or _scan_sessions.get(loop) is not session:
                return
            counts["broadcasts"] += 1
            device_address = str(dev.address)
            key = _normalize_ble_address(device_address)
            previous = results.get(key)
            name = (getattr(adv, "local_name", None)
                    or (previous.name if previous else None) or getattr(dev, "name", None))
            uuids = tuple(sorted(set(
                (previous.service_uuids if previous else ())
                + tuple(str(u).lower() for u in getattr(adv, "service_uuids", ()))
                + tuple(str(u).lower() for u in getattr(adv, "service_data", {}))
            )))
            service_match = NUS_SERVICE_UUID.lower() in uuids
            name_match = _compatible_name(name) or bool(previous and previous.matched_name)
            counts["service"] += int(service_match)
            counts["name"] += int(name_match)
            accepted = (_address_matches(device_address, address) if address is not None
                        else service_match or name_match)
            if not accepted:
                counts["filtered"] += 1
                return
            if first_found is None:
                first_found = loop.time() - started
            info = BleDeviceInfo(name, device_address, getattr(adv, "rssi", None),
                                 uuids, service_match, name_match, dev)
            results[key] = info
            if previous is None:
                report()
            elif info != previous:
                remaining = 0.2 - (loop.time() - last_report)
                if remaining <= 0:
                    report()
                elif timer is None:
                    timer = loop.call_later(remaining, report)
            if address is not None:
                found.set()

        scanner = None
        entered = False
        _logger.info("SCANNING")
        try:
            scanner = BleakScanner(detection_callback=detected, scanning_mode="active")
            async with scanner:
                entered = True
                try:
                    await asyncio.wait_for(found.wait(), timeout_s)
                except asyncio.TimeoutError:
                    pass
        except Exception as exc:
            raise TransportError(f"SCANNING failed: {exc}; stats={counts}") from exc
        finally:
            active = False
            if timer is not None:
                timer.cancel()
            try:
                # __aexit__ handles normal exits, failures and cancellation after start.
                if scanner is not None and not entered:
                    try:
                        await asyncio.wait_for(scanner.stop(), 2.0)
                    except Exception:
                        _logger.exception("Scanner cleanup after start failure failed")
            finally:
                report()
                _scan_sessions.pop(loop, None)
                if _scan_stats is not None:
                    _scan_stats.update(counts, first_found_s=first_found)
                _logger.info("Scan stats=%s first_found_s=%s", counts, first_found)
        if address is not None and not results:
            _logger.warning("SCANNING timeout: target not found; stats=%s", counts)
        return snapshot()

    def set_rx_callback(self, callback: RxCallback | None) -> None:
        self._rx_callback = callback

    def _set_disconnect_callback(self, callback: DisconnectCallback | None) -> None:
        self._disconnect_callback = callback

    @property
    def is_connected(self) -> bool:
        return bool(self._client and self._client.is_connected)

    async def connect(self) -> None:
        if self._connecting or self._client is not None:
            raise TransportError("A connection is already active; disconnect first")
        if not _normalize_ble_address(self.address):
            raise TransportError("A device address/identifier or scanned device is required")
        if asyncio.get_running_loop() in _scan_sessions:
            raise TransportError("SCANNING: cancel and await the active scan before connecting")
        self._connecting = True
        stage = "SCANNING"
        client = None
        try:
            from bleak import BleakClient
            selected = self.device
            # Native objects are only reused for this immediate connection in their loop.
            self.device = None
            if (selected is None or selected._native_device is None
                    or selected._native_loop is not asyncio.get_running_loop()):
                stats: dict[str, Any] = {}
                devices = await self.discover(address=self.address, timeout_s=self.scan_timeout_s,
                                              _scan_stats=stats)
                if not devices:
                    raise TransportError(f"SCANNING timeout: target address not found; stats={stats}")
                selected = devices[0]
            stage = "CONNECTING"
            _logger.info(stage)
            client = BleakClient(selected._native_device,
                                 disconnected_callback=self._handle_disconnect,
                                 timeout=self.connect_timeout_s)
            self._client = client
            await asyncio.wait_for(client.connect(), self.connect_timeout_s)
            service = client.services.get_service(self.service_uuid)
            if service is None:
                raise TransportError("NUS service is missing")
            rx = service.get_characteristic(self.rx_uuid)
            tx = service.get_characteristic(self.tx_uuid)
            write_property = "write" if self.write_with_response else "write-without-response"
            if rx is None or write_property not in rx.properties:
                raise TransportError(f"NUS RX must support {write_property}")
            if tx is None or "notify" not in tx.properties:
                raise TransportError("NUS TX must support notify")
            stage = "SUBSCRIBING"
            _logger.info(stage)
            def notified(sender: Any, data: bytearray) -> None:
                if self._client is client:
                    self._handle_notify(sender, data)

            await asyncio.wait_for(client.start_notify(self.tx_uuid, notified),
                                   self.connect_timeout_s)
            self._notify_started = True
            stage = "STABILIZING"
            _logger.info(stage)
            await asyncio.sleep(DEFAULT_CONNECTION_STABILIZATION_S)
            if not client.is_connected:
                raise TransportError("Link disconnected during stabilization")
            self._ready = True
            _logger.info("READY")
        except BaseException as exc:
            self._ready = False
            try:
                if client is not None:
                    await asyncio.wait_for(self.disconnect(), 2.0)
            except Exception:
                _logger.exception("BLE cleanup failed")
            finally:
                self._client = None
                self._notify_started = False
            if not isinstance(exc, Exception):
                raise
            raise TransportError(f"{stage} failed: {exc}") from exc
        finally:
            self._connecting = False

    async def disconnect(self) -> None:
        self._ready = False
        if self._client is None:
            return
        try:
            if self._notify_started and self._client.is_connected:
                await self._client.stop_notify(self.tx_uuid)
        finally:
            self._notify_started = False
            if self._client.is_connected:
                await self._client.disconnect()
            self._client = None

    async def write(self, data: bytes | bytearray | memoryview) -> None:
        if not self._ready or self._client is None or not self._client.is_connected:
            raise TransportError("BLE client is not ready")

        payload = bytes(data)
        for offset in range(0, len(payload), _NUS_WRITE_CHUNK_SIZE):
            chunk = payload[offset : offset + _NUS_WRITE_CHUNK_SIZE]
            await self._client.write_gatt_char(
                self.rx_uuid,
                chunk,
                response=self.write_with_response,
            )
            await asyncio.sleep(0)

    async def __aenter__(self) -> "NusClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.disconnect()

    def _handle_notify(self, _sender: Any, data: bytearray) -> None:
        callback = self._rx_callback
        if callback is None:
            return

        result = callback(bytes(data))
        if inspect.isawaitable(result):
            start_background_task(self._callback_tasks, result, "BLE receive callback")

    def _handle_disconnect(self, _client: Any) -> None:
        if _client is not self._client:
            return
        self._ready = False
        self._notify_started = False
        callback = self._disconnect_callback
        if callback is None:
            return

        result = callback()
        if inspect.isawaitable(result):
            start_background_task(self._callback_tasks, result, "BLE disconnect callback")

# SPDX-License-Identifier: MPL-2.0
"""OpenZilo Connect API v2 local host broker (NDJSON over TCP / Unix socket / stdio)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
import hmac
import json
import logging
import os
from pathlib import Path
import stat
from typing import Any
import uuid

from ._client import OpenZiloClient
from ._compatibility import DeviceCapabilities, _native_features, get_device_capabilities
from ._connect_calibration import ConnectCalibrationStore
from ._connect_protocol import (
    API_VERSION,
    DEFAULT_HOST,
    DEFAULT_PORT,
    EVENT_QUEUE_SIZE,
    MAX_ACTIVE_OPS_PER_CLIENT,
    MAX_ACTIVE_OPS_TOTAL,
    MAX_ARGUMENTS_BYTES,
    MAX_FIRMWARE_BYTES,
    MAX_PACKET_BODY_BYTES,
    MAX_SUBSCRIPTIONS_TOTAL,
    SCOPES,
    command_topic,
    decode_bytes,
    encode_bytes,
    operation_scope,
    require_scopes,
    topic_scope,
)
from ._core import native, native_packet
from ._device import SystemInfo, enable_time_sync, get_system_info
from ._errors import DeviceError, OpenZiloError
from ._ota import update_firmware
from ._protocol import Packet

_logger = logging.getLogger(__name__)

_EVENT_COMMANDS: tuple[int, ...] = (
    0x0605,
    0x0701, 0x0702, 0x0703, 0x0704,
    0x050F, 0x0510, 0x0511,
    0x050A,
    0x0504, 0x0505, 0x0508,
    0x0401,
)
_MAX_LINE_BYTES = 1024 * 1024


class _PermissionDenied(Exception):
    pass


class _DeviceRejected(Exception):
    def __init__(self, code: int, command: int, body: bytes, detail: str | None = None) -> None:
        super().__init__(detail or f"Device rejected operation ({code})")
        self.code = code
        self.command = command
        self.body = body


@dataclass(frozen=True)
class _RingSnapshot:
    phase: str = "disconnected"
    device_name: str = ""
    address: str = ""
    info: native.DeviceInfo | None = None
    capabilities: DeviceCapabilities | None = None
    message: str | None = None
    firmware_progress: int | None = None


@dataclass
class _ControlOwner:
    client_id: str
    permission: str
    request_id: str
    epoch: int
    file_index: int | None = None


@dataclass
class _ActiveImuState:
    epoch: int
    response_body: bytes
    config: native.ImuConfig


@dataclass
class _ImuLease:
    client_id: str
    epoch: int


@dataclass
class _ClientSession:
    client_id: str
    writer: asyncio.StreamWriter
    client_name: str
    granted_scopes: set[str]
    subscribed_topics: set[str]
    event_queue: asyncio.Queue[tuple[str, dict[str, Any]]]
    write_lock: asyncio.Lock
    active_ops: dict[str, asyncio.Task[Any]]
    op_permissions: dict[str, str]
    closed: bool = False
    event_task: asyncio.Task[Any] | None = None


def _to_native_info(info: SystemInfo | native.DeviceInfo) -> native.DeviceInfo:
    if isinstance(info, native.DeviceInfo):
        return info
    return native.DeviceInfo(
        firmware_version=info.firmware_version,
        system_time=info.system_time,
        audio_storage_total=info.audio_storage_total,
        audio_storage_available=info.audio_storage_available,
        battery_percent=info.battery_percent,
        battery_charging=info.battery_charging,
        sn=info.sn,
        cpuid=info.cpuid,
        model=info.model,
    )


def _ring_identity(info: native.DeviceInfo, address: str) -> str:
    if info.cpuid.strip():
        return f"cpu:{info.cpuid}"
    if info.sn.strip():
        return f"serial:{info.sn}"
    return f"address:{address}"


def _require_uint(args: dict[str, Any], key: str, maximum: int = 0xFFFF_FFFF) -> int:
    if key not in args:
        raise ValueError(f"Missing {key}")
    raw = args[key]
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{key} must be an integer")
    if not (0 <= raw <= maximum):
        raise ValueError(f"{key} is outside its supported range")
    return raw


def _require_bool(args: dict[str, Any], key: str) -> bool:
    if key not in args:
        raise ValueError(f"Missing {key}")
    raw = args[key]
    if not isinstance(raw, bool):
        raise ValueError(f"{key} must be a boolean")
    return raw


def _live_event_to_payload(event: native.LiveEvent) -> dict[str, Any]:
    if event.is_start():
        val = event.value
        return {
            "type": "started",
            "sessionId": int(val.session_id),
            "recordTime": int(val.record_time),
            "sampleRate": int(val.sample_rate),
            "channels": int(val.channels),
            "codec": "opus",
        }
    if event.is_data():
        val = event.value
        return {
            "type": "frame",
            "sessionId": int(val.session_id),
            "sequence": int(val.sequence),
            "data": encode_bytes(bytes(val.data)),
        }
    if event.is_end():
        val = event.value
        return {
            "type": "ended",
            "sessionId": int(val.session_id),
            "byteCount": int(val.sent_bytes),
        }
    return {"type": "interrupted"}


class ConnectHost:
    """Connect API v2 host broker owning one BLE connection and serving local clients."""

    def __init__(
        self,
        *,
        address: str | None = None,
        scan_timeout_s: float = 10.0,
        connect_timeout_s: float = 30.0,
        allow_unverified_features: bool = False,
        allowed_scopes: set[str] | None = None,
        require_authorization: bool = False,
        token: str | None = None,
        firmware_public_key: bytes | None = None,
        auto_reconnect: bool = True,
        calibration_store: ConnectCalibrationStore | None = None,
        client_factory: Callable[..., OpenZiloClient] | None = None,
    ) -> None:
        self.address = address
        self.scan_timeout_s = scan_timeout_s
        self.connect_timeout_s = connect_timeout_s
        self.allow_unverified_features = allow_unverified_features
        self.allowed_scopes: set[str] = (
            require_scopes(set(allowed_scopes)) if allowed_scopes is not None else set(SCOPES)
        )
        self.require_authorization = require_authorization or (token is not None)
        self._token = token
        self._firmware_public_key = firmware_public_key
        self.auto_reconnect = auto_reconnect
        self.calibrations = calibration_store or ConnectCalibrationStore()
        self._client_factory = client_factory or OpenZiloClient

        self._snapshot = _RingSnapshot()
        self._epoch = 0
        self._expected_identity: str | None = None
        self._ring: OpenZiloClient | None = None
        self._ring_lock = asyncio.Lock()
        self._live_validator = native.LiveValidator()
        self._handlers_attached: list[tuple[int, Callable[[Packet], None]]] = []

        self._clients: dict[str, _ClientSession] = {}
        self._controls: dict[str, _ControlOwner] = {}
        self._releasing: set[str] = set()
        self._imu_lock = asyncio.Lock()
        self._imu_leases: dict[str, _ImuLease] = {}
        self._active_imu: _ActiveImuState | None = None
        self._attitude_estimators: dict[str, native.ImuAttitudeEstimator] = {}
        self._raw_imu_waiters: list[asyncio.Queue[tuple[int, bytes]]] = []

        self._servers: list[asyncio.AbstractServer] = []
        self._unix_socket_path: Path | None = None
        self._supervisor_task: asyncio.Task[Any] | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._closed = False

    @property
    def connection_epoch(self) -> int:
        return self._epoch

    def _spawn(self, coro: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def _status_payload(self, session: _ClientSession | None = None) -> dict[str, Any]:
        snap = self._snapshot
        payload: dict[str, Any] = {
            "apiVersion": API_VERSION,
            "phase": snap.phase,
            "deviceName": snap.device_name,
            "message": snap.message,
            "charging": False,
            "calibratedComponents": [],
        }
        if snap.firmware_progress is not None:
            payload["firmwareProgress"] = snap.firmware_progress
        if snap.capabilities is not None and snap.capabilities.board_target is not None:
            payload["boardTarget"] = snap.capabilities.board_target
        if snap.info is not None:
            info = snap.info
            payload["model"] = info.model
            payload["firmwareVersion"] = info.firmware_version
            payload["batteryPercent"] = int(info.battery_percent)
            payload["charging"] = bool(info.battery_charging)
            payload["calibratedComponents"] = self.calibrations.calibrated_components(info)
            bias = self.calibrations.gyro_bias_dps(info)
            if bias is not None:
                payload["gyroBiasDps"] = bias
            if session is not None:
                try:
                    payload["ringKey"] = native.scoped_device_key(info, f"local:{session.client_name}")
                except Exception:
                    pass
        return payload

    def _set_snapshot(self, snapshot: _RingSnapshot) -> None:
        self._snapshot = snapshot
        self._broadcast_status()

    def _broadcast_status(self) -> None:
        for session in list(self._clients.values()):
            if "status" in session.subscribed_topics and "info" in session.granted_scopes:
                self._enqueue_event(session, "status", self._status_payload(session))

    def _enqueue_event(self, session: _ClientSession, topic: str, data: dict[str, Any]) -> None:
        if session.closed:
            return
        try:
            session.event_queue.put_nowait((topic, data))
        except asyncio.QueueFull:
            _logger.warning("Connect client %s event queue overflow; unsubscribing", session.client_id)
            self._unsubscribe_session(session, release_streams=True)

    async def connect_ring(self, address: str | None = None) -> None:
        target = address or self.address
        if not target:
            raise ValueError("No ring address configured")
        async with self._ring_lock:
            await self._disconnect_ring_locked(broadcast=False)
            self._epoch += 1
            epoch = self._epoch
            self._set_snapshot(_RingSnapshot(phase="connecting", device_name="OpenZilo Ring", address=target))
            client = self._client_factory(
                address=target,
                scan_timeout_s=self.scan_timeout_s,
                connect_timeout_s=self.connect_timeout_s,
                allow_unverified_features=self.allow_unverified_features,
            )
            try:
                await client.connect()
                self._ring = client
                self._live_validator = native.LiveValidator()
                self._attach_handlers(client, epoch)
                enable_time_sync(client)
                info = _to_native_info(await get_system_info(client))
                identity = _ring_identity(info, target)
                if self._expected_identity is not None and identity != self._expected_identity:
                    raise RuntimeError("The connected ring does not match the saved binding")
                self._expected_identity = identity
                capabilities = await get_device_capabilities(client, timeout_s=3.0)
                if self._ring is not client or not client.is_connected:
                    raise RuntimeError("Ring disconnected during initialization")
                device_name = getattr(getattr(client, "transport", None), "device_name", None) or info.model or "OpenZilo Ring"
                self._set_snapshot(_RingSnapshot(
                    phase="connected",
                    device_name=str(device_name),
                    address=target,
                    info=info,
                    capabilities=capabilities,
                ))
            except BaseException as exc:
                await self._disconnect_ring_locked(broadcast=False)
                self._set_snapshot(_RingSnapshot(phase="disconnected", address=target, message=str(exc)))
                raise

    async def disconnect_ring(self, *, expected_epoch: int | None = None) -> None:
        async with self._ring_lock:
            if expected_epoch is not None and expected_epoch != self._epoch:
                return
            await self._disconnect_ring_locked(broadcast=True)

    async def _disconnect_ring_locked(self, *, broadcast: bool) -> None:
        self._epoch += 1
        ring = self._ring
        self._ring = None
        if ring is not None:
            for cmd, handler in self._handlers_attached:
                try:
                    ring.remove_packet_handler(cmd, handler)
                except Exception:
                    pass
            self._handlers_attached.clear()
            try:
                await ring.disconnect()
            except Exception:
                pass
        for resource, owner in list(self._controls.items()):
            if resource != "firmware":
                self._drop_control(resource, owner)
        self._imu_leases.clear()
        self._active_imu = None
        if broadcast:
            self._set_snapshot(_RingSnapshot(phase="disconnected", address=self.address or ""))

    def _attach_handlers(self, client: OpenZiloClient, epoch: int) -> None:
        self._handlers_attached.clear()
        for cmd in _EVENT_COMMANDS:
            def _make_handler(expected_epoch: int) -> Callable[[Packet], None]:
                def _on_packet(packet: Packet) -> None:
                    self._handle_ring_packet(expected_epoch, packet)
                return _on_packet
            handler = _make_handler(epoch)
            client.add_packet_handler(cmd, handler, queue_packets=True)
            self._handlers_attached.append((cmd, handler))

    def _handle_ring_packet(self, epoch: int, packet: Packet) -> None:
        if epoch != self._epoch:
            return
        topic = command_topic(packet.command)
        if topic is None or len(packet.body) > MAX_PACKET_BODY_BYTES:
            return

        if topic == "imu":
            for waiter in list(self._raw_imu_waiters):
                try:
                    waiter.put_nowait((epoch, bytes(packet.body)))
                except asyncio.QueueFull:
                    pass
            physical = self._decode_physical_imu(packet.body, epoch)
            base_event: dict[str, Any] = {
                "apiVersion": API_VERSION,
                "command": int(packet.command),
                "body": encode_bytes(bytes(packet.body)),
            }
            if physical is not None:
                self._write_physical_imu_fields(base_event, physical)
        elif topic == "live":
            try:
                live_event = self._live_validator.accept(native_packet(packet))
                base_event = {"apiVersion": API_VERSION, **_live_event_to_payload(live_event)}
            except Exception:
                base_event = {"apiVersion": API_VERSION, "type": "interrupted"}
            physical = None
        else:
            base_event = {
                "apiVersion": API_VERSION,
                "command": int(packet.command),
                "body": encode_bytes(bytes(packet.body)),
            }
            if topic == "gesture":
                self._enrich_gesture_fields(base_event, packet.command, packet.body)
            physical = None

        required_scope = topic_scope(topic)
        for session in list(self._clients.values()):
            if topic not in session.subscribed_topics:
                continue
            if required_scope not in session.granted_scopes:
                continue
            if not self._owns_event(topic, session.client_id):
                continue
            outbound = dict(base_event)
            if topic == "imu" and physical is not None:
                self._attach_client_attitude(outbound, session.client_id, physical)
            self._enqueue_event(session, topic, outbound)

    def _decode_physical_imu(self, raw_body: bytes, epoch: int) -> native.PhysicalImuBatch | None:
        state = self._active_imu
        if state is None or state.epoch != epoch:
            return None
        try:
            raw_batch = native.parse_imu(raw_body)
            snap = self._snapshot
            features = _native_features(snap.capabilities.features) if snap.capabilities is not None else []
            return self.calibrations.apply_or_convert(raw_batch, snap.info, state.config, features)
        except Exception:
            return None

    @staticmethod
    def _write_physical_imu_fields(event: dict[str, Any], physical: native.PhysicalImuBatch) -> None:
        ts: list[int] = []
        accel: list[float] = []
        gyro: list[float] = []
        for s in physical.samples:
            ts.append(int(s.timestamp_ms))
            accel.extend((float(s.accel_g[0]), float(s.accel_g[1]), float(s.accel_g[2])))
            gyro.extend((float(s.gyro_dps[0]), float(s.gyro_dps[1]), float(s.gyro_dps[2])))
        event["sequenceStart"] = int(physical.sequence_start)
        event["timestampsMs"] = ts
        event["accelG"] = accel
        event["gyroDps"] = gyro
        event["appliedComponents"] = list(physical.applied_components)

    def _get_or_create_estimator(self, client_id: str) -> native.ImuAttitudeEstimator:
        estimator = self._attitude_estimators.get(client_id)
        if estimator is not None:
            return estimator
        snap = self._snapshot
        board_target = snap.capabilities.board_target if snap.capabilities is not None else None
        estimator = native.ImuAttitudeEstimator(native.default_ring_axis_mapping(board_target), 1.6)
        mount = self.calibrations.load_mount_alignment(snap.info)
        if mount is not None:
            try:
                estimator.set_mount_alignment(mount)
            except Exception:
                pass
        self._attitude_estimators[client_id] = estimator
        return estimator

    def _attach_client_attitude(
        self,
        event: dict[str, Any],
        client_id: str,
        physical: native.PhysicalImuBatch,
    ) -> None:
        estimator = self._get_or_create_estimator(client_id)
        try:
            snapshots = estimator.accept_batch(physical)
        except Exception:
            return
        if not snapshots:
            return
        latest = snapshots[-1]
        traj: list[float] = []
        for snap in snapshots:
            sq = snap.quaternion
            traj.extend((float(sq.w), float(sq.x), float(sq.y), float(sq.z)))
        q = latest.quaternion
        event["trajectoryQuaternions"] = traj
        event["quaternion"] = [float(q.w), float(q.x), float(q.y), float(q.z)]
        event["eulerDeg"] = [
            float(latest.euler.roll_deg),
            float(latest.euler.pitch_deg),
            float(latest.euler.yaw_deg),
        ]
        event["gyroBodyDps"] = [float(v) for v in latest.gyro_body_dps]
        event["tiltFromZenithDeg"] = float(latest.tilt_from_zenith_deg)
        event["posture"] = latest.posture.name
        event["stationary"] = bool(latest.stationary)
        try:
            event["openGlMatrix"] = [float(v) for v in native.quaternion_to_opengl_matrix(q)]
        except Exception:
            pass

    @staticmethod
    def _enrich_gesture_fields(event: dict[str, Any], command: int, body: bytes) -> None:
        try:
            parsed = native.parse_device_event(command, body)
        except Exception:
            return
        event["timestamp"] = int(parsed.timestamp)
        event["timestampUnit"] = parsed.timestamp_unit
        if parsed.gesture_id is not None:
            event["gestureId"] = int(parsed.gesture_id)
            event["gestureName"] = native.sensor_gesture_name(parsed.gesture_id)

    def _owns_event(self, topic: str, client_id: str) -> bool:
        if topic not in ("audio", "live"):
            return True
        owner = self._controls.get(topic)
        return owner is not None and owner.epoch == self._epoch and owner.client_id == client_id

    def _check_control_owner(self, resource: str, client_id: str) -> None:
        owner = self._controls.get(resource)
        if owner is None:
            return
        if owner.client_id != client_id or resource in self._releasing:
            raise RuntimeError("Another application owns this device operation")

    def _claim_control(
        self,
        resource: str,
        client_id: str,
        permission: str,
        request_id: str,
        epoch: int,
        file_index: int | None = None,
    ) -> _ControlOwner:
        if epoch != self._epoch:
            raise RuntimeError("Ring connection changed")
        existing = self._controls.get(resource)
        if existing is not None and existing.epoch != epoch and resource != "firmware":
            self._drop_control(resource, existing)
        self._check_control_owner(resource, client_id)
        existing = self._controls.get(resource)
        if existing is not None:
            return existing
        owner = _ControlOwner(client_id, permission, request_id, epoch, file_index)
        self._controls[resource] = owner
        return owner

    def _drop_control(self, resource: str, owner: _ControlOwner | None) -> None:
        if owner is None or self._controls.get(resource) is not owner:
            return
        self._controls.pop(resource, None)
        self._releasing.discard(resource)

    def _lose_control(self, resource: str, owner: _ControlOwner | None) -> None:
        if owner is None or self._controls.get(resource) is not owner or resource in self._releasing:
            return
        self._releasing.add(resource)
        self._spawn(self._release_control_async(resource, owner))

    async def _release_control_async(self, resource: str, owner: _ControlOwner) -> None:
        try:
            stopped = False
            try:
                async with asyncio.timeout(3.0):
                    if resource == "imu":
                        pkt = await self._send_device_request(native.DeviceRequest.STOP_IMU(), owner.epoch)
                    elif resource == "live":
                        pkt = await self._send_device_request(native.DeviceRequest.LIVE_SUBSCRIBE(False), owner.epoch)
                    elif resource == "audio":
                        if owner.file_index is None:
                            raise RuntimeError("Missing extraction identity")
                        pkt = await self._send_device_request(
                            native.DeviceRequest.AUDIO_END(owner.file_index), owner.epoch
                        )
                    elif resource == "recording":
                        status_pkt = await self._send_device_request(
                            native.DeviceRequest.RECORDING_STATUS(), owner.epoch
                        )
                        rec = native.parse_recording_status(status_pkt.body)
                        if rec.session_id == 0 or rec.state not in (1, 2, 3):
                            stopped = True
                            pkt = None
                        else:
                            pkt = await self._send_device_request(
                                native.DeviceRequest.STOP_RECORDING(rec.session_id, True), owner.epoch
                            )
                    else:
                        raise RuntimeError("Operation outcome requires reconnect")
                    if pkt is not None:
                        if len(pkt.body) >= 2 and pkt.body[0] == 0 and pkt.body[1] == 0:
                            stopped = True
            except Exception:
                stopped = False
            if not stopped:
                try:
                    await self.disconnect_ring(expected_epoch=owner.epoch)
                except Exception:
                    pass
        finally:
            self._drop_control(resource, owner)
            self._releasing.discard(resource)

    async def _send_device_request(
        self,
        request: native.DeviceRequest,
        expected_epoch: int,
        *,
        timeout_s: float = 10.0,
    ) -> Packet:
        if expected_epoch != self._epoch:
            raise RuntimeError("Ring connection changed")
        ring = self._ring
        if ring is None or not ring.is_connected:
            raise RuntimeError("Connect a ring first")
        spec = native.prepare_request(request)
        if spec.response is None:
            await ring.send_command(spec.command, bytes(spec.body))
            return Packet(command=int(spec.command), body=b"", version=4, body_crc=0)
        return await ring.request(spec.command, spec.response, bytes(spec.body), timeout_s=timeout_s)

    async def _acquire_imu_lease(self, lease_key: str, epoch: int) -> _ActiveImuState:
        async with self._imu_lock:
            if epoch != self._epoch:
                raise RuntimeError("Ring connection changed")
            for key, lease in list(self._imu_leases.items()):
                if lease.epoch != epoch:
                    self._imu_leases.pop(key, None)
            if self._active_imu is not None and self._active_imu.epoch == epoch and self._imu_leases:
                state = self._active_imu
            else:
                packet = await self._send_device_request(native.DeviceRequest.START_IMU(), epoch)
                if len(packet.body) >= 2:
                    code = int.from_bytes(packet.body[:2], "big")
                    if code != 0:
                        raise _DeviceRejected(code, packet.command, packet.body)
                cfg = native.parse_imu_config(packet.body)
                state = _ActiveImuState(epoch=epoch, response_body=bytes(packet.body), config=cfg)
                self._active_imu = state
            self._imu_leases[lease_key] = _ImuLease(client_id=lease_key, epoch=epoch)
            return state

    async def _release_imu_lease(self, lease_key: str) -> None:
        async with self._imu_lock:
            removed = self._imu_leases.pop(lease_key, None)
            if removed is None:
                return
            if not any(lease.epoch == removed.epoch for lease in self._imu_leases.values()):
                if self._active_imu is not None and self._active_imu.epoch == removed.epoch:
                    self._active_imu = None
                    if removed.epoch == self._epoch:
                        try:
                            async with asyncio.timeout(3.0):
                                await self._send_device_request(native.DeviceRequest.STOP_IMU(), removed.epoch)
                        except Exception:
                            pass

    def _require_access(self, session: _ClientSession, scope: str) -> None:
        if scope not in SCOPES or scope not in session.granted_scopes:
            raise _PermissionDenied(f"Permission not granted: {scope}")

    async def _perform_operation(
        self,
        session: _ClientSession,
        operation: str,
        args: dict[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        epoch = self._epoch

        if operation == "system.info":
            ring = self._ring
            if ring is None or not ring.is_connected:
                raise RuntimeError("Connect a ring first")
            info = _to_native_info(await get_system_info(ring))
            self._set_snapshot(replace(self._snapshot, info=info, message=None))
            return self._status_payload(session)

        if operation == "imu.start":
            state = await self._acquire_imu_lease(session.client_id, epoch)
            return {
                "command": 0x0602,
                "body": encode_bytes(state.response_body),
                "sampleRateHz": int(state.config.sample_rate_hz),
                "accelRangeG": int(state.config.accel_range_g),
                "gyroRangeDps": int(state.config.gyro_range_dps),
            }

        if operation == "imu.stop":
            self._attitude_estimators.pop(session.client_id, None)
            await self._release_imu_lease(session.client_id)
            return {"command": 0x0604, "body": encode_bytes(b"\x00\x00")}

        if operation == "imu.attitude.zero":
            estimator = self._attitude_estimators.get(session.client_id)
            if estimator is not None:
                estimator.zero_heading()
            return {}

        if operation == "imu.attitude.mapping":
            preset_name = args.get("preset")
            preset_map = {
                "STANDARD": native.ImuAxisPreset.STANDARD,
                "SWAPPED_XY": native.ImuAxisPreset.SWAPPED_XY,
                "Z_BORE": native.ImuAxisPreset.Z_BORE,
            }
            if preset_name not in preset_map:
                raise ValueError("Invalid axis preset")
            invert = _require_bool(args, "invertRadialZ")
            mapping = native.ImuAxisMapping(preset=preset_map[preset_name], invert_radial_z=invert)
            estimator = self._attitude_estimators.get(session.client_id)
            if estimator is None:
                estimator = native.ImuAttitudeEstimator(mapping, 1.6)
                self._attitude_estimators[session.client_id] = estimator
            else:
                estimator.set_axis_mapping(mapping)
            return {}

        if operation == "imu.calibration":
            return {"calibratedComponents": self.calibrations.calibrated_components(self._snapshot.info)}

        if operation == "imu.calibrate.upright":
            info = self._snapshot.info
            if info is None:
                raise RuntimeError("Connect a ring first")
            estimator = self._attitude_estimators.get(session.client_id)
            if estimator is None:
                raise RuntimeError("Start IMU stream before alignment")
            mount = estimator.calibrate_worn_button_up()
            self.calibrations.save_mount_alignment(info, mount)
            for other_id, other_est in self._attitude_estimators.items():
                if other_id != session.client_id:
                    try:
                        other_est.set_mount_alignment(mount)
                    except Exception:
                        pass
            self._broadcast_status()
            return {"calibratedComponents": self.calibrations.calibrated_components(info)}

        if operation == "imu.calibration.reset":
            info = self._snapshot.info
            if info is None:
                raise RuntimeError("Connect a ring first")
            self.calibrations.reset_calibration(info)
            for est in self._attitude_estimators.values():
                est.clear_mount_alignment()
                est.clear_gyro_bias()
            self._broadcast_status()
            return {"calibratedComponents": []}

        if operation == "imu.calibrate.gyro":
            duration_ms = _require_uint(args, "durationMs", 30_000) if "durationMs" in args else 3_000
            duration_ms = max(2_000, min(30_000, duration_ms))
            align_flat = _require_bool(args, "alignFlat") if "alignFlat" in args else True
            temp_lease = f"cal:{uuid.uuid4().hex}"
            waiter: asyncio.Queue[tuple[int, bytes]] = asyncio.Queue(maxsize=256)
            self._raw_imu_waiters.append(waiter)
            imu_state = await self._acquire_imu_lease(temp_lease, epoch)
            try:
                desk_fn = getattr(native, "analyze_desk_imu_window", None)
                min_samples = 140 if callable(desk_fn) else 220
                target_samples = max(min_samples, min(3000, (duration_ms * int(imu_state.config.sample_rate_hz)) // 1000))
                raw_samples: list[native.ImuSample] = []
                while len(raw_samples) < target_samples:
                    ev_epoch, body = await waiter.get()
                    if ev_epoch != epoch:
                        raise RuntimeError("Ring disconnected during calibration")
                    try:
                        parsed = native.parse_imu(body)
                    except Exception:
                        continue
                    raw_samples.extend(parsed.samples)
                desk_fn = getattr(native, "analyze_desk_imu_window", None)
                if callable(desk_fn):
                    window = desk_fn(raw_samples, imu_state.config)
                else:
                    window = native.analyze_imu_static_window(raw_samples, imu_state.config, True)
                snap = self._snapshot
                info = snap.info
                if info is None:
                    raise RuntimeError("Ring disconnected during calibration")
                features = _native_features(snap.capabilities.features) if snap.capabilities is not None else []
                self.calibrations.save_gyro_bias_window(info, imu_state.config, features, window)
                if align_flat:
                    caller_est = self._get_or_create_estimator(session.client_id)
                    mount = caller_est.calibrate_flat_table_mount(window.accel_g)
                    self.calibrations.save_mount_alignment(info, mount)
                    for other_id, other_est in self._attitude_estimators.items():
                        if other_id != session.client_id:
                            try:
                                other_est.set_mount_alignment(mount)
                            except Exception:
                                pass
                for est in self._attitude_estimators.values():
                    est.clear_gyro_bias()
                self._broadcast_status()
                result: dict[str, Any] = {
                    "calibratedComponents": self.calibrations.calibrated_components(info),
                }
                bias = self.calibrations.gyro_bias_dps(info)
                if bias is not None:
                    result["gyroBiasDps"] = bias
                return result
            finally:
                if waiter in self._raw_imu_waiters:
                    self._raw_imu_waiters.remove(waiter)
                await self._release_imu_lease(temp_lease)

        if operation == "firmware.upgrade":
            if self._firmware_public_key is None:
                raise RuntimeError("Firmware upgrades require --firmware-public-key on the host")
            firmware_bytes = self._read_firmware_argument(args)
            ring = self._ring
            if ring is None or not ring.is_connected:
                raise RuntimeError("Connect a ring first")
            owner = self._claim_control("firmware", session.client_id, "firmware", request_id, epoch)
            try:
                self._set_snapshot(replace(self._snapshot, phase="upgrading", firmware_progress=0, message=None))

                def _on_progress(sent: int, total: int) -> None:
                    if total > 0:
                        pct = min(100, (sent * 100) // total)
                        if pct != self._snapshot.firmware_progress:
                            self._set_snapshot(replace(self._snapshot, phase="upgrading", firmware_progress=pct))

                info = _to_native_info(
                    await update_firmware(
                        ring,
                        firmware_bytes,
                        trusted_public_key=self._firmware_public_key,
                        progress=_on_progress,
                    )
                )
                capabilities = await get_device_capabilities(ring, timeout_s=3.0)
                self._set_snapshot(replace(
                    self._snapshot,
                    phase="connected",
                    info=info,
                    capabilities=capabilities,
                    firmware_progress=None,
                    message="Firmware update verified",
                ))
            except BaseException as exc:
                self._set_snapshot(replace(
                    self._snapshot,
                    phase="disconnected" if not ring.is_connected else self._snapshot.phase,
                    firmware_progress=None,
                    message=f"Firmware installation failed: {exc}",
                ))
                raise
            finally:
                self._drop_control("firmware", owner)
            return self._status_payload(session)

        request = self._build_device_request(operation, args)
        resource = self._operation_resource(operation)
        if resource is not None:
            self._check_control_owner(resource, session.client_id)
        if operation == "audio.clear" and "audio" in self._controls:
            raise RuntimeError("End extraction before clearing recordings")
        if resource == "audio" and operation != "audio.clear":
            active_audio = self._controls.get("audio")
            if active_audio is not None and active_audio.file_index is not None:
                if active_audio.file_index != _require_uint(args, "fileIndex"):
                    raise ValueError("End the current extraction before selecting another file")

        starts_control = operation in ("recording.start", "audio.info", "audio.quick", "audio.read") or (
            operation == "live.subscribe" and _require_bool(args, "enabled")
        )
        owner: _ControlOwner | None = None
        if starts_control and resource is not None:
            file_index = _require_uint(args, "fileIndex") if resource == "audio" else None
            owner = self._claim_control(
                resource, session.client_id, operation_scope(operation), request_id, epoch, file_index=file_index
            )
        elif resource is not None:
            owner = self._controls.get(resource)

        try:
            packet = await self._send_device_request(request, epoch)
        except BaseException:
            if starts_control and resource is not None:
                self._lose_control(resource, owner)
            raise

        if len(packet.body) >= 2:
            code = int.from_bytes(packet.body[:2], "big")
            if code != 0:
                if starts_control and resource is not None:
                    self._lose_control(resource, owner)
                raise _DeviceRejected(code, packet.command, packet.body)

        if operation in ("recording.stop", "audio.end") or (
            operation == "live.subscribe" and not _require_bool(args, "enabled")
        ):
            if resource is not None:
                self._drop_control(resource, owner)

        if len(packet.body) > MAX_PACKET_BODY_BYTES:
            raise ValueError("Response exceeds API limit")
        return {
            "command": int(packet.command),
            "body": encode_bytes(bytes(packet.body)),
        }

    @staticmethod
    def _read_firmware_argument(args: dict[str, Any]) -> bytes:
        if "firmware" in args:
            data = decode_bytes(args["firmware"])
            if not (1 <= len(data) <= MAX_FIRMWARE_BYTES):
                raise ValueError("Firmware must be between 1 byte and 600 KiB")
            return data
        if "firmwarePath" in args:
            raw_path = args["firmwarePath"]
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ValueError("firmwarePath must be a non-empty string")
            path = Path(raw_path).expanduser()
            st = path.stat()
            if not stat.S_ISREG(st.st_mode) or not (1 <= st.st_size <= MAX_FIRMWARE_BYTES):
                raise ValueError("Firmware must be a bounded regular file")
            return path.read_bytes()
        raise ValueError("Missing firmware or firmwarePath argument")

    @staticmethod
    def _operation_resource(operation: str) -> str | None:
        if operation in ("recording.start", "recording.stop", "recording.configure"):
            return "recording"
        if operation == "live.subscribe":
            return "live"
        if operation in ("audio.info", "audio.quick", "audio.read", "audio.end", "audio.clear"):
            return "audio"
        return None

    @staticmethod
    def _build_device_request(operation: str, args: dict[str, Any]) -> native.DeviceRequest:
        if operation == "capabilities":
            return native.DeviceRequest.CAPABILITIES()
        if operation == "connection.rssi":
            return native.DeviceRequest.CONNECTION_RSSI()
        if operation == "audio.count":
            return native.DeviceRequest.AUDIO_COUNT()
        if operation == "audio.info":
            return native.DeviceRequest.AUDIO_INFO(_require_uint(args, "fileIndex"))
        if operation == "audio.quick":
            return native.DeviceRequest.AUDIO_QUICK(_require_uint(args, "fileIndex"))
        if operation == "audio.read":
            return native.DeviceRequest.AUDIO_READ(_require_uint(args, "fileIndex"), _require_uint(args, "offset"))
        if operation == "audio.end":
            return native.DeviceRequest.AUDIO_END(_require_uint(args, "fileIndex"))
        if operation == "audio.clear":
            confirmed = _require_bool(args, "confirmed")
            if not confirmed:
                raise ValueError("Deleting recordings requires confirmed=true")
            return native.DeviceRequest.CLEAR_AUDIO(True)
        if operation == "live.subscribe":
            return native.DeviceRequest.LIVE_SUBSCRIBE(_require_bool(args, "enabled"))
        if operation == "recording.config":
            return native.DeviceRequest.GET_RECORDING_CONFIG()
        if operation == "recording.configure":
            cfg = native.RecordingConfig(
                output=_require_uint(args, "output", 3),
                disconnect_policy=_require_uint(args, "disconnectPolicy", 1),
                channels=_require_uint(args, "channels", 2),
                bitrate=_require_uint(args, "bitrate"),
                gain_left_q8=_require_uint(args, "gainLeftQ8", 1024),
                gain_right_q8=_require_uint(args, "gainRightQ8", 1024),
                max_duration_ms=_require_uint(args, "maxDurationMs", 60000),
            )
            return native.DeviceRequest.SET_RECORDING_CONFIG(cfg)
        if operation == "recording.start":
            return native.DeviceRequest.START_RECORDING()
        if operation == "recording.stop":
            session_id = _require_uint(args, "sessionId")
            if session_id == 0:
                raise ValueError("sessionId must be non-zero")
            return native.DeviceRequest.STOP_RECORDING(session_id, _require_bool(args, "cancel"))
        if operation == "recording.status":
            return native.DeviceRequest.RECORDING_STATUS()
        if operation == "logs.storage":
            return native.DeviceRequest.LOG_STORAGE()
        if operation == "logs.read":
            return native.DeviceRequest.READ_LOG(
                _require_uint(args, "fileIndex"),
                _require_uint(args, "offset"),
                _require_uint(args, "length", 4096),
            )
        if operation == "time.reply":
            return native.DeviceRequest.TIME_REPLY(
                _require_uint(args, "requestTime"),
                _require_uint(args, "responseTime"),
                _require_uint(args, "sendTime"),
            )
        raise ValueError(f"Unknown operation: {operation}")

    async def _send_json(self, session: _ClientSession, payload: dict[str, Any]) -> None:
        if session.closed:
            return
        line = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        async with session.write_lock:
            if session.closed:
                return
            try:
                session.writer.write(line)
                await session.writer.drain()
            except Exception:
                session.closed = True

    async def _send_result(self, session: _ClientSession, request_id: str, result: dict[str, Any]) -> None:
        await self._send_json(session, {"type": "result", "requestId": request_id, "result": result})

    async def _event_sender_loop(self, session: _ClientSession) -> None:
        try:
            while not session.closed:
                topic, data = await session.event_queue.get()
                if topic not in session.subscribed_topics:
                    continue
                if topic_scope(topic) not in session.granted_scopes:
                    continue
                if not self._owns_event(topic, session.client_id):
                    continue
                await self._send_json(session, {"type": "event", "topic": topic, "data": data})
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    def _unsubscribe_session(self, session: _ClientSession, *, release_streams: bool = True) -> None:
        had_imu = "imu" in session.subscribed_topics
        session.subscribed_topics.clear()
        while not session.event_queue.empty():
            try:
                session.event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        if release_streams:
            live_owner = self._controls.get("live")
            if live_owner is not None and live_owner.client_id == session.client_id:
                self._lose_control("live", live_owner)
            if had_imu:
                self._attitude_estimators.pop(session.client_id, None)
                self._spawn(self._release_imu_lease(session.client_id))

    async def _close_session(self, session: _ClientSession) -> None:
        if session.closed:
            return
        session.closed = True
        self._clients.pop(session.client_id, None)
        for task in list(session.active_ops.values()):
            task.cancel()
        session.active_ops.clear()
        session.op_permissions.clear()
        for resource, owner in list(self._controls.items()):
            if owner.client_id == session.client_id:
                self._lose_control(resource, owner)
        self._attitude_estimators.pop(session.client_id, None)
        await self._release_imu_lease(session.client_id)
        session.subscribed_topics.clear()
        if session.event_task is not None:
            session.event_task.cancel()
        try:
            session.writer.close()
            await session.writer.wait_closed()
        except Exception:
            pass

    def _total_active_ops(self) -> int:
        return sum(len(c.active_ops) for c in self._clients.values())

    def _total_subscriptions(self) -> int:
        return sum(1 for c in self._clients.values() if c.subscribed_topics)

    async def _handle_message(self, session: _ClientSession, message: dict[str, Any]) -> None:
        method = message.get("method")
        request_id = str(message.get("requestId") or message.get("id") or "")
        if not request_id or len(request_id) > 64:
            if request_id:
                await self._send_result(session, request_id[:64], self._error_bundle("invalid_arguments", "Invalid request ID"))
            return

        if method == "requestAuthorization":
            try:
                raw_scopes = message.get("scopes")
                if not isinstance(raw_scopes, list) or not all(isinstance(s, str) for s in raw_scopes):
                    raise ValueError("scopes must be a list of strings")
                requested = require_scopes(set(raw_scopes))
                if self._token is not None:
                    provided = message.get("token")
                    if not isinstance(provided, str) or not hmac.compare_digest(provided, self._token):
                        raise _PermissionDenied("Invalid host authorization token")
                client_name = message.get("clientName")
                if isinstance(client_name, str) and client_name.strip():
                    session.client_name = client_name.strip()[:128]
                granted = requested & self.allowed_scopes
                denied = requested - self.allowed_scopes
                session.granted_scopes |= granted
                await self._send_result(session, request_id, {
                    "ok": True,
                    "apiVersion": API_VERSION,
                    "grantedScopes": sorted(granted),
                    "deniedScopes": sorted(denied),
                    "scopes": sorted(session.granted_scopes),
                })
            except _PermissionDenied as exc:
                await self._send_result(session, request_id, self._error_bundle("permission_denied", str(exc)))
            except ValueError as exc:
                await self._send_result(session, request_id, self._error_bundle("invalid_arguments", str(exc)))
            return

        if method == "getStatus":
            try:
                self._require_access(session, "info")
                payload = self._status_payload(session)
                payload["ok"] = True
                await self._send_result(session, request_id, payload)
            except _PermissionDenied as exc:
                await self._send_result(session, request_id, self._error_bundle("permission_denied", str(exc)))
            return

        if method == "subscribe":
            try:
                raw_topics = message.get("topics")
                if not isinstance(raw_topics, list) or not raw_topics or not all(isinstance(t, str) for t in raw_topics):
                    raise ValueError("Invalid topics")
                selected = set(raw_topics)
                if len(selected) > len(SCOPES):
                    raise ValueError("Invalid topics")
                for topic in selected:
                    self._require_access(session, topic_scope(topic))
                if not session.subscribed_topics and self._total_subscriptions() >= MAX_SUBSCRIPTIONS_TOTAL:
                    raise RuntimeError("Too many listeners")
                self._unsubscribe_session(session, release_streams=False)
                session.subscribed_topics = selected
                await self._send_result(session, request_id, {
                    "ok": True,
                    "apiVersion": API_VERSION,
                    "topics": sorted(selected),
                })
            except _PermissionDenied as exc:
                await self._send_result(session, request_id, self._error_bundle("permission_denied", str(exc)))
            except ValueError as exc:
                await self._send_result(session, request_id, self._error_bundle("invalid_arguments", str(exc)))
            except Exception as exc:
                await self._send_result(session, request_id, self._error_bundle("operation_failed", str(exc)))
            return

        if method == "unsubscribe":
            self._unsubscribe_session(session, release_streams=True)
            await self._send_result(session, request_id, {"ok": True, "apiVersion": API_VERSION})
            return

        if method == "cancel":
            target_id = str(message.get("targetRequestId") or message.get("cancelRequestId") or "")
            if not target_id or len(target_id) > 64:
                await self._send_result(session, request_id, self._error_bundle("invalid_arguments", "Invalid targetRequestId"))
                return
            task = session.active_ops.get(target_id)
            if task is not None:
                task.cancel()
            for resource, owner in list(self._controls.items()):
                if owner.client_id == session.client_id and owner.request_id == target_id:
                    self._lose_control(resource, owner)
            await self._send_result(session, request_id, {"ok": True, "apiVersion": API_VERSION})
            return

        if method == "closeClient":
            await self._send_result(session, request_id, {"ok": True, "apiVersion": API_VERSION})
            await self._close_session(session)
            return

        if method == "execute":
            operation = message.get("operation")
            args = message.get("arguments")
            if args is None:
                args = {}
            try:
                if not isinstance(operation, str):
                    raise ValueError("Missing operation")
                if not isinstance(args, dict):
                    raise ValueError("arguments must be an object")
                permission = operation_scope(operation)
                self._require_access(session, permission)
                if operation != "firmware.upgrade":
                    encoded_size = len(json.dumps(args, ensure_ascii=False).encode("utf-8"))
                    if encoded_size > MAX_ARGUMENTS_BYTES:
                        raise ValueError(f"Arguments exceed {MAX_ARGUMENTS_BYTES} bytes")
                if len(session.active_ops) >= MAX_ACTIVE_OPS_PER_CLIENT or self._total_active_ops() >= MAX_ACTIVE_OPS_TOTAL:
                    raise RuntimeError("Too many active operations")
                if request_id in session.active_ops:
                    raise ValueError("Duplicate active requestId")
            except _PermissionDenied as exc:
                await self._send_result(session, request_id, self._error_bundle("permission_denied", str(exc)))
                return
            except ValueError as exc:
                await self._send_result(session, request_id, self._error_bundle("invalid_arguments", str(exc)))
                return
            except Exception as exc:
                await self._send_result(session, request_id, self._error_bundle("operation_failed", str(exc)))
                return

            async def _run_op() -> None:
                timeout_s = 600.0 if operation == "firmware.upgrade" else (
                    max(30.0, (int(args.get("durationMs", 3000)) / 1000.0) + 15.0)
                    if operation == "imu.calibrate.gyro" and isinstance(args.get("durationMs", 3000), int)
                    else 30.0
                )
                try:
                    async with asyncio.timeout(timeout_s):
                        self._require_access(session, permission)
                        payload = await self._perform_operation(session, operation, dict(args), request_id)
                        payload["ok"] = True
                        payload["apiVersion"] = API_VERSION
                except asyncio.CancelledError:
                    for resource, owner in list(self._controls.items()):
                        if owner.client_id == session.client_id and owner.request_id == request_id:
                            self._lose_control(resource, owner)
                    raise
                except _PermissionDenied as exc:
                    payload = self._error_bundle("permission_denied", str(exc))
                except _DeviceRejected as exc:
                    payload = self._error_bundle(
                        "device_rejected",
                        str(exc),
                        extra={
                            "deviceCode": exc.code,
                            "command": exc.command,
                            "body": encode_bytes(exc.body),
                        },
                    )
                except DeviceError as exc:
                    payload = self._error_bundle(
                        "device_rejected",
                        str(exc),
                        extra={"deviceCode": int(exc.code)},
                    )
                except ValueError as exc:
                    payload = self._error_bundle("invalid_arguments", str(exc))
                except Exception as exc:
                    payload = self._error_bundle("operation_failed", str(exc))
                finally:
                    session.active_ops.pop(request_id, None)
                    session.op_permissions.pop(request_id, None)

                if not session.closed and permission in session.granted_scopes:
                    await self._send_result(session, request_id, payload)

            task = asyncio.create_task(_run_op())
            session.active_ops[request_id] = task
            session.op_permissions[request_id] = permission
            return

        await self._send_result(session, request_id, self._error_bundle("invalid_arguments", f"Unknown method: {method!r}"))

    @staticmethod
    def _error_bundle(error: str, detail: str, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        bundle: dict[str, Any] = {
            "ok": False,
            "apiVersion": API_VERSION,
            "error": error,
            "message": "Operation failed",
        }
        if detail:
            bundle["detail"] = detail
        if extra:
            bundle.update(extra)
        return bundle

    async def handle_stream(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client_id = uuid.uuid4().hex
        initial_scopes = set() if self.require_authorization else set(self.allowed_scopes)
        session = _ClientSession(
            client_id=client_id,
            writer=writer,
            client_name=f"client-{client_id[:8]}",
            granted_scopes=initial_scopes,
            subscribed_topics=set(),
            event_queue=asyncio.Queue(maxsize=EVENT_QUEUE_SIZE),
            write_lock=asyncio.Lock(),
            active_ops={},
            op_permissions={},
        )
        self._clients[client_id] = session
        session.event_task = asyncio.create_task(self._event_sender_loop(session))
        try:
            while not session.closed and not self._closed:
                try:
                    raw_line = await reader.readline()
                except ValueError:
                    await self._send_json(session, {
                        "type": "result",
                        "requestId": "",
                        "result": self._error_bundle("invalid_arguments", "Message exceeds size limit"),
                    })
                    break
                if not raw_line:
                    break
                if len(raw_line) > _MAX_LINE_BYTES:
                    await self._send_json(session, {
                        "type": "result",
                        "requestId": "",
                        "result": self._error_bundle("invalid_arguments", "Message exceeds size limit"),
                    })
                    break
                text = raw_line.decode("utf-8", errors="strict").strip()
                if not text:
                    continue
                try:
                    message = json.loads(text)
                except ValueError:
                    continue
                if isinstance(message, dict):
                    await self._handle_message(session, message)
        finally:
            await self._close_session(session)

    async def start_tcp(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> tuple[str, int]:
        server = await asyncio.start_server(self.handle_stream, host=host, port=port, limit=_MAX_LINE_BYTES)
        self._servers.append(server)
        sock = server.sockets[0]
        bound_host, bound_port = sock.getsockname()[:2]
        return str(bound_host), int(bound_port)

    async def start_unix(self, socket_path: Path | str) -> Path:
        path = Path(socket_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        server = await asyncio.start_unix_server(self.handle_stream, path=str(path), limit=_MAX_LINE_BYTES)
        os.chmod(path, 0o600)
        self._unix_socket_path = path
        self._servers.append(server)
        return path

    def start_connection_supervisor(self) -> None:
        if self._supervisor_task is not None or not self.address:
            return
        self._supervisor_task = asyncio.create_task(self._maintain_connection())

    async def _maintain_connection(self) -> None:
        retry_delay = 1.0
        while not self._closed:
            if self._ring is not None and self._ring.is_connected:
                disconnected_event = getattr(self._ring, "_disconnected", None)
                if isinstance(disconnected_event, asyncio.Event):
                    await disconnected_event.wait()
                else:
                    await asyncio.sleep(0.5)
                    continue
                if self._closed:
                    break
                async with self._ring_lock:
                    if self._ring is not None and not self._ring.is_connected:
                        await self._disconnect_ring_locked(broadcast=True)
                if not self.auto_reconnect:
                    break
                await asyncio.sleep(1.0)
            try:
                await self.connect_ring()
                retry_delay = 1.0
            except asyncio.CancelledError:
                raise
            except (OpenZiloError, OSError, RuntimeError, ValueError) as exc:
                _logger.warning("Ring connection attempt failed: %s", exc)
                if not self.auto_reconnect:
                    break
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2.0, 60.0)

    async def stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._supervisor_task is not None:
            self._supervisor_task.cancel()
            await asyncio.gather(self._supervisor_task, return_exceptions=True)
            self._supervisor_task = None
        for server in self._servers:
            server.close()
            await server.wait_closed()
        self._servers.clear()
        if self._unix_socket_path is not None:
            self._unix_socket_path.unlink(missing_ok=True)
            self._unix_socket_path = None
        for session in list(self._clients.values()):
            await self._close_session(session)
        if self._background_tasks:
            for task in list(self._background_tasks):
                task.cancel()
            await asyncio.gather(*list(self._background_tasks), return_exceptions=True)
            self._background_tasks.clear()
        await self.disconnect_ring()

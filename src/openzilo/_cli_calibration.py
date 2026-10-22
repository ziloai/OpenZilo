# SPDX-License-Identifier: MPL-2.0
"""Interactive charging-case calibration; candidates are saved only after validation."""
import asyncio
from dataclasses import asdict, replace
import json
import sys

from contextlib import suppress

from ._client import OpenZiloClient
from ._sensor import start_sensor_report, stop_sensor_report
from ._device import get_system_info, enable_time_sync
from ._imu_calibration import (
    ImuCalibration, ImuStaticWindow, collect_imu_static_window, fit_imu_gyro_bias,
    fit_imu_six_face_calibration, validate_imu_calibration,
)
from ._imu_profiles import (
    ImuCalibrationProfile, imu_calibration_path, imu_device_key,
    load_imu_calibration_profile, save_imu_calibration_profile, require_software_imu_source,
)



async def _prompt(message, *, client=None):
    print(message, end='', flush=True)
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    def read():
        line = sys.stdin.readline()
        if not future.done():
            if not line:
                future.set_exception(EOFError('Calibration cancelled; no new parameters were saved'))
            else:
                future.set_result(line)
    async def discard_idle_samples():
        while True:
            await asyncio.sleep(0.1)
            client._drain_queue(0x0605)
    discarder = asyncio.create_task(discard_idle_samples()) if client else None
    try:
        loop.add_reader(sys.stdin.fileno(), read)
    except (NotImplementedError, PermissionError):
        try:
            return await asyncio.to_thread(input)
        finally:
            if discarder:
                discarder.cancel()
                with suppress(asyncio.CancelledError): await discarder
    try:
        return await future
    finally:
        loop.remove_reader(sys.stdin.fileno())
        if discarder:
            discarder.cancel()
            with suppress(asyncio.CancelledError): await discarder


def _correct_window(window, calibration, *, accel=False, gyro=False):
    """Validation uses NEW raw windows, transformed in software like the stream."""
    return ImuStaticWindow(
        tuple((v-calibration.accel_bias_ug[i]/1e6)*calibration.accel_scale_ppm[i]/1e6
              if accel else v for i, v in enumerate(window.accel_g)),
        tuple(v-calibration.gyro_bias_udps[i]/1e6 if gyro else v
              for i, v in enumerate(window.gyro_dps)),
        window.accel_std_g, window.gyro_std_dps, window.samples,
    )


async def cmd_imu_calibration(args):
    path = args.profile or imu_calibration_path(args.address)
    if args.action == 'show':
        profile = load_imu_calibration_profile(path)
        if profile.device_key != imu_device_key(args.address):
            raise ValueError('Profile belongs to another device')
        print(json.dumps({'path': str(path), 'application': 'software', **asdict(profile)}, indent=2))
        return
    if args.action == 'reset':
        if path.exists() and load_imu_calibration_profile(path).device_key != imu_device_key(args.address):
            raise ValueError('Profile belongs to another device')
        path.unlink(missing_ok=True)
        print('Local software calibration profile removed.')
        return
    if not 2 <= args.seconds <= 120:
        raise ValueError('--seconds must be between 2 and 120')
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout) as client:
        await require_software_imu_source(client)
        info = await get_system_info(client)
        enable_time_sync(client)
        previous = load_imu_calibration_profile(path) if path.exists() else None
        if previous:
            previous.check_device(args.address, info.firmware_version, info.model)
        accel_stage = args.action in ('accel', 'full')
        gyro_stage = args.action in ('quick', 'full')
        streaming = False
        candidate = None
        accel_validated = previous.accel_validated if previous else False
        gyro_validated = previous.gyro_validated if previous else False
        accel_report = gyro_report = None

        async def prompt(message):
            return await _prompt(message, client=client)

        async def stop():
            nonlocal streaming
            if streaming:
                await stop_sensor_report(client)
                streaming = False

        async def start():
            nonlocal streaming, candidate
            streaming = True  # A timed-out start may still have enabled capture.
            config = await start_sensor_report(client)
            client._drain_queue(0x0605)
            if candidate is None:
                candidate = previous.calibration if previous else ImuCalibration.identity(config)
            if (config.accel_range_g != candidate.accel_range_g or
                    config.gyro_range_dps != candidate.gyro_range_dps):
                raise ValueError('IMU ranges differ from the local profile; reset the profile and recalibrate')
            return config

        async def window(config, seconds, *, gyro=True):
            try:
                return await collect_imu_static_window(client, config, seconds=seconds,
                                                       settle_seconds=2, check_gyro=gyro)
            except ValueError as exc:
                print(str(exc), flush=True)
                return None

        async def stable_gyro(config):
            print('Keep the ring still. Waiting for consecutive stable windows (up to 3 minutes).')
            history = []
            deadline = asyncio.get_running_loop().time() + 180
            while asyncio.get_running_loop().time() < deadline:
                w = await window(config, 5)
                if w is None:
                    history.clear()
                    continue
                history = (history + [w])[-3:]
                print('Current stationary angular velocity (deg/s): ' + ', '.join(f'{v:.3f}' for v in w.gyro_dps), flush=True)
                if len(history) == 3 and all(
                        max(v.gyro_dps[i] for v in history)-min(v.gyro_dps[i] for v in history) <= 0.08
                        for i in range(3)):
                    return
            raise ValueError('Readings did not stabilize; the local profile was not updated. Wait for a stable temperature and retry')

        try:
            print('Calibration is computed, saved and applied locally by OpenZilo.')
            if accel_stage:
                print('Secure the ring in the charging case. Keep it attached throughout all six faces.')
                config = await start()
                faces = {}
                while len(faces) < 6:
                    await prompt(f'Collected {list(faces)}. Place the case on an unused face, release it, then press Enter: ')
                    w = await window(config, args.seconds, gyro=False)
                    if w is None:
                        continue
                    try:
                        face = w.face
                    except ValueError as exc:
                        print(str(exc)); continue
                    if face in faces:
                        print(f'{face} is already collected. Choose another face.'); continue
                    faces[face] = w
                    print(f'Accepted {face}.')
                candidate = fit_imu_six_face_calibration(candidate, list(faces.values()))
                validations = []
                print('Candidate parameters are ready. Collecting fresh data for software validation.')
                while len(validations) < 3:
                    await prompt(f'Accelerometer validation {len(validations)+1}: choose a face on another axis, release the case, then press Enter: ')
                    w = await window(config, max(5, args.seconds), gyro=False)
                    if w is None:
                        continue
                    corrected = _correct_window(w, candidate, accel=True)
                    try:
                        if corrected.face[0] in {v.face[0] for v in validations}:
                            print('This axis is already validated. Choose another axis.'); continue
                    except ValueError as exc:
                        print(str(exc)); continue
                    validations.append(corrected)
                accel_report = validate_imu_calibration(validations, full=True, component='accel')
                accel_validated = True
                await stop()
                print('Accelerometer independent validation passed.')

            if gyro_stage and args.action == 'full' and candidate.gyro_range_dps == 0:
                gyro_stage = False
            if gyro_stage:
                print('Remove the ring from the case and keep it away from magnets. Lay it flat; use paper support to prevent rolling if needed.')
                await prompt('Place the ring still, release it, then press Enter to start gyroscope calibration: ')
                config = await start()
                if not config.gyro_range_dps:
                    raise ValueError('This sensor has no gyroscope; use accel to calibrate its accelerometer')
                await stable_gyro(config)
                gyro_window = None
                for _ in range(3):
                    gyro_window = await window(config, max(20, args.seconds))
                    if gyro_window is not None:
                        break
                if gyro_window is None:
                    raise ValueError('Could not collect stable gyroscope data; the local profile was not updated')
                candidate = fit_imu_gyro_bias(candidate, gyro_window)
                await prompt('Keep the ring flat and still. Press Enter to collect fresh validation data: ')
                verification = None
                for _ in range(3):
                    verification = await window(config, max(5, args.seconds))
                    if verification is not None:
                        break
                if verification is None:
                    raise ValueError('Could not collect stable validation data; the local profile was not updated')
                gyro_report = validate_imu_calibration(
                    [_correct_window(verification, candidate, gyro=True)], full=False, component='gyro')
                gyro_validated = True
                await stop()

            profile = ImuCalibrationProfile(imu_device_key(args.address), info.firmware_version, info.model,
                                            candidate, accel_validated, gyro_validated)
            save_imu_calibration_profile(profile, path)
            print(f'Validation passed. Local software calibration profile saved: {path}')
            print(json.dumps({'calibration': asdict(candidate), 'accel_validated': accel_validated,
                              'gyro_validated': gyro_validated, 'accel_validation': accel_report,
                              'gyro_validation': gyro_report}, indent=2))
        finally:
            await stop()

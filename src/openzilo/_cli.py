# SPDX-License-Identifier: MPL-2.0
"""Command-line interface (python -m openzilo)."""

from __future__ import annotations

import argparse
import asyncio
import json
import importlib.util
import logging
import math
import os
import shlex
import sys
from dataclasses import asdict, replace
from pathlib import Path

from ._identity import get_sdk_identity
from ._compatibility import get_device_capabilities
from ._version import __version__
from ._transport import DEFAULT_SCAN_TIMEOUT_S
from ._cli_config import config_path, load_address, save_address
from ._errors import OpenZiloError, TimeoutError as DeviceTimeoutError
from ._sensor import start_sensor_report, stop_sensor_report, wait_sensor_data
from ._client import OpenZiloClient
from ._device import (
    connect_ring,
    enable_time_sync,
    get_log_storage,
    get_system_info,
    read_log_chunk,
    scan_rings,
)
from ._ota import _validate_firmware_package, update_firmware
from ._codec import (
    build_playable_audio,
    DEFAULT_BIT_DEPTH,
    DEFAULT_CHANNELS,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SPEEX_QUALITY,
    PcmConfig,
    save_audio_bundle,
)
from ._audio import (
    clear_audio_files,
    download_audio_file,
    get_audio_file_count,
    ProgressPrinter,
    receive_auto_audio_file,
)
from ._live_audio import receive_live_audio_file
from ._recording import (
    AudioOutput, AudioDisconnectPolicy, get_audio_recording_config,
    set_audio_recording_config, get_audio_recording_status,
    start_audio_recording, stop_audio_recording, wait_audio_recording_finished,
)

_logger = logging.getLogger(__name__)


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--address", help="BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'.")
    parser.add_argument("--scan-timeout", type=positive_seconds, default=DEFAULT_SCAN_TIMEOUT_S)
    parser.add_argument("--connect-timeout", type=positive_seconds, default=30.0)
    parser.add_argument("--allow-unverified-features", action="store_true",
                        help="Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility.")
    parser.set_defaults(needs_device=True)


def positive_seconds(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("must be finite and greater than zero")
    return seconds


async def cmd_device(args: argparse.Namespace) -> None:
    if args.action == "forget":
        config_path().unlink(missing_ok=True)
        print("Saved device removed. OPENZILO_ADDRESS, if set, still applies.")
    elif args.action == "show":
        address = os.environ.get("OPENZILO_ADDRESS") or load_address()
        print(f"device: {address or '(none; run openzilo device use)'}")
        print(f"config: {config_path()}")
    else:
        address = args.address
        if address is None:
            print("Scanning for rings...", flush=True)
            devices = await scan_rings(timeout_s=args.timeout)
            if not devices:
                raise ValueError("No rings found; wake the ring and run 'device use' again")
            for index, device in enumerate(devices, 1):
                print(f"{index}. {device.name or 'Ring'}  {device.address}  RSSI={device.rssi}")
            choice = input("Select device number (Enter to cancel): ")
            if not choice.strip():
                return
            if not choice.isdecimal() or not 1 <= int(choice) <= len(devices):
                raise ValueError("Invalid device number; no device saved")
            address = devices[int(choice) - 1].address
        save_address(address)
        print(f"Saved default device: {address.strip()}")


async def cmd_shell(args: argparse.Namespace) -> None:
    print("OpenZilo 交互终端：help 查看命令，exit 退出。每条设备命令会自动连接并断开。")
    print("常用：info | audio-config | audio-record recording.wav --seconds 5 | audio-status")
    parser = build_parser()
    while True:
        try:
            # No BLE session is active at the prompt. Read on the main thread so
            # Ctrl+C cannot strand an input worker during asyncio shutdown.
            line = input("openzilo> ")
        except EOFError:
            return
        try:
            words = shlex.split(line)
            if not words:
                continue
            if words == ["exit"] or words == ["quit"]:
                return
            if words[0] == "help":
                parser.parse_args([*words[1:], "--help"])
                continue
            command = parser.parse_args(words)
            if command.func is cmd_shell:
                print("Already in the interactive shell.")
                continue
            await dispatch(command, fallback_address=args.address)
        except SystemExit as exc:
            # argparse help and invalid commands must not terminate the shell.
            if isinstance(exc.code, str):
                print(exc.code, file=sys.stderr)
            continue
        except (OpenZiloError, OSError, ValueError, RuntimeError, EOFError) as exc:
            print(f"Error: {exc}", file=sys.stderr)


async def cmd_sensor_stream(args: argparse.Namespace) -> None:
    # Open output before connecting so an invalid path cannot start device capture.
    stream = None
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        stream = args.output.open("w", encoding="utf-8")
    try:
        async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                                  connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False)) as client:
            await get_device_capabilities(client, timeout_s=3.0)
            enable_time_sync(client)
            info = await start_sensor_report(client)
            print(f"IMU: {info}", file=sys.stderr)
            try:
                loop = asyncio.get_running_loop()
                deadline = loop.time() + args.seconds
                while (remaining := deadline - loop.time()) > 0:
                    try:
                        batch = await wait_sensor_data(client, timeout_s=remaining)
                    except DeviceTimeoutError:
                        break
                    print(json.dumps(asdict(batch)), file=stream or sys.stdout, flush=True)
            finally:
                await stop_sensor_report(client)
    finally:
        if stream:
            stream.close()


def add_audio_decode_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg executable path.")
    parser.add_argument("--pcm-sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument("--pcm-channels", type=int, default=DEFAULT_CHANNELS, choices=(1, 2))
    parser.add_argument("--pcm-bit-depth", type=int, default=DEFAULT_BIT_DEPTH, choices=(8, 16))
    parser.add_argument("--speex-quality", type=int, default=DEFAULT_SPEEX_QUALITY)
    parser.add_argument("--speex-bits-size", type=int, default=None)
    parser.add_argument(
        "--allow-framed-blocks",
        action="store_true",
        help="Allow legacy 1026-byte outer blocks when parsing Speex packets.",
    )


def pcm_config_from_args(args: argparse.Namespace) -> PcmConfig:
    return PcmConfig(
        sample_rate=args.pcm_sample_rate,
        channels=args.pcm_channels,
        bit_depth=args.pcm_bit_depth,
    )


async def cmd_scan(args: argparse.Namespace) -> None:
    seen = {}

    def changed(devices):
        for device in devices:
            if seen.get(device.address) != device:
                name = device.name or "Ring (name pending)"
                print(f"name={name!r} address={device.address} rssi={device.rssi} "
                      f"matched_service={device.matched_service}", flush=True)
                seen[device.address] = device

    devices = await scan_rings(address=args.address, timeout_s=args.timeout,
                               on_devices_changed=changed)
    if not devices:
        print("No matching devices found.")


async def cmd_connect(args: argparse.Namespace) -> None:
    client = await connect_ring(address=args.address, scan_timeout_s=args.scan_timeout,
                                connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False))
    try:
        print(f"connected: {client.is_connected}")
    finally:
        await client.disconnect()


async def cmd_capabilities(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False)) as client:
        capabilities = await get_device_capabilities(client, timeout_s=args.timeout)
    result = {"sdk": asdict(get_sdk_identity()), "device": asdict(capabilities)}
    if args.command == "doctor":
        result["host"] = {"opus_decoder_installed": importlib.util.find_spec("av") is not None}
        result["notes"] = ["Capabilities describe support, not current busy state or BLE readiness."]
    print(json.dumps(result, ensure_ascii=False, indent=2))


async def cmd_info(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False)) as client:
        enable_time_sync(client)
        info = await get_system_info(client)

    print(f"firmware_version: {info.firmware_version}")
    print(f"system_time: {info.system_time}")
    print(f"audio_storage_total: {info.audio_storage_total}")
    print(f"audio_storage_available: {info.audio_storage_available}")
    print(f"battery_percent: {info.battery_percent}")
    print(f"battery_charging: {info.battery_charging}")
    print(f"sn: {info.sn}")
    print(f"cpuid: {info.cpuid}")
    print(f"model: {info.model}")


async def cmd_time_sync(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False)) as client:
        enable_time_sync(client)
        print(f"time sync auto-response enabled for {args.seconds:g}s")
        await asyncio.sleep(args.seconds)
    print("time sync session ended")


async def cmd_audio_count(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False)) as client:
        count = await get_audio_file_count(client)
    print(f"audio file count: {count}")


async def cmd_audio_download(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False)) as client:
        count = await get_audio_file_count(client)
        print(f"audio file count: {count}")
        info, data = await download_audio_file(
            client,
            args.file_index,
            progress=ProgressPrinter(prefix="audio"),
            timeout_s=args.timeout,
        )

    bundle = save_audio_bundle(
        file_index=args.file_index,
        data=data,
        metadata={"record_time": info.record_time},
        output_path=args.output,
        pcm_config=pcm_config_from_args(args),
        quality=args.speex_quality,
        bits_size=args.speex_bits_size,
        allow_framed_blocks=args.allow_framed_blocks,
        ffmpeg_path=args.ffmpeg,
    )
    print(f"raw recording saved: {bundle.raw_path} ({bundle.raw_size} bytes)")
    print(f"decoded recording saved: {bundle.play_path} ({bundle.play_size} bytes)")
    print(f"audio format: {bundle.play_description or bundle.format_label}")
    print(f"file info: {info}")


async def cmd_audio_receive(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False)) as client:
        print("Connected. Make a recording; waiting for local save or legacy automatic upload.", flush=True)
        index, data = await receive_auto_audio_file(client, timeout_s=args.timeout)
    bundle = save_audio_bundle(file_index=index, data=data, output_path=args.output, ffmpeg_path=args.ffmpeg)
    print(f"Saved {bundle.raw_path} and {bundle.play_path}: {bundle.play_description}")


async def cmd_audio_live(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False)) as client:
        await get_device_capabilities(client, timeout_s=3.0)
        print("Subscribing to live audio. Flash retention follows the ring's recording configuration.", flush=True)
        recording = await receive_live_audio_file(
            client, timeout_s=args.timeout,
            on_subscribed=lambda: print("Subscribed. Hold the record button now; release to finish.", flush=True),
        )
    bundle = save_audio_bundle(
        file_index=recording.start.session_id, data=recording.data,
        metadata={"record_time": recording.start.record_time},
        output_path=args.output, ffmpeg_path=args.ffmpeg,
    )
    print(f"Saved {bundle.raw_path} and {bundle.play_path}: {bundle.play_description}")


async def _apply_recording_args(client: OpenZiloClient, args: argparse.Namespace):
    config = await get_audio_recording_config(client)
    changes = {}
    for name in ("channels", "bitrate", "gain_left_q8", "gain_right_q8", "max_duration_ms"):
        if getattr(args, name, None) is not None:
            changes[name] = getattr(args, name)
    if getattr(args, "destination", None) is not None:
        changes["output"] = {"auto": AudioOutput.AUTO, "flash": AudioOutput.FLASH,
                             "live": AudioOutput.LIVE, "both": AudioOutput.LIVE_AND_FLASH}[args.destination]
    if getattr(args, "disconnect", None) is not None:
        changes["disconnect_policy"] = {"stop": AudioDisconnectPolicy.STOP,
                                        "save": AudioDisconnectPolicy.CONTINUE_SAVING}[args.disconnect]
    return await set_audio_recording_config(client, replace(config, **changes)) if changes else config


async def cmd_audio_config(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False)) as client:
        await get_device_capabilities(client, timeout_s=3.0)
        print(await _apply_recording_args(client, args))


async def cmd_audio_status(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False)) as client:
        await get_device_capabilities(client, timeout_s=3.0)
        print(await get_audio_recording_status(client))


async def cmd_audio_stop(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False)) as client:
        await get_device_capabilities(client, timeout_s=3.0)
        await stop_audio_recording(client, args.session_id, cancel=args.cancel)
        print(await wait_audio_recording_finished(client, args.session_id))


async def cmd_audio_record(args: argparse.Namespace) -> None:
    if not math.isfinite(args.seconds) or not 0.02 <= args.seconds <= 60:
        raise ValueError("seconds must be 0.02..60")
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False)) as client:
        await get_device_capabilities(client, timeout_s=3.0)
        config = await _apply_recording_args(client, args)
        session = None
        stopper = None

        async def timed_stop():
            await asyncio.sleep(args.seconds)
            await stop_audio_recording(client, session)

        async def subscribed():
            nonlocal session, stopper
            session = await start_audio_recording(client)
            print(f"Recording session {session}", flush=True)
            stopper = asyncio.create_task(timed_stop())

        try:
            if config.output in (AudioOutput.LIVE, AudioOutput.LIVE_AND_FLASH):
                recording = await receive_live_audio_file(client, on_subscribed=subscribed)
                data = recording.data
            else:
                session = await start_audio_recording(client)
                print(f"Recording session {session}", flush=True)
                stopper = asyncio.create_task(timed_stop())
                await stopper
                status = await wait_audio_recording_finished(client, session)
                if status.file_index is None:
                    raise RuntimeError("Recording ended without a saved file")
                _, data = await download_audio_file(client, status.file_index)
            if stopper is not None:
                await stopper
            status = await wait_audio_recording_finished(client, session)
            print(status)
        finally:
            if stopper is not None and not stopper.done():
                stopper.cancel()
                await asyncio.gather(stopper, return_exceptions=True)
            if session is not None and client.is_connected:
                try:
                    await stop_audio_recording(client, session)
                except Exception as exc:
                    _logger.warning("Could not confirm stop of session %s; query status before reuse: %s", session, exc)
    bundle = save_audio_bundle(file_index=status.file_index if status.saved else session,
                               data=data, output_path=args.output, ffmpeg_path=args.ffmpeg)
    print(f"Saved {bundle.raw_path} and {bundle.play_path}")


async def cmd_ota_update(args: argparse.Namespace) -> None:
    # Reject corrupt or invalid input before opening a BLE session.
    data = _validate_firmware_package(args.firmware.read_bytes(), args.version, args.sha256)
    print("OTA transfer progress is not installation confirmation; keep the ring nearby.")
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False)) as client:
        await get_device_capabilities(client, timeout_s=3.0)
        info = await update_firmware(
            client, data, version=args.version, sha256=args.sha256,
            expected_model=args.model, progress=ProgressPrinter(prefix="OTA transfer"),
            timeout_s=args.timeout, total_timeout_s=args.total_timeout,
            reboot_timeout_s=args.reboot_timeout,
        )
    print(f"Firmware update verified after reboot: {info.firmware_version}")


async def cmd_audio_decode(args: argparse.Namespace) -> None:
    data = args.input.read_bytes()
    playable = build_playable_audio(
        data,
        pcm_config=pcm_config_from_args(args),
        quality=args.speex_quality,
        bits_size=args.speex_bits_size,
        allow_framed_blocks=args.allow_framed_blocks,
        ffmpeg_path=args.ffmpeg,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(playable.bytes)
    print(f"decoded recording saved: {args.output} ({len(playable.bytes)} bytes)")
    print(f"audio format: {playable.description or playable.label}")


async def cmd_audio_clear(args: argparse.Namespace) -> None:
    if not args.yes:
        raise SystemExit("Refusing to clear audio files without --yes.")

    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False)) as client:
        await clear_audio_files(client)
    print("audio files cleared")


async def cmd_log_storage(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False)) as client:
        storage = await get_log_storage(client)
    print(f"page_size: {storage.page_size}")
    print(f"total_len: {storage.total_len}")


async def cmd_log_read(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout,
                              allow_unverified_features=getattr(args, "allow_unverified_features", False)) as client:
        data = await read_log_chunk(client, args.index, args.offset, args.size)

    if args.output:
        args.output.write_bytes(data)
        print(f"wrote {len(data)} bytes to {args.output}")
        return

    if args.text:
        print(data.decode(args.encoding, errors="replace"))
    else:
        print(data.hex(" "))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OpenZilo device CLI.",
        epilog="Quick start: scan → device use ADDRESS → info → shell. See docs/cli.zh-CN.md.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    device = subparsers.add_parser("device", help="Select, show or forget the default ring.")
    device_commands = device.add_subparsers(dest="action", required=True)
    use = device_commands.add_parser("use", help="Save an address, or scan and select interactively.")
    use.add_argument("address", nargs="?", help="BLE address/UUID; omit to scan and choose.")
    use.add_argument("--timeout", type=positive_seconds, default=DEFAULT_SCAN_TIMEOUT_S)
    use.set_defaults(func=cmd_device)
    for action in ("show", "forget"):
        device_commands.add_parser(action).set_defaults(func=cmd_device)

    capabilities = device_commands.add_parser("capabilities", help="Query device contracts and limits as JSON.")
    add_connection_args(capabilities)
    capabilities.add_argument("--timeout", type=positive_seconds, default=3.0)
    capabilities.set_defaults(func=cmd_capabilities)
    doctor = subparsers.add_parser("doctor", help="Report SDK identity, device contracts and decoder availability.")
    add_connection_args(doctor)
    doctor.add_argument("--timeout", type=positive_seconds, default=3.0)
    doctor.set_defaults(func=cmd_capabilities)

    shell = subparsers.add_parser("shell", help="Interactive device terminal; help and exit are built in.")
    shell.add_argument("--address", help="Override the default device for this shell.")
    shell.set_defaults(func=cmd_shell)

    sensor = subparsers.add_parser("sensor-stream", help="Capture IMU batches as JSON lines, then stop reports.")
    add_connection_args(sensor)
    sensor.add_argument("--seconds", type=positive_seconds, default=10.0)
    sensor.add_argument("--output", type=Path, help="Write JSONL to a file instead of stdout.")
    sensor.set_defaults(func=cmd_sensor_stream)

    scan = subparsers.add_parser("scan", help="Scan nearby devices.")
    scan.add_argument("--address", default=None, help="Target device address/identifier; return as soon as found.")
    scan.add_argument("--timeout", type=positive_seconds, default=DEFAULT_SCAN_TIMEOUT_S)
    scan.set_defaults(func=cmd_scan)

    connect = subparsers.add_parser("connect", help="Connect and disconnect once.")
    add_connection_args(connect)
    connect.set_defaults(func=cmd_connect)

    info = subparsers.add_parser("info", help="Print system information.")
    add_connection_args(info)
    info.set_defaults(func=cmd_info)

    time_sync = subparsers.add_parser(
        "time-sync",
        help="Auto-respond to device time-sync requests.",
    )
    add_connection_args(time_sync)
    time_sync.add_argument("--seconds", type=float, default=30.0)
    time_sync.set_defaults(func=cmd_time_sync)

    audio_count = subparsers.add_parser(
        "audio-count",
        help="Print stored audio file count.",
    )
    add_connection_args(audio_count)
    audio_count.set_defaults(func=cmd_audio_count)

    def recording_options(command):
        command.add_argument("--destination", choices=("auto", "flash", "live", "both"))
        command.add_argument("--disconnect", choices=("stop", "save"))
        command.add_argument("--channels", type=int, choices=(1, 2))
        command.add_argument("--bitrate", type=int)
        command.add_argument("--gain-left-q8", type=int)
        command.add_argument("--gain-right-q8", type=int)
        command.add_argument("--max-duration-ms", type=int)

    audio_config = subparsers.add_parser("audio-config", help="Read/set volatile recording defaults (extended firmware).")
    add_connection_args(audio_config)
    recording_options(audio_config)
    audio_config.set_defaults(func=cmd_audio_config)

    audio_status = subparsers.add_parser("audio-status", help="Read the latest recording session state.")
    add_connection_args(audio_status)
    audio_status.set_defaults(func=cmd_audio_status)

    audio_stop = subparsers.add_parser("audio-stop", help="Stop/cancel a recording session and confirm completion.")
    add_connection_args(audio_stop)
    audio_stop.add_argument("session_id", type=int)
    audio_stop.add_argument("--cancel", action="store_true")
    audio_stop.set_defaults(func=cmd_audio_stop)

    audio_record = subparsers.add_parser("audio-record", help="Remotely record, stop and save the result.")
    add_connection_args(audio_record)
    recording_options(audio_record)
    audio_record.set_defaults(destination="flash", disconnect="stop", func=cmd_audio_record)
    audio_record.add_argument("output", type=Path)
    audio_record.add_argument("--seconds", type=float, default=5.0)
    audio_record.add_argument("--ffmpeg", default="ffmpeg")

    audio_download = subparsers.add_parser(
        "audio-download",
        help="Download one audio file.",
    )
    add_connection_args(audio_download)
    audio_download.add_argument("file_index", type=int)
    audio_download.add_argument("output", type=Path)
    audio_download.add_argument("--timeout", type=float, default=30.0)
    add_audio_decode_args(audio_download)
    audio_download.set_defaults(func=cmd_audio_download)

    for name, handler, description in (
        ("audio-receive", cmd_audio_receive, "Wait for a saved recording and download it (old/new firmware)."),
        ("audio-live", cmd_audio_live, "Receive live Opus; Flash retention follows device configuration."),
    ):
        audio_receive = subparsers.add_parser(name, help=description)
        add_connection_args(audio_receive)
        audio_receive.add_argument("output", type=Path)
        audio_receive.add_argument("--timeout", type=float, default=60.0)
        audio_receive.add_argument("--ffmpeg", default="ffmpeg")
        audio_receive.set_defaults(func=handler)

    ota = subparsers.add_parser(
        "ota-update", help="Install an official APP update package and verify the running version.",
    )
    add_connection_args(ota)
    ota.add_argument("firmware", type=Path, help="Official update package, transmitted unchanged.")
    ota.add_argument("--version", required=True, help="Target version from the release notes.")
    ota.add_argument("--sha256", help="Expected SHA-256 from the official release.")
    ota.add_argument("--model", help="Expected model string returned by the info command.")
    ota.add_argument("--timeout", type=float, default=30.0, help="Per-operation timeout in seconds.")
    ota.add_argument("--total-timeout", type=float, default=600.0, help="Overall transfer time limit.")
    ota.add_argument("--reboot-timeout", type=float, default=90.0, help="Reboot and verification time limit.")
    ota.set_defaults(func=cmd_ota_update)

    audio_decode = subparsers.add_parser(
        "audio-decode",
        help="Decode a downloaded recording bin into WAV.",
    )
    audio_decode.add_argument("input", type=Path)
    audio_decode.add_argument("output", type=Path)
    add_audio_decode_args(audio_decode)
    audio_decode.set_defaults(func=cmd_audio_decode)

    audio_clear = subparsers.add_parser(
        "audio-clear",
        help="Clear all stored audio files.",
    )
    add_connection_args(audio_clear)
    audio_clear.add_argument("--yes", action="store_true", help="Confirm clearing.")
    audio_clear.set_defaults(func=cmd_audio_clear)

    log_storage = subparsers.add_parser("log-storage", help="Print log storage info.")
    add_connection_args(log_storage)
    log_storage.set_defaults(func=cmd_log_storage)

    log_read = subparsers.add_parser("log-read", help="Read one log chunk.")
    add_connection_args(log_read)
    log_read.add_argument("index", type=int)
    log_read.add_argument("offset", type=int)
    log_read.add_argument("size", type=int)
    log_read.add_argument("--output", type=Path, default=None)
    log_read.add_argument("--text", action="store_true", help="Decode as text.")
    log_read.add_argument("--encoding", default="utf-8")
    log_read.set_defaults(func=cmd_log_read)

    return parser


async def dispatch(args: argparse.Namespace, *, fallback_address: str | None = None) -> None:
    if getattr(args, "needs_device", False):
        args.address = args.address or fallback_address or os.environ.get("OPENZILO_ADDRESS") or load_address()
        if not args.address or not args.address.strip():
            raise ValueError("No device selected. Run 'openzilo device use', set OPENZILO_ADDRESS, or pass --address.")
    await args.func(args)


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    await dispatch(args)


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130) from None
    except (OpenZiloError, OSError, ValueError, RuntimeError, EOFError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

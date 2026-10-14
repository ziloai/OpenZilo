# SPDX-License-Identifier: MPL-2.0
"""Command-line interface (python -m openzilo)."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from ._transport import DEFAULT_SCAN_TIMEOUT_S
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


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--address", required=True, help="BLE device address/identifier (macOS UUID).")
    parser.add_argument("--scan-timeout", type=float, default=DEFAULT_SCAN_TIMEOUT_S)
    parser.add_argument("--connect-timeout", type=float, default=30.0)


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
                                connect_timeout_s=args.connect_timeout)
    try:
        print(f"connected: {client.is_connected}")
    finally:
        await client.disconnect()


async def cmd_info(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout) as client:
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
                              connect_timeout_s=args.connect_timeout) as client:
        enable_time_sync(client)
        print(f"time sync auto-response enabled for {args.seconds:g}s")
        await asyncio.sleep(args.seconds)
    print("time sync session ended")


async def cmd_audio_count(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout) as client:
        count = await get_audio_file_count(client)
    print(f"audio file count: {count}")


async def cmd_audio_download(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout) as client:
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
                              connect_timeout_s=args.connect_timeout) as client:
        print("Connected. Make a recording; waiting for local save or legacy automatic upload.", flush=True)
        index, data = await receive_auto_audio_file(client, timeout_s=args.timeout)
    bundle = save_audio_bundle(file_index=index, data=data, output_path=args.output, ffmpeg_path=args.ffmpeg)
    print(f"Saved {bundle.raw_path} and {bundle.play_path}: {bundle.play_description}")


async def cmd_audio_live(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout) as client:
        print("Live-only capture: the ring will NOT save this recording to Flash. "
              "Subscribing now...", flush=True)
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


async def cmd_ota_update(args: argparse.Namespace) -> None:
    # Reject corrupt or invalid input before opening a BLE session.
    data = _validate_firmware_package(args.firmware.read_bytes(), args.version, args.sha256)
    print("OTA transfer progress is not installation confirmation; keep the ring nearby.")
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout) as client:
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
                              connect_timeout_s=args.connect_timeout) as client:
        await clear_audio_files(client)
    print("audio files cleared")


async def cmd_log_storage(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout) as client:
        storage = await get_log_storage(client)
    print(f"page_size: {storage.page_size}")
    print(f"total_len: {storage.total_len}")


async def cmd_log_read(args: argparse.Namespace) -> None:
    async with OpenZiloClient(address=args.address, scan_timeout_s=args.scan_timeout,
                              connect_timeout_s=args.connect_timeout) as client:
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
    parser = argparse.ArgumentParser(description="OpenZilo SDK tool.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Scan nearby devices.")
    scan.add_argument("--address", default=None, help="Target device address/identifier; return as soon as found.")
    scan.add_argument("--timeout", type=float, default=DEFAULT_SCAN_TIMEOUT_S)
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
        ("audio-live", cmd_audio_live, "Receive one live stereo Opus recording; the ring makes no Flash copy."),
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


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    await args.func(args)


def run() -> None:
    asyncio.run(main())

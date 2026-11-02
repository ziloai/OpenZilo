# Download and receive saved recordings

--8<-- "docs/_includes/devices.en.md"

Download recordings already stored on the device, or receive a recording after it finishes saving. See [live audio](sdk-live-audio.en.md) for streaming and [remote recording](recording-control.md) for configuration and control.

Code snippets use `import openzilo as sdk`; `ring` is a connected client. See the [quick start](sdk-quickstart.en.md) for a complete connection example.

## Download and save a recording

```text
connect -> get_audio_file_count -> download_audio_file -> save_audio_bundle
```

```python
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    count = await sdk.get_audio_file_count(ring)
    if count:
        info, raw_audio = await sdk.download_audio_file(ring, file_index=0)
        bundle = sdk.save_audio_bundle(
            file_index=info.file_index,
            data=raw_audio,
            metadata={"record_time": info.record_time},
            output_dir="audio",
        )
        print(bundle.raw_path)
        print(bundle.play_path)
```

`download_audio_file()` defaults to fast download (`quick=True`). With `quick=False`, the SDK requests each data chunk separately.

## Receive a recording after it finishes

```text
connect -> wait in receive_auto_audio_file -> hold the button to record, then release
        -> download after 0x050A on firmware `V2.001.0002.0001` / receive 0x0505 on legacy firmware -> save_audio_bundle
```

```python
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    print("Hold the ring button to record, then release")
    file_index, raw_audio = await sdk.receive_auto_audio_file(
        ring,
        timeout_s=60.0,
    )
    bundle = sdk.save_audio_bundle(
        file_index=file_index,
        data=raw_audio,
        output_dir="audio",
    )
    print(bundle.raw_path)
    print(bundle.play_path)
```

Automatic transfers from `V2.001.0002.0000` do not begin with `0x0504`, so the return value has no `AudioFileInfo`. During normal continuous reception the SDK sends no extra commands. Recovery queries file metadata, verifies the index, and bounds the result by `data_size`. Keep BLE connected and do not simultaneously call `download_audio_file()` or `read_audio_frame()` on the same connection. If you connected too late, query the file count and download by index.

## Recording transfer sequences

The SDK supports normal and fast downloads, plus automatic reception and live streaming:

| Transfer | Protocol sequence | SDK call |
| --- | --- | --- |
| Fast download | `0x0509 -> 0x0504 -> 0x0505...`; `0x0506` recovers missing data | `download_audio_file(..., quick=True)` |
| Normal download | `0x0503 -> 0x0504`, repeated `0x0506 -> 0x0505`, then `0x0507 -> 0x0508` | `download_audio_file(..., quick=False)` |
| `V2.001.0002.0000` post-save push | Consecutive `0x0505...` after saving; recovery queries `0x0504` metadata and requests `0x0506` | `receive_auto_audio_file()` |
| `V2.001.0002.0001` post-save notification | Normal download after `0x050A` | `receive_auto_audio_file()` |
| Live recording | Subscribe with `0x050D -> 0x050E`, then `0x050F -> 0x0510... -> 0x0511` | `receive_live_audio_file()` |

Low-level normal-download functions `get_audio_file_info()`, `read_audio_frame()` and `end_audio_extract()` are mainly for debugging.

## `download_audio_file()`

Purpose: download a complete recording by index.

Signature:

```python
info, raw_audio = await download_audio_file(
    client,
    file_index,
    progress=None,
    timeout_s=None,
    quick=True,
)
```

Returns: `tuple[AudioFileInfo, bytes]`.

Example:

```python
info, raw_audio = await sdk.download_audio_file(
    ring,
    file_index=0,
    progress=sdk.ProgressPrinter(prefix="audio"),
)
```

`file_index` starts at `0`. Query `get_audio_file_count()` first to avoid requesting a missing recording.

## `receive_auto_audio_file()`

Purpose: obtain a complete recording immediately after saving. On `0x050A`, the SDK performs a normal download and sends `0x0507` to release the file. Legacy firmware instead pushes `0x0505`, with metadata queried only for recovery. Both return the original file for automatic encoding detection by `save_audio_bundle()`.

Signature:

```python
file_index, raw_audio = await sdk.receive_auto_audio_file(
    ring,
    timeout_s=60.0,
)
```

Arguments:

- `client`: connected `OpenZiloClient`, named `ring` in the examples.
- `timeout_s`: maximum seconds for each data arrival; `None` uses client `command_timeout_s`.

Returns: `tuple[int, bytes]`.

- The first value is the file index from `0x050A` or the first valid `0x0505`.
- The second is raw audio reconstructed by `frame_offset`, ready for `save_audio_bundle()`.
- Legacy push has no initial `0x0504`, so no `AudioFileInfo` is returned. Recovery metadata is used only for integrity and length checks.

Reception behavior:

- The first frame selects the file index; frames belonging to other files are excluded.
- Duplicate and overlapping bytes are removed by offset.
- For gaps, post-first-frame timeouts or damaged frames, the SDK queries and validates file index and exact `data_size`, then requests the expected offset with `0x0506`.
- Normal reception returns at `is_end=True`. Recovered data is truncated to `data_size` without extra bytes.

Exceptions:

- No initial frame before timeout: `TimeoutError`.
- An unrecoverable gap, mismatched metadata index, or invalid frame fields: `ProtocolError`.
- Nonzero device error: `DeviceError`.
- Disconnected before the call or during the wait: `TransportError`.

Do not run concurrently with `download_audio_file()`, `read_audio_frame()` or other direct `0x0505` waiters. Run recording reception sequentially on a connection. If connection began too late for the push, use `get_audio_file_count()` and `download_audio_file()`.

Saving example:

```python
file_index, raw_audio = await sdk.receive_auto_audio_file(ring, timeout_s=60.0)
bundle = sdk.save_audio_bundle(
    file_index=file_index,
    data=raw_audio,
    output_dir="audio",
)
```

## `clear_audio_files()`

Purpose: delete every recording on the device.

```python
await sdk.clear_audio_files(ring)
```

This is irreversible. Applications should require explicit confirmation or an environment-specific safeguard.

## Read information, download the first recording, and save it

```python
import asyncio
import openzilo as sdk

ADDRESS = "AA:BB:CC:DD:EE:FF"


async def main() -> None:
    async with sdk.OpenZiloClient(address=ADDRESS) as ring:
        sdk.enable_time_sync(ring)

        info = await sdk.get_system_info(ring)
        print("system:", info)

        count = await sdk.get_audio_file_count(ring)
        print("audio count:", count)
        if count == 0:
            return

        audio_info, raw_audio = await sdk.download_audio_file(
            ring,
            file_index=0,
            progress=sdk.ProgressPrinter(prefix="audio"),
        )

    bundle = sdk.save_audio_bundle(
        file_index=audio_info.file_index,
        data=raw_audio,
        metadata={"record_time": audio_info.record_time},
        output_dir="audio",
    )
    print("raw:", bundle.raw_path)
    print("play:", bundle.play_path)


if __name__ == "__main__":
    asyncio.run(main())
```

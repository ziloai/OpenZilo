# Remote recording and configuration

--8<-- "docs/_includes/devices.en.md"

Start and stop recordings with Python or the CLI, and configure channels, bitrate, gain and maximum duration. Audio can be saved on the ring, streamed to the computer, or both.

--8<-- "docs/_includes/features.en.md:recording-control"

## Record with the CLI

--8<-- "docs/_includes/firmware-0001.en.md"

Select a device, then record five seconds and download it:

```bash
uv run openzilo device use
uv run openzilo audio-record recordings/test.wav --seconds 5 --channels 1
```

WAV output requires `ffmpeg`. Inspect settings and recording status:

```bash
uv run openzilo audio-config
uv run openzilo audio-status
```

See the [CLI guide](cli.en.md) for all commands.

## Record and save with Python

--8<-- "docs/_includes/firmware-0001.en.md"

Replace `ADDRESS` with the scanned address. This example stores five seconds on the ring, waits for saving, and downloads the completed recording:

```python
import asyncio
import openzilo as sdk

ADDRESS = "AA:BB:CC:DD:EE:FF"

async def main():
    ring = await sdk.connect_ring(address=ADDRESS)
    try:
        if not ring.capabilities.supports("recording_control"):
            print("No compatible remote recording interface is available")
            return
        config = sdk.AudioRecordingConfig(
            output=sdk.AudioOutput.FLASH,
            channels=1,
            bitrate=16000,
            max_duration_ms=5000,
        )
        await sdk.set_audio_recording_config(ring, config)
        session_id = await sdk.start_audio_recording(ring)
        status = await sdk.wait_audio_recording_finished(ring, session_id)
        if status.saved:
            info, data = await sdk.download_audio_file(ring, status.file_index)
            bundle = sdk.save_audio_bundle(
                file_index=info.file_index, data=data, output_dir="recordings",
            )
            print(bundle.play_path)
    finally:
        await ring.disconnect()

asyncio.run(main())
```

## Change recording settings

--8<-- "docs/_includes/firmware-0001.en.md"

Read with `get_audio_recording_config()` and write with `set_audio_recording_config()`. Changes are allowed only while idle, survive reconnection and reset on reboot.

| Setting | Argument | Values/range |
| --- | --- | --- |
| Output | `output` | `AUTO` automatic, `FLASH` save on device, `LIVE` stream, `LIVE_AND_FLASH` stream and save |
| Channels | `channels` | 1 or 2 |
| Bitrate | `bitrate` | 8000–32000 bit/s |
| Digital gain | `gain_left_q8`, `gain_right_q8` | 0–1024; 256 means 1x |
| Maximum duration | `max_duration_ms` | 20–60000 ms in multiples of 20 |
| Disconnect handling | `disconnect_policy` | `STOP` or `CONTINUE_SAVING` on device |

Sample rate is fixed at 16 kHz with 20 ms frames. The device also reports allowed ranges, checked by the SDK before writing. Other fixed Opus parameters can be read but not changed through this API.

`CONTINUE_SAVING` requires `FLASH` or `LIVE_AND_FLASH`.

## Stop early or cancel

--8<-- "docs/_includes/firmware-0001.en.md"

`start_audio_recording()` returns the recording `session_id`, not completion. To stop early:

```python
await sdk.stop_audio_recording(ring, session_id)
status = await sdk.wait_audio_recording_finished(ring, session_id)
```

Pass `cancel=True` to discard an uncommitted recording. A stop response does not establish that a file was saved; query or wait for completion.

If START times out, query `get_audio_recording_status()` instead of repeating START. Session IDs last only for the current device boot and cannot be reused after reboot.

## Stream with a device copy

--8<-- "docs/_includes/firmware-0001.en.md"

For `LIVE` or `LIVE_AND_FLASH`, subscribe before starting. Call `start_audio_recording()` from `receive_live_audio_file()`'s `on_subscribed` callback. See [remote_recording.py](../examples/remote_recording.py).

Interrupted live audio cannot resume across connections. With simultaneous saving, the device copy can be downloaded after saving finishes. Live-only disconnect fails that transfer.

## API quick reference

--8<-- "docs/_includes/firmware-0001.en.md"

| API | Result |
| --- | --- |
| `get_audio_recording_config(ring)` | Current `AudioRecordingConfig`. |
| `set_audio_recording_config(ring, config)` | Configuration read back from the device. |
| `start_audio_recording(ring)` | Recording `session_id`. |
| `stop_audio_recording(ring, session_id, cancel=False)` | Session ID confirmed by the device. |
| `get_audio_recording_status(ring)` | `AudioRecordingStatus`, including state, saved flag, file index and error. |
| `wait_audio_recording_finished(ring, session_id, timeout_s=75.0, poll_interval_s=0.2)` | Final status; raises for a failed recording. |

All APIs above are asynchronous. Except the completion waiter, they accept `timeout_s` for a single request timeout.

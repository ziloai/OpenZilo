# Exceptions and troubleshooting

--8<-- "docs/_includes/devices.en.md"

Identify the failure from its exception, then check the connection, device state and call order.

## Exceptions

```python
OpenZiloError
# SDK base exception; catch this to handle all SDK failures together.

TransportError
# BLE transport failure: missing bleak, device not found, connection failure, writes while disconnected, or disconnect while waiting.

ProtocolError
# Invalid protocol header, CRC, length or response body.

TimeoutError
# Request queue, write, response or unsolicited-event timeout. Reconnect if a write was interrupted.

DeviceError
error_code: int  # Nonzero device error code.
# Explicit device error, such as busy, invalid argument or missing file.

AudioDecodeError
# Audio cannot be decoded to playable WAV, or ffmpeg exceeds 30 seconds.

SpeexDecoderUnavailable
# ffmpeg is missing or a custom Speex decoder is unavailable.

OpusDecoderUnavailable
# ffmpeg is missing, preventing OP2C decoding.
```

## `TransportError: Install bleak to use BLE transport`

The current Python environment lacks SDK dependencies, often because the script used a different Python environment. In your project, install the SDK from GitHub:

```powershell
uv add git+https://github.com/ziloai/OpenZilo.git
uv run python your_script.py
```

## Cannot discover or connect to a device

- Use the scanned address, or UUID on macOS; the SDK does not filter by advertising name.
- Ensure the ring is advertising and no other application holds its connection.
- On Windows, try toggling Bluetooth.
- In PyCharm, ensure the interpreter uses the environment containing the dependencies.

## `Timed out waiting for command ...`

The requested response or event did not arrive before timeout. Common causes:

- Busy device: recording, writing flash or transferring a large file.
- Concurrent commands take responses expected by other tasks.
- Gesture mode was not entered on `V2.001.0002.0000`, or IMU capture was not started on `V2.001.0002.0001`.

Prefer one request/response operation at a time on each connection.

## `receive_auto_audio_file()` times out

An initial timeout means no post-save `0x050A` or pushed `0x0505` arrived in time. Keep BLE connected and start waiting before asking the user to hold and release the recording button. If connection began too late, query the count and download by index.

Do not run `receive_auto_audio_file()` with `download_audio_file()`, `read_audio_frame()` or direct `wait_for_command(0x0505)` calls. Run recording reception sequentially on a connection to avoid timeouts or incomplete data.

## `start_sensor_report()` reports device busy

Finish conflicting operations. Enter gesture mode with the button on `V2.001.0002.0000`; call `start_sensor_report()` directly on `V2.001.0002.0001`. Wait for a successful response before receiving data.

## Download succeeds but decoding fails

Check that `ffmpeg -version` runs. To keep raw audio only, preserve the returned `bytes` or the raw file written by `save_audio_bundle()`.

## Can deleted recordings be recovered?

`clear_audio_files()` deletes all stored recordings, with no SDK recovery. Put it behind an explicit maintenance or test action, never in ordinary startup code.

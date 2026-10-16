# Recording control

Experimental support for remote recording control and audio configuration. Requires firmware implementing commands `0x0512`–`0x051B`; protocol v4 alone does not imply support. Hardware validation is pending.

Import the public API from `openzilo`. With an already connected client named `ring`:

```python
import openzilo as sdk

await sdk.set_audio_recording_config(ring, sdk.AudioRecordingConfig(
    output=sdk.AudioOutput.FLASH,
    channels=1,
    bitrate=16000,
    max_duration_ms=5000,
))
session = await sdk.start_audio_recording(ring)
status = await sdk.wait_audio_recording_finished(ring, session)
if status.saved:
    info, data = await sdk.download_audio_file(ring, status.file_index)
```

Use `stop_audio_recording(ring, session)` to stop early, or pass `cancel=True` to discard an uncommitted recording. A stop acknowledgment does not confirm file completion. If a START acknowledgment is lost, query `get_audio_recording_status()` instead of blindly retrying START. Session IDs are scoped to one device boot.

`AudioRecordingConfig` supports AUTO, FLASH, LIVE, and LIVE_AND_FLASH; one or two channels; 8–32 kbps; left/right digital Q8 gains (256 = unity); and a 20–60000 ms limit in 20 ms increments. The sample rate and frame duration remain fixed at 16 kHz and 20 ms. Changes are allowed only while idle, survive reconnection, and reset on reboot.

LIVE and LIVE_AND_FLASH require a live subscription before START. Use the `on_subscribed` callback in [remote_recording.py](../examples/remote_recording.py) to register the receiver first. CONTINUE_SAVING requires FLASH or LIVE_AND_FLASH; live delivery does not resume across connections. A live-only disconnect is a failure, while explicit unsubscription cancels the live session. A successful local backup remains independently available.

CLI examples (replace the placeholder address):

```sh
openzilo audio-config --address AA:BB:CC:DD:EE:FF
openzilo audio-record --address AA:BB:CC:DD:EE:FF --seconds 5 --channels 1 recording.wav
openzilo audio-status --address AA:BB:CC:DD:EE:FF
openzilo audio-stop --address AA:BB:CC:DD:EE:FF 1
```

Query the current session before using `audio-stop`; `1` is illustrative. Both OP2C files and live PCM support mono/stereo. Confirm completion with `get_audio_recording_status()` or `wait_audio_recording_finished()` before starting OTA.

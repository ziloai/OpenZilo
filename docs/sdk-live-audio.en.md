# Live audio

--8<-- "docs/_includes/devices.en.md"

Receive live Opus or PCM from button-triggered recordings. Use `connect_ring()` to connect and discover features, or call `get_device_capabilities()` after connecting an `OpenZiloClient`. Event fields are listed in [data types](sdk-data-types.en.md).

Code snippets use `import openzilo as sdk`; `ring` is a connected client. See the [quick start](sdk-quickstart.en.md) for a complete connection example.

## Receive live recordings

--8<-- "docs/_includes/firmware-0001.en.md"

```text
connect -> subscribe with receive_live_audio_file -> hold the button, then release
        -> device streams Opus audio -> SDK unsubscribes -> save_audio_bundle
```

```python
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    await sdk.get_device_capabilities(ring)
    recording = await sdk.receive_live_audio_file(
        ring,
        on_subscribed=lambda: print("Hold the ring button to record, then release"),
    )
    bundle = sdk.save_audio_bundle(
        file_index=0,
        data=recording.data,
        output_dir="audio",
    )
    print(bundle.play_path)
```

Live recording requires firmware **V2.001.0002.0001 or later**. Live-only recordings are not stored and cannot be recovered after disconnection or loss. Simultaneous saving provides a device copy to download after saving finishes. Wait for `on_subscribed` before asking the user to record.

## `open_live_audio_stream()`: PCM / Opus events

--8<-- "docs/_includes/features.en.md:live-audio"

Install PCM decoding dependencies with `uv add "openzilo[pcm] @ git+https://github.com/ziloai/OpenZilo.git"`. PyAV decodes in-process, without an `ffmpeg` executable. `output="opus"` needs only the base SDK.

```python
async with sdk.open_live_audio_stream(
    ring,
    output="pcm",             # Default; "opus" is also available
    queue_size=64,
    timeout_s=60.0,
    recording_timeout_s=70.0,
) as stream:
    print("Subscribed; hold the recording button now")
    async for event in stream:
        if isinstance(event, sdk.LiveAudioStart):
            print(event.sample_rate, event.channels)
        elif isinstance(event, sdk.LivePcmFrame):
            # data is 16 kHz, 16-bit little-endian PCM; see event.pcm_config for channels.
            # Pass audio to another task for speech recognition or playback.
            application_queue.put_nowait(event)
        elif isinstance(event, sdk.LiveAudioEnd):
            print("Complete recording", event.sent_bytes)
```

Create `application_queue` in your application and read it promptly from another task; downstream handling is omitted here. If it fills, stop reception or handle it according to application needs. Do not run slow synchronous processing in the receive loop. Keep the `async with` block for cleanup on cancellation, `break` or exception. No extra `0x050F`–`0x0511` listeners are needed.

Events arrive in this order:

| Event | Meaning |
| --- | --- |
| `LiveAudioStart` | `session_id`, device recording time, `sample_rate=16000`, `channels=1` or `2`, and `codec=3`. |
| `LivePcmFrame` | PCM mode: `session_id`, `sample_offset`, `sample_count=320`, `data`, and `pcm_config` containing the actual channels, 16 kHz rate and 16-bit depth. |
| `LiveAudioData` | Opus mode: `session_id`, `sequence`, compressed `byte_offset`, and original Opus `data`. |
| `LiveAudioEnd` | Validated packet and byte counts at recording end. PCM mode drains the decoder first. |

`sample_offset` starts at 0 and advances by 320 per frame, measured per channel. Divide by 16000 for audio-relative time, not host reception time. Mono frames contain 640 bytes; stereo frames 1280, without WAV headers. Channel count matches the device, with no denoising or mixing. `stream.start` is available after START; `stream.end` and `stream.complete` are set only after final validation and decoder drain.

Entering the context waits only for subscription confirmation. `timeout_s` limits subscription and waiting for START separately. `recording_timeout_s` limits reception after START; inter-packet waits are capped at five seconds. A recording is at most 60 seconds and a stream receives one recording; open a new context for the next one.

The application event queue holds 64 events by default. The raw notification queue holds 256 packets by default, configured by client `receive_queue_size`. Slow consumption or notification backlog raises `ProtocolError`; queues do not grow indefinitely or silently drop frames. Decoder state also uses memory. These local buffers cannot throttle the device.

Only a validated `LiveAudioEnd` confirms a complete recording. PCM already delivered can be followed by loss, disconnect, invalid END or decoding failure. Distinguish partial audio from a complete recording. Cancellation and early exit produce no successful END. Empty recordings may contain START and END without audio frames.

Missing PyAV or decoder initialization failure raises `OpusDecoderUnavailable` before subscription; decoding failure raises `AudioDecodeError`. Other protocol, device, timeout and transport exceptions match file reception. Context exit attempts unsubscribe; on failure it logs a warning. Reconnect before more audio or OTA operations. A stream cannot be reused or read by concurrent tasks.

Cancellation partway through a BLE write makes the client reject further writes to avoid leaving a partial protocol packet. Unsubscribe may also fail; reconnect. The SDK does not report this as successful cleanup.

See [examples/live_pcm.py](../examples/live_pcm.py) for a complete example.

## `receive_live_audio_file()`

--8<-- "docs/_includes/firmware-0001.en.md"

Purpose: subscribe, receive one button-triggered live recording, then unsubscribe. Requires firmware **V2.001.0002.0001 or later**.

Signature:

```python
recording = await sdk.receive_live_audio_file(
    ring,
    on_packet=None,
    on_subscribed=None,
    timeout_s=60.0,
    recording_timeout_s=70.0,
)
```

Arguments:

- `on_subscribed`: called when the device confirms subscription; use it to prompt recording.
- `on_packet`: called for each validated `LiveAudioData`, containing original Opus bytes. Whole-recording completeness is confirmed only when the function returns.
- `timeout_s`: maximum seconds for subscription and waiting for recording start.
- `recording_timeout_s`: total limit from START to END, with at most five seconds between packets.

Callbacks may be synchronous or asynchronous and should return quickly. The function assembles received Opus into a complete file. Slow callbacks can fill the bounded queue and fail reception; slow synchronous callbacks also block the event loop. For PCM, use `open_live_audio_stream(output="pcm")`.

Returns `LiveAudioRecording`; its `data` is a complete OP2C file accepted by `save_audio_bundle()` or `decode_audio_to_wav()`.

Exceptions:

- Rejected subscription, such as insufficient ATT MTU, or an END error code: `DeviceError`.
- Inconsistent session, sequence, offsets, END counts or device-reported drops: `ProtocolError`.
- BLE disconnect while waiting: `TransportError`.

Notes:

- Live-only mode **does not store recordings on the device**. Simultaneous saving permits downloading the device copy after completion.
- The function attempts unsubscribe on exit, including error and cancellation. If a complete recording is received but unsubscribe fails, it still returns the recording and logs an `openzilo` warning. Reconnect before downloads or firmware updates.
- Do not combine a live subscription with downloads, `receive_auto_audio_file()` or OTA.

Low-level `set_live_audio_subscription(client, enabled)` only toggles subscription; handle `0x050F`–`0x0511` yourself. Disabling it aborts live transmission, and disconnect clears the subscription.

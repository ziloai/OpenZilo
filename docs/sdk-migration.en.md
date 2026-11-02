# Version migration and firmware differences

--8<-- "docs/_includes/devices.en.md"

Check API changes when upgrading the SDK and discover features again after changing firmware. SDK and firmware have separate version numbers; version ordering alone does not determine compatibility.

## BLE write chunks and migration from 0.3.x

BLE fragmentation is handled automatically; applications do not configure fragment lengths.

Since `0.4.0`, `NusClient` no longer accepts `write_chunk_size`. Remove it from custom transport code using `0.3.x`:

```python
# Old 0.3.x usage, no longer supported
# transport = sdk.NusClient(address=ADDRESS, write_chunk_size=20)

# 0.4.0
transport = sdk.NusClient(address=ADDRESS)
ring = sdk.OpenZiloClient(transport=transport)
```

## Differences between firmware implementations

When upgrading from `V2.001.0002.0000` to `V2.001.0002.0001`, update your application for these changes:

- **Remote recording and settings**: `V2.001.0002.0001` adds start, stop, status and configuration of channels, bitrate, gain and duration. `V2.001.0002.0000` has none of these APIs.
- **Live audio**: `V2.001.0002.0001` adds live Opus output, which the SDK can decode to PCM. `V2.001.0002.0000` transfers files after recording is saved.
- **Recording format**: `V2.001.0002.0000` uses Speex. New recordings in `V2.001.0002.0001` use mono/stereo Opus (OP2C), with stereo as the default. The SDK still decodes existing Speex files.
- **Save notification**: `V2.001.0002.0000` pushes `0x0505` after saving. `V2.001.0002.0001` notifies with `0x050A`, followed by file download. Continue using `receive_auto_audio_file()` for both.
- **IMU**: `V2.001.0002.0000` requires gesture mode first. `V2.001.0002.0001` starts capture on `0x0601` and stops on `0x0603` or disconnect. Subscribe again after reconnecting.
- **Button and tap events**: `V2.001.0002.0001` removes recording/gesture mode switching; single presses only report events. Tap detection runs with the IMU subscription instead of maintaining separate background capture.

See [remote recording](recording-control.md), [live audio](sdk-live-audio.en.md), [IMU](sdk-imu.en.md) and [events](sdk-events.en.md) for SDK usage.

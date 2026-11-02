# OpenZilo SDK data flow

--8<-- "docs/_includes/devices.en.md"

--8<-- "docs/_includes/features.en.md:device-basics"

This page explains receiving device data, saving recordings and converting audio. See the [API index](python-sdk.en.md) for calls and the [protocol reference](protocol.en.md) for wire layouts.

## Connections and packets

Use `connect_ring()` to connect and discover features. With `OpenZiloClient`, explicitly query features as described in [compatibility](compatibility.en.md). Connections use device addresses, or UUIDs on macOS.

BLE notification boundaries are not protocol packet boundaries. SDK APIs return complete responses or events; custom transports can use `PacketStream` to reconstruct packets. Invalid headers, CRC or fields raise `ProtocolError`; disconnection during a wait raises `TransportError`.

## Live audio

--8<-- "docs/_includes/firmware-0001.en.md"

`open_live_audio_stream()` manages subscription with `async with` and yields recording start, audio and end events through `async for`. Subscription does not start recording; use the button or a remote command. Exiting attempts to unsubscribe.

PCM output is 16 kHz signed 16-bit little-endian data, with 320 samples per channel per frame and interleaved left/right stereo. Opus output preserves compressed packets. Process events promptly; slow consumption fails explicitly.

Only a validated end event confirms a complete recording. Lost live-only audio cannot be retransmitted; simultaneous saving provides a device copy to download after saving finishes. Do not download or update firmware concurrently with live reception. See [live audio](sdk-live-audio.en.md).

## Recording formats

!!! note "Firmware version"

    OP2C mono/stereo Opus recordings are available starting with **V2.001.0002.0001**. Decoding existing Speex files does not require a firmware upgrade.

Firmware `V2.001.0002.0000` stores consecutive Speex frames; `V2.001.0002.0001` stores mono/stereo OP2C. Firmware upgrades do not convert existing files, so both can coexist. The SDK detects encoding from contents, not firmware versions or filename extensions.

Each Speex frame has a two-byte little-endian payload length:

```text
[length:u16 little-endian][Speex payload:length bytes]
[length:u16 little-endian][Speex payload:length bytes]
...
```

For example, `14 00` means 20 payload bytes. Read each length rather than splitting at fixed 20-byte boundaries. Speex Wideband frames contain 320 mono samples at 16 kHz (20 ms). Default decoded PCM is 16 kHz mono 16-bit.

OP2C starts with a 12-byte little-endian header followed by length-prefixed Opus packets:

```text
magic:"OP2C" | version:u16=1 | channels:u16=1 or 2 | sample_rate:u16=16000 | frame_samples:u16=320
[length:u16 little-endian][Opus payload:length bytes]
...
```

Each Opus packet carries 20 ms at 16 kHz with the header's channels, in 1–100 bytes. A recording has at most 3000 packets (60 seconds), without trailing padding or terminators.

Join `0x0505.data` by `frame_offset`. The file data excludes device file-management metadata; `AudioFileInfo.data_size` is its byte count. For Speex, data starts with the first length field. SDK `.bin` output preserves the original format for later decoding.

## Recording transfer and saving

`download_audio_file()` downloads saved recordings. `receive_auto_audio_file()` waits for a save notification or a legacy post-save transfer. Pass the returned audio to `save_audio_bundle()`. OP2C files from live reception use the same saving and decoding APIs.

For automatic reception, connect and start waiting before recording finishes. If a transfer was missed, query the recording count and download the saved file. Run downloads, automatic reception and live reception sequentially on a connection. See [recording downloads](sdk-downloads.en.md).

## Audio conversion

`save_audio_bundle()` preserves the raw `.bin` and attempts to produce WAV. Converting saved Speex/OP2C requires `ffmpeg`; live PCM requires the optional `pcm` dependency. Raw files remain available if decoding fails.

| File or data | Content | Playback |
| --- | --- | --- |
| `.bin` | Speex frames or OP2C | Convert with the SDK |
| `.spx` / `.ogg` | Ogg Speex audio | Use a compatible player |
| PCM | Samples without a container | Specify rate, bit depth and channels |
| `.wav` | Playable audio file | Use a standard player |

Changing an extension does not convert a format. OP2C decoding follows the header's channel count. See [audio decoding](sdk-audio-decoding.en.md) for parameters and errors.

## IMU and motion events

`start_sensor_report()` enables reporting, `wait_sensor_data()` receives samples and `stop_sensor_report()` stops it. Firmware `V2.001.0002.0000` requires gesture mode first; `V2.001.0002.0001` starts capture directly, stops on disconnect and requires subscription again after reconnecting.

IMU and tap events use milliseconds since boot. Button events use device seconds, although the SDK field is still named `timestamp_ms`. Do not compare these time domains directly. See [IMU](sdk-imu.en.md) and [events](sdk-events.en.md).

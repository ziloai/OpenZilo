# OpenZilo SDK architecture and data flow

--8<-- "docs/_includes/devices.en.md"

--8<-- "docs/_includes/features.en.md:device-basics"


This page explains BLE and recording processing in the current SDK. See the [ring guide](../wiki/Home.md) for device operations and [feature requirements](features.en.md) for firmware requirements.

It covers receiving data, downloading files and producing WAV. Function signatures and examples are in the [API index](python-sdk.en.md); commands and fields are in the [protocol reference](protocol.en.md).

## Module organization

Applications import public names from `openzilo.__all__`. Implementation modules are private and underscore-prefixed:

| Module | Responsibility |
| --- | --- |
| `_errors` | Exceptions and device error codes. |
| `_protocol` | V4 headers, CRC, command numbers and binary I/O. |
| `_transport` | Bleak-based NUS discovery, connection and chunked writes. |
| `_client` | `OpenZiloClient` request matching and packet dispatch. |
| `_tasks` | Asyncio deadline and background callback helpers. |
| `_device` | Scanning, connections, system information, logs and time synchronization. |
| `_ota` | Application firmware updates. |
| `_compatibility` | Feature discovery, interface version and recording parameter checks. |
| `_recording` | Remote recording, status and configuration. |
| `_identity`, `_version` | SDK version and source checksum. |
| `_audio` | Stored recording queries, download and automatic reception. |
| `_live_audio` | Live recording subscription and reception. |
| `_codec` | Speex, OP2C and WAV conversion. |
| `_pcm` | Optional stateful PyAV Opus decoding and PCM framing, independent of BLE. |
| `_sensor` | IMU reporting and motion events. |
| `_cli` | `python -m openzilo` CLI. |

`_errors` and `_protocol` do not depend on BLE. `_codec` is also independent of connections and can process files offline.

### Live audio streams

--8<-- "docs/_includes/firmware-0001.en.md"

`open_live_audio_stream()` manages subscription and cleanup with an async context, yielding START, audio frames and END for one recording. Context entry confirms subscription; users still trigger recording with the button. One task reads the stream. Context exit aborts unfinished reception and attempts unsubscribe.

```text
BLE notifications -> bounded _PacketInbox -> background receiver: session, sequence and offset checks
                                        -> Opus events
                                        -> optional stateful decode/resample -> 20 ms PCM
                                        -> bounded event queue -> application async for
```

The receiver exclusively owns audio operations, excluding downloads, other receivers and OTA. Client `receive_queue_size` controls the raw queue (default 256); stream `queue_size` controls output events (default 64). Both report overflow errors instead of dropping data silently. Pausing local consumption cannot stop the ring from transmitting.

The optional `pcm` extra supplies PyAV. Each recording creates a stateful decoder/resampler and processes packets sequentially in a worker thread. Output is 16 kHz signed 16-bit little-endian PCM, 320 samples per channel per frame. Channel count follows the recording, with stereo interleaved L/R. After valid END, the resampler drains and total samples are checked. No per-packet files or ffmpeg processes are created.

Streaming does not accumulate an entire recording. `receive_live_audio_file()` reads the same validated Opus events and assembles OP2C. Only a checked END establishes completeness; live-only data lost after an error cannot be recovered from flash.

## From BLE notifications to SDK APIs

```text
Ring Nordic UART Service
  ↓  BLE notifications / characteristic writes
NusClient                 scan, connect, subscribe, chunk writes
  ↓
PacketStream              reconstruct v4 packets, check header and CRC
  ↓
OpenZiloClient            dispatch responses and events by command
  ↓
get_system_info() / download_audio_file() / wait_sensor_data() ...
```

`NusClient` uses `bleak` and connects by address, without relying on advertising names. NUS RX writes contain at most 20 bytes per chunk; system MTU negotiation remains enabled. Ring TX notifications have no matching 20-byte guarantee.

`PacketStream.feed()` accepts arbitrary notification sizes, including partial or consecutive packets. It uses `body_length` to extract packets and skips bytes before the magic marker. Invalid headers, CRC or lengths raise `ProtocolError`. Bodies are limited to 5120 bytes.

`OpenZiloClient` maintains per-command queues. `request()` serializes calls expecting the same response, drains stale queued packets, sends and waits. `wait_for_command()` receives events such as `0x0605`. Long-lived listeners use `add_packet_handler()`, as time synchronization does. Queue capacity defaults to 256; overflow clears backlog and raises `ProtocolError`. Callback-only handlers use `queue_packets=False` for exclusive delivery without queue copies. BLE disconnect during waits raises `TransportError`.

### Protocol v4 packet boundaries

The fixed header is 11 bytes:

```text
magic:u8=0x3F | version:u16=4 | command:u16 | body_length:u32 | body_crc:u16 | body
```

Header and body integers are big-endian. CRC16 covers `body` only and is 0 for an empty body. `BinaryReader` and `BinaryWriter` handle these fields. Speex frame lengths are separate two-byte little-endian file fields, not protocol headers. See the [protocol reference](protocol.en.md).

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

For example, `14 00` means 20 payload bytes. Read each length rather than splitting at fixed 20-byte boundaries. Speex Wideband frames contain 320 mono samples at 16 kHz (20 ms). Individual packets are limited to 540 bytes; default decoded PCM is 16 kHz mono 16-bit.

OP2C starts with a 12-byte little-endian header followed by length-prefixed Opus packets:

```text
magic:"OP2C" | version:u16=1 | channels:u16=1 or 2 | sample_rate:u16=16000 | frame_samples:u16=320
[length:u16 little-endian][Opus payload:length bytes]
...
```

Each Opus packet carries 20 ms at 16 kHz with the header's channels, in 1–100 bytes. A recording has at most 3000 packets (60 seconds), without trailing padding or terminators.

Join `0x0505.data` by `frame_offset`. The file data excludes device file-management metadata; `AudioFileInfo.data_size` is its byte count. For Speex, data starts with the first length field. SDK `.bin` output preserves the original format for later decoding.

## Recording transfers

| Entry point | Device interaction | SDK API |
| --- | --- | --- |
| Normal extraction | `0x0503 → 0x0504` metadata, repeated `0x0506 → 0x0505` by offset, then `0x0507 → 0x0508` | `download_audio_file(..., quick=False)` |
| Fast extraction | `0x0509 → 0x0504`, then consecutive `0x0505` | `download_audio_file(..., quick=True)`, default |
| `V2.001.0002.0000` post-save push | Consecutive `0x0505`, without initial `0x0504` | `receive_auto_audio_file()` |
| `V2.001.0002.0001` post-save notification | Device sends `0x050A`; SDK downloads normally | `receive_auto_audio_file()` |
| Live recording | Subscribe `0x050D → 0x050E`; button recording sends `0x050F`, consecutive `0x0510`, then `0x0511` | `receive_live_audio_file()` |

Each `0x0505` has a file index and offset. Assembly skips duplicate overlap. Gaps or timeouts in fast transfer trigger `0x0506` recovery; more than three unsuccessful recovery attempts raise `ProtocolError`. Output is truncated to `data_size`. Device data chunks are at most 4096 bytes; SDK bodies are limited to 5120.

Legacy push happens after saving, with no initial extraction request. `receive_auto_audio_file()` selects the first frame's index and returns `(file_index, raw_audio)`. For missing data it queries metadata, checks file length and recovers by offset, failing rather than returning incomplete audio.

The `0x050A` save notification carries a file index. The SDK performs normal extraction and sends `0x0507` to release the file, including on errors.

Live-only audio is not stored and cannot be retransmitted. Simultaneous saving permits downloading a completed device copy. Live reception validates session, sequence, offsets and END counts, rejecting incomplete audio. It packages Opus as OP2C for the same decoding path used by downloaded files.

Connect before automatic transmission begins. `receive_auto_audio_file()`, `download_audio_file()` and `read_audio_frame()` share `0x0505`; concurrent use is rejected with `ProtocolError`. If push was missed, query the count and download by index.

## From Speex / Opus to WAV

```text
Speex: .bin -> read frame lengths -> Speex payload -> temporary Ogg Speex
            -> ffmpeg s16le PCM -> add RIFF/WAV header -> .wav
OP2C:  .bin -> validate header and packet lengths -> Opus -> temporary Ogg Opus
            -> ffmpeg 16 kHz mono/stereo s16le PCM -> add RIFF/WAV header -> .wav
```

OP2C decoding follows its header's channel count; a caller-supplied `pcm_config` cannot override it. Missing ffmpeg raises `OpusDecoderUnavailable` on the Opus path.

`save_audio_bundle()` writes raw `.bin` first, then attempts WAV. The raw file survives missing ffmpeg or decode failure, reported as `SpeexDecoderUnavailable`, `OpusDecoderUnavailable` or `AudioDecodeError`.

`build_playable_audio()` returns existing WAV unchanged and recognizes Ogg Speex or raw Speex without lengths. `source_type` may be `wav`, `ogg-speex`, `packet-speex` or `raw-speex`; OP2C returns `opus-mono` or `opus-stereo`. Only raw-Speex fallback uses `quality` and `bits_size`: quality 3 estimates 20-byte frames, while explicit `bits_size` overrides that estimate.

For legacy 1026-byte outer blocks, pass `allow_framed_blocks=True`. Low-level `parse_packetized_speex_stream()` allows them by default; higher-level decoding and saving APIs require explicit opt-in.

`build_ogg_speex()` constructs a temporary container with `speex-1.2.1`, Wideband, 16 kHz mono, 320 samples per frame, one frame per packet, and vendor `openzilo-python`. Granule position advances by 320 per packet. ffmpeg emits s16le; `build_wav_from_pcm()` adds a 44-byte header. If one packet decodes to multiple evenly sized frames, `normalize_decoded_speex_pcm()` retains only the first. Intermediate Ogg files are not saved separately by default.

| File/data | Content | Directly playable? |
| --- | --- | --- |
| Device `.bin` | Length-prefixed Speex or OP2C | No |
| `.spx` / `.ogg` | Speex in Ogg | With a Speex-capable player |
| `s16le` PCM | Unwrapped 16-bit samples | Requires sample rate and channels |
| `.wav` | PCM with RIFF/WAV header | Yes |

Changing extensions does not convert formats. Extract, wrap and decode the Speex or Opus packets to produce WAV.

## IMU and motion events

Firmware `V2.001.0002.0001` starts capture and reports on `start_sensor_report()`, and stops capture on `stop_sensor_report()` or disconnect. Subscribe again after reconnecting. Firmware `V2.001.0002.0000` needs gesture mode first and can retain local detection after BLE reports stop.

The SDK accepts two successful `0x0605` formats:

- Single sample: `error_code:u16 + sequence:u32 + timestamp_ms:u32 + six_axes:i16*6`, 22 bytes.
- Batch: `error_code:u16 + sequence_start:u32 + frame_count:u16 + sample_size:u16 + samples`, `10 + 16*N` bytes.

Both return `SensorDataBatch`, with `frame_count=1` for single-sample input. The event layouts below are retained in `V2.001.0002.0000` and `V2.001.0002.0001`.

| Command | Event | Body |
| --- | --- | --- |
| `0x0701` | Physical double tap | `timestamp_ms:u32`, milliseconds since boot |
| `0x0703` | Double button press | `u32` device seconds; SDK retains `timestamp_ms` |
| `0x0704` | Single button press | `u32` device seconds; SDK retains `timestamp_ms` |

Firmware `V2.001.0002.0001` detects taps using IMU data enabled by subscription, and single presses (`0x0704`) no longer switch modes. Firmware `V2.001.0002.0000` detects taps in gesture mode and uses single presses for mode switching. LEDs are local indicators without an SDK query.

Restart reports after reconnection. Local capture restoration depends on firmware.

## Debugging checklist

- Unplayable `.bin`: use `save_audio_bundle()` for raw Speex/OP2C conversion and check ffmpeg installation.
- ffmpeg format error: check file framing, offset-based assembly, and that no protocol fields were mixed into audio. Speex starts with its two-byte length; OP2C starts with its header.
- No `0x0605`: confirm successful `0x0602` after starting reports. Enter gesture mode first only on firmware requiring it.
- Consecutive `0x0505` without `0x0504`: this is post-save push; use `receive_auto_audio_file()`.

When firmware or protocols change, compare device behavior, `src/openzilo/` and the [protocol reference](protocol.en.md), then update the SDK guide and this page.

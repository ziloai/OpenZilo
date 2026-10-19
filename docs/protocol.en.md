# OpenZilo BLE protocol reference

--8<-- "docs/_includes/devices.en.md"

--8<-- "docs/_includes/features.en.md:device-basics"


## 1. Scope

This reference describes protocol v4 framing, commands and fields used by the SDK. Firmware may implement only a subset; query features to check. Button and LED behavior is covered by the [user guide](../wiki/Home.md).

See the [API index](python-sdk.en.md) for calls and [architecture](architecture.en.md) for transport and audio handling.

## 2. BLE services

The protocol uses Nordic UART Service (NUS):

| Purpose | UUID | Direction |
| --- | --- | --- |
| Service | `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` | Service identifier. |
| TX Characteristic | `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` | Ring notifies SDK. |
| RX Characteristic | `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` | SDK writes to ring. |

Connect by the scanned address (UUID on macOS), without depending on advertising names.

SDK RX writes use chunks of up to 20 bytes; the last may be shorter. This is a BLE write policy, not a packet boundary or a replacement for system MTU negotiation. TX notifications can use other sizes; reconstruct them with `OpenZiloClient` or `PacketStream`.

## 3. Protocol v4 packets

The fixed header is 11 bytes:

| Offset | Field | Type | Bytes | Description |
| ---: | --- | --- | ---: | --- |
| 0 | `magic_number` | `u8` | 1 | Always `0x3F`. |
| 1 | `version` | `u16` | 2 | Currently 4. |
| 3 | `command` | `u16` | 2 | Command number. |
| 5 | `body_length` | `u32` | 4 | Body size in bytes. |
| 9 | `body_crc` | `u16` | 2 | Body CRC16; 0 for an empty body. |
| 11 | `body` | `bytes` | variable | Command body. |

Header and body integers are network byte order (big-endian). Strings and raw bytes are not reordered. CRC covers only the body, using SDK `crc16_compute()` with initial value `0xFFFF`.

A packet can span notifications and a notification can contain multiple packets. Reconstruct using the fixed header and `body_length` before parsing. `OpenZiloClient` and `PacketStream` do this already.

## 4. Commands

| Function | Request/event | Response | SDK API |
| --- | --- | --- | --- |
| System information | `0x0101` | `0x0102` | `get_system_info()` |
| Feature discovery | `0x0105` | `0x0106` | `get_device_capabilities()` |
| Command error | `0x01FF` device response | None | `DeviceError` |
| Log storage information | `0x0301` | `0x0302` | `get_log_storage()` |
| Log data | `0x0303` | `0x0304` | `read_log_chunk()` |
| Time synchronization | Device requests `0x0401` | SDK replies `0x0402` | `enable_time_sync()`, `send_time_response()` |
| Recording count | `0x0501` | `0x0502` | `get_audio_file_count()` |
| Normal recording extraction | `0x0503` | `0x0504` | `get_audio_file_info()` |
| Recording data | `0x0506` | `0x0505` | `read_audio_frame()` |
| End normal extraction | `0x0507` | `0x0508` | `end_audio_extract()` |
| Fast recording extraction | `0x0509` | `0x0504`, consecutive `0x0505` | `download_audio_file(..., quick=True)` |
| `V2.001.0002.0000` post-save push | Consecutive device `0x0505` | No initial `0x0504`; metadata queried for recovery | `receive_auto_audio_file()` |
| Recording saved | Device `0x050A` | None | `wait_audio_record_result()`, `receive_auto_audio_file()` |
| Live audio subscription | `0x050D` | `0x050E` | `set_live_audio_subscription()` |
| Live audio data | Device `0x050F`, `0x0510`, `0x0511` | None | `receive_live_audio_file()` |
| Delete all recordings | `0x050B` | `0x050C` | `clear_audio_files()` |
| Start recording | `0x0512` | `0x0513` | `start_audio_recording()` |
| Stop recording | `0x0514` | `0x0515` | `stop_audio_recording()` |
| Recording status | `0x0516` | `0x0517` | `get_audio_recording_status()` |
| Read recording settings | `0x0518` | `0x0519` | `get_audio_recording_config()` |
| Write recording settings | `0x051A` | `0x051B` | `set_audio_recording_config()` |
| Start IMU reports | `0x0601` | `0x0602` | `start_sensor_report()` |
| Stop IMU reports | `0x0603` | `0x0604` | `stop_sensor_report()` |
| IMU batches | Device `0x0605` | None | `wait_sensor_data()` |
| Physical double tap | Device `0x0701` | None | `wait_sensor_double_tap_event()` |
| Double button press | Device `0x0703` | None | `wait_sensor_key_double_press_event()` |
| Single button press | Device `0x0704` | None | `wait_sensor_key_single_press_event()` |

## 5. Message bodies

All `u16`, `i16` and `u32` below are big-endian. A nonzero response `error_code` makes subsequent fields invalid; a response may contain only that error. Some recording failure paths return no response, so timeout alone does not identify the cause.

### 5.1 System information

#### `0x0101` Get system information

Empty body.

#### `0x0102` System information response

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Error code. |
| `firmware_version_len` | `u16` | 2 | Firmware version string length. |
| `firmware_version` | UTF-8 | variable | Firmware version string. |
| `system_time` | `u32` | 4 | Unix timestamp in seconds. |
| `audio_storage_total` | `u32` | 4 | Total recording storage in bytes. |
| `audio_storage_available` | `u32` | 4 | Available recording storage in bytes. |
| `battery_percent` | `u16` | 2 | Battery percentage. |
| `battery_charging` | `u8` | 1 | `0` not charging, `1` charging. |
| `sn_len` | `u16` | 2 | Serial number string length. |
| `sn` | UTF-8 | variable | Device serial number. |
| `cpuid_len` | `u16` | 2 | CPUID string length. |
| `cpuid` | UTF-8 | variable | Device CPUID. |
| `model_len` | `u16` | 2 | Model string length. |
| `model` | UTF-8 | variable | Device model. |

### 5.2 Logs

#### `0x0301` Get log storage

Empty body.

#### `0x0302` Log storage response

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Error code. |
| `page_size` | `u32` | 4 | Log page size or the device's current paging unit. |
| `total_len` | `u32` | 4 | Total log data length. |

#### `0x0303` Read log data

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `index` | `u32` | 4 | Log index. |
| `offset` | `u32` | 4 | Starting offset. |
| `size` | `u32` | 4 | Requested byte count. |

#### `0x0304` Log data response

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Error code. |
| `data_len` | `u32` | 4 | Actual data length. |
| `data` | `bytes` | `data_len` | Log bytes. |

### 5.3 Time synchronization

#### `0x0401` Device time request

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `request_time` | `u32` | 4 | Request construction timestamp T1. |

#### `0x0402` SDK time response

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `request_time` | `u32` | 4 | Original request timestamp T1. |
| `response_time` | `u32` | 4 | Request arrival timestamp T2. |
| `send_time` | `u32` | 4 | Reply send timestamp T3. |

### 5.4 Recordings

#### `0x0501` Get recording count

Empty body.

#### `0x0502` Recording count response

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Error code. |
| `file_count` | `u32` | 4 | Number of stored recordings. |

#### `0x0503` Begin normal extraction

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Always 0. |
| `file_index` | `u32` | 4 | Recording file index. |

#### `0x0509` Begin fast extraction

Same body as `0x0503`. The device first returns `0x0504`, then consecutive `0x0505` packets until `is_end=1`.

#### `0x0504` Recording file information

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Error code. |
| `file_index` | `u32` | 4 | Recording file index. |
| `record_time` | `u32` | 4 | Recording timestamp in seconds. |
| `data_size` | `u32` | 4 | Total encoded data bytes. |

#### `0x0505` Recording data chunk

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Error code. |
| `file_index` | `u32` | 4 | Recording file index. |
| `frame_offset` | `u32` | 4 | Byte offset within recording data. |
| `frame_size` | `u32` | 4 | Chunk byte count, currently at most 4096. |
| `is_end` | `u8` | 1 | `0` not final, `1` final chunk. |
| `data` | `bytes` | `frame_size` | Encoded recording bytes. |

`data` is a raw file fragment: OP2C on Opus firmware, or consecutive little-endian two-byte lengths followed by Speex payloads on legacy firmware. See [recording formats](architecture.en.md#recording-formats). File-internal little-endian lengths do not change big-endian protocol fields.

After saving, legacy Speex firmware pushes this same `0x0505` format without preceding `0x0504`. `receive_auto_audio_file()` selects the first frame's index, assembles by offset, and finishes at `is_end=1`. It returns `(file_index, raw_audio)` without `AudioFileInfo`.

Normal continuous push needs no extraction commands. For a gap, timeout or damaged frame, the SDK queries and verifies index and `data_size` using `0x0503 -> 0x0504`, then requests the expected offset with `0x0506`, up to three attempts. Results are bounded by `data_size`. Keep BLE connected during saving and push. If connection was too late, query the recording count and download by index.

#### `0x0506` Request recording offset

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Always 0. |
| `file_index` | `u32` | 4 | Recording file index. |
| `frame_offset` | `u32` | 4 | Byte offset to read or recover. |
| `reserved` | `u16` | 2 | Reserved padding required by current firmware length checks; always 0. |

The SDK uses `frame_offset` for the next normal-download chunk and to recover missing fast-download or push data.

#### `0x0507` End normal extraction

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Always 0. |
| `file_index` | `u32` | 4 | Recording file index. |

#### `0x0508` Extraction-end response

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Error code. |
| `file_index` | `u32` | 4 | Recording file index. |

#### `0x050A` Recording save result

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Error code. |
| `file_index` | `u32` | 4 | Newly saved recording index. |

Firmware `V2.001.0002.0001` sends this after saving instead of pushing `0x0505`. Retrieve using normal `0x0503` extraction and finish with `0x0507`. Failed saves may return only `error_code`.

#### `0x050B` Delete all recordings

Empty body. Irreversibly deletes all recordings on the device.

#### `0x050C` Delete response

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Error code. |

#### `0x050D` Live audio subscription

--8<-- "docs/_includes/firmware-0001.en.md"

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `enabled` | `u8` | 1 | `1` enable, `0` disable. |

Subscribing does not start recording; users still hold the button in recording mode. Live-only output uses BLE without flash saving; configurable firmware can also save a copy. Disconnect clears the subscription. Unsubscribe aborts live transmission.

#### `0x050E` Subscription response

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Error code; notifications disabled or ATT MTU below 128 causes an error. |
| `enabled` | `u8` | 1 | Current device subscription state. |

#### `0x050F` Live recording START

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `session_id` | `u32` | 4 | Nonzero recording session ID. |
| `reserved` | `u32` | 4 | Always 0. |
| `record_time` | `u32` | 4 | Recording timestamp in seconds. |
| `reserved` | `u32` | 4 | Always 0. |
| `sample_rate` | `u16` | 2 | Always 16000. |
| `channels` | `u8` | 1 | 1 or 2, matching recording settings. |
| `codec` | `u8` | 1 | Always 3 (Opus). |

#### `0x0510` Live recording DATA

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `session_id` | `u32` | 4 | Same as `0x050F`. |
| `sequence` | `u32` | 4 | Packet sequence starting at 0. |
| `byte_offset` | `u32` | 4 | Offset in transmitted Opus bytes, starting at 0. |
| `length` | `u16` | 2 | Opus packet length, 1–100 bytes. |
| `data` | `bytes` | `length` | One 20 ms Opus packet, with the START channel count. |

`byte_offset` counts Opus data only, excluding OP2C length prefixes.

#### `0x0511` Live recording END

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Error code. |
| `session_id` | `u32` | 4 | Same as `0x050F`. |
| `reserved` | `u32` | 4 | Always 0. |
| `produced_bytes` | `u32` | 4 | Opus bytes produced by the device encoder. |
| `sent_bytes` | `u32` | 4 | Opus bytes sent by the device. |
| `dropped_frames` | `u32` | 4 | Frames dropped by the device. |

A recording is complete only when `error_code=0`, `dropped_frames=0`, and both byte counts equal the actual received data. Downloads during live recording may receive device-busy in `0x0504`.

### 5.5 Live IMU

Firmware `V2.001.0002.0000` requires gesture mode first. Firmware `V2.001.0002.0001` removes mode switching and starts capture directly on `0x0601`. Both retain the following command numbers.

#### `0x0601` Start live reports

Empty body. Direct capture startup requires firmware **V2.001.0002.0001 or later**. Firmware `V2.001.0002.0000` requires gesture mode first. Starting from stopped resets `sequence_start`; an active subscription does not reset it.

Use this sequence:

```text
Firmware V2.001.0002.0001: no mode change required
-> Send 0x0601
-> Receive 0x0602 with error_code=0
-> Receive batch 0x0605
```

In recording mode on `V2.001.0002.0000`, `0x0601` returns device-busy. Firmware `V2.001.0002.0001` has no such mode restriction. `wait_sensor_data()` only waits for data and does not send `0x0601`.

#### `0x0602` Start-report response

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Error code. |
| `sample_rate_hz` | `u16` | 2 | Current sample rate; use this returned value. |
| `accel_range_g` | `u16` | 2 | Accelerometer range. |
| `gyro_range_dps` | `u16` | 2 | Gyroscope range. |

#### `0x0603` Stop live reports

Empty body. Firmware `V2.001.0002.0001` stops both BLE reporting and IMU capture. Firmware `V2.001.0002.0000` only stops BLE reports and can retain local capture in gesture mode.

#### `0x0604` Stop-report response

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Error code. |

#### `0x0605` Single-sample and batch IMU data

A successful single-sample body is `error_code:u16 + sequence:u32 + timestamp_ms:u32 + accel_x/y/z:i16 + gyro_x/y/z:i16`, exactly 22 big-endian bytes. The SDK returns a one-sample `SensorDataBatch`.

Batch format follows; its successful length is `10 + 16*N`, distinct from single-sample format:

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `error_code` | `u16` | 2 | Error code. |
| `sequence_start` | `u32` | 4 | First sample sequence in this batch. |
| `frame_count` | `u16` | 2 | Samples in this batch. |
| `sample_size` | `u16` | 2 | Bytes per sample, currently 16. |
| `samples` | `bytes` | `frame_count * sample_size` | Consecutive samples. |

Each 16-byte sample has this layout:

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `timestamp_ms` | `u32` | 4 | Device capture timestamp in milliseconds. |
| `accel_x` | `i16` | 2 | Raw X-axis acceleration. |
| `accel_y` | `i16` | 2 | Raw Y-axis acceleration. |
| `accel_z` | `i16` | 2 | Raw Z-axis acceleration. |
| `gyro_x` | `i16` | 2 | Raw X-axis gyroscope value. |
| `gyro_y` | `i16` | 2 | Raw Y-axis gyroscope value. |
| `gyro_z` | `i16` | 2 | Raw Z-axis gyroscope value. |

Successful body length must equal:

```text
2 + 4 + 2 + 2 + frame_count * sample_size
```

Batches contain at most 32 samples; use `frame_count` for the actual size. The next sequence is `sequence_start + frame_count`. Firmware `V2.001.0002.0001` stops capture on disconnect and requires another `0x0601` after reconnecting. Firmware `V2.001.0002.0000` can resume local gesture-mode detection after reconnecting, but reporting still needs another subscription.

### 5.6 Motion and button events

Both `V2.001.0002.0000` and `V2.001.0002.0001` retain these event layouts. Changes to capture conditions and single-press behavior are described below.

#### `0x0701` Physical double tap

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `timestamp_ms` | `u32` | 4 | Event timestamp in milliseconds. |

Firmware `V2.001.0002.0001` needs `0x0601` to start IMU capture before detecting taps. Firmware `V2.001.0002.0000` detects taps in gesture mode without BLE sample reporting. Timestamps are milliseconds since boot, unlike the device-second timestamps of button events.

#### `0x0703` Double button press

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `timestamp_ms` | `u32` | 4 | Device timestamp in seconds; SDK retains the field name `timestamp_ms`. |

A recognized double press emits only `0x0703`, without the corresponding single press or mode change.

#### `0x0704` Single button press

| Field | Type | Bytes | Description |
| --- | --- | ---: | --- |
| `timestamp_ms` | `u32` | 4 | Device timestamp in seconds; SDK retains the field name `timestamp_ms`. |

Firmware `V2.001.0002.0001` only emits `0x0704`, without switching modes. Firmware `V2.001.0002.0000` also attempts to switch recording/gesture modes. Confirmation waits for the double-press window; the body has no mode field.

After synchronization, button seconds represent device Unix time. Before synchronization, do not interpret them as calendar time. Do not compare directly with IMU/tap milliseconds since boot.

### 5.7 Remote recording and settings

--8<-- "docs/_includes/firmware-0001.en.md"

These commands implement recording-control interface v1. Start, status and configuration-read requests have empty bodies. Integers are big-endian. See [recording control](recording-control.md) for application examples.

#### `0x0512` / `0x0513` Start recording

Empty request. A successful response is `error_code:u16, session_id:u32`, six bytes. Nonzero session ID confirms acceptance, not completion; query `0x0516` for final status. After START timeout, query status instead of automatically retrying.

#### `0x0514` / `0x0515` Stop recording

Request: `session_id:u32, cancel:u8`. `cancel=0` stops according to output settings; `cancel=1` discards uncommitted audio. Success: `error_code:u16, session_id:u32`. The ID must match; final status must still be awaited.

#### `0x0516` / `0x0517` Query recording status

Empty request. Successful response is 14 bytes:

| Field | Type | Description |
| --- | --- | --- |
| `error_code` | `u16` | Error code for the status query. |
| `session_id` | `u32` | Session ID; 0 when idle. |
| `state` | `u8` | 0 idle, 1 queued, 2 capturing, 3 finalizing, 4 complete, 5 failed, 6 cancelled. |
| `saved` | `u8` | 1 if a device file was saved, otherwise 0. |
| `recording_error` | `u16` | Recording error code, separate from the query error. |
| `file_index` | `u32` | Saved file index; 0 if not saved. |

The SDK uses `saved` to determine whether the index is valid. Without a saved file, returned `file_index` is `None`.

#### `0x0518` / `0x0519` Read recording configuration

Empty request. Response begins with `error_code:u16`; on success the 14-byte settings below are followed by sample rate, frame duration and fixed codec parameters.

| Field | Type | Description |
| --- | --- | --- |
| `version` | `u8` | Configuration structure version, currently 1. |
| `output` | `u8` | 0 automatic, 1 flash, 2 live, 3 live plus flash. |
| `disconnect_policy` | `u8` | 0 stop, 1 continue saving on device. |
| `channels` | `u8` | 1 or 2. |
| `bitrate` | `u32` | Bitrate in bit/s. |
| `gain_left_q8`, `gain_right_q8` | `u16` each | Left/right digital gain; 256 means 1x. |
| `max_duration_ms` | `u16` | Maximum duration in milliseconds. |

Successful responses are 34 bytes. Settings are followed by `sample_rate:u16`, `frame_duration_ms:u16`, then `codec:u8`, `complexity:u8`, `vbr:u8`, `constrained_vbr:u8`, `dtx:u8`, `fec:u8`, `packet_loss_percent:u8`, `signal:u16`, `bit_depth:u8`, `max_packet_size:u16`, `application:u16`. The device returns these fixed parameters; configuration writes cannot change them.

#### `0x051A` / `0x051B` Write recording configuration

Request contains only the 14-byte settings above. Response matches configuration readback, showing accepted settings. Write only while idle. Continue-saving on disconnect requires flash or live-plus-flash output.

## 6. Error codes

| Value | Name | Description |
| ---: | --- | --- |
| 0 | `SUCCESS` | Success. |
| 1 | `UNKNOWN` | Unknown error. |
| 2 | `DEVICE_BUSY` | Device busy. |
| 3 | `FILE_NOT_EXIST` | File not found. |
| 4 | `CMD_GROUP_NOT_EXIST` | Command group not found. |
| 5 | `CMD_NOT_EXIST` | Command not found. |
| 6 | `TIMEOUT` | Operation timed out. |
| 7 | `PARAM_INVALID` | Invalid argument. |
| 8 | `COMMUNICATION` | Communication error. |
| 9 | `UNSUPPORTED_SCHEMA` | Unsupported message structure version. |

See the [firmware update guide](../wiki/Firmware-Updates.md). The SDK provides `update_firmware()` and `ota-update`; calls are documented in the [SDK firmware updates](sdk-ota.en.md#firmware-updates).

## Capability discovery messages

The release tags for `V2.001.0002.0000` and `V2.001.0002.0001` do not implement the discovery commands below. This section documents the SDK parser for the discovery extension; it does not attribute that extension to the `V2.001.0002.0001` release.


Protocol v4 and existing GET_INFO and recording-v1 layouts remain unchanged. All integers are big-endian.

| Command | Direction | Body |
|---|---|---|
| `0x0105` | Host → device | Empty |
| `0x0106` | Device → host | `error:u16`; success adds `schema:u8=1` followed by TLVs |
| `0x01FF` | Device → host | `original_command:u16, error:u16`, exactly four bytes |

Errors: 2 busy, 5 unknown command, 7 invalid argument, 9 unsupported structure version. An unknown command returns 5, nonempty discovery request returns 7, and unknown version in the 14-byte recording settings returns 9. Existing command-specific errors remain valid; not all legacy failures use generic errors. Never reply to an error with another error.

TLVs contain `tag:u16, length:u16, value:length bytes`, within v4's 5120-byte limit; current firmware constructs responses in a buffer of at most 512 bytes. Duplicate tags, truncation, invalid UTF-8 and missing required device fields fail parsing. Unknown optional tags are skipped; an unknown tag with its top bit set requires an SDK upgrade.

| Tag | Content |
|---|---|
| 1 | Full firmware version, UTF-8. |
| 2 | Product model, UTF-8. |
| 3 | Firmware compilation target, UTF-8. |
| 4 | Eight-byte random boot_id for this boot. |
| 5 | Firmware build ID, UTF-8. |
| 6 | Supported protocol versions as consecutive u16 values; currently 4. |
| `0x0100 + feature_id` | Feature interface version `major:u8, minor:u8`. |
| `0x0204` | Recording limits, defined below. |

Feature IDs: 1 system/1, 2 time_sync/1, 3 audio_files/1, 4 recording_control/1, 5 live_audio/1, 6 imu/2, 7 key_events/1, 8 double_tap/1, 9 ota/1, 10 gesture/1. The suffix is the supported major version. Current firmware does not advertise gesture. IMU/2 starts capture on subscription; an implementation requiring separate gesture mode must not advertise it.

Firmware advertises features only for fully registered command groups. Button/tap events require connected producers in the product build. Advertisement identifies implementation support, not successful hardware initialization, current connection readiness or an idle device.

Recording limits occupy exactly 26 bytes:

| Position | Type | Meaning |
|---|---|---|
| 1–2 | u16, u16 | Sample rate and frame duration in milliseconds. |
| 3–6 | u8 × 4 | Channel mask, output mask, continue-saving output mask, reserved=0. |
| 7–8 | u32 × 2 | Minimum and maximum bitrate, inclusive. |
| 9–10 | u16 × 2 | Minimum and maximum Q8 digital gain. |
| 11–13 | u16 × 3 | Minimum and maximum duration, and duration step in milliseconds. |

Masks use enum values as bit positions: channels 1/2 give `0x06`; CONTINUE_SAVING with FLASH=1/BOTH=3 gives `0x0A`. Recording interface v1 requires these limits. Read fixed Opus parameters through the existing configuration-read command.

### Interface evolution

Use optional TLVs for additive fields so older clients can skip them. Incompatible fields or behavior need a higher major version and new command or structure. Mark client-required fields as required. Reject unsupported fields in writes. Detect recording formats from content, independently of current firmware.

Requests have no transaction IDs. Query state before retrying START. Release notes specify OTA compatibility; the SDK does not infer every starting-version combination or provide automatic rollback. Application and bootloader security versions are independent.

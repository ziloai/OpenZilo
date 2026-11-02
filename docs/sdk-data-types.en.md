# Data types

--8<-- "docs/_includes/devices.en.md"

Use public data types through `import openzilo as sdk`. See [exceptions and troubleshooting](sdk-errors.en.md) for errors and the [API index](python-sdk.en.md) for functions.

## BLE and protocol types

```python
BleDeviceInfo
name: str | None    # BLE advertising name, possibly absent.
address: str        # BLE address; UUID on macOS.
rssi: int | None    # Signal strength; unavailable on some bleak backends.

Packet
command: int        # Command number, for example 0x0605.
body: bytes         # Body bytes, without the protocol header.
version: int        # Protocol version, currently 4.
body_crc: int       # CRC16 of the body.

OpenZiloClient
# High-level BLE client: connection, packet reconstruction, requests and event dispatch.

NusClient
# Nordic UART Service client for custom transports.
# Normally used directly only for debugging or custom transports.

PacketStream
# Reconstructs complete packets from BLE fragments, for protocol debugging.

BinaryReader
# Reads u8/u16/u32/i16/string_u16 from bytes in network byte order.

BinaryWriter
# Builds body bytes in network byte order.
```

## System and log types

```python
SystemInfo
firmware_version: str          # Firmware version.
system_time: int               # Device system timestamp.
audio_storage_total: int       # Total recording storage in bytes.
audio_storage_available: int   # Available recording storage in bytes.
battery_percent: int           # Battery percentage.
battery_charging: bool         # Whether charging is active.
sn: str                        # Device serial number; may be unknown if not provisioned.
cpuid: str                     # Chip ID string.
model: str                     # Device model.

LogStorageInfo
page_size: int   # Log file or page size, as returned by the device.
total_len: int   # Maximum readable log length.
```

## Recording types

```python
AudioFileInfo
file_index: int    # Recording index.
record_time: int   # Device-stored recording timestamp.
data_size: int     # Raw recording length in bytes.

AudioDataFrame
file_index: int     # Recording index.
frame_offset: int   # Start offset of this chunk within the recording.
frame_size: int     # Declared chunk data length.
is_end: bool        # Whether this is the final chunk.
data: bytes         # Recording bytes in this chunk.

PcmConfig
sample_rate: int = 16000  # WAV output sample rate.
channels: int = 1         # WAV output channel count.
bit_depth: int = 16       # WAV output bit depth.

SpeexDecodeResult
pcm_bytes: bytes          # Decoded PCM bytes.
pcm_config: PcmConfig     # PCM parameters.
source_type: str          # Input type, such as packet-speex or ogg-speex.
source_extension: str     # Suggested input extension.
packet_count: int         # Speex packet count, or 0 when unavailable.

PlayableAudio
bytes: bytes              # Playable audio bytes, usually WAV.
extension: str            # Suggested extension.
mime: str                 # MIME type.
play_mode: str            # direct or speex-decode.
label: str                # Format label.
pcm_config: PcmConfig | None
source_type: str
source_extension: str
source_mime: str
description: str

AudioBundle
raw_path: Path            # Saved raw recording path.
raw_file_name: str
play_path: Path           # Decoded playable file path.
play_file_name: str
play_mode: str
format_label: str
play_description: str
pcm_summary: str
raw_size: int
play_size: int
source_type: str
source_extension: str

OpusDecodeResult
pcm_bytes: bytes          # Decoded 16 kHz mono/stereo 16-bit PCM.
pcm_config: PcmConfig     # PCM parameters.
source_type: str          # opus-mono for mono; opus-stereo for stereo.
source_extension: str     # Always op2c.
packet_count: int         # Opus packet count.

AudioRecordResult
file_index: int           # Recording index reported by 0x050A.

LiveAudioSubscription
enabled: bool             # Live subscription state confirmed by the device.

LiveAudioStart
session_id: int           # Live recording session.
record_time: int          # Recording timestamp in seconds.
sample_rate: int          # Always 16000.
channels: int             # 1 or 2, matching device recording settings.
codec: int                # Always 3 (Opus).

LiveAudioData
session_id: int
sequence: int             # Packet sequence, starting at 0.
byte_offset: int          # Opus byte offset, starting at 0.
data: bytes               # One 20 ms Opus packet, matching the START channel count.

LivePcmFrame
session_id: int
sample_offset: int        # Per-channel sample position, not compressed byte offset.
sample_count: int         # 320 samples per channel, or 20 ms.
data: bytes               # 640 mono or 1280 stereo s16le bytes; no WAV header.
pcm_config: PcmConfig     # 16 kHz, 16-bit; channels match the recording.

LiveAudioEnd
error_code: int
session_id: int
produced_bytes: int       # Opus bytes produced by the device encoder.
sent_bytes: int           # Opus bytes sent by the device.
dropped_frames: int       # Frames dropped by the device.

LiveAudioRecording
start: LiveAudioStart
end: LiveAudioEnd
data: bytes               # Complete OP2C file, ready for decoding or saving.

ProgressPrinter
# Can be used as the download_audio_file(progress=...) callback.
```

## IMU and event types

```python
SensorStartInfo
sample_rate_hz: int    # Sample rate returned by the device.
accel_range_g: int     # Accelerometer range.
gyro_range_dps: int    # Gyroscope range.

SensorStopInfo
# Successful IMU-stop result; currently has no fields.

SensorDataSample
timestamp_ms: int      # Device sample timestamp in milliseconds.
accel_x: int           # Raw X-axis acceleration.
accel_y: int           # Raw Y-axis acceleration.
accel_z: int           # Raw Z-axis acceleration.
gyro_x: int            # Raw X-axis angular velocity.
gyro_y: int            # Raw Y-axis angular velocity.
gyro_z: int            # Raw Z-axis angular velocity.

SensorDataBatch
sequence_start: int                    # Sequence number of the first sample.
frame_count: int                       # Samples in this batch.
sample_size: int                       # Bytes per sample, currently 16.
samples: tuple[SensorDataSample, ...]  # Sample n has sequence_start + n.

SensorDoubleTapEvent
timestamp_ms: int  # Physical double-tap timestamp.

SensorKeyDoublePressEvent
timestamp_ms: int  # This firmware sends seconds; the historical SDK field name is retained.

SensorKeySinglePressEvent
timestamp_ms: int  # This firmware sends seconds; the historical SDK field name is retained.
```

Call `start_sensor_report()` again after reconnection. Whether local capture resumes automatically depends on firmware, not just BLE connection state.

## Software IMU calibration

```python
ImuCalibration
sensor_type: int             # 0 = unknown; no guessed chip identity
accel_range_g: int
gyro_range_dps: int
accel_bias_ug: tuple[int, int, int]
accel_scale_ppm: tuple[int, int, int]  # identity = (1000000, 1000000, 1000000)
gyro_bias_udps: tuple[int, int, int]

ImuCalibrationProfile
device_key: str              # Opaque identifier for binding a profile to a device
firmware_version: str        # exact match, not a version range
model: str
calibration: ImuCalibration
accel_validated: bool
gyro_validated: bool
created_at: str              # ISO 8601, with timezone

CalibratedImuSample
timestamp_ms: int
accel_g: tuple[float, float, float]
gyro_dps: tuple[float, float, float]

CalibratedImuBatch
sequence_start: int
frame_count: int
samples: tuple[CalibratedImuSample, ...]
applied_components: tuple[str, ...]  # e.g. ("accel",), or ("accel", "gyro")
```

[Software calibration workflow and APIs](sdk-imu.en.md).

## FirmwareBundle

The immutable result of `inspect_firmware_bundle()` contains `version`, `model`, `board`, `profile`, `security_version`, `source_versions`, `signing_key_id`, and update payload bytes `payload`. Its `manifest` property returns a fresh dictionary of every verified field, suitable for display or JSON output. Mutating that copy cannot change update data. Inspection does not check device compatibility.

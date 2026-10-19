# 数据类型

--8<-- "docs/_includes/devices.zh-CN.md"

公开数据类型统一通过 `import openzilo as sdk` 使用。异常类型见[异常与问题排查](sdk-errors.zh-CN.md)，函数入口见[API 索引](python-sdk.zh-CN.md)。

## BLE 和协议类型

```python
BleDeviceInfo
name: str | None    # BLE 广播名称，可能为空。
address: str        # BLE MAC 地址。
rssi: int | None    # 信号强度；部分 bleak 后端可能不提供。

Packet
command: int        # 命令字，例如 0x0605。
body: bytes         # 包体，不包含协议头。
version: int        # 协议版本，当前通常为 4。
body_crc: int       # 包体 CRC16。

OpenZiloClient
# 高层 BLE 协议客户端。负责连接、收包重组、请求响应匹配和事件分发。

NusClient
# 底层 Nordic UART Service BLE 客户端。发送固定按 20 字节分片，
# 通常只在调试或自定义传输时直接使用。

PacketStream
# 将 BLE 分片拼成完整 Packet，适合协议调试。

BinaryReader
# 按网络字节序从 bytes 中读取 u8/u16/u32/i16/string_u16。

BinaryWriter
# 按网络字节序构建 bytes 包体。
```

## 系统和日志类型

```python
SystemInfo
firmware_version: str          # 固件版本。
system_time: int               # 设备侧系统时间戳。
audio_storage_total: int       # 录音存储总字节数。
audio_storage_available: int   # 录音存储剩余字节数。
battery_percent: int           # 电量百分比。
battery_charging: bool         # 是否正在充电。
sn: str                        # 设备序列号；设备未写入时可能为 unknown。
cpuid: str                     # 芯片 ID 字符串。
model: str                     # 设备型号。

LogStorageInfo
page_size: int   # 当前日志文件大小或页大小字段，按设备端返回解释。
total_len: int   # 日志最大可读长度。
```

## 录音类型

```python
AudioFileInfo
file_index: int    # 录音索引。
record_time: int   # 录音时间戳，由设备端保存。
data_size: int     # 录音原始数据字节数。

AudioDataFrame
file_index: int     # 录音索引。
frame_offset: int   # 本帧在录音数据中的起始偏移。
frame_size: int     # 本帧声明的数据长度。
is_end: bool        # 是否为最后一帧。
data: bytes         # 本帧录音数据。

PcmConfig
sample_rate: int = 16000  # WAV 输出采样率。
channels: int = 1         # WAV 输出声道数。
bit_depth: int = 16       # WAV 输出位深。

SpeexDecodeResult
pcm_bytes: bytes          # 解码后的 PCM 数据。
pcm_config: PcmConfig     # PCM 参数。
source_type: str          # 源数据类型，例如 packet-speex、ogg-speex。
source_extension: str     # 源数据建议扩展名。
packet_count: int         # Speex 包数量，无法统计时为 0。

PlayableAudio
bytes: bytes              # 可播放音频字节，通常是 WAV。
extension: str            # 建议扩展名。
mime: str                 # MIME 类型。
play_mode: str            # direct 或 speex-decode。
label: str                # 格式标签。
pcm_config: PcmConfig | None
source_type: str
source_extension: str
source_mime: str
description: str

AudioBundle
raw_path: Path            # 原始录音保存路径。
raw_file_name: str
play_path: Path           # 解码后可播放文件路径。
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
pcm_bytes: bytes          # 解码后的 16 kHz、单声道或双声道、16 bit PCM。
pcm_config: PcmConfig     # PCM 参数。
source_type: str          # 单声道为 opus-mono，双声道为 opus-stereo。
source_extension: str     # 固定为 op2c。
packet_count: int         # Opus 包数量。

AudioRecordResult
file_index: int           # V2.001.0002.0001 的 0x050A 录音索引。

LiveAudioSubscription
enabled: bool             # 设备确认的实时录音订阅状态。

LiveAudioStart
session_id: int           # 实时录音会话。
record_time: int          # 录音时间戳，单位秒。
sample_rate: int          # 固定为 16000。
channels: int             # 1 或 2，与设备录音设置一致。
codec: int                # 固定为 3，表示 Opus。

LiveAudioData
session_id: int
sequence: int             # 包序号，从 0 开始。
byte_offset: int          # Opus 数据字节偏移，从 0 开始。
data: bytes               # 一个 20 ms Opus 包，声道数与录音开始事件一致。

LivePcmFrame
session_id: int
sample_offset: int        # 每声道采样位置，从 0 开始；不是压缩字节偏移。
sample_count: int         # 固定为每声道 320 个采样，即 20 ms。
data: bytes               # 单声道 640 字节或双声道 1280 字节 s16le PCM，不含 WAV 文件头。
pcm_config: PcmConfig     # 16 kHz、16 位，声道数与录音一致。

LiveAudioEnd
error_code: int
session_id: int
produced_bytes: int       # 设备编码产生的 Opus 字节数。
sent_bytes: int           # 设备已发送的 Opus 字节数。
dropped_frames: int       # 设备丢弃的帧数。

LiveAudioRecording
start: LiveAudioStart
end: LiveAudioEnd
data: bytes               # 完整 OP2C 文件，可直接解码或保存。

ProgressPrinter
# 可作为 download_audio_file(progress=...) 的进度回调。
```

## 六轴和事件类型

```python
SensorStartInfo
sample_rate_hz: int    # 设备返回的采样率。
accel_range_g: int     # 加速度计量程。
gyro_range_dps: int    # 陀螺仪量程。

SensorStopInfo
# 停止六轴上报的成功结果；当前没有字段。

SensorDataSample
timestamp_ms: int      # 设备侧采样时间戳，单位 ms。
accel_x: int           # 加速度 X 轴原始值。
accel_y: int           # 加速度 Y 轴原始值。
accel_z: int           # 加速度 Z 轴原始值。
gyro_x: int            # 陀螺仪 X 轴原始值。
gyro_y: int            # 陀螺仪 Y 轴原始值。
gyro_z: int            # 陀螺仪 Z 轴原始值。

SensorDataBatch
sequence_start: int                    # 本批第一个采样点序号。
frame_count: int                       # 本批采样点数量。
sample_size: int                       # 单个采样点字节数，当前为 16。
samples: tuple[SensorDataSample, ...]  # 批量采样点；第 n 个样本序号为 sequence_start + n。

SensorDoubleTapEvent
timestamp_ms: int  # 普通双击事件时间戳。

SensorKeyDoublePressEvent
timestamp_ms: int  # 本固件发送秒级设备时间；SDK 保留此历史字段名。

SensorKeySinglePressEvent
timestamp_ms: int  # 本固件发送秒级设备时间；SDK 保留此历史字段名。
```

重连后应重新调用 `start_sensor_report()`。本地采集是否自动恢复取决于固件实现，不能从连接状态推断。

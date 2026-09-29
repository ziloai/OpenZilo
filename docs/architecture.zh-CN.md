# OpenZilo SDK 架构与数据流

基线：Python SDK `0.5.0`、通信协议 v4、设备固件 `V2.000.0001.0015`。

这里说明 `src/openzilo.py` 怎样收发数据、下载录音并生成 WAV。函数签名和调用示例见 [SDK 手册](python-sdk.zh-CN.md)，命令和包体字段见 [协议参考](protocol.zh-CN.md)。涉及设备行为的结论以对应固件的实测结果为准。

## 从 BLE 通知到 SDK 接口

```text
戒指 Nordic UART Service
  ↓  BLE 通知 / 特征值写入
NusClient                 扫描、连接、订阅通知、分片写入
  ↓
PacketStream              拼出完整 v4 包，检查包头与 CRC
  ↓
OpenZiloClient            按命令分发响应和主动上报
  ↓
get_system_info() / download_audio_file() / wait_sensor_data() ...
```

`NusClient` 使用 `bleak`，按设备地址扫描和连接，不依赖广播名称。写入 NUS RX 特征值时，SDK 把数据切成最多 20 字节的片段；这不会改变系统蓝牙栈的 MTU 协商。戒指从 NUS TX 发来的通知没有相同的长度保证。

`PacketStream.feed()` 接收任意长度的通知数据。一个协议包可以跨多次通知，多包也可以连续到达。它按包头中的 `body_length` 截取完整包，跳过 magic 之前的杂字节；包头、CRC 或长度不合法时抛出 `ProtocolError`。包体上限是 5120 字节。

`OpenZiloClient` 为每个命令维护接收队列。`request()` 先清掉目标响应队列中的旧包，再发送请求并等待响应；`wait_for_command()` 用于等待 `0x0605` 等主动上报。长期监听可注册 `add_packet_handler()`，自动校时就是这种用法。持续上报要及时消费，否则队列会积压。等待期间 BLE 断开时抛出 `TransportError`。

### v4 包的边界

包头固定 11 字节：

```text
magic:u8=0x3F | version:u16=4 | command:u16 | body_length:u32 | body_crc:u16 | body
```

包头和普通包体整数用大端序，CRC16 只覆盖 `body`，空包体的 CRC 为 0。`BinaryReader` 和 `BinaryWriter` 处理这些字段。录音文件中的 Speex 帧长另用 2 字节小端序；它属于文件内容，不属于 v4 包头。各命令的包体布局在[协议参考](protocol.zh-CN.md)中。

## 录音文件格式

设备保存的是连续的 Speex 帧。每帧前有 2 字节小端长度，后面紧跟该长度的 payload：

```text
[length:u16 little-endian][Speex payload:length bytes]
[length:u16 little-endian][Speex payload:length bytes]
...
```

例如 `14 00` 表示下一帧 payload 长 20 字节。解析时要逐帧读取长度，不能按 20 字节固定切分。编码模式为 Speex Wideband；一帧对应 320 个 16 kHz 单声道采样点，即 20 ms。SDK 对单个 Speex 包设有 540 字节上限，输出的 PCM 默认为 16 kHz、单声道、16 bit。

把各个 `0x0505.data` 按 `frame_offset` 拼接后，完整录音从第一个长度字段开始，不带设备文件管理元数据。`AudioFileInfo.data_size` 是这段编码数据的字节数。SDK 保存的 `.bin` 保持原始格式，便于重新解码。

## 录音怎样传到电脑

| 入口 | 设备交互 | SDK 接口 |
| --- | --- | --- |
| 普通提取 | `0x0503 → 0x0504` 取得文件信息，再用 `0x0506 → 0x0505` 按偏移读取；结束时 `0x0507 → 0x0508` | `download_audio_file(..., quick=False)` |
| 快速提取 | `0x0509 → 0x0504`，随后设备连续发送 `0x0505` | `download_audio_file(..., quick=True)`，默认路径 |
| 保存后主动发送 | 设备直接发送连续 `0x0505`，事先没有 `0x0504` | `receive_auto_audio_file()` |

每个 `0x0505` 包都有文件索引和 `frame_offset`。SDK 按偏移拼接，跳过已收到的重叠字节。快速提取遇到缺口或超时，会用 `0x0506` 请求缺失位置；连续补传超过 3 次仍不完整时抛出 `ProtocolError`。结果按 `AudioFileInfo.data_size` 截断。设备单帧数据区最大 4096 字节，SDK 的包体上限为 5120 字节。

主动发送发生在录音保存后，不需要应用先发提取命令。`receive_auto_audio_file()` 从首帧取得文件索引，返回 `(file_index, raw_audio)`。如果帧丢失，它会先用 `0x0503 → 0x0504` 核对文件长度，再按偏移补传；无法补齐就报错，不返回残缺录音。

使用主动接收时，BLE 连接要在设备发送前建立。`receive_auto_audio_file()`、`download_audio_file()` 和 `read_audio_frame()` 会消费同一连接的 `0x0505` 队列，不能并发调用。如果错过主动发送，查询录音数量后再按索引下载。

## 从 Speex 到 WAV

```text
.bin → 逐帧读取长度前缀 → Speex payload → 临时 Ogg Speex
     → ffmpeg 解码为 s16le PCM → 加 RIFF/WAV 头 → .wav
```

`save_audio_bundle()` 先写入原始 `.bin`，再尝试生成 WAV。没有 `ffmpeg` 或解码失败时，原始文件仍在，函数会抛出 `SpeexDecoderUnavailable` 或 `AudioDecodeError`。

`build_playable_audio()` 遇到已有的 WAV 会直接返回；其他路径还能识别 Ogg Speex 和无长度前缀的裸 Speex。返回的 `source_type` 可为 `wav`、`ogg-speex`、`packet-speex` 或 `raw-speex`。设备录音走 `packet-speex` 路径。只有裸 Speex 回退才使用 `quality` 和 `bits_size`：默认 `quality=3` 对应估算帧长 20 字节，显式传入的 `bits_size` 会覆盖该估算。

旧数据若带 1026 字节外层分块，可传入 `allow_framed_blocks=True`。底层 `parse_packetized_speex_stream()` 默认允许这种分块；`decode_speex_to_pcm()`、`build_playable_audio()`、`decode_audio_to_wav()` 和 `save_audio_bundle()` 默认不启用，调用高层函数时需显式指定。

`build_ogg_speex()` 只为解码临时封装 Ogg。Speex 头使用版本标记 `speex-1.2.1`、Wideband mode、16 kHz、单声道、每帧 320 个采样点、每包一帧；vendor comment 为 `openzilo-python`。音频包的 granule position 每包增加 320。`ffmpeg` 输出 `s16le` PCM，`build_wav_from_pcm()` 再写入 44 字节的 PCM WAV 头。若解码器为一个 Speex 包输出多帧且长度可整除，`normalize_decoded_speex_pcm()` 只保留每包的第一帧。SDK 默认不单独保存中间 Ogg 文件。

| 文件或数据 | 内容 | 能否直接播放 |
| --- | --- | --- |
| 设备 `.bin` | 带长度前缀的 Speex 帧 | 否 |
| `.spx` / `.ogg` | Ogg 容器中的 Speex | 支持 Speex 的播放器可以 |
| `s16le` PCM | 无容器的 16 bit 采样 | 需要另给采样率和声道数 |
| `.wav` | PCM 加 RIFF/WAV 头 | 可以 |

改扩展名不会改变数据格式。设备 `.bin` 要先拆出 Speex 帧并封装、解码，才能得到 WAV。

## IMU 与动作事件

设备启动后通常处于录音模式，单击会尝试切换到手势模式。SDK 没有查询或设置模式的命令。要接收实时 IMU，先让设备进入手势模式，再调用 `start_sensor_report()`，等待 `0x0602` 成功后循环调用 `wait_sensor_data()`。在录音模式发送 `0x0601` 会得到设备忙碌。`stop_sensor_report()` 只停 BLE 上报，不退出手势模式。

`0x0605` 一次上报一批样本：`error_code:u16`、`sequence_start:u32`、`frame_count:u16`、`sample_size:u16`，随后是 `frame_count` 个样本。一个样本占 16 字节，由 `timestamp_ms:u32` 和加速度、角速度各三个 `i16` 组成。字段均为大端序。SDK 校验 `sample_size == 16` 和包体长度，返回 `SensorDataBatch`。

| 命令 | 事件 | 包体 |
| --- | --- | --- |
| `0x0701` | 普通双击 | `timestamp_ms:u32` |
| `0x0702` | HMM 手势 | `timestamp_ms:u32 + gesture_id:u8` |
| `0x0703` | 按键双击 | `timestamp_ms:u32` |
| `0x0704` | 按键单击 | `timestamp_ms:u32` |

HMM 手势使用设备本地 IMU，不要求开启 `0x0605` 实时上报。`gesture_id` 可用 `sensor_gesture_name()` 转成名称，并应容忍未知值。`0x0704` 只确认识别到单击，可能因双击判定而延迟；它不表示模式切换成功。LED 是本地提示，SDK 无法查询其状态，应以协议响应判断操作结果。

## 联调时先查什么

- `.bin` 无法播放：这是原始 Speex 帧流。用 `save_audio_bundle()` 生成 WAV，并确认安装了 `ffmpeg`。
- `ffmpeg` 报格式错误：检查文件是否从首个 2 字节小端长度字段开始，下载时是否按 `frame_offset` 拼接，是否把协议包字段混进了数据区。
- 收不到 `0x0605`：确认设备在手势模式，且 `start_sensor_report()` 收到了成功的 `0x0602`。
- 收到连续 `0x0505` 却没有 `0x0504`：这是保存后的主动发送，用 `receive_auto_audio_file()` 接收。

固件或协议升级时，先比对实机行为、`src/openzilo.py` 和[协议参考](protocol.zh-CN.md)，再更新调用手册和本页。

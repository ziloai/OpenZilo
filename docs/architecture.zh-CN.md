# OpenZilo SDK 架构与数据流

--8<-- "docs/_includes/devices.zh-CN.md"

--8<-- "docs/_includes/features.zh-CN.md:device-basics"


本文介绍当前 SDK 如何处理 BLE 数据和录音文件。设备操作说明见[戒指使用指南](../wiki/Home-zh-CN.md)，各功能的固件要求见[功能与版本要求](features.zh-CN.md)。

这里说明 `openzilo` 包怎样收发数据、下载录音并生成 WAV。函数签名和调用示例见 [API 索引](python-sdk.zh-CN.md)，命令和包体字段见 [协议参考](protocol.zh-CN.md)。具体功能要求见[功能与版本要求](features.zh-CN.md)。

## 代码结构

应用只从 `import openzilo` 使用 `__all__` 中的名称。实现按职责放在下划线开头的内部子模块中：

| 模块 | 职责 |
| --- | --- |
| `_errors` | 异常类型和设备错误码 |
| `_protocol` | v4 包头、CRC、命令号、二进制读写 |
| `_transport` | 基于 bleak 的 NUS 扫描、连接和分片写入 |
| `_client` | `OpenZiloClient`：请求响应匹配和收包分发 |
| `_tasks` | 截止时间和后台回调任务的 asyncio 工具 |
| `_device` | 扫描连接入口、系统信息、日志、校时 |
| `_ota` | 应用固件升级 |
| `_compatibility` | 查询设备功能、检查接口版本与录音参数 |
| `_recording` | 远程录音、状态查询与录音设置 |
| `_identity`、`_version` | SDK 版本与源码校验值 |
| `_audio` | 已保存录音的查询、下载和自动接收 |
| `_live_audio` | 实时录音订阅和接收 |
| `_codec` | Speex、OP2C 格式与 WAV 转换 |
| `_pcm` | 可选 PyAV 有状态 Opus 解码与 PCM 分块，不依赖 BLE |
| `_sensor` | IMU 上报和动作事件 |
| `_cli` | `python -m openzilo` 命令行 |

依赖只从上往下：`_errors`、`_protocol` 不依赖 BLE，录音编解码 `_codec` 也不依赖连接，可以单独用于离线文件处理。

### 实时音频流

--8<-- "docs/_includes/firmware-0001.zh-CN.md"

`open_live_audio_stream()` 用异步上下文管理订阅和清理，用异步迭代输出一段按键录音的 START、音频帧、END。进入上下文表示订阅已确认，录音仍由用户按键触发。一个流只能由一个任务读取，退出上下文会停止未完成的接收并尝试退订。

```text
BLE 通知 → _PacketInbox 有界队列 → 后台接收任务：会话、序号、偏移校验
                                → Opus 事件
                                → 可选有状态解码/重采样 → 20 ms PCM 音频
                                → 有界事件队列 → 应用 async for
```

后台接收任务独占音频操作，禁止并发下载、其他音频接收或 OTA。原始通知队列由 `OpenZiloClient.receive_queue_size` 控制，默认 256；应用事件队列由 `queue_size` 控制，默认 64。两层队列都在溢出时报错，不能通过暂停应用读取让戒指停止发送，也不静默丢弃帧。

PCM 模式的可选 `pcm` extra 提供 PyAV。每段录音单独创建 Opus 解码器和重采样器，逐包顺序执行，保留跨包状态；解码调用在工作线程中执行。输出为 16 kHz、有符号 16 位小端 PCM，每帧每声道 320 个采样；单声道或双声道与录音设置一致，双声道按左右交错排列。重采样器存在短缓存，END 校验成功后排空缓存并核对样本总数；不会给每个包单独创建文件或调用 ffmpeg 子进程。

流不累计整段录音。`receive_live_audio_file()` 读取同一条 Opus 事件流，累计原始包并生成 OP2C，沿用相同的完整性校验。收到并检查结束事件（END）之前，应用还不能确认整段音频完整，错误后无法从设备 Flash 补回。

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

`OpenZiloClient` 为每个命令维护接收队列。`request()` 按响应命令串行执行，先清掉目标响应队列中的旧包，再发送请求并等待响应；`wait_for_command()` 用于等待 `0x0605` 等主动上报。长期监听可注册 `add_packet_handler()`，自动校时就是这种用法。每命令队列默认最多 256 包，可通过 `receive_queue_size` 调整；溢出清理积压并报告 `ProtocolError`。纯回调监听使用 `add_packet_handler(..., queue_packets=False)`，独占该命令且不保留队列副本。等待期间 BLE 断开时抛出 `TransportError`。

### v4 包的边界

包头固定 11 字节：

```text
magic:u8=0x3F | version:u16=4 | command:u16 | body_length:u32 | body_crc:u16 | body
```

包头和普通包体整数用大端序，CRC16 只覆盖 `body`，空包体的 CRC 为 0。`BinaryReader` 和 `BinaryWriter` 处理这些字段。录音文件中的 Speex 帧长另用 2 字节小端序；它属于文件内容，不属于 v4 包头。各命令的包体布局在[协议参考](protocol.zh-CN.md)中。

## 录音文件格式

!!! note "固件版本"

    OP2C 单／双声道 Opus 录音从固件 **V2.001.0002.0001** 开始提供。解码已有 Speex 文件无需升级固件。

固件 `V2.001.0002.0000` 保存连续的 Speex 帧，固件 `V2.001.0002.0001`保存 OP2C 格式的单声道或双声道 Opus 文件。升级不会转换已有录音，同一设备上可能两种都有，所以 SDK 按文件内容识别编码，不看固件版本或扩展名。

Speex 文件每帧前有 2 字节小端长度，后面紧跟该长度的 payload：

```text
[length:u16 little-endian][Speex payload:length bytes]
[length:u16 little-endian][Speex payload:length bytes]
...
```

例如 `14 00` 表示下一帧 payload 长 20 字节。解析时要逐帧读取长度，不能按 20 字节固定切分。编码模式为 Speex Wideband；一帧对应 320 个 16 kHz 单声道采样点，即 20 ms。SDK 对单个 Speex 包设有 540 字节上限，输出的 PCM 默认为 16 kHz、单声道、16 bit。

OP2C 文件先是 12 字节小端文件头，之后同样是长度前缀加 Opus 包：

```text
magic:"OP2C" | version:u16=1 | channels:u16=1或2 | sample_rate:u16=16000 | frame_samples:u16=320
[length:u16 little-endian][Opus payload:length bytes]
...
```

每个 Opus 包是 20 ms 的 16 kHz 音频，声道数与文件头一致，长度 1～100 字节，一段录音最多 3000 包（60 秒）。文件没有尾部填充或结束标记。

把各个 `0x0505.data` 按 `frame_offset` 拼接后，完整录音从第一个长度字段开始，不带设备文件管理元数据。`AudioFileInfo.data_size` 是这段编码数据的字节数。SDK 保存的 `.bin` 保持原始格式，便于重新解码。

## 录音怎样传到电脑

| 入口 | 设备交互 | SDK 接口 |
| --- | --- | --- |
| 普通提取 | `0x0503 → 0x0504` 取得文件信息，再用 `0x0506 → 0x0505` 按偏移读取；结束时 `0x0507 → 0x0508` | `download_audio_file(..., quick=False)` |
| 快速提取 | `0x0509 → 0x0504`，随后设备连续发送 `0x0505` | `download_audio_file(..., quick=True)`，默认方式 |
| `V2.001.0002.0000` 保存后主动发送 | 设备直接发送连续 `0x0505`，事先没有 `0x0504` | `receive_auto_audio_file()` |
| `V2.001.0002.0001` 保存后通知 | 设备发送 `0x050A`，SDK 再按普通提取下载 | `receive_auto_audio_file()` |
| 实时录音 | `0x050D → 0x050E` 订阅，按键录音时设备发送 `0x050F`、连续 `0x0510`、`0x0511` | `receive_live_audio_file()` |

每个 `0x0505` 包都有文件索引和 `frame_offset`。SDK 按偏移拼接，跳过已收到的重叠字节。快速提取遇到缺口或超时，会用 `0x0506` 请求缺失位置；连续补传超过 3 次仍不完整时抛出 `ProtocolError`。结果按 `AudioFileInfo.data_size` 截断。设备单帧数据区最大 4096 字节，SDK 的包体上限为 5120 字节。

固件 `V2.001.0002.0000` 主动发送发生在录音保存后，不需要应用先发提取命令。`receive_auto_audio_file()` 从首帧取得文件索引，返回 `(file_index, raw_audio)`。如果帧丢失，它会先用 `0x0503 → 0x0504` 核对文件长度，再按偏移补传；无法补齐就报错，不返回残缺录音。

固件 `V2.001.0002.0001` 保存后的 `0x050A` 只带文件索引。`receive_auto_audio_file()` 收到后走普通提取，结束或出错时都会发送 `0x0507` 释放文件。

仅实时发送的录音不保存在设备中，丢失的数据无法补传。选择同时保存时，可在设备保存完成后下载副本。`receive_live_audio_file()` 校验会话、序号、偏移和结束包里的计数，任一不符都会报错，不返回不完整的录音。成功后它把收到的 Opus 包封装成 OP2C，和下载得到的文件走同一条解码路径。

使用主动接收时，BLE 连接要在设备发送前建立。`receive_auto_audio_file()`、`download_audio_file()` 和 `read_audio_frame()` 会读取同一连接的 `0x0505` 队列，并发调用会被 SDK 拒绝（`ProtocolError`）。如果错过主动发送，查询录音数量后再按索引下载。

## 从 Speex / Opus 到 WAV

```text
Speex: .bin → 逐帧读取长度前缀 → Speex payload → 临时 Ogg Speex
            → ffmpeg 解码为 s16le PCM → 加 RIFF/WAV 头 → .wav
OP2C:  .bin → 校验文件头和每包长度 → Opus payload → 临时 Ogg Opus
            → ffmpeg 解码为 16 kHz 单声道或双声道 s16le PCM → 加 RIFF/WAV 头 → .wav
```

OP2C 按文件头中的声道数解码，调用方传入的 `pcm_config` 不会覆盖文件头。缺少 ffmpeg 时 Opus 路径抛出 `OpusDecoderUnavailable`。

`save_audio_bundle()` 先写入原始 `.bin`，再尝试生成 WAV。没有 `ffmpeg` 或解码失败时，原始文件仍在，函数会抛出 `SpeexDecoderUnavailable`、`OpusDecoderUnavailable` 或 `AudioDecodeError`。

`build_playable_audio()` 遇到已有的 WAV 会直接返回；其他路径还能识别 Ogg Speex 和无长度前缀的裸 Speex。返回的 `source_type` 可为 `wav`、`ogg-speex`、`packet-speex` 或 `raw-speex`。旧录音走 `packet-speex` 路径，Opus 录音按声道数返回 `opus-mono` 或 `opus-stereo`。只有裸 Speex 回退才使用 `quality` 和 `bits_size`：默认 `quality=3` 对应估算帧长 20 字节，显式传入的 `bits_size` 会覆盖该估算。

旧数据若带 1026 字节外层分块，可传入 `allow_framed_blocks=True`。底层 `parse_packetized_speex_stream()` 默认允许这种分块；`decode_speex_to_pcm()`、`build_playable_audio()`、`decode_audio_to_wav()` 和 `save_audio_bundle()` 默认不启用，调用高层函数时需显式指定。

`build_ogg_speex()` 只为解码临时封装 Ogg。Speex 头使用版本标记 `speex-1.2.1`、Wideband mode、16 kHz、单声道、每帧 320 个采样点、每包一帧；vendor comment 为 `openzilo-python`。音频包的 granule position 每包增加 320。`ffmpeg` 输出 `s16le` PCM，`build_wav_from_pcm()` 再写入 44 字节的 PCM WAV 头。若解码器为一个 Speex 包输出多帧且长度可整除，`normalize_decoded_speex_pcm()` 只保留每包的第一帧。SDK 默认不单独保存中间 Ogg 文件。

| 文件或数据 | 内容 | 能否直接播放 |
| --- | --- | --- |
| 设备 `.bin` | 带长度前缀的 Speex 帧，或 OP2C 文件 | 否 |
| `.spx` / `.ogg` | Ogg 容器中的 Speex | 支持 Speex 的播放器可以 |
| `s16le` PCM | 无容器的 16 bit 采样 | 需要另给采样率和声道数 |
| `.wav` | PCM 加 RIFF/WAV 头 | 可以 |

改扩展名不会改变数据格式。设备 `.bin` 要先拆出 Speex 或 Opus 包并封装、解码，才能得到 WAV。

## IMU 与动作事件

固件 `V2.001.0002.0001`：`start_sensor_report()` 启动采集和上报，`stop_sensor_report()` 或断线停止采集；重连后重新订阅。固件 `V2.001.0002.0000`：先进入手势模式，停止 BLE 上报后仍可继续本地检测。

SDK 支持两种 `0x0605` 成功包体：

- 单点：`error_code:u16 + sequence:u32 + timestamp_ms:u32 + 六轴:i16*6`，共 22 字节。
- 批量：`error_code:u16 + sequence_start:u32 + frame_count:u16 + sample_size:u16 + samples`，共 `10 + 16*N` 字节。

两种格式统一返回 `SensorDataBatch`；单点的 `frame_count=1`。下列事件格式在 `V2.001.0002.0000` 与 `V2.001.0002.0001` 中保留，采集条件和单击行为的变化见下文。

| 命令 | 事件 | 包体 |
| --- | --- | --- |
| `0x0701` | 普通双击 | `timestamp_ms:u32`（开机后毫秒数） |
| `0x0703` | 按键双击 | `u32` 秒级设备时间；SDK 字段名为 `timestamp_ms` |
| `0x0704` | 按键单击 | `u32` 秒级设备时间；SDK 字段名为 `timestamp_ms` |

`V2.001.0002.0001` 的敲击检测使用订阅开启的 IMU 数据，单击 `0x0704` 不再切换模式。`V2.001.0002.0000` 在手势模式下检测敲击，单击可切换模式。LED 是本地提示，SDK 无法查询其状态。

重连后客户端应重新开启实时上报，本地采集的恢复行为以对应固件为准。

## 联调时先查什么

- `.bin` 无法播放：这是原始 Speex 帧流或 OP2C 文件。用 `save_audio_bundle()` 生成 WAV，并确认安装了 `ffmpeg`。
- `ffmpeg` 报格式错误：检查文件是否从首个 2 字节小端长度字段开始，下载时是否按 `frame_offset` 拼接，是否把协议包字段混进了数据区。
- 收不到 `0x0605`：确认 `start_sensor_report()` 收到了成功的 `0x0602`；`V2.001.0002.0000` 先进入手势模式；`V2.001.0002.0001` 无需切换。
- 收到连续 `0x0505` 却没有 `0x0504`：这是保存后的主动发送，用 `receive_auto_audio_file()` 接收。

固件或协议升级时，先比对实机行为、`src/openzilo/` 和[协议参考](protocol.zh-CN.md)，再更新调用手册和本页。

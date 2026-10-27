# OpenZilo SDK 数据流

--8<-- "docs/_includes/devices.zh-CN.md"

--8<-- "docs/_includes/features.zh-CN.md:device-basics"

本文说明应用如何接收设备数据、保存录音和转换音频。调用方法见 [API 索引](python-sdk.zh-CN.md)，字节布局见[协议参考](protocol.zh-CN.md)。

## 连接与收包

使用 `connect_ring()` 连接并查询功能；使用 `OpenZiloClient` 时按[兼容说明](compatibility.zh-CN.md)显式查询。设备按地址连接，macOS 使用 UUID。

BLE 通知边界不等于协议包边界。使用 SDK 接口可直接取得完整响应或事件；自行处理传输时用 `PacketStream` 重组完整包。包头、CRC 或字段不合法会报告 `ProtocolError`，等待期间断线会报告 `TransportError`。

## 实时音频

--8<-- "docs/_includes/firmware-0001.zh-CN.md"

`open_live_audio_stream()` 通过 `async with` 管理订阅，通过 `async for` 输出录音开始、音频和结束事件。订阅成功不会自动开始录音；可由按键或远程命令启动。退出时会尝试退订。

PCM 输出为 16 kHz、有符号 16 位小端数据，每帧每声道 320 个采样点，双声道按左右交错排列。Opus 输出保留压缩音频包。应用应及时处理事件；处理过慢会明确报错。

只有收到并校验结束事件才能确认整段完整。纯实时输出丢失的数据无法补传；同时保存模式可在保存完成后下载设备副本。实时接收期间不要并发下载或升级固件。用法见[实时音频](sdk-live-audio.zh-CN.md)。

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

例如 `14 00` 表示下一帧 payload 长 20 字节。解析时要逐帧读取长度，不能按 20 字节固定切分。编码模式为 Speex Wideband；一帧对应 320 个 16 kHz 单声道采样点，即 20 ms。输出的 PCM 默认为 16 kHz、单声道、16 bit。

OP2C 文件先是 12 字节小端文件头，之后同样是长度前缀加 Opus 包：

```text
magic:"OP2C" | version:u16=1 | channels:u16=1或2 | sample_rate:u16=16000 | frame_samples:u16=320
[length:u16 little-endian][Opus payload:length bytes]
...
```

每个 Opus 包是 20 ms 的 16 kHz 音频，声道数与文件头一致，长度 1～100 字节，一段录音最多 3000 包（60 秒）。文件没有尾部填充或结束标记。

把各个 `0x0505.data` 按 `frame_offset` 拼接后，Speex 录音从第一个长度字段开始，OP2C 录音从文件头开始，不带设备文件管理元数据。`AudioFileInfo.data_size` 是这段编码数据的字节数。SDK 保存的 `.bin` 保持原始格式，便于重新解码。

## 录音传输与保存

`download_audio_file()` 下载已保存录音；`receive_auto_audio_file()` 等待保存通知或旧固件的主动传输。两者返回的音频可交给 `save_audio_bundle()`。实时接收返回的 OP2C 文件也使用相同的保存和解码接口。

自动接收需要在录音完成前建立连接并开始等待。错过传输时，先查询录音数量，再下载已有文件。同一连接上的录音下载、自动接收和实时接收应依次执行。用法见[录音下载](sdk-downloads.zh-CN.md)。

## 音频转换

`save_audio_bundle()` 保留原始 `.bin` 并尝试生成 WAV。转换已有 Speex／OP2C 文件需要 `ffmpeg`；实时 PCM 需要可选的 `pcm` 依赖。原始文件在解码失败时仍保留。

| 文件或数据 | 内容 | 播放方式 |
| --- | --- | --- |
| `.bin` | Speex 帧流或 OP2C 文件 | 通过 SDK 转换 |
| `.spx`／`.ogg` | Ogg Speex 音频 | 使用兼容播放器 |
| PCM | 无容器的采样数据 | 指定采样率、位深和声道 |
| `.wav` | 可播放音频文件 | 使用常见播放器 |

修改扩展名不会转换格式。OP2C 按文件头的声道数解码。参数和错误处理见[音频解码](sdk-audio-decoding.zh-CN.md)。

## IMU 与动作事件

`start_sensor_report()` 开启上报，`wait_sensor_data()` 接收样本，`stop_sensor_report()` 停止。`V2.001.0002.0000` 需先进入手势模式；`V2.001.0002.0001` 直接启动采集，断线后停止，重连需重新订阅。

IMU 和敲击事件使用开机后毫秒数；按键事件使用秒级设备时间，虽然 SDK 字段仍名为 `timestamp_ms`。不要直接比较两种时间。详情见 [IMU](sdk-imu.zh-CN.md)与[事件接收](sdk-events.zh-CN.md)。

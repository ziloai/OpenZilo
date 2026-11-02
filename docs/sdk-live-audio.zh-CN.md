# 实时音频

--8<-- "docs/_includes/devices.zh-CN.md"

接收按键录音的实时 Opus 或 PCM 数据。先用 `connect_ring()` 连接并查询功能，或在 `OpenZiloClient` 连接后调用 `get_device_capabilities()`。返回事件字段见[数据类型](sdk-data-types.zh-CN.md)。

以下代码片段使用 `import openzilo as sdk`；`ring` 表示已连接的客户端，完整连接示例见[快速开始](sdk-quickstart.zh-CN.md)。

## 实时接收录音

--8<-- "docs/_includes/firmware-0001.zh-CN.md"

```text
connect -> receive_live_audio_file 订阅 -> 用户长按录音并松开
        -> 设备实时发送 Opus 音频 -> SDK 退订 -> save_audio_bundle
```

```python
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    await sdk.get_device_capabilities(ring)
    recording = await sdk.receive_live_audio_file(
        ring,
        on_subscribed=lambda: print("请长按戒指录音，完成后松开"),
    )
    bundle = sdk.save_audio_bundle(
        file_index=0,
        data=recording.data,
        output_dir="audio",
    )
    print(bundle.play_path)
```

实时录音需要固件 **V2.001.0002.0001 或更新版本**。仅实时发送时，录音不保存在设备中，断线或丢包后无法补传。选择同时保存时，可在保存完成后下载设备副本。等 `on_subscribed` 回调后再让用户录音。

## `open_live_audio_stream()`：实时 PCM / Opus 事件流

--8<-- "docs/_includes/features.zh-CN.md:live-audio"

安装 PCM 解码依赖：`uv add "openzilo[pcm] @ git+https://github.com/ziloai/OpenZilo.git"`。PyAV 提供进程内解码，PCM 流不需要 `ffmpeg` 可执行文件；`output="opus"` 只需要基础 SDK。

```python
async with sdk.open_live_audio_stream(
    ring,
    output="pcm",             # 默认；也可选 "opus"
    queue_size=64,
    timeout_s=60.0,
    recording_timeout_s=70.0,
) as stream:
    print("订阅成功，现在可以长按录音键")
    async for event in stream:
        if isinstance(event, sdk.LiveAudioStart):
            print(event.sample_rate, event.channels)
        elif isinstance(event, sdk.LivePcmFrame):
            # data 是 16 kHz、16 位小端 PCM；声道数见 event.pcm_config。
            # 将音频交给其他任务做语音识别或播放。
            application_queue.put_nowait(event)
        elif isinstance(event, sdk.LiveAudioEnd):
            print("整段完整", event.sent_bytes)
```

`application_queue` 需由应用先创建，并在另一项任务中及时读取；示例省略了后续处理。队列满时应停止接收，或按应用需求处理。不要在接收循环中执行耗时的同步操作。取消、`break` 或异常退出时，必须保留 `async with` 来释放订阅；无需另行注册 `0x050F`～`0x0511` 监听器。

事件按顺序输出：

| 事件 | 含义 |
| --- | --- |
| `LiveAudioStart` | `session_id`、设备录音时间、`sample_rate=16000`、`channels=1` 或 `2`、`codec=3` |
| `LivePcmFrame` | PCM 模式：`session_id`、`sample_offset`、`sample_count=320`、`data`、`pcm_config` 包含实际声道数、16 kHz 采样率和 16 位采样深度 |
| `LiveAudioData` | Opus 模式：`session_id`、`sequence`、压缩字节 `byte_offset`、原始 Opus `data` |
| `LiveAudioEnd` | 录音结束事件，包含已检查的包数与字节数。 |

`sample_offset` 从 0 开始，每帧增加 320，表示每声道的采样位置；`sample_offset / 16000` 是相对音频时间，不是主机接收时间。每帧单声道为 640 字节、双声道为 1280 字节，不含 WAV 文件头。声道数与设备发送的一致，不做降噪或自动混音。`stream.start` 在收到 START 后可读，`stream.end` 和 `stream.complete` 仅在整段录音校验成功后设置。

进入上下文只等待订阅确认。`timeout_s` 分别限制订阅和等待 START；`recording_timeout_s` 限制 START 之后的接收，总包间等待上限为 5 秒。当前设备一段最多 60 秒，流接收一段后结束；下一段请重新打开上下文。

应用应及时消费音频事件，处理过慢会导致 `ProtocolError`。本机接收速度不能控制设备发送速度，不能依靠暂停读取来暂停录音。

收到并通过检查的 `LiveAudioEnd` 后，才能确认整段录音完整。已输出的 PCM 可能在随后遇到丢包、断线、错误 END 或解码失败，应用应区分尚未收完的音频和完整录音。取消与提前退出不产生成功 END；尚未结束的数据应视为部分音频。空录音可以包含 START 和 END 而没有音频帧。

缺少 PyAV 或无法初始化解码器时抛出 `OpusDecoderUnavailable`，在开启订阅前失败；解码失败抛出 `AudioDecodeError`。协议、设备、超时和断线异常与文件接收相同。退出会尝试退订；退订失败会记录警告，请断开重连后再进行音频操作或 OTA。流对象不可复用，也不能同时由多个任务读取。

取消操作后若连接无法继续使用，请断开重连，再执行音频或升级操作。

完整例子见 [examples/live_pcm.py](../examples/live_pcm.py)。

## `receive_live_audio_file()`

--8<-- "docs/_includes/firmware-0001.zh-CN.md"

作用：订阅实时录音，接收用户按键录下的一段音频，然后取消订阅。需要固件 **V2.001.0002.0001 或更新版本**。

签名：

```python
recording = await sdk.receive_live_audio_file(
    ring,
    on_packet=None,
    on_subscribed=None,
    timeout_s=60.0,
    recording_timeout_s=70.0,
)
```

参数：

- `on_subscribed`：设备确认订阅后调用，适合提示用户开始录音。
- `on_packet`：每收到一个校验通过的 `LiveAudioData` 调用一次。它是原始 Opus 包，整段是否完整要等函数返回才能确定。
- `timeout_s`：订阅和等待录音开始的最长秒数。
- `recording_timeout_s`：从开始到结束的总上限；两个包之间最多等待 5 秒。

两个回调可以是同步函数或协程，应尽快返回。该接口将实时收到的 Opus 音频整理成完整文件。回调处理过慢可能导致接收失败。需要 PCM 时使用 `open_live_audio_stream(output="pcm")`。

返回：`LiveAudioRecording`，其中 `data` 是完整 OP2C 文件，可直接传给 `save_audio_bundle()` 或 `decode_audio_to_wav()`。

异常：

- 订阅被拒绝（例如 ATT MTU 不足）或结束包带错误码：`DeviceError`。
- 会话、序号、偏移不连续，结束包计数不符或设备报告丢帧：`ProtocolError`。
- 等待期间 BLE 断开：`TransportError`。

注意：

- 仅实时发送时，录音**不保存在设备中**；同时保存模式可在录音结束后下载设备副本。
- 函数退出时会尝试退订，包括出错和取消的情况。录音完整但退订失败时仍返回录音，并在 `openzilo` 日志记录警告；此时请断开重连，再做下载或固件升级。
- 订阅时不能与下载、`receive_auto_audio_file()` 或固件升级同时运行。

低层的 `set_live_audio_subscription(client, enabled)` 只负责开关订阅，需要自行处理 `0x050F`～`0x0511`。关闭订阅会中止正在发送的实时录音；断线后订阅自动失效。

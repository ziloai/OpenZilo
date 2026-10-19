# 远程录音与录音设置

--8<-- "docs/_includes/devices.zh-CN.md"

用 Python 或命令行开始、停止录音，并设置声道、码率、增益和最长录音时间。录音可以保存在戒指中，也可以实时发送到电脑，或同时进行。

--8<-- "docs/_includes/features.zh-CN.md:recording-control"

## 用命令行录一段音频

--8<-- "docs/_includes/firmware-0001.zh-CN.md"

先选择设备，再录制 5 秒并下载到电脑：

```bash
uv run openzilo device use
uv run openzilo audio-record recordings/test.wav --seconds 5 --channels 1
```

生成 WAV 需要安装 `ffmpeg`。查看当前设置和录音状态：

```bash
uv run openzilo audio-config
uv run openzilo audio-status
```

完整命令见 [命令行指南](cli.zh-CN.md)。

## 用 Python 录音并保存

--8<-- "docs/_includes/firmware-0001.zh-CN.md"

将 `ADDRESS` 替换成扫描得到的地址。示例把录音保存在戒指中，5 秒后自动结束，确认保存完成后再下载：

```python
import asyncio
import openzilo as sdk

ADDRESS = "AA:BB:CC:DD:EE:FF"

async def main():
    ring = await sdk.connect_ring(address=ADDRESS)
    try:
        if not ring.capabilities.supports("recording_control"):
            print("当前设备没有提供可用的远程录音接口")
            return
        config = sdk.AudioRecordingConfig(
            output=sdk.AudioOutput.FLASH,
            channels=1,
            bitrate=16000,
            max_duration_ms=5000,
        )
        await sdk.set_audio_recording_config(ring, config)
        session_id = await sdk.start_audio_recording(ring)
        status = await sdk.wait_audio_recording_finished(ring, session_id)
        if status.saved:
            info, data = await sdk.download_audio_file(ring, status.file_index)
            bundle = sdk.save_audio_bundle(
                file_index=info.file_index, data=data, output_dir="recordings",
            )
            print(bundle.play_path)
    finally:
        await ring.disconnect()

asyncio.run(main())
```

## 调整录音设置

--8<-- "docs/_includes/firmware-0001.zh-CN.md"

用 `get_audio_recording_config()` 读取，用 `set_audio_recording_config()` 修改。设置只能在未录音时修改；断开重连后保留，设备重启后恢复默认值。

| 设置 | 参数 | 可选值或范围 |
| --- | --- | --- |
| 输出方式 | `output` | `AUTO` 自动选择、`FLASH` 保存在设备、`LIVE` 实时发送、`LIVE_AND_FLASH` 同时发送和保存 |
| 声道 | `channels` | 1 或 2 |
| 码率 | `bitrate` | 8000–32000 bit/s |
| 数字增益 | `gain_left_q8`、`gain_right_q8` | 0–1024，256 表示 1 倍 |
| 最长录音时间 | `max_duration_ms` | 20–60000 毫秒，须为 20 的整数倍 |
| 断线处理 | `disconnect_policy` | `STOP` 停止，或 `CONTINUE_SAVING` 继续保存在设备 |

采样率固定为 16 kHz，每帧 20 ms。设备还会返回自己允许的参数范围，SDK 会在发送设置前检查。Opus 编码器的其余固定参数可以读取，不能通过此接口修改。

`CONTINUE_SAVING` 只能与 `FLASH` 或 `LIVE_AND_FLASH` 搭配使用。

## 提前结束或取消录音

--8<-- "docs/_includes/firmware-0001.zh-CN.md"

`start_audio_recording()` 返回本次录音的 `session_id`，不表示录音已经结束。提前停止时执行：

```python
await sdk.stop_audio_recording(ring, session_id)
status = await sdk.wait_audio_recording_finished(ring, session_id)
```

如需丢弃尚未保存的录音，传入 `cancel=True`。停止命令收到响应后，仍需查询或等待录音完成，才能确认文件是否保存。

如果开始命令超时，先调用 `get_audio_recording_status()` 查询，避免重复发送开始命令。`session_id` 只在本次设备启动期间有效，重启后不能沿用。

## 实时发送并保留设备副本

--8<-- "docs/_includes/firmware-0001.zh-CN.md"

选择 `LIVE` 或 `LIVE_AND_FLASH` 时，要先订阅实时音频，再开始录音。可在 `receive_live_audio_file()` 的 `on_subscribed` 回调里调用 `start_audio_recording()`。完整示例见 [remote_recording.py](../examples/remote_recording.py)。

实时传输中断后不能续接这一段音频。选择同时保存时，设备上的副本可在录音保存完成后单独下载。仅实时发送时，断线会使该次传输失败。

## 接口速查

--8<-- "docs/_includes/firmware-0001.zh-CN.md"

| 接口 | 返回结果 |
| --- | --- |
| `get_audio_recording_config(ring)` | 当前录音设置 `AudioRecordingConfig` |
| `set_audio_recording_config(ring, config)` | 设备返回的录音设置 |
| `start_audio_recording(ring)` | 本次录音编号 `session_id` |
| `stop_audio_recording(ring, session_id, cancel=False)` | 设备确认的录音编号 |
| `get_audio_recording_status(ring)` | `AudioRecordingStatus`，含状态、是否保存、文件索引与错误码 |
| `wait_audio_recording_finished(ring, session_id, timeout_s=75.0, poll_interval_s=0.2)` | 录音结束后的状态；失败时抛出异常 |

上表除等待结束接口外，均可用 `timeout_s` 设置单次请求超时。以上接口均需通过 `await` 调用。

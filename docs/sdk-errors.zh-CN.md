# 异常与问题排查

--8<-- "docs/_includes/devices.zh-CN.md"

按异常类型判断失败原因，再检查连接、设备状态和调用顺序。

## 异常类型

```python
OpenZiloError
# SDK 异常基类。只想统一捕获 SDK 异常时捕获这个类型。

TransportError
# BLE 传输异常，例如未安装 bleak、找不到设备、连接失败、未连接时写入或等待期间连接断开。

ProtocolError
# 协议异常，例如包头、CRC、包体长度、字段解析不符合预期。

TimeoutError
# 请求在排队、写入或等待响应阶段超时，或等待主动上报超时。写入被中断后需重连。

DeviceError
error_code: int  # 设备返回的非 0 错误码。
# 设备明确返回错误时抛出，例如 busy、参数错误、文件不存在。

AudioDecodeError
# 录音数据无法解码为可播放 WAV，或 ffmpeg 30 秒内未完成。

SpeexDecoderUnavailable
# 缺少 ffmpeg 或自定义 Speex 解码器不可用。

OpusDecoderUnavailable
# 缺少 ffmpeg，无法解码 OP2C 录音。
```

## `TransportError: Install bleak to use BLE transport`

当前 Python 环境没有安装 SDK 的依赖。请在运行脚本的项目中从 GitHub 安装 SDK，并使用 `uv run` 执行脚本：

```powershell
uv add git+https://github.com/ziloai/OpenZilo.git
uv run python your_script.py
```

## 扫描不到设备或连接失败

- 使用扫描返回的设备地址，macOS 使用 UUID；SDK 不按广播名称筛选。
- 确认戒指正在广播，且没有被其他程序保持连接。
- Windows 上可以尝试关闭再打开蓝牙适配器。
- PyCharm 中确认解释器和安装依赖的虚拟环境一致。

## `Timed out waiting for command ...`

表示指定响应或事件没有在超时时间内到达。常见原因：

- 设备忙，例如正在录音、写 Flash、传输大文件。
- 业务代码同时发起多个命令请求，导致响应被其他任务取走。
- 在 `V2.001.0002.0000` 中尚未进入手势模式，或在 `V2.001.0002.0001` 中尚未启动 IMU 采集。

建议同一连接上同一时间只发起一个“命令-响应”类请求。

## `receive_auto_audio_file()` 等待超时

首帧超时表示 SDK 在限定时间内没有收到录音保存后的 `0x050A` 或主动上报的 `0x0505`。确认调用期间 BLE 始终连接，并在开始等待后再让用户长按录音、松开。若程序连接过晚，设备可能已经发送完毕，此时应调用 `get_audio_file_count()` 查询文件，再用 `download_audio_file()` 重新下载。

不要让 `receive_auto_audio_file()` 与 `download_audio_file()`、`read_audio_frame()` 或手工 `wait_for_command(0x0505)` 并发运行；它们读取同一个 `0x0505` 接收队列，可能造成某个接收流程超时或出现偏移缺口。

## `start_sensor_report()` 返回设备忙碌

先结束冲突操作。固件 `V2.001.0002.0000` 需先用按键进入手势模式；`V2.001.0002.0001` 直接调用 `start_sensor_report()`。确认成功响应后再等待数据。

## 录音可以下载但不能解码

确认安装了 `ffmpeg`，并且命令行能执行 `ffmpeg -version`。如果只需要保存原始录音，可以直接保留 `download_audio_file()` 返回的 `bytes` 或 `save_audio_bundle()` 生成的 raw 文件。

## 清空录音后能恢复吗

该函数会删除设备保存的所有录音，成功后无法通过 SDK 恢复。业务代码应把它放在明确的维护或测试入口中，不要在普通启动流程里自动调用。

# 版本升级与固件差异

--8<-- "docs/_includes/devices.zh-CN.md"

升级 SDK 时检查接口变化；更换固件时重新查询功能。SDK 与固件分别编号，不能只按版本号大小判断兼容性。

## BLE 写入分片与 0.3.x 迁移

BLE 分片由 SDK 自动处理，应用无需配置分片长度。

从 `0.4.0` 开始，`NusClient` 不再接受 `write_chunk_size` 参数。使用 `0.3.x` 自定义传输的代码需要移除该参数：

```python
# 0.3.x 旧写法，不再支持
# transport = sdk.NusClient(address=ADDRESS, write_chunk_size=20)

# 0.4.0
transport = sdk.NusClient(address=ADDRESS)
ring = sdk.OpenZiloClient(transport=transport)
```

## 不同固件的使用差异

从 `V2.001.0002.0000` 升级到 `V2.001.0002.0001` 时，应用需留意：

- **远程录音与设置**：`V2.001.0002.0001` 新增开始、停止、状态查询，以及声道、码率、增益和时长配置；`V2.001.0002.0000` 没有这些接口。
- **实时音频**：`V2.001.0002.0001` 新增实时 Opus 输出，可由 SDK 解码为 PCM；`V2.001.0002.0000` 在录音保存后传输文件。
- **录音格式**：`V2.001.0002.0000` 为 Speex；`V2.001.0002.0001` 新录音使用单／双声道 Opus（OP2C），默认双声道。已有 Speex 文件仍可由 SDK 解码。
- **保存通知**：`V2.001.0002.0000` 保存后主动发送 `0x0505`；`V2.001.0002.0001` 用 `0x050A` 通知，随后下载文件。继续使用 `receive_auto_audio_file()` 即可。
- **IMU**：`V2.001.0002.0000` 需先进入手势模式；`V2.001.0002.0001` 由 `0x0601` 启动采集，`0x0603` 或断线停止，重连后需重新订阅。
- **单击与敲击**：`V2.001.0002.0001` 取消录音／手势模式切换，单击只上报事件；敲击检测随 IMU 订阅开启，不再单独维持后台采集。

SDK 调用入口分别见[远程录音](recording-control.zh-CN.md)、[实时音频](sdk-live-audio.zh-CN.md)、[IMU](sdk-imu.zh-CN.md)和[事件接收](sdk-events.zh-CN.md)。

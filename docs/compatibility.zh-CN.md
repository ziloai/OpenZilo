# SDK 与固件兼容

--8<-- "docs/_includes/devices.zh-CN.md"

--8<-- "docs/_includes/features.zh-CN.md:capabilities"

连接成功表示蓝牙通信已经建立。要使用远程录音、实时音频、IMU 或固件升级，还需要确认设备支持对应接口。

## 推荐连接方式

`connect_ring()` 默认查询设备支持的功能。连接后通过 `ring.capabilities` 查看结果：

```python
import asyncio
import openzilo as sdk

ADDRESS = "AA:BB:CC:DD:EE:FF"

async def main():
    ring = await sdk.connect_ring(address=ADDRESS, auto_time_sync=True)
    try:
        capabilities = ring.capabilities
        print("固件：", capabilities.firmware_version)
        print("型号：", capabilities.model)
        if capabilities.supports("recording_control"):
            print(await sdk.get_audio_recording_config(ring))
    finally:
        await ring.disconnect()

asyncio.run(main())
```

如果用 `async with sdk.OpenZiloClient(...)` 建立连接，请在调用上述功能前执行：

```python
capabilities = await sdk.get_device_capabilities(ring)
```

命令行中的远程录音、实时音频、IMU 和 OTA 操作会自动执行查询。读取系统信息、日志、下载已有录音和校时不依赖这项查询。

## 查询结果从哪里来

固件 `V2.001.0002.0000` 与 `V2.001.0002.0001` 的发行包没有功能查询命令，SDK 对已内置的完整版本使用配置匹配。本文说明功能查询与错误处理；远程录音等功能的最低固件版本直接标在对应使用小节前。


`DeviceCapabilities.source` 表示支持信息的来源：

| 返回值 | 含义 |
| --- | --- |
| `device` | 设备返回了功能列表，SDK 同时核对型号和固件版本。 |
| `legacy_profile` | 旧固件没有提供功能列表，SDK 按完整固件版本与型号使用内置配置。 |
| `unknown` | 没有取得功能列表，也没有匹配的内置配置。 |

旧固件配置仅对 SDK 明确识别的型号和完整版本生效，不能仅按版本前缀推断兼容性。查询超时表示没有取得结果，并不表示设备一定缺少该功能。

## 如何判断功能是否可用

用 `capabilities.supports("功能名")` 检查。常用功能名如下：

| 功能名 | 用途 |
| --- | --- |
| `recording_control` | 开始、停止录音及修改录音设置 |
| `live_audio` | 实时接收音频 |
| `imu` | 接收加速度计和陀螺仪数据 |
| `key_events` | 接收按键事件 |
| `double_tap` | 接收敲击事件 |
| `ota` | 升级应用固件 |

SDK 会同时检查接口主版本。例如 `imu/2` 表示 IMU 接口第 2 版，订阅时直接启动采集；需要先切换手势模式的旧接口不能仅因名称相同就视作第 2 版。

修改录音设置时，还会检查设备允许的声道数、码率、增益、时长和输出方式。断线后继续保存要求选择设备存储或同时保存，不能只选择实时发送。

## 出错后怎么处理

| 异常 | 常见原因 | 处理方式 |
| --- | --- | --- |
| `CompatibilityError` | 功能不在支持列表中、接口版本不同，或录音参数超出范围 | 查看功能列表和参数范围，调整调用或选择适用固件。 |
| `DeviceError` | 设备拒绝命令，例如正在执行其他操作 | 查看 `error_code`，结束冲突操作后再试。 |
| `TimeoutError` | 指定时间内没有收到响应 | 检查连接；重新连接后再查询。录音开始超时后先查状态，避免重复录音。 |
| `ProtocolError` | 响应缺少字段或内容不一致 | 记录 SDK 版本、固件版本及错误，提交问题反馈。 |

查询结果只在当前连接期间有效。断开连接后 SDK 会清除结果；OTA 完成并重新连接后也会重新查询。旧固件查询失败后，如需再次查询，请先断开重连。

## 查看诊断信息

```bash
uv run openzilo --version
uv run openzilo device capabilities
uv run openzilo doctor
```

`device capabilities` 输出 JSON 格式的设备功能和录音参数范围；`doctor` 还显示 SDK 版本、运行环境标识和 PyAV 安装情况。反馈问题时附上这些信息，并移除设备地址、序列号和私人录音。

## 高级连接选项

`allow_unverified_features=True` 允许在查询结果为 `unknown` 时继续调用功能，适用于调用方已经掌握设备接口的情况。它不会绕过设备明确返回的接口版本不兼容。CLI 对应参数为 `--allow-unverified-features`。

`negotiate_capabilities=False` 关闭自动查询，调用方需自行确认固件支持的接口。它与 `OpenZiloClient` 的默认连接行为一致。

## 协议字段

需要自行实现客户端时，请阅读 [功能查询消息格式](protocol.zh-CN.md#功能查询消息格式)。一般应用只需使用上述 SDK 接口。

# 功能与版本要求

--8<-- "docs/_includes/devices.zh-CN.md"

先查看戒指的固件版本，再确认它支持你要使用的功能。SDK 版本、固件版本和通信协议版本分别编号，不能用其中一个代替另一个。

## 查看版本和可用功能

在仓库目录运行：

```bash
uv run openzilo --version
uv run openzilo device use
uv run openzilo info
uv run openzilo device capabilities
```

`--version` 显示 SDK 版本，`info` 显示设备型号和固件版本，`device capabilities` 列出设备支持的功能及录音参数范围。

在 Python 中，可以先检查功能再调用：

```python
import asyncio
import openzilo as sdk

ADDRESS = "AA:BB:CC:DD:EE:FF"  # 替换为扫描得到的设备地址

async def main():
    ring = await sdk.connect_ring(address=ADDRESS)
    try:
        info = await sdk.get_system_info(ring)
        print("固件版本：", info.firmware_version)
        if ring.capabilities.supports("recording_control"):
            config = await sdk.get_audio_recording_config(ring)
            print("录音设置：", config)
        else:
            print("当前设备没有提供可用的远程录音接口")
    finally:
        await ring.disconnect()

asyncio.run(main())
```

`supports()` 检查设备与 SDK 是否支持同一版本的功能接口。详细说明见 [SDK 与固件兼容](compatibility.zh-CN.md)。

## 各功能的使用要求

--8<-- "docs/_includes/features.zh-CN.md"

## 版本说明怎么看

- **自固件 XXX 起支持**：该功能从指定固件版本开始提供。
- **自 SDK XXX 起支持**：调用该功能需要指定 SDK 版本或后续兼容版本。
- **本页适用于固件 XXX**：页面描述的是该版本的操作方式，其他版本请结合发行说明使用。

远程录音、录音设置和实时音频从 `V2.001.0002.0001` 开始提供；具体用法前写明最低固件版本。`V2.001.0002.0000` 与 `V2.001.0002.0001` 的其余行为变化见[版本升级说明](sdk-migration.zh-CN.md)。

## 下载固件

前往 [官方固件发行页面](https://github.com/ziloai/OpenZilo-Hardware/releases)，查看型号、适用硬件和允许升级的起始版本，再按 [固件升级指南](../wiki/Firmware-Updates-zh-CN.md)操作。

# 快速开始

--8<-- "docs/_includes/devices.zh-CN.md"

本页完成第一件事：连接戒指，读取型号、固件版本和电量，再断开连接。先按[安装说明](sdk-install.zh-CN.md)安装 SDK。

## 扫描设备

在 SDK 仓库目录运行以下命令，记下输出中的设备地址。使用自己的 uv 项目时，命令相同。

```bash
uv run openzilo scan
```

## 连接并读取信息

把 `AA:BB:CC:DD:EE:FF` 替换成扫描得到的设备地址；macOS 使用扫描返回的 UUID：

```python
import asyncio
import openzilo as sdk

ADDRESS = "AA:BB:CC:DD:EE:FF"


async def main() -> None:
    ring = await sdk.connect_ring(address=ADDRESS)
    try:
        info = await sdk.get_system_info(ring)
        print(info.model, info.firmware_version, info.battery_percent)
    finally:
        await ring.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
```

`ring` 是已经连接的 `OpenZiloClient` 对象。所有需要访问设备的高层函数都把它作为第一个参数，例如 `sdk.get_system_info(ring)`。

## 运行示例

将上面的代码保存为 `connect.py`，替换设备地址后运行：

```bash
uv run python connect.py
```

程序打印型号、固件版本和电量后断开连接。接下来可以[查询设备功能](compatibility.zh-CN.md)，或按首页的功能列表继续。

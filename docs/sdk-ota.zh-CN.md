# 通过 SDK 升级固件

--8<-- "docs/_includes/devices.zh-CN.md"

使用 Python SDK 发送官方应用固件包，并在设备重启后核对版本。先查询设备功能；固件下载和设备操作见[固件升级指南](../wiki/Firmware-Updates-zh-CN.md)。

以下代码片段使用 `import openzilo as sdk`；`ring` 表示已连接的客户端，完整连接示例见[快速开始](sdk-quickstart.zh-CN.md)。

## 固件升级

--8<-- "docs/_includes/features.zh-CN.md:ota"

`update_firmware()` 和 `ota-update` 提供应用固件升级；可通过 `openzilo ota-update --help` 检查当前安装的命令。它们只处理应用固件升级，不升级 bootloader。升级包需来自官方发布说明，并明确兼容设备型号和起始版本。升级前备份重要录音，停止录音、下载与 IMU 上报，保持电量和连接稳定；调用期间该连接由升级操作独占。

```python
from pathlib import Path

async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    await sdk.get_device_capabilities(ring)
    info = await sdk.update_firmware(
        ring,
        Path("path/to/official-update.bin").read_bytes(),
        version="V2.001.0002.0001",
        sha256="SHA256_FROM_RELEASE",
        expected_model="MODEL_FROM_RELEASE",
        progress=lambda sent, total: print(f"Transferred: {sent}/{total}"),
    )
    print("重启后已确认版本：", info.firmware_version)
```

路径、SHA-256 和型号都是占位值，需替换为发布说明中的实际值。SDK 原样发送升级包，不解析其中的固件内容。完整可运行示例见 [update_firmware.py](../examples/update_firmware.py)。

| 参数 | 含义 |
| --- | --- |
| `client` / `firmware` | 已连接的客户端与完整升级包字节。 |
| `version` | 必填目标版本，须与升级包的完整运行版本一致，例如 `V2.001.0002.0000` 或 `V2.001.0002.0000-prod-1234abcd`；也接受 `-debug-8位十六进制哈希` 后缀。重启后精确匹配，不忽略后缀。设备已运行此版本时拒绝重复升级。 |
| `sha256=None` | 可选的 64 位十六进制 SHA-256；建议传入官方值。校验失败时不发送升级请求。 |
| `expected_model=None` | 可选型号，必须与设备信息中的 `model` 完全相同。仍需自行确认起始版本兼容。 |
| `progress=None` | 同步回调 `(sent, total)`，单位字节；只反映传输进度。设备请求续传时可能跳过已接收的前缀。 |
| `timeout_s=30.0` | 单次设备检查、传输或重连操作的超时。 |
| `total_timeout_s=600.0` | 升级前的设备检查和传输阶段的总上限。 |
| `reboot_timeout_s=90.0` | 传输确认之后，等待重启、重连和版本核验的总上限。 |

返回 `SystemInfo`，来源于设备重启并重连后的查询。SDK 确认设备没有变化、固件版本符合目标后才成功返回；**进度到达 100% 或蓝牙断开都不表示升级成功**。设备拒绝升级时抛出 `DeviceError`；超时、通信中断或异常响应分别通过 `TimeoutError`、`TransportError` 或 `ProtocolError` 报告。取消操作不会撤销设备已收到的升级包，失败后应重连读取版本确认状态。

官方发布信息、失败处理见 [固件升级指南](../wiki/Firmware-Updates-zh-CN.md)。

# 通过 SDK 升级固件

--8<-- "docs/_includes/devices.zh-CN.md"

使用 Python SDK 发送官方应用固件包，并在设备重启后核对版本。先查询设备功能；固件下载和设备操作见[固件升级指南](../wiki/Firmware-Updates-zh-CN.md)。

以下代码片段使用 `import openzilo as sdk`；`ring` 表示已连接的客户端，完整连接示例见[快速开始](sdk-quickstart.zh-CN.md)。

## 固件升级

--8<-- "docs/_includes/features.zh-CN.md:ota"

`update_firmware()` 和 `ota-update` 提供应用固件升级；可通过 `openzilo ota-update --help` 检查当前安装的命令。它们只处理应用固件升级，不升级 bootloader。升级包需来自官方发布说明，并明确兼容设备型号和起始版本。升级前备份重要录音，停止录音、下载与 IMU 上报，保持电量和连接稳定；调用期间该连接由升级操作独占。

固件打包生成带完整版本号的 `ring_sound-V2.001.0002.0001-prod-1234abcd.ota.zip`，包含 `manifest.json`、`manifest.sig` 和 `app.ota.bin`。清单携带版本、型号、板型、测试或生产配置、安全版本、允许的起始版本，以及内部 OTA 的大小和 SHA-256。外层可复用固件的 P-256 签名密钥；SDK 仅使用通过独立可信渠道取得的公钥，不能直接信任下载包附带的公钥。

```python
from pathlib import Path

bundle = Path("ring_sound-V2.001.0002.0001-prod-1234abcd.ota.zip").read_bytes()
public_key = Path("trusted-signing-public.pem").read_bytes()
metadata = sdk.inspect_firmware_bundle(bundle, trusted_public_key=public_key)
print(metadata.version, metadata.model, metadata.board)
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    info = await sdk.update_firmware(ring, bundle, trusted_public_key=public_key)
```

离线展示全部已验证元数据，无需连接戒指：

```bash
openzilo ota-inspect ring_sound-V2.001.0002.0001-prod-1234abcd.ota.zip --public-key trusted-signing-public.pem
# 加上 --json 可供程序读取
```

`inspect_firmware_bundle()` 返回的 `FirmwareBundle.manifest` 是完整已验证清单的字典副本。验签失败时命令返回失败，不输出成功标记。验签通过说明来源和完整性有效；设备适配仍需在发送前检查。

```bash
openzilo ota-update --address ADDRESS ring_sound-V2.001.0002.0001-prod-1234abcd.ota.zip --public-key trusted-signing-public.pem
```

板型比较会忽略重复的 `/`，以兼容 Zephyr qualifiers 自带前导斜杠的写法。展示和验签仍保留原始元数据。

离线检查包括签名、归档结构、长度、摘要和加密头。发送 OTA 前，SDK 核对设备型号、板型和起始版本。`source_versions=[]` 表示不限制起始版本。测试包需显式传入 `allow_test_firmware=True` 或 `--allow-test-firmware`。设备无法报告板型时，只能使用 SDK 已核实的精确旧构建配置；目前覆盖 `Open Zilo` 的 `V2.001.0002.0001-prod-7fd1dfc9`，其板型取自对应交付元数据，其他未知板型拒绝升级。安全版本和加密密钥匹配仍由设备检查，SDK 不解密，也不能读取防回滚计数。校验后只传输内部 OTA 字节，重启后继续核对完整运行版本。

OTA 接口只接受签名 ZIP，拒绝原始 BIN。目标版本和适配字段来自已验签的元数据，不再接受手填 `version`、`sha256` 或 `expected_model`。重启后精确比较完整运行版本，包括 debug/prod 和提交后缀；设备已运行目标版本时拒绝重复升级。完整示例见 [update_firmware.py](../examples/update_firmware.py)。

| 参数 | 含义 |
| --- | --- |
| `client` / `firmware` | 已连接的客户端与完整升级包字节。 |
| `trusted_public_key` | ZIP 必填的可信 PEM P-256 公钥字节。 |
| `allow_test_firmware=False` | 是否显式允许测试配置 ZIP。 |
| `progress=None` | 同步回调 `(sent, total)`，单位字节；只反映传输进度。设备请求续传时可能跳过已接收的前缀。 |
| `timeout_s=30.0` | 单次设备检查、传输或重连操作的超时。 |
| `total_timeout_s=600.0` | 升级前的设备检查和传输阶段的总上限。 |
| `reboot_timeout_s=90.0` | 传输确认之后，等待重启、重连和版本核验的总上限。 |

返回 `SystemInfo`，来源于设备重启并重连后的查询。SDK 确认设备没有变化、固件版本符合目标后才成功返回；**进度到达 100% 或蓝牙断开都不表示升级成功**。设备拒绝升级时抛出 `DeviceError`；超时、通信中断或异常响应分别通过 `TimeoutError`、`TransportError` 或 `ProtocolError` 报告。取消操作不会撤销设备已收到的升级包，失败后应重连读取版本确认状态。

官方发布信息、失败处理见 [固件升级指南](../wiki/Firmware-Updates-zh-CN.md)。

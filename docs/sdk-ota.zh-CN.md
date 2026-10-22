# 通过 SDK 升级固件

--8<-- "docs/_includes/devices.zh-CN.md"

使用 Python SDK 发送官方应用固件包，并在设备重启后核对版本。先查询设备功能；固件下载和设备操作见[固件升级指南](../wiki/Firmware-Updates-zh-CN.md)。

以下代码片段使用 `import openzilo as sdk`；`ring` 表示已连接的客户端，完整连接示例见[快速开始](sdk-quickstart.zh-CN.md)。

## 固件升级

--8<-- "docs/_includes/features.zh-CN.md:ota"

`update_firmware()` 和 `ota-update` 提供应用固件升级；可通过 `openzilo ota-update --help` 检查当前安装的命令。它们只处理应用固件升级，不升级 bootloader。升级包需来自官方发布说明，并明确兼容设备型号和起始版本。升级前备份重要录音，停止录音、下载与 IMU 上报，保持电量和连接稳定；调用期间该连接由升级操作独占。

Firmware packaging now produces `ring_sound-V2.001.0002.0001-prod-1234abcd.ota.zip` with `manifest.json`, `manifest.sig`, and `app.ota.bin`. The manifest carries version, model, board, test/production profile, security version, allowed source versions, and payload size/SHA-256. The outer signature can reuse the firmware P-256 signing key. Obtain the verification public key independently through a trusted channel; a key supplied inside a download is not a trust anchor.

```python
from pathlib import Path

bundle = Path("ring_sound-V2.001.0002.0001-prod-1234abcd.ota.zip").read_bytes()
public_key = Path("trusted-signing-public.pem").read_bytes()
metadata = sdk.inspect_firmware_bundle(bundle, trusted_public_key=public_key)
print(metadata.version, metadata.model, metadata.board)
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    info = await sdk.update_firmware(ring, bundle, trusted_public_key=public_key)
```

Display all verified metadata offline, without connecting to a ring:

```bash
openzilo ota-inspect ring_sound-V2.001.0002.0001-prod-1234abcd.ota.zip --public-key trusted-signing-public.pem
# Add --json for machine-readable output.
```

`inspect_firmware_bundle()` returns a `FirmwareBundle` whose `manifest` property is a fresh dictionary of all verified fields. Invalid signatures fail without a success marker. Successful inspection establishes package authenticity and integrity; device compatibility is checked before uploading.

```bash
openzilo ota-update --address ADDRESS ring_sound-V2.001.0002.0001-prod-1234abcd.ota.zip --public-key trusted-signing-public.pem
```

Board comparison ignores repeated `/` separators to support Zephyr qualifiers with a leading slash. Display and signature verification preserve the original metadata.

Offline checks cover signature, archive structure, lengths, digest and encryption header. Before OTA starts, the SDK checks device model, board and source version. An empty `source_versions` explicitly allows any starting version. Test bundles require `allow_test_firmware=True` or `--allow-test-firmware`. When a device cannot report its board, only an exact verified legacy profile may supply it. Currently this covers `Open Zilo` firmware `V2.001.0002.0001-prod-7fd1dfc9`, whose board is recorded in that build’s delivery metadata. Other unknown boards are rejected. Security-version enforcement and matching device encryption keys remain device checks: the SDK cannot decrypt or read rollback counters. Only the inner OTA bytes are transmitted, and the running version is still checked after reboot.

OTA accepts only this signed ZIP format and rejects raw BIN input. The target version and compatibility fields come from verified metadata; `version`, `sha256`, and `expected_model` overrides have been removed. The full runtime version, including debug/prod and commit suffixes, is compared after reboot. Updating to the already running version is rejected. See [update_firmware.py](../examples/update_firmware.py) for a runnable example.

| 参数 | 含义 |
| --- | --- |
| `client` / `firmware` | 已连接的客户端与完整升级包字节。 |
| `trusted_public_key` | Trusted PEM P-256 public key bytes, required for ZIPs. |
| `allow_test_firmware=False` | Explicitly permit test ZIPs. |
| `progress=None` | 同步回调 `(sent, total)`，单位字节；只反映传输进度。设备请求续传时可能跳过已接收的前缀。 |
| `timeout_s=30.0` | 单次设备检查、传输或重连操作的超时。 |
| `total_timeout_s=600.0` | 升级前的设备检查和传输阶段的总上限。 |
| `reboot_timeout_s=90.0` | 传输确认之后，等待重启、重连和版本核验的总上限。 |

返回 `SystemInfo`，来源于设备重启并重连后的查询。SDK 确认设备没有变化、固件版本符合目标后才成功返回；**进度到达 100% 或蓝牙断开都不表示升级成功**。设备拒绝升级时抛出 `DeviceError`；超时、通信中断或异常响应分别通过 `TimeoutError`、`TransportError` 或 `ProtocolError` 报告。取消操作不会撤销设备已收到的升级包，失败后应重连读取版本确认状态。

官方发布信息、失败处理见 [固件升级指南](../wiki/Firmware-Updates-zh-CN.md)。

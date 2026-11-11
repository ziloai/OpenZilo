<a id="changelog"></a>

# 更新日志

## 0.6.3 - 2026-11-11

<a id="connection-signal-strength"></a>

### 连接信号强度

- 新增 `get_connection_rssi()` 和 `openzilo rssi`，在受支持的固件上查询当前连接信号强度，单位为 dBm。
- 查询前检查设备能力，串行处理 RSSI 请求；超时、取消或响应格式异常导致结果不明确时，要求重新连接后再查询。

<a id="unlimited-recording"></a>

### 不限时录音

- 支持 `AudioRecordingConfig(max_duration_ms=0)`，在固件 `V2.001.0002.0002` 及以上版本启用不限时录音。
- SDK 默认录音上限仍为 60000 毫秒；有限时长仍为 20–60000 毫秒，须为 20 的整数倍。

<a id="documentation"></a>

### 文档

- 同步中英文功能要求、示例与适配说明。
- 公开文档聚焦受支持的接口、协议约定及可观察行为。


## 0.6.2 - 2026-10-22

<a id="signed-firmware-bundles"></a>

### 签名固件包

- 新增 `inspect_firmware_bundle()` 和 `ota-inspect`，支持离线验签和完整元数据展示，包括 JSON 输出。
- 升级开始前验证清单签名、签名密钥标识、内部数据摘要、长度和加密应用固件头。
- 发送内部 OTA 数据前核对设备型号、板型和允许的起始版本；重启后重新连接，核对完整运行版本。
- 测试配置包需显式允许。验签公钥必须通过独立可信渠道取得，不能直接信任下载包附带的公钥。

<a id="local-imu-calibration"></a>

### 本机 IMU 校准

- 新增加速度计六面拟合、陀螺仪静止零偏拟合和独立验证。
- 已验证的配置保存在本机，并绑定设备标识、型号、完整固件版本和传感器量程。
- 新增 `imu-calibrate` 和显式校正数据流，以 g 和度/秒输出，保留原始数据流并避免重复校正。
- 校准全部在电脑端完成，不向戒指写入校准参数；受支持的 IMU 功能契约无需为此升级固件。

<a id="breaking-change-and-migration"></a>

### 不兼容改动与迁移

`update_firmware()` 和 `ota-update` 现在只接受签名 OTA ZIP。原始 BIN 输入及 `version`、`sha256`、`expected_model` 覆盖参数已移除，版本和适配信息改为从已验签的元数据中读取。

```python
from pathlib import Path
import openzilo as sdk

# ring 表示已经连接的 OpenZiloClient。
bundle = Path("firmware.ota.zip").read_bytes()
public_key = Path("trusted-signing-public.pem").read_bytes()
metadata = sdk.inspect_firmware_bundle(bundle, trusted_public_key=public_key)
info = await sdk.update_firmware(ring, bundle, trusted_public_key=public_key)
```

新增必需依赖 `cryptography>=43`。现有固件 OTA 传输协议保持不变。设备侧加密密钥匹配和防回滚仍由设备检查；电脑端验签不代表已安装成功，也不能证明实机校准精度。

# 固件升级

--8<-- "docs/_includes/devices.zh-CN.md"

[English](https://github.com/ziloai/OpenZilo/wiki/Firmware-Updates) | [简体中文](https://github.com/ziloai/OpenZilo/wiki/Firmware-Updates-zh-CN)

--8<-- "docs/_includes/features.zh-CN.md:ota"

## 1. 选择升级包

打开 [官方固件发行页面](https://github.com/ziloai/OpenZilo-Hardware/releases)，确认以下信息：

- 设备型号和硬件版本在支持列表中。
- 当前固件版本可以升级到目标版本。
- 已了解录音、设置是否保留，以及该版本的已知问题。

下载带版本号的签名 OTA ZIP，并通过独立可信渠道取得签名公钥。目标版本、型号、板型和内部摘要均包含在受签名保护的元数据中。工厂烧录文件不用于 SDK OTA 升级。

## 2. 升级前准备

先备份重要录音，停止录音、下载和 IMU 上报，并断开其他连接戒指的应用。确保电量充足，遵循发行说明中的电量要求。

在 SDK 仓库目录运行：

```bash
uv sync --locked
uv run openzilo device use
uv run openzilo info
```

记下当前固件版本。可运行 `uv run openzilo ota-update --help` 查看当前安装的升级命令。

## 3. 运行升级命令

下面的参数都需要替换为本次发行提供的值：

```bash
uv run openzilo ota-inspect "path/to/firmware.ota.zip" --public-key "path/to/trusted-signing-public.pem"
uv run openzilo ota-update "path/to/firmware.ota.zip" --public-key "path/to/trusted-signing-public.pem"
```

命令使用已保存的默认设备；也可用 `--address` 指定地址。升级期间保持设备靠近，避免中断蓝牙和供电。

`ota-inspect` 离线验签并展示全部元数据，可用 `--json` 输出 JSON。`ota-update` 核对设备型号、板型和起始版本后，只发送内部 OTA 字节。原始 BIN 和手填版本、摘要、型号的覆盖参数已移除。测试配置 ZIP 需要 `--allow-test-firmware`；板型必须由设备报告或来自已核实的精确旧构建配置，未知板型拒绝升级。

## 4. 确认结果

SDK 发送完文件后会等待戒指重启、重新连接，确认仍是同一台设备，并读取目标固件版本。**只有版本检查通过，命令才报告成功。** 传输进度到达 100% 时还需继续等待。

完成后可运行 `uv run openzilo info` 查看版本，再录制一段短音频并检查需要使用的功能。

超时参数均以秒计：`--timeout` 默认 30，限制单次操作；`--total-timeout` 默认 600，限制升级前检查与传输；`--reboot-timeout` 默认 90，限制重启、重连与版本检查。Python 调用见 [SDK 手册](../docs/sdk-ota.zh-CN.md#固件升级)和 [update_firmware.py](../examples/update_firmware.py)。

## 升级中断怎么办

超时、断线或取消后，先重新连接并读取固件版本，再决定是否重试。退出电脑端程序不会撤回戒指已经收到的升级包。

无法重新连接时，记录升级前版本、目标版本和错误信息，并[联系支持](mailto:openzilo@ziloring.com)。降级、自动恢复和录音保留情况以该版本发行说明为准。

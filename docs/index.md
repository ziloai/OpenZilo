# OpenZilo Python SDK

--8<-- "docs/_includes/devices.zh-CN.md"

使用 Python 连接 OpenZilo 戒指，读取设备信息、录音与动作数据，并接入你的应用。公开接口来自 `openzilo` 包，命令行工具与 Python SDK 一起安装。

## 从这里开始

1. [安装与运行环境](sdk-install.zh-CN.md)：安装 SDK，配置蓝牙和音频依赖。
2. [快速开始](sdk-quickstart.zh-CN.md)：运行完整示例，连接设备并读取信息。
3. [SDK 与固件兼容](compatibility.zh-CN.md)：查询设备功能，判断哪些接口可用。

想先从终端操作设备，可以直接使用[命令行指南](cli.zh-CN.md)。

## 按功能使用

| 你要做什么 | 阅读 |
| --- | --- |
| 扫描设备，连接、断开或管理通知 | [扫描与连接](sdk-connection.zh-CN.md) |
| 查询固件、型号、电量与存储 | [读取设备信息](sdk-device-info.zh-CN.md) |
| 回复设备的时间请求 | [设备校时](sdk-time-sync.zh-CN.md) |
| 修改录音设置，远程开始或停止录音 | [远程录音与录音设置](recording-control.zh-CN.md) |
| 下载已有录音，接收刚保存的录音 | [下载与接收已保存的录音](sdk-downloads.zh-CN.md) |
| 实时接收 Opus 或 PCM | [实时音频](sdk-live-audio.zh-CN.md) |
| 保存原始文件，转换为 WAV | [音频解码与文件保存](sdk-audio-decoding.zh-CN.md) |
| 采集加速度计、陀螺仪数据 | [IMU 数据采集](sdk-imu.zh-CN.md) |
| 等待按键或敲击事件 | [按键与敲击事件](sdk-events.zh-CN.md) |
| 分块读取设备日志 | [读取设备日志](sdk-logs.zh-CN.md) |
| 在应用中升级固件 | [通过 SDK 升级固件](sdk-ota.zh-CN.md) |

各功能页说明调用顺序、参数、返回结果和错误处理，并提供相应示例。

## 查询接口与排查问题

- [API 索引](python-sdk.zh-CN.md)：按功能查找公开函数及签名。
- [数据类型](sdk-data-types.zh-CN.md)：连接信息、录音、音频与 IMU 的返回字段。
- [异常与问题排查](sdk-errors.zh-CN.md)：连接失败、超时、解码失败及设备忙碌。
- [功能与版本要求](features.zh-CN.md)、[版本升级与固件差异](sdk-migration.zh-CN.md)：功能条件与升级变化。

## 设备与底层资料

需要操作戒指时，查看[设备使用指南](../wiki/Home-zh-CN.md)。实现自定义客户端或联调通信时，再阅读[协议参考](protocol.zh-CN.md)、[架构与数据流](architecture.zh-CN.md)和[协议调试工具](sdk-protocol-tools.zh-CN.md)。

# 首次使用

--8<-- "docs/_includes/devices.zh-CN.md"

[English](https://github.com/ziloai/OpenZilo/wiki/First-Use) | [简体中文](https://github.com/ziloai/OpenZilo/wiki/First-Use-zh-CN)

--8<-- "docs/_includes/features.zh-CN.md:user-guide-scope"

## 1. 给戒指充电

使用配套充电附件。红灯闪烁表示正在充电，充满后绿灯常亮。录音前请确保电量充足，尤其是设备显示电量低于 20% 时。其他灯光含义见[灯光说明](https://github.com/ziloai/OpenZilo/wiki/LED-Indicators-zh-CN)。

## 2. 安装并连接

需要 Python 3.10 或更新版本、[uv](https://docs.astral.sh/uv/getting-started/installation/) 和支持低功耗蓝牙的电脑。Linux 还需要 BlueZ 和蓝牙访问权限。将录音转成 WAV 时需要安装 `ffmpeg`。

```bash
git clone https://github.com/ziloai/OpenZilo.git
cd OpenZilo
uv sync --locked
uv run openzilo device use
uv run openzilo info
```

按提示从扫描结果中选择戒指，设备地址会保存在本机。先关闭其他正在连接戒指的应用。`info` 会显示设备型号、固件版本和电量。

后续命令默认使用这台设备。需要切换时，再运行 `device use`；也可以用 `--address` 为单条命令指定地址。

## 3. 录制并下载音频

按住按键，绿灯亮起后说话，松开结束。固件 `V2.001.0002.0001` 无需切换录音模式；`V2.001.0002.0000` 如已进入手势模式，先按[按键说明](https://github.com/ziloai/OpenZilo/wiki/Buttons-and-Modes-zh-CN)返回录音模式。

```bash
uv run openzilo audio-count
uv run openzilo audio-download 0 first-recording.wav
```

先确认录音数量增加，再下载索引 `0` 的文件。索引 `0` 表示第一条已存录音，不一定是刚录的那条。命令生成可播放的 WAV，同时保留原始录音。

WAV 转换失败时，检查 `ffmpeg -version` 是否可执行。保留原始 `.bin` 文件，之后可以重新转换；改文件扩展名不能改变音频格式。

## 4. 查看 IMU 数据

以下直接启动用法需要固件 **V2.001.0002.0001 或更新版本**。使用 `V2.001.0002.0000` 时，先短按进入手势模式，再运行：

```bash
uv run openzilo sensor-stream --seconds 10
```

移动手部，终端会输出 IMU 数据。运行结束后停止上报并断开连接；按 Ctrl+C 可提前结束。两版行为差异见[版本升级说明](../docs/sdk-migration.zh-CN.md)。

## 下一步

用[交互终端](../docs/cli.zh-CN.md#交互终端)连续操作设备，或用 [Python SDK](../docs/python-sdk.zh-CN.md)编写应用。远程开始录音和修改录音设置见[远程录音](../docs/recording-control.zh-CN.md)。

遇到连接问题，先检查电量、蓝牙权限，以及是否有其他程序占用连接。无法录音时检查当前模式、电量和存储空间；没有 IMU 数据时检查模式和开始上报的响应。更多问题见 [SDK 常见问题](../docs/sdk-errors.zh-CN.md)。

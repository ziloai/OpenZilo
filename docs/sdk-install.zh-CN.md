# 安装与运行环境

--8<-- "docs/_includes/devices.zh-CN.md"

需要先安装 Python 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。

安装 Python SDK，以及蓝牙和音频解码所需依赖。完成后阅读[快速开始](sdk-quickstart.zh-CN.md)。

## 安装与导入

安装后导入模块：

```python
import openzilo as sdk
```

下文用 `sdk` 作为 `openzilo` 的模块别名。

## 安装依赖

推荐用 [uv](https://docs.astral.sh/uv/) 在自己的项目中从 GitHub 安装 SDK：

```bash
uv add git+https://github.com/ziloai/OpenZilo.git
```

之后用 `uv run python your_script.py` 执行脚本。不用 uv 时，也可以直接从 GitHub 安装：

```bash
python -m pip install git+https://github.com/ziloai/OpenZilo.git
```

直接操作设备可用[命令行工具](cli.zh-CN.md)：

```bash
uvx --from git+https://github.com/ziloai/OpenZilo.git openzilo shell
```

如果需要把戒指录音解码成 WAV，还需要安装 `ffmpeg`，并确保命令行可以执行：

```powershell
ffmpeg -version
```

只下载原始录音字节、不解码时，可以不安装 `ffmpeg`。

## Python

- 推荐 Python `3.11` 或更新版本。
- SDK 使用 `asyncio`，所有 BLE 设备访问函数都需要在 `async def` 中通过 `await` 调用。
- PyCharm 中请确认运行脚本使用的是安装了 `bleak` 的同一个虚拟环境。

## Windows

- 推荐 Windows 10/11。
- 打开系统蓝牙，并确认没有其他程序独占连接戒指。
- 如果出现设备可以被其他设备扫描到、但本机连接失败，优先尝试关闭再打开蓝牙、断开其他 BLE 工具、重启戒指广播。

## Ubuntu/Linux

- `bleak` 随 SDK 一同安装。
- 通常还需要 BlueZ 蓝牙栈，并确保当前用户有访问蓝牙设备的权限。
- 如果扫描或连接权限异常，可先用系统蓝牙工具确认本机能看到该 MAC 地址。

录音文件转 WAV 需要 `ffmpeg`；实时 PCM 使用可选依赖 `pcm`，安装方法和区别见[音频解码](sdk-audio-decoding.zh-CN.md)与[实时音频](sdk-live-audio.zh-CN.md)。

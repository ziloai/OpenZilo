# 命令行指南

--8<-- "docs/_includes/devices.zh-CN.md"

从 GitHub 安装和运行设备命令。扫描和操作设备需要系统蓝牙开启，设备在附近并处于可连接状态。

## 用 uvx 直接启动

从 GitHub 获取 CLI 并进入交互终端，无需手动配置项目环境：

```sh
uvx --from git+https://github.com/ziloai/OpenZilo.git openzilo shell
```

`uvx` 会自动管理隔离环境。设备操作需要系统蓝牙开启，并具备蓝牙访问权限。进入后选择戒指，再执行命令：

```text
openzilo> device use
openzilo> info
openzilo> doctor
openzilo> exit
```

经常使用时，可以从 GitHub 安装命令，之后直接运行 `openzilo`：

```sh
uv tool install git+https://github.com/ziloai/OpenZilo.git
openzilo shell
```

下文示例使用安装后的 `openzilo` 命令。也可直接在 `shell` 中输入子命令。默认设备配置保存在用户配置目录，不随工具环境切换。

要固定分支、标签或提交，在 GitHub 地址后追加 `@REF`：

```sh
uvx --from git+https://github.com/ziloai/OpenZilo.git@REF openzilo shell
```

将 `REF` 替换为所需版本。需要刷新 GitHub 工具环境时使用 `uvx --refresh --from git+https://github.com/ziloai/OpenZilo.git openzilo shell`。分发机制见 [uv 官方工具指南](https://docs.astral.sh/uv/guides/tools/)。

## 第一次使用

```sh
# 扫描并按编号选择默认设备
openzilo device use

# 查看设备信息、电量、固件版本
openzilo info

# 进入交互终端
openzilo shell
```

已知地址时可直接运行 `openzilo device use AA:BB:CC:DD:EE:FF`；macOS 使用扫描得到的 UUID。保存地址不会立即连接设备。仅查看附近设备可运行 `openzilo scan`，不会更改默认设备。

默认设备保存在 `$XDG_CONFIG_HOME/openzilo/config.json`，未设置 XDG 时使用 `~/.config/openzilo/config.json`。文件只包含设备地址，并以当前用户可读写的权限创建。不要将真实设备配置加入版本控制。可以通过 `OPENZILO_CONFIG` 指定其他文件。

设备地址优先级为：命令的 `--address` → `shell --address` → 环境变量 `OPENZILO_ADDRESS` → 已保存的默认设备。`scan` 不受默认设备影响，扫描目标由自己的 `--address` 指定。

```sh
openzilo device show
openzilo device forget
openzilo info --address AA:BB:CC:DD:EE:FF
```

`device forget` 只删除本地配置，不会改动戒指，也不会取消环境变量。配置损坏时可用它重置，或重新执行 `device use ADDRESS`。

## 交互终端

进入 `shell` 后直接输入子命令，不需要加 `openzilo`：

```text
openzilo> info
openzilo> audio-count
openzilo> audio-config
openzilo> audio-record recordings/test.wav --seconds 5 --channels 1 --bitrate 16000
openzilo> audio-status
openzilo> sensor-stream --seconds 10 --output captures/imu.jsonl
openzilo> help audio-record
openzilo> exit
```

`help` 列出全部命令，`help 命令名` 查看参数。每条设备命令独立连接并在结束时断开；终端不会持续占用 BLE 连接。`device use` 可以在终端中切换默认设备；若启动时传入了 `shell --address`，该覆盖值一直有效。输入错误或设备报错后可以继续输入命令。Ctrl+C 取消当前操作并退出程序，Ctrl+D 或 `exit` 结束终端。

## 录音和配置

--8<-- "docs/_includes/firmware-0001.zh-CN.md"

这些命令从固件 `V2.001.0002.0001` 开始提供，`V2.001.0002.0000` 没有远程录音和设置接口。完整说明见[远程录音与录音设置](recording-control.zh-CN.md)。

```sh
# 查看配置；增益为数字 Q8，256 表示 1 倍
openzilo audio-config
openzilo audio-config --channels 2 --bitrate 32000 --gain-left-q8 256 --gain-right-q8 256

# 远程录制 5 秒、等待写入完成、下载并生成可播放文件
openzilo audio-record recordings/test.wav --seconds 5

# 选择实时传输并同时保留设备端备份
openzilo audio-record recordings/live.wav --destination both --seconds 5

# 查询状态；根据实际 session_id 提前停止或丢弃
openzilo audio-status
openzilo audio-stop 123
openzilo audio-stop 123 --cancel
```

`123` 是示例，请使用状态查询返回的实际会话编号。停止请求的确认不等于文件已经保存，命令会继续等待终态。START 超时后先查询 `audio-status`，避免重复启动。

配置在重连后保留，重启后恢复默认值。`audio-record` 默认使用 Flash 输出和断连停止策略，其他未指定字段沿用设备配置；`--max-duration-ms` 是设备侧时长上限（20–60000 毫秒，20 毫秒步进），`--seconds` 是 CLI 请求停止前等待的时间（0.02–60 秒）。设备上限更短时可能提前结束。

转换 Speex/Opus 为 WAV 需要可执行的 `ffmpeg`，可以通过 `--ffmpeg /path/to/ffmpeg` 指定。接收、下载和解码已保存录音：

```sh
openzilo audio-receive recordings/button.wav
openzilo audio-download 0 recordings/saved.wav
openzilo audio-decode recordings/raw.bin recordings/decoded.wav
```

`audio-live` 等待按键触发的实时录音，设备是否保留 Flash 副本取决于录音配置。`audio-clear --yes` 会永久清除设备全部录音，必须显式传入 `--yes`。

## 实时音频

--8<-- "docs/_includes/firmware-0001.zh-CN.md"

```sh
openzilo audio-live recordings/live.wav
```

## IMU 数据和其他操作

```sh
# 每行一个批次的 JSON，包含 sequence_start、frame_count、sample_size 和 samples
openzilo sensor-stream --seconds 10 --output captures/imu.jsonl

# 输出到终端，也可通过标准输出接入其他程序
openzilo sensor-stream --seconds 5

openzilo connect
openzilo time-sync --seconds 30
openzilo log-storage
openzilo log-read 0 0 128 --text
openzilo ota-update --help
```

固件 `V2.001.0002.0001` 直接启动 IMU；`V2.001.0002.0000` 需先进入手势模式。采集达到时长、出错或取消时会尝试停止上报并断开连接。文件输出会覆盖指定路径，父目录自动创建；中途失败时已写入的批次保留。传感器数据保持协议原始数值，单位解释见 [SDK 指南](python-sdk.zh-CN.md)。

连接命令均支持 `--scan-timeout` 和 `--connect-timeout`。错误写入 stderr 并返回退出码 1；参数错误返回 2；Ctrl+C 返回 130。交互终端中的命令错误会显示并返回提示符。

<a id="software-imu-calibration"></a>

## 本机 IMU 软件校准

使用 `openzilo imu-calibrate accel` 在充电盒中完成加速度计六面校准，使用 `quick` 在盒外静置校准陀螺仪，或用 `full` 顺序完成两阶段。独立验证通过后才原子保存本机配置。`show` 读取本机文件，`reset` 删除本机文件。`sensor-stream --calibrated --seconds 10` 显式应用匹配的配置，以 g 和度/秒输出数据，并标明已校正组件。默认原始数据流保持不变，不向戒指下发校准参数。详见[本机软件校准](sdk-imu.zh-CN.md#本机软件校准)。

## 兼容诊断

`openzilo --version` 查看 SDK 版本；`openzilo device capabilities` 输出支持的功能、录音参数范围和信息来源；`openzilo doctor` 额外输出 SDK 版本、运行环境标识和音频解码依赖。远程录音、实时音频、IMU、OTA 在执行前查询能力，SDK 根据查询结果检查功能，不按固件版本号大小推断。详见[兼容说明](compatibility.zh-CN.md)。

离线验签并查看签名 OTA ZIP 的完整元数据：

```bash
openzilo ota-inspect firmware.ota.zip --public-key trusted-signing-public.pem --json
```

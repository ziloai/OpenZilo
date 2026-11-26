# CLI 命令参考

本页由 `tools/generate_cli_reference.py` 直接从 `openzilo._cli.build_parser()` 自动生成，列出当前版本全部 CLI 子命令、参数与选项。

安装或直接运行：

```sh
uv tool install openzilo
openzilo --help

# 或免安装直接运行
uvx openzilo --help
```

## 命令总览

| 命令 | 说明 |
| :--- | :--- |
| [`openzilo device use`](#openzilo-device-use) | Save an address, or scan and select interactively. |
| [`openzilo device show`](#openzilo-device-show) |  |
| [`openzilo device forget`](#openzilo-device-forget) |  |
| [`openzilo device capabilities`](#openzilo-device-capabilities) | Query device contracts and limits as JSON. |
| [`openzilo doctor`](#openzilo-doctor) | Report SDK identity, device contracts and decoder availability. |
| [`openzilo shell`](#openzilo-shell) | Interactive device terminal; help and exit are built in. |
| [`openzilo sensor-stream`](#openzilo-sensor-stream) | Capture IMU batches as JSON lines, then stop reports. |
| [`openzilo imu-calibrate`](#openzilo-imu-calibrate) | Local software IMU calibration; no firmware writes. |
| [`openzilo scan`](#openzilo-scan) | Scan nearby devices. |
| [`openzilo connect`](#openzilo-connect) | Connect and disconnect once. |
| [`openzilo info`](#openzilo-info) | Print system information. |
| [`openzilo rssi`](#openzilo-rssi) | Read the ring's received connection RSSI in dBm. |
| [`openzilo time-sync`](#openzilo-time-sync) | Auto-respond to device time-sync requests. |
| [`openzilo audio-count`](#openzilo-audio-count) | Print stored audio file count. |
| [`openzilo audio-config`](#openzilo-audio-config) | Read/set volatile recording defaults (extended firmware). |
| [`openzilo audio-status`](#openzilo-audio-status) | Read the latest recording session state. |
| [`openzilo audio-stop`](#openzilo-audio-stop) | Stop/cancel a recording session and confirm completion. |
| [`openzilo audio-record`](#openzilo-audio-record) | Remotely record, stop and save the result. |
| [`openzilo audio-download`](#openzilo-audio-download) | Download one audio file. |
| [`openzilo audio-receive`](#openzilo-audio-receive) | Wait for a saved recording and download it (old/new firmware). |
| [`openzilo audio-live`](#openzilo-audio-live) | Receive live Opus; Flash retention follows device configuration. |
| [`openzilo ota-inspect`](#openzilo-ota-inspect) | Verify a firmware ZIP and display all metadata without BLE. |
| [`openzilo ota-update`](#openzilo-ota-update) | Install an official APP update package and verify the running version. |
| [`openzilo audio-decode`](#openzilo-audio-decode) | Decode a downloaded recording bin into WAV. |
| [`openzilo audio-clear`](#openzilo-audio-clear) | Clear all stored audio files. |
| [`openzilo log-storage`](#openzilo-log-storage) | Print log storage info. |
| [`openzilo log-read`](#openzilo-log-read) | Read one log chunk. |
| [`openzilo host`](#openzilo-host) | Run a local Connect API v2 host broker (NDJSON over TCP, Unix socket, or stdio). |

## 命令详情

### openzilo device use

Save an address, or scan and select interactively.

```sh
openzilo device use [-h] [--timeout TIMEOUT] [address]
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `address` | - | - | BLE address/UUID; omit to scan and choose. |
| `--timeout` | - | `30.0` | - |

### openzilo device show

```sh
openzilo device show [-h]
```

### openzilo device forget

```sh
openzilo device forget [-h]
```

### openzilo device capabilities

Query device contracts and limits as JSON.

```sh
openzilo device capabilities [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features] [--timeout TIMEOUT]
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |
| `--timeout` | - | `3.0` | - |

### openzilo doctor

Report SDK identity, device contracts and decoder availability.

```sh
openzilo doctor [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features] [--timeout TIMEOUT]
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |
| `--timeout` | - | `3.0` | - |

### openzilo shell

Interactive device terminal; help and exit are built in.

```sh
openzilo shell [-h] [--address ADDRESS]
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | Override the default device for this shell. |

### openzilo sensor-stream

Capture IMU batches as JSON lines, then stop reports.

```sh
openzilo sensor-stream [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features] [--seconds SECONDS] [--output OUTPUT] [--calibrated] [--calibration-profile CALIBRATION_PROFILE]
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |
| `--seconds` | - | `10.0` | - |
| `--output` | - | - | Write JSONL to a file instead of stdout. |
| `--calibrated` | - | - | Apply a matching local software profile; output g and deg/s. |
| `--calibration-profile` | - | - | Profile JSON override for --calibrated. |

### openzilo imu-calibrate

Local software IMU calibration; no firmware writes.

```sh
openzilo imu-calibrate [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features] [--seconds SECONDS] [--profile PROFILE] {show,accel,quick,full,reset}
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |
| `action` | `show`, `accel`, `quick`, `full`, `reset` | - | - |
| `--seconds` | - | `5.0` | Static seconds per face; quick uses at least 20 seconds. |
| `--profile` | - | - | Override local calibration JSON path. |

### openzilo scan

Scan nearby devices.

```sh
openzilo scan [-h] [--address ADDRESS] [--timeout TIMEOUT]
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | Target device address/identifier; return as soon as found. |
| `--timeout` | - | `30.0` | - |

### openzilo connect

Connect and disconnect once.

```sh
openzilo connect [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features]
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |

### openzilo info

Print system information.

```sh
openzilo info [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features]
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |

### openzilo rssi

Read the ring's received connection RSSI in dBm.

```sh
openzilo rssi [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features] [--timeout TIMEOUT]
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |
| `--timeout` | - | `3.0` | - |

### openzilo time-sync

Auto-respond to device time-sync requests.

```sh
openzilo time-sync [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features] [--seconds SECONDS]
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |
| `--seconds` | - | `30.0` | - |

### openzilo audio-count

Print stored audio file count.

```sh
openzilo audio-count [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features]
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |

### openzilo audio-config

Read/set volatile recording defaults (extended firmware).

```sh
openzilo audio-config [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features] [--destination {auto,flash,live,both}] [--disconnect {stop,save}] [--channels {1,2}] [--bitrate BITRATE] [--gain-left-q8 GAIN_LEFT_Q8] [--gain-right-q8 GAIN_RIGHT_Q8] [--max-duration-ms MAX_DURATION_MS]
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |
| `--destination` | `auto`, `flash`, `live`, `both` | - | - |
| `--disconnect` | `stop`, `save` | - | - |
| `--channels` | `1`, `2` | - | - |
| `--bitrate` | - | - | - |
| `--gain-left-q8` | - | - | - |
| `--gain-right-q8` | - | - | - |
| `--max-duration-ms` | - | - | - |

### openzilo audio-status

Read the latest recording session state.

```sh
openzilo audio-status [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features]
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |

### openzilo audio-stop

Stop/cancel a recording session and confirm completion.

```sh
openzilo audio-stop [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features] [--cancel] session_id
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |
| `session_id` | - | - | - |
| `--cancel` | - | - | - |

### openzilo audio-record

Remotely record, stop and save the result.

```sh
openzilo audio-record [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features] [--destination {auto,flash,live,both}] [--disconnect {stop,save}] [--channels {1,2}] [--bitrate BITRATE] [--gain-left-q8 GAIN_LEFT_Q8] [--gain-right-q8 GAIN_RIGHT_Q8] [--max-duration-ms MAX_DURATION_MS] [--seconds SECONDS] [--ffmpeg FFMPEG] output
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |
| `--destination` | `auto`, `flash`, `live`, `both` | `flash` | - |
| `--disconnect` | `stop`, `save` | `stop` | - |
| `--channels` | `1`, `2` | - | - |
| `--bitrate` | - | - | - |
| `--gain-left-q8` | - | - | - |
| `--gain-right-q8` | - | - | - |
| `--max-duration-ms` | - | - | - |
| `output` | - | - | - |
| `--seconds` | - | `5.0` | - |
| `--ffmpeg` | - | `ffmpeg` | - |

### openzilo audio-download

Download one audio file.

```sh
openzilo audio-download [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features] [--timeout TIMEOUT] [--ffmpeg FFMPEG] [--pcm-sample-rate PCM_SAMPLE_RATE] [--pcm-channels {1,2}] [--pcm-bit-depth {8,16}] [--speex-quality SPEEX_QUALITY] [--speex-bits-size SPEEX_BITS_SIZE] [--allow-framed-blocks] file_index output
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |
| `file_index` | - | - | - |
| `output` | - | - | - |
| `--timeout` | - | `30.0` | - |
| `--ffmpeg` | - | `ffmpeg` | ffmpeg executable path. |
| `--pcm-sample-rate` | - | `16000` | - |
| `--pcm-channels` | `1`, `2` | `1` | - |
| `--pcm-bit-depth` | `8`, `16` | `16` | - |
| `--speex-quality` | - | `3` | - |
| `--speex-bits-size` | - | - | - |
| `--allow-framed-blocks` | - | - | Allow legacy 1026-byte outer blocks when parsing Speex packets. |

### openzilo audio-receive

Wait for a saved recording and download it (old/new firmware).

```sh
openzilo audio-receive [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features] [--timeout TIMEOUT] [--ffmpeg FFMPEG] output
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |
| `output` | - | - | - |
| `--timeout` | - | `60.0` | - |
| `--ffmpeg` | - | `ffmpeg` | - |

### openzilo audio-live

Receive live Opus; Flash retention follows device configuration.

```sh
openzilo audio-live [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features] [--timeout TIMEOUT] [--ffmpeg FFMPEG] output
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |
| `output` | - | - | - |
| `--timeout` | - | `60.0` | - |
| `--ffmpeg` | - | `ffmpeg` | - |

### openzilo ota-inspect

Verify a firmware ZIP and display all metadata without BLE.

```sh
openzilo ota-inspect [-h] --public-key PUBLIC_KEY [--json] firmware
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `firmware` | - | - | - |
| `--public-key` | - | - | Independently trusted PEM P-256 public key. |
| `--json` | - | - | Print verified metadata as JSON. |

### openzilo ota-update

Install an official APP update package and verify the running version.

```sh
openzilo ota-update [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features] --public-key PUBLIC_KEY [--allow-test-firmware] [--timeout TIMEOUT] [--total-timeout TOTAL_TIMEOUT] [--reboot-timeout REBOOT_TIMEOUT] firmware
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |
| `firmware` | - | - | Signed APP OTA ZIP containing verified release metadata. |
| `--public-key` | - | - | Independently trusted PEM P-256 public key for ZIPs. |
| `--allow-test-firmware` | - | - | Permit signed test-profile firmware. |
| `--timeout` | - | `30.0` | Per-operation timeout in seconds. |
| `--total-timeout` | - | `600.0` | Overall transfer time limit. |
| `--reboot-timeout` | - | `90.0` | Reboot and verification time limit. |

### openzilo audio-decode

Decode a downloaded recording bin into WAV.

```sh
openzilo audio-decode [-h] [--ffmpeg FFMPEG] [--pcm-sample-rate PCM_SAMPLE_RATE] [--pcm-channels {1,2}] [--pcm-bit-depth {8,16}] [--speex-quality SPEEX_QUALITY] [--speex-bits-size SPEEX_BITS_SIZE] [--allow-framed-blocks] input output
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `input` | - | - | - |
| `output` | - | - | - |
| `--ffmpeg` | - | `ffmpeg` | ffmpeg executable path. |
| `--pcm-sample-rate` | - | `16000` | - |
| `--pcm-channels` | `1`, `2` | `1` | - |
| `--pcm-bit-depth` | `8`, `16` | `16` | - |
| `--speex-quality` | - | `3` | - |
| `--speex-bits-size` | - | - | - |
| `--allow-framed-blocks` | - | - | Allow legacy 1026-byte outer blocks when parsing Speex packets. |

### openzilo audio-clear

Clear all stored audio files.

```sh
openzilo audio-clear [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features] [--yes]
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |
| `--yes` | - | - | Confirm clearing. |

### openzilo log-storage

Print log storage info.

```sh
openzilo log-storage [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features]
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |

### openzilo log-read

Read one log chunk.

```sh
openzilo log-read [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features] [--output OUTPUT] [--text] [--encoding ENCODING] index offset size
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |
| `index` | - | - | - |
| `offset` | - | - | - |
| `size` | - | - | - |
| `--output` | - | - | - |
| `--text` | - | - | Decode as text. |
| `--encoding` | - | `utf-8` | - |

### openzilo host

Run a local Connect API v2 host broker (NDJSON over TCP, Unix socket, or stdio).

```sh
openzilo host [-h] [--address ADDRESS] [--scan-timeout SCAN_TIMEOUT] [--connect-timeout CONNECT_TIMEOUT] [--allow-unverified-features] [--host HOST] [--port PORT] [--socket SOCKET] [--stdio] [--scopes SCOPES] [--token TOKEN] [--require-authorization] [--firmware-public-key FIRMWARE_PUBLIC_KEY] [--no-reconnect]
```

| 参数 / 选项 | 可选值 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--address` | - | - | BLE address/UUID; defaults to OPENZILO_ADDRESS or 'device use'. |
| `--scan-timeout` | - | `30.0` | - |
| `--connect-timeout` | - | `30.0` | - |
| `--allow-unverified-features` | - | - | Allow enhanced commands on unknown legacy firmware; does not override declared incompatibility. |
| `--host` | - | `127.0.0.1` | TCP bind address (default: 127.0.0.1). |
| `--port` | - | `7420` | TCP bind port (default: 7420). |
| `--socket` | - | - | Listen on a Unix domain socket instead of TCP. |
| `--stdio` | - | - | Serve one Connect API client over stdin/stdout. |
| `--scopes` | - | `audio,firmware,info,logs,recording,sensors,time` | Comma-separated Connect API scopes allowed for clients. |
| `--token` | - | - | Optional shared authorization token (defaults to OPENZILO_HOST_TOKEN if set). |
| `--require-authorization` | - | - | Require clients to call requestAuthorization before accessing protected operations. |
| `--firmware-public-key` | - | - | Trusted PEM P-256 public key to enable firmware.upgrade. |
| `--no-reconnect` | - | - | Do not automatically reconnect if the ring disconnects. |

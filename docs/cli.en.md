# Command-line guide

--8<-- "docs/_includes/devices.en.md"

The device CLI is available on [PyPI](https://pypi.org/project/openzilo/). Enable Bluetooth and keep the ring nearby and connectable.

## Run directly with uvx

Start the interactive shell without setting up a project environment:

```sh
uvx openzilo shell
```

`uvx` manages an isolated environment automatically. Device operations require Bluetooth and OS access permissions. Inside the shell, select a ring and run commands:

```text
openzilo> device use
openzilo> info
openzilo> doctor
openzilo> exit
```

For frequent use, install the CLI, then invoke `openzilo` directly:

```sh
uv tool install openzilo
openzilo shell
```

The examples below use the installed `openzilo` command. You can also enter subcommands inside the shell. Device selection is stored in the user configuration directory and survives tool environment changes.

To run a specific PyPI release, use `uvx openzilo@VERSION shell` and replace `VERSION` with the release version. Use `uvx openzilo@latest shell` for the latest release. See the [official uv tools guide](https://docs.astral.sh/uv/guides/tools/).

To install the development CLI from Git, run `uv tool install git+https://github.com/ziloai/OpenZilo.git@main`.

## First use

```sh
# Scan and select the default device by number
openzilo device use

# Read device information, battery and firmware version
openzilo info

# Read connection signal strength (requires connection_rssi)
openzilo rssi

# Enter the interactive shell
openzilo shell
```

With a known address, run `openzilo device use AA:BB:CC:DD:EE:FF`; on macOS use the scanned UUID. Saving an address does not connect immediately. `openzilo scan` lists nearby devices without changing the default.

The default device is stored in `$XDG_CONFIG_HOME/openzilo/config.json`, or `~/.config/openzilo/config.json` when XDG is unset. The file contains only the device address and is created with current-user read/write permissions. Do not commit real device settings. `OPENZILO_CONFIG` selects another file.

Address precedence: command `--address`, then `shell --address`, then `OPENZILO_ADDRESS`, then the saved default. `scan` ignores the default and uses its own `--address` filter.

```sh
openzilo device show
openzilo device forget
openzilo info --address AA:BB:CC:DD:EE:FF
```

`device forget` deletes local configuration only; it neither modifies the ring nor clears environment variables. Use it to reset damaged configuration, or run `device use ADDRESS` again.

## Interactive shell

Inside `shell`, enter subcommands without the `openzilo` prefix:

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

`help` lists commands; `help COMMAND` shows arguments. Each device command connects and disconnects independently, so the shell does not hold BLE continuously. `device use` changes the saved default, but an initial `shell --address` override remains effective. Command errors return to the prompt. Ctrl+C cancels and exits; Ctrl+D or `exit` closes the shell.

## Recording and configuration

--8<-- "docs/_includes/firmware-0001.en.md"

Remote start, stop, status and settings require firmware **V2.001.0002.0001 or later**. They are absent from `V2.001.0002.0000`. See [recording control](recording-control.md).

```sh
# Read settings; Q8 gain 256 means 1x
openzilo audio-config
openzilo audio-config --channels 2 --bitrate 32000 --gain-left-q8 256 --gain-right-q8 256

# Record five seconds remotely, wait for saving, download and create playable audio
openzilo audio-record recordings/test.wav --seconds 5

# Stream while retaining a device copy
openzilo audio-record recordings/live.wav --destination both --seconds 5

# Query status; use the actual session_id to stop or discard
openzilo audio-status
openzilo audio-stop 123
openzilo audio-stop 123 --cancel
```

`123` is illustrative; use the session ID returned by status. A stop acknowledgment does not confirm saving; the command waits for final state. If START times out, query `audio-status` before another START.

Configuration survives reconnection and resets on reboot. `audio-record` defaults to flash storage and stopping on disconnect; unspecified settings retain device values. `--max-duration-ms` is the device limit (0 for unlimited, or 20–60000 ms in 20 ms steps); `--seconds` is how long the CLI waits before requesting stop (0.02–60 seconds). A shorter device limit ends recording earlier.

Converting Speex/Opus to WAV requires an `ffmpeg` executable; specify it with `--ffmpeg /path/to/ffmpeg`. Legacy recordings can be received after a button recording or downloaded:

```sh
openzilo audio-receive recordings/button.wav
openzilo audio-download 0 recordings/saved.wav
openzilo audio-decode recordings/raw.bin recordings/decoded.wav
```

`audio-live` waits for a button-triggered recording; whether flash retains a copy depends on configuration. `audio-clear --yes` permanently deletes every recording and requires explicit `--yes`.

## Live audio

--8<-- "docs/_includes/firmware-0001.en.md"

```sh
openzilo audio-live recordings/live.wav
```

## IMU and other operations

```sh
# One JSON batch per line, with sequence_start, frame_count, sample_size and samples
openzilo sensor-stream --seconds 10 --output captures/imu.jsonl

# Print to the terminal or pipe stdout to another program
openzilo sensor-stream --seconds 5

openzilo connect
openzilo time-sync --seconds 30
openzilo log-storage
openzilo log-read 0 0 128 --text
openzilo ota-update --help
```

Firmware `V2.001.0002.0001` starts IMU directly; `V2.001.0002.0000` requires gesture mode first. At the time limit, error or cancellation, the command attempts to stop reports and disconnect. File output overwrites its path, creating parent directories; batches already written remain after failure. Values remain in protocol units; see the [IMU guide](sdk-imu.en.md).

Connection commands accept `--scan-timeout` and `--connect-timeout`. Errors go to stderr and exit with 1; argument errors with 2; Ctrl+C with 130. Interactive command errors return to the prompt.

## Compatibility diagnostics

`openzilo --version` shows the SDK version. `openzilo device capabilities` shows features, recording limits and information source. `openzilo doctor` also shows the SDK environment identifier and audio dependencies. RSSI, remote recording, live audio, IMU and OTA query capabilities before running; support is checked from the response, not firmware version ordering. See [compatibility](compatibility.en.md).

## Software IMU calibration

Use `openzilo imu-calibrate accel` for six-face accelerometer calibration in the charging case,
`quick` for stationary gyro calibration outside the case, or `full` for both stages.
Independent validation precedes atomic local saving. `show` reads the local file; `reset`
deletes it. `sensor-stream --calibrated --seconds 10` explicitly applies the matching profile,
outputs g / deg/s and marks the corrected components. Default raw streaming is unchanged.
No calibration parameters are sent to the ring. See [the software calibration specification](sdk-imu.en.md#local-software-calibration).

Inspect and verify all signed OTA ZIP metadata offline:

```bash
openzilo ota-inspect firmware.ota.zip --public-key trusted-signing-public.pem --json
```

## Connect Host mode (Connect API v2)

Run `openzilo host` to start a local OpenZilo Connect-compatible broker. The host process owns the single BLE connection, handles automatic reconnection and host-side IMU calibration, and exposes Connect API v2 (matching the Android OpenZilo Connect contract) to multiple local clients over NDJSON (defaulting to `127.0.0.1:7420`, with optional `--socket` Unix domain socket and `--stdio` single-client pipe modes).

```sh
# Run the local Connect Host directly with uvx without pre-installing (listens on 127.0.0.1:7420)
uvx openzilo host

# Or install persistently with uv tool install
uv tool install openzilo
openzilo host

# Listen on a Unix domain socket with explicit authorization and token verification
openzilo host --socket /tmp/openzilo-connect.sock --require-authorization --token my-secret

# Restrict allowed scopes or supply a trusted public key to enable firmware.upgrade
openzilo host --scopes info,sensors,audio --firmware-public-key trusted-signing-public.pem
```

Supported methods are `requestAuthorization`, `getStatus`, `execute`, `subscribe`, `unsubscribe`, `cancel`, and `closeClient`, covering the `status`, `imu`, `gesture`, `live`, `audio`, `recording`, and `time` topics with reference-counted IMU leases and automatic cleanup of exclusive device controls on client disconnect. Python clients can connect via `openzilo.ConnectClient`; see `examples/connect_client_demo.py`.

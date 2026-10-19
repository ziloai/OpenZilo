# First use

--8<-- "docs/_includes/devices.en.md"

[English](https://github.com/ziloai/OpenZilo/wiki/First-Use) | [简体中文](https://github.com/ziloai/OpenZilo/wiki/First-Use-zh-CN)

--8<-- "docs/_includes/features.en.md:user-guide-scope"

## 1. Charge the ring

Use the supplied charging accessory. Red flashes indicate charging; steady green indicates a full charge. Charge before recording, especially when the device reports less than 20% battery. See [LED indicators](https://github.com/ziloai/OpenZilo/wiki/LED-Indicators).

## 2. Install and connect

You need Python 3.10 or later, [uv](https://docs.astral.sh/uv/getting-started/installation/), and Bluetooth Low Energy support. Linux also requires BlueZ and permission to access Bluetooth. Install `ffmpeg` to convert recordings to WAV.

```bash
git clone https://github.com/ziloai/OpenZilo.git
cd OpenZilo
uv sync --locked
uv run openzilo device use
uv run openzilo info
```

Select a ring from the scan results. Its address is saved locally. Close other apps connected to the ring first. `info` shows the model, firmware version and battery level.

Later commands use the saved device. Run `device use` again to change it, or supply `--address` for an individual command.

## 3. Record and download audio

Hold the button, speak after the green light appears, then release to finish. Firmware `V2.001.0002.0001` needs no recording-mode change. If `V2.001.0002.0000` is in gesture mode, return to recording mode using [Buttons and modes](https://github.com/ziloai/OpenZilo/wiki/Buttons-and-Modes).

```bash
uv run openzilo audio-count
uv run openzilo audio-download 0 first-recording.wav
```

Confirm the count increased, then download file index `0`. This is the first stored recording, not necessarily the latest one. The command produces a playable WAV and preserves the original data.

If conversion fails, check that `ffmpeg -version` runs. Keep the original `.bin` file for conversion later. Renaming its extension does not convert the audio.

## 4. Receive IMU data

Direct startup requires firmware **V2.001.0002.0001 or later**. On `V2.001.0002.0000`, enter gesture mode with a short press first, then run:

```bash
uv run openzilo sensor-stream --seconds 10
```

Move your hand to see data in the terminal. The command stops reporting and disconnects when finished; Ctrl+C ends it early. Check [feature requirements](../docs/features.en.md) for other firmware.

## Next steps

Use the [interactive CLI](../docs/cli.zh-CN.md#interactive-shell) for repeated operations, or the [Python SDK](../docs/python-sdk.zh-CN.md) to build an app. See [Recording control](../docs/recording-control.md) to start recordings remotely and change recording settings.

For connection issues, check battery, Bluetooth permissions and other connected apps. For recording issues, check mode, battery and storage. For IMU issues, check mode and the start-report response. More help is in the [SDK FAQ](../docs/sdk-errors.en.md).

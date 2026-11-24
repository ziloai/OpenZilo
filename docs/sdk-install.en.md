# Installation and requirements

--8<-- "docs/_includes/devices.en.md"

Install Python and [uv](https://docs.astral.sh/uv/getting-started/installation/) first.

Install the Python SDK and its Bluetooth and audio dependencies, then follow the [quick start](sdk-quickstart.en.md).

## Install and import

After installation, import the package:

```python
import openzilo as sdk
```

This guide uses `sdk` as an alias for `openzilo`.

## Dependencies

Add the SDK from [PyPI](https://pypi.org/project/openzilo/) to your [uv](https://docs.astral.sh/uv/) project.

```bash
uv add openzilo
```

Run Python scripts with `uv run python your_script.py`. Without uv, use pip:

```bash
python -m pip install openzilo
```

To install the development version from Git, run `uv add git+https://github.com/ziloai/OpenZilo.git --branch main`.

For device commands, see the [CLI guide](cli.en.md):

```bash
uvx openzilo shell
```

To decode recordings to WAV, install `ffmpeg` and make it available from the command line:

```powershell
ffmpeg -version
```

Downloading raw recording bytes without decoding does not require `ffmpeg`.

## Python

- Python `3.11` or later is recommended.
- The SDK uses `asyncio`. Call asynchronous BLE operations with `await` inside `async def`.
- In PyCharm, select the same virtual environment where `bleak` was installed.

## Windows

- Windows 10 or 11 is recommended.
- Enable Bluetooth and disconnect other applications using the ring.
- If other devices can discover the ring but this computer cannot connect, toggle Bluetooth, disconnect other BLE tools, and restart advertising on the ring.

## Ubuntu/Linux

- `bleak` is installed with the SDK.
- Linux generally requires BlueZ and permission for the current user to access Bluetooth.
- For scan or connection permission problems, check discovery with your system Bluetooth tools first.

Recording-to-WAV conversion needs `ffmpeg`; live PCM uses the `pcm` extra. See [audio decoding](sdk-audio-decoding.en.md) and [live audio](sdk-live-audio.en.md) for the installation requirements.

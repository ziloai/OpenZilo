# Features and version requirements

--8<-- "docs/_includes/devices.en.md"

Check the ring's firmware version and supported features before choosing an API. The SDK, firmware and communication protocol have separate version numbers.

## Check versions and features

Run these commands from the repository:

```bash
uv run openzilo --version
uv run openzilo device use
uv run openzilo info
uv run openzilo device capabilities
```

`--version` shows the SDK version. `info` shows the device model and firmware. `device capabilities` lists supported features and recording parameter limits.

```python
import asyncio
import openzilo as sdk

ADDRESS = "AA:BB:CC:DD:EE:FF"  # Replace with the scanned device address

async def main():
    ring = await sdk.connect_ring(address=ADDRESS)
    try:
        info = await sdk.get_system_info(ring)
        print("Firmware:", info.firmware_version)
        if ring.capabilities.supports("recording_control"):
            print("Recording configuration:", await sdk.get_audio_recording_config(ring))
        else:
            print("No compatible remote recording interface is available")
    finally:
        await ring.disconnect()

asyncio.run(main())
```

`supports()` checks that the device and SDK share a compatible feature interface version. See [SDK and firmware compatibility](compatibility.en.md).

## Requirements by feature

--8<-- "docs/_includes/features.en.md"

## Reading version notes

- **Supported since firmware XXX** identifies the firmware that introduced a feature.
- **Available since SDK XXX** identifies the SDK that introduced its API.
- **This page applies to firmware XXX** identifies the device behavior described by the page.

Remote recording, recording settings and live audio are available starting with `V2.001.0002.0001`. The relevant usages state their minimum firmware version. See [version migration](sdk-migration.en.md) for other changes from `V2.001.0002.0000` to `V2.001.0002.0001`.

## Firmware downloads

Read the supported model, hardware revisions and starting versions in [official firmware releases](https://github.com/ziloai/OpenZilo-Hardware/releases), then follow the [firmware update guide](../wiki/Firmware-Updates.md).

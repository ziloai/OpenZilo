# SDK and firmware compatibility

--8<-- "docs/_includes/devices.en.md"

--8<-- "docs/_includes/features.en.md:capabilities"


A successful connection establishes BLE communication. Remote recording, live audio, IMU and firmware updates additionally require a compatible device interface.

## Recommended connection method

`connect_ring()` discovers supported features by default. Inspect `ring.capabilities` after connecting:

```python
import asyncio
import openzilo as sdk

ADDRESS = "AA:BB:CC:DD:EE:FF"

async def main():
    ring = await sdk.connect_ring(address=ADDRESS, auto_time_sync=True)
    try:
        capabilities = ring.capabilities
        print("Firmware:", capabilities.firmware_version)
        print("Model:", capabilities.model)
        if capabilities.supports("recording_control"):
            print(await sdk.get_audio_recording_config(ring))
    finally:
        await ring.disconnect()

asyncio.run(main())
```

With `async with sdk.OpenZiloClient(...)`, run this before those operations:

```python
capabilities = await sdk.get_device_capabilities(ring)
```

CLI remote recording, live audio, IMU and OTA commands query features automatically. Basic information, logs, existing-file downloads and time replies do not depend on discovery.

## Where support information comes from

Release builds `V2.001.0002.0000` and `V2.001.0002.0001` have no feature-discovery command. The SDK uses a built-in profile for exact versions it recognizes. This page explains SDK discovery and error handling; the minimum firmware version for a usage is stated directly in its feature section.


`DeviceCapabilities.source` identifies the source:

| Value | Meaning |
| --- | --- |
| `device` | The device returned a feature list; the SDK also checked the model and firmware version. |
| `legacy_profile` | The old firmware returned no list, so the SDK selected a built-in profile by exact firmware version and model. |
| `unknown` | No feature list or matching built-in profile is available. |

Legacy profiles apply only to models and full versions explicitly recognized by the SDK. A shared version prefix does not establish compatibility. Discovery timeout means no response was obtained, not necessarily that a feature is absent.

## Check feature availability

Use `capabilities.supports("FEATURE_NAME")`. Common feature names:

| Feature | Purpose |
| --- | --- |
| `recording_control` | Start, stop and configure recordings. |
| `live_audio` | Receive live audio. |
| `imu` | Receive accelerometer and gyroscope data. |
| `key_events` | Receive button events. |
| `double_tap` | Receive physical tap events. |
| `ota` | Update application firmware. |

The SDK also checks the interface major version. For example, `imu/2` starts capture on subscription. An older interface requiring gesture mode is not interchangeable just because the feature name matches.

Recording settings are checked against device channel, bitrate, gain, duration and output limits. Continuing on disconnect requires flash storage or simultaneous saving, not live-only output.

## Handle errors

| Exception | Common cause | Action |
| --- | --- | --- |
| `CompatibilityError` | Feature absent, interface version mismatch or recording settings outside limits | Inspect features and limits; adjust the call or choose compatible firmware. |
| `DeviceError` | Device rejected a command, such as during another operation | Inspect `error_code`, finish conflicting operations and retry. |
| `TimeoutError` | No response before the deadline | Check the connection and reconnect before discovery. After START timeout, query recording state before retrying. |
| `ProtocolError` | Missing fields or inconsistent data | Record SDK and firmware versions plus the error and report it. |

Results last for the current connection only and are cleared on disconnect. They are refreshed after OTA reconnection. Reconnect before retrying discovery after a failed legacy query.

## Inspect diagnostics

```bash
uv run openzilo --version
uv run openzilo device capabilities
uv run openzilo doctor
```

`device capabilities` outputs features and recording limits as JSON. `doctor` also reports the SDK version, environment identifier and PyAV availability. Include these when reporting issues, after removing addresses, serial numbers and private audio.

## Advanced connection options

`allow_unverified_features=True` permits feature calls when discovery is `unknown`, for applications that already know the interface. It does not override an explicit version mismatch. The CLI equivalent is `--allow-unverified-features`.

`negotiate_capabilities=False` disables automatic discovery; the caller must establish compatibility. This matches the default low-level `OpenZiloClient` connection behavior.

## Wire fields

For custom client implementations, see [capability discovery messages](protocol.en.md#capability-discovery-messages). Ordinary applications can use the SDK APIs above.

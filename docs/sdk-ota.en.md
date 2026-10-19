# Update firmware with the SDK

--8<-- "docs/_includes/devices.en.md"

Transfer an official application firmware package through Python and verify the version after reboot. Discover features first; see the [firmware guide](../wiki/Firmware-Updates.md) for downloads and device instructions.

Code snippets use `import openzilo as sdk`; `ring` is a connected client. See the [quick start](sdk-quickstart.en.md) for a complete connection example.

## Firmware updates

--8<-- "docs/_includes/features.en.md:ota"

`update_firmware()` and `ota-update` update application firmware; inspect the installed command with `openzilo ota-update --help`. They do not update the bootloader. Use an official package listing your model and starting version. Back up recordings, stop recording, downloads and IMU reporting, and maintain power and connection. The update exclusively owns this connection until it finishes.

```python
from pathlib import Path

async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    await sdk.get_device_capabilities(ring)
    info = await sdk.update_firmware(
        ring,
        Path("path/to/official-update.bin").read_bytes(),
        version="V2.001.0002.0001",
        sha256="SHA256_FROM_RELEASE",
        expected_model="MODEL_FROM_RELEASE",
        progress=lambda sent, total: print(f"Transferred: {sent}/{total}"),
    )
    print("Confirmed version after reboot:", info.firmware_version)
```

Replace the path, SHA-256 and model placeholders with release values. The SDK sends bytes unchanged without parsing the firmware contents. See [update_firmware.py](../examples/update_firmware.py) for a runnable example.

| Argument | Meaning |
| --- | --- |
| `client` / `firmware` | Connected client and the complete package bytes. |
| `version` | Required full target runtime version, such as `V2.001.0002.0000` or `V2.001.0002.0000-prod-1234abcd`; `-debug-8hex` suffixes are also accepted. Post-reboot comparison is exact, including the suffix. Updating to the already running version is rejected. |
| `sha256=None` | Optional 64-digit hexadecimal SHA-256; use the official value. A mismatch prevents the update request. |
| `expected_model=None` | Optional model that must exactly match device `model`. Starting-version compatibility must still be checked. |
| `progress=None` | Synchronous `(sent, total)` callback in bytes, for transfer progress only. Device resume requests may skip an already received prefix. |
| `timeout_s=30.0` | Timeout for a single check, transfer or reconnection operation. |
| `total_timeout_s=600.0` | Total limit for preparation checks and transfer. |
| `reboot_timeout_s=90.0` | Limit for reboot, reconnect and version verification after transfer confirmation. |

Returns `SystemInfo` read after reboot and reconnection. The SDK returns successfully only after verifying device identity and the target version. **100% transfer or a BLE disconnect does not mean installation succeeded.** Device rejection raises `DeviceError`; timeouts, transport failure and invalid responses raise `TimeoutError`, `TransportError` and `ProtocolError`. Cancellation does not withdraw received bytes; reconnect and read the version after failure.

See the [firmware update guide](../wiki/Firmware-Updates.md) for releases and recovery.

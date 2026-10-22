# Update firmware with the SDK

--8<-- "docs/_includes/devices.en.md"

Transfer an official application firmware package through Python and verify the version after reboot. Discover features first; see the [firmware guide](../wiki/Firmware-Updates.md) for downloads and device instructions.

Code snippets use `import openzilo as sdk`; `ring` is a connected client. See the [quick start](sdk-quickstart.en.md) for a complete connection example.

## Firmware updates

--8<-- "docs/_includes/features.en.md:ota"

`update_firmware()` and `ota-update` update application firmware; inspect the installed command with `openzilo ota-update --help`. They do not update the bootloader. Use an official package listing your model and starting version. Back up recordings, stop recording, downloads and IMU reporting, and maintain power and connection. The update exclusively owns this connection until it finishes.

Firmware packaging now produces `ring_sound-V2.001.0002.0001-prod-1234abcd.ota.zip` with `manifest.json`, `manifest.sig`, and `app.ota.bin`. The manifest carries version, model, board, test/production profile, security version, allowed source versions, and payload size/SHA-256. The outer signature can reuse the firmware P-256 signing key. Obtain the verification public key independently through a trusted channel; a key supplied inside a download is not a trust anchor.

```python
from pathlib import Path

bundle = Path("ring_sound-V2.001.0002.0001-prod-1234abcd.ota.zip").read_bytes()
public_key = Path("trusted-signing-public.pem").read_bytes()
metadata = sdk.inspect_firmware_bundle(bundle, trusted_public_key=public_key)
print(metadata.version, metadata.model, metadata.board)
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    info = await sdk.update_firmware(ring, bundle, trusted_public_key=public_key)
```

Display all verified metadata offline, without connecting to a ring:

```bash
openzilo ota-inspect ring_sound-V2.001.0002.0001-prod-1234abcd.ota.zip --public-key trusted-signing-public.pem
# Add --json for machine-readable output.
```

`inspect_firmware_bundle()` returns a `FirmwareBundle` whose `manifest` property is a fresh dictionary of all verified fields. Invalid signatures fail without a success marker. Successful inspection establishes package authenticity and integrity; device compatibility is checked before uploading.

```bash
openzilo ota-update --address ADDRESS ring_sound-V2.001.0002.0001-prod-1234abcd.ota.zip --public-key trusted-signing-public.pem
```

Board comparison ignores repeated `/` separators to support Zephyr qualifiers with a leading slash. Display and signature verification preserve the original metadata.

Offline checks cover signature, archive structure, lengths, digest and encryption header. Before OTA starts, the SDK checks device model, board and source version. An empty `source_versions` explicitly allows any starting version. Test bundles require `allow_test_firmware=True` or `--allow-test-firmware`. When a device cannot report its board, only an exact verified legacy profile may supply it. Currently this covers `Open Zilo` firmware `V2.001.0002.0001-prod-7fd1dfc9`, whose board is recorded in that build’s delivery metadata. Other unknown boards are rejected. Security-version enforcement and matching device encryption keys remain device checks: the SDK cannot decrypt or read rollback counters. Only the inner OTA bytes are transmitted, and the running version is still checked after reboot.

OTA accepts only this signed ZIP format and rejects raw BIN input. The target version and compatibility fields come from verified metadata; `version`, `sha256`, and `expected_model` overrides have been removed. The full runtime version, including debug/prod and commit suffixes, is compared after reboot. Updating to the already running version is rejected. See [update_firmware.py](../examples/update_firmware.py) for a runnable example.

| Argument | Meaning |
| --- | --- |
| `client` / `firmware` | Connected client and the complete package bytes. |
| `trusted_public_key` | Trusted PEM P-256 public key bytes, required for ZIPs. |
| `allow_test_firmware=False` | Explicitly permit test ZIPs. |
| `progress=None` | Synchronous `(sent, total)` callback in bytes, for transfer progress only. Device resume requests may skip an already received prefix. |
| `timeout_s=30.0` | Timeout for a single check, transfer or reconnection operation. |
| `total_timeout_s=600.0` | Total limit for preparation checks and transfer. |
| `reboot_timeout_s=90.0` | Limit for reboot, reconnect and version verification after transfer confirmation. |

Returns `SystemInfo` read after reboot and reconnection. The SDK returns successfully only after verifying device identity and the target version. **100% transfer or a BLE disconnect does not mean installation succeeded.** Device rejection raises `DeviceError`; timeouts, transport failure and invalid responses raise `TimeoutError`, `TransportError` and `ProtocolError`. Cancellation does not withdraw received bytes; reconnect and read the version after failure.

See the [firmware update guide](../wiki/Firmware-Updates.md) for releases and recovery.

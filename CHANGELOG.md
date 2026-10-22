# Changelog

## 0.6.2 - 2026-10-22

### Signed firmware bundles

- Add `inspect_firmware_bundle()` and `ota-inspect` for offline signature verification and complete metadata display, including JSON output.
- Verify the manifest signature, signing key ID, payload digest, length and encrypted APP header before an update starts.
- Check device model, board and allowed starting versions before transmitting only the inner OTA payload. Reconnect and verify the full running version after reboot.
- Require explicit opt-in for test-profile bundles. Verification requires an independently trusted P-256 public key; a downloaded bundle cannot supply its own trust anchor.

### Local IMU calibration

- Add six-face accelerometer fitting, stationary gyroscope bias fitting and independent validation.
- Store validated profiles locally, bound to the device identifier, model, exact firmware version and sensor ranges.
- Add `imu-calibrate` and explicit calibrated streams in g and deg/s. Preserve raw streaming and avoid applying corrections twice.
- Perform all calibration on the host without writing calibration parameters to the ring. A new firmware image is not required for supported IMU contracts.

### Breaking change and migration

`update_firmware()` and `ota-update` now accept only signed OTA ZIPs. Raw BIN input and the `version`, `sha256` and `expected_model` overrides have been removed. Version and compatibility fields come from verified metadata.

```python
from pathlib import Path
import openzilo as sdk

# ring is an already connected OpenZiloClient.
bundle = Path("firmware.ota.zip").read_bytes()
public_key = Path("trusted-signing-public.pem").read_bytes()
metadata = sdk.inspect_firmware_bundle(bundle, trusted_public_key=public_key)
info = await sdk.update_firmware(ring, bundle, trusted_public_key=public_key)
```

`cryptography>=43` is now a required dependency. Existing firmware OTA wire protocols remain unchanged. Device-side encryption-key matching and rollback enforcement remain device checks; host verification does not confirm installation or hardware calibration accuracy.

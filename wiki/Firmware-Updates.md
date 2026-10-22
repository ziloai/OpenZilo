# Firmware updates

--8<-- "docs/_includes/devices.en.md"

[English](https://github.com/ziloai/OpenZilo/wiki/Firmware-Updates) | [简体中文](https://github.com/ziloai/OpenZilo/wiki/Firmware-Updates-zh-CN)

--8<-- "docs/_includes/features.en.md:ota"

## 1. Select a package

Open [official firmware releases](https://github.com/ziloai/OpenZilo-Hardware/releases). Confirm that your model and hardware revision are supported, your current version is an allowed starting version, and you have read the data-retention policy and known issues.

Download the versioned signed OTA ZIP and obtain its signing public key independently through a trusted channel. The signed metadata carries the target version, model, board and payload digest. Factory flashing files are not SDK OTA packages.

## 2. Prepare

Back up important recordings. Stop recording, downloads and IMU reporting, and disconnect other apps. Ensure sufficient charge according to the release instructions.

From the SDK repository:

```bash
uv sync --locked
uv run openzilo device use
uv run openzilo info
```

Record the current firmware version. Run `uv run openzilo ota-update --help` to inspect the installed updater.

## 3. Run the update

Replace each placeholder with the values for this release:

```bash
uv run openzilo ota-inspect "path/to/firmware.ota.zip" --public-key "path/to/trusted-signing-public.pem"
uv run openzilo ota-update "path/to/firmware.ota.zip" --public-key "path/to/trusted-signing-public.pem"
```

The command uses your saved device; `--address` selects another one. Keep the ring nearby and avoid interrupting power or Bluetooth.

`ota-inspect` verifies signatures and displays all metadata offline; add `--json` for JSON. `ota-update` checks device model, board and source version before sending only the inner OTA bytes. Raw BIN input and manual version, digest or model overrides are no longer accepted. Test-profile ZIPs require `--allow-test-firmware`; boards must be reported by the device or provided by an exact verified legacy profile; unknown boards are rejected.

## 4. Confirm completion

After transfer, the SDK waits for reboot, reconnects, checks that it is the same device, and reads its firmware version. **The command reports success only after the target version is confirmed.** Continue waiting when transfer reaches 100%.

Run `uv run openzilo info` again, record a short clip and check the features your application uses.

Timeouts are in seconds: `--timeout` defaults to 30 per operation, `--total-timeout` to 600 for preparation and transfer, and `--reboot-timeout` to 90 for reboot, reconnect and version checks. See the [SDK guide](../docs/sdk-ota.en.md#firmware-updates) and [update_firmware.py](../examples/update_firmware.py) for Python integration.

## If the update is interrupted

Reconnect and read the firmware version before retrying after a timeout, disconnect or cancellation. Exiting the computer-side updater does not withdraw a package already received by the ring.

If reconnection fails, record the starting version, target version and error message, then [contact support](mailto:openzilo@ziloring.com). Downgrade, recovery and recording retention depend on the release instructions.

# Collect IMU data

--8<-- "docs/_includes/devices.en.md"

Start accelerometer and gyroscope reports, receive single-sample or batch data, and stop reporting when finished. Discover device features first. See [event handling](sdk-events.en.md) for button and tap events.

Code snippets use `import openzilo as sdk`; `ring` is a connected client. See the [quick start](sdk-quickstart.en.md) for a complete connection example.

## Receive IMU batches

--8<-- "docs/_includes/firmware-0001.en.md"

```text
connect -> discover features
        -> start_sensor_report succeeds (0x0601 -> 0x0602 error_code=0)
        -> wait_sensor_data loop (receive 0x0605)
        -> stop_sensor_report
```

Firmware `V2.001.0002.0001` starts capture on subscription without a button-based mode change. Firmware `V2.001.0002.0000` requires gesture mode first.

```python
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    await sdk.get_device_capabilities(ring)
    start = await sdk.start_sensor_report(ring)
    print(start)
    try:
        for _ in range(10):
            batch = await sdk.wait_sensor_data(ring, timeout_s=5.0)
            for sample in batch.samples:
                print(batch.sequence_start, sample.timestamp_ms, sample.accel_x)
    finally:
        await sdk.stop_sensor_report(ring)
```

Start the `wait_sensor_data()` loop only after `start_sensor_report()` succeeds. Waiting receives the next `0x0605`; it does not send `0x0601` or start the local IMU.

## IMU data

--8<-- "docs/_includes/features.en.md:imu"

Firmware `V2.001.0002.0001` removes recording/gesture modes. A BLE connection alone does not start IMU capture:

- `start_sensor_report()` (`0x0601`) starts capture and `0x0605` reporting. Wait for successful `0x0602` before receiving data.
- `stop_sensor_report()` (`0x0603`) stops reports and capture; tap detection stops with capture.
- Disconnection stops capture; subscribe again after reconnecting.
- Use the returned `SensorStartInfo.sample_rate_hz`.

Firmware `V2.001.0002.0000` requires gesture mode first and can retain local tap detection after BLE reporting stops. That old procedure does not apply to `V2.001.0002.0001`.

Current `0x0605` batch body:

```text
error_code: u16
sequence_start: u32
frame_count: u16
sample_size: u16
samples: frame_count * sample_size
```

Each sample is currently `16` bytes:

```text
timestamp_ms: u32
accel_x: i16
accel_y: i16
accel_z: i16
gyro_x: i16
gyro_y: i16
gyro_z: i16
```

Usage:

```python
# Firmware V2.001.0002.0001: subscription starts capture without a mode change.
start = await sdk.start_sensor_report(ring)  # Await success before expecting 0x0605
print(start.sample_rate_hz)
try:
    batch = await sdk.wait_sensor_data(ring, timeout_s=5.0)
    for index, sample in enumerate(batch.samples):
        sequence = batch.sequence_start + index
        print(sequence, sample.timestamp_ms, sample.accel_x, sample.gyro_x)
finally:
    await sdk.stop_sensor_report(ring)
```

## Receive ten IMU batches

--8<-- "docs/_includes/firmware-0001.en.md"

Firmware `V2.001.0002.0001` starts IMU directly; firmware `V2.001.0002.0000` requires entering gesture mode using the button first.

```python
import asyncio
import openzilo as sdk

ADDRESS = "AA:BB:CC:DD:EE:FF"


async def main() -> None:
    async with sdk.OpenZiloClient(address=ADDRESS) as ring:
        await sdk.get_device_capabilities(ring)
        await sdk.start_sensor_report(ring)
        try:
            for _ in range(10):
                batch = await sdk.wait_sensor_data(ring, timeout_s=5.0)
                print("batch:", batch.sequence_start, batch.frame_count)
                for sample in batch.samples:
                    print(sample.timestamp_ms, sample.accel_x, sample.gyro_x)
        finally:
            await sdk.stop_sensor_report(ring)


if __name__ == "__main__":
    asyncio.run(main())
```

## Save `0x0605` to TXT

--8<-- "docs/_includes/firmware-0001.en.md"

This example uses the direct-start behavior of `V2.001.0002.0001`.

```python
import asyncio
import openzilo as sdk

ADDRESS = "AA:BB:CC:DD:EE:FF"


async def main() -> None:
    async with sdk.OpenZiloClient(address=ADDRESS) as ring:
        await sdk.get_device_capabilities(ring)
        await sdk.start_sensor_report(ring)
        try:
            with open("imu_0605.txt", "w", encoding="utf-8") as f:
                for _ in range(20):
                    batch = await sdk.wait_sensor_data(ring, timeout_s=5.0)
                    for i, sample in enumerate(batch.samples):
                        seq = batch.sequence_start + i
                        f.write(
                            f"{seq},{sample.timestamp_ms},"
                            f"{sample.accel_x},{sample.accel_y},{sample.accel_z},"
                            f"{sample.gyro_x},{sample.gyro_y},{sample.gyro_z}\n"
                        )
        finally:
            await sdk.stop_sensor_report(ring)


if __name__ == "__main__":
    asyncio.run(main())
```

## Local software calibration

OpenZilo computes, stores and applies calibration on the host. No calibration commands or
parameters are written to the ring. The known legacy IMU/2 firmware is supported; unknown
or incompatible contracts are rejected. Firmware upgrades are not required for this feature.

```bash
openzilo imu-calibrate accel
openzilo imu-calibrate quick
openzilo imu-calibrate full
openzilo imu-calibrate show
openzilo imu-calibrate reset
openzilo sensor-stream --calibrated --seconds 10
```

`accel` collects six signed gravity directions with the ring fixed in the charging case,
then fits diagonal accelerometer biases/gains and validates new data on three distinct axes.
An inverted attachment and arbitrary face order are supported. Release the case before
pressing Enter; use a support if necessary. Do not remove and reattach the ring during the six
faces. Each face settles for 2 seconds and records at least 5 seconds.

`quick` calibrates only gyro bias. Remove the ring from the case, keep it away from magnets,
and lay it still, with paper support to prevent rolling. Three consecutive windows must have
mean gyro ranges within 0.08 deg/s (up to 3 minutes), followed by a minimum 20-second bias
recording and fresh independent validation. Charging, magnetic attachment and temperature
conditions must not be confused with normal-use bias. There is no full-turn rotation.

`full` performs both stages and replaces the local file only when both pass. Cancellation,
drift, failed validation or storage failure preserves the previous file. Use `accel` first and
`quick` later to retain independent progress. Each action preserves any previously validated
parameters of the other component. Unvalidated components remain uncorrected.

Original `start_sensor_report`, `wait_sensor_data` and default `sensor-stream` semantics
remain unchanged. Software correction is explicit:

```python
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    async with sdk.open_calibrated_imu_stream(ring) as stream:
        async for batch in stream:
            for sample in batch.samples:
                print(sample.timestamp_ms, sample.accel_g, sample.gyro_dps)
            print(batch.applied_components)
```

The context starts/stops reports, cleans up on errors/cancellation, and is invalid after
reconnect. Use an exclusive IMU consumer on the connection. Custom transports must provide
`device_id=` for profile binding. `CalibratedImuBatch` and `CalibratedImuSample` preserve
sequences/counts/timestamps and contain new float tuples in g and deg/s, leaving raw objects
untouched. CLI JSONL marks `data_domain="software_calibrated"`, `accel_unit="g"`,
`gyro_unit="deg/s"`, and `applied_components`. An accel-only profile does not subtract gyro bias.

For range R, raw signed counts convert by `counts * R / 32768`. Per-axis corrections are
`(accel_g - accel_bias_ug/1e6) * accel_scale_ppm/1e6` and
`gyro_dps - gyro_bias_udps/1e6`. The six-face fit uses a diagonal ellipsoid with unit gravity
magnitude, permitting small fixture tilt. Gravity is retained. There is no gyro gain fit,
full cross-axis matrix, temperature compensation, orientation fusion or drift-free heading.

Sampling rejects gaps, clipping, movement and within-window drift. Initial thresholds are
0.008 g accel standard deviation, 0.06 g peak-to-peak, 0.3 deg/s gyro standard deviation,
and first/second-half mean changes of 0.003 g / 0.15 deg/s. Accel-stage quality ignores gyro
bias/noise. Independent acceptance thresholds are 0.015 g gravity-norm error and 0.15 deg/s
mean gyro residual per axis. Thresholds are acceptance rules, not universal accuracy claims.

Profiles live next to CLI preferences under `imu/<device_hash>.json`, normally
`~/.config/openzilo/imu/` on Linux. They record schema, input domain, units, device hash,
model, exact firmware version, parameters, component validation flags and creation time.
Unknown chip type is 0. Device/model/firmware/ranges must match; recalibrate after firmware
upgrades. Corrupt profiles fail explicitly. Save uses a temporary file, sync and atomic replace.
Override with `imu-calibrate --profile FILE` or `sensor-stream --calibrated --calibration-profile FILE`.

Public helpers include `ImuCalibration`, `ImuCalibrationProfile`, `imu_device_key`,
`imu_calibration_path`, `load_imu_calibration_profile`, `save_imu_calibration_profile`,
`apply_imu_calibration`, `analyze_imu_static_window`, `collect_imu_static_window`,
`fit_imu_six_face_calibration`, `fit_imu_gyro_bias`, and `validate_imu_calibration`.
Offline application requires original raw samples and rejects already-calibrated batch types.

Future firmware application must explicitly negotiate raw/corrected data, chip identity,
storage and ownership. This SDK sends no calibration commands and refuses software streams
when firmware advertises calibration feature ID 11, preventing double correction.

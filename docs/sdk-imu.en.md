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

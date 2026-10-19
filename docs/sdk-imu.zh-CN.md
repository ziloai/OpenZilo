# IMU 数据采集

--8<-- "docs/_includes/devices.zh-CN.md"

开启加速度计和陀螺仪上报，读取单点或批量数据，并在结束时停止上报。先查询设备支持的功能。按键和敲击事件见[事件接收](sdk-events.zh-CN.md)。

以下代码片段使用 `import openzilo as sdk`；`ring` 表示已连接的客户端，完整连接示例见[快速开始](sdk-quickstart.zh-CN.md)。

## 接收批量 IMU 数据

--8<-- "docs/_includes/firmware-0001.zh-CN.md"

```text
connect -> 查询功能
        -> start_sensor_report 成功（0x0601 -> 0x0602 error_code=0）
        -> wait_sensor_data loop（接收 0x0605）
        -> stop_sensor_report
```

固件 `V2.001.0002.0001` 由订阅启动采集，无需先按键切换模式。固件 `V2.001.0002.0000` 需先进入手势模式。

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

只有 `start_sensor_report()` 成功返回后才能开始循环调用 `wait_sensor_data()`。后者只等待下一批 `0x0605`，不会自动发送 `0x0601`，也不会启动本地 IMU。

## 六轴数据

--8<-- "docs/_includes/features.zh-CN.md:imu"

固件 `V2.001.0002.0001` 不再区分录音模式与手势模式，蓝牙连接本身不会启动 IMU：

- `start_sensor_report()`（`0x0601`）启动采集和 `0x0605` 上报；等待 `0x0602` 成功后再接收数据。
- `stop_sensor_report()`（`0x0603`）停止上报和采集，敲击检测也随采集停止。
- 断开连接后停止采集；重新连接后需再次订阅。
- 采样率使用返回的 `SensorStartInfo.sample_rate_hz`。

固件 `V2.001.0002.0000` 需先进入手势模式，停止 BLE 上报后仍可保留本地敲击检测。这一旧操作方式不用于 `V2.001.0002.0001`。

设备端当前 `0x0605` 包体：

```text
error_code: u16
sequence_start: u32
frame_count: u16
sample_size: u16
samples: frame_count * sample_size
```

每个 sample 当前固定 `16` 字节：

```text
timestamp_ms: u32
accel_x: i16
accel_y: i16
accel_z: i16
gyro_x: i16
gyro_y: i16
gyro_z: i16
```

调用方式：

```python
# 固件 V2.001.0002.0001：无需切换模式，订阅时启动采集。
start = await sdk.start_sensor_report(ring)  # 成功返回后才会有 0x0605
print(start.sample_rate_hz)
try:
    batch = await sdk.wait_sensor_data(ring, timeout_s=5.0)
    for index, sample in enumerate(batch.samples):
        sequence = batch.sequence_start + index
        print(sequence, sample.timestamp_ms, sample.accel_x, sample.gyro_x)
finally:
    await sdk.stop_sensor_report(ring)
```

## 接收 10 批 IMU 数据

--8<-- "docs/_includes/firmware-0001.zh-CN.md"

固件 `V2.001.0002.0001` 直接启动 IMU；固件 `V2.001.0002.0000` 需先通过按键进入手势模式。

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

## 保存 `0x0605` 到 TXT

--8<-- "docs/_includes/firmware-0001.zh-CN.md"

以下示例使用 `V2.001.0002.0001` 的直接启动方式。

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

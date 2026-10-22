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

<a id="local-software-calibration"></a>

## 本机软件校准

OpenZilo 在电脑端计算、保存和应用校准参数，不向戒指发送校准命令或写入参数。已核实的旧版 IMU/2 固件可使用此功能；未知或不兼容的功能契约会被拒绝，无需为本机校准升级固件。

```bash
openzilo imu-calibrate accel
openzilo imu-calibrate quick
openzilo imu-calibrate full
openzilo imu-calibrate show
openzilo imu-calibrate reset
openzilo sensor-stream --calibrated --seconds 10
```

`accel` 在戒指固定于充电盒内时采集六个正、负重力方向，拟合各轴加速度零偏和增益，再使用三个不同轴上的新数据独立验证。支持倒置吸附和任意采集顺序。摆好盒子后松手，再按 Enter；必要时使用支架。六面采集期间不要取下戒指重新吸附。每面先等待 2 秒稳定，再采集至少 5 秒。

`quick` 只校准陀螺仪零偏。将戒指取出充电盒，远离磁铁并平放，必要时用纸片防止滚动。软件最多等待 3 分钟，要求连续三个静止窗口的各轴均值范围均不超过 0.08 度/秒，然后采集至少 20 秒计算零偏，再用新数据独立验证。充电、磁吸和温度条件下的偏置不能直接当作日常使用的零偏；不需要旋转整圈。

`full` 顺序执行两阶段，全部通过后才替换本机文件。取消、漂移、验证失败或存储失败均保留原文件。也可先执行 `accel`，之后再执行 `quick`，分别保留已完成的结果。每次操作都会保留另一组件已经验证的参数；未验证的组件不应用校正。

原有 `start_sensor_report`、`wait_sensor_data` 和默认 `sensor-stream` 的原始数据语义保持不变。软件校正需显式启用：

```python
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    async with sdk.open_calibrated_imu_stream(ring) as stream:
        async for batch in stream:
            for sample in batch.samples:
                print(sample.timestamp_ms, sample.accel_g, sample.gyro_dps)
            print(batch.applied_components)
```

上下文负责启动、停止上报，并在出错或取消时清理；重连后需重新打开。同一连接应由一个 IMU 消费者独占。自定义 transport 必须通过 `device_id=` 提供配置绑定标识。`CalibratedImuBatch` 和 `CalibratedImuSample` 保留序号、数量和时间戳，以新的浮点元组输出 g 和度/秒，不修改原始对象。CLI 的 JSONL 输出带有 `data_domain="software_calibrated"`、`accel_unit="g"`、`gyro_unit="deg/s"` 和 `applied_components`。仅有加速度校准参数时，不会减去陀螺仪零偏。

量程为 R 时，原始有符号计数按 `counts * R / 32768` 换算。逐轴校正公式为 `(accel_g - accel_bias_ug/1e6) * accel_scale_ppm/1e6` 和 `gyro_dps - gyro_bias_udps/1e6`。六面拟合使用重力模长为 1 的对角椭球，允许夹具存在小幅倾斜，并保留重力分量。不拟合陀螺仪增益或完整交叉轴矩阵，也不提供温度补偿、姿态融合或航向无漂移保证。

采样会拒绝序号间断、饱和、移动和窗口内漂移。初始门槛为：加速度标准差 0.008 g、峰峰值 0.06 g、陀螺仪标准差 0.3 度/秒；窗口前后半段均值变化分别不超过 0.003 g 和 0.15 度/秒。加速度阶段不使用陀螺仪偏置或噪声作为验收依据。独立验证要求重力模长误差不超过 0.015 g，陀螺仪各轴均值残差不超过 0.15 度/秒。这些是验收规则，不是所有环境下的精度承诺。

配置保存在 CLI 配置目录下的 `imu/<device_hash>.json` 中，Linux 通常为 `~/.config/openzilo/imu/`。文件记录结构版本、输入数据域、单位、设备哈希、型号、完整固件版本、参数、组件验证状态和创建时间。未知芯片类型为 0。设备、型号、固件和量程必须匹配；固件升级后应重新校准。损坏的配置会明确报错。保存过程使用临时文件、同步和原子替换。可通过 `imu-calibrate --profile FILE` 或 `sensor-stream --calibrated --calibration-profile FILE` 指定文件。

公开辅助接口包括 `ImuCalibration`、`ImuCalibrationProfile`、`imu_device_key`、`imu_calibration_path`、`load_imu_calibration_profile`、`save_imu_calibration_profile`、`apply_imu_calibration`、`analyze_imu_static_window`、`collect_imu_static_window`、`fit_imu_six_face_calibration`、`fit_imu_gyro_bias` 和 `validate_imu_calibration`。离线应用必须传入未经校正的原始样本，已经校正的批次类型会被拒绝。

若未来将校准迁移到固件，必须明确协商原始或校正数据域、芯片身份、存储和参数应用位置。本版 SDK 不发送校准命令；固件若声明校准功能 ID 11，软件校正流会拒绝启动，避免重复校正。

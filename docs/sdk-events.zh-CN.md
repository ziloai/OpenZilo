# 按键与敲击事件

--8<-- "docs/_includes/devices.zh-CN.md"

等待设备主动发送的按键和敲击事件。固件 `V2.001.0002.0001` 的单击只上报事件，不切换录音／手势模式。

以下代码片段使用 `import openzilo as sdk`；`ring` 表示已连接的客户端，完整连接示例见[快速开始](sdk-quickstart.zh-CN.md)。

## 动作事件

`0x0701` 普通双击：

固件 `V2.001.0002.0001` 先用 `start_sensor_report()` 启动 IMU，再等待敲击事件；停止采集后不再检测。固件 `V2.001.0002.0000` 则在手势模式下检测，无需开启 BLE 数据上报。

```python
await sdk.start_sensor_report(ring)
try:
    event = await sdk.wait_sensor_double_tap_event(ring, timeout_s=30.0)
    print(event.timestamp_ms)
finally:
    await sdk.stop_sensor_report(ring)
```

`0x0703` 按键双击：

按键双击是排他事件。双击成立时只上报 `0x0703`，不会再产生对应的 `0x0704`，也不会切换录音/手势模式。

```python
event = await sdk.wait_sensor_key_double_press_event(ring, timeout_s=30.0)
print(event.timestamp_ms)
```

`0x0704` 按键单击：

```python
event = await sdk.wait_sensor_key_single_press_event(ring, timeout_s=30.0)
print(event.timestamp_ms)
```

固件 `V2.001.0002.0001` 确认单击后只上报 `0x0704`，不切换模式。固件 `V2.001.0002.0000` 会尝试切换录音／手势模式并上报事件。单击仍需等待双击判定窗口结束，事件包体不包含模式字段。

### `wait_sensor_key_single_press_event()`

```python
event = await sdk.wait_sensor_key_single_press_event(
    ring,
    timeout_s=30.0,
)
```

- 作用：等待设备主动上报的 `0x0704` 按键单击事件。
- `ring`：已经连接的 `OpenZiloClient`。
- `timeout_s`：最长等待秒数；为 `None` 时使用客户端的 `command_timeout_s`。
- 返回值：`SensorKeySinglePressEvent`，其中 `timestamp_ms` 在本固件中是秒级设备时间，名称沿用 SDK 历史字段。
- 异常：等待超时抛出 SDK 的 `TimeoutError`；收到损坏包时可能抛出 `ProtocolError`。

### `parse_sensor_key_single_press_event()`

```python
event = sdk.parse_sensor_key_single_press_event(body)
```

- 作用：解析已经去掉 11 字节协议头的 `0x0704` 包体，通常只用于协议测试和自定义接收流程。
- `body`：必须恰好包含一个网络字节序的 `u32` 时间戳，共 4 字节。
- 返回值：`SensorKeySinglePressEvent`。
- 异常：包体不足 4 字节或存在多余字节时抛出 `ProtocolError`。

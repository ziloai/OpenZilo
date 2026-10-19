# 扫描与连接

--8<-- "docs/_includes/devices.zh-CN.md"

扫描附近设备并管理蓝牙连接。首次使用见[快速开始](sdk-quickstart.zh-CN.md)；连接后查询功能见[SDK 与固件兼容](compatibility.zh-CN.md)。

以下代码片段使用 `import openzilo as sdk`；`ring` 表示已连接的客户端，完整连接示例见[快速开始](sdk-quickstart.zh-CN.md)。

## `scan_rings()`

作用：扫描附近 BLE 设备，可按 MAC 地址过滤。

签名：

```python
devices = await scan_rings(address=None, timeout_s=25.0)
```

返回：`list[BleDeviceInfo]`

`timeout_s` 是本次扫描允许等待的最长时间，默认值为 25 秒；调用方可按需要显式传入其他正数。

常见异常：未安装 `bleak` 时抛出 `TransportError`。

示例：

```python
devices = await sdk.scan_rings(address="AA:BB:CC:DD:EE:FF")
print(devices)
```

## `connect_ring()`

作用：创建并连接 `OpenZiloClient`。

签名：

```python
ring = await connect_ring(
    address="AA:BB:CC:DD:EE:FF",
    command_timeout_s=10.0,
    auto_time_sync=False,
    negotiate_capabilities=True,
    allow_unverified_features=False,
)
```

返回：已连接的 `OpenZiloClient`。

连接后会自动查询设备支持的功能。调用方需在 `finally` 中执行 `await ring.disconnect()`。若使用 `async with OpenZiloClient(...)` 自动断开连接，请另行调用 `get_device_capabilities()` 查询功能。

## `OpenZiloClient`

作用：高层连接对象。负责 BLE 连接、协议收包、命令请求、事件等待。

常用方式：

```python
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    packet = await ring.request(0x0101, 0x0102)
```

常用成员：

- `is_connected`：当前是否连接。
- `connect()` / `disconnect()`：手动连接和断开。
- `send_command(command, body=b"")`：只发送命令，不等待响应。
- `request(command, response_command, body=b"", timeout_s=None)`：发送并等待指定响应。
- `wait_for_command(command, timeout_s=None)`：等待设备主动上报或后续响应。
- `add_packet_handler(command, handler, queue_packets=True)`：注册异步或同步包处理器。设为 `False` 时独占该命令的接收，不再保留队列副本；不能与同命令的其他处理器或等待接口混用。处理器抛出的异常会记录到 `openzilo` 日志，不会影响其他包；断线时会取消未完成的异步处理器。
- `remove_packet_handler(command, handler)`：移除处理器。

接收队列每个命令默认最多 256 个包，可通过 `OpenZiloClient(receive_queue_size=...)` 调整。溢出会清理该命令的积压包，并通过等待接口报告 `ProtocolError`，不会将数据缺失当作成功。只使用回调时建议 `queue_packets=False`；处理器应尽快返回，异步处理器自行控制处理并发。

同一响应命令的 `request()` 会串行执行。录音下载、自动接收、逐帧读取和清空等高层操作不能竞争同一连接，冲突时立即抛出 `ProtocolError`。手动组合低层录音接口时，应用仍需管理整段会话。OTA 期间拒绝其他任务的普通命令，自动校时应答除外；开始 OTA 前应停止录音及 IMU。

普通下载失败或取消后会尽力发送结束命令，清理最多等待 2 秒，清理失败不覆盖原始异常。协议没有事务 ID，同命令超时后的迟到响应无法可靠归属；需要严格隔离时应重连后再发起新请求。

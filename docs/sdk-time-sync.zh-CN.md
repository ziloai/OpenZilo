# 设备校时

--8<-- "docs/_includes/devices.zh-CN.md"

配置 SDK 对设备校时请求的自动应答，或在应用中手动回复时间。无需先查询功能列表。

以下代码片段使用 `import openzilo as sdk`；`ring` 表示已连接的客户端，完整连接示例见[快速开始](sdk-quickstart.zh-CN.md)。

## 自动校时

```text
connect -> enable_time_sync -> 保持连接
```

```python
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    sdk.enable_time_sync(ring)
    await asyncio.sleep(60)
```

## `enable_time_sync()` 和 `send_time_response()`

`enable_time_sync()` 注册自动校时处理器。设备发送 `0x0401` 后，SDK 自动回复 `0x0402`。

可以在连接前启用；连接建立或重连期间收到的请求会等待该连接就绪后再回复。SDK 保留请求到达时的接收时间，并在取得写锁、实际发送前生成发送时间。断开或连接失败时取消该连接的待发送应答，不会将旧应答发送到新连接。重复调用不会重复注册处理器。`connect_ring(auto_time_sync=True)` 会在开始连接前注册，接住通知刚启用时的校时请求。

```python
sdk.enable_time_sync(ring)
```

`send_time_response()` 用于手动回复校时请求：

```python
await sdk.send_time_response(ring, request_time)
```

`request_time` 应来自设备 `0x0401` 包体。

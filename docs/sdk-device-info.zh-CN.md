# 读取设备信息

--8<-- "docs/_includes/devices.zh-CN.md"

读取型号、固件版本、电量和存储信息。无需先查询功能列表。返回字段见[数据类型](sdk-data-types.zh-CN.md)。

以下代码片段使用 `import openzilo as sdk`；`ring` 表示已连接的客户端，完整连接示例见[快速开始](sdk-quickstart.zh-CN.md)。

## 读取系统信息

```text
connect -> get_system_info -> disconnect
```

```python
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    info = await sdk.get_system_info(ring)
```

## `get_system_info()` 和 `parse_system_info()`

`get_system_info()` 读取设备系统信息；`parse_system_info()` 只解析 `0x0102` 包体，通常用于测试。

```python
info = await sdk.get_system_info(ring)
print(info.firmware_version, info.battery_percent)
```

返回：`SystemInfo`

常见异常：超时抛出 `TimeoutError`；设备返回错误码抛出 `DeviceError`。

# 读取设备日志

--8<-- "docs/_includes/devices.zh-CN.md"

查询设备日志存储并分块读取原始字节。无需先查询功能列表。

以下代码片段使用 `import openzilo as sdk`；`ring` 表示已连接的客户端，完整连接示例见[快速开始](sdk-quickstart.zh-CN.md)。

## `get_log_storage()` 和 `read_log_chunk()`

```python
storage = await sdk.get_log_storage(ring)
chunk = await sdk.read_log_chunk(ring, index=0, offset=0, size=256)
print(chunk.decode("utf-8", errors="replace"))
```

`read_log_chunk()` 返回原始 `bytes`。调用方可以按 UTF-8 或设备端实际日志编码解码。

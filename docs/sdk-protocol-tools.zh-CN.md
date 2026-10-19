# 协议调试工具

--8<-- "docs/_includes/devices.zh-CN.md"

直接处理协议字节，用于联调和自定义传输。一般应用优先使用高层功能接口。包格式见[协议参考](protocol.zh-CN.md)。

以下代码片段使用 `import openzilo as sdk`；`ring` 表示已连接的客户端，完整连接示例见[快速开始](sdk-quickstart.zh-CN.md)。

## 协议调试工具

通常业务代码不需要直接使用这些工具。

```python
packet_bytes = sdk.encode_packet(0x0101)
packet = sdk.decode_packet(packet_bytes)
crc = sdk.crc16_compute(packet.body)
```

`PacketStream` 可用于把 BLE 分片重组成完整包：

```python
stream = sdk.PacketStream()
for packet in stream.feed(chunk):
    print(packet.command, packet.body)
```

`BinaryReader` 和 `BinaryWriter` 用于解析或构造协议包体：

```python
body = sdk.BinaryWriter().u16(0).u32(0).build()
reader = sdk.BinaryReader(body)
error_code = reader.u16()
```

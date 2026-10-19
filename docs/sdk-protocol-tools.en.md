# Protocol debugging utilities

--8<-- "docs/_includes/devices.en.md"

Work directly with protocol bytes for debugging and custom transports. Prefer the high-level feature APIs in applications. See the [protocol reference](protocol.en.md) for packet formats.

Code snippets use `import openzilo as sdk`; `ring` is a connected client. See the [quick start](sdk-quickstart.en.md) for a complete connection example.

## Protocol debugging utilities

Application code normally does not need these directly.

```python
packet_bytes = sdk.encode_packet(0x0101)
packet = sdk.decode_packet(packet_bytes)
crc = sdk.crc16_compute(packet.body)
```

Use `PacketStream` to reconstruct packets from BLE fragments:

```python
stream = sdk.PacketStream()
for packet in stream.feed(chunk):
    print(packet.command, packet.body)
```

Use `BinaryReader` and `BinaryWriter` to read or build bodies:

```python
body = sdk.BinaryWriter().u16(0).u32(0).build()
reader = sdk.BinaryReader(body)
error_code = reader.u16()
```

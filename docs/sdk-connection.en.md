# Scan and connect

--8<-- "docs/_includes/devices.en.md"

Scan for nearby devices and manage the BLE connection. Start with the [quick start](sdk-quickstart.en.md); see [compatibility](compatibility.en.md) for feature discovery after connecting.

Code snippets use `import openzilo as sdk`; `ring` is a connected client. See the [quick start](sdk-quickstart.en.md) for a complete connection example.

## `scan_rings()`

Purpose: scan nearby BLE devices, optionally filtering by address.

Signature:

```python
devices = await scan_rings(address=None, timeout_s=25.0)
```

Returns: `list[BleDeviceInfo]`.

`timeout_s` limits the scan duration and defaults to 25 seconds. Supply another positive value if needed.

Common exception: `TransportError` if `bleak` is missing.

Example:

```python
devices = await sdk.scan_rings(address="AA:BB:CC:DD:EE:FF")
print(devices)
```

## `connect_ring()`

Purpose: create and connect an `OpenZiloClient`.

Signature:

```python
ring = await connect_ring(
    address="AA:BB:CC:DD:EE:FF",
    command_timeout_s=10.0,
    auto_time_sync=False,
    negotiate_capabilities=True,
    allow_unverified_features=False,
)
```

Returns: a connected `OpenZiloClient`.

Features are discovered automatically. Call `await ring.disconnect()` in `finally`. With `async with OpenZiloClient(...)`, discover features explicitly through `get_device_capabilities()`.

## `OpenZiloClient`

Purpose: manage BLE connection, packet reception, requests and event waits.

Typical usage:

```python
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    packet = await ring.request(0x0101, 0x0102)
```

Common members:

- `is_connected`: whether the connection is currently open.
- `connect()` / `disconnect()`: connect and disconnect manually.
- `send_command(command, body=b"")`: send without waiting for a response.
- `request(command, response_command, body=b"", timeout_s=None)`: send and await the specified response.
- `wait_for_command(command, timeout_s=None)`: await an event or subsequent response.
- `add_packet_handler(command, handler, queue_packets=True)`: register a synchronous or asynchronous handler. With `False`, the handler exclusively receives this command instead of delivering it through waiting APIs; do not mix with other handlers or waiters for that command. Exceptions are logged to `openzilo` without affecting other packets. Disconnect cancels unfinished asynchronous handlers.
- `remove_packet_handler(command, handler)`: remove a handler.

Slow reception reports `ProtocolError` through waiting APIs. Configure receive capacity with `receive_queue_size`, and return promptly from handlers. For callback-only use, select `queue_packets=False`.

Recording download, automatic reception, frame reads and deletion cannot compete on one connection; conflicts immediately raise `ProtocolError`. Applications combining low-level recording functions must manage the whole session. OTA rejects ordinary commands from other tasks, except automatic time replies. Stop recording and IMU before OTA.

Failed or cancelled downloads attempt to end extraction; reconnect before retrying if the device remains busy. Without transaction IDs, late responses after a timeout cannot be reliably matched; reconnect before retrying when strict isolation is required.

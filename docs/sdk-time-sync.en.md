# Synchronize device time

--8<-- "docs/_includes/devices.en.md"

Configure automatic replies to device time requests, or respond manually in your application. Feature discovery is not required.

Code snippets use `import openzilo as sdk`; `ring` is a connected client. See the [quick start](sdk-quickstart.en.md) for a complete connection example.

## Enable automatic time synchronization

```text
connect -> enable_time_sync -> keep the connection open
```

```python
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    sdk.enable_time_sync(ring)
    await asyncio.sleep(60)
```

## `enable_time_sync()` and `send_time_response()`

`enable_time_sync()` registers an automatic handler that replies to device `0x0401` with `0x0402`.

It can be enabled before connection. Requests received while connecting or reconnecting wait until that connection is ready. The SDK records reception time when the request arrives and generates send time immediately before writing under the write lock. Disconnect or connection failure cancels pending replies; old replies never reach a new connection. Repeated calls do not duplicate the handler. `connect_ring(auto_time_sync=True)` registers before connecting to catch requests immediately after notifications start.

```python
sdk.enable_time_sync(ring)
```

Use `send_time_response()` for a manual reply:

```python
await sdk.send_time_response(ring, request_time)
```

Take `request_time` from the device's `0x0401` body.

# Read device information

--8<-- "docs/_includes/devices.en.md"

Read the model, firmware, battery and storage information. Feature discovery is not required. Returned fields are listed in [data types](sdk-data-types.en.md).

Code snippets use `import openzilo as sdk`; `ring` is a connected client. See the [quick start](sdk-quickstart.en.md) for a complete connection example.

## Read device information

```text
connect -> get_system_info -> disconnect
```

```python
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    info = await sdk.get_system_info(ring)
```

## `get_system_info()` and `parse_system_info()`

`get_system_info()` reads device information. `parse_system_info()` parses only the `0x0102` body, normally for testing.

```python
info = await sdk.get_system_info(ring)
print(info.firmware_version, info.battery_percent)
```

Returns: `SystemInfo`.

Common exceptions: `TimeoutError` for timeout, `DeviceError` for a device error code.

# Read device logs

--8<-- "docs/_includes/devices.en.md"

Inspect device log storage and read raw bytes in chunks. Feature discovery is not required.

Code snippets use `import openzilo as sdk`; `ring` is a connected client. See the [quick start](sdk-quickstart.en.md) for a complete connection example.

## `get_log_storage()` and `read_log_chunk()`

```python
storage = await sdk.get_log_storage(ring)
chunk = await sdk.read_log_chunk(ring, index=0, offset=0, size=256)
print(chunk.decode("utf-8", errors="replace"))
```

`read_log_chunk()` returns raw `bytes`. Decode using UTF-8 or the firmware's actual log encoding.

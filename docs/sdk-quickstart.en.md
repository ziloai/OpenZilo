# Quick start

--8<-- "docs/_includes/devices.en.md"

Connect a ring, read its model, firmware and battery level, then disconnect. Install the SDK using the [installation guide](sdk-install.en.md) first.

## Scan for a device

Run the following command in your uv project and copy the device address from its output.

```bash
uv run openzilo scan
```

## Connect and read device information

Replace `AA:BB:CC:DD:EE:FF` with the scanned address. On macOS, use the UUID returned by scanning:

```python
import asyncio
import openzilo as sdk

ADDRESS = "AA:BB:CC:DD:EE:FF"


async def main() -> None:
    ring = await sdk.connect_ring(address=ADDRESS)
    try:
        info = await sdk.get_system_info(ring)
        print(info.model, info.firmware_version, info.battery_percent)
    finally:
        await ring.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
```

`ring` is a connected `OpenZiloClient`. High-level device functions take it as the first argument, for example `sdk.get_system_info(ring)`.

## Run the example

Save the code above as `connect.py`, replace the device address, then run:

```bash
uv run python connect.py
```

The script prints the model, firmware and battery level, then disconnects. Next, [discover device features](compatibility.en.md) or choose a feature guide from the home page.

# SPDX-License-Identifier: MPL-2.0
"""Display ring candidates immediately without choosing a connection target."""
import asyncio
import openzilo as sdk


def changed(devices):
    for device in devices:
        print(device.name or "Ring (name pending)", device.address,
              device.rssi, device.matched_service)


async def main():
    devices = await sdk.scan_rings(on_devices_changed=changed)
    print(f"Final candidate count: {len(devices)}")


if __name__ == "__main__":
    asyncio.run(main())

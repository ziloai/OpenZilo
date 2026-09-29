# SPDX-License-Identifier: MPL-2.0
"""Scan for compatible OpenZilo devices."""

import asyncio

import openzilo as sdk


async def main() -> None:
    for device in await sdk.scan_rings(timeout_s=10):
        print(f"{device.address}  name={device.name!r}  rssi={device.rssi}")


if __name__ == "__main__":
    asyncio.run(main())

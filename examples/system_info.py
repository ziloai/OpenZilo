# SPDX-License-Identifier: MPL-2.0
"""Print system information from one ring."""

import asyncio

import openzilo as sdk


ADDRESS = "AA:BB:CC:DD:EE:FF"


async def main() -> None:
    async with sdk.OpenZiloClient(address=ADDRESS) as ring:
        print(await sdk.get_system_info(ring))


if __name__ == "__main__":
    asyncio.run(main())

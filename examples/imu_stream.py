# SPDX-License-Identifier: MPL-2.0
"""Print IMU batches after the ring has entered gesture mode."""

import asyncio

import openzilo as sdk


ADDRESS = "AA:BB:CC:DD:EE:FF"


async def main() -> None:
    async with sdk.OpenZiloClient(address=ADDRESS) as ring:
        print("Switch the ring to gesture mode, then starting IMU reports.")
        print(await sdk.start_sensor_report(ring))
        try:
            while True:
                print(await sdk.wait_sensor_data(ring, timeout_s=30))
        finally:
            await sdk.stop_sensor_report(ring)


if __name__ == "__main__":
    asyncio.run(main())

# SPDX-License-Identifier: MPL-2.0
"""Update application firmware using an official, device-compatible package."""
import argparse
import asyncio
from pathlib import Path

import openzilo as sdk


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--public-key", type=Path, required=True, help="Independently trusted signing public key.")
    parser.add_argument("firmware", type=Path)
    args = parser.parse_args()
    data = args.firmware.read_bytes()
    public_key = args.public_key.read_bytes()
    sdk.inspect_firmware_bundle(data, trusted_public_key=public_key)
    # Stop recording and IMU streaming first; use this connection exclusively.
    async with sdk.OpenZiloClient(address=args.address) as ring:
        info = await sdk.update_firmware(
            ring, data, trusted_public_key=public_key, progress=sdk.ProgressPrinter(prefix="OTA transfer"),
        )
        print(f"Verified after reboot: {info.firmware_version}")


if __name__ == "__main__":
    asyncio.run(main())

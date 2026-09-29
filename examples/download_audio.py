# SPDX-License-Identifier: MPL-2.0
"""Download a recording and save its raw and playable forms."""

import asyncio

import openzilo as sdk


ADDRESS = "AA:BB:CC:DD:EE:FF"
FILE_INDEX = 0


async def main() -> None:
    async with sdk.OpenZiloClient(address=ADDRESS) as ring:
        info, data = await sdk.download_audio_file(ring, FILE_INDEX)
    bundle = sdk.save_audio_bundle(
        file_index=FILE_INDEX,
        data=data,
        metadata={"record_time": info.record_time},
        output_dir="audio",
    )
    print(f"raw: {bundle.raw_path}")
    print(f"playable: {bundle.play_path}")


if __name__ == "__main__":
    asyncio.run(main())

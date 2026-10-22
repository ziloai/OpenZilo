# SPDX-License-Identifier: MPL-2.0
"""Read explicit software-corrected physical units using a matching local profile.

First run `openzilo imu-calibrate accel --address YOUR_DEVICE` (or full/quick).
Then run this example with `--address YOUR_DEVICE`. No device writes occur.
"""
import argparse
import asyncio
import openzilo as sdk


async def main(address: str, batches: int) -> None:
    async with sdk.OpenZiloClient(address=address) as ring:
        async with sdk.open_calibrated_imu_stream(ring) as stream:
            for _ in range(batches):
                batch = await anext(stream)
                print('Applied:', batch.applied_components)
                for sample in batch.samples:
                    print(sample.timestamp_ms, 'accel(g):', sample.accel_g, 'gyro(deg/s):', sample.gyro_dps)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', required=True)
    parser.add_argument('--batches', type=int, default=10)
    args = parser.parse_args()
    if args.batches < 1:
        parser.error('--batches must be positive')
    asyncio.run(main(args.address, args.batches))

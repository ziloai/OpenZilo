# SPDX-License-Identifier: MPL-2.0
"""Connect to a local ``openzilo host`` broker and print status + IMU/gesture events."""

from __future__ import annotations

import argparse
import asyncio

from openzilo import ConnectClient


async def main() -> None:
    parser = argparse.ArgumentParser(description="OpenZilo Connect API v2 client demo.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7420)
    parser.add_argument("--socket", default=None, help="Unix socket path (overrides --host/--port).")
    parser.add_argument("--token", default=None, help="Optional host authorization token.")
    parser.add_argument("--seconds", type=float, default=5.0, help="Seconds to stream IMU/gesture events.")
    args = parser.parse_args()

    async with ConnectClient(
        host=args.host,
        port=args.port,
        socket_path=args.socket,
        token=args.token,
        client_name="connect-demo",
    ) as client:
        await client.request_authorization(["info", "sensors"])
        status = await client.ring_status()
        print("status:", status)
        await client.subscribe(["status", "imu", "gesture"])
        imu_cfg = await client.start_imu()
        print("imu started:", imu_cfg)
        try:
            async with asyncio.timeout(args.seconds):
                async for event in client.events:
                    if batch := event.imu_batch():
                        att = batch.attitude
                        print(
                            f"imu seq={batch.sequence_start} n={len(batch.samples)} "
                            f"posture={att.posture.value if att else None}"
                        )
                    elif gesture := event.gesture_event():
                        print("gesture:", gesture)
                    elif snap := event.status_snapshot():
                        print("status update:", snap.phase, snap.battery_percent)
        except TimeoutError:
            pass
        finally:
            await client.stop_imu()


if __name__ == "__main__":
    asyncio.run(main())

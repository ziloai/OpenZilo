# SPDX-License-Identifier: MPL-2.0
"""Remotely capture live audio with a complete Flash backup (extended firmware)."""

import asyncio
from pathlib import Path

import openzilo as sdk

ADDRESS = "AA:BB:CC:DD:EE:FF"


async def main() -> None:
    async with sdk.OpenZiloClient(address=ADDRESS) as ring:
        await sdk.set_audio_recording_config(ring, sdk.AudioRecordingConfig(
            output=sdk.AudioOutput.LIVE_AND_FLASH,
            disconnect_policy=sdk.AudioDisconnectPolicy.CONTINUE_SAVING,
            channels=2, bitrate=32000, max_duration_ms=10000,
        ))
        session = None
        stopper = None

        async def stop_later():
            await asyncio.sleep(5)
            await sdk.stop_audio_recording(ring, session)

        async def subscribed():
            nonlocal session, stopper
            session = await sdk.start_audio_recording(ring)
            stopper = asyncio.create_task(stop_later())

        try:
            recording = await sdk.receive_live_audio_file(ring, on_subscribed=subscribed)
            await stopper
            status = await sdk.wait_audio_recording_finished(ring, session)
            Path("remote.op2c").write_bytes(recording.data)
            print(f"session={session}, saved file={status.file_index}")
        finally:
            if stopper is not None and not stopper.done():
                stopper.cancel()
                await asyncio.gather(stopper, return_exceptions=True)
            if session is not None and ring.is_connected:
                await sdk.stop_audio_recording(ring, session)


if __name__ == "__main__":
    asyncio.run(main())

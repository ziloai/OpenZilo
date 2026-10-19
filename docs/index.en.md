# OpenZilo Python SDK

--8<-- "docs/_includes/devices.en.md"

Connect an OpenZilo ring from Python, read device information, recordings and motion data, and integrate them into your application. Public APIs are provided by the `openzilo` package; the CLI is installed with the SDK.

## Start here

1. [Installation and requirements](sdk-install.en.md): install the SDK and configure Bluetooth and audio dependencies.
2. [Quick start](sdk-quickstart.en.md): run a complete example to connect and read device information.
3. [SDK and firmware compatibility](compatibility.en.md): discover features and check which APIs are available.

To operate a device from a terminal first, use the [CLI guide](cli.en.md).

## Use SDK features

| Your task | Guide |
| --- | --- |
| Scan, connect, disconnect or manage notifications | [Scan and connect](sdk-connection.en.md) |
| Read firmware, model, battery and storage | [Read device information](sdk-device-info.en.md) |
| Respond to device time requests | [Synchronize device time](sdk-time-sync.en.md) |
| Configure, start or stop recording remotely | [Remote recording and configuration](recording-control.md) |
| Download stored recordings or receive newly saved recordings | [Download and receive saved recordings](sdk-downloads.en.md) |
| Receive live Opus or PCM | [Live audio](sdk-live-audio.en.md) |
| Preserve original files and convert to WAV | [Decode and save audio](sdk-audio-decoding.en.md) |
| Collect accelerometer and gyroscope samples | [Collect IMU data](sdk-imu.en.md) |
| Wait for button or tap events | [Button and tap events](sdk-events.en.md) |
| Read device logs in chunks | [Read device logs](sdk-logs.en.md) |
| Update firmware from an application | [Update firmware with the SDK](sdk-ota.en.md) |

Each feature guide explains call order, arguments, results and error handling, with relevant examples.

## Look up APIs and troubleshoot

- [API index](python-sdk.en.md): public functions and signatures grouped by feature.
- [Data types](sdk-data-types.en.md): connection, recording, audio and IMU result fields.
- [Exceptions and troubleshooting](sdk-errors.en.md): connection failures, timeouts, decoding errors and busy devices.
- [Feature requirements](features.en.md) and [version migration](sdk-migration.en.md): feature conditions and upgrade changes.

## Device and protocol

See the [ring user guide](../wiki/Home.md) for physical device operation. For custom clients or communication debugging, read the [protocol reference](protocol.en.md), [architecture and data flow](architecture.en.md), and [protocol debugging utilities](sdk-protocol-tools.en.md).

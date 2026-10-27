# API index

--8<-- "docs/_includes/devices.en.md"

The public API is defined by `openzilo.__all__`. Import it with `import openzilo as sdk`; underscore-prefixed modules are private. Start with the [quick start](sdk-quickstart.en.md); returned fields are listed in [data types](sdk-data-types.en.md).

## Find APIs by task

| Task | Common APIs | Purpose |
| --- | --- | --- |
| Connection | `scan_rings()`, `connect_ring()`, `OpenZiloClient` | Scan, connect, send requests, and await events. |
| Device information | `get_system_info()`, `parse_system_info()` | Firmware, time, storage, battery, serial number, CPUID and model. |
| Feature discovery | `get_device_capabilities()`, `DeviceCapabilities.supports()` | Check supported features, interface versions and parameter limits. |
| Remote recording | `start_audio_recording()`, `stop_audio_recording()`, `set_audio_recording_config()` | Start, stop and configure recordings. |
| Time synchronization | `enable_time_sync()`, `send_time_response()` | Reply automatically or manually to device `0x0401` with `0x0402`. |
| IMU and events | `start_sensor_report()`, `wait_sensor_data()`, `wait_sensor_double_tap_event()` | Receive IMU batches, taps and button events. |
| Logs | `get_log_storage()`, `read_log_chunk()` | Inspect log storage and read chunks by offset. |
| Recording transfers | `receive_auto_audio_file()`, `receive_live_audio_file()`, `download_audio_file()` | Receive completed or live recordings, or download a stored file. |
| Decode and save | `save_audio_bundle()`, `decode_audio_to_wav()` | Preserve raw audio and create WAV. |
| Protocol utilities | `encode_packet()`, `decode_packet()`, `PacketStream` | Inspect packets, CRC and binary fields. |

## Connection and system

| Function | Signature | Returns | Usage |
| --- | --- | --- | --- |
| [`scan_rings()`](sdk-connection.en.md) | `await scan_rings(address=None, timeout_s=25.0)` | `list[BleDeviceInfo]` | Scan BLE devices, optionally filtering by address. |
| [`connect_ring()`](sdk-connection.en.md) | `await connect_ring(address=..., command_timeout_s=10.0, auto_time_sync=False)` | `OpenZiloClient` | Create and connect a client; the caller must disconnect it. |
| [`get_system_info()`](sdk-device-info.en.md) | `await get_system_info(client, timeout_s=None)` | `SystemInfo` | Read device information. |
| [`parse_system_info()`](sdk-device-info.en.md) | `parse_system_info(body)` | `SystemInfo` | Parse a `0x0102` body, normally for tests or protocol debugging. |
| [`enable_time_sync()`](sdk-time-sync.en.md) | `enable_time_sync(client)` | `None` | Register an automatic responder for `0x0401`. |
| [`send_time_response()`](sdk-time-sync.en.md) | `await send_time_response(client, request_time, response_time=None, send_time=None)` | `None` | Send a manual `0x0402` time response. |
| [`get_log_storage()`](sdk-logs.en.md) | `await get_log_storage(client, timeout_s=None)` | `LogStorageInfo` | Read log storage information. |
| [`read_log_chunk()`](sdk-logs.en.md) | `await read_log_chunk(client, index, offset, size, timeout_s=None)` | `bytes` | Read log bytes by index, offset and length. |

## Feature discovery

| API | Returns | Description |
| --- | --- | --- |
| [`await get_device_capabilities(client, timeout_s=None, refresh=False)`](compatibility.en.md) | `DeviceCapabilities` | Query supported features and recording parameter ranges. |
| [`capabilities.supports(name, major=None, min_minor=0)`](compatibility.en.md) | `bool` | Check a feature and its interface version. |
| [`get_sdk_identity()`](compatibility.en.md) | `SdkIdentity` | Return the SDK version and environment identifier for environment records. |

Feature discovery results are cleared on disconnect. See [compatibility](compatibility.en.md) for fields.

## Remote recording

| API | Purpose |
| --- | --- |
| [`get_audio_recording_config()` / `set_audio_recording_config()`](recording-control.md) | Requires firmware `V2.001.0002.0001` or later. Read or change recording configuration. |
| [`start_audio_recording()`](recording-control.md) | Requires firmware `V2.001.0002.0001` or later. Start recording and return its session ID. |
| [`stop_audio_recording()`](recording-control.md) | Requires firmware `V2.001.0002.0001` or later. Stop early or cancel the specified recording. |
| [`get_audio_recording_status()`](recording-control.md) | Requires firmware `V2.001.0002.0001` or later. Query recording state and the saved file. |
| [`wait_audio_recording_finished()`](recording-control.md) | Requires firmware `V2.001.0002.0001` or later. Wait for recording and saving to finish. |

These APIs are asynchronous. Arguments, results and complete examples are in [recording control](recording-control.md).

## Firmware updates

| Function | Call | Returns | Description |
| --- | --- | --- | --- |
| [`inspect_firmware_bundle()`](sdk-ota.en.md) | `inspect_firmware_bundle(bundle, trusted_public_key=...)` | `FirmwareBundle` | Verify a signed ZIP and inspect metadata offline. |
| [`update_firmware()`](sdk-ota.en.md) | `await update_firmware(client, firmware, trusted_public_key=..., allow_test_firmware=False, progress=..., timeout_s=30, total_timeout_s=600, reboot_timeout_s=90)` | `SystemInfo` | Upload an official application package, wait for reboot, and verify the running version. See [firmware updates](#firmware-updates). |

## Recording downloads

| Function | Signature | Returns | Usage |
| --- | --- | --- | --- |
| [`get_audio_file_count()`](sdk-downloads.en.md) | `await get_audio_file_count(client, timeout_s=None)` | `int` | Count recordings stored on the device. |
| [`get_audio_file_info()`](sdk-downloads.en.md) | `await get_audio_file_info(client, file_index, timeout_s=None)` | `AudioFileInfo` | Low-level normal transfer: send `0x0503` and await `0x0504`. |
| [`read_audio_frame()`](sdk-downloads.en.md) | `await read_audio_frame(client, file_index, frame_offset, timeout_s=None)` | `AudioDataFrame` | Low-level normal transfer: send `0x0506` and await `0x0505`. |
| [`end_audio_extract()`](sdk-downloads.en.md) | `await end_audio_extract(client, file_index, timeout_s=None, ignore_timeout=True)` | `None` | Low-level normal transfer: send `0x0507` and await `0x0508`. |
| [`download_audio_file()`](sdk-downloads.en.md) | `await download_audio_file(client, file_index, progress=None, timeout_s=None, quick=True)` | `tuple[AudioFileInfo, bytes]` | Download a complete recording, using fast transfer by default. |
| [`receive_auto_audio_file()`](sdk-downloads.en.md) | `await receive_auto_audio_file(client, timeout_s=None)` | `tuple[int, bytes]` | Download after `0x050A` on firmware `V2.001.0002.0001`, or receive consecutive legacy `0x0505` packets. |
| [`wait_audio_record_result()`](sdk-downloads.en.md) | `await wait_audio_record_result(client, timeout_s=None)` | `AudioRecordResult` | Wait for `0x050A` without downloading. |
| [`set_live_audio_subscription()`](sdk-live-audio.en.md) | `await set_live_audio_subscription(client, enabled, timeout_s=None)` | `LiveAudioSubscription` | Requires firmware `V2.001.0002.0001` or later. Low-level subscription: send `0x050D` and await `0x050E`. |
| [`receive_live_audio_file()`](sdk-live-audio.en.md) | `await receive_live_audio_file(client, on_packet=None, on_subscribed=None, timeout_s=60.0, recording_timeout_s=70.0)` | `LiveAudioRecording` | Requires firmware `V2.001.0002.0001` or later. Subscribe, receive one live recording, and unsubscribe. |
| [`open_live_audio_stream()`](sdk-live-audio.en.md) | `open_live_audio_stream(client, output="pcm", queue_size=64, timeout_s=60.0, recording_timeout_s=70.0)` | `LiveAudioStream` | Requires firmware `V2.001.0002.0001` or later. Manage the subscription with `async with`; read START, audio and END with `async for`. |
| [`clear_audio_files()`](sdk-downloads.en.md) | `await clear_audio_files(client, timeout_s=None)` | `None` | Delete every recording on the device; irreversible. |
| [`parse_audio_file_info()`](sdk-downloads.en.md) | `parse_audio_file_info(body)` | `AudioFileInfo` | Parse a `0x0504` body. |
| [`parse_audio_data_frame()`](sdk-downloads.en.md) | `parse_audio_data_frame(body)` | `AudioDataFrame` | Parse a `0x0505` body. |
| [`parse_audio_record_result()`](sdk-downloads.en.md) | `parse_audio_record_result(body)` | `AudioRecordResult` | Parse a `0x050A` body. |
| [`parse_live_audio_start()`](sdk-live-audio.en.md) | `parse_live_audio_start(body)` | `LiveAudioStart` | Parse a `0x050F` body. |
| [`parse_live_audio_data()`](sdk-live-audio.en.md) | `parse_live_audio_data(body)` | `LiveAudioData` | Parse a `0x0510` body. |
| [`parse_live_audio_end()`](sdk-live-audio.en.md) | `parse_live_audio_end(body)` | `LiveAudioEnd` | Parse a `0x0511` body. |

## Audio decoding and file output

| Function | Signature | Returns | Usage |
| --- | --- | --- | --- |
| [`save_audio_bundle()`](sdk-audio-decoding.en.md) | `save_audio_bundle(file_index, data, metadata=None, output_path=None, output_dir=None, pcm_config=None, ...)` | `AudioBundle` | Preserve raw audio and generate a playable file. |
| [`decode_audio_to_wav()`](sdk-audio-decoding.en.md) | `decode_audio_to_wav(data, pcm_config=None, ...)` | `bytes` | Decode recording bytes to WAV bytes. |
| [`build_playable_audio()`](sdk-audio-decoding.en.md) | `build_playable_audio(data, pcm_config=None, ...)` | `PlayableAudio` | Detect WAV, mono/stereo OP2C or Speex and return playable audio. |
| [`build_wav_from_pcm()`](sdk-audio-decoding.en.md) | `build_wav_from_pcm(pcm_bytes, pcm_config=None)` | `bytes` | Wrap PCM in a WAV header. |
| [`decode_speex_to_pcm()`](sdk-audio-decoding.en.md) | `decode_speex_to_pcm(data, pcm_config=None, ...)` | `SpeexDecodeResult` | Decode Speex to PCM. |
| [`decode_opus_to_pcm()`](sdk-audio-decoding.en.md) | `decode_opus_to_pcm(data, ffmpeg_path="ffmpeg")` | `OpusDecodeResult` | Decode OP2C to PCM using its header channel count. |
| [`parse_opus_recording()`](sdk-audio-decoding.en.md) | `parse_opus_recording(data)` | `list[bytes]` | Validate OP2C and extract Opus packets. |
| [`build_opus_recording()`](sdk-audio-decoding.en.md) | `build_opus_recording(packets)` | `bytes` | Package Opus packets as an OP2C file. |
| [`decode_ogg_speex_with_ffmpeg()`](sdk-audio-decoding.en.md) | `decode_ogg_speex_with_ffmpeg(ogg_bytes, pcm_config=None, ffmpeg_path="ffmpeg")` | `bytes` | Decode Ogg Speex to PCM with ffmpeg. |
| [`parse_packetized_speex_stream()`](sdk-audio-decoding.en.md) | `parse_packetized_speex_stream(data, allow_framed_blocks=True)` | `list[bytes]` | Parse length-prefixed Speex packets. |
| [`split_raw_speex_packets()`](sdk-audio-decoding.en.md) | `split_raw_speex_packets(data, quality=3, bits_size=None)` | `list[bytes]` | Split raw data by Speex frame size. |
| [`build_ogg_speex()`](sdk-audio-decoding.en.md) | `build_ogg_speex(packets, pcm_config=None)` | `bytes` | Wrap Speex packets in Ogg Speex. |
| [`normalize_decoded_speex_pcm()`](sdk-audio-decoding.en.md) | `normalize_decoded_speex_pcm(pcm, packet_count, pcm_config=None)` | `bytes` | Normalize decoded PCM length. |
| [`normalize_pcm_config()`](sdk-audio-decoding.en.md) | `normalize_pcm_config(config=None)` | `PcmConfig` | Normalize a PCM configuration input. |
| [`format_pcm_config()`](sdk-audio-decoding.en.md) | `format_pcm_config(config=None)` | `str` | Format PCM parameters as text. |
| [`build_audio_bundle_paths()`](sdk-audio-decoding.en.md) | `build_audio_bundle_paths(file_index, metadata=None, output_path=None, output_dir=None)` | `tuple[Path, Path]` | Build paths for raw and playable files. |
| [`build_base_name()`](sdk-audio-decoding.en.md) | `build_base_name(file_index, metadata=None)` | `str` | Build a recording base filename. |
| [`is_wav()`](sdk-audio-decoding.en.md) | `is_wav(data)` | `bool` | Check for WAV data. |
| [`is_ogg_speex()`](sdk-audio-decoding.en.md) | `is_ogg_speex(data)` | `bool` | Check for Ogg Speex data. |
| [`pick_speex_mode()`](sdk-audio-decoding.en.md) | `pick_speex_mode(sample_rate)` | `int` | Select the Speex mode for a sample rate. |
| [`pick_frame_size()`](sdk-audio-decoding.en.md) | `pick_frame_size(sample_rate)` | `int` | Select PCM samples per frame for a sample rate. |
| [`pick_bits_size()`](sdk-audio-decoding.en.md) | `pick_bits_size(quality)` | `int` | Estimate Speex frame bytes from quality. |

## IMU and events

| Function | Signature | Returns | Usage |
| --- | --- | --- | --- |
| [`start_sensor_report()`](sdk-imu.en.md) | `await start_sensor_report(client, timeout_s=None)` | `SensorStartInfo` | `V2.001.0002.0001` starts capture directly; `V2.001.0002.0000` requires gesture mode first. |
| [`wait_sensor_data()`](sdk-imu.en.md) | `await wait_sensor_data(client, timeout_s=None)` | `SensorDataBatch` | After starting reports, wait for a single-sample or batch `0x0605`; does not automatically send `0x0601`. |
| [`stop_sensor_report()`](sdk-imu.en.md) | `await stop_sensor_report(client, timeout_s=None)` | `SensorStopInfo` | `V2.001.0002.0001` stops capture; `V2.001.0002.0000` can retain local capture in gesture mode. |
| [`open_calibrated_imu_stream()`](sdk-imu.en.md) | `async with open_calibrated_imu_stream(client, profile=None, device_id=None)` | `CalibratedImuStream` | Explicit host correction in g / deg/s, with profile binding and report cleanup; no calibration writes. |
| [`apply_imu_calibration()`](sdk-imu.en.md) | `apply_imu_calibration(batch, config, calibration, accel=True, gyro=True)` | `CalibratedImuBatch` | Offline conversion of original integer batches; input remains untouched. |
| [`load_imu_calibration_profile()`](sdk-imu.en.md) | `load_imu_calibration_profile(path)` | `ImuCalibrationProfile` | Validate local schema, units and parameters. |
| [`save_imu_calibration_profile()`](sdk-imu.en.md) | `save_imu_calibration_profile(profile, path)` | `None` | Atomically save locally after independent validation. |
| [`parse_sensor_data_batch()`](sdk-imu.en.md) | `parse_sensor_data_batch(body)` | `SensorDataBatch` | Parse a `0x0605` body. |
| [`wait_sensor_double_tap_event()`](sdk-events.en.md) | `await wait_sensor_double_tap_event(client, timeout_s=None)` | `SensorDoubleTapEvent` | Wait for a physical double-tap event (`0x0701`). |
| [`wait_sensor_key_double_press_event()`](sdk-events.en.md) | `await wait_sensor_key_double_press_event(client, timeout_s=None)` | `SensorKeyDoublePressEvent` | Wait for a double button press (`0x0703`). |
| [`wait_sensor_key_single_press_event()`](sdk-events.en.md) | `await wait_sensor_key_single_press_event(client, timeout_s=None)` | `SensorKeySinglePressEvent` | Wait for a single button press (`0x0704`). |
| [`parse_sensor_double_tap_event()`](sdk-events.en.md) | `parse_sensor_double_tap_event(body)` | `SensorDoubleTapEvent` | Parse a `0x0701` body. |
| [`parse_sensor_key_double_press_event()`](sdk-events.en.md) | `parse_sensor_key_double_press_event(body)` | `SensorKeyDoublePressEvent` | Parse a `0x0703` body. |
| [`parse_sensor_key_single_press_event()`](sdk-events.en.md) | `parse_sensor_key_single_press_event(body)` | `SensorKeySinglePressEvent` | Strictly parse the four-byte `0x0704` timestamp. |

## Protocol utilities

| Function | Signature | Returns | Usage |
| --- | --- | --- | --- |
| [`encode_packet()`](sdk-protocol-tools.en.md) | `encode_packet(command, body=b"")` | `bytes` | Build a complete packet including header and CRC. |
| [`decode_packet()`](sdk-protocol-tools.en.md) | `decode_packet(data)` | `Packet` | Parse a complete protocol packet. |
| [`crc16_compute()`](sdk-protocol-tools.en.md) | `crc16_compute(data, initial=0xFFFF)` | `int` | Calculate the protocol CRC16. |

# API 索引

--8<-- "docs/_includes/devices.zh-CN.md"

公开接口以 `openzilo.__all__` 为准，统一从 `import openzilo as sdk` 导入；下划线开头的子模块属于内部实现。首次使用从[快速开始](sdk-quickstart.zh-CN.md)进入，返回字段见[数据类型](sdk-data-types.zh-CN.md)。

## 按功能查找接口

| 功能 | 常用名称 | 说明 |
| --- | --- | --- |
| 连接设备 | `scan_rings()`、`connect_ring()`、`OpenZiloClient` | 扫描、连接、发送请求、等待设备上报 |
| 系统信息 | `get_system_info()`、`parse_system_info()` | 获取固件版本、时间、存储、电量、SN、CPUID、型号 |
| 功能查询 | `get_device_capabilities()`、`DeviceCapabilities.supports()` | 查询可用功能，检查接口版本与参数范围 |
| 远程录音 | `start_audio_recording()`、`stop_audio_recording()`、`set_audio_recording_config()` | 开始、停止录音及修改设置 |
| 校时服务 | `enable_time_sync()`、`send_time_response()` | 设备发出 `0x0401` 时自动或手动回复 `0x0402` |
| 六轴和事件 | `start_sensor_report()`、`wait_sensor_data()`、`wait_sensor_double_tap_event()` | 接收批量 IMU 数据、敲击和按键事件 |
| 日志 | `get_log_storage()`、`read_log_chunk()` | 获取日志空间信息并按偏移读取日志 |
| 录音接收与下载 | `receive_auto_audio_file()`、`receive_live_audio_file()`、`download_audio_file()` | 接收刚保存或实时发送的录音，或查询并下载指定录音 |
| 录音解码保存 | `save_audio_bundle()`、`decode_audio_to_wav()` | 保存原始录音并生成 WAV |
| 协议工具 | `encode_packet()`、`decode_packet()`、`PacketStream` | 调试协议包、CRC、二进制读写 |

## 连接和系统

| 函数 | 签名 | 返回值 | 使用方式 |
| --- | --- | --- | --- |
| [`scan_rings()`](sdk-connection.zh-CN.md) | `await scan_rings(address=None, timeout_s=25.0)` | `list[BleDeviceInfo]` | 扫描 BLE 设备，可按 MAC 地址过滤。 |
| [`connect_ring()`](sdk-connection.zh-CN.md) | `await connect_ring(address=..., command_timeout_s=10.0, auto_time_sync=False)` | `OpenZiloClient` | 创建并连接客户端，调用方负责 `disconnect()`。 |
| [`get_system_info()`](sdk-device-info.zh-CN.md) | `await get_system_info(client, timeout_s=None)` | `SystemInfo` | 读取设备系统信息。 |
| [`parse_system_info()`](sdk-device-info.zh-CN.md) | `parse_system_info(body)` | `SystemInfo` | 解析 `0x0102` 包体，通常只用于测试或协议调试。 |
| [`enable_time_sync()`](sdk-time-sync.zh-CN.md) | `enable_time_sync(client)` | `None` | 注册 `0x0401` 自动应答处理器。 |
| [`send_time_response()`](sdk-time-sync.zh-CN.md) | `await send_time_response(client, request_time, response_time=None, send_time=None)` | `None` | 手动发送 `0x0402` 校时应答。 |
| [`get_log_storage()`](sdk-logs.zh-CN.md) | `await get_log_storage(client, timeout_s=None)` | `LogStorageInfo` | 查询日志存储信息。 |
| [`read_log_chunk()`](sdk-logs.zh-CN.md) | `await read_log_chunk(client, index, offset, size, timeout_s=None)` | `bytes` | 按日志索引、偏移、长度读取日志。 |

## 功能查询

| 接口 | 返回值 | 说明 |
| --- | --- | --- |
| [`await get_device_capabilities(client, timeout_s=None, refresh=False)`](compatibility.zh-CN.md) | `DeviceCapabilities` | 查询设备支持的功能及录音参数范围。 |
| [`capabilities.supports(name, major=None, min_minor=0)`](compatibility.zh-CN.md) | `bool` | 检查指定功能及其接口版本。 |
| [`get_sdk_identity()`](compatibility.zh-CN.md) | `SdkIdentity` | 返回 SDK 版本和源码校验值，便于记录运行环境。 |

功能查询结果会在断开连接后清除。字段说明见[兼容说明](compatibility.zh-CN.md)。

## 远程录音

| 接口 | 用途 |
| --- | --- |
| [`get_audio_recording_config()` / `set_audio_recording_config()`](recording-control.zh-CN.md) | 需固件 `V2.001.0002.0001` 或更新版本。 读取、修改录音设置。 |
| [`start_audio_recording()`](recording-control.zh-CN.md) | 需固件 `V2.001.0002.0001` 或更新版本。 开始录音，返回本次录音编号。 |
| [`stop_audio_recording()`](recording-control.zh-CN.md) | 需固件 `V2.001.0002.0001` 或更新版本。 提前结束或取消指定录音。 |
| [`get_audio_recording_status()`](recording-control.zh-CN.md) | 需固件 `V2.001.0002.0001` 或更新版本。 查询录音状态和已保存文件。 |
| [`wait_audio_recording_finished()`](recording-control.zh-CN.md) | 需固件 `V2.001.0002.0001` 或更新版本。 等待录音结束和保存完成。 |

以上接口均为异步调用。参数、返回结果及完整示例见[远程录音与录音设置](recording-control.zh-CN.md)。

## 固件升级

| 函数 | 调用方式 | 返回 | 说明 |
| --- | --- | --- | --- |
| [`inspect_firmware_bundle()`](sdk-ota.zh-CN.md) | `inspect_firmware_bundle(bundle, trusted_public_key=...)` | `FirmwareBundle` | 离线验证签名 ZIP 并读取元数据，无需连接设备。 |
| [`update_firmware()`](sdk-ota.zh-CN.md) | `await update_firmware(client, firmware, trusted_public_key=..., allow_test_firmware=False, progress=..., timeout_s=30, total_timeout_s=600, reboot_timeout_s=90)` | `SystemInfo` | 上传已验证的应用固件，等待重启并核对运行版本，见[固件升级](#固件升级)。 |

## 录音下载

| 函数 | 签名 | 返回值 | 使用方式 |
| --- | --- | --- | --- |
| [`get_audio_file_count()`](sdk-downloads.zh-CN.md) | `await get_audio_file_count(client, timeout_s=None)` | `int` | 查询设备中保存的录音数量。 |
| [`get_audio_file_info()`](sdk-downloads.zh-CN.md) | `await get_audio_file_info(client, file_index, timeout_s=None)` | `AudioFileInfo` | 普通链路低层接口，发送 `0x0503` 并等待 `0x0504`。 |
| [`read_audio_frame()`](sdk-downloads.zh-CN.md) | `await read_audio_frame(client, file_index, frame_offset, timeout_s=None)` | `AudioDataFrame` | 普通链路低层接口，发送 `0x0506` 并等待 `0x0505`。 |
| [`end_audio_extract()`](sdk-downloads.zh-CN.md) | `await end_audio_extract(client, file_index, timeout_s=None, ignore_timeout=True)` | `None` | 普通链路低层接口，发送 `0x0507` 并等待 `0x0508`。 |
| [`download_audio_file()`](sdk-downloads.zh-CN.md) | `await download_audio_file(client, file_index, progress=None, timeout_s=None, quick=True)` | `tuple[AudioFileInfo, bytes]` | 完整下载录音；默认 quick 链路。 |
| [`receive_auto_audio_file()`](sdk-downloads.zh-CN.md) | `await receive_auto_audio_file(client, timeout_s=None)` | `tuple[int, bytes]` | `V2.001.0002.0001` 收到 `0x050A` 后下载；`V2.001.0002.0000` 接收连续 `0x0505`。 |
| [`wait_audio_record_result()`](sdk-downloads.zh-CN.md) | `await wait_audio_record_result(client, timeout_s=None)` | `AudioRecordResult` | 需固件 `V2.001.0002.0001` 或更新版本；只等待 `0x050A`，不下载。 |
| [`set_live_audio_subscription()`](sdk-live-audio.zh-CN.md) | `await set_live_audio_subscription(client, enabled, timeout_s=None)` | `LiveAudioSubscription` | 需固件 `V2.001.0002.0001` 或更新版本。 低层接口，发送 `0x050D` 并等待 `0x050E`。 |
| [`receive_live_audio_file()`](sdk-live-audio.zh-CN.md) | `await receive_live_audio_file(client, on_packet=None, on_subscribed=None, timeout_s=60.0, recording_timeout_s=70.0)` | `LiveAudioRecording` | 需固件 `V2.001.0002.0001` 或更新版本。 订阅并接收一段实时录音，结束后退订。 |
| [`open_live_audio_stream()`](sdk-live-audio.zh-CN.md) | `open_live_audio_stream(client, output="pcm", queue_size=64, timeout_s=60.0, recording_timeout_s=70.0)` | `LiveAudioStream` | 需固件 `V2.001.0002.0001` 或更新版本。 `async with` 管理订阅，`async for` 读取录音开始、音频帧和录音结束事件。 |
| [`clear_audio_files()`](sdk-downloads.zh-CN.md) | `await clear_audio_files(client, timeout_s=None)` | `None` | 删除设备内所有录音，属于破坏性操作。 |
| [`parse_audio_file_info()`](sdk-downloads.zh-CN.md) | `parse_audio_file_info(body)` | `AudioFileInfo` | 解析 `0x0504` 包体。 |
| [`parse_audio_data_frame()`](sdk-downloads.zh-CN.md) | `parse_audio_data_frame(body)` | `AudioDataFrame` | 解析 `0x0505` 包体。 |
| [`parse_audio_record_result()`](sdk-downloads.zh-CN.md) | `parse_audio_record_result(body)` | `AudioRecordResult` | 解析 `0x050A` 包体。 |
| [`parse_live_audio_start()`](sdk-live-audio.zh-CN.md) | `parse_live_audio_start(body)` | `LiveAudioStart` | 解析 `0x050F` 包体。 |
| [`parse_live_audio_data()`](sdk-live-audio.zh-CN.md) | `parse_live_audio_data(body)` | `LiveAudioData` | 解析 `0x0510` 包体。 |
| [`parse_live_audio_end()`](sdk-live-audio.zh-CN.md) | `parse_live_audio_end(body)` | `LiveAudioEnd` | 解析 `0x0511` 包体。 |

## 录音解码和文件保存

| 函数 | 签名 | 返回值 | 使用方式 |
| --- | --- | --- | --- |
| [`save_audio_bundle()`](sdk-audio-decoding.zh-CN.md) | `save_audio_bundle(file_index, data, metadata=None, output_path=None, output_dir=None, pcm_config=None, ...)` | `AudioBundle` | 保存原始录音并生成可播放文件。 |
| [`decode_audio_to_wav()`](sdk-audio-decoding.zh-CN.md) | `decode_audio_to_wav(data, pcm_config=None, ...)` | `bytes` | 把录音字节解码成 WAV 字节。 |
| [`build_playable_audio()`](sdk-audio-decoding.zh-CN.md) | `build_playable_audio(data, pcm_config=None, ...)` | `PlayableAudio` | 自动识别 WAV、OP2C 单声道或双声道 Opus 或 Speex，返回可播放音频对象。 |
| [`build_wav_from_pcm()`](sdk-audio-decoding.zh-CN.md) | `build_wav_from_pcm(pcm_bytes, pcm_config=None)` | `bytes` | 给 PCM 数据封装 WAV 头。 |
| [`decode_speex_to_pcm()`](sdk-audio-decoding.zh-CN.md) | `decode_speex_to_pcm(data, pcm_config=None, ...)` | `SpeexDecodeResult` | 把 Speex 数据解码成 PCM。 |
| [`decode_opus_to_pcm()`](sdk-audio-decoding.zh-CN.md) | `decode_opus_to_pcm(data, ffmpeg_path="ffmpeg")` | `OpusDecodeResult` | 按 OP2C 文件头中的声道数解码成 PCM。 |
| [`parse_opus_recording()`](sdk-audio-decoding.zh-CN.md) | `parse_opus_recording(data)` | `list[bytes]` | 校验 OP2C 文件并取出 Opus 包。 |
| [`build_opus_recording()`](sdk-audio-decoding.zh-CN.md) | `build_opus_recording(packets)` | `bytes` | 把 Opus 包封装成 OP2C 文件。 |
| [`decode_ogg_speex_with_ffmpeg()`](sdk-audio-decoding.zh-CN.md) | `decode_ogg_speex_with_ffmpeg(ogg_bytes, pcm_config=None, ffmpeg_path="ffmpeg")` | `bytes` | 用 ffmpeg 解码 Ogg Speex 为 PCM。 |
| [`parse_packetized_speex_stream()`](sdk-audio-decoding.zh-CN.md) | `parse_packetized_speex_stream(data, allow_framed_blocks=True)` | `list[bytes]` | 解析带长度字段的 Speex 包流。 |
| [`split_raw_speex_packets()`](sdk-audio-decoding.zh-CN.md) | `split_raw_speex_packets(data, quality=3, bits_size=None)` | `list[bytes]` | 按 Speex 帧大小切分原始数据。 |
| [`build_ogg_speex()`](sdk-audio-decoding.zh-CN.md) | `build_ogg_speex(packets, pcm_config=None)` | `bytes` | 把 Speex 包封装成 Ogg Speex。 |
| [`normalize_decoded_speex_pcm()`](sdk-audio-decoding.zh-CN.md) | `normalize_decoded_speex_pcm(pcm, packet_count, pcm_config=None)` | `bytes` | 规范解码后 PCM 长度。 |
| [`normalize_pcm_config()`](sdk-audio-decoding.zh-CN.md) | `normalize_pcm_config(config=None)` | `PcmConfig` | 规范 PCM 配置输入。 |
| [`format_pcm_config()`](sdk-audio-decoding.zh-CN.md) | `format_pcm_config(config=None)` | `str` | 格式化 PCM 配置说明。 |
| [`build_audio_bundle_paths()`](sdk-audio-decoding.zh-CN.md) | `build_audio_bundle_paths(file_index, metadata=None, output_path=None, output_dir=None)` | `tuple[Path, Path]` | 生成原始文件和播放文件路径。 |
| [`build_base_name()`](sdk-audio-decoding.zh-CN.md) | `build_base_name(file_index, metadata=None)` | `str` | 生成录音文件基础名称。 |
| [`is_wav()`](sdk-audio-decoding.zh-CN.md) | `is_wav(data)` | `bool` | 判断是否为 WAV。 |
| [`is_ogg_speex()`](sdk-audio-decoding.zh-CN.md) | `is_ogg_speex(data)` | `bool` | 判断是否为 Ogg Speex。 |
| [`pick_speex_mode()`](sdk-audio-decoding.zh-CN.md) | `pick_speex_mode(sample_rate)` | `int` | 根据采样率选择 Speex 模式。 |
| [`pick_frame_size()`](sdk-audio-decoding.zh-CN.md) | `pick_frame_size(sample_rate)` | `int` | 根据采样率选择 PCM 帧采样数。 |
| [`pick_bits_size()`](sdk-audio-decoding.zh-CN.md) | `pick_bits_size(quality)` | `int` | 根据质量参数估算 Speex 帧字节数。 |

## 六轴和事件

| 函数 | 签名 | 返回值 | 使用方式 |
| --- | --- | --- | --- |
| [`start_sensor_report()`](sdk-imu.zh-CN.md) | `await start_sensor_report(client, timeout_s=None)` | `SensorStartInfo` | `V2.001.0002.0001` 直接启动采集；`V2.001.0002.0000` 需先进入手势模式。 |
| [`wait_sensor_data()`](sdk-imu.zh-CN.md) | `await wait_sensor_data(client, timeout_s=None)` | `SensorDataBatch` | 在 `start_sensor_report()` 成功后等待一个 `0x0605` 单点或批量包；不会自动发送 `0x0601`。 |
| [`stop_sensor_report()`](sdk-imu.zh-CN.md) | `await stop_sensor_report(client, timeout_s=None)` | `SensorStopInfo` | `V2.001.0002.0001` 停止采集；`V2.001.0002.0000` 在手势模式下可保留本地采集。 |
| [`open_calibrated_imu_stream()`](sdk-imu.zh-CN.md) | `async with open_calibrated_imu_stream(client, profile=None, device_id=None)` | `CalibratedImuStream` | 匹配本机配置后显式输出 g 和度/秒，管理上报和清理，不下发校准参数。 |
| [`apply_imu_calibration()`](sdk-imu.zh-CN.md) | `apply_imu_calibration(batch, config, calibration, accel=True, gyro=True)` | `CalibratedImuBatch` | 离线转换原始整数批次，不修改输入。 |
| [`load_imu_calibration_profile()`](sdk-imu.zh-CN.md) | `load_imu_calibration_profile(path)` | `ImuCalibrationProfile` | 校验本机配置的结构版本、单位和参数。 |
| [`save_imu_calibration_profile()`](sdk-imu.zh-CN.md) | `save_imu_calibration_profile(profile, path)` | `None` | 独立验证后原子保存本机配置。 |
| [`parse_sensor_data_batch()`](sdk-imu.zh-CN.md) | `parse_sensor_data_batch(body)` | `SensorDataBatch` | 解析 `0x0605` 包体。 |
| [`wait_sensor_double_tap_event()`](sdk-events.zh-CN.md) | `await wait_sensor_double_tap_event(client, timeout_s=None)` | `SensorDoubleTapEvent` | 等待 `0x0701` 普通双击事件。 |
| [`wait_sensor_key_double_press_event()`](sdk-events.zh-CN.md) | `await wait_sensor_key_double_press_event(client, timeout_s=None)` | `SensorKeyDoublePressEvent` | 等待 `0x0703` 按键双击事件。 |
| [`wait_sensor_key_single_press_event()`](sdk-events.zh-CN.md) | `await wait_sensor_key_single_press_event(client, timeout_s=None)` | `SensorKeySinglePressEvent` | 等待 `0x0704` 按键单击事件。 |
| [`parse_sensor_double_tap_event()`](sdk-events.zh-CN.md) | `parse_sensor_double_tap_event(body)` | `SensorDoubleTapEvent` | 解析 `0x0701` 包体。 |
| [`parse_sensor_key_double_press_event()`](sdk-events.zh-CN.md) | `parse_sensor_key_double_press_event(body)` | `SensorKeyDoublePressEvent` | 解析 `0x0703` 包体。 |
| [`parse_sensor_key_single_press_event()`](sdk-events.zh-CN.md) | `parse_sensor_key_single_press_event(body)` | `SensorKeySinglePressEvent` | 严格解析 `0x0704` 的 4 字节时间戳包体。 |

## 协议工具

| 函数 | 签名 | 返回值 | 使用方式 |
| --- | --- | --- | --- |
| [`encode_packet()`](sdk-protocol-tools.zh-CN.md) | `encode_packet(command, body=b"")` | `bytes` | 构造带协议头和 CRC 的完整包。 |
| [`decode_packet()`](sdk-protocol-tools.zh-CN.md) | `decode_packet(data)` | `Packet` | 解析完整协议包。 |
| [`crc16_compute()`](sdk-protocol-tools.zh-CN.md) | `crc16_compute(data, initial=0xFFFF)` | `int` | 计算协议 CRC16。 |

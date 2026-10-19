# 音频解码与文件保存

--8<-- "docs/_includes/devices.zh-CN.md"

识别 Speex 或 Opus 录音，保存原始文件并转换为可播放音频。这些操作处理本地字节，不需要保持蓝牙连接。实时 PCM 的 PyAV 依赖见[实时音频](sdk-live-audio.zh-CN.md)。

以下代码片段使用 `import openzilo as sdk`；`ring` 表示已连接的客户端，完整连接示例见[快速开始](sdk-quickstart.zh-CN.md)。

## 音频解码

录音 `.bin` 是`V2.001.0002.0000` 的 Speex 帧流，或 `V2.001.0002.0001` 的 OP2C 格式的单声道或双声道 Opus 文件。SDK 会保留原始 `.bin`，按内容识别编码，并借助 `ffmpeg` 解码为 `.wav`；格式说明见[录音文件格式](architecture.zh-CN.md#录音文件格式)。

```python
bundle = sdk.save_audio_bundle(file_index=0, data=raw_audio, output_dir="audio")
print(bundle.raw_path)
print(bundle.play_path)
```

如果缺少 `ffmpeg`，下载录音仍然可行，但解码会抛出 `SpeexDecoderUnavailable` 或 `OpusDecoderUnavailable`。

## `save_audio_bundle()`

作用：保存原始录音，并尝试生成可播放 WAV。

```python
bundle = sdk.save_audio_bundle(
    file_index=0,
    data=raw_audio,
    metadata={"record_time": info.record_time},
    output_dir="audio",
)
print(bundle.raw_path)
print(bundle.play_path)
```

返回：`AudioBundle`

常见异常：缺少 `ffmpeg` 或解码失败时抛出 `SpeexDecoderUnavailable` / `OpusDecoderUnavailable` / `AudioDecodeError`。

## 录音解码辅助函数

- `decode_audio_to_wav()`：返回 WAV 字节，适合自己管理文件保存。
- `build_playable_audio()`：返回 `PlayableAudio`，包含字节、扩展名、MIME、解码说明。
- `decode_speex_to_pcm()`、`decode_opus_to_pcm()`：返回 PCM 解码结果，适合需要进一步处理 PCM 的场景。
- `parse_opus_recording()`、`build_opus_recording()`：OP2C 文件处理工具。
- `build_wav_from_pcm()`：只负责给 PCM 包 WAV 头。
- `decode_ogg_speex_with_ffmpeg()`：底层 ffmpeg 调用。
- `parse_packetized_speex_stream()`、`split_raw_speex_packets()`、`build_ogg_speex()`：Speex 包处理工具。
- `normalize_decoded_speex_pcm()`：修正解码后 PCM 长度。
- `normalize_pcm_config()`、`format_pcm_config()`：统一和展示 PCM 配置。
- `build_audio_bundle_paths()`、`build_base_name()`：生成保存路径和基础文件名。
- `is_wav()`、`is_ogg_speex()`：格式探测。
- `pick_speex_mode()`、`pick_frame_size()`、`pick_bits_size()`：Speex 参数推导。

`parse_packetized_speex_stream()` 这个公开底层函数还支持 1026 字节外层分块输入；高层 `decode_speex_to_pcm()`、`build_playable_audio()`、`decode_audio_to_wav()` 和 `save_audio_bundle()` 默认 `allow_framed_blocks=False`。处理这种兼容输入时，可显式设置 `allow_framed_blocks=True`。

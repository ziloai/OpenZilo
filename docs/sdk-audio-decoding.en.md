# Decode and save audio

--8<-- "docs/_includes/devices.en.md"

Detect Speex or Opus recordings, preserve the original file and convert to playable audio. These functions process local bytes without an active BLE connection. See [live audio](sdk-live-audio.en.md) for the PyAV dependency used by live PCM.

Code snippets use `import openzilo as sdk`; `ring` is a connected client. See the [quick start](sdk-quickstart.en.md) for a complete connection example.

## Audio decoding

A recording `.bin` contains legacy Speex frames or mono/stereo Opus in OP2C format. The SDK preserves it, detects its encoding from the content, and uses `ffmpeg` to produce WAV. See [recording formats](architecture.en.md#recording-formats).

```python
bundle = sdk.save_audio_bundle(file_index=0, data=raw_audio, output_dir="audio")
print(bundle.raw_path)
print(bundle.play_path)
```

Without `ffmpeg`, downloading still works, but decoding raises `SpeexDecoderUnavailable` or `OpusDecoderUnavailable`.

## `save_audio_bundle()`

Purpose: preserve raw recording data and attempt playable WAV output.

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

Returns: `AudioBundle`.

Missing `ffmpeg` or decoding failure raises `SpeexDecoderUnavailable`, `OpusDecoderUnavailable` or `AudioDecodeError`.

## Audio decoding helpers

- `decode_audio_to_wav()`: return WAV bytes for application-managed storage.
- `build_playable_audio()`: return `PlayableAudio` with bytes, extension, MIME and decoding description.
- `decode_speex_to_pcm()`, `decode_opus_to_pcm()`: return decoded PCM for further processing.
- `parse_opus_recording()`, `build_opus_recording()`: read and write OP2C files.
- `build_wav_from_pcm()`: wrap PCM in a WAV header.
- `decode_ogg_speex_with_ffmpeg()`: low-level ffmpeg invocation.
- `parse_packetized_speex_stream()`, `split_raw_speex_packets()`, `build_ogg_speex()`: Speex packet utilities.
- `normalize_decoded_speex_pcm()`: correct decoded PCM length.
- `normalize_pcm_config()`, `format_pcm_config()`: normalize and display PCM configuration.
- `build_audio_bundle_paths()`, `build_base_name()`: generate output paths and base filenames.
- `is_wav()`, `is_ogg_speex()`: detect formats.
- `pick_speex_mode()`, `pick_frame_size()`, `pick_bits_size()`: derive Speex parameters.

Low-level `parse_packetized_speex_stream()` also accepts legacy 1026-byte outer blocks. High-level `decode_speex_to_pcm()`, `build_playable_audio()`, `decode_audio_to_wav()` and `save_audio_bundle()` default to `allow_framed_blocks=False`. Pass `True` explicitly for that legacy input.

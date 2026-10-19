# Buttons and Modes

--8<-- "docs/_includes/devices.en.md"

[English](https://github.com/ziloai/OpenZilo/wiki/Buttons-and-Modes) | [简体中文](https://github.com/ziloai/OpenZilo/wiki/Buttons-and-Modes-zh-CN)

--8<-- "docs/_includes/features.en.md:user-guide-scope"

Firmware `V2.001.0002.0001` removes recording/gesture mode switching. The table describes that version; differences for `V2.001.0002.0000` follow it.

| Action | Behavior in `V2.001.0002.0001` |
| --- | --- |
| Single short press | Report a single-press event without changing modes. |
| Double button press | Report a double-press event without the corresponding single press. |
| Press and hold | Start local recording after about 0.3 seconds; release to finish. |
| Physical double tap | Report a tap when the application has subscribed to IMU and capture is active. |

Firmware `V2.001.0002.0000` starts in recording mode and uses a single press to switch recording/gesture modes. Gesture mode does not start button recording and can retain local IMU tap detection. This procedure does not apply to `V2.001.0002.0001`.

A short press is under about 0.2 seconds. Two presses within roughly 0.5 seconds form a double press, so single-press confirmation has a short delay.

## Recording

--8<-- "docs/_includes/firmware-0001.en.md"

Live audio, remote recording and recording settings are available starting with `V2.001.0002.0001`. Choose device storage, live-only output or both. Live-only output leaves no device copy; select simultaneous saving and the continue-saving policy before recording if a device copy must survive disconnection.

Button recordings in `V2.001.0002.0000` use Speex and can be pushed after saving. Firmware `V2.001.0002.0001` saves Opus (OP2C), notifies with `0x050A`, then allows download. The SDK's `receive_auto_audio_file()` handles both workflows.

Hold the button, speak after the green light appears, then release it. Recording is rejected below 20% reported battery. Local recordings can be saved without BLE. Back up before clearing full storage; downloading does not delete files.

## IMU and Tap Detection

--8<-- "docs/_includes/firmware-0001.en.md"

Firmware `V2.001.0002.0001` needs no mode change. `start_sensor_report()` starts IMU; `stop_sensor_report()` or disconnection stops it. Subscribe again after reconnecting. Tap detection starts and stops with capture.

Firmware `V2.001.0002.0000` requires gesture mode first and can keep local tap detection after BLE reports stop. Physical double taps (`0x0701`) differ from double button presses (`0x0703`).

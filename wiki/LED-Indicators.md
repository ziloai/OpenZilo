# LED Indicators

--8<-- "docs/_includes/devices.en.md"

[English](https://github.com/ziloai/OpenZilo/wiki/LED-Indicators) | [简体中文](https://github.com/ziloai/OpenZilo/wiki/LED-Indicators-zh-CN)

--8<-- "docs/_includes/features.en.md:user-guide-scope"

The same color can mean different things. Use the action you just performed and the blink pattern together.

| When | Indicator | Meaning / next step |
| --- | --- | --- |
| Startup / reset | White for about 0.2 seconds | The ring has started. This does not confirm a Bluetooth connection. |
| Charging | Red, about 0.5 seconds on / 0.5 seconds off | Charging is in progress. |
| Fully charged | Steady green while the charging status remains full | Charging is complete. |
| Recording | Steady green | Audio recording is active. Release the button to finish. |
| `V2.001.0002.0000` successful mode switch | Blue twice, about 0.5 seconds on / 0.5 seconds off | The recording / gesture mode changed. Both directions use the same indication. |
| Recording transfer | Blue, about 0.5 seconds on / 0.5 seconds off | A recording transfer is active. |
| Recording or IMU-start error | Three quick red pulses, about 0.1 seconds on / off | The operation failed. Check battery, available storage, and the current mode. |
| Low-battery indication | Red for about 2 seconds, then off | Charge the ring. A short press can request this indication when the battery is low. |
| Critical-battery indication | Brief red for about 0.3 seconds, then off | Charge the ring before continuing. The indication alone does not confirm power-off. |

The low-battery and critical-battery indications are **continuous red intervals**, not three flashes. Startup, mode changes, and error indications are brief and can be missed.

Indicators can interrupt one another: battery warnings take precedence over mode changes, recording / transfer, and charging. Recording and a full charge both use green, so the LED alone cannot identify the state. Recording / transfer completion ends the corresponding indication; another active indication, such as charging, may then appear.

See [Buttons and Modes](https://github.com/ziloai/OpenZilo/wiki/Buttons-and-Modes) and [First Use](https://github.com/ziloai/OpenZilo/wiki/First-Use).

Firmware `V2.001.0002.0001` removes recording/gesture mode switching; do not use that blue indication to infer a mode.

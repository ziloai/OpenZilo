# Button and tap events

--8<-- "docs/_includes/devices.en.md"

Wait for device button and tap events. In firmware `V2.001.0002.0001`, a single press reports an event without switching recording/gesture modes.

Code snippets use `import openzilo as sdk`; `ring` is a connected client. See the [quick start](sdk-quickstart.en.md) for a complete connection example.

## Motion and button events

`0x0701`: physical double tap:

With firmware `V2.001.0002.0001`, start IMU with `start_sensor_report()` before waiting for taps; detection stops when capture stops. Firmware `V2.001.0002.0000` detects taps in gesture mode without BLE sample reporting.

```python
await sdk.start_sensor_report(ring)
try:
    event = await sdk.wait_sensor_double_tap_event(ring, timeout_s=30.0)
    print(event.timestamp_ms)
finally:
    await sdk.stop_sensor_report(ring)
```

`0x0703`: double button press:

A recognized double press emits only `0x0703`, without a corresponding `0x0704` or mode change.

```python
event = await sdk.wait_sensor_key_double_press_event(ring, timeout_s=30.0)
print(event.timestamp_ms)
```

`0x0704`: single button press:

```python
event = await sdk.wait_sensor_key_single_press_event(ring, timeout_s=30.0)
print(event.timestamp_ms)
```

Firmware `V2.001.0002.0001` emits `0x0704` without switching modes. Firmware `V2.001.0002.0000` attempts to switch recording/gesture modes and emits the event. Confirmation still waits for the double-press window, and the event body contains no mode field.

### `wait_sensor_key_single_press_event()`

```python
event = await sdk.wait_sensor_key_single_press_event(
    ring,
    timeout_s=30.0,
)
```

- Purpose: await the device's unsolicited `0x0704` single-button event.
- `ring`: connected `OpenZiloClient`.
- `timeout_s`: maximum wait in seconds; `None` uses client `command_timeout_s`.
- Returns `SensorKeySinglePressEvent`; `timestamp_ms` carries device time in seconds on this firmware, retaining a historical field name.
- Exceptions: SDK `TimeoutError` on timeout; `ProtocolError` for damaged packets.

### `parse_sensor_key_single_press_event()`

```python
event = sdk.parse_sensor_key_single_press_event(body)
```

- Purpose: parse a `0x0704` body without its 11-byte protocol header, usually for protocol tests or custom reception.
- `body`: exactly one network-order `u32` timestamp, four bytes.
- Returns `SensorKeySinglePressEvent`.
- Raises `ProtocolError` for fewer or more than four bytes.

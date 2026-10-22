<!-- --8<-- [start:device-basics] -->

!!! note "Connection requirements"

    Your computer needs Bluetooth Low Energy (BLE). The SDK communicates with the ring through NUS and supports protocol v4.


<!-- --8<-- [end:device-basics] -->

<!-- --8<-- [start:capabilities] -->

!!! tip "Available since SDK v0.6.1"

    `connect_ring()` discovers features automatically. When using `OpenZiloClient`, call `get_device_capabilities()` explicitly.


<!-- --8<-- [end:capabilities] -->

<!-- --8<-- [start:recording-control] -->

!!! note "Firmware version"

    This usage requires firmware **V2.001.0002.0001 or later**. V2.001.0002.0000 does not provide remote start, stop, status or recording configuration APIs.

<!-- --8<-- [end:recording-control] -->

<!-- --8<-- [start:live-audio] -->

!!! note "Firmware version"

    This usage requires firmware **V2.001.0002.0001 or later**. V2.001.0002.0000 transfers files after recording has been saved and does not provide live audio. Live PCM also requires the `pcm` extra.

<!-- --8<-- [end:live-audio] -->

<!-- --8<-- [start:imu] -->

!!! note "Firmware version"

    Starting capture directly with `start_sensor_report()` without switching modes requires firmware **V2.001.0002.0001 or later**. V2.001.0002.0000 requires entering gesture mode with the button first.

<!-- --8<-- [end:imu] -->

<!-- --8<-- [start:ota] -->

!!! note "Update requirements"

    Use the official OTA package specified in the release notes. Match the device model, hardware revision and starting firmware version. The SDK updates application firmware only, not the bootloader.


<!-- --8<-- [end:ota] -->

<!-- --8<-- [start:user-guide-scope] -->

!!! note "Firmware versions"

    This guide covers device operation in V2.001.0002.0000 and V2.001.0002.0001. V2.001.0002.0001 removes recording/gesture mode switching; the relevant sections identify the changes.

<!-- --8<-- [end:user-guide-scope] -->

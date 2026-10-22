<!-- --8<-- [start:device-basics] -->

!!! note "连接要求"

    电脑需要支持低功耗蓝牙（BLE）。SDK 使用 NUS 服务与戒指通信，支持协议 v4。


<!-- --8<-- [end:device-basics] -->

<!-- --8<-- [start:capabilities] -->

!!! tip "Available since SDK v0.6.1"

    连接时查询设备支持的功能。使用 `connect_ring()` 会自动查询；使用 `OpenZiloClient` 时需调用 `get_device_capabilities()`。


<!-- --8<-- [end:capabilities] -->

<!-- --8<-- [start:recording-control] -->

!!! note "固件版本"

    此用法需要固件 **V2.001.0002.0001 或更新版本**。V2.001.0002.0000 不提供远程开始、停止、状态查询和录音设置接口。

<!-- --8<-- [end:recording-control] -->

<!-- --8<-- [start:live-audio] -->

!!! note "固件版本"

    此用法需要固件 **V2.001.0002.0001 或更新版本**。V2.001.0002.0000 只在录音保存后传输文件，不提供实时音频。实时 PCM 还需安装 `pcm` 可选依赖。

<!-- --8<-- [end:live-audio] -->

<!-- --8<-- [start:imu] -->

!!! note "固件版本"

    无需切换模式、直接用 `start_sensor_report()` 启动采集的用法，需要固件 **V2.001.0002.0001 或更新版本**。V2.001.0002.0000 需先用按键进入手势模式。

<!-- --8<-- [end:imu] -->

<!-- --8<-- [start:ota] -->

!!! note "升级要求"

    使用官方发行说明指定的 OTA 升级包，并核对设备型号、硬件版本和当前固件版本。SDK 只升级应用固件，不升级引导程序（bootloader）。


<!-- --8<-- [end:ota] -->

<!-- --8<-- [start:user-guide-scope] -->

!!! note "固件版本说明"

    本文说明 V2.001.0002.0000 与 V2.001.0002.0001 的设备操作。V2.001.0002.0001 取消录音／手势模式切换；相关变化在对应小节注明。

<!-- --8<-- [end:user-guide-scope] -->

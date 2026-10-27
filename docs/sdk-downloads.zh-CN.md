# 下载与接收已保存的录音

--8<-- "docs/_includes/devices.zh-CN.md"

下载设备里已有的录音，或接收刚保存完成的录音。实时音频见[实时音频](sdk-live-audio.zh-CN.md)，录音参数与远程控制见[远程录音](recording-control.zh-CN.md)。

以下代码片段使用 `import openzilo as sdk`；`ring` 表示已连接的客户端，完整连接示例见[快速开始](sdk-quickstart.zh-CN.md)。

## 下载并保存录音

```text
connect -> get_audio_file_count -> download_audio_file -> save_audio_bundle
```

```python
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    count = await sdk.get_audio_file_count(ring)
    if count:
        info, raw_audio = await sdk.download_audio_file(ring, file_index=0)
        bundle = sdk.save_audio_bundle(
            file_index=info.file_index,
            data=raw_audio,
            metadata={"record_time": info.record_time},
            output_dir="audio",
        )
        print(bundle.raw_path)
        print(bundle.play_path)
```

`download_audio_file()` 默认 `quick=True`，使用快速下载。设置 `quick=False` 时，SDK 逐次请求文件数据。

## 接收并保存刚结束的录音

```text
connect -> receive_auto_audio_file 等待 -> 用户长按录音并松开
        -> `V2.001.0002.0001` 上报 0x050A 后 SDK 下载 / `V2.001.0002.0000` 连续上报 0x0505 -> save_audio_bundle
```

```python
async with sdk.OpenZiloClient(address=ADDRESS) as ring:
    print("请长按戒指录音，完成后松开")
    file_index, raw_audio = await sdk.receive_auto_audio_file(
        ring,
        timeout_s=60.0,
    )
    bundle = sdk.save_audio_bundle(
        file_index=file_index,
        data=raw_audio,
        output_dir="audio",
    )
    print(bundle.raw_path)
    print(bundle.play_path)
```

固件 `V2.001.0002.0000` 的自动上报不会预先发送 `0x0504`，因此返回值不包含 `AudioFileInfo`。正常连续接收时 SDK 不发送额外命令；需要恢复时会在内部查询元数据，以校验文件索引并将结果限制为准确的 `data_size`。等待期间必须保持 BLE 连接，并且不能同时调用 `download_audio_file()` 或 `read_audio_frame()` 接收同一段录音。若连接建立过晚而错过主动上报，应查询录音数量后使用 `download_audio_file()` 重新下载。

## 录音下载链路

SDK 支持两条录音提取链路：

| 链路 | 协议顺序 | SDK 调用 |
| --- | --- | --- |
| quick 链路 | `0x0509 -> 0x0504 -> 0x0505...`，缺帧时 `0x0506` 补帧 | `download_audio_file(..., quick=True)` |
| 普通链路 | `0x0503 -> 0x0504`，循环 `0x0506 -> 0x0505`，最后 `0x0507 -> 0x0508` | `download_audio_file(..., quick=False)` |
| `V2.001.0002.0000` 保存后自动上报 | 录音保存成功后直接连续 `0x0505...`；需要恢复时查询 `0x0504` 元数据，再用 `0x0506` 补帧 | `receive_auto_audio_file()` |
| `V2.001.0002.0001` 保存后通知 | `0x050A` 后按普通链路下载 | `receive_auto_audio_file()` |
| 实时录音 | `0x050D -> 0x050E` 订阅，随后 `0x050F -> 0x0510... -> 0x0511` | `receive_live_audio_file()` |

普通链路低层函数 `get_audio_file_info()`、`read_audio_frame()`、`end_audio_extract()` 主要用于调试。

## `download_audio_file()`

作用：完整下载指定录音。

签名：

```python
info, raw_audio = await download_audio_file(
    client,
    file_index,
    progress=None,
    timeout_s=None,
    quick=True,
)
```

返回：`tuple[AudioFileInfo, bytes]`

示例：

```python
info, raw_audio = await sdk.download_audio_file(
    ring,
    file_index=0,
    progress=sdk.ProgressPrinter(prefix="audio"),
)
```

注意：`file_index` 从 `0` 开始。先用 `get_audio_file_count()` 查询数量，避免访问不存在的录音。

## `receive_auto_audio_file()`

作用：取得刚保存的完整录音。固件 `V2.001.0002.0001` 收到 `0x050A` 后，SDK 主动普通下载并发送 `0x0507` 释放文件；固件 `V2.001.0002.0000` 接收主动 `0x0505`，仅在恢复时查询元数据。两种情况均返回原始文件，可交给 `save_audio_bundle()` 自动识别编码。

签名：

```python
file_index, raw_audio = await sdk.receive_auto_audio_file(
    ring,
    timeout_s=60.0,
)
```

参数：

- `client`：已连接的 `OpenZiloClient`，示例中为 `ring`。
- `timeout_s`：等待每次数据到达的最长秒数；为 `None` 时使用客户端的 `command_timeout_s`。

返回：`tuple[int, bytes]`

- 第一个值是 `0x050A` 或首个有效 `0x0505` 中的 `file_index`。
- 第二个值是按 `frame_offset` 拼接完成的原始录音字节，可直接传给 `save_audio_bundle()`。
- 固件 `V2.001.0002.0000` 自动上报不会预先携带 `0x0504`，因此函数不会返回 `AudioFileInfo`；恢复期间查询到的元数据只用于完整性校验和长度控制。

接收行为：

- 第一帧确定本次接收的 `file_index`，其他文件索引的帧不会混入结果。
- 重复和重叠数据会按偏移去除。
- 偏移出现缺口、首帧后等待超时或收到损坏帧时，SDK 先查询并校验文件索引和准确 `data_size`，再使用 `0x0506` 从当前期望偏移补传。
- 正常连续数据收到 `is_end=True` 后返回；恢复数据严格按 `data_size` 裁剪，不会返回边界后的字节。

异常：

- 首帧未在超时时间内到达：`TimeoutError`。
- 偏移缺口无法恢复、元数据索引不一致或帧字段不合法：`ProtocolError`。
- 设备返回非 0 错误码：`DeviceError`。
- 调用开始时未连接或等待期间 BLE 断开：`TransportError`。

并发限制：不要与 `download_audio_file()`、`read_audio_frame()` 或其他直接等待 `0x0505` 的代码同时运行。同一连接的录音接收操作应依次执行。若 BLE 连接建立得太晚而错过自动上报，使用 `get_audio_file_count()` 和 `download_audio_file()` 重新下载。

保存示例：

```python
file_index, raw_audio = await sdk.receive_auto_audio_file(ring, timeout_s=60.0)
bundle = sdk.save_audio_bundle(
    file_index=file_index,
    data=raw_audio,
    output_dir="audio",
)
```

## `clear_audio_files()`

作用：删除设备内所有录音。

```python
await sdk.clear_audio_files(ring)
```

这是破坏性操作。建议业务代码增加二次确认或环境变量保护。

## 读取信息、下载第一条录音、保存文件

```python
import asyncio
import openzilo as sdk

ADDRESS = "AA:BB:CC:DD:EE:FF"


async def main() -> None:
    async with sdk.OpenZiloClient(address=ADDRESS) as ring:
        sdk.enable_time_sync(ring)

        info = await sdk.get_system_info(ring)
        print("system:", info)

        count = await sdk.get_audio_file_count(ring)
        print("audio count:", count)
        if count == 0:
            return

        audio_info, raw_audio = await sdk.download_audio_file(
            ring,
            file_index=0,
            progress=sdk.ProgressPrinter(prefix="audio"),
        )

    bundle = sdk.save_audio_bundle(
        file_index=audio_info.file_index,
        data=raw_audio,
        metadata={"record_time": audio_info.record_time},
        output_dir="audio",
    )
    print("raw:", bundle.raw_path)
    print("play:", bundle.play_path)


if __name__ == "__main__":
    asyncio.run(main())
```

# 参与贡献

欢迎改进 SDK、示例和文档。提交前请先确认修改范围，并保持 `openzilo.__all__` 中的公开接口兼容；需要更改接口时，请在说明中写清影响和迁移方法。

## 修改代码

代码放在负责相应功能的模块中，公开接口统一从 `openzilo` 导出。协议或解析逻辑发生变化时，补充不依赖设备的测试，并更新相关示例和文档。

在仓库目录运行：

```bash
uv sync --locked
uv run python -m compileall src
uv run python -m unittest discover -s tests -v
uv run openzilo --help
```

用 `uv add` 或 `uv remove` 修改依赖，并提交更新后的 `uv.lock`。涉及设备功能时，在 PR 中说明适用的固件和设备。

## 修改文档

正文使用 Markdown。文档构建、语言文件和 GitHub Pages 配置见[维护文档](docs/documentation.zh-CN.md)。版本要求写清设备、固件和 SDK，不用协议版本代替具体功能要求。

## 提交内容

示例使用占位地址。提交前移除真实设备地址、序列号、CPUID、私人录音和凭据。不要把设备采集记录、生成音频、固件、APK 或 CAD 文件混入 SDK 修改。

软件和文档贡献采用 MPL-2.0。硬件设计如在相应仓库发布，采用对应硬件许可。安全漏洞请按[安全报告说明](SECURITY.zh-CN.md)私下报告。

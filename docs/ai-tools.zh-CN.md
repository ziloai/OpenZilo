# 使用 AI 编程工具

--8<-- "docs/_includes/devices.zh-CN.md"

先把 OpenZilo 仓库克隆到本机并安装依赖，再用编程工具打开仓库：

```bash
git clone https://github.com/ziloai/openzilo.git
cd openzilo
uv sync --locked
```

[`llms.txt`](../llms.txt) 是文档索引，列出 SDK 手册、协议说明和示例。让工具先读索引，再按需要查接口，可以减少调用不存在的 API。

## Codex

在仓库目录运行 `codex`。项目要求见 [`AGENTS.md`](../AGENTS.md)。

## Claude Code

在仓库目录运行 `claude`。[`CLAUDE.md`](../CLAUDE.md) 会引用 `AGENTS.md` 中的项目要求。

## Cursor

用 Cursor 打开仓库并使用 Agent，项目要求见 [`AGENTS.md`](../AGENTS.md)。

## GitHub Copilot

用编辑器打开仓库，或使用其编程代理。项目要求见 [Copilot 项目说明](../.github/copilot-instructions.md)。

## Gemini CLI

在仓库目录运行 `gemini`。[`GEMINI.md`](../GEMINI.md) 会引用 `AGENTS.md` 中的项目要求。

## OpenCode

在仓库目录运行 `opencode`。项目要求见 [`AGENTS.md`](../AGENTS.md)。

这些文件说明公开接口、示例位置和贡献要求。工具安装与配置请参考各自的官方文档，英文页面保留了对应链接。

## 从一个小任务开始

可以这样提问：

> 读取 `llms.txt` 和 `docs/python-sdk.zh-CN.md`。使用 `openzilo` 的公开接口写一个脚本，扫描戒指，读取型号、固件版本和电量。用 `asyncio.run()` 启动，结束时断开连接。

需要录音等功能时，再让工具阅读对应功能页，并在调用前检查设备是否支持。Python SDK 的接口从 `openzilo` 导入，不从以下划线开头的内部模块导入。

## 在其他项目中使用

将 `llms.txt` 的本地副本或[原始文件链接](https://raw.githubusercontent.com/ziloai/openzilo/main/llms.txt)提供给编程工具，并指向相关手册。SDK 本身可以通过 Git URL 添加到自己的 uv 项目，安装方式见 [安装说明](sdk-install.zh-CN.md#安装依赖)。

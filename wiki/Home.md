# OpenZilo 文档

OpenZilo 是兼容 BLE 戒指的 Python SDK。这里是文档入口；完整技术文档在主仓库维护，避免 Wiki 与代码版本脱节。

想了解或获取硬件？访问 [OpenZilo 官网](https://openzilo.com)及[开发套件页面](https://openzilo.com/buy)。

## 从这里开始

1. [安装与快速开始](https://github.com/ziloai/openzilo/blob/main/README.zh-CN.md)
2. [Python SDK 使用手册](https://github.com/ziloai/openzilo/blob/main/docs/python-sdk.zh-CN.md)
3. [协议参考](https://github.com/ziloai/openzilo/blob/main/docs/protocol.zh-CN.md)
4. [架构与数据流](https://github.com/ziloai/openzilo/blob/main/docs/architecture.zh-CN.md)

## 常用命令

```bash
python -m pip install -e .
python -m openzilo scan --timeout 10
python -m openzilo info --address AA:BB:CC:DD:EE:FF
```

将示例地址换成扫描得到的设备地址。SDK 需要 Python 3.10+ 和可用的 BLE 适配器；Speex 转 WAV 时还需 `ffmpeg`。

## 给 AI 编程工具

[AI 工具接入指南](https://github.com/ziloai/openzilo/blob/main/docs/ai-tools.md)说明 Codex、Claude Code、Cursor、GitHub Copilot、Gemini CLI 和 OpenCode 的项目接入方式；[llms.txt](https://raw.githubusercontent.com/ziloai/openzilo/main/llms.txt) 汇总文档、源码和示例链接。

## 研究

[ComBodied Agents: a New Paradigm of Human-Centric Agentic AI](https://arxiv.org/abs/2608.10915) 是官网展示的研究论文；另有 [PDF](https://arxiv.org/pdf/2608.10915)。

## 项目与安全

- [English README](https://github.com/ziloai/openzilo/blob/main/README.md)
- [示例代码](https://github.com/ziloai/openzilo/tree/main/examples)
- [贡献指南](https://github.com/ziloai/openzilo/blob/main/CONTRIBUTING.md)
- [安全问题私下报告](https://github.com/ziloai/openzilo/blob/main/SECURITY.md)
- [软件许可 MPL-2.0](https://github.com/ziloai/openzilo/blob/main/LICENSE)
- [硬件设计许可 CERN-OHL-W-2.0](https://github.com/ziloai/openzilo/blob/main/LICENSES/CERN-OHL-W-2.0.txt)

当前文档基于 SDK 0.5.0、设备协议 v4 和固件 `V2.000.0001.0015`；请在目标硬件上验证行为。

<p align="center">
  <a href="https://openzilo.com"><img src="docs/assets/openzilo-hero.png" alt="OpenZilo ring" width="960"></a>
</p>

<h1 align="center">OpenZilo Python SDK</h1>

<p align="center">Audio, motion, and gesture input from an OpenZilo BLE ring.</p>

<p align="center">
  <a href="https://github.com/ziloai/openzilo/actions/workflows/ci.yml"><img src="https://github.com/ziloai/openzilo/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/software-MPL--2.0-555555" alt="MPL-2.0"></a>
  <a href="LICENSES/CERN-OHL-W-2.0.txt"><img src="https://img.shields.io/badge/hardware-CERN--OHL--W--2.0-555555" alt="CERN-OHL-W-2.0"></a>
</p>

<p align="center">
  <a href="https://openzilo.com">Website</a> ·
  <a href="https://openzilo.com/buy">Get the Kit</a> ·
  <a href="#coding-agents">Coding agents</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="README.zh-CN.md">简体中文</a>
</p>

This repository contains the Python SDK and CLI for scanning and connecting to a ring, reading device information, downloading recordings, converting Speex to WAV, and receiving IMU and gesture events. It documents protocol v4 on firmware `V2.000.0001.0015`. Check device behavior on your own hardware.

## Coding agents

Open the cloned repository in your tool. The project instructions point to the SDK's public API and the [`llms.txt`](llms.txt) documentation index.

| Tool | Start in repository root | Project instructions |
| --- | --- | --- |
| <img src="docs/assets/ai-tools/openai-codex.png" alt="" width="24"> [Codex](docs/ai-tools.md#codex) | `codex` | [`AGENTS.md`](AGENTS.md) |
| <img src="docs/assets/ai-tools/claude-code.png" alt="" width="24"> [Claude Code](docs/ai-tools.md#claude-code) | `claude` | [`CLAUDE.md`](CLAUDE.md) |
| <img src="docs/assets/ai-tools/cursor.png" alt="" width="24"> [Cursor](docs/ai-tools.md#cursor) | Open the repository | [`AGENTS.md`](AGENTS.md) |
| <img src="docs/assets/ai-tools/github-copilot.svg" alt="" width="24"> [GitHub Copilot](docs/ai-tools.md#github-copilot) | Open the repository | [Copilot instructions](.github/copilot-instructions.md) |
| <img src="docs/assets/ai-tools/gemini-cli.png" alt="" width="24"> [Gemini CLI](docs/ai-tools.md#gemini-cli) | `gemini` | [`GEMINI.md`](GEMINI.md) |
| <img src="docs/assets/ai-tools/opencode.png" alt="" width="24"> [OpenCode](docs/ai-tools.md#opencode) | `opencode` | [`AGENTS.md`](AGENTS.md) |

Try: “Read `llms.txt` and the Python SDK guide. Write a script using exported `openzilo` APIs that scans for a ring and prints its model, firmware version, and battery level.” See the [setup guide](docs/ai-tools.md) for installation links and using these docs from another repository.

## Quick start

You need Python 3.10+ and a BLE adapter. On Linux, you also need BlueZ and Bluetooth access. Install from the repository:

```bash
git clone https://github.com/ziloai/openzilo.git
cd openzilo
python -m pip install -e .
python -m openzilo scan --timeout 10
python -m openzilo info --address AA:BB:CC:DD:EE:FF
```

Replace the example address with one returned by `scan`. In Python:

```python
import asyncio
import openzilo as sdk


async def main() -> None:
    async with sdk.OpenZiloClient(address="AA:BB:CC:DD:EE:FF") as ring:
        info = await sdk.get_system_info(ring)
        print(info.model, info.firmware_version, info.battery_percent)


asyncio.run(main())
```

See the [examples](examples/) for audio download and IMU streaming. Install `ffmpeg` if you need Speex-to-WAV conversion. `audio-clear` deletes recordings from the device and requires `--yes`.

## Research and partners

[ComBodied Agents: a New Paradigm of Human-Centric Agentic AI](https://arxiv.org/abs/2608.10915) is featured on the [OpenZilo website](https://openzilo.com). [PDF](https://arxiv.org/pdf/2608.10915) · [Hugging Face Papers](https://huggingface.co/papers/2608.10915)

<p align="center"><a href="https://openzilo.com"><img src="docs/assets/partners-panel.png" alt="OpenZilo research and industry partners" width="1000"></a></p>

## Citation

If you find OpenZilo or the ComBodied Agents paradigm useful in your research, please consider citing:

```bibtex
@article{ding2026combodied,
  title={ComBodied Agents: a New Paradigm of Human-Centric Agentic AI},
  author={Ding, Qianggang and Wang, Xingyao and Feng, Rui and Wang, Zhibin and Yao, Feixiang and Mao, Kelong and Sun, Hao and Luo, Zhiyao and Tang, Jiankai and Li, Lei and Guo, Jiadong and Ni, Minheng and Lin, Weicong and Yang, Chenxi and Gao, Hongxiang and Chen, Zhenghua and Bai, Yang and Wu, Min and Cheng, Jun and Fu, Huazhu and Tao, Dacheng and Liu, Bang},
  journal={arXiv preprint arXiv:2608.10915},
  year={2026}
}
```

## Get Featured on OpenZilo GitHub Trend

Want your project to appear on the **OpenZilo homepage GitHub Trend**?

Simply mention **“ComBodied AI”** in your `README.md`.

OpenZilo automatically discovers and surfaces GitHub projects building around the **ComBodied AI** ecosystem.

## Documentation

- [Python SDK guide](docs/python-sdk.zh-CN.md): public API and examples
- [BLE protocol reference](docs/protocol.zh-CN.md): packet format and implemented commands
- [Architecture and data flow](docs/architecture.zh-CN.md): recording transfer, audio decoding, and events
- [Coding agent setup](docs/ai-tools.md) and [`llms.txt`](llms.txt)

## License and contributions

Software and documentation use [MPL-2.0](LICENSE). Hardware designs use [CERN-OHL-W-2.0](LICENSES/CERN-OHL-W-2.0.txt). Brand and third-party marks belong to their respective owners.

See [CONTRIBUTING.md](CONTRIBUTING.md) for contributions and [SECURITY.md](SECURITY.md) for private security reports.

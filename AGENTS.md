# OpenZilo project guidance

This repository contains the Python BLE SDK and CLI for compatible OpenZilo rings. The maintained public API is `openzilo.__all__` in `src/openzilo/__init__.py`; the underscore submodules are private. It does not contain firmware source, a TypeScript SDK, or public PPG APIs. The [website](https://openzilo.com) describes a broader platform; check the implementation and [SDK documentation](docs/index.md) before claiming a capability is available here.

## Where to look

- Start with [llms.txt](llms.txt) for the documentation index.
- Start with [installation](docs/sdk-install.zh-CN.md) and [quick start](docs/sdk-quickstart.zh-CN.md). Use [docs/python-sdk.zh-CN.md](docs/python-sdk.zh-CN.md) as the Python API index; it links to feature guides. Use [docs/protocol.zh-CN.md](docs/protocol.zh-CN.md) for wire fields, and [docs/architecture.zh-CN.md](docs/architecture.zh-CN.md) for transport and audio behavior.
- Use [examples/](examples/) for small runnable examples. `ffmpeg` is needed only for Speex/Opus-to-WAV conversion.

## Working agreements

- Keep changes focused. Put code in the submodule that owns that area, export public names only from `src/openzilo/__init__.py`, and update examples and documentation when a public API changes.
- Never commit real device addresses, serial numbers, CPUIDs, recordings, captures, firmware, or credentials. Follow [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).
- Keep `audio-clear` gated by its explicit `--yes` confirmation.
- Run the smallest relevant check first. Use uv: `uv sync` sets up `.venv` from `uv.lock`. For protocol or parser changes, run `uv run python -m unittest discover -s tests -v`; CI also compiles `src` and checks `uv run openzilo --help`. Change dependencies with `uv add`/`uv remove`, not by hand.
- Hardware-dependent claims require validation on the target device. The documented baseline is protocol v4 and firmware `V2.001.0002.0000`.
- Software and documentation use MPL-2.0; hardware design files, if published, use CERN-OHL-W-2.0. The third-party logos are separate marks.

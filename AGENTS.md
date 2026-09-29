# OpenZilo project guidance

This repository contains the Python BLE SDK and CLI for compatible OpenZilo rings. The maintained public API is `src/openzilo.py.__all__`. It does not contain firmware source, a TypeScript SDK, or public PPG APIs. The [website](https://openzilo.com) describes a broader platform; check the implementation and [SDK guide](docs/python-sdk.zh-CN.md) before claiming a capability is available here.

## Where to look

- Start with [llms.txt](llms.txt) for the documentation index.
- Use [docs/python-sdk.zh-CN.md](docs/python-sdk.zh-CN.md) for Python API calls, [docs/protocol.zh-CN.md](docs/protocol.zh-CN.md) for wire fields, and [docs/architecture.zh-CN.md](docs/architecture.zh-CN.md) for transport and audio behavior.
- Use [examples/](examples/) for small runnable examples. `ffmpeg` is needed only for Speex-to-WAV conversion.

## Working agreements

- Keep changes focused and match the existing single-module SDK structure. Update examples and documentation when a public API changes.
- Never commit real device addresses, serial numbers, CPUIDs, recordings, captures, firmware, or credentials. Follow [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).
- Keep `audio-clear` gated by its explicit `--yes` confirmation.
- Run the smallest relevant check first. For protocol or parser changes, run `python -m unittest discover -s tests -v`; CI also compiles `src` and checks `python -m openzilo --help`.
- Hardware-dependent claims require validation on the target device. The documented baseline is protocol v4 and firmware `V2.000.0001.0015`.
- Software and documentation use MPL-2.0; hardware design files, if published, use CERN-OHL-W-2.0. The third-party logos are separate marks.

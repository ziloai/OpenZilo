# OpenZilo SDK

This repository is a Python 3.10+ BLE SDK and CLI, not firmware source. The implemented public API is `src/openzilo.py.__all__`; consult `docs/python-sdk.zh-CN.md`, `llms.txt`, and the examples before generating integrations. The product website describes a broader platform, so do not invent Python PPG APIs or a TypeScript SDK.

Keep changes focused. Do not commit real device identifiers, recordings, firmware, captures, or credentials. Preserve the `audio-clear --yes` confirmation. For protocol or parser changes, run `python -m unittest discover -s tests -v` and update the relevant docs and examples. The repository's `AGENTS.md` has the complete project guidance.

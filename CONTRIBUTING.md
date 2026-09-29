# Contributing

Thank you for contributing to OpenZilo Python SDK.

Keep changes focused, preserve the single-file public module unless a compatibility change is explicitly agreed, and do not include device captures, generated audio, firmware, APKs, CAD assets, or secrets. Use placeholder MAC addresses and remove real serial numbers and CPUIDs from examples, logs, and screenshots. Add or update hardware-free tests for protocol and parser changes.

Before opening a pull request, run:

```bash
python -m compileall src
python -m unittest discover -s tests -v
python -m openzilo --help
```

Describe the tested firmware/device baseline for hardware-dependent changes. Software and documentation contributions are submitted under MPL-2.0; hardware design contributions, if added, are submitted under CERN-OHL-W-2.0.

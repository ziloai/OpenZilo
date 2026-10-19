# Contributing

Contributions to the SDK, examples and documentation are welcome. Keep changes focused and preserve compatibility for the public API in `openzilo.__all__`. If an API must change, explain its impact and migration steps.

## Code changes

Keep code in the module responsible for the feature and export public APIs from `openzilo`. For protocol or parser changes, add hardware-free tests and update relevant examples and documentation.

Run these checks from the repository:

```bash
uv sync --locked
uv run python -m compileall src
uv run python -m unittest discover -s tests -v
uv run openzilo --help
```

Use `uv add` or `uv remove` to change dependencies, and commit the updated `uv.lock`. For hardware-dependent changes, describe the applicable firmware and device in the PR.

## Documentation changes

Write documentation in Markdown. State device, firmware and SDK requirements explicitly; a protocol version alone does not establish feature support.

## Submission contents

Use placeholder addresses in examples. Remove real device addresses, serial numbers, CPUIDs, private recordings and credentials before submitting. Do not include device captures, generated audio, firmware, APKs or CAD files in SDK changes.

Software and documentation contributions use MPL-2.0. Hardware designs published in their own repository use its hardware license. Report vulnerabilities privately as described in the [security policy](SECURITY.md).

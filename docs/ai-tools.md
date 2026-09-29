# Use OpenZilo with coding agents

Clone the repository, install the SDK, and start your coding tool from the repository root:

```bash
git clone https://github.com/ziloai/openzilo.git
cd openzilo
python -m pip install -e .
```

[`llms.txt`](../llms.txt) lists the API guide, protocol reference, examples, and source. The files below give each tool the same project boundaries.

## Codex

Run `codex`. It reads [`AGENTS.md`](../AGENTS.md) for project instructions. [Codex setup](https://developers.openai.com/codex/cli/) · [AGENTS.md support](https://developers.openai.com/codex/guides/agents-md/)

## Claude Code

Run `claude`. [`CLAUDE.md`](../CLAUDE.md) imports `AGENTS.md`. [Claude Code setup](https://code.claude.com/docs/en/quickstart) · [Project memory](https://code.claude.com/docs/en/memory)

## Cursor

Open the repository in Cursor and use Agent chat. Cursor reads the root [`AGENTS.md`](../AGENTS.md). [Cursor rules](https://cursor.com/docs/context/rules)

## GitHub Copilot

Open the repository in an IDE with Copilot, or select it for Copilot's coding agent. Its repository instructions are in [`.github/copilot-instructions.md`](../.github/copilot-instructions.md). [Copilot instructions](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions)

## Gemini CLI

Run `gemini`. [`GEMINI.md`](../GEMINI.md) imports `AGENTS.md`. [Gemini CLI setup](https://geminicli.com/docs/) · [Project context](https://geminicli.com/docs/cli/gemini-md/)

## OpenCode

Run `opencode`. It reads [`AGENTS.md`](../AGENTS.md). [OpenCode setup](https://opencode.ai/docs/) · [Rules](https://opencode.ai/docs/rules/)

## First task

> Read `llms.txt` and `docs/python-sdk.zh-CN.md`. Using only exported `openzilo` APIs, write a script that scans for a ring and prints its model, firmware version, and battery level.

Working in another repository? Give the tool a local copy of `llms.txt` or its [raw URL](https://raw.githubusercontent.com/ziloai/openzilo/main/llms.txt), then point it to the relevant SDK pages. GitHub access is required while this repository is private.

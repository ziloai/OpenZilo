# SPDX-License-Identifier: MPL-2.0
"""Local CLI preferences; device identifiers never belong in the repository."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def config_path() -> Path:
    if os.environ.get("OPENZILO_CONFIG"):
        return Path(os.environ["OPENZILO_CONFIG"]).expanduser()
    root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return root / "openzilo" / "config.json"


def load_address() -> str | None:
    path = config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"Invalid CLI config at {path}; use 'device forget' to reset it") from exc
    if not isinstance(data, dict) or not isinstance(data.get("address"), str) or not data["address"].strip():
        raise ValueError(f"Invalid CLI config at {path}; use 'device forget' to reset it")
    return data["address"].strip()


def save_address(address: str) -> None:
    address = address.strip()
    if not address:
        raise ValueError("Device address must not be empty")
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement avoids leaving a truncated config on interruption.
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".openzilo-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"address": address}, stream)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)

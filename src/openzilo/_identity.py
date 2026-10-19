# SPDX-License-Identifier: MPL-2.0
"""Reproducible SDK source identity, including editable installations."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from ._version import __version__

@dataclass(frozen=True)
class SdkIdentity:
    version: str
    source_sha256: str


def get_sdk_identity() -> SdkIdentity:
    """Hash package Python sources only; never inspect device/user configuration."""
    digest = sha256()
    package = Path(__file__).parent
    for source in sorted(package.rglob("*.py")):
        digest.update(source.relative_to(package).as_posix().encode("utf-8") + b"\0")
        content = source.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return SdkIdentity(__version__, digest.hexdigest())

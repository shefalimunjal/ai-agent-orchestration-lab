#!/usr/bin/env python3
"""Load the orchestrator identity without ever writing it to stdout or stderr."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Mapping


PRIVATE_KEY_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def load_private_key(identity: Mapping[str, object]) -> str:
    for name in ("private_key_hex", "secret_key_hex", "private_key"):
        value = identity.get(name)
        if isinstance(value, str) and PRIVATE_KEY_PATTERN.fullmatch(value):
            return value
    raise RuntimeError("identity file must contain a 64-hex private key")


def main() -> None:
    identity_path = os.environ.get("ORCHESTRATOR_IDENTITY_FILE")
    if not identity_path:
        raise RuntimeError("ORCHESTRATOR_IDENTITY_FILE is required")
    try:
        identity = json.loads(Path(identity_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("could not load orchestrator identity file") from exc
    if not isinstance(identity, dict):
        raise RuntimeError("orchestrator identity must be a JSON object")
    os.environ["BUZZ_PRIVATE_KEY"] = load_private_key(identity)
    os.execv("/usr/local/bin/buzz-acp", ["/usr/local/bin/buzz-acp"])


if __name__ == "__main__":
    main()

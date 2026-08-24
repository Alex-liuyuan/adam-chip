"""CanMV/Kendryte K230 platform plugin."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


PLATFORM_DIR = Path(__file__).resolve().parent
ROOT = PLATFORM_DIR.parents[1]


def contract_path(name: str) -> Path:
    return PLATFORM_DIR / f"{name}.json"


def load_contract(name: str) -> dict[str, Any]:
    return json.loads(contract_path(name).read_text(encoding="utf-8"))


def target_path() -> Path:
    return contract_path("target")


def required_third_party_groups() -> tuple[str, ...]:
    return ("platform_backends",)


def ensure_tools_path() -> None:
    tools = str(ROOT / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)

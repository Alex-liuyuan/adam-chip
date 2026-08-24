"""Validated project-order loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "project_order.schema.json"


def resolve(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).iter_errors(data), key=lambda item: list(item.path))
    if errors:
        raise ValueError(errors[0].message)
    target = resolve(data["target"])
    platform = ROOT / "platforms" / data["platform"]
    if not target.is_file():
        raise ValueError(f"target contract is missing: {target}")
    if not platform.is_dir():
        raise ValueError(f"platform plugin is missing: {platform}")
    for values in data.get("hardware_inputs", {}).values():
        for value in values:
            source = resolve(value)
            if not source.is_file():
                raise ValueError(f"hardware input is missing: {source}")
    return data

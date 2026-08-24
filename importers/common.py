"""Shared helpers for hardware metadata importers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_TARGET_FIELDS = ("name", "isa", "abi", "toolchain_prefix", "memory", "firmware")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def missing_required(target: dict[str, Any]) -> list[str]:
    return [key for key in REQUIRED_TARGET_FIELDS if target.get(key) in (None, "", {})]


def report(source: Path, target: dict[str, Any], observations: list[dict[str, Any]], evidence_name: str, conflicts: list[str] | None = None) -> dict[str, Any]:
    conflicts = conflicts or []
    missing = missing_required(target)
    return {
        "schema": "adam.target_import.draft.v1",
        "ok": not conflicts,
        "source": str(source),
        "target": target,
        "observations": observations,
        "missing_required_fields": missing,
        "conflicts": conflicts,
        "evidence": {
            evidence_name: not conflicts and bool(observations),
            "field_provenance_recorded": bool(observations),
        },
        "not_claimed": [
            "imported hardware metadata is not a complete SDK contract until missing fields are resolved",
            "imported hardware metadata is not board execution evidence",
        ],
    }

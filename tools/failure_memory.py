#!/usr/bin/env python3
"""JSONL failure memory for ADAM tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_memory(path: Path, *, domain: str = "", target: str = "") -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if domain and item.get("domain") != domain:
            continue
        if target and item.get("target") not in ("", target):
            continue
        records.append(item)
    return records


def append_memory(path: Path, records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_memory(path)
    seen = {(item.get("domain"), item.get("target"), item.get("cause"), item.get("effect"), item.get("artifact")) for item in existing}
    added = []
    for record in records:
        key = (
            record.get("domain"),
            record.get("target"),
            record.get("cause"),
            record.get("effect"),
            record.get("artifact"),
        )
        if key in seen:
            continue
        seen.add(key)
        added.append(record)
    if not added:
        return 0
    with path.open("a", encoding="utf-8") as handle:
        for record in added:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    return len(added)

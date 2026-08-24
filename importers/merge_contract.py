#!/usr/bin/env python3
"""Merge target contract drafts without silently resolving conflicts."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from importers.common import missing_required, read_json, write_json


def draft_target(data: dict[str, Any]) -> dict[str, Any]:
    target = data.get("target", data)
    return target if isinstance(target, dict) else {}


def merge_value(dst: dict[str, Any], key: str, value: Any, conflicts: list[str], prefix: str = "") -> None:
    path = f"{prefix}.{key}" if prefix else key
    if key not in dst or dst[key] in ({}, [], "", None):
        dst[key] = value
        return
    current = dst[key]
    if isinstance(current, dict) and isinstance(value, dict):
        for child_key, child_value in value.items():
            merge_value(current, child_key, child_value, conflicts, path)
        return
    if current != value and value not in ({}, [], "", None):
        conflicts.append(f"conflict at {path}: {current!r} != {value!r}")


def merge(paths: list[Path], out: Path) -> dict[str, Any]:
    target: dict[str, Any] = {}
    conflicts: list[str] = []
    sources: list[str] = []
    for path in paths:
        sources.append(str(path))
        for key, value in draft_target(read_json(path)).items():
            merge_value(target, key, value, conflicts)
    missing = missing_required(target)
    result = {
        "schema": "adam.target_import.merge.v1",
        "ok": not conflicts,
        "sources": sources,
        "target": target,
        "missing_required_fields": missing,
        "conflicts": conflicts,
        "evidence": {
            "contract_conflicts_checked": not conflicts,
            "field_provenance_recorded": bool(sources),
        },
        "not_claimed": [
            "merged target draft is not complete while missing_required_fields is non-empty",
            "merged target draft is not board execution evidence",
        ],
    }
    write_json(out / "target.draft.json", result)
    write_json(out / "target.json", target)
    return result


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        a = root / "a.json"
        b = root / "b.json"
        a.write_text('{"target":{"name":"demo","isa":"rv64gcv","memory":{"flash_kb":1024}}}', encoding="utf-8")
        b.write_text('{"target":{"abi":"lp64d","toolchain_prefix":"riscv64-unknown-elf-","firmware":{"image":"x.bin"}}}', encoding="utf-8")
        result = merge([a, b], root / "out")
        assert result["ok"], result
        assert result["missing_required_fields"] == [], result
        c = root / "c.json"
        c.write_text('{"target":{"name":"other"}}', encoding="utf-8")
        bad = merge([a, c], root / "bad")
        assert not bad["ok"], bad
        assert bad["conflicts"], bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", nargs="+")
    parser.add_argument("--out", default=str(ROOT / "build/import_merge"))
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    if not args.inputs:
        parser.error("--inputs is required unless --selftest is used")
    result = merge([Path(item).resolve() for item in args.inputs], Path(args.out).resolve())
    print(__import__("json").dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

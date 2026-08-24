#!/usr/bin/env python3
"""Validate platform contract files against the project schema subset."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ("target", "boot", "image", "flash", "accelerator", "evidence")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


def validate_node(data: Any, schema: dict[str, Any], prefix: str = "$") -> list[str]:
    errors: list[str] = []
    expected = schema.get("type")
    if expected and not type_ok(data, str(expected)):
        return [f"{prefix}: expected {expected}"]
    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{prefix}: value is not in enum")
    if isinstance(data, str):
        if len(data) < int(schema.get("minLength", 0)):
            errors.append(f"{prefix}: string is shorter than minLength")
        if schema.get("pattern") and not re.search(str(schema["pattern"]), data):
            errors.append(f"{prefix}: string does not match pattern")
    if isinstance(data, int) and not isinstance(data, bool) and "minimum" in schema and data < int(schema["minimum"]):
        errors.append(f"{prefix}: value is below minimum")
    if isinstance(data, list):
        if len(data) < int(schema.get("minItems", 0)):
            errors.append(f"{prefix}: array has fewer than minItems")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(data):
                errors.extend(validate_node(item, item_schema, f"{prefix}[{index}]"))
    if isinstance(data, dict):
        for key in schema.get("required", []):
            if key not in data or data[key] in ("", None, {}, []):
                errors.append(f"{prefix}: missing required field {key}")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if key in data and isinstance(child_schema, dict):
                    errors.extend(validate_node(data[key], child_schema, f"{prefix}.{key}"))
    return errors


def validate_file(contract: Path, schema: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        data = load(contract)
        schema_data = load(schema)
    except Exception as exc:
        return {"ok": False, "contract": str(contract), "schema": str(schema), "errors": [str(exc)]}
    errors.extend(validate_node(data, schema_data))
    return {"ok": not errors, "contract": str(contract), "schema": str(schema), "errors": errors}


def target_mirror_status(target_data: dict[str, Any], targets_dir: Path) -> dict[str, Any]:
    mirror = targets_dir / f"{target_data.get('name', '')}.json"
    if not mirror.exists():
        return {"present": False, "ok": True}
    matches = load(mirror) == target_data
    return {
        "present": True,
        "ok": matches,
        "path": str(mirror),
        "error": "" if matches else "legacy target mirror differs from canonical platform target",
    }


def source_revision_status(target_data: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    required = target_data.get("_provenance", {}).get("source_revisions", {})
    if not required:
        return {"present": False, "ok": True, "mismatches": []}
    manifest = load(manifest_path)
    declared = {item["name"]: str(item.get("revision", "")) for items in manifest.values() for item in items}
    mismatches = [name for name, revision in required.items() if declared.get(name) != revision]
    return {"present": True, "ok": not mismatches, "required": required, "mismatches": mismatches}


def validate_platform_contracts(platform: str, platform_dir: Path, out: Path) -> dict[str, Any]:
    checks = []
    for name in CONTRACTS:
        contract = platform_dir / f"{name}.json"
        schema = ROOT / "contracts" / f"{name}.schema.json"
        if not contract.exists():
            checks.append({"ok": False, "contract": str(contract), "schema": str(schema), "errors": ["missing contract file"]})
        elif not schema.exists():
            checks.append({"ok": False, "contract": str(contract), "schema": str(schema), "errors": ["missing schema file"]})
        else:
            checks.append(validate_file(contract, schema))
    target_path = platform_dir / "target.json"
    target_semantics = {"ok": False, "errors": ["target contract is unavailable"]}
    target_mirror = {"present": False, "ok": True}
    source_revisions = {"present": False, "ok": True, "mismatches": []}
    if target_path.exists():
        try:
            from tools import target_contract_validate
        except ModuleNotFoundError:  # pragma: no cover
            import target_contract_validate
        target_data = load(target_path)
        semantic_errors, semantic_warnings = target_contract_validate.validate_shape(target_data)
        target_semantics = {"ok": not semantic_errors, "errors": semantic_errors, "warnings": semantic_warnings}
        target_mirror = target_mirror_status(target_data, ROOT / "targets")
        source_revisions = source_revision_status(target_data, ROOT / "third_party.manifest.json")
    report = {
        "schema": "adam.contract_schema_gate.v1",
        "platform": platform,
        "ok": all(item["ok"] for item in checks) and target_semantics["ok"] and target_mirror["ok"] and source_revisions["ok"],
        "checks": checks,
        "target_semantics": target_semantics,
        "target_mirror": target_mirror,
        "source_revisions": source_revisions,
        "evidence": {
            "schema_valid": all(item["ok"] for item in checks) and target_semantics["ok"],
            "contract_conflicts_checked": all(item["ok"] for item in checks),
        },
        "not_claimed": [
            "schema validation is not build, flash, boot, or model runtime evidence",
        ],
    }
    write_json(out / "contract_schema_gate.json", report)
    return report


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good = validate_platform_contracts("example_riscv_board", ROOT / "platforms/example_riscv_board", root / "good")
        assert good["ok"], good
        bad_dir = root / "bad_platform"
        bad_dir.mkdir()
        for name in CONTRACTS:
            (bad_dir / f"{name}.json").write_text("{}", encoding="utf-8")
        bad = validate_platform_contracts("bad", bad_dir, root / "bad")
        assert not bad["ok"], bad
        assert any(item["errors"] for item in bad["checks"]), bad
        mirror_dir = root / "targets"
        mirror_dir.mkdir()
        (mirror_dir / "demo.json").write_text('{"name":"different"}', encoding="utf-8")
        assert not target_mirror_status({"name": "demo"}, mirror_dir)["ok"]
        manifest = root / "manifest.json"
        manifest.write_text('{"group":[{"name":"sdk","revision":"abc"}]}', encoding="utf-8")
        assert source_revision_status({"_provenance": {"source_revisions": {"sdk": "abc"}}}, manifest)["ok"]
        assert not source_revision_status({"_provenance": {"source_revisions": {"sdk": "def"}}}, manifest)["ok"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default="canaan_k230")
    parser.add_argument("--platform-dir")
    parser.add_argument("--out", default=str(ROOT / "build/contract_schema_gate"))
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    platform_dir = Path(args.platform_dir).resolve() if args.platform_dir else ROOT / "platforms" / args.platform
    report = validate_platform_contracts(args.platform, platform_dir, Path(args.out).resolve())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

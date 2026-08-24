"""Boot component manifest packing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def toc_manifest_parse_pass(required: list[str], components: dict[str, Path]) -> bool:
    if "toc_manifest" not in required:
        return True
    path = components.get("toc_manifest")
    if not path or not path.exists():
        return False
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def pack(contract_path: Path, out: Path, components: dict[str, Path]) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    contract = load(contract_path)
    required = list(contract.get("required_components", []))
    missing = [name for name in required if name not in components or not components[name].exists()]
    component_report = {
        name: {"path": str(path), "present": path.exists(), "sha256": sha256(path) if path.exists() else ""}
        for name, path in sorted(components.items())
    }
    toc_ok = toc_manifest_parse_pass(required, components)
    blockers = ["missing boot components: " + ", ".join(missing)] if missing else []
    if not toc_ok:
        blockers.append("toc_manifest parse evidence is missing")
    manifest = {
        "schema": "adam.boot_manifest.v1",
        "contract": str(contract_path),
        "components": component_report,
        "self_hosted_boot_chain": not blockers,
        "blockers": blockers,
        "not_claimed": contract.get("not_claimed", []),
    }
    evidence = {
        "component_files_present": not missing,
        "component_hashes_recorded": not missing and all(item["sha256"] for item in component_report.values()),
        "toc_manifest_parse_pass": toc_ok,
        "self_hosted_boot_chain_declared": not blockers,
        "boot_layout_pass": not blockers and not missing and all(item["sha256"] for item in component_report.values()),
    }
    report = {"ok": not blockers, "manifest": str(out / "boot_manifest.json"), "evidence": evidence, **manifest}
    (out / "boot_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "boot_manifest_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report

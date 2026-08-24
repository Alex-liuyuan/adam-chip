"""Normalize virtual-board simulation evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify(reports: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = {
        "sim_report_present": bool(reports),
        "virtual_execution_pass": all(bool(item.get("ok")) for item in reports) if reports else False,
        "board_evidence_claimed": any(bool(item.get("product_ready") or item.get("board_verified")) for item in reports),
    }
    blockers = []
    if not evidence["sim_report_present"]:
        blockers.append("simulation report is missing")
    if not evidence["virtual_execution_pass"]:
        blockers.append("one or more simulation reports failed")
    if evidence["board_evidence_claimed"]:
        blockers.append("simulation reports must not claim physical board evidence")
    return {
        "ok": evidence["sim_report_present"] and evidence["virtual_execution_pass"] and not evidence["board_evidence_claimed"],
        "evidence_level": "E4_virtual" if evidence["virtual_execution_pass"] else "E0",
        "evidence": evidence,
        "blockers": blockers,
        "not_claimed": ["QEMU/Renode evidence is virtual; it is not E5 physical-board evidence"],
    }


def verify_files(paths: list[Path]) -> dict[str, Any]:
    return verify([load(path) for path in paths])


#!/usr/bin/env python3
"""Check whether a project order has enough authoritative input for its requested evidence level."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.project import load as load_project, resolve
from tools.target_contract_validate import validate_shape


LEVELS = {f"E{index}": index for index in range(1, 7)}


def _present_hardware(project: dict[str, Any]) -> set[str]:
    return {kind for kind, values in project.get("hardware_inputs", {}).items() if values}


def analyze(project_path: Path, out: Path) -> dict[str, Any]:
    project = load_project(project_path)
    target_path = resolve(project["target"])
    target = json.loads(target_path.read_text(encoding="utf-8"))
    level = LEVELS[project["required_evidence_level"]]
    features = set(map(str, project.get("features", [])))
    hardware = _present_hardware(project)
    provenance = target.get("_provenance", {}) if isinstance(target.get("_provenance"), dict) else {}
    semantic_errors, semantic_warnings = validate_shape(target)

    requirements = [
        {"id": "target_contract", "level": "E1", "ready": not semantic_errors, "missing": semantic_errors},
        {
            "id": "authoritative_hardware_source",
            "level": "E2",
            "ready": bool(hardware & {"trm", "svd", "dts", "cmsis_pack"}) or bool(provenance.get("sources")),
            "missing": ["provide a TRM/SVD/DTS/CMSIS pack or target._provenance.sources"],
        },
        {
            "id": "source_revisions",
            "level": "E2",
            "ready": bool(provenance.get("source_revisions")),
            "missing": ["record pinned source revisions in target._provenance.source_revisions"],
        },
        {
            "id": "physical_lab",
            "level": "E5",
            "ready": bool(project.get("lab_config")) and resolve(str(project.get("lab_config"))).is_file(),
            "missing": ["provide an existing lab_config for flash/reset/serial HIL"],
        },
        {
            "id": "board_schematic",
            "level": "E5",
            "ready": "schematic" in hardware,
            "missing": ["provide the board schematic for physical-board claims"],
        },
        {
            "id": "custom_models",
            "level": "E3",
            "ready": "custom_model" not in features or bool(project.get("models")),
            "missing": ["features includes custom_model but project models[] is empty"],
        },
        {
            "id": "stress_budget",
            "level": "E6",
            "ready": int(project.get("budgets", {}).get("board_runs", 0)) > 0,
            "missing": ["set budgets.board_runs for E6 stress evidence"],
        },
    ]
    for item in requirements:
        item["required_now"] = LEVELS[item["level"]] <= level
    blockers = [message for item in requirements if item["required_now"] and not item["ready"] for message in item["missing"]]
    future_gaps = [message for item in requirements if not item["required_now"] and not item["ready"] for message in item["missing"]]
    report = {
        "schema": "adam.project_input_readiness.v1",
        "ok": not blockers,
        "project_id": project["project_id"],
        "required_evidence_level": project["required_evidence_level"],
        "features": sorted(features),
        "target": str(target_path),
        "requirements": requirements,
        "blockers": blockers,
        "future_gaps": future_gaps,
        "warnings": semantic_warnings,
        "evidence": {
            "project_input_gate_pass": not blockers,
            "missing_inputs_recorded": True,
            "hardware_sources_present": requirements[1]["ready"],
            "product_requirements_declared": bool(features),
        },
        "not_claimed": ["input readiness is not build, flash, boot, or physical-board evidence"],
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "input_readiness_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "missing_inputs.json").write_text(json.dumps({"blockers": blockers, "future_gaps": future_gaps}, indent=2) + "\n", encoding="utf-8")
    return report


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        base = json.loads((ROOT / "projects/k230_sdk_project.json").read_text(encoding="utf-8"))
        project = root / "project.json"
        project.write_text(json.dumps(base), encoding="utf-8")
        assert analyze(project, root / "e2")["ok"]
        base["required_evidence_level"] = "E5"
        project.write_text(json.dumps(base), encoding="utf-8")
        blocked = analyze(project, root / "e5")
        assert not blocked["ok"]
        assert any("lab_config" in item for item in blocked["blockers"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project")
    parser.add_argument("--out", default=str(ROOT / "build/project_input_gate"))
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    if not args.project:
        parser.error("--project is required unless --selftest is used")
    report = analyze(Path(args.project).resolve(), Path(args.out).resolve())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

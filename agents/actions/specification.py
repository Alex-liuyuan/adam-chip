"""Executable SpecificationAgent workflow."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from agents.catalog import load_catalog
from agents.executor import ActionInvocation, execute
from agents.handoff import create as create_handoff
from agents.project import ROOT, load as load_project, resolve


PYTHON = sys.executable
AGENT = "SpecificationAgent"
IMPORTERS = {
    "svd": ("ImportSvd", "importers/svd_importer.py"),
    "dts": ("ImportDts", "importers/dts_importer.py"),
    "cmsis_pack": ("ImportCmsisPack", "importers/cmsis_pack_importer.py"),
    "platformio": ("ImportPlatformIo", "importers/platformio_importer.py"),
}


def _run(project: dict[str, Any], action: str, commands: list[list[str]], inputs: list[Path], target: Path, out: Path) -> dict[str, Any]:
    role = load_catalog()[AGENT]
    return execute(
        ActionInvocation(
            project_id=project["project_id"],
            agent=AGENT,
            action=action,
            commands=tuple(tuple(item) for item in commands),
            inputs=tuple(inputs),
            target=target,
            out=out,
            allowed_paths=tuple(role["owned_paths"]),
        )
    )


def run(project_path: Path, out: Path, handoffs: tuple[Path, ...] = ()) -> dict[str, Any]:
    del handoffs
    project = load_project(project_path)
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = resolve(project["target"])
    hardware = project.get("hardware_inputs", {})
    results = []
    skipped = []
    drafts: list[Path] = [target]

    documents = [resolve(value) for key in ("trm", "schematic") for value in hardware.get(key, [])]
    if documents:
        action_out = out / "01_hardware_documents"
        command = [PYTHON, "tools/hardware_document_import.py", "--out", str(action_out)]
        for source in documents:
            command.extend(["--input", str(source)])
        results.append(_run(project, "IngestHardwareDocuments", [command], [*documents, target], target, action_out))
        if not results[-1]["handoff_ready"]:
            return _finish(project, target, out, results, skipped)
    else:
        skipped.append({"action": "IngestHardwareDocuments", "reason": "no TRM or schematic supplied"})

    index = 2
    for kind, (action, tool) in IMPORTERS.items():
        sources = [resolve(value) for value in hardware.get(kind, [])]
        if not sources:
            skipped.append({"action": action, "reason": f"no {kind} input supplied"})
            continue
        for source_index, source in enumerate(sources, 1):
            action_out = out / f"{index:02d}_{kind}_{source_index}"
            result = _run(project, action, [[PYTHON, tool, "--in", str(source), "--out", str(action_out)]], [source, target], target, action_out)
            results.append(result)
            if not result["handoff_ready"]:
                return _finish(project, target, out, results, skipped)
            drafts.append(action_out / "target.draft.json")
            index += 1

    merge_out = out / f"{index:02d}_merge"
    results.append(_run(project, "MergeContract", [[PYTHON, "importers/merge_contract.py", "--inputs", *map(str, drafts), "--out", str(merge_out)]], drafts, target, merge_out))
    if not results[-1]["handoff_ready"]:
        return _finish(project, target, out, results, skipped)

    validate_out = out / f"{index + 1:02d}_validate"
    results.append(
        _run(
            project,
            "ValidatePlatformContract",
            [[PYTHON, "tools/contract_schema_gate.py", "--platform", project["platform"], "--out", str(validate_out)]],
            [target, *sorted((ROOT / "platforms" / project["platform"]).glob("*.json"))],
            target,
            validate_out,
        )
    )
    if not results[-1]["handoff_ready"]:
        return _finish(project, target, out, results, skipped)

    readiness_out = out / f"{index + 2:02d}_input_readiness"
    results.append(
        _run(
            project,
            "CheckInputReadiness",
            [[PYTHON, "tools/project_input_gate.py", "--project", str(project_path.resolve()), "--out", str(readiness_out)]],
            [project_path.resolve(), target, Path(results[-1]["result_path"])],
            target,
            readiness_out,
        )
    )
    return _finish(project, target, out, results, skipped)


def _finish(project: dict[str, Any], target: Path, out: Path, results: list[dict[str, Any]], skipped: list[dict[str, str]]) -> dict[str, Any]:
    role = load_catalog()[AGENT]
    handoffs = []
    for result in results:
        if not result["handoff_ready"]:
            continue
        result_path = Path(result["result_path"])
        handoff_path = out / "handoffs" / f"{result['action']}.json"
        create_handoff(result_path, tuple(role["handoff_to"]), handoff_path)
        handoffs.append(str(handoff_path))
    report = {
        "schema": "adam.specification_workflow.v1",
        "project_id": project["project_id"],
        "agent": AGENT,
        "target": str(target),
        "ok": bool(results) and all(item["handoff_ready"] for item in results),
        "actions": [{"action": item["action"], "status": item["status"], "result": item["result_path"], "gate_errors": item["gate_errors"]} for item in results],
        "skipped": skipped,
        "handoffs": handoffs,
        "not_claimed": ["specification evidence is not build, simulation, flash, boot, or physical-board evidence"],
    }
    (out / "specification_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report

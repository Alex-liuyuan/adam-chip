"""Executable DriverAgent workflow."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from agents.artifacts import sha256
from agents.catalog import load_catalog
from agents.executor import ActionInvocation, execute
from agents.handoff import create as create_handoff
from agents.handoff import validate as validate_handoff
from agents.project import load as load_project, resolve


AGENT = "DriverAgent"
PYTHON = sys.executable


def _authorize(project: dict[str, Any], target: Path, handoffs: tuple[Path, ...]) -> list[str]:
    required = {("SpecificationAgent", "ValidatePlatformContract"), ("BspBootAgent", "BuildRtThreadBsp")}
    accepted = set()
    errors = []
    for path in handoffs:
        checked = validate_handoff(path, recipient=AGENT, project_id=project["project_id"], target_hash=sha256(target))
        if not checked["ok"]:
            errors.extend(checked["errors"])
            continue
        item = json.loads(path.read_text(encoding="utf-8"))
        accepted.add((item["from_agent"], item["action"]))
    errors.extend(f"missing required handoff: {agent}.{action}" for agent, action in sorted(required - accepted))
    return errors


def _run(project: dict[str, Any], action: str, command: list[str], inputs: list[Path], target: Path, out: Path, patterns: tuple[str, ...]) -> dict[str, Any]:
    role = load_catalog()[AGENT]
    return execute(ActionInvocation(project_id=project["project_id"], agent=AGENT, action=action, commands=(tuple(command),), inputs=tuple(inputs), target=target, out=out, allowed_paths=tuple(role["owned_paths"]), timeout_seconds=1800, artifact_patterns=patterns))


def run(project_path: Path, out: Path, handoffs: tuple[Path, ...] = ()) -> dict[str, Any]:
    project = load_project(project_path)
    target = resolve(project["target"])
    incoming = tuple(path.resolve() for path in handoffs)
    errors = _authorize(project, target, incoming)
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if errors:
        report = {"schema": "adam.driver_workflow.v1", "project_id": project["project_id"], "agent": AGENT, "ok": False, "status": "blocked", "blockers": errors, "actions": [], "handoffs": []}
        (out / "driver_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report

    results = []
    register = out / "01_register_ir"
    results.append(_run(project, "BuildRegisterIr", [PYTHON, "tools/driver_adapt.py", "register-ir", str(target), "--out", str(register)], [target, *incoming], target, register, ("**/*.json", "**/*.h", "command_*.log")))
    if results[-1]["handoff_ready"]:
        reuse = out / "02_reuse"
        results.append(_run(project, "RetrieveReferenceDrivers", [PYTHON, "tools/github_driver_reuse.py", str(target), "--out", str(reuse), "--repo-limit", "0"], [target, Path(results[-1]["result_path"])], target, reuse, ("driver_reuse_index.json", ".fetched", "command_*.log")))
    if results[-1]["handoff_ready"]:
        generated_root = out / "03_generate"
        results.append(_run(project, "GenerateDrivers", [PYTHON, "tools/driver_adapt.py", "generate", str(target), "--out", str(generated_root)], [target, Path(results[-1]["result_path"])], target, generated_root, ("**/*.json", "**/*.h", "**/*.c", "command_*.log")))
    if results[-1]["handoff_ready"]:
        artifact = out / "03_generate" / json.loads(target.read_text(encoding="utf-8"))["name"]
        verify_out = out / "04_verify"
        verify_out.mkdir(exist_ok=True)
        results.append(_run(project, "VerifyDrivers", [PYTHON, "tools/driver_adapt.py", "verify", str(artifact), "--report-out", str(verify_out / "driver_verification_report.json")], [target, artifact / "driver_ir.json", Path(results[-1]["result_path"])], target, verify_out, ("*.json", "command_*.log")))
    return _finish(project, out, results)


def _finish(project: dict[str, Any], out: Path, results: list[dict[str, Any]]) -> dict[str, Any]:
    role = load_catalog()[AGENT]
    handoffs = []
    for result in results:
        if result["handoff_ready"]:
            path = out / "handoffs" / f"{result['action']}.json"
            create_handoff(Path(result["result_path"]), tuple(role["handoff_to"]), path)
            handoffs.append(str(path))
    ok = len(results) == 4 and all(item["handoff_ready"] for item in results)
    report = {"schema": "adam.driver_workflow.v1", "project_id": project["project_id"], "agent": AGENT, "ok": ok, "status": "passed" if ok else "failed", "actions": [{"action": item["action"], "status": item["status"], "result": item["result_path"], "gate_errors": item["gate_errors"]} for item in results], "handoffs": handoffs, "not_claimed": ["generated NPU driver is not production-ready while reset and command ABI remain unresolved", "driver tests are host/static evidence, not physical IRQ or DMA evidence"]}
    (out / "driver_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report

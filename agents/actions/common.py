"""Shared mechanics for executable engineering Agent workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents.artifacts import sha256
from agents.catalog import load_catalog
from agents.executor import ActionInvocation, execute
from agents.handoff import create as create_handoff
from agents.handoff import validate as validate_handoff


def authorize(project: dict[str, Any], target: Path, agent: str, handoffs: tuple[Path, ...], required: set[tuple[str, str]]) -> list[str]:
    accepted = set()
    errors = []
    for path in handoffs:
        checked = validate_handoff(path, recipient=agent, project_id=project["project_id"], target_hash=sha256(target))
        if not checked["ok"]:
            errors.extend(checked["errors"])
            continue
        item = json.loads(path.read_text(encoding="utf-8"))
        accepted.add((item["from_agent"], item["action"]))
    errors.extend(f"missing required handoff: {owner}.{action}" for owner, action in sorted(required - accepted))
    return errors


def run_action(project: dict[str, Any], agent: str, action: str, command: list[str], inputs: list[Path], target: Path, out: Path, patterns: tuple[str, ...] = ("**/*",)) -> dict[str, Any]:
    role = load_catalog()[agent]
    return execute(
        ActionInvocation(
            project_id=project["project_id"],
            agent=agent,
            action=action,
            commands=(tuple(command),),
            inputs=tuple(inputs),
            target=target,
            out=out,
            allowed_paths=tuple(role["owned_paths"]),
            timeout_seconds=1800,
            artifact_patterns=patterns,
        )
    )


def blocked(project: dict[str, Any], agent: str, out: Path, blockers: list[str]) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    report = {"schema": "adam.agent_workflow.v1", "project_id": project["project_id"], "agent": agent, "ok": False, "status": "blocked", "blockers": blockers, "actions": [], "handoffs": []}
    (out / "workflow_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def finish(project: dict[str, Any], agent: str, out: Path, results: list[dict[str, Any]], expected_actions: int, not_claimed: list[str] | None = None) -> dict[str, Any]:
    role = load_catalog()[agent]
    handoffs = []
    for result in results:
        if result["handoff_ready"]:
            path = out / "handoffs" / f"{result['action']}.json"
            create_handoff(Path(result["result_path"]), tuple(role["handoff_to"]), path)
            handoffs.append(str(path))
    ok = len(results) == expected_actions and all(item["handoff_ready"] for item in results)
    report = {
        "schema": "adam.agent_workflow.v1",
        "project_id": project["project_id"],
        "agent": agent,
        "ok": ok,
        "status": "passed" if ok else "failed",
        "actions": [{"action": item["action"], "status": item["status"], "result": item["result_path"], "gate_errors": item["gate_errors"]} for item in results],
        "handoffs": handoffs,
        "not_claimed": not_claimed or [],
    }
    (out / "workflow_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def package_from_handoffs(handoffs: tuple[Path, ...]) -> Path | None:
    for handoff in handoffs:
        data = json.loads(handoff.read_text(encoding="utf-8"))
        for artifact in data.get("artifacts", []):
            path = Path(artifact["path"])
            if path.name == "aec.json" and path.parent.name == "contracts" and path.is_file():
                return path.parent.parent
            if path.name == "package_reference.json" and path.is_file():
                reference = json.loads(path.read_text(encoding="utf-8"))
                package = Path(reference.get("package", ""))
                aec = package / "contracts/aec.json"
                if aec.is_file() and reference.get("aec_sha256") == sha256(aec):
                    return package
    return None


def artifact_from_handoffs(handoffs: tuple[Path, ...], name: str) -> Path | None:
    for handoff in handoffs:
        data = json.loads(handoff.read_text(encoding="utf-8"))
        for artifact in data.get("artifacts", []):
            path = Path(artifact["path"])
            if path.name == name and path.is_file() and artifact.get("sha256") == sha256(path):
                return path
    return None

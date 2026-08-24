#!/usr/bin/env python3
"""Run one typed agent action with deterministic provenance."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.artifacts import collect, describe
from agents.catalog import load_catalog
from agents.failure import classify, owner
from agents.gates import evaluate_action_result


RESULT_NAME = "action_result.json"
RESULT_SCHEMA = ROOT / "schemas" / "action_result.schema.json"


@dataclass(frozen=True)
class ActionInvocation:
    project_id: str
    agent: str
    action: str
    commands: tuple[tuple[str, ...], ...]
    inputs: tuple[Path, ...]
    target: Path
    out: Path
    allowed_paths: tuple[str, ...]
    required_evidence: tuple[str, ...] = ()
    timeout_seconds: float = 900.0
    artifact_patterns: tuple[str, ...] = ("**/*",)


def _action(role: dict[str, Any], action_id: str) -> dict[str, Any]:
    for action in role["actions"]:
        if action["id"] == action_id:
            return action
    raise ValueError(f"{role['name']} does not own action {action_id}")


def _workspace_state() -> dict[str, str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", "chip"],
        cwd=ROOT.parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    state = {}
    for line in proc.stdout.splitlines():
        relative = line[3:].split(" -> ")[-1]
        if not relative.startswith("chip/"):
            continue
        relative = relative[5:]
        path = ROOT / relative
        state[relative] = describe(path)["sha256"] if path.is_file() else "deleted"
    return state


def _changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def _within(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)


def _validate_invocation(invocation: ActionInvocation, role: dict[str, Any]) -> list[str]:
    blockers = []
    if not invocation.project_id:
        blockers.append("project_id is required")
    if not invocation.commands:
        blockers.append("at least one command is required")
    if invocation.timeout_seconds <= 0:
        blockers.append("timeout_seconds must be positive")
    for path in invocation.inputs:
        if not path.is_file():
            blockers.append(f"input artifact is missing: {path}")
    if not invocation.target.is_file():
        blockers.append(f"target contract is missing: {invocation.target}")
    for prefix in invocation.allowed_paths:
        if not _within(prefix, tuple(role["owned_paths"])):
            blockers.append(f"path is outside {invocation.agent} ownership: {prefix}")
    return blockers


def _report_evidence(out: Path) -> list[str]:
    names = []
    for path in out.rglob("*.json"):
        if path.name == RESULT_NAME:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("evidence", {}), dict):
            continue
        for name, value in data.get("evidence", {}).items():
            if value:
                names.append(str(name))
    return list(dict.fromkeys(names))


def execute(invocation: ActionInvocation) -> dict[str, Any]:
    catalog = load_catalog()
    if invocation.agent not in catalog:
        raise ValueError(f"unknown agent: {invocation.agent}")
    role = catalog[invocation.agent]
    action = _action(role, invocation.action)
    out = invocation.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    inputs = [describe(path) for path in invocation.inputs if path.is_file()]
    target_hash = describe(invocation.target)["sha256"] if invocation.target.is_file() else None
    report: dict[str, Any] = {
        "schema": "adam.action_result.v1",
        "run_id": run_id,
        "project_id": invocation.project_id,
        "agent": invocation.agent,
        "action": invocation.action,
        "target_hash": target_hash,
        "status": "blocked",
        "commands": [],
        "inputs": inputs,
        "artifacts": [],
        "evidence": {},
        "evidence_level": "E0",
        "gate_errors": [],
        "missing_evidence": list(invocation.required_evidence),
        "failure_class": None,
        "blockers": [],
        "handoff_ready": False,
        "tool": action["tool"],
        "third_party": action["third_party"],
        "result_path": str(out / RESULT_NAME),
    }
    blockers = _validate_invocation(invocation, role)
    if blockers:
        report["blockers"] = blockers
        _write_result(out, report)
        return report

    before = _workspace_state()
    logs = []
    failure_class = None
    for index, command in enumerate(invocation.commands, 1):
        started = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(
                list(command),
                cwd=ROOT,
                env={**os.environ, "ADAM_RUN_ID": run_id},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=invocation.timeout_seconds,
                check=False,
            )
            output = proc.stdout
            returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:
            output = str(exc.stdout or "") + str(exc.stderr or "")
            returncode = None
            timed_out = True
        log = out / f"command_{index}.log"
        log.write_text(output, encoding="utf-8")
        logs.append(log)
        report["commands"].append(
            {
                "argv": list(command),
                "returncode": returncode,
                "timed_out": timed_out,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "log": str(log),
            }
        )
        failure_class = classify(returncode, output, timed_out=timed_out)
        if failure_class:
            break

    after = _workspace_state()
    changed = _changed(before, after)
    unauthorized = [path for path in changed if not _within(path, invocation.allowed_paths)]
    if unauthorized:
        failure_class = "workspace_policy_violation"
        report["blockers"].extend(f"unauthorized workspace change: {path}" for path in unauthorized)
    evidence_names = _report_evidence(out)
    evidence = {name: True for name in evidence_names}
    evidence.update(
        {
            "tool_exit_pass": failure_class is None,
            "input_hashes_recorded": len(inputs) == len(invocation.inputs),
            "artifact_hashes_recorded": True,
            "workspace_policy_pass": not unauthorized,
        }
    )
    required_evidence = tuple(dict.fromkeys([*action["evidence"], *invocation.required_evidence]))
    missing_evidence = [name for name in required_evidence if not evidence.get(name)]
    if missing_evidence and failure_class is None:
        failure_class = "tool_failure"
    artifacts = collect(out, patterns=invocation.artifact_patterns, exclude=(RESULT_NAME,))
    evidence["artifact_hashes_recorded"] = bool(artifacts)
    if not artifacts and failure_class is None:
        failure_class = "tool_failure"
        report["blockers"].append("action produced no auditable artifact")
    report.update(
        status="passed" if failure_class is None else "failed",
        artifacts=artifacts,
        evidence=evidence,
        missing_evidence=missing_evidence,
        failure_class=failure_class,
        failure_owner=owner(failure_class, invocation.agent) if failure_class else None,
        changed_files=changed,
        handoff_ready=False,
    )
    gate = evaluate_action_result(report, required_evidence)
    if not gate["ok"] and failure_class is None:
        failure_class = "evidence_gate_failure"
        report["status"] = "failed"
        report["failure_class"] = failure_class
        report["failure_owner"] = owner(failure_class, invocation.agent)
    report["evidence_level"] = gate["evidence_level"]
    report["gate_errors"] = gate["errors"]
    report["handoff_ready"] = gate["ok"]
    _write_result(out, report)
    return report


def _write_result(out: Path, report: dict[str, Any]) -> None:
    schema = json.loads(RESULT_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)
    (out / RESULT_NAME).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _self_test() -> None:
    catalog = load_catalog()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "input.json"
        source.write_text("{}\n", encoding="utf-8")
        out = root / "run"
        command = (
            sys.executable,
            "-c",
            "import json; from pathlib import Path; Path(r'%s').write_text('artifact'); Path(r'%s').write_text(json.dumps({'evidence': {'svd_import_pass': True}}))" % (out / "artifact.bin", out / "tool_report.json"),
        )
        invocation = ActionInvocation(
            project_id="executor-selftest",
            agent="SpecificationAgent",
            action="ImportSvd",
            commands=(command,),
            inputs=(source,),
            target=source,
            out=out,
            allowed_paths=tuple(catalog["SpecificationAgent"]["owned_paths"]),
        )
        report = execute(invocation)
        assert report["status"] == "passed", report
        assert report["evidence"]["artifact_hashes_recorded"]
        assert report["handoff_ready"] is True
        blocked = execute(
            ActionInvocation(
                project_id="executor-selftest",
                agent="SpecificationAgent",
                action="ImportSvd",
                commands=(command,),
                inputs=(root / "missing",),
                target=root / "missing-target",
                out=root / "blocked",
                allowed_paths=("boot",),
            )
        )
        assert blocked["status"] == "blocked"
    assert classify(1, "undefined reference to symbol") == "link_failure"
    assert classify(None, "", timed_out=True) == "tool_timeout"


if __name__ == "__main__":
    _self_test()
    print("ok")

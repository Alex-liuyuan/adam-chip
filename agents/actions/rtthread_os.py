"""Executable RtThreadOsAgent workflow."""

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
from agents.project import ROOT, load as load_project, resolve


AGENT = "RtThreadOsAgent"
PYTHON = sys.executable


def _run(project: dict[str, Any], action: str, command: list[str], inputs: list[Path], target: Path, out: Path, patterns: tuple[str, ...]) -> dict[str, Any]:
    role = load_catalog()[AGENT]
    return execute(ActionInvocation(project_id=project["project_id"], agent=AGENT, action=action, commands=(tuple(command),), inputs=tuple(inputs), target=target, out=out, allowed_paths=tuple(role["owned_paths"]), timeout_seconds=1800, artifact_patterns=patterns))


def run(project_path: Path, out: Path, handoffs: tuple[Path, ...] = ()) -> dict[str, Any]:
    project = load_project(project_path)
    target = resolve(project["target"])
    incoming = tuple(path.resolve() for path in handoffs)
    accepted = False
    errors = []
    for path in incoming:
        checked = validate_handoff(path, recipient=AGENT, project_id=project["project_id"], target_hash=sha256(target))
        if checked["ok"]:
            item = json.loads(path.read_text(encoding="utf-8"))
            accepted |= item["from_agent"] == "BspBootAgent" and item["action"] == "BuildRtThreadBsp"
        else:
            errors.extend(checked["errors"])
    if not accepted:
        errors.append("a valid BspBootAgent BuildRtThreadBsp handoff is required")
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if errors:
        report = {"schema": "adam.rtthread_os_workflow.v1", "project_id": project["project_id"], "agent": AGENT, "ok": False, "status": "blocked", "blockers": errors, "actions": [], "handoffs": []}
        (out / "rtthread_os_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report

    bsp = ROOT / "third_party/k230-sdk/src/big/rt-smart/kernel/bsp/maix3"
    runtime = ROOT / "sdk/packages/rvaic"
    prefix = ROOT / "third_party/k230-toolchain/riscv64-linux-musleabi_for_x86_64-pc-linux-gnu/bin/riscv64-unknown-linux-musl-"
    results = []
    config = out / "01_config"
    results.append(_run(project, "ConfigureRtThread", [PYTHON, "tools/rtthread_config_check.py", "--config", str(bsp / "rtconfig.h"), "--out", str(config)], [target, *incoming], target, config, ("*.json", "command_*.log")))
    if results[-1]["handoff_ready"]:
        component = out / "02_component"
        results.append(_run(project, "IntegrateAiService", [PYTHON, "tools/rtthread_rvaic_package_build.py", "--runtime-only", "--bsp", str(bsp), "--runtime", str(runtime), "--cross-prefix", str(prefix), "--scons", str(ROOT / ".venv/bin/scons"), "--out", str(component)], [target, runtime / "SConscript", Path(results[-1]["result_path"])], target, component, ("*.json", "*.log", "bsp_overlay/rtthread.elf")))
    if results[-1]["handoff_ready"]:
        primitives = out / "03_primitives"
        primitives.mkdir(exist_ok=True)
        results.append(_run(project, "TestOsPrimitives", [PYTHON, "tools/rvaic_rtthread_native_check.py", "--runtime-dir", str(runtime), "--out", str(primitives / "queue_timer_heap_report.json")], [target, runtime / "include/rvaic.h", Path(results[-1]["result_path"])], target, primitives, ("*.json", "command_*.log")))
    if results[-1]["handoff_ready"]:
        virtual = out / "04_virtual"
        results.append(_run(project, "RunVirtualFirmware", [PYTHON, "tools/rtthread_virtual_portability.py", "--out", str(virtual)], [target, Path(results[-1]["result_path"])], target, virtual, ("*.json", "command_*.log")))
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
    report = {"schema": "adam.rtthread_os_workflow.v1", "project_id": project["project_id"], "agent": AGENT, "ok": ok, "status": "passed" if ok else "failed", "actions": [{"action": item["action"], "status": item["status"], "result": item["result_path"], "gate_errors": item["gate_errors"]} for item in results], "handoffs": handoffs, "not_claimed": ["FE310 Renode evidence proves generic RT-Thread portability, not K230 simulation or physical boot"]}
    (out / "rtthread_os_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report

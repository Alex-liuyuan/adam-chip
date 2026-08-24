"""Executable BspBootAgent workflow."""

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


PYTHON = sys.executable
AGENT = "BspBootAgent"


def _blocked(project: dict[str, Any], out: Path, blockers: list[str]) -> dict[str, Any]:
    report = {"schema": "adam.bsp_boot_workflow.v1", "project_id": project["project_id"], "agent": AGENT, "ok": False, "status": "blocked", "blockers": blockers, "actions": [], "handoffs": []}
    out.mkdir(parents=True, exist_ok=True)
    (out / "bsp_boot_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _authorize(project: dict[str, Any], target: Path, handoffs: tuple[Path, ...]) -> list[str]:
    errors = []
    accepted = False
    for path in handoffs:
        result = validate_handoff(path, recipient=AGENT, project_id=project["project_id"], target_hash=sha256(target), required_evidence=("schema_valid", "contract_conflicts_checked"))
        if not result["ok"]:
            errors.extend(result["errors"])
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest["from_agent"] == "SpecificationAgent" and manifest["action"] == "ValidatePlatformContract":
            accepted = True
    if not accepted:
        errors.append("a valid SpecificationAgent ValidatePlatformContract handoff is required")
    return errors


def _run(project: dict[str, Any], action: str, command: list[str], inputs: list[Path], target: Path, out: Path, patterns: tuple[str, ...]) -> dict[str, Any]:
    role = load_catalog()[AGENT]
    return execute(ActionInvocation(project_id=project["project_id"], agent=AGENT, action=action, commands=(tuple(command),), inputs=tuple(inputs), target=target, out=out, allowed_paths=tuple(role["owned_paths"]), timeout_seconds=1800, artifact_patterns=patterns))


def run(project_path: Path, out: Path, handoffs: tuple[Path, ...] = ()) -> dict[str, Any]:
    project = load_project(project_path)
    out = out.resolve()
    target = resolve(project["target"])
    incoming = tuple(path.resolve() for path in handoffs)
    errors = _authorize(project, target, incoming)
    if errors:
        return _blocked(project, out, errors)
    results = []
    boot_contract = ROOT / "platforms" / project["platform"] / "boot.json"

    toolchain_out = out / "01_toolchain"
    results.append(_run(project, "FreezeToolchain", [PYTHON, "tools/toolchain_freeze.py", "--platform", project["platform"], "--target", str(target), "--boot-contract", str(boot_contract), "--out", str(toolchain_out)], [target, boot_contract, *incoming], target, toolchain_out, ("toolchain_report.json", "command_*.log")))
    if not results[-1]["handoff_ready"]:
        return _finish(project, out, results)
    toolchain = json.loads((toolchain_out / "toolchain_report.json").read_text(encoding="utf-8"))
    boot_prefix = toolchain["toolchains"]["boot"]["prefix"]
    bsp_prefix = toolchain["toolchains"]["bsp"]["prefix"]

    boot_out = out / "02_boot"
    results.append(_run(project, "BuildBootChain", [PYTHON, "tools/boot_build.py", "--platform", project["platform"], "--cross-prefix", boot_prefix, "--out", str(boot_out)], [target, boot_contract, Path(results[-1]["result_path"])], target, boot_out, ("boot_build_report.json", "*.log", "build/u-boot-spl-k230.bin", "build/fn_u-boot.img")))
    if not results[-1]["handoff_ready"]:
        return _finish(project, out, results)
    boot_report = json.loads((boot_out / "boot_build_report.json").read_text(encoding="utf-8"))

    bsp_out = out / "03_bsp"
    results.append(_run(project, "BuildRtThreadBsp", [PYTHON, "tools/bsp_build.py", "--platform", project["platform"], "--toolchain-bin", str(Path(bsp_prefix).parent), "--out", str(bsp_out)], [target, Path(results[-1]["result_path"])], target, bsp_out, ("bsp_build_report.json", "*.log", "artifacts/*")))
    if not results[-1]["handoff_ready"]:
        return _finish(project, out, results)
    bsp_report = json.loads((bsp_out / "bsp_build_report.json").read_text(encoding="utf-8"))
    elf = Path(bsp_report["verification"]["artifacts"]["rtthread.elf"]["path"])
    map_file = Path(bsp_report["verification"]["artifacts"]["rtthread.map"]["path"])

    inspect_out = out / "04_elf"
    results.append(_run(project, "InspectFirmwareElf", [PYTHON, "tools/elf_inspect.py", "--platform", project["platform"], "--elf", str(elf), "--prefix", bsp_prefix, "--out", str(inspect_out)], [target, elf, map_file, Path(results[-1]["result_path"])], target, inspect_out, ("elf_inspection_report.json", "command_*.log")))
    if not results[-1]["handoff_ready"]:
        return _finish(project, out, results)

    artifacts = boot_report["verification"]["artifacts"]
    spl = Path(artifacts["spl"]["path"])
    uboot = Path(artifacts["uboot"]["path"])
    manifest_out = out / "05_boot_layout"
    results.append(_run(project, "VerifyBootLayout", [PYTHON, "tools/boot_manifest.py", "--contract", str(boot_contract), "--component", f"spl={spl}", "--component", f"uboot={uboot}", "--out", str(manifest_out)], [target, boot_contract, spl, uboot], target, manifest_out, ("*.json", "command_*.log")))
    return _finish(project, out, results)


def _finish(project: dict[str, Any], out: Path, results: list[dict[str, Any]]) -> dict[str, Any]:
    role = load_catalog()[AGENT]
    handoffs = []
    for result in results:
        if not result["handoff_ready"]:
            continue
        path = out / "handoffs" / f"{result['action']}.json"
        create_handoff(Path(result["result_path"]), tuple(role["handoff_to"]), path)
        handoffs.append(str(path))
    report = {
        "schema": "adam.bsp_boot_workflow.v1",
        "project_id": project["project_id"],
        "agent": AGENT,
        "ok": len(results) == 5 and all(item["handoff_ready"] for item in results),
        "status": "passed" if len(results) == 5 and all(item["handoff_ready"] for item in results) else "failed",
        "actions": [{"action": item["action"], "status": item["status"], "result": item["result_path"], "gate_errors": item["gate_errors"]} for item in results],
        "handoffs": handoffs,
        "not_claimed": ["boot and BSP build evidence is not physical flash or boot evidence"],
    }
    (out / "bsp_boot_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report

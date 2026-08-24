"""Bounded coding-agent execution for every engineering capability."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from engine.tools import ToolContext
from tools.llm_client import effective_config


ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = ROOT / "schemas/engineering_agent_report.schema.json"
ROLE_MISSIONS = {
    "HardwareAgent": "Resolve hardware contracts from cited material; preserve unknown and conflicting facts instead of guessing.",
    "SourceDiscoveryAgent": "Find the closest licensed upstream software stack, lock exact revisions, and prefer adaptation over reimplementation.",
    "SourceStackAgent": "Integrate a coherent pinned source stack and prove that every selected component is buildable and redistributable.",
    "BootBspAgent": "Adapt startup, linker, trap, OpenSBI, U-Boot and RT-Thread BSP code to the exact boot and memory contracts.",
    "DriverAgent": "Adapt register, clock, reset, pinmux, IRQ, DMA and device-model code from verified IP-compatible implementations.",
    "SimulationAgent": "Build executable MMIO and platform models with IRQ, DMA, timeout and reset fault injection.",
    "RtAiOsAgent": "Integrate asynchronous AI scheduling, memory ownership, deadlines and recovery into RT-Thread components.",
    "RuntimeAgent": "Implement the AEG loader, provider ABI, sessions, cancellation, cache/DMA handling and epoch-safe completion.",
    "CompilerAgent": "Implement and test the TVM Relax, S-TIR, RVV and accelerator backend against the target runtime ABI.",
    "CecapAirtosAgent": "Integrate compiler plans and RT-AI runtime policy without allowing runtime evidence to mutate deployed code.",
    "ProductAgent": "Integrate MicroPython, SYSU compatibility APIs and capability-specific reference applications into target firmware.",
    "ImageAgent": "Compose a reproducible source-built image with target layout, ancestry, unpack and rebuild verification.",
    "VerificationAgent": "Independently exercise simulation and physical HIL, attribute failures, and never upgrade missing evidence to pass.",
}


@dataclass(frozen=True)
class EngineeringRequest:
    context: ToolContext
    task: dict[str, Any]
    scaffold: dict[str, Any]
    failures: tuple[str, ...]
    round_number: int
    attempt_id: str
    report_dir: Path


def _prompt(request: EngineeringRequest) -> str:
    agent = request.task["agent"]
    mission = ROLE_MISSIONS[agent]
    worktree = request.context.worktree.resolve()
    run = next((path for path in (worktree, *worktree.parents) if (path / "materials").is_dir()), worktree.parent)
    payload = {
        "task": request.task,
        "hardware_ir": {key: value for key, value in request.context.hardware_ir.items() if key != "observations"},
        "locked_material_directory": str(run / "materials"),
        "reference_profile": request.context.reference_profile,
        "software_requirements": request.context.software_requirements,
        "source_policy_path": str(ROOT / "config/source_policy.json"),
        "source_policy_sha256": request.context.source_policy_sha256,
        "scaffold_result": request.scaffold,
        "previous_failures": list(request.failures),
    }
    return f"""You are the project-internal {agent}, acting as a real senior engineer rather than a role label.

Mission: {mission}

Work autonomously inside the current isolated Git worktree. Inspect the existing outputs, relevant project code under
{ROOT}, locked sources under {ROOT / 'third_party'}, and the task payload below. Reuse the closest compatible pinned
source and make the smallest target-specific adaptation. You may edit only the task provider owned_paths. Do not commit,
change Git metadata, modify the controller, or write outside the worktree. Run concrete build, inspection, simulation or
test commands appropriate to your role and record them in the report.

The deterministic generator result is only a scaffold. Review it as an engineer, correct it when the contracts and source
support a correction, and report a blocker when authoritative hardware facts, proprietary ABI, required source, toolchain
or physical equipment are absent. Never invent DDR training, BootROM formats, register semantics, accelerator command ABI,
signing material, physical test results or performance numbers. Reference-only sources may be studied but not copied into
production outputs. Record downstream capability blockers in the owned output; block this task only when its own required
output cannot be produced or verified. For HardwareAgent specifically, a provenance-bound summary that faithfully retains
unknown and conflicting facts is an implementation: unresolved facts must block their downstream capabilities, not the
summary task or source discovery. A second round must address only the listed deterministic failures.

Return exactly one JSON object matching {REPORT_SCHEMA}. Bind it to task_id={request.task['id']},
attempt_id={request.attempt_id}, agent={agent}, hardware_ir_sha256={request.task['hardware_ir_sha256']},
input_hash={request.task['input_hash']}, round={request.round_number}. Use status=implemented only after inspecting files and
running every locally available relevant check. Use status=blocked with specific blockers when safe implementation is not
possible.

Task payload:
{json.dumps(payload, indent=2, sort_keys=True)}
"""


def _validate_report(request: EngineeringRequest, report: Any) -> list[str]:
    if not isinstance(report, dict):
        return ["engineering Agent report is not an object"]
    schema = json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))
    errors = [error.message for error in sorted(Draft202012Validator(schema).iter_errors(report), key=lambda item: list(item.path))]
    expected = {
        "task_id": request.task["id"],
        "attempt_id": request.attempt_id,
        "agent": request.task["agent"],
        "hardware_ir_sha256": request.task["hardware_ir_sha256"],
        "input_hash": request.task["input_hash"],
        "round": request.round_number,
    }
    errors.extend(f"engineering Agent report binding mismatch: {name}" for name, value in expected.items() if report.get(name) != value)
    if report.get("status") == "implemented":
        if report.get("blockers"):
            errors.append("implemented engineering Agent report must not contain blockers")
        if not report.get("commands"):
            errors.append("implemented engineering Agent report must contain a command")
    elif report.get("status") == "blocked" and not report.get("blockers"):
        errors.append("blocked engineering Agent report must contain a blocker")
    return errors


def _process_failure(output: str, returncode: int) -> str:
    if "502 Bad Gateway" in output:
        return "engineering model service unavailable: 502 Bad Gateway"
    if "401 Unauthorized" in output or "authentication" in output.lower():
        return "engineering model authentication failed"
    return f"engineering Agent failed with exit code {returncode}"


def _responses_base_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1/chat/completions"):
        return base[: -len("/chat/completions")]
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return base if base.endswith("/v1") else base + "/v1"


def run_engineering_agent(request: EngineeringRequest) -> dict[str, Any]:
    executable = shutil.which("codex")
    if not executable:
        return {"ok": False, "status": "blocked", "errors": ["engineering Agent executable is unavailable"]}
    llm = effective_config()
    if llm["config_error"]:
        return {"ok": False, "status": "blocked", "errors": ["invalid project LLM configuration: " + llm["config_error"]]}
    if not llm["api_key"]:
        return {"ok": False, "status": "blocked", "errors": ["project LLM API key is unavailable"]}
    effort = os.environ.get("SOC_IMAGE_ENGINEER_REASONING_EFFORT", "high")
    if effort not in {"low", "medium", "high", "xhigh"}:
        return {"ok": False, "status": "blocked", "errors": ["invalid SOC_IMAGE_ENGINEER_REASONING_EFFORT"]}
    timeout_text = os.environ.get("SOC_IMAGE_ENGINEER_TIMEOUT_SECONDS", "900")
    if not timeout_text.isdigit() or not 60 <= int(timeout_text) <= 1800:
        return {"ok": False, "status": "blocked", "errors": ["SOC_IMAGE_ENGINEER_TIMEOUT_SECONDS must be 60 through 1800"]}

    request.report_dir.mkdir(parents=True, exist_ok=True)
    report_path = request.report_dir / f"engineering-round-{request.round_number}.json"
    log_path = request.report_dir / f"engineering-round-{request.round_number}.log"
    command = [
        executable,
        "exec",
        "--ignore-user-config",
        "--ephemeral",
        "--color",
        "never",
        "--config",
        'model_provider="chip"',
        "--config",
        "model=" + json.dumps(llm["model"]),
        "--config",
        "model_providers.chip={name=\"chip\",base_url="
        + json.dumps(_responses_base_url(str(llm["base_url"])))
        + ',env_key="SOC_IMAGE_LLM_API_KEY",wire_api="responses",requires_openai_auth=false}',
        "--config",
        f'model_reasoning_effort="{effort}"',
        "--sandbox",
        "workspace-write",
        "--output-schema",
        str(REPORT_SCHEMA),
        "--output-last-message",
        str(report_path),
        "--cd",
        str(request.context.worktree),
        "-",
    ]
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update({
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "SOC_IMAGE_LLM_API_KEY": llm["api_key"],
    })
    try:
        process = subprocess.run(
            command,
            cwd=request.context.worktree,
            env=environment,
            input=_prompt(request),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=int(timeout_text),
        )
    except subprocess.TimeoutExpired as exc:
        log_path.write_text((exc.stdout or "") if isinstance(exc.stdout, str) else "", encoding="utf-8")
        return {"ok": False, "status": "blocked", "errors": ["engineering Agent timed out"], "log": str(log_path)}
    log_path.write_text(process.stdout, encoding="utf-8")
    if process.returncode or not report_path.is_file():
        return {
            "ok": False,
            "status": "blocked",
            "errors": [_process_failure(process.stdout, process.returncode)],
            "log": str(log_path),
        }
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"ok": False, "status": "blocked", "errors": [f"engineering Agent report is invalid JSON: {exc}"], "log": str(log_path)}
    errors = _validate_report(request, report)
    return {
        "ok": not errors and report.get("status") == "implemented",
        "status": "blocked" if errors or report.get("status") == "blocked" else "implemented",
        "errors": errors,
        "report": report,
        "report_path": str(report_path),
        "log": str(log_path),
    }


def selftest() -> None:
    capabilities = json.loads((ROOT / "engine/capabilities.json").read_text(encoding="utf-8"))["capabilities"]
    assert {item["provider"]["agent"] for item in capabilities} <= set(ROLE_MISSIONS)
    context = ToolContext(
        worktree=ROOT,
        project_id="selftest",
        task_id="task:hardware_contract_summary",
        hardware_ir_sha256="a" * 64,
        hardware_ir={},
        outputs=("generated/control/summary.json",),
        reference_profile={},
        reference_profile_sha256="b" * 64,
        software_requirements={},
        software_requirements_sha256="c" * 64,
        source_policy={},
        source_policy_sha256="d" * 64,
        artifact_dir=ROOT,
    )
    task = {
        "id": context.task_id,
        "agent": "HardwareAgent",
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "input_hash": "e" * 64,
        "provider": {"owned_paths": ["generated/control"]},
    }
    request = EngineeringRequest(context, task, {}, (), 1, "f" * 32, ROOT)
    assert "unresolved facts must block their downstream capabilities" in _prompt(request)
    report = {
        "schema": "soc-image.engineering-agent-report.v1",
        "task_id": task["id"],
        "attempt_id": request.attempt_id,
        "agent": task["agent"],
        "hardware_ir_sha256": task["hardware_ir_sha256"],
        "input_hash": task["input_hash"],
        "round": 1,
        "status": "implemented",
        "summary": "inspected deterministic contract summary",
        "inspected_paths": ["generated/control/summary.json"],
        "reused_sources": [],
        "changes": [],
        "commands": ["python3 -m json.tool generated/control/summary.json"],
        "blockers": [],
    }
    assert not _validate_report(request, report)
    report["task_id"] = "task:other"
    assert "engineering Agent report binding mismatch: task_id" in _validate_report(request, report)
    report["task_id"] = task["id"]
    report["status"] = "blocked"
    assert "blocked engineering Agent report must contain a blocker" in _validate_report(request, report)
    assert _process_failure("unexpected status 502 Bad Gateway", 1).endswith("502 Bad Gateway")
    assert _responses_base_url("https://www.dmxapi.cn") == "https://www.dmxapi.cn/v1"
    assert _responses_base_url("https://www.dmxapi.cn/v1/chat/completions") == "https://www.dmxapi.cn/v1"

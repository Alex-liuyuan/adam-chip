"""Dispatch an engineering role to its executable workflow."""

from __future__ import annotations

from pathlib import Path

from agents.model_decision import decide

from agents.actions.specification import run as run_specification
from agents.actions.bsp_boot import run as run_bsp_boot
from agents.actions.driver import run as run_driver
from agents.actions.micropython import run as run_micropython
from agents.actions.verification import run as run_verification
from agents.actions.security import run as run_security
from agents.actions.release import run as run_release
from agents.actions.rtthread_os import run as run_rtthread_os


RUNNERS = {"SpecificationAgent": run_specification, "BspBootAgent": run_bsp_boot, "DriverAgent": run_driver, "RtThreadOsAgent": run_rtthread_os, "MicroPythonAgent": run_micropython, "VerificationAgent": run_verification, "SecurityAgent": run_security, "ReleaseAgent": run_release}


def run_agent(project: Path, agent: str, out: Path, handoffs: tuple[Path, ...] = (), *, use_model: bool = True) -> dict:
    if agent not in RUNNERS:
        return {"ok": False, "status": "blocked", "agent": agent, "blockers": ["agent workflow is not implemented yet"]}
    model_decision = None
    if use_model:
        model_decision = decide(project.resolve(), agent, handoffs, out.resolve() / "00_model_decision")
        if not model_decision["ok"]:
            rationale = str(model_decision["decision"].get("rationale", "")).strip()
            return {
                "schema": "adam.agent_workflow.v1",
                "project_id": model_decision["project_id"],
                "agent": agent,
                "ok": False,
                "status": "blocked",
                "blockers": [*model_decision["errors"], *([rationale] if rationale else [])],
                "actions": [],
                "handoffs": [],
                "model_execution": model_decision,
            }
    report = RUNNERS[agent](project, out, handoffs)
    report["model_execution"] = model_decision or {"enabled": False, "reason": "explicit --no-model bypass"}
    return report

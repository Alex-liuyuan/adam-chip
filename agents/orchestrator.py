"""Run the engineering team in dependency order."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from agents.agentscope_manager import AgentScopeExecutionManager
from agents.catalog import ORDER, workflow_agents, workflow_handoffs
from agents.project import load as load_project
from agents.registry import run_agent


Runner = Callable[..., dict]


def run_project(project: Path, out: Path, *, use_model: bool = True, max_workers: int = 4, runner: Runner = run_agent) -> dict:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    project_data = load_project(project)
    selected = workflow_agents(project_data)
    active = set(selected)
    available: dict[tuple[str, str], Path] = {}
    pending = list(selected)
    reports: dict[str, dict] = {}
    waves = []
    manager = AgentScopeExecutionManager(runner)
    while pending:
        ready = [agent for agent in pending if workflow_handoffs(agent, active) <= available.keys()]
        if not ready:
            break
        waves.append({"index": len(waves) + 1, "agents": ready, "parallel": len(ready) > 1})
        calls = []
        for agent in ready:
            handoffs = tuple(available[key] for key in sorted(workflow_handoffs(agent, active)))
            index = ORDER.index(agent) + 1
            calls.append({"project": str(project), "agent": agent, "out": str(out / f"{index:02d}_{agent}"), "handoffs": [str(path) for path in handoffs], "use_model": use_model})
        wave_reports = manager.run_wave(calls, max_workers)
        for agent in ready:
            report = wave_reports[agent]
            reports[agent] = report
            for value in report.get("handoffs", []):
                path = Path(value)
                data = json.loads(path.read_text(encoding="utf-8"))
                available[(data["from_agent"], data["action"])] = path
            pending.remove(agent)
    for agent in pending:
        missing = sorted(workflow_handoffs(agent, active) - available.keys())
        reports[agent] = {"agent": agent, "ok": False, "status": "blocked", "blockers": [f"missing required handoff: {owner}.{action}" for owner, action in missing], "handoffs": []}
    results = [reports[agent] for agent in selected]
    complete = len(results) == len(selected) and all(item.get("ok") for item in results)
    first_failed = next((item["agent"] for item in results if not item.get("ok")), None)
    final = {
        "schema": "adam.project_execution.v1",
        "project": str(project.resolve()),
        "ok": complete,
        "status": "passed" if complete else "blocked",
        "execution_mode": "serial" if max_workers == 1 else "parallel_dag",
        "execution_manager": manager.status(),
        "max_workers": max(1, max_workers),
        "selected_agents": list(selected),
        "excluded_agents": [agent for agent in ORDER if agent not in active],
        "waves": waves,
        "agents_completed": [item["agent"] for item in results if item.get("ok")],
        "stopped_at": first_failed,
        "results": results,
        "not_claimed": ["project execution does not upgrade absent physical-board evidence"],
    }
    (out / "project_execution_report.json").write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
    return final

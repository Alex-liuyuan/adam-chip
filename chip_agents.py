#!/usr/bin/env python3
"""Build and validate the K230 SDK image through the AgentScope DAG."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agents.agentscope_manager import AgentScopeExecutionManager
from agents.catalog import role_catalog
from agents.orchestrator import run_project
from agents.registry import run_agent
from tools.llm_client import config as llm_config
from tools.llm_client import request_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    project = commands.add_parser("run-project")
    project.add_argument("project")
    project.add_argument("--out", required=True)
    project.add_argument("--max-workers", type=int, default=4)
    project.add_argument("--no-model", action="store_true")
    agent = commands.add_parser("run-agent")
    agent.add_argument("project")
    agent.add_argument("--agent", required=True, choices=sorted(role_catalog()))
    agent.add_argument("--out", required=True)
    agent.add_argument("--handoff", action="append", default=[])
    agent.add_argument("--no-model", action="store_true")
    commands.add_parser("agent-roles")
    commands.add_parser("agentscope-status")
    commands.add_parser("model-config")
    commands.add_parser("model-ping")
    commands.add_parser("selftest")
    args = parser.parse_args()

    if args.command == "run-project":
        report = run_project(Path(args.project), Path(args.out), use_model=not args.no_model, max_workers=args.max_workers)
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    if args.command == "run-agent":
        report = run_agent(Path(args.project), args.agent, Path(args.out), tuple(map(Path, args.handoff)), use_model=not args.no_model)
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    if args.command == "agent-roles":
        print(json.dumps(role_catalog(), indent=2))
    elif args.command == "agentscope-status":
        print(json.dumps(AgentScopeExecutionManager().status(), indent=2))
    elif args.command == "model-config":
        print(json.dumps(llm_config(), indent=2))
    elif args.command == "model-ping":
        result = request_text("Return exactly: ok", timeout=40)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    else:
        roles = role_catalog()
        assert len(roles) == 8
        assert AgentScopeExecutionManager().status()["agent_count"] == 8
        print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

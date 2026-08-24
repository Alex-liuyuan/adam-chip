"""AgentScope-backed execution manager for engineering workflows."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
for site_packages in (ROOT / ".venv/lib").glob(f"python{sys.version_info.major}.{sys.version_info.minor}/site-packages"):
    sys.path.insert(0, str(site_packages))
    break

import agentscope
from agentscope.agent import Agent
from agentscope.message import TextBlock, UserMsg
from agentscope.model import ChatModelBase, ChatResponse
from pydantic import BaseModel

from agents.catalog import load_catalog
from agents.prompts import render_prompt
from agents.registry import run_agent


Runner = Callable[..., dict]


class _Parameters(BaseModel):
    pass


class _ExecutionModel(ChatModelBase):
    def __init__(self, agent: str, runner: Runner) -> None:
        super().__init__(credential=None, model="adam-typed-runner", parameters=_Parameters(), stream=False, max_retries=0)
        self.agent = agent
        self.runner = runner

    async def _call_api(self, model_name, messages, tools=None, tool_choice=None, **kwargs):
        del model_name, tools, tool_choice, kwargs
        payload = json.loads(messages[-1].get_text_content() or "{}")
        if payload.get("agent") != self.agent:
            raise ValueError("AgentScope execution payload role mismatch")
        report = await asyncio.to_thread(
            self.runner,
            Path(payload["project"]),
            self.agent,
            Path(payload["out"]),
            tuple(Path(value) for value in payload["handoffs"]),
            use_model=payload["use_model"],
        )
        return ChatResponse(content=[TextBlock(text=json.dumps(report, sort_keys=True))], is_last=True)


class AgentScopeExecutionManager:
    def __init__(self, runner: Runner = run_agent) -> None:
        roles = load_catalog()
        self.agents = {}
        for name, role in roles.items():
            system, _ = render_prompt(
                f"{name}.EngineeringRole",
                owned_domains=", ".join(role["owned_paths"]),
                role_contract_json=json.dumps(role, sort_keys=True),
                task_payload_json="{}",
            )
            self.agents[name] = Agent(name=name, system_prompt=system, model=_ExecutionModel(name, runner))

    def status(self) -> dict:
        return {
            "framework": "agentscope",
            "version": getattr(agentscope, "__version__", None),
            "agent_class": "agentscope.agent.Agent",
            "agent_count": len(self.agents),
        }

    def run_wave(self, calls: list[dict], max_concurrency: int) -> dict[str, dict]:
        return asyncio.run(self._run_wave(calls, max_concurrency))

    async def _run_wave(self, calls: list[dict], max_concurrency: int) -> dict[str, dict]:
        semaphore = asyncio.Semaphore(max(1, max_concurrency))

        async def execute(call: dict) -> tuple[str, dict]:
            agent = call["agent"]
            try:
                async with semaphore:
                    message = await self.agents[agent].reply(
                        UserMsg("ADAMExecutionManager", json.dumps(call, sort_keys=True), metadata={"runtime": "agentscope"})
                    )
                return agent, json.loads(message.get_text_content() or "{}")
            except Exception as exc:
                return agent, {"agent": agent, "ok": False, "status": "failed", "blockers": [f"AgentScope execution raised {type(exc).__name__}: {exc}"], "handoffs": []}

        return dict(await asyncio.gather(*(execute(call) for call in calls)))

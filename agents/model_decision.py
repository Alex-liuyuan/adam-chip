"""Remote-model admission decision for a typed engineering Agent workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from agents.artifacts import describe
from agents.catalog import load_catalog, workflow_agents, workflow_handoffs
from agents.project import load as load_project, resolve
from agents.prompts import render_prompt
from tools.llm_client import request_json


Requester = Callable[..., dict[str, Any]]


def decide(project_path: Path, agent: str, handoffs: tuple[Path, ...], out: Path, *, requester: Requester = request_json) -> dict[str, Any]:
    project = load_project(project_path)
    role = load_catalog()[agent]
    target = resolve(project["target"])
    actions = [item["id"] for item in role["actions"]]
    available_handoffs = set()
    handoff_payload = []
    for path in handoffs:
        if not path.is_file():
            continue
        item = json.loads(path.read_text(encoding="utf-8"))
        available_handoffs.add((item.get("from_agent"), item.get("action")))
        handoff_payload.append({"artifact": describe(path.resolve()), "from_agent": item.get("from_agent"), "action": item.get("action")})
    required_handoffs = workflow_handoffs(agent, set(workflow_agents(project)))
    missing_handoffs = required_handoffs - available_handoffs
    payload = {
        "project": project,
        "agent": agent,
        "human_role": role["human_role"],
        "mission": role["mission"],
        "allowed_actions": actions,
        "action_contracts": role["actions"],
        "allowed_handoffs": role["handoff_to"],
        "target": describe(target),
        "required_handoffs": [{"from_agent": owner, "action": action} for owner, action in sorted(required_handoffs)],
        "available_handoffs": handoff_payload,
        "missing_required_handoffs": [{"from_agent": owner, "action": action} for owner, action in sorted(missing_handoffs)],
    }
    role_system, _ = render_prompt(
        f"{agent}.EngineeringRole",
        owned_domains=", ".join(role["owned_paths"]),
        role_contract_json=json.dumps(role, sort_keys=True),
        task_payload_json="{}",
    )
    system, prompt = render_prompt(
        "Shared.ExecutionDecision",
        role_system=role_system,
        allowed_actions_json=json.dumps(actions),
        task_payload_json=json.dumps(payload, sort_keys=True),
    )
    response = requester(prompt, system=system, timeout=60.0)
    decision = response.get("json") if response.get("ok") else None
    errors: list[str] = []
    if not response.get("ok"):
        errors.append(str(response.get("error", "model API request failed")))
    if not isinstance(decision, dict):
        errors.append("model response is not a JSON object")
        decision = {}
    if decision.get("decision") not in {"execute", "block"}:
        errors.append("decision must be execute or block")
    selected = decision.get("actions")
    if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
        errors.append("actions must be a string array")
        selected = []
    action_scope_ok = selected == actions if decision.get("decision") == "execute" else all(item in actions for item in selected)
    if not action_scope_ok:
        errors.append("execute must select the full typed workflow; block may only name typed actions")
    prerequisite_ok = decision.get("decision") != "execute" or not missing_handoffs
    if not prerequisite_ok:
        errors.append("execute is forbidden while required handoffs are missing")
    if not isinstance(decision.get("rationale"), str) or not decision.get("rationale", "").strip():
        errors.append("rationale is required")
    risks = decision.get("risks")
    if not isinstance(risks, list) or not all(isinstance(item, str) for item in risks):
        errors.append("risks must be a string array")
    assessment = decision.get("input_assessment")
    assessment_ok = isinstance(assessment, dict) and all(isinstance(assessment.get(key), list) and all(isinstance(item, str) for item in assessment[key]) for key in ("ready", "missing_optional", "missing_required"))
    if not assessment_ok:
        errors.append("input_assessment requires ready, missing_optional and missing_required string arrays")
    missing_labels = {f"{owner}.{action}" for owner, action in missing_handoffs}
    prerequisite_assessment_ok = assessment_ok and missing_labels <= set(assessment["missing_required"])
    if not prerequisite_assessment_ok:
        errors.append("input_assessment.missing_required must list every missing handoff as ProducerAgent.Action")
    action_plan = decision.get("action_plan")
    plan_ok = isinstance(action_plan, list)
    planned_actions = []
    contracts = {item["id"]: item for item in role["actions"]}
    if plan_ok:
        for item in action_plan:
            if not isinstance(item, dict) or item.get("action") not in contracts:
                plan_ok = False
                break
            expected = contracts[item["action"]]
            planned_actions.append(item["action"])
            if item.get("tool") != expected["tool"] or item.get("third_party") != expected["third_party"] or item.get("outputs") != expected["outputs"] or item.get("required_evidence") != expected["evidence"]:
                plan_ok = False
                break
    expected_planned = actions if decision.get("decision") == "execute" else selected
    plan_ok = plan_ok and planned_actions == expected_planned
    if not plan_ok:
        errors.append("action_plan must exactly reproduce the selected typed action contracts")
    handoff_plan = decision.get("handoffs")
    handoffs_ok = isinstance(handoff_plan, list) and (handoff_plan == role["handoff_to"] if decision.get("decision") == "execute" else all(isinstance(item, str) and item in role["handoff_to"] for item in handoff_plan))
    if not handoffs_ok:
        errors.append("execute must select all typed handoffs; block may select only typed recipients")
    blocked_capabilities = decision.get("blocked_capabilities")
    if not isinstance(blocked_capabilities, list) or not all(isinstance(item, str) for item in blocked_capabilities):
        errors.append("blocked_capabilities must be a string array")
    forbidden_claims = decision.get("claims_not_allowed")
    if not isinstance(forbidden_claims, list) or not all(isinstance(item, str) for item in forbidden_claims):
        errors.append("claims_not_allowed must be a string array")
    approved = not errors and decision.get("decision") == "execute"
    report = {
        "schema": "adam.model_execution_decision.v1",
        "project_id": project["project_id"],
        "agent": agent,
        "ok": approved,
        "status": "approved" if approved else "blocked",
        "decision": decision,
        "model": response.get("model"),
        "profile": response.get("profile"),
        "usage": response.get("usage", {}),
        "errors": errors,
        "evidence": {
            "remote_model_api_pass": bool(response.get("ok")),
            "model_decision_schema_pass": not errors,
            "model_action_scope_pass": action_scope_ok,
            "model_prerequisite_pass": prerequisite_ok and prerequisite_assessment_ok,
            "model_action_contract_pass": plan_ok,
            "model_handoff_scope_pass": handoffs_ok,
        },
        "not_claimed": ["model output is not verification evidence", "model output cannot alter commands or evidence gates", *forbidden_claims] if isinstance(forbidden_claims, list) else ["model output is not verification evidence", "model output cannot alter commands or evidence gates"],
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "model_execution_decision.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report

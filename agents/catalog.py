#!/usr/bin/env python3
"""Load and validate the engineering role catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CATALOG = Path(__file__).with_name("roles.json")
CORE_AGENTS = {
    "SpecificationAgent",
    "BspBootAgent",
    "RtThreadOsAgent",
    "DriverAgent",
    "VerificationAgent",
    "SecurityAgent",
    "ReleaseAgent",
}

REQUIRED_HANDOFFS = {
    "BspBootAgent": {("SpecificationAgent", "ValidatePlatformContract")},
    "RtThreadOsAgent": {("BspBootAgent", "BuildRtThreadBsp")},
    "DriverAgent": {("SpecificationAgent", "ValidatePlatformContract"), ("BspBootAgent", "BuildRtThreadBsp")},
    "MicroPythonAgent": {("BspBootAgent", "BuildRtThreadBsp")},
    "VerificationAgent": {
        ("RtThreadOsAgent", "RunVirtualFirmware"),
        ("DriverAgent", "VerifyDrivers"),
        ("MicroPythonAgent", "InspectMicroPythonImage"),
    },
    "SecurityAgent": {("VerificationAgent", "RunVirtualVerification")},
    "ReleaseAgent": {("SecurityAgent", "SignRelease"), ("VerificationAgent", "RunVirtualVerification")},
}

ORDER = (
    "SpecificationAgent",
    "BspBootAgent",
    "RtThreadOsAgent",
    "DriverAgent",
    "MicroPythonAgent",
    "VerificationAgent",
    "SecurityAgent",
    "ReleaseAgent",
)


def workflow_agents(project: dict[str, Any]) -> tuple[str, ...]:
    selected = set(CORE_AGENTS)
    if "micropython" in set(map(str, project.get("features", []))):
        selected.add("MicroPythonAgent")
    return tuple(agent for agent in ORDER if agent in selected)


def workflow_handoffs(agent: str, active_agents: set[str]) -> set[tuple[str, str]]:
    required = {item for item in REQUIRED_HANDOFFS.get(agent, set()) if item[0] in active_agents}
    return required


def load_catalog(path: Path = CATALOG) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "adam.agent_roles.v1" or not isinstance(data.get("roles"), list):
        raise ValueError("invalid agent role catalog schema")
    roles: dict[str, dict[str, Any]] = {}
    for role in data["roles"]:
        name = role.get("name")
        required = {"name", "human_role", "mission", "owned_paths", "actions", "handoff_to"}
        if not isinstance(name, str) or required - set(role):
            raise ValueError(f"invalid role entry: {name!r}")
        if name in roles or not role["actions"]:
            raise ValueError(f"duplicate or empty role: {name}")
        action_ids = [action.get("id") for action in role["actions"]]
        if any(not value for value in action_ids) or len(action_ids) != len(set(action_ids)):
            raise ValueError(f"invalid action IDs for {name}")
        for action in role["actions"]:
            action_required = {"id", "tool", "third_party", "inputs", "outputs", "evidence"}
            if action_required - set(action):
                raise ValueError(f"incomplete action {name}.{action.get('id')}")
        roles[name] = role
    if not CORE_AGENTS <= set(roles):
        raise ValueError(f"missing core agents: {sorted(CORE_AGENTS - set(roles))}")
    return roles


def role_catalog() -> dict[str, dict[str, Any]]:
    return load_catalog()


def _self_test() -> None:
    roles = load_catalog()
    assert CORE_AGENTS <= set(roles)
    assert {action["id"] for action in roles["SpecificationAgent"]["actions"]} >= {"ImportSvd", "MergeContract"}
    assert any(action["id"] == "BuildRtThreadBsp" for action in roles["BspBootAgent"]["actions"])
    assert roles["VerificationAgent"]["independent_verifier"] is True
    assert all(role["owned_paths"] for role in roles.values())
    for recipient, prerequisites in REQUIRED_HANDOFFS.items():
        assert all(recipient in roles[owner]["handoff_to"] for owner, _ in prerequisites)
    assert "MicroPythonAgent" in roles["BspBootAgent"]["handoff_to"]
    base = workflow_agents({"features": ["boot", "rtos"], "required_evidence_level": "E2"})
    assert "CompilerAgent" not in base
    image = workflow_agents({"features": ["micropython"], "required_evidence_level": "E2"})
    assert "MicroPythonAgent" in image


if __name__ == "__main__":
    _self_test()
    print("ok")

#!/usr/bin/env python3
"""Create and validate content-bound handoffs between engineering agents."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.artifacts import describe, verify


SCHEMA = ROOT / "schemas" / "handoff.schema.json"


def create(result_path: Path, recipients: tuple[str, ...], out: Path) -> dict[str, Any]:
    result_path = result_path.resolve()
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if not result.get("handoff_ready"):
        raise ValueError("action result has not passed its evidence gate")
    manifest = {
        "schema": "adam.handoff.v1",
        "run_id": result["run_id"],
        "project_id": result["project_id"],
        "from_agent": result["agent"],
        "to_agents": list(recipients),
        "action": result["action"],
        "action_result": describe(result_path),
        "target_hash": result["target_hash"],
        "artifacts": result["artifacts"],
        "evidence": result["evidence"],
        "evidence_level": result["evidence_level"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _validate_schema(manifest)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def validate(
    path: Path,
    *,
    recipient: str = "",
    project_id: str = "",
    target_hash: str = "",
    required_evidence: tuple[str, ...] = (),
) -> dict[str, Any]:
    errors = []
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        _validate_schema(manifest)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {"ok": False, "errors": [f"invalid handoff: {exc}"]}
    if recipient and recipient not in manifest["to_agents"]:
        errors.append(f"handoff is not addressed to {recipient}")
    if project_id and project_id != manifest["project_id"]:
        errors.append("project ID mismatch")
    if target_hash and target_hash != manifest["target_hash"]:
        errors.append("target hash mismatch")
    if not verify(manifest["action_result"]):
        errors.append("action result hash mismatch")
    errors.extend(f"artifact hash mismatch: {item['path']}" for item in manifest["artifacts"] if not verify(item))
    errors.extend(f"missing evidence: {name}" for name in required_evidence if not manifest["evidence"].get(name))
    return {
        "ok": not errors,
        "run_id": manifest["run_id"],
        "producer": manifest["from_agent"],
        "evidence_level": manifest["evidence_level"],
        "errors": errors,
    }


def _validate_schema(data: dict[str, Any]) -> None:
    errors = sorted(Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).iter_errors(data), key=lambda item: list(item.path))
    if errors:
        raise ValueError(errors[0].message)


def _self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        artifact = root / "firmware.bin"
        artifact.write_bytes(b"firmware")
        result_path = root / "action_result.json"
        result = {
            "run_id": "run-1",
            "project_id": "project-1",
            "agent": "BspBootAgent",
            "action": "BuildRtThreadBsp",
            "target_hash": "a" * 64,
            "artifacts": [describe(artifact)],
            "evidence": {"vendor_rtsmart_bsp_build_pass": True},
            "evidence_level": "E2",
            "handoff_ready": True,
        }
        result_path.write_text(json.dumps(result), encoding="utf-8")
        handoff_path = root / "handoff.json"
        create(result_path, ("VerificationAgent",), handoff_path)
        assert validate(handoff_path, recipient="VerificationAgent", project_id="project-1", target_hash="a" * 64)["ok"]
        artifact.write_bytes(b"tampered")
        assert not validate(handoff_path)["ok"]


if __name__ == "__main__":
    _self_test()
    print("ok")

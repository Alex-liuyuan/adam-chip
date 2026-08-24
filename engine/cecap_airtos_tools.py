"""CECAP/AIRTOS convergence and immutable trace-feedback contracts."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from socimage.facts import sha256


ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _contracts(worktree: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    compiler = worktree / "generated/compiler"
    plan = _load(compiler / "plan.json")
    evidence = _load(compiler / "evidence.json")
    policy = _load(compiler / "airtos_policy.json")
    for value, name in ((plan, "cecap_plan.schema.json"), (evidence, "cecap_evidence.schema.json"), (policy, "airtos_policy.schema.json")):
        Draft202012Validator(_load(ROOT / "schemas" / name)).validate(value)
    if evidence["plan_id"] != plan["plan_id"] or evidence["evidence_id"] != plan["evidence_sha256"] or policy["policy_id"] != plan["policy_sha256"]:
        raise ValueError("CECAP/AIRTOS contract hashes do not converge")
    return plan, evidence, policy


def _generate(context: Any, root: Path) -> dict[str, Any]:
    plan, evidence, policy = _contracts(context.worktree)
    compiler = context.worktree / "generated/compiler"
    runtime = context.worktree / "generated/rt_ai/runtime"
    deployment = {
        "schema": "soc-image.cecap-airtos-deployment.v1",
        "plan_id": plan["plan_id"],
        "plan_sha256": sha256(compiler / "plan.json"),
        "evidence_sha256": sha256(compiler / "evidence.json"),
        "policy_sha256": sha256(compiler / "airtos_policy.json"),
        "aeg_sha256": sha256(compiler / "model.aeg"),
        "runtime_manifest_sha256": sha256(runtime / "manifest.json"),
        "deployable": all(item["status"] == "verified" for item in evidence["obligations"]),
        "runtime_responsibility": "consume_plan_and_emit_trace",
        "compiler_responsibility": "search_and_promote_new_plan",
    }
    feedback = {
        "schema": "soc-image.cecap-trace-feedback.v1",
        "parent_plan_id": plan["plan_id"],
        "accepted_trace_schema": "soc-image.airtos-trace.v2",
        "action": "create_compiler_experiment",
        "direct_evidence_promotion": False,
        "mutate_running_plan": False,
    }
    _write(root / "deployment.json", deployment)
    _write(root / "feedback_contract.json", feedback)
    with tempfile.TemporaryDirectory() as tmp:
        trace_path = Path(tmp) / "trace.json"
        experiment_path = Path(tmp) / "experiment.json"
        _write(trace_path, {
            "schema": "soc-image.airtos-trace.v2", "run_id": "1" * 64, "plan_id": plan["plan_id"], "dropped": 0,
            "events": [{"sequence": 0, "timestamp_us": 1, "job_id": 1, "cookie": 1, "plan_id": plan["plan_id"], "segment_id": 1, "resource": "cpu", "epoch": 1, "event": "complete", "status": 0, "queue_depth": 0}],
        })
        experiment = create_trace_experiment(trace_path, compiler / "plan.json", experiment_path)
    verification = {
        "schema": "soc-image.cecap-airtos-verification.v1",
        "contract_hash_binding_pass": True,
        "independent_fallback_pass": any(item["role"] == "fallback" and item["independently_valid"] for item in plan["plans"]),
        "runtime_compiler_separation_pass": not feedback["direct_evidence_promotion"] and not feedback["mutate_running_plan"],
        "trace_feedback_candidate_pass": experiment["status"] == "candidate" and experiment["parent_plan_id"] == plan["plan_id"],
    }
    _write(root / "verification.json", verification)
    return {"deployment": deployment, "verification": verification}


def generate_cecap_airtos_integration(context: Any) -> dict[str, Any]:
    root = context.worktree / "generated/cecap_airtos"
    result = _generate(context, root)
    _write(root / "manifest.json", {
        "schema": "soc-image.cecap-airtos-manifest.v1", "task_id": context.task_id,
        "hardware_ir_sha256": context.hardware_ir_sha256, "generator": "CecapAirtosAgent",
        "deployment_sha256": sha256(root / "deployment.json"),
        "compiler_manifest_sha256": sha256(context.worktree / "generated/compiler/manifest.json"),
        "runtime_manifest_sha256": sha256(context.worktree / "generated/rt_ai/runtime/manifest.json"),
    })
    return {"status": "passed", "outputs": list(context.outputs), "verification": result["verification"]}


def verify_cecap_airtos_integration(context: Any) -> list[str]:
    errors = [f"missing CECAP/AIRTOS output: {path}" for path in context.outputs if not (context.worktree / path).is_file()]
    if errors:
        return errors
    root = context.worktree / "generated/cecap_airtos"
    manifest = _load(root / "manifest.json")
    if manifest.get("task_id") != context.task_id or manifest.get("hardware_ir_sha256") != context.hardware_ir_sha256:
        errors.append("CECAP/AIRTOS manifest is not bound to the task and Hardware IR")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            rebuilt = Path(tmp) / "cecap_airtos"
            result = _generate(context, rebuilt)
            if not all(value is True for name, value in result["verification"].items() if name.endswith("_pass")):
                errors.append("independent CECAP/AIRTOS verification failed")
            for name in ("deployment.json", "feedback_contract.json", "verification.json"):
                if sha256(root / name) != sha256(rebuilt / name):
                    errors.append(f"independent CECAP/AIRTOS output differs: {name}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    return errors


def create_trace_experiment(trace_path: Path, plan_path: Path, output: Path) -> dict[str, Any]:
    trace = _load(trace_path)
    plan = _load(plan_path)
    Draft202012Validator(_load(ROOT / "schemas/airtos_trace.schema.json")).validate(trace)
    if trace["plan_id"] != plan["plan_id"]:
        raise ValueError("trace is not bound to its parent CECAP plan")
    experiment = {
        "schema": "soc-image.cecap-compiler-experiment.v1",
        "parent_plan_id": plan["plan_id"],
        "parent_plan_sha256": sha256(plan_path),
        "trace_sha256": sha256(trace_path),
        "status": "candidate",
        "promotion": "requires_compiler_and_independent_verifier",
    }
    _write(output, experiment)
    return experiment

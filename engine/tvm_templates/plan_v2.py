"""Deterministic CECAP Plan v2 construction and AEG v2 encoding."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any


AEG_MAGIC = 0x32474541
AEG_VERSION = 2
SECTION_SEGMENTS = 1
SECTION_METADATA = 2
SECTION_EVIDENCE = 3
SECTION_FALLBACKS = 4
SECTION_RESERVATIONS = 5
SECTION_ARRIVAL = 6
SECTION_RECOVERY = 7
SECTION_DOMAIN = 8


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identified(value: dict[str, Any], field: str) -> dict[str, Any]:
    value[field] = digest({key: item for key, item in value.items() if key != field})
    return value


def build_contracts(out: Path, target: dict[str, Any], search: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    selected = search["selected"]["segments"][0]["backend"]
    if selected not in ("cpu", "rvv"):
        raise ValueError("deployable CECAP plan requires an evidenced CPU or RVV backend")
    verifier_hash = file_digest(out / "compiler.py")
    obligations = []
    for backend, artifact in (("cpu", "cpu_model.c"), ("rvv", "rvv_model.c")):
        obligations.append({
            "id": f"{backend}_numerical_and_codegen",
            "claim": f"{backend.upper()} implementation matches the ONNX reference in the declared domain",
            "scope": {"backend": backend, "shape": [1, 8], "dtype": "float32", "layout": "NC"},
            "artifacts": [
                {"path": artifact, "sha256": file_digest(out / artifact)},
                {"path": f"{backend}_output.txt", "sha256": file_digest(out / f"{backend}_output.txt")},
            ],
            "verifier": {"name": "CompilerAgent.compiler.py", "sha256": verifier_hash},
            "status": "verified",
        })
    evidence = {"schema": "soc-image.cecap-evidence.v2", "evidence_id": "0" * 64, "plan_id": "0" * 64, "obligations": obligations}
    policy = _identified({
        "schema": "soc-image.airtos-policy.v2",
        "admission": {"algorithm": "sim_edf_plus", "max_retries": 3, "include_active_residual": True, "include_nonpreemptive_blocking": True},
        "recovery": {"cancel_ack_timeout_us": 50, "reset_timeout_us": 500, "reinit_timeout_us": 1000, "max_reset_attempts": 3, "quarantine_on_failure": True},
        "trace": {"format": "soc-image.airtos-trace.v2", "chronological_export": True, "report_dropped": True},
    }, "policy_id")
    wcet = {"cpu": 10, "rvv": 4}
    plans = []
    for plan_id, (role, backend) in enumerate((("primary", selected), ("fallback", "cpu" if selected == "rvv" else "rvv")), 1):
        plans.append({
            "id": plan_id, "role": role, "independently_valid": True,
            "evidence_obligations": [f"{backend}_numerical_and_codegen"],
            "segments": [{
                "id": 1, "resource": backend, "dependencies": [], "wcet_us": wcet[backend],
                "buffers": [{"id": "activation", "offset": 0, "size": 64, "access": "read_write", "coherency": "clean_invalidate"}],
                "coherency_cost_us": 1, "recovery_cost_us": 50,
            }],
        })
    plan = {
        "schema": "soc-image.cecap-plan.v2", "plan_id": "0" * 64,
        "model_sha256": file_digest(out / "model.onnx"), "target_sha256": digest(target),
        "runtime_abi_sha256": target["rt_ai_runtime_manifest_sha256"],
        "provider_abi_sha256": hashlib.sha256(b"rt_ai_provider_v2:submit,cancel_begin,cancel_poll,reset_begin,reinit_poll,health").hexdigest(),
        "domain": {"inputs": [{"name": "input", "shape": [1, 8], "dtype": "float32", "layout": "NC"}], "precision": "fp32", "runtime_requirements": ["rv64gc", "little_endian", "coherent_plan_buffers"]},
        "plans": plans,
        "memory": {"arena_bytes": 64, "alignment_bytes": 64, "lifetimes": [{"buffer": "activation", "first_segment": 1, "last_segment": 1}], "alias_rules": [{"buffers": ["activation"], "allowed": False}]},
        "evidence_sha256": "0" * 64, "policy_sha256": policy["policy_id"],
        "arrival_model": {"minimum_interarrival_us": 100, "relative_deadline_us": 100, "reservations": [{"resource": backend, "budget_us": wcet[backend] + 51, "period_us": 100} for backend in dict.fromkeys((selected, "cpu" if selected == "rvv" else "rvv"))]},
    }
    evidence["evidence_id"] = digest({"schema": evidence["schema"], "obligations": obligations})
    plan["evidence_sha256"] = evidence["evidence_id"]
    plan["plan_id"] = digest({key: value for key, value in plan.items() if key != "plan_id"})
    evidence["plan_id"] = plan["plan_id"]
    return plan, evidence, policy


def encode_aeg(path: Path, plan: dict[str, Any], evidence: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    primary, fallback = plan["plans"]
    resource_ids = {"cpu": 0, "rvv": 1, "npu": 2, "dma": 3}
    segments = bytearray()
    for index, segment in enumerate(primary["segments"]):
        dependency_mask = sum(1 << primary["segments"].index(next(item for item in primary["segments"] if item["id"] == dep)) for dep in segment["dependencies"])
        buffer = segment["buffers"][0]
        flags = 3 if buffer["coherency"] == "clean_invalidate" else 0
        obligation_id = primary["evidence_obligations"][0]
        evidence_index = next(i for i, item in enumerate(evidence["obligations"]) if item["id"] == obligation_id)
        segments += struct.pack("<HBBIIIIIIHH", segment["id"], resource_ids[segment["resource"]], flags, dependency_mask, buffer["offset"], buffer["size"], segment["wcet_us"], segment["coherency_cost_us"], segment["recovery_cost_us"], fallback["id"], evidence_index)
    metadata = b"".join(bytes.fromhex(value) for value in (plan["plan_id"], evidence["evidence_id"], policy["policy_id"], plan["model_sha256"], plan["target_sha256"], plan["runtime_abi_sha256"], plan["provider_abi_sha256"]))
    evidence_records = bytearray()
    for obligation in evidence["obligations"]:
        evidence_records += struct.pack(
            "<32s32s32s32sBBH",
            bytes.fromhex(digest(obligation["id"])), bytes.fromhex(digest(obligation["scope"])),
            bytes.fromhex(digest(obligation["artifacts"])), bytes.fromhex(obligation["verifier"]["sha256"]),
            1 if obligation["status"] == "verified" else 0, resource_ids[obligation["scope"]["backend"]], 0,
        )
    fallback_plan_sha256 = digest(fallback)
    metadata += bytes.fromhex(fallback_plan_sha256)
    fallback_records = bytearray()
    for segment in fallback["segments"]:
        dependency_mask = sum(1 << fallback["segments"].index(next(item for item in fallback["segments"] if item["id"] == dep)) for dep in segment["dependencies"])
        buffer = segment["buffers"][0]
        flags = 3 if buffer["coherency"] == "clean_invalidate" else 0
        fallback_evidence = next(i for i, item in enumerate(evidence["obligations"]) if item["id"] == fallback["evidence_obligations"][0])
        fallback_records += struct.pack("<HBBIIIIIIHH", segment["id"], resource_ids[segment["resource"]], flags, dependency_mask, buffer["offset"], buffer["size"], segment["wcet_us"], segment["coherency_cost_us"], segment["recovery_cost_us"], fallback["id"], fallback_evidence)
    reservations = b"".join(struct.pack("<B3xIII", resource_ids[item["resource"]], item["budget_us"], item["period_us"], 0) for item in plan["arrival_model"]["reservations"])
    arrival = struct.pack("<II", plan["arrival_model"]["minimum_interarrival_us"], plan["arrival_model"]["relative_deadline_us"])
    recovery = struct.pack("<III", policy["recovery"]["cancel_ack_timeout_us"], policy["recovery"]["reset_timeout_us"], policy["recovery"]["reinit_timeout_us"])
    tensor = plan["domain"]["inputs"][0]
    shape = (tensor["shape"] + [0, 0, 0, 0])[:4]
    domain = struct.pack("<BBBB6I", len(tensor["shape"]), {"float32": 1, "float16": 2, "int8": 3}[tensor["dtype"]], {"NC": 1}[tensor["layout"]], 0, *shape, 32, 32)
    payloads = ((SECTION_SEGMENTS, 32, bytes(segments), len(primary["segments"])), (SECTION_METADATA, 256, metadata, 1), (SECTION_EVIDENCE, 132, bytes(evidence_records), len(evidence["obligations"])), (SECTION_FALLBACKS, 32, bytes(fallback_records), len(fallback["segments"])), (SECTION_RESERVATIONS, 16, reservations, len(plan["arrival_model"]["reservations"])), (SECTION_ARRIVAL, 8, arrival, 1), (SECTION_RECOVERY, 16, recovery + struct.pack("<I", policy["recovery"]["max_reset_attempts"]), 1), (SECTION_DOMAIN, 28, domain, 1))
    offset = 64 + 16 * len(payloads)
    directory = bytearray()
    body = bytearray()
    debug_sections = []
    for section_type, entry_size, payload, count in payloads:
        directory += struct.pack("<HHIII", section_type, entry_size, offset, count, 0)
        debug_sections.append({"type": section_type, "entry_size": entry_size, "offset": offset, "count": count})
        body += payload
        offset += len(payload)
    header = struct.pack("<IHHIHHI32s12x", AEG_MAGIC, AEG_VERSION, 64, offset, len(payloads), 1, plan["memory"]["arena_bytes"], bytes.fromhex(plan["plan_id"]))
    path.write_bytes(header + directory + body)
    return {"magic": "AEG2", "version": 2, "deployable": True, "plan_id": plan["plan_id"], "total_size": offset, "sections": debug_sections}

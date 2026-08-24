"""Small, explicitly allowed tools used by project Agents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from engine.boot_bsp_tools import generate_boot_bsp, verify_boot_bsp
from engine.driver_sim_tools import (
    generate_contract_drivers,
    generate_simulation_models,
    verify_contract_drivers,
    verify_simulation_models,
)
from engine.rt_ai_tools import generate_rt_ai_os, generate_rt_ai_runtime, verify_rt_ai_os, verify_rt_ai_runtime
from engine.tvm_ai_tools import generate_tvm_ai_compiler, verify_tvm_ai_compiler
from engine.cecap_airtos_tools import generate_cecap_airtos_integration, verify_cecap_airtos_integration
from engine.product_tools import generate_product_layer, verify_product_layer
from engine.image_tools import generate_source_image, verify_source_image
from engine.hil_tools import generate_hil_verification, verify_hil_verification
from engine.source_discovery_tools import generate_source_discovery, verify_source_discovery
from engine.source_stack_tools import generate_source_stack_image, verify_source_stack_image
from engine.evaluation_stack_tools import generate_canmv_evaluation_image, verify_canmv_evaluation_image


@dataclass(frozen=True)
class ToolContext:
    worktree: Path
    project_id: str
    task_id: str
    hardware_ir_sha256: str
    hardware_ir: dict[str, Any]
    outputs: tuple[str, ...]
    reference_profile: dict[str, Any]
    reference_profile_sha256: str
    software_requirements: dict[str, Any]
    software_requirements_sha256: str
    source_policy: dict[str, Any]
    source_policy_sha256: str
    artifact_dir: Path


def write_contract_summary(context: ToolContext) -> dict[str, Any]:
    output = context.worktree / context.outputs[0]
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema": "soc-image.generated-contract-summary.v1",
        "task_id": context.task_id,
        "project_id": context.project_id,
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "cpu_fact_count": len(context.hardware_ir.get("cpu", {})),
        "memory_region_count": len(context.hardware_ir.get("memory_regions", [])),
        "peripheral_count": len(context.hardware_ir.get("peripherals", [])),
        "unresolved_count": len(context.hardware_ir.get("unresolved", [])),
    }
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "passed", "outputs": [str(output.relative_to(context.worktree))]}


def verify_contract_summary(context: ToolContext) -> list[str]:
    path = context.worktree / context.outputs[0]
    if not path.is_file():
        return [f"missing output: {context.outputs[0]}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"invalid summary JSON: {exc}"]
    errors = []
    expected = {
        "schema": "soc-image.generated-contract-summary.v1",
        "task_id": context.task_id,
        "project_id": context.project_id,
        "hardware_ir_sha256": context.hardware_ir_sha256,
    }
    for name, value in expected.items():
        if data.get(name) != value:
            errors.append(f"{name} does not match the task contract")
    return errors


TOOLS: dict[str, Callable[[ToolContext], Any]] = {
    "write_contract_summary": write_contract_summary,
    "verify_contract_summary": verify_contract_summary,
    "generate_boot_bsp": generate_boot_bsp,
    "verify_boot_bsp": verify_boot_bsp,
    "generate_contract_drivers": generate_contract_drivers,
    "verify_contract_drivers": verify_contract_drivers,
    "generate_simulation_models": generate_simulation_models,
    "verify_simulation_models": verify_simulation_models,
    "generate_rt_ai_os": generate_rt_ai_os,
    "verify_rt_ai_os": verify_rt_ai_os,
    "generate_rt_ai_runtime": generate_rt_ai_runtime,
    "verify_rt_ai_runtime": verify_rt_ai_runtime,
    "generate_tvm_ai_compiler": generate_tvm_ai_compiler,
    "verify_tvm_ai_compiler": verify_tvm_ai_compiler,
    "generate_cecap_airtos_integration": generate_cecap_airtos_integration,
    "verify_cecap_airtos_integration": verify_cecap_airtos_integration,
    "generate_product_layer": generate_product_layer,
    "verify_product_layer": verify_product_layer,
    "generate_source_image": generate_source_image,
    "verify_source_image": verify_source_image,
    "generate_hil_verification": generate_hil_verification,
    "verify_hil_verification": verify_hil_verification,
    "generate_source_discovery": generate_source_discovery,
    "verify_source_discovery": verify_source_discovery,
    "generate_source_stack_image": generate_source_stack_image,
    "verify_source_stack_image": verify_source_stack_image,
    "generate_canmv_evaluation_image": generate_canmv_evaluation_image,
    "verify_canmv_evaluation_image": verify_canmv_evaluation_image,
}

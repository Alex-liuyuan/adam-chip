"""Stable failure classes used for ADAM repair routing."""

from __future__ import annotations


FAILURE_OWNERS = {
    "contract_missing": "SpecificationAgent",
    "contract_conflict": "SpecificationAgent",
    "dependency_missing": "BspBootAgent",
    "tool_timeout": "ADAM",
    "toolchain_mismatch": "BspBootAgent",
    "build_failure": "producer",
    "link_failure": "producer",
    "model_unsupported": "VerificationAgent",
    "numerical_mismatch": "VerificationAgent",
    "simulation_failure": "VerificationAgent",
    "hardware_unavailable": "VerificationAgent",
    "flash_readback_mismatch": "VerificationAgent",
    "boot_attribution_failure": "VerificationAgent",
    "performance_regression": "VerificationAgent",
    "security_gate_failure": "SecurityAgent",
    "workspace_policy_violation": "ADAM",
    "evidence_gate_failure": "producer",
    "tool_failure": "producer",
}


def classify(returncode: int | None, output: str, *, timed_out: bool = False) -> str | None:
    text = output.lower()
    if timed_out:
        return "tool_timeout"
    if returncode == 0:
        return None
    if "contract" in text and ("missing" in text or "required" in text):
        return "contract_missing"
    if "contract" in text and "conflict" in text:
        return "contract_conflict"
    if "no such file" in text or "not found" in text or "missing dependency" in text:
        return "dependency_missing"
    if "wrong elf class" in text or "unrecognized option" in text or "march" in text or "mabi" in text:
        return "toolchain_mismatch"
    if "undefined reference" in text or "linker" in text or "ld returned" in text:
        return "link_failure"
    if "unsupported op" in text or "unsupported model" in text:
        return "model_unsupported"
    if "reference" in text and ("mismatch" in text or "diff failed" in text):
        return "numerical_mismatch"
    if "readback" in text and ("mismatch" in text or "failed" in text):
        return "flash_readback_mismatch"
    if "boot marker" in text or "run id mismatch" in text:
        return "boot_attribution_failure"
    if "usb" in text or "serial device" in text or "board unavailable" in text:
        return "hardware_unavailable"
    if "qemu" in text or "renode" in text or "simulation" in text:
        return "simulation_failure"
    if "vulnerability" in text or "license" in text or "signature" in text:
        return "security_gate_failure"
    if "compile" in text or "compiler" in text or "build" in text:
        return "build_failure"
    return "tool_failure"


def owner(failure_class: str | None, producer: str) -> str:
    value = FAILURE_OWNERS.get(str(failure_class), "producer")
    return producer if value == "producer" else value

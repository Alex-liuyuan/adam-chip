"""Evidence authority and action admission gates."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.artifacts import verify


LEVELS = {f"E{index}": index for index in range(7)}
LEVEL_MARKERS = {
    "E6": ("stress", "p95", "p99", "energy", "long_running", "performance_verified"),
    "E5": ("physical", "board", "flash_readback", "boot_marker", "serial_capture", "device_run"),
    "E4": ("qemu", "renode", "virtual", "simulation", "rtthread_build"),
    "E3": ("reference_diff", "host_diff", "unit_pass", "operator_diff", "fault_injection"),
    "E2": ("build_pass", "compile_pass", "link_pass", "codegen_pass"),
    "E1": ("schema", "static", "checker", "contract", "hashes_recorded", "workspace_policy"),
}
PHYSICAL_MARKERS = LEVEL_MARKERS["E5"] + LEVEL_MARKERS["E6"]
SECURITY_MARKERS = ("sbom", "license_scan", "vuln_scan", "attestation", "supply_chain_provenance")
INDEPENDENT_MARKERS = ("independent_", "counterexample", "regression_reproducer")


def evidence_level(names: list[str]) -> str:
    for level in ("E6", "E5", "E4", "E3", "E2", "E1"):
        if any(marker in name.lower() for name in names for marker in LEVEL_MARKERS[level]):
            return level
    return "E0"


def authority_errors(agent: str, names: list[str]) -> list[str]:
    errors = []
    for name in names:
        lowered = name.lower()
        negative_scope_marker = lowered.startswith("host_only") or "not_board" in lowered or "not_physical" in lowered or any(marker in lowered for marker in ("qemu", "renode", "virtual"))
        if agent != "VerificationAgent" and not negative_scope_marker and any(marker in lowered for marker in PHYSICAL_MARKERS + INDEPENDENT_MARKERS):
            errors.append(f"{agent} cannot issue independent or physical evidence: {name}")
        security_evidence = (
            any(marker in lowered for marker in SECURITY_MARKERS)
            or lowered in {"signature_pass", "provenance_pass"}
            or lowered.startswith(("package_signature", "release_signature", "cryptographic_signature"))
        )
        if agent != "SecurityAgent" and (security_evidence or lowered == "provenance_pass"):
            errors.append(f"{agent} cannot issue security evidence: {name}")
    return errors


def evaluate_action_result(report: dict[str, Any], required: tuple[str, ...]) -> dict[str, Any]:
    evidence = [name for name, value in report.get("evidence", {}).items() if value]
    errors = authority_errors(str(report.get("agent", "")), evidence)
    errors.extend(f"missing required evidence: {name}" for name in required if name not in evidence)
    errors.extend(f"artifact hash mismatch: {item.get('path')}" for item in report.get("artifacts", []) if not verify(item))
    if report.get("status") != "passed":
        errors.append("action execution did not pass")
    return {"ok": not errors, "errors": errors, "evidence_level": evidence_level(evidence)}


def _self_test() -> None:
    assert evidence_level(["host_reference_diff_pass"]) == "E3"
    assert evidence_level(["boot_marker_pass"]) == "E5"
    assert authority_errors("BspBootAgent", ["boot_marker_pass"])
    assert not authority_errors("VerificationAgent", ["boot_marker_pass", "independent_test_pass"])
    assert authority_errors("ReleaseAgent", ["sbom_generated"])
    assert not authority_errors("SecurityAgent", ["sbom_generated"])
    assert not authority_errors("ReleaseAgent", ["mbr_signature_pass"])
    assert not authority_errors("MicroPythonAgent", ["host_only_not_board_import"])
    assert not authority_errors("MicroPythonAgent", ["qemu_or_renode_board_boot_pass"])


if __name__ == "__main__":
    _self_test()
    print("ok")

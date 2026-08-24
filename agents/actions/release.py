"""Executable ReleaseAgent workflow."""

from __future__ import annotations

import sys
from pathlib import Path

from agents.actions.common import artifact_from_handoffs, authorize, blocked, finish, run_action
from agents.project import load as load_project, resolve


AGENT = "ReleaseAgent"
PYTHON = sys.executable


def run(project_path: Path, out: Path, handoffs: tuple[Path, ...] = ()) -> dict:
    project = load_project(project_path)
    target = resolve(project["target"])
    incoming = tuple(path.resolve() for path in handoffs)
    out = out.resolve()
    errors = authorize(project, target, AGENT, incoming, {("SecurityAgent", "SignRelease"), ("VerificationAgent", "RunVirtualVerification")})
    manifest = artifact_from_handoffs(incoming, "firmware_manifest.json")
    verification = artifact_from_handoffs(incoming, "product_image_verify_report.json")
    signed_provenance = artifact_from_handoffs(incoming, "signed_provenance.json")
    sbom = artifact_from_handoffs(incoming, "sbom.json")
    provenance = artifact_from_handoffs(incoming, "dependency_provenance_report.json")
    for label, path in (("firmware manifest", manifest), ("product image verification", verification), ("signed provenance", signed_provenance), ("firmware SBOM", sbom), ("dependency provenance", provenance)):
        if path is None:
            errors.append(f"security handoff does not contain {label}")
    if errors:
        return blocked(project, AGENT, out, errors)
    assert manifest and verification and signed_provenance and sbom and provenance
    results = []
    stage = out / "01_firmware"
    results.append(run_action(project, AGENT, "StageFirmwareImage", [PYTHON, "tools/firmware_release.py", "--manifest", str(manifest), "--verification", str(verification), "--out", str(stage)], [target, manifest, verification, signed_provenance], target, stage))
    if not results[-1]["handoff_ready"]:
        return finish(project, AGENT, out, results, 3)
    release = out / "02_release"
    artifacts = (stage / "sdk.img", stage / "rollback.img", stage / "firmware_manifest.json", stage / "product_image_verify_report.json", signed_provenance, sbom, provenance)
    command = [PYTHON, "tools/release_package.py", "--out", str(release), "--version", project["project_id"]]
    for artifact in artifacts:
        command.extend(("--artifact", str(artifact)))
    results.append(run_action(project, AGENT, "PackageSdkRelease", command, [target, *artifacts, Path(results[-1]["result_path"])], target, release))
    if not results[-1]["handoff_ready"]:
        return finish(project, AGENT, out, results, 3)
    gate = out / "03_gate"
    security_handoff = next(path for path in incoming if "SecurityAgent" == __import__("json").loads(path.read_text())["from_agent"])
    verification_handoff = next(path for path in incoming if "VerificationAgent" == __import__("json").loads(path.read_text())["from_agent"])
    results.append(run_action(project, AGENT, "ApplyReleaseGate", [PYTHON, "tools/release_gate.py", "--release", str(release / "release_report.json"), "--security-handoff", str(security_handoff), "--verification-handoff", str(verification_handoff), "--image-report", str(stage / "firmware_release_report.json"), "--out", str(gate / "release_gate_report.json")], [target, release / "release_report.json", security_handoff, verification_handoff, stage / "firmware_release_report.json"], target, gate))
    return finish(project, AGENT, out, results, 3, ["physical-board release readiness requires flash readback and boot markers"])

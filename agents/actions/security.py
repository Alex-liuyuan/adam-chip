"""Executable SecurityAgent workflow."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from agents.actions.common import artifact_from_handoffs, authorize, blocked, finish, run_action
from agents.project import load as load_project, resolve


AGENT = "SecurityAgent"
PYTHON = sys.executable


def run(project_path: Path, out: Path, handoffs: tuple[Path, ...] = ()) -> dict:
    project = load_project(project_path)
    target = resolve(project["target"])
    incoming = tuple(path.resolve() for path in handoffs)
    out = out.resolve()
    errors = authorize(project, target, AGENT, incoming, {("VerificationAgent", "RunVirtualVerification")})
    manifest = artifact_from_handoffs(incoming, "firmware_manifest.json")
    verification = artifact_from_handoffs(incoming, "product_image_verify_report.json")
    if manifest is None:
        errors.append("verification handoff does not contain firmware_manifest.json")
    if verification is None:
        errors.append("verification handoff does not contain product_image_verify_report.json")
    if not os.environ.get("ADAM_RELEASE_SIGNING_KEY"):
        errors.append("ADAM_RELEASE_SIGNING_KEY is required")
    if errors:
        return blocked(project, AGENT, out, errors)
    assert manifest and verification
    firmware = json.loads(manifest.read_text(encoding="utf-8"))
    image = Path(firmware["image"])
    results = []
    sbom = out / "01_sbom"
    results.append(run_action(project, AGENT, "GenerateSbom", [PYTHON, "tools/security_supply_chain.py", "sbom", "--root", str(image), "--out", str(sbom / "sbom.json")], [target, manifest, image], target, sbom))
    if not results[-1]["handoff_ready"]:
        return finish(project, AGENT, out, results, 3)
    scan = out / "02_scan"
    results.append(run_action(project, AGENT, "VerifyDependencyProvenance", [PYTHON, "tools/security_supply_chain.py", "firmware-scan", "--firmware-manifest", str(manifest), "--out", str(scan / "dependency_provenance_report.json")], [target, manifest, Path(results[-1]["result_path"])], target, scan))
    if not results[-1]["handoff_ready"]:
        return finish(project, AGENT, out, results, 3)
    sign = out / "03_sign"
    sign.mkdir(parents=True, exist_ok=True)
    for source in (manifest, verification, sbom / "sbom.json", scan / "dependency_provenance_report.json"):
        shutil.copyfile(source, sign / source.name)
    results.append(run_action(project, AGENT, "SignRelease", [PYTHON, "tools/security_supply_chain.py", "attest", "--subject", str(manifest), "--out", str(sign / "signed_provenance.json")], [target, manifest, Path(results[-1]["result_path"])], target, sign))
    return finish(project, AGENT, out, results, 3, ["online CVE scanning and vendor-key signing remain external release gates"])

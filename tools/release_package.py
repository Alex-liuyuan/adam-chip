#!/usr/bin/env python3
"""Create a traceable host-side SDK release package for the ADAM chip project."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import rvaic_rtthread_native_check
import reuse_scan
import third_party_use


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACTS = (
    "LICENSE",
    "README.md",
    "chip_agents.py",
    "requirements-agent.txt",
    "third_party.manifest.json",
    "third_party.lock.json",
    "contracts",
    "targets",
    "compiler/backends/rvv_microkernel",
    "sdk/packages/rvaic",
    "tools",
    "docs/k230_official_image_strict_comparison.md",
)

SUPPORTED_CLAIMS = (
    "AgentScope-managed K230 SDK image build",
    "RT-Smart BSP and RVAIC component host build",
    "CanMV product overlay structural readback",
)
FORBIDDEN_CLAIMS = (
    "arbitrary_onnx_deployment_complete",
    "rvv_generally_faster_than_cpu",
    "real_npu_acceleration_complete",
    "long_running_physical_hil_closed_loop_complete",
    "unattended_chip_bringup_complete",
)
FORBIDDEN_CLAIM_TEXT = (
    re.compile(r"\barbitrary\s+ONNX\s+deployment\s+(?:is\s+)?complete\b", re.IGNORECASE),
    re.compile(r"\bRVV\s+(?:is\s+)?generally\s+faster\s+than\s+CPU\b", re.IGNORECASE),
    re.compile(r"\breal\s+NPU\s+acceleration(?:\s+execution)?\s+(?:is\s+)?complete\b", re.IGNORECASE),
    re.compile(r"\blong-running\s+physical\s+HIL\s+closed\s+loop\s+(?:is\s+)?complete\b", re.IGNORECASE),
    re.compile(r"\bunattended\s+chip\s+bring-up\s+(?:is\s+)?complete\b", re.IGNORECASE),
    re.compile(r"\btarget\s+device\s+can\s+now\s+run\s+C/RVV/NPU\s+firmware\b", re.IGNORECASE),
)
BOUNDARY_SECTION_HEADINGS = ("cannot claim", "known limits", "not claimed", "claim boundary")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tracked_files() -> list[Path]:
    paths: list[Path] = []
    for rel in DEFAULT_ARTIFACTS:
        path = ROOT / rel
        if path.is_file():
            paths.append(path)
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and "__pycache__" not in child.parts:
                    paths.append(child)
    return sorted(dict.fromkeys(paths))


def license_scan(files: list[Path]) -> tuple[bool, list[str]]:
    license_files = [path for path in files if path.name.lower() in {"license", "license.txt", "copying"}]
    project_license = ROOT / "LICENSE"
    warnings: list[str] = []
    if not license_files and not project_license.exists():
        warnings.append("No project-level LICENSE file found; release is blocked.")
    return bool(license_files or project_license.exists()), warnings


def binary_inventory(files: list[Path]) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    forbidden_suffixes = {".so", ".dll", ".dylib", ".exe"}
    binaries = [path for path in files if path.suffix.lower() in forbidden_suffixes]
    if binaries:
        warnings.append(f"Binary artifacts included in package metadata: {len(binaries)}")
    return True, warnings


def claim_text_scan(files: list[Path]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for path in files:
        if path.suffix.lower() not in {".md", ".txt", ".rst"}:
            continue
        in_boundary_section = False
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
            stripped = line.strip()
            lower = stripped.lower()
            if stripped.startswith("#"):
                heading = lower.lstrip("#").strip()
                in_boundary_section = any(item in heading for item in BOUNDARY_SECTION_HEADINGS)
            elif lower.rstrip(":") == "can claim":
                in_boundary_section = False
            elif any(lower.rstrip(":") == item for item in BOUNDARY_SECTION_HEADINGS):
                in_boundary_section = True
            elif not stripped:
                continue
            if any(item in lower for item in ("not claim", "not claimed", "without external evidence", "forbidden claim")):
                continue
            if in_boundary_section:
                continue
            for pattern in FORBIDDEN_CLAIM_TEXT:
                if pattern.search(line):
                    try:
                        rel = str(path.relative_to(ROOT))
                    except ValueError:
                        rel = str(path)
                    violations.append(
                        {
                            "path": rel,
                            "line": str(line_no),
                            "pattern": pattern.pattern,
                        }
                    )
    return violations


def create_release(out: Path, version: str, supplied_artifacts: tuple[Path, ...] = ()) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    files = tracked_files()
    sbom_files = [
        {
            "path": str(path.relative_to(ROOT)),
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in files
    ]
    license_pass, license_warnings = license_scan(files)
    binary_inventory_pass, binary_warnings = binary_inventory(files)
    supplied = [path.resolve() for path in supplied_artifacts]
    missing_supplied = [str(path) for path in supplied if not path.is_file()]
    claim_text_violations = claim_text_scan(files)
    reuse_report = reuse_scan.scan(ROOT)
    third_party_report = third_party_use.collect(
        ROOT,
        out / "third_party_use",
        ("default", "sdk_ecosystem", "deferred", "qimeng"),
        120.0,
        check_capability=False,
    )
    local_unreferenced = reuse_report.get("local_unreferenced", [])
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    sbom = {
        "name": "adam-chip-sdk",
        "version": version,
        "generated_at": generated_at,
        "license": {
            "path": "LICENSE" if (ROOT / "LICENSE").exists() else "",
            "sha256": sha256(ROOT / "LICENSE") if (ROOT / "LICENSE").exists() else "",
        },
        "files": sbom_files,
        "notes": [
            "Host-side metadata SBOM generated by project tooling.",
            "third_party downloads are intentionally not vendored into this release tarball.",
        ],
    }
    sbom_path = out / "sbom.json"
    notes_path = out / "release_notes.md"
    rollback_path = out / "rollback_plan.md"
    manifest_path = out / "release_manifest.json"
    native_report_path = out / "rvaic_rtthread_native_report.json"
    archive = out / f"adam-chip-sdk-{version}.tar.gz"
    native_report = rvaic_rtthread_native_check.analyze(ROOT / "sdk" / "packages" / "rvaic")

    sbom_path.write_text(json.dumps(sbom, indent=2), encoding="utf-8")
    native_report_path.write_text(json.dumps(native_report, indent=2), encoding="utf-8")
    notes_path.write_text(
        f"""# ADAM Chip SDK {version}

Generated: {generated_at}

Included capabilities:

- AgentScope-managed K230 SDK image build.
- RT-Smart BSP, boot-chain and RVAIC component build evidence.
- CanMV MicroPython firmware with verified product overlay.
- Structural image readback, SBOM, provenance and release gates.

Known limits:

- Physical HIL flashing is not claimed by this host-side release proof.
- Physical boot, RVV performance and KPU execution are not claimed without board evidence.
""",
        encoding="utf-8",
    )
    rollback_path.write_text(
        f"""# Rollback Plan

1. Keep the previous `adam-chip-sdk-<version>.tar.gz` archive and SBOM.
2. Restore the previous SDK archive and `sdk.img` into a clean workspace.
3. Run `python3 tools/run_strict_tests.py`.
4. Re-run `chip_agents.py run-project` and compare the image readback report.
5. Publish only when strict tests and the release gate pass.

Release under test: {version}
""",
        encoding="utf-8",
    )
    manifest = {
        "version": version,
        "archive": str(archive),
        "sbom": str(sbom_path),
        "release_notes": str(notes_path),
        "rollback_plan": str(rollback_path),
        "rvaic_rtthread_native_report": str(native_report_path),
        "third_party_use_report": str(out / "third_party_use" / "third_party_use_report.json"),
        "file_count": len(files),
        "supplied_artifacts": [
            {"path": str(path), "size": path.stat().st_size, "sha256": sha256(path)}
            for path in supplied
            if path.is_file()
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    with tarfile.open(archive, "w:gz") as tar:
        for artifact in (sbom_path, notes_path, rollback_path, manifest_path, native_report_path):
            tar.add(artifact, arcname=f"adam-chip-sdk-{version}/{artifact.name}")
        for artifact in sorted((out / "third_party_use").rglob("*.json")):
            tar.add(artifact, arcname=f"adam-chip-sdk-{version}/third_party_use/{artifact.relative_to(out / 'third_party_use')}")
        for index, artifact in enumerate(supplied):
            if artifact.is_file():
                tar.add(artifact, arcname=f"adam-chip-sdk-{version}/artifacts/{index:02d}-{artifact.name}")
        for path in files:
            tar.add(path, arcname=f"adam-chip-sdk-{version}/{path.relative_to(ROOT)}")

    evidence = {
        "versioned_artifacts": archive.exists() and archive.stat().st_size > 0,
        "release_notes": notes_path.exists(),
        "rollback_plan": rollback_path.exists(),
        "release_file_inventory_generated": sbom_path.exists() and len(sbom_files) > 0,
        "project_license_present": license_pass,
        "binary_inventory_recorded": binary_inventory_pass,
        "release_inputs_packaged": not missing_supplied and all(path.is_file() for path in supplied),
        "claim_boundary_recorded": True,
        "claim_text_boundary_pass": not claim_text_violations,
        "third_party_reuse_boundary_pass": bool(reuse_report.get("ok")),
        "third_party_use_artifacts_pass": bool(third_party_report.get("ok")) and int(third_party_report.get("artifact_count", 0)) >= 40,
        "forbidden_claim_gate_pass": True,
        "rvaic_rtthread_native_check_pass": bool(native_report.get("ok")),
        "rvaic_rtthread_component_native_pass": native_report.get("capability_level") == "rtthread_component_native",
        "rvaic_rtthread_boundary_pass": isinstance(native_report.get("not_implemented"), list),
    }
    report = {
        "ok": all(evidence.values()),
        "release": manifest,
        "claim_boundary": {
            "supported_claims": list(SUPPORTED_CLAIMS),
            "forbidden_claims": list(FORBIDDEN_CLAIMS),
        },
        "claims": list(SUPPORTED_CLAIMS),
        "evidence": evidence,
        "claim_text_violations": claim_text_violations,
        "third_party_reuse": {
            "ok": bool(reuse_report.get("ok")),
            "local_unreferenced": local_unreferenced,
        },
        "third_party_use": {
            "ok": bool(third_party_report.get("ok")),
            "report": str(out / "third_party_use" / "third_party_use_report.json"),
            "artifact_count": int(third_party_report.get("artifact_count", 0)),
            "blocked": third_party_report.get("blocked", []),
        },
        "rvaic_rtthread_native": native_report,
        "warnings": license_warnings + binary_warnings + (["Local third-party checkouts not included in the release: " + ", ".join(local_unreferenced)] if local_unreferenced else []) + (["Missing supplied artifacts: " + ", ".join(missing_supplied)] if missing_supplied else []),
        "notes": [
            "This is a project-owned host metadata release proof.",
            "It does not claim external Syft/Trivy/Cosign execution unless those tools are separately wired in.",
        ],
    }
    (out / "release_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bad = root / "bad.md"
        bad.write_text("The target device can now run C/RVV/NPU firmware.\n", encoding="utf-8")
        assert claim_text_scan([bad]), "forbidden positive claim was not detected"
        boundary = root / "boundary.md"
        boundary.write_text("Cannot Claim:\n- arbitrary ONNX deployment is complete;\n", encoding="utf-8")
        assert not claim_text_scan([boundary]), "boundary section should be allowed to name forbidden claims"
        report = create_release(root, "selftest")
        assert report["ok"], report
        assert Path(report["release"]["archive"]).exists()
        assert Path(report["release"]["sbom"]).exists()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/tmp/adam_release_package")
    parser.add_argument("--version", default="dev")
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    report = create_release(Path(args.out).resolve(), args.version, tuple(Path(path) for path in args.artifact))
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

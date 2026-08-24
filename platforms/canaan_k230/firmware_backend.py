"""Build a complete editable CanMV K230 firmware image."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from . import ROOT, contract_path, ensure_tools_path

ensure_tools_path()

from tools import k230_image_analyze, k230_image_compose, product_image_verify


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def build(config: dict[str, Any], out: Path, *, reuse_existing: bool = False) -> dict[str, Any]:
    source = _resolve(str(config["source"]))
    script = _resolve(str(config["build_script"]))
    artifact = _resolve(str(config["artifact"]))
    source_lock = _resolve(str(config["source_lock"]))
    dockerfile = source / "repro/Dockerfile"
    out.mkdir(parents=True, exist_ok=True)
    blockers = []
    for label, path in (("source", source), ("build_script", script), ("source_lock", source_lock), ("Dockerfile", dockerfile)):
        if not path.exists():
            blockers.append(f"{label} is missing: {path}")
    if blockers:
        return _write(out, {"ok": False, "blockers": blockers, "evidence": {}})

    build_result = {"skipped": True, "reason": "verified existing artifact requested"}
    if not reuse_existing:
        proc = subprocess.run(
            [str(script)],
            cwd=source,
            env=os.environ.copy(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        (out / "build.log").write_text(proc.stdout, encoding="utf-8", errors="ignore")
        build_result = {"skipped": False, "returncode": proc.returncode, "log": str(out / "build.log")}
        if proc.returncode != 0:
            blockers.append("CanMV editable build failed")
    if not artifact.is_file():
        blockers.append(f"firmware artifact is missing: {artifact}")
        return _write(out, {"ok": False, "blockers": blockers, "build": build_result, "evidence": {}})

    final_artifact = artifact
    overlay_result: dict[str, Any] = {"ok": True, "skipped": True}
    if config.get("overlay"):
        overlay = _resolve(str(config["overlay"]))
        if not overlay.is_dir():
            blockers.append(f"product overlay is missing: {overlay}")
        else:
            overlay_result = k230_image_compose.compose(
                artifact,
                out / "product_image",
                overlay,
                target=contract_path("target"),
                install_main=bool(config.get("install_main", False)),
            )
            if overlay_result.get("ok"):
                final_artifact = Path(str(overlay_result["image"]))
            else:
                blockers.append("product overlay injection failed")
    analysis = k230_image_analyze.analyze(final_artifact, out / "image_analysis")
    product_verification: dict[str, Any] = {"ok": True, "skipped": True, "evidence": {}}
    if config.get("overlay") and config.get("product") and final_artifact != artifact:
        product_verification = product_image_verify.verify(
            final_artifact,
            artifact,
            _resolve(str(config["overlay"])),
            _resolve(str(config["product"])),
            out / "product_verification",
        )
        if not product_verification.get("ok"):
            blockers.append("product image readback verification failed")
    contract = json.loads(contract_path("image").read_text(encoding="utf-8"))
    expected_parts = {(int(item["index"]), int(item["start_lba"]), int(item["sectors"])) for item in contract["partitions"]}
    actual_parts = {(int(item["index"]), int(item["start_lba"]), int(item["sectors"])) for item in analysis["partitions"]}
    components = {
        "uboot": source / "output/k230_canmv_v3p0_defconfig/uboot/u-boot.bin",
        "opensbi": source / "output/k230_canmv_v3p0_defconfig/opensbi/opensbi.bin",
        "rt_smart": source / "output/k230_canmv_v3p0_defconfig/opensbi/rtthread.bin",
        "micropython": source / "output/k230_canmv_v3p0_defconfig/canmv/micropython",
    }
    docker_text = dockerfile.read_text(encoding="utf-8", errors="ignore")
    checkout_lock = source / "repro/manifest.lock.xml"
    evidence = {
        "firmware_image_created": final_artifact.stat().st_size == int(contract["image_size_bytes"]),
        "mbr_signature_pass": bool(analysis["partitions"]),
        "partition_layout_pass": expected_parts <= actual_parts,
        "boot_region_present": bool(analysis["pre_partition_boot_region"]["required_for_boot"]),
        "firmware_components_present": all(path.is_file() and path.stat().st_size > 0 for path in components.values()),
        "source_lock_present": len(ET.parse(source_lock).getroot().findall("project")) == 20,
        "source_lock_matches_checkout": checkout_lock.is_file() and source_lock.read_bytes() == checkout_lock.read_bytes(),
        "container_digest_pinned": "FROM " in docker_text and "@sha256:" in docker_text,
        "micropython_image_layout_pass": len(analysis["partitions"]) >= 2,
        "product_overlay_applied": bool(not config.get("overlay") or overlay_result.get("ok")),
        "overlay_readback_pass": bool(not config.get("overlay") or product_verification.get("evidence", {}).get("overlay_readback_pass")),
        "boot_region_preserved": bool(not config.get("overlay") or product_verification.get("evidence", {}).get("boot_region_preserved")),
    }
    image_link = out / "firmware.img"
    image_link.unlink(missing_ok=True)
    image_link.symlink_to(final_artifact)
    manifest = {
        "schema": "adam.firmware_manifest.v1",
        "platform": "canaan_k230",
        "backend": "canmv-editable",
        "self_hosted_boot_chain": True,
        "source": str(source),
        "source_lock": str(source_lock),
        "image": str(image_link),
        "image_source": str(final_artifact),
        "base_image": str(artifact),
        "image_size_bytes": final_artifact.stat().st_size,
        "image_sha256": _sha256(final_artifact),
        "components": {name: str(path) for name, path in components.items()},
        "build": build_result,
        "overlay": overlay_result,
        "product_verification": product_verification,
    }
    (out / "firmware_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return _write(out, {"ok": all(evidence.values()) and not blockers, "blockers": blockers, "build": build_result, "manifest": manifest, "evidence": evidence})


def _write(out: Path, report: dict[str, Any]) -> dict[str, Any]:
    report.setdefault("schema", "adam.firmware_build.v1")
    out.mkdir(parents=True, exist_ok=True)
    (out / "firmware_build_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report

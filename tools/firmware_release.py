#!/usr/bin/env python3
"""Stage a verified complete firmware image and its rollback image for release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _stage(source: Path, target: Path) -> None:
    target.unlink(missing_ok=True)
    try:
        os.link(source.resolve(), target)
    except OSError:
        shutil.copyfile(source, target)


def stage(manifest_path: Path, verification_path: Path, out: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    image = Path(manifest["image"])
    rollback = Path(manifest["base_image"])
    out.mkdir(parents=True, exist_ok=True)
    staged = out / "sdk.img"
    staged_rollback = out / "rollback.img"
    _stage(image, staged)
    _stage(rollback, staged_rollback)
    shutil.copyfile(manifest_path, out / "firmware_manifest.json")
    shutil.copyfile(verification_path, out / "product_image_verify_report.json")
    evidence = {
        "firmware_image_staged": staged.is_file() and staged.stat().st_size > 0,
        "rollback_image_staged": staged_rollback.is_file() and staged_rollback.stat().st_size > 0,
        "image_hash_match_pass": digest(staged) == manifest.get("image_sha256"),
        "product_image_verified_pass": bool(verification.get("ok")),
        "self_hosted_boot_chain": bool(manifest.get("self_hosted_boot_chain")),
    }
    report = {"ok": all(evidence.values()), "image": str(staged), "rollback_image": str(staged_rollback), "firmware_manifest": str(out / "firmware_manifest.json"), "evidence": evidence}
    (out / "firmware_release_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        image = root / "image.img"
        rollback = root / "base.img"
        image.write_bytes(b"firmware")
        rollback.write_bytes(b"rollback")
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"image": str(image), "base_image": str(rollback), "image_sha256": digest(image), "self_hosted_boot_chain": True}), encoding="utf-8")
        verification = root / "verification.json"
        verification.write_text(json.dumps({"ok": True}), encoding="utf-8")
        report = stage(manifest, verification, root / "out")
        assert report["ok"], report
        assert (root / "out/sdk.img").read_bytes() == b"firmware"
        assert (root / "out/rollback.img").read_bytes() == b"rollback"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest")
    parser.add_argument("--verification")
    parser.add_argument("--out")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    if not all((args.manifest, args.verification, args.out)):
        parser.error("--manifest, --verification and --out are required")
    report = stage(Path(args.manifest).resolve(), Path(args.verification).resolve(), Path(args.out).resolve())
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

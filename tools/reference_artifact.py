#!/usr/bin/env python3
"""Validate that a regression artifact is immutable and reference-only."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(data: dict[str, Any]) -> list[str]:
    errors = []
    if data.get("schema") != "soc-image.reference-artifact.v1":
        errors.append("invalid reference artifact schema")
    if data.get("role") != "reference_only":
        errors.append("reference artifact role must be reference_only")
    if data.get("build_input_allowed") is not False:
        errors.append("reference artifact must be forbidden as a build input")
    if not isinstance(data.get("sha256"), str) or len(data["sha256"]) != 64:
        errors.append("reference artifact sha256 is invalid")
    if not isinstance(data.get("bytes"), int) or data["bytes"] < 1:
        errors.append("reference artifact size is invalid")
    if not data.get("prohibited_uses"):
        errors.append("reference artifact prohibited_uses is required")
    return errors


def verify(manifest_path: Path) -> dict[str, Any]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors = validate_manifest(data)
    artifact = ROOT / str(data.get("path", ""))
    if not artifact.is_file():
        errors.append(f"reference artifact is missing: {artifact}")
    else:
        if artifact.stat().st_size != data.get("bytes"):
            errors.append("reference artifact size mismatch")
        if _sha256(artifact) != data.get("sha256"):
            errors.append("reference artifact sha256 mismatch")
    return {"ok": not errors, "manifest": str(manifest_path), "artifact": str(artifact), "errors": errors}


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        artifact = Path(tmp) / "reference.img"
        artifact.write_bytes(b"reference")
        good = {
            "schema": "soc-image.reference-artifact.v1",
            "role": "reference_only",
            "build_input_allowed": False,
            "sha256": _sha256(artifact),
            "bytes": artifact.stat().st_size,
            "prohibited_uses": ["build_input"],
        }
        assert not validate_manifest(good)
        bad = dict(good, build_input_allowed=True)
        assert validate_manifest(bad)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    if not args.manifest:
        parser.error("--manifest is required unless --selftest is used")
    report = verify(Path(args.manifest).resolve())
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

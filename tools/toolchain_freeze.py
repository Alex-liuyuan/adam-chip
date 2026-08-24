#!/usr/bin/env python3
"""Resolve and smoke-test the toolchains declared by platform contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def resolve_prefix(value: str) -> str:
    if "/" in value:
        prefix = Path(value)
        prefix = prefix if prefix.is_absolute() else ROOT / prefix
        return str(prefix) if Path(str(prefix) + "gcc").is_file() else ""
    return value if shutil.which(value + "gcc") else ""


def inspect_toolchain(role: str, spec: dict) -> dict:
    prefix = resolve_prefix(str(spec.get("prefix", "")))
    gcc = Path(prefix + "gcc") if prefix else Path("missing")
    version = ""
    smoke_ok = False
    smoke_output = ""
    if gcc.is_file():
        version_proc = subprocess.run([str(gcc), "--version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        version = version_proc.stdout.splitlines()[0] if version_proc.stdout else ""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "smoke.c"
            obj = Path(tmp) / "smoke.o"
            source.write_text("int adam_toolchain_smoke(int x) { return x + 1; }\n", encoding="utf-8")
            proc = subprocess.run([str(gcc), f"-march={spec['isa']}", f"-mabi={spec['abi']}", "-c", str(source), "-o", str(obj)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
            smoke_output = proc.stdout
            smoke_ok = proc.returncode == 0 and obj.is_file()
    actual_sha256 = hashlib.sha256(gcc.read_bytes()).hexdigest() if gcc.is_file() else ""
    expected_sha256 = str(spec.get("gcc_sha256", ""))
    identity_ok = bool(actual_sha256 and expected_sha256 and actual_sha256 == expected_sha256)
    return {
        "role": role,
        "ok": bool(prefix and gcc.is_file() and smoke_ok and identity_ok),
        "prefix": prefix,
        "gcc": str(gcc) if gcc.is_file() else "",
        "gcc_sha256": actual_sha256,
        "expected_gcc_sha256": expected_sha256,
        "identity_pass": identity_ok,
        "version": version,
        "isa": spec.get("isa", ""),
        "abi": spec.get("abi", ""),
        "smoke_output": smoke_output,
    }


def freeze(platform: str, target_path: Path, boot_path: Path | None, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    target = json.loads(target_path.read_text(encoding="utf-8"))
    bsp_spec = target.get("toolchains", {}).get("bsp", {"prefix": target.get("toolchain_prefix", ""), "isa": target["isa"], "abi": target["abi"]})
    specs = {"bsp": bsp_spec}
    if boot_path:
        boot = json.loads(boot_path.read_text(encoding="utf-8"))
        specs["boot"] = boot.get("build", {}).get("toolchain", {})
    toolchains = {role: inspect_toolchain(role, spec) for role, spec in specs.items()}
    ok = bool(toolchains) and all(item["ok"] for item in toolchains.values())
    report = {
        "schema": "adam.toolchain_freeze.v1",
        "ok": ok,
        "platform": platform,
        "target": str(target_path),
        "boot_contract": str(boot_path) if boot_path else "",
        "toolchains": toolchains,
        "evidence": {"cross_toolchain_pass": ok},
    }
    (out / "toolchain_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--boot-contract")
    parser.add_argument("--out", required=True)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        assert resolve_prefix("missing-prefix-") == ""
        print("ok")
        return 0
    report = freeze(args.platform, Path(args.target).resolve(), Path(args.boot_contract).resolve() if args.boot_contract else None, Path(args.out).resolve())
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

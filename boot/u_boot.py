"""Contract-driven out-of-tree U-Boot builds."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def executable(prefix: str, name: str) -> str:
    candidate = prefix + name
    return shutil.which(candidate) or (candidate if Path(candidate).is_file() else "")


def python_with_modules(root: Path, modules: list[str]) -> str:
    for candidate in (Path(sys.executable), root / ".venv/bin/python"):
        if not candidate.is_file():
            continue
        command = [str(candidate), "-c", "; ".join(f"import {name}" for name in modules)]
        if subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0:
            return str(candidate)
    return ""


def run(command: list[str], cwd: Path, env: dict[str, str], log: Path) -> bool:
    proc = subprocess.run(command, cwd=str(cwd), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(proc.stdout, encoding="utf-8", errors="replace")
    return proc.returncode == 0


def verify(build_dir: Path, config: dict[str, Any], cross_prefix: str) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    artifacts: dict[str, Any] = {}
    for item in config.get("artifacts", []):
        path = build_dir / item["path"]
        magic = str(item.get("magic_ascii", "")).encode("ascii")
        present = path.is_file() and path.stat().st_size >= int(item.get("min_bytes", 1))
        magic_ok = present and (not magic or path.read_bytes()[: len(magic)] == magic)
        artifacts[item["name"]] = {
            "path": str(path),
            "present": present,
            "bytes": path.stat().st_size if path.is_file() else 0,
            "magic_pass": magic_ok,
            "sha256": sha256(path) if present else "",
        }
        if not present or not magic_ok:
            blockers.append(f"invalid boot artifact: {item['name']}")

    symbol_checks = []
    nm = executable(cross_prefix, "nm")
    for item in config.get("symbol_checks", []):
        path = build_dir / item["artifact"]
        output = ""
        if nm and path.is_file():
            proc = subprocess.run([nm, str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
            output = proc.stdout if proc.returncode == 0 else ""
        missing = [symbol for symbol in item.get("required", []) if symbol not in output]
        symbol_checks.append({"artifact": str(path), "required": item.get("required", []), "missing": missing, "ok": not missing})
        if missing:
            blockers.append("missing linked symbols: " + ", ".join(missing))

    dot_config = (build_dir / ".config").read_text(encoding="utf-8", errors="replace") if (build_dir / ".config").is_file() else ""
    missing_config = [line for line in config.get("required_config", []) if line not in dot_config.splitlines()]
    if missing_config:
        blockers.append("missing U-Boot config: " + ", ".join(missing_config))
    return {
        "artifacts": artifacts,
        "symbol_checks": symbol_checks,
        "required_config": config.get("required_config", []),
        "missing_config": missing_config,
    }, blockers


def build(root: Path, contract_path: Path, out: Path, cross_prefix: str, jobs: int = 1) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    config = contract["build"]
    source = (root / config["source"]).resolve()
    build_dir = out / "build"
    out.mkdir(parents=True, exist_ok=True)
    blockers = []
    if config.get("cross_compile_required") and not cross_prefix:
        blockers.append("cross compiler prefix is required by the boot contract")
    gcc = executable(cross_prefix, "gcc")
    if not gcc:
        blockers.append(f"cross compiler not found: {cross_prefix}gcc")
    python_modules = list(config.get("python_modules", []))
    host_python = python_with_modules(root, python_modules)
    if not host_python:
        blockers.append("no Python interpreter provides modules: " + ", ".join(python_modules))
    actual_revision = ""
    if source.is_dir():
        proc = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
        actual_revision = proc.stdout.strip() if proc.returncode == 0 else ""
    if actual_revision != config.get("source_revision"):
        blockers.append(f"source revision mismatch: expected {config.get('source_revision')}, got {actual_revision or 'none'}")

    configured = built = False
    if not blockers:
        env = os.environ.copy()
        env.update(
            {
                "ARCH": config.get("arch", "riscv"),
                "CROSS_COMPILE": cross_prefix,
                "SOURCE_DATE_EPOCH": str(config.get("source_date_epoch", 0)),
                "GZIP": "-n",
            }
        )
        env["PATH"] = str(Path(host_python).parent) + os.pathsep + env.get("PATH", "")
        configured = run(["make", "-C", str(source), f"O={build_dir}", config["defconfig"]], root, env, out / "configure.log")
        if not configured:
            blockers.append("U-Boot defconfig failed")
        else:
            built = run(["make", "-C", str(build_dir), f"-j{max(1, jobs)}"], root, env, out / "build.log")
            if not built:
                blockers.append("U-Boot build failed")

    verification, verify_blockers = verify(build_dir, config, cross_prefix) if built else ({"artifacts": {}, "symbol_checks": []}, [])
    blockers.extend(verify_blockers)
    compiler_version = ""
    if gcc:
        compiler_version = subprocess.run([gcc, "--version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False).stdout.splitlines()[0]
    report = {
        "schema": "adam.boot_source_build.v1",
        "ok": not blockers,
        "contract": str(contract_path),
        "source": str(source),
        "source_revision": actual_revision,
        "defconfig": config.get("defconfig"),
        "cross_prefix": cross_prefix,
        "compiler_version": compiler_version,
        "host_python": host_python,
        "configured": configured,
        "built": built,
        "verification": verification,
        "evidence": {
            "source_revision_pass": actual_revision == config.get("source_revision"),
            "spl_build_pass": bool(verification.get("artifacts", {}).get("spl", {}).get("present")),
            "ddr_init_link_pass": bool(verification.get("symbol_checks")) and all(item["ok"] for item in verification.get("symbol_checks", [])),
            "uboot_build_pass": bool(verification.get("artifacts", {}).get("uboot", {}).get("present")),
            "physical_boot_pass": False,
        },
        "blockers": blockers,
        "not_claimed": ["source build evidence is not image integration, flash, or physical boot evidence"],
    }
    (out / "boot_build_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report

"""Build and verify a pinned RT-Thread BSP source tree."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_output(command: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
    proc = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return proc.returncode, proc.stdout


def verify(artifacts: Path, toolchain_bin: Path, required_symbols: list[str], required_objects: list[str]) -> tuple[dict[str, Any], list[str]]:
    elf, binary, link_map = (artifacts / name for name in ("rtthread.elf", "rtthread.bin", "rtthread.map"))
    blockers = [f"missing BSP artifact: {path.name}" for path in (elf, binary, link_map) if not path.is_file()]
    prefix = toolchain_bin / "riscv64-unknown-linux-musl-"
    readelf = Path(str(prefix) + "readelf")
    nm = Path(str(prefix) + "nm")
    _, header = command_output([str(readelf), "-h", str(elf)]) if readelf.is_file() and elf.is_file() else (1, "")
    _, symbols = command_output([str(nm), str(elf)]) if nm.is_file() and elf.is_file() else (1, "")
    map_text = link_map.read_text(encoding="utf-8", errors="replace") if link_map.is_file() else ""
    missing_symbols = [name for name in required_symbols if not re.search(rf"\b{re.escape(name)}$", symbols, re.MULTILINE)]
    missing_objects = [name for name in required_objects if name not in map_text]
    machine_pass = "Machine:                           RISC-V" in header
    entry_match = re.search(r"Entry point address:\s+(0x[0-9a-fA-F]+)", header)
    entry = entry_match.group(1) if entry_match else ""
    if not machine_pass:
        blockers.append("rtthread.elf is not a RISC-V ELF")
    if not entry or int(entry, 16) == 0:
        blockers.append("rtthread.elf has no valid entry point")
    if missing_symbols:
        blockers.append("missing BSP symbols: " + ", ".join(missing_symbols))
    if missing_objects:
        blockers.append("missing BSP objects: " + ", ".join(missing_objects))
    return {
        "artifacts": {
            path.name: {"path": str(path), "bytes": path.stat().st_size if path.is_file() else 0, "sha256": sha256(path) if path.is_file() else ""}
            for path in (elf, binary, link_map)
        },
        "machine": "RISC-V" if machine_pass else "",
        "entry": entry,
        "required_symbols": required_symbols,
        "missing_symbols": missing_symbols,
        "required_objects": required_objects,
        "missing_objects": missing_objects,
    }, blockers


def build(root: Path, out: Path, spec: dict[str, Any], toolchain_bin: Path, scons: Path, jobs: int = 1) -> dict[str, Any]:
    source_repo = (root / spec["source_repo"]).resolve()
    bsp_dir = source_repo / spec["bsp_path"]
    rtt_root = source_repo / spec["rtthread_path"]
    out.mkdir(parents=True, exist_ok=True)
    artifacts = out / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    blockers: list[str] = []

    revision_rc, revision = command_output(["git", "-C", str(source_repo), "rev-parse", "HEAD"]) if source_repo.is_dir() else (1, "")
    revision = revision.strip() if revision_rc == 0 else ""
    if revision != spec["source_revision"]:
        blockers.append(f"source revision mismatch: expected {spec['source_revision']}, got {revision or 'none'}")
    diff_rc = subprocess.run(["git", "-C", str(source_repo), "diff", "--quiet"], check=False).returncode if source_repo.is_dir() else 1
    if diff_rc:
        blockers.append("pinned BSP source has tracked modifications")

    gcc = toolchain_bin / "riscv64-unknown-linux-musl-gcc"
    if not gcc.is_file():
        blockers.append(f"missing RT-Smart musl compiler: {gcc}")
    scons_libs = list((scons.parent.parent / "lib").glob("python*/site-packages/scons"))
    scons_lib = scons_libs[0] if scons_libs else Path()
    version_env = os.environ.copy()
    version_env["SCONS_LIB_DIR"] = str(scons_lib)
    version_rc, scons_version = command_output([str(scons), "--version"], version_env) if scons.is_file() else (1, "")
    if version_rc or "3.1.2" not in scons_version:
        blockers.append("SCons 3.1.2 is required")
    missing_sources = [name for name in spec.get("required_sources", []) if not (bsp_dir / name).is_file()]
    if missing_sources:
        blockers.append("missing BSP driver sources: " + ", ".join(missing_sources))

    generated = [bsp_dir / name for name in (".config", "cconfig.h", "rtthread.elf", "rtthread.bin", "rtthread.map")]
    previous = {path: path.read_bytes() for path in generated if path.is_file()}
    built = False
    try:
        if not blockers:
            (bsp_dir / ".config").write_text("CONFIG_RT_USING_MUSL=y\n", encoding="ascii")
            for path in generated[1:]:
                path.unlink(missing_ok=True)
            env = os.environ.copy()
            env.update(
                {
                    "SCONS_LIB_DIR": str(scons_lib),
                    "RTT_ROOT": str(rtt_root),
                    "RTT_SDK_BUILD_DIR": str(out / "objects"),
                    "RTT_EXEC_PATH": str(toolchain_bin),
                    "RTT_CC_PREFIX": "riscv64-unknown-linux-musl-",
                }
            )
            proc = subprocess.run(
                [str(scons), "-C", str(bsp_dir), f"-j{max(1, jobs)}"],
                cwd=str(root), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
            )
            (out / "build.log").write_text(proc.stdout, encoding="utf-8", errors="replace")
            built = proc.returncode == 0
            if not built:
                blockers.append("RT-Smart BSP SCons build failed")
            else:
                for name in ("rtthread.elf", "rtthread.bin", "rtthread.map"):
                    shutil.copy2(bsp_dir / name, artifacts / name)
    finally:
        for path in generated:
            if path in previous:
                path.write_bytes(previous[path])
            else:
                path.unlink(missing_ok=True)

    verification, verify_blockers = verify(artifacts, toolchain_bin, spec["required_symbols"], spec["required_objects"]) if built else ({}, [])
    blockers.extend(verify_blockers)
    config_text = (bsp_dir / "rtconfig.h").read_text(encoding="utf-8", errors="replace") if (bsp_dir / "rtconfig.h").is_file() else ""
    single_core_pass = "RT_USING_SMP" not in config_text and not re.search(r"#define\s+RT_CPUS_NR\s+[2-9]", config_text)
    if not single_core_pass:
        blockers.append("K230 RT-Smart BSP must remain a single-core AMP instance")
    compiler_version = command_output([str(gcc), "--version"])[1].splitlines()[0] if gcc.is_file() else ""
    report = {
        "schema": "adam.rtthread_source_build.v1",
        "ok": not blockers,
        "built": built,
        "source": str(bsp_dir),
        "source_revision": revision,
        "compiler_version": compiler_version,
        "scons_version": "3.1.2" if "3.1.2" in scons_version else "",
        "verification": verification,
        "evidence": {
            "source_revision_pass": revision == spec["source_revision"],
            "vendor_rtsmart_bsp_build_pass": built and not verify_blockers,
            "riscv_elf_pass": verification.get("machine") == "RISC-V",
            "entry_point_pass": bool(verification.get("entry")),
            "driver_stack_link_pass": built and not verification.get("missing_symbols") and not verification.get("missing_objects"),
            "required_driver_sources_pass": not missing_sources,
            "single_core_amp_pass": bool(single_core_pass),
            "physical_boot_pass": False,
        },
        "blockers": blockers,
        "not_claimed": ["BSP compile evidence is not physical K230 boot evidence"],
    }
    (out / "bsp_build_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report

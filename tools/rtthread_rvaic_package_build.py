#!/usr/bin/env python3
"""Install a generated .rvaic package into an RT-Thread BSP and run SCons."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    ignore = shutil.ignore_patterns(".git", "__pycache__", "*.o", "*.elf", "*.bin", ".sconsign.dblite")
    shutil.copytree(src, dst, ignore=ignore)


def append_define(path: Path, name: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if f"#define {name}" not in text:
        text += f"\n#define {name}\n"
        path.write_text(text, encoding="utf-8")


def append_sconscript(path: Path, child: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else "from building import *\ngroup = []\nReturn('group')\n"
    line = f"group += SConscript('{child}')"
    if line not in text:
        text = text.replace("Return('group')", f"{line}\n\nReturn('group')") if "Return('group')" in text else text + f"\nSConscript('{child}')\n"
        path.write_text(text, encoding="utf-8")


def patch_drop_libsupcxx(overlay: Path) -> bool:
    rtconfig = overlay / "rtconfig.py"
    if not rtconfig.exists():
        return False
    text = rtconfig.read_text(encoding="utf-8")
    patched = text.replace(" -lsupc++", "")
    if patched != text:
        rtconfig.write_text(patched, encoding="utf-8")
        return True
    return False


def model_sconscript(package: Path) -> str:
    with_tvm = all(
        (package / rel).exists()
        for rel in ("tvm_aot_bridge.c", "tvm_runtime_stubs.c", "tvm_export/lib0.c", "tvm/ffi/c_api.h")
    )
    tvm_sources = "\nsrc += ['tvm_aot_bridge.c', 'tvm_runtime_stubs.c', 'tvm_export/lib0.c']" if with_tvm else ""
    cppdefines = "CPPDEFINES = ['RVAIC_USE_TVM_AOT']" if with_tvm else "CPPDEFINES = []"
    return f"""from building import *

cwd = GetCurrentDir()
src = ['model.c', 'finsh.c']{tvm_sources}
CPPPATH = [cwd, cwd + '/../rvaic_runtime/include']
{cppdefines}
group = DefineGroup('rvaic_model', src, depend=['PKG_USING_RVAIC'], CPPPATH=CPPPATH, CPPDEFINES=CPPDEFINES)
Return('group')
"""


def install_package(package: Path, bsp: Path, runtime: Path, out: Path, drop_libsupcxx: bool) -> dict[str, Any]:
    overlay = out / "bsp_overlay"
    copy_tree(bsp, overlay)
    apps = overlay / "applications"
    apps.mkdir(exist_ok=True)

    runtime_dst = apps / "rvaic_runtime"
    model_dst = apps / "rvaic_model"
    copy_tree(runtime, runtime_dst)
    copy_tree(package, model_dst)
    append_sconscript(apps / "SConscript", "rvaic_runtime/SConscript")
    append_sconscript(apps / "SConscript", "rvaic_model/SConscript")

    (model_dst / "SConscript").write_text(model_sconscript(package), encoding="utf-8")
    append_define(overlay / "rtconfig.h", "PKG_USING_RVAIC")
    return {
        "overlay": str(overlay),
        "runtime": str(runtime_dst),
        "model": str(model_dst),
        "drop_libsupcxx_patch": patch_drop_libsupcxx(overlay) if drop_libsupcxx else False,
    }


def install_runtime(bsp: Path, runtime: Path, out: Path, drop_libsupcxx: bool) -> dict[str, Any]:
    overlay = out / "bsp_overlay"
    copy_tree(bsp, overlay)
    apps = overlay / "applications"
    apps.mkdir(exist_ok=True)
    runtime_dst = apps / "rvaic_runtime"
    copy_tree(runtime, runtime_dst)
    append_sconscript(apps / "SConscript", "rvaic_runtime/SConscript")
    append_define(overlay / "rtconfig.h", "PKG_USING_RVAIC")
    (overlay / ".config").write_text("CONFIG_RT_USING_MUSL=y\n", encoding="ascii")
    return {"overlay": str(overlay), "runtime": str(runtime_dst), "drop_libsupcxx_patch": patch_drop_libsupcxx(overlay) if drop_libsupcxx else False}


def rtthread_root_from_bsp(bsp: Path) -> Path | None:
    if bsp.parent.name == "bsp":
        root = bsp.parent.parent
        if (root / "tools/building.py").is_file():
            return root
        if (root / "rt-thread/tools/building.py").is_file():
            return root / "rt-thread"
    for parent in bsp.parents:
        candidate = parent / "rt-thread"
        if (candidate / "tools/building.py").is_file():
            return candidate
    return None


def make_picolibc_wrappers(out: Path, prefix: str) -> Path | None:
    wrapper_dir = out / "toolchain_wrappers"
    wrapper_dir.mkdir(exist_ok=True)
    for tool in ("gcc", "g++", "ar", "objcopy", "size", "objdump"):
        target = shutil.which(prefix + tool)
        if not target:
            return None
        wrapper = wrapper_dir / f"{prefix}{tool}"
        specs = " --specs=picolibc.specs" if tool in {"gcc", "g++"} else ""
        wrapper.write_text(f"#!/bin/sh\nexec {target}{specs} \"$@\"\n", encoding="utf-8")
        wrapper.chmod(0o755)
    return wrapper_dir


def run_scons(
    overlay: Path,
    scons: str,
    jobs: int,
    out: Path,
    rtt_root: Path | None,
    cross_prefix: str | None,
    picolibc: bool,
) -> tuple[bool, str, int]:
    if not shutil.which(scons) and not Path(scons).exists():
        return False, f"missing_scons: {scons}", 127
    env = os.environ.copy()
    scons_path = Path(scons).resolve()
    scons_libs = list((scons_path.parent.parent / "lib").glob("python*/site-packages/scons"))
    if scons_libs:
        env["SCONS_LIB_DIR"] = str(scons_libs[0])
    if rtt_root:
        env["RTT_ROOT"] = str(rtt_root)
    env["RTT_SDK_BUILD_DIR"] = str(out / "objects")
    if cross_prefix:
        env["RTT_CC_PREFIX"] = cross_prefix
    if picolibc:
        prefix = cross_prefix or "riscv64-unknown-elf-"
        wrapper_dir = make_picolibc_wrappers(out, prefix)
        if wrapper_dir:
            env["RTT_EXEC_PATH"] = str(wrapper_dir)
    proc = subprocess.run(
        [scons, "-C", str(overlay), f"-j{jobs}"],
        cwd=str(ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log = out / "scons.log"
    log.write_text(proc.stdout, encoding="utf-8")
    return proc.returncode == 0, str(log), proc.returncode


def build(
    package: Path | None,
    bsp: Path,
    runtime: Path,
    out: Path,
    scons: str,
    jobs: int,
    cross_prefix: str | None,
    picolibc: bool,
    drop_libsupcxx: bool,
) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    evidence = {
        "rtthread_bsp_present": bsp.exists(),
        "rvaic_package_present": package is None or ((package / "model.c").exists() and (package / "SConscript").exists()),
        "rvaic_runtime_present": (runtime / "SConscript").exists() and (runtime / "include" / "rvaic.h").exists(),
        "rtthread_application_sconscript_reuse": "SConscript" in (bsp / "applications" / "SConscript").read_text(encoding="utf-8", errors="ignore")
        if (bsp / "applications" / "SConscript").exists()
        else False,
        "rvaic_runtime_installed": False,
        "rvaic_model_sconscript_installed": False,
        "tvm_aot_bridge_preserved": True,
        "rtconfig_pkg_enabled": False,
        "scons_available": bool(shutil.which(scons) or Path(scons).exists()),
        "rtthread_scons_build_pass": False,
        "rvaic_rtthread_component_build_pass": False,
    }
    report: dict[str, Any] = {"ok": False, "package": str(package), "bsp": str(bsp), "out": str(out), "evidence": evidence}
    if not all(evidence[key] for key in ("rtthread_bsp_present", "rvaic_package_present", "rvaic_runtime_present")):
        report["failure_reason"] = "missing_input"
        write_json(out / "rtthread_rvaic_package_build_report.json", report)
        return report

    install = install_package(package, bsp, runtime, out, drop_libsupcxx) if package else install_runtime(bsp, runtime, out, drop_libsupcxx)
    overlay = Path(install["overlay"])
    evidence["rtthread_application_sconscript_reuse"] = "rvaic_runtime/SConscript" in (overlay / "applications/SConscript").read_text(encoding="utf-8", errors="ignore")
    evidence["rvaic_runtime_installed"] = (overlay / "applications" / "rvaic_runtime" / "include" / "rvaic.h").exists()
    evidence["rvaic_model_sconscript_installed"] = package is None or (overlay / "applications" / "rvaic_model" / "SConscript").exists()
    if package and (package / "tvm_aot_bridge.c").exists():
        evidence["tvm_aot_bridge_preserved"] = (
            (overlay / "applications" / "rvaic_model" / "tvm_aot_bridge.c").exists()
            and "RVAIC_USE_TVM_AOT" in (overlay / "applications" / "rvaic_model" / "SConscript").read_text(encoding="utf-8", errors="ignore")
        )
    evidence["rtconfig_pkg_enabled"] = "#define PKG_USING_RVAIC" in (overlay / "rtconfig.h").read_text(encoding="utf-8", errors="ignore")
    build_pass, log, returncode = run_scons(overlay, scons, jobs, out, rtthread_root_from_bsp(bsp), cross_prefix, picolibc)
    evidence["rtthread_scons_build_pass"] = build_pass
    evidence["rvaic_rtthread_component_build_pass"] = build_pass
    report.update({"install": install, "scons_log": log, "scons_returncode": returncode})
    if not build_pass:
        report["failure_reason"] = "rtthread_scons_build_failed"
    report["ok"] = all(evidence.values())
    write_json(out / "rtthread_rvaic_package_build_report.json", report)
    return report


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bsp = root / "bsp"
        package = root / "demo.rvaic"
        runtime = root / "rvaic"
        fake_scons = root / "scons"
        (bsp / "applications").mkdir(parents=True)
        (bsp / "applications" / "SConscript").write_text("SConscript('rvaic_model/SConscript')\n", encoding="utf-8")
        (bsp / "rtconfig.h").write_text("", encoding="utf-8")
        package.mkdir()
        (package / "model.c").write_text("int demo_model_c;\n", encoding="utf-8")
        (package / "finsh.c").write_text("int demo_finsh_c;\n", encoding="utf-8")
        (package / "SConscript").write_text("old\n", encoding="utf-8")
        (runtime / "include").mkdir(parents=True)
        (runtime / "src").mkdir()
        (runtime / "include" / "rvaic.h").write_text("#define RVAIC_MODEL_VERSION 1\n", encoding="utf-8")
        (runtime / "SConscript").write_text("runtime\n", encoding="utf-8")
        fake_scons.write_text("#!/bin/sh\nprintf 'scons: done building targets\\n'\n", encoding="utf-8")
        fake_scons.chmod(0o755)
        report = build(package, bsp, runtime, root / "out", str(fake_scons), 1, None, False, False)
        assert report["ok"], report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package")
    parser.add_argument("--runtime-only", action="store_true")
    parser.add_argument("--bsp", default=str(ROOT / "third_party/rt-thread/bsp/qemu-virt64-riscv"))
    parser.add_argument("--runtime", default=str(ROOT / "sdk/packages/rvaic"))
    parser.add_argument("--out", default="/tmp/adam_rtthread_rvaic_package")
    parser.add_argument("--scons", default="scons")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--cross-prefix")
    parser.add_argument("--picolibc", action="store_true")
    parser.add_argument("--drop-libsupcxx", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    if not args.package and not args.runtime_only:
        parser.error("--package or --runtime-only is required unless --selftest is used")
    report = build(
        Path(args.package).resolve() if args.package else None,
        Path(args.bsp).resolve(),
        Path(args.runtime).resolve(),
        Path(args.out).resolve(),
        args.scons,
        args.jobs,
        args.cross_prefix,
        args.picolibc,
        args.drop_libsupcxx,
    )
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

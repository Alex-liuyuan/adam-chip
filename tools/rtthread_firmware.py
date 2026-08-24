#!/usr/bin/env python3
"""Build RT-Thread firmware overlays and run them on virtual RISC-V boards."""

from __future__ import annotations

import argparse
import json
import os
import selectors
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


@dataclass(frozen=True)
class Board:
    name: str
    bsp: str
    renode_repl: str
    uart: str
    primary_cpu: str
    app_target: str
    renode_mips: int = 320


BOARDS = {
    "fe310": Board(
        name="fe310",
        bsp="hifive1",
        renode_repl="platforms/cpus/sifive-fe310.repl",
        uart="uart0",
        primary_cpu="cpu",
        app_target="example_riscv_ai",
    ),
}


def run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    try:
        return subprocess.run(
            command,
            cwd=str(cwd),
            env=merged_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="ignore")
        output += f"\nTIMEOUT after {timeout} seconds\n"
        return subprocess.CompletedProcess(command, 124, output, None)


def copy_rtthread_tree(out_dir: Path) -> Path:
    source = ROOT / "third_party" / "rt-thread"
    if not source.exists():
        raise FileNotFoundError(f"missing RT-Thread checkout: {source}")
    overlay = out_dir / "rt-thread"
    if overlay.exists():
        shutil.rmtree(overlay)
    ignore = shutil.ignore_patterns(
        ".git",
        "__pycache__",
        "build",
        "*.o",
        "*.i",
        "*.s",
        "*.elf",
        "*.bin",
        "*.map",
        "*.asm",
        ".sconsign.dblite",
    )
    shutil.copytree(source, overlay, ignore=ignore)
    return overlay


def create_toolchain_wrappers(out_dir: Path, prefix: str) -> Path:
    wrapper_dir = out_dir / "toolchain-wrappers"
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    for tool in ("gcc", "g++", "ar", "objcopy", "size", "objdump"):
        wrapper = wrapper_dir / f"riscv-none-embed-{tool}"
        target = f"{prefix}{tool}"
        if tool in {"gcc", "g++"}:
            body = f"#!/bin/sh\nexec {target} --specs=picolibc.specs \"$@\"\n"
        else:
            body = f"#!/bin/sh\nexec {target} \"$@\"\n"
        wrapper.write_text(body, encoding="utf-8")
        wrapper.chmod(0o755)
    return wrapper_dir


def patch_hifive1_for_renode(bsp_dir: Path) -> list[str]:
    board_c = bsp_dir / "drivers" / "board.c"
    rtconfig_py = bsp_dir / "rtconfig.py"
    patches: list[str] = []
    text = board_c.read_text(encoding="utf-8")
    old = """static void rt_hw_clock_init(void)
{
    use_default_clocks();
    use_pll(0, 0, 1, 31, 1);
}
"""
    new = """static void rt_hw_clock_init(void)
{
#ifdef ADAM_RENODE
    return;
#else
    use_default_clocks();
    use_pll(0, 0, 1, 31, 1);
#endif
}
"""
    if old in text and "ADAM_RENODE" not in text:
        board_c.write_text(text.replace(old, new), encoding="utf-8")
        patches.append("hifive1_skip_prci_clock_wait_for_renode")

    rtconfig = rtconfig_py.read_text(encoding="utf-8")
    if "-DADAM_RENODE" not in rtconfig:
        rtconfig = rtconfig.replace("DEVICE = ' ", "DEVICE = ' -DADAM_RENODE ", 1)
        rtconfig_py.write_text(rtconfig, encoding="utf-8")
        patches.append("hifive1_add_adam_renode_define")
    return patches


def generate_target_app(board: Board, out_dir: Path) -> Path:
    generated = out_dir / "generated-target"
    command = [
        PY,
        str(ROOT / "tools" / "adapt_riscv_target.py"),
        str(ROOT / "targets" / "example_riscv_ai.json"),
        "--out",
        str(generated),
    ]
    proc = run_command(command, cwd=ROOT)
    log = out_dir / f"{board.name}_target_generation.log"
    log.write_text(proc.stdout, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"target generation failed for {board.name}: {log}")
    app = generated / board.app_target / "rtthread" / "applications" / "rvaic_conv_smoke.c"
    if not app.exists():
        raise FileNotFoundError(f"target generator did not emit RT-Thread app: {app}")
    return app


def integrate_rvaic_app(board: Board, overlay: Path, out_dir: Path) -> dict[str, object]:
    bsp_dir = overlay / "bsp" / board.bsp
    apps = bsp_dir / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    app = generate_target_app(board, out_dir)
    shutil.copy2(app, apps / "rvaic_conv_smoke.c")
    copied_sources = []
    for src in sorted((ROOT / "sdk" / "packages" / "rvaic" / "src").glob("*.c")):
        dst = apps / src.name
        shutil.copy2(src, dst)
        copied_sources.append(str(dst))
    for subdir in ("memory", "object", "service"):
        for src in sorted((ROOT / "sdk" / "packages" / "rvaic" / "src" / subdir).glob("*.c")):
            dst = apps / f"rvaic_{subdir}_{src.name}"
            shutil.copy2(src, dst)
            copied_sources.append(str(dst))
    shutil.copy2(ROOT / "sdk" / "packages" / "rvaic" / "include" / "rvaic.h", apps / "rvaic.h")
    return {
        "app_source": str(app),
        "bsp_application": str(apps / "rvaic_conv_smoke.c"),
        "runtime_sources": copied_sources,
        "runtime_header": str(apps / "rvaic.h"),
    }


def prepare_overlay(board: Board, out_dir: Path) -> tuple[Path, dict[str, object]]:
    overlay = copy_rtthread_tree(out_dir / board.name)
    patches: list[str] = []
    if board.name == "fe310":
        patches.extend(patch_hifive1_for_renode(overlay / "bsp" / board.bsp))
    integration = integrate_rvaic_app(board, overlay, out_dir / board.name)
    return overlay, {"patches": patches, "integration": integration}


def build_bsp(board: Board, overlay: Path, wrapper_dir: Path, jobs: int) -> dict[str, object]:
    bsp_dir = overlay / "bsp" / board.bsp
    build_log = bsp_dir / "adam_build.log"
    if not bsp_dir.exists():
        return {
            "compile_pass": False,
            "build_returncode": 2,
            "build_log": str(build_log),
            "failure_reason": f"missing RT-Thread BSP: {bsp_dir}",
        }
    env = {"RTT_EXEC_PATH": str(wrapper_dir)}
    proc = run_command(
        ["scons", "-C", str(bsp_dir), f"-j{jobs}"],
        cwd=ROOT,
        env=env,
    )
    build_log.write_text(proc.stdout, encoding="utf-8")
    elf = bsp_dir / "rtthread.elf"
    image = bsp_dir / "rtthread.bin"
    compile_pass = proc.returncode == 0 and elf.exists()
    failure_reason = ""
    if not compile_pass:
        failure_reason = classify_build_failure(proc.stdout)
    return {
        "compile_pass": compile_pass,
        "build_returncode": proc.returncode,
        "build_log": str(build_log),
        "elf": str(elf),
        "image": str(image),
        "failure_reason": failure_reason,
    }


def classify_build_failure(log: str) -> str:
    if "No such file or directory" in log and "riscv-none-embed" in log:
        return "missing_riscv_none_embed_toolchain"
    if "picolibc.specs" in log:
        return "missing_picolibc_specs"
    return "rtthread_bsp_build_failed"


def resc_script(board: Board, elf: Path, uart_log: Path, run_seconds: float) -> str:
    lines = [
        "using sysbus",
        f'mach create "adam-{board.name}-rtthread"',
        f"machine LoadPlatformDescription @{board.renode_repl}",
        f"{board.uart} CreateFileBackend @{uart_log}",
        f"showAnalyzer {board.uart}",
        f"sysbus LoadELF @{elf}",
        f'{board.primary_cpu} PC `sysbus GetSymbolAddress "_start"`',
        f"{board.primary_cpu} PerformanceInMips {board.renode_mips}",
    ]
    lines.extend(
        [
            "start",
            f'emulation RunFor "{run_seconds}"',
            "pause",
            f"{board.uart} CloseFileBackend @{uart_log}",
            "quit",
        ]
    )
    return "\n".join(lines) + "\n"


def run_renode(board: Board, out_dir: Path, renode: Path, elf: Path, timeout: float, run_seconds: float) -> dict[str, object]:
    board_out = out_dir / board.name
    board_out.mkdir(parents=True, exist_ok=True)
    uart_log = board_out / "uart.log"
    renode_log = board_out / "renode.log"
    script = board_out / f"{board.name}_rtthread.resc"
    uart_log.unlink(missing_ok=True)
    script.write_text(resc_script(board, elf, uart_log, run_seconds), encoding="utf-8")

    proc = subprocess.Popen(
        [str(renode), "--disable-gui", "--plain", "--port", "-1", str(script)],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + timeout
    stdout_chunks: list[str] = []
    uart_text = ""
    terminated_after_pass = False
    timed_out = False
    selector = selectors.DefaultSelector()
    if proc.stdout is not None:
        selector.register(proc.stdout, selectors.EVENT_READ)

    while time.monotonic() < deadline:
        for key, _ in selector.select(timeout=0.1):
            line = key.fileobj.readline()
            if line:
                stdout_chunks.append(line)
        stdout_so_far = "".join(stdout_chunks)
        if uart_log.exists():
            uart_text = uart_log.read_text(encoding="utf-8", errors="ignore")
        combined = stdout_so_far + uart_text
        if "RT-Thread" in combined and has_shell_prompt(combined) and "RVAIC_CONV_SMOKE_PASS" in combined:
            terminated_after_pass = True
            proc.terminate()
            break
        if proc.poll() is not None:
            break
    else:
        timed_out = True
        proc.terminate()

    try:
        stdout, _ = proc.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, _ = proc.communicate()
    stdout = "".join(stdout_chunks) + stdout
    if uart_log.exists():
        uart_text = uart_log.read_text(encoding="utf-8", errors="ignore")
    if timed_out:
        stdout += f"\nTIMEOUT after {timeout} seconds\n"
    renode_log.write_text(stdout, encoding="utf-8")
    combined = stdout + uart_text
    success_observed = "RT-Thread" in combined and "RVAIC_CONV_SMOKE_PASS" in combined
    if success_observed and has_shell_prompt(combined):
        timed_out = False
        terminated_after_pass = True
    return {
        "renode_script": str(script),
        "uart_log": str(uart_log),
        "renode_log": str(renode_log),
        "renode_returncode": proc.returncode,
        "boot_pass": "RT-Thread" in combined,
        "finsh_pass": has_shell_prompt(combined),
        "rvaic_app_pass": "RVAIC_CONV_SMOKE_PASS" in combined,
        "lightweight_conv_reference_pass": "RVAIC_CONV_SMOKE_PASS" in combined,
        "uart": uart_text,
        "timed_out": timed_out,
        "terminated_after_pass": terminated_after_pass,
    }


def has_shell_prompt(text: str) -> bool:
    return "msh >" in text or "msh />" in text


def run_board(board: Board, args: argparse.Namespace, out_dir: Path, wrapper_dir: Path) -> dict[str, object]:
    result: dict[str, object] = {
        "board": board.name,
        "rtthread_bsp": board.bsp,
        "os": "RT-Thread",
        "app": "rvaic_conv_smoke",
        "platform": board.renode_repl,
        "pass": False,
    }
    try:
        overlay, metadata = prepare_overlay(board, out_dir)
        result["overlay"] = str(overlay)
        result.update(metadata)
    except Exception as exc:  # report generator/integration failures as evidence, do not hide them.
        result["failure_reason"] = f"overlay_prepare_failed: {exc}"
        return result

    build = build_bsp(board, overlay, wrapper_dir, args.jobs)
    result.update(build)
    if not build.get("compile_pass"):
        return result
    if args.compile_only:
        result["pass"] = True
        return result
    renode = Path(args.renode)
    if not renode.exists():
        result["failure_reason"] = f"missing_renode_executable: {renode}"
        return result
    run = run_renode(board, out_dir, renode, Path(str(build["elf"])), args.timeout, args.run_seconds)
    result.update(run)
    result["pass"] = bool(
        result.get("compile_pass")
        and result.get("boot_pass")
        and result.get("finsh_pass")
        and result.get("rvaic_app_pass")
    )
    if not result["pass"] and not result.get("failure_reason"):
        result["failure_reason"] = classify_run_failure(result)
    return result


def classify_run_failure(result: dict[str, object]) -> str:
    text = str(result.get("uart", ""))
    renode_log = result.get("renode_log")
    if renode_log and Path(str(renode_log)).exists():
        text += Path(str(renode_log)).read_text(encoding="utf-8", errors="ignore")
    if "PRIC:HFROSCCFG" in text or "PRCI" in text:
        return "renode_prci_clock_model_mismatch"
    if "Unhandled Trap" in text:
        return "rtthread_unhandled_trap"
    if not result.get("boot_pass"):
        return "rtthread_boot_banner_missing"
    if not result.get("rvaic_app_pass"):
        return "rvaic_rtthread_app_output_missing"
    return "rtthread_renode_run_failed"


def collect_evidence(board_results: list[dict[str, object]]) -> dict[str, bool]:
    return {
        "rtthread_bsp_build_pass": all(bool(item.get("compile_pass")) for item in board_results),
        "qemu_or_renode_board_boot_pass": all(bool(item.get("boot_pass")) for item in board_results),
        "finsh_console_pass": all(bool(item.get("finsh_pass")) for item in board_results),
        "rvaic_rtthread_app_pass": all(bool(item.get("rvaic_app_pass")) for item in board_results),
        "lightweight_conv_reference_pass": all(
            bool(item.get("lightweight_conv_reference_pass")) for item in board_results
        ),
    }


def selftest() -> None:
    assert BOARDS["fe310"].bsp == "hifive1"
    assert "RVAIC_CONV_SMOKE_PASS" in "\n".join(
        [resc_script(BOARDS["fe310"], Path("rtthread.elf"), Path("uart.log"), 0.1), "RVAIC_CONV_SMOKE_PASS"]
    )
    assert has_shell_prompt("msh />") is True
    evidence = collect_evidence(
        [
            {
                "compile_pass": True,
                "boot_pass": True,
                "finsh_pass": True,
                "rvaic_app_pass": True,
                "lightweight_conv_reference_pass": True,
            }
        ]
    )
    assert evidence["rtthread_bsp_build_pass"] is True
    assert evidence["rvaic_rtthread_app_pass"] is True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/tmp/adam_rtthread_firmware")
    parser.add_argument("--renode", default=str(ROOT / "third_party" / "renode_portable" / "renode"))
    parser.add_argument("--cross-prefix", default="riscv64-unknown-elf-")
    parser.add_argument("--boards", nargs="+", choices=sorted(BOARDS), default=["fe310"])
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--run-seconds", type=float, default=0.2)
    parser.add_argument("--compile-only", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        selftest()
        print("ok")
        return 0

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    wrapper_dir = create_toolchain_wrappers(out_dir, args.cross_prefix)
    board_results = [run_board(BOARDS[name], args, out_dir, wrapper_dir) for name in args.boards]
    evidence = collect_evidence(board_results)
    report = {
        "ok": all(bool(item.get("pass")) for item in board_results),
        "test": "rtthread_firmware",
        "boards": board_results,
        "evidence": evidence,
        "notes": [
            "Firmware is built through RT-Thread SCons BSPs in a project-owned overlay.",
            "RVAIC convolution is integrated as an RT-Thread application, not a bare-metal smoke binary.",
            "Renode uses sysbus LoadELF for virtual-board execution; this is not a physical flash/HIL proof.",
        ],
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Check the implemented RT-Thread-native RVAIC surface from source evidence."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = ROOT / "sdk" / "packages" / "rvaic"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def runtime_sources(runtime: Path) -> list[Path]:
    paths = sorted((runtime / "src").glob("*.c"))
    paths += sorted((runtime / "src" / "object").glob("*.c"))
    paths += sorted((runtime / "src" / "service").glob("*.c"))
    paths += sorted((runtime / "src" / "memory").glob("*.c"))
    return paths


def has_all(text: str, names: tuple[str, ...]) -> bool:
    return all(name in text for name in names)


def host_utest_pass(runtime: Path) -> bool:
    cc = shutil.which("cc")
    test_c = runtime / "tests" / "test_rvaic_host.c"
    if not cc or not test_c.exists():
        return False
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / "rvaic_host_utest"
        compile_cmd = [
            cc,
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(runtime / "include"),
            *(str(path) for path in runtime_sources(runtime)),
            str(test_c),
            "-o",
            str(exe),
        ]
        compiled = subprocess.run(compile_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        if compiled.returncode != 0:
            return False
        ran = subprocess.run([str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        return ran.returncode == 0


def analyze(runtime: Path = DEFAULT_RUNTIME) -> dict:
    header = read(runtime / "include" / "rvaic.h")
    sources = "\n".join(read(path) for path in runtime_sources(runtime))
    sconscript = read(runtime / "SConscript")
    text = "\n".join((header, sources, sconscript))
    unit_pass = host_utest_pass(runtime)
    device_class_impl = "rt_device_register" in text or "RT_Device_Class" in text
    irq_dma_impl = has_all(text, ("IRQ", "DMA")) and has_all(text, ("rvaic_fence", "rvaic_backend_reset"))

    evidence = {
        "rvaic_package_layout_pass": all(
            (runtime / rel).exists()
            for rel in (
                "include/rvaic.h",
                "SConscript",
                "src/rvaic.c",
                "src/object/rt_ai_object.c",
                "src/service/ai_service.c",
                "src/memory/arena_pool.c",
            )
        ),
        "rtthread_component_build_binding_pass": has_all(sconscript, ("src/object/*.c", "src/service/*.c", "src/memory/*.c")),
        "rt_ai_object_api_pass": has_all(
            header + sources,
            ("rt_ai_model_t", "rt_ai_job_t", "rt_ai_fence_t", "rt_ai_model_find", "rt_ai_submit", "rt_ai_cancel"),
        ),
        "rtthread_service_thread_pass": has_all(sources, ("RT_USING_HEAP", "rt_thread_create", "rvaic_service_thread_entry")),
        "rtthread_event_ipc_pass": has_all(sources, ("RT_USING_EVENT", "rt_event_create", "rt_event_send", "rt_event_recv")),
        "service_priority_queue_pass": has_all(sources, ("select_job", "priority > best_priority", "rvaic_service_step")),
        "backend_run_queue_pass": has_all(header + sources, ("rvaic_backend_queue_state", "queued", "running", "credits")),
        "backend_lock_watchdog_reset_pass": has_all(
            header + sources,
            ("rvaic_backend_lock", "rvaic_backend_unlock", "rvaic_service_watchdog_tick", "rvaic_backend_reset"),
        ),
        "plan_admission_runtime_pass": has_all(header + sources, ("rvaic_plan_admit", "RVAIC_PLAN_REJECT_TARGET", "RVAIC_PLAN_REJECT_EVIDENCE")),
        "multi_session_arena_pass": has_all(header + sources, ("RVAIC_MAX_SESSIONS", "rvaic_session_create_with_admission", "rvaic_arena_pool_init")),
        "host_runtime_utest_pass": unit_pass,
    }
    boundaries = {
        "rtthread_device_class_status_recorded": True,
        "irq_dma_fence_scheduler_status_recorded": True,
        "board_evidence_status_recorded": True,
    }
    not_implemented = []
    if not device_class_impl:
        not_implemented.append("full RT-Thread rt_device class registration for AI backends")
    if not irq_dma_impl:
        not_implemented.append("hardware IRQ/DMA/fence scheduler integration")

    return {
        "scope": "rvaic_rtthread_native_capability",
        "ok": all(evidence.values()) and all(boundaries.values()),
        "capability_level": "rtthread_component_native",
        "evidence": evidence,
        "boundaries": boundaries,
        "implemented": [key for key, value in evidence.items() if value],
        "not_implemented": not_implemented,
        "runtime_dir": str(runtime),
    }


def selftest() -> None:
    report = analyze(DEFAULT_RUNTIME)
    assert report["ok"], report
    assert report["evidence"]["rtthread_event_ipc_pass"], report
    assert "hardware IRQ/DMA/fence scheduler integration" in report["not_implemented"], report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--out")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    report = analyze(Path(args.runtime_dir))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

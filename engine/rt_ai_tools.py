"""RtAiOsAgent and RuntimeAgent generation and verification tools."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from socimage.facts import is_safe, sha256


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = Path(__file__).with_name("rt_ai_templates")
RTTHREAD = ROOT / "third_party/rt-thread"
PASS_TOKENS = (
    "AEG_PASS", "ASYNC_PASS", "DAG_PASS", "EDF_PASS", "ARENA_PASS", "CACHE_PASS",
    "TIMEOUT_PASS", "CANCEL_PASS", "EPOCH_PASS", "IRQ_PASS",
    "ADMISSION_PASS",
    "RECOVERY_ACK_PASS", "QUARANTINE_PASS", "TRACE_V2_PASS",
    "STRESS_PASS",
    "RESET_BOUND_PASS", "FALLBACK_PASS", "EVIDENCE_POLICY_PASS", "CACHE_MODEL_PASS",
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _cache_line(hardware_ir: dict[str, Any]) -> int:
    value = hardware_ir.get("cpu", {}).get("cache_line_bytes")
    if not is_safe(value) or not isinstance(value.get("value"), int) or value["value"] <= 0:
        raise ValueError("RT-AI requires an authoritative cache line size")
    return value["value"]


def _template_hashes(paths: list[Path]) -> list[dict[str, str]]:
    return [{"path": str(path.relative_to(TEMPLATES)), "sha256": sha256(path)} for path in paths]


def _os_templates() -> list[Path]:
    return [
        TEMPLATES / "include/rt_ai.h",
        TEMPLATES / "include/rt_ai_internal.h",
        *sorted((TEMPLATES / "os").glob("*.c")),
    ]


def _runtime_templates() -> list[Path]:
    return [
        *sorted((TEMPLATES / "runtime").glob("*.c")),
        *sorted(path for path in (TEMPLATES / "tests").glob("*") if path.is_file()),
    ]


def _kconfig() -> str:
    return """menuconfig PKG_USING_RT_AI
    bool "Native asynchronous RT-AI runtime"
    default y
    help
      AEG execution, per-resource EDF, arena leases, cache ownership and epoch recovery.
"""


def _sconscript() -> str:
    return """from building import *
cwd = GetCurrentDir()
src = Glob('src/*.c') + Glob('../runtime/src/aeg_loader.c') + Glob('../runtime/src/session.c')
group = DefineGroup('rt_ai', src, depend=['PKG_USING_RT_AI'], CPPPATH=[cwd + '/include'])
Return('group')
"""


def generate_rt_ai_os(context: Any) -> dict[str, Any]:
    cache_line = _cache_line(context.hardware_ir)
    root = context.worktree / "generated/rt_ai/os"
    for source in _os_templates():
        relative = source.relative_to(TEMPLATES)
        destination = root / (Path("src") / relative.name if relative.parts[0] == "os" else relative)
        _copy(source, destination)
    _write(root / "include/rt_ai_target.h", f"#ifndef RT_AI_TARGET_H\n#define RT_AI_TARGET_H\n#define RT_AI_CACHE_LINE_BYTES {cache_line}U\n#endif\n")
    _write(root / "Kconfig", _kconfig())
    _write(root / "SConscript", _sconscript())
    manifest = {
        "schema": "soc-image.rt-ai-os-manifest.v1",
        "task_id": context.task_id,
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "generator": "RtAiOsAgent",
        "cache_line_bytes": cache_line,
        "rtthread_revision": subprocess.run(["git", "rev-parse", "HEAD"], cwd=RTTHREAD, text=True, stdout=subprocess.PIPE, check=True).stdout.strip(),
        "templates": _template_hashes(_os_templates()),
        "legacy_rvaic_used": False,
    }
    _write(root / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {"status": "passed", "outputs": list(context.outputs), "cache_line_bytes": cache_line}


def verify_rt_ai_os(context: Any) -> list[str]:
    errors = [f"missing RT-AI OS output: {path}" for path in context.outputs if not (context.worktree / path).is_file()]
    if errors:
        return errors
    root = context.worktree / "generated/rt_ai/os"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("task_id") != context.task_id or manifest.get("hardware_ir_sha256") != context.hardware_ir_sha256:
        errors.append("RT-AI OS manifest is not bound to the task and Hardware IR")
    if manifest.get("cache_line_bytes") != _cache_line(context.hardware_ir):
        errors.append("RT-AI cache line does not match Hardware IR")
    if manifest.get("legacy_rvaic_used") is not False:
        errors.append("legacy rvaic ancestry is prohibited")
    for source in _os_templates():
        relative = source.relative_to(TEMPLATES)
        generated = root / (Path("src") / relative.name if relative.parts[0] == "os" else relative)
        if sha256(generated) != sha256(source):
            errors.append(f"generated RT-AI OS source differs from reviewed template: {relative}")
    return errors


def _source_lists(worktree: Path) -> tuple[list[Path], list[Path], Path]:
    os_root = worktree / "generated/rt_ai/os"
    runtime_root = worktree / "generated/rt_ai/runtime"
    os_sources = sorted(path for path in (os_root / "src").glob("*.c") if path.name != "rt_ai_port_rtthread.c")
    runtime_sources = sorted((runtime_root / "src").glob("*.c"))
    host_port = runtime_root / "src/rt_ai_port_host.c"
    runtime_sources.remove(host_port)
    return os_sources, runtime_sources, host_port


def _build_host(worktree: Path, destination: Path) -> tuple[str, str]:
    compiler = shutil.which("gcc")
    if not compiler:
        raise RuntimeError("host C compiler is unavailable")
    os_sources, runtime_sources, host_port = _source_lists(worktree)
    include = worktree / "generated/rt_ai/os/include"
    test = worktree / "generated/rt_ai/runtime/tests/test_rt_ai.c"
    destination.mkdir(parents=True, exist_ok=True)
    binary = destination / "test_rt_ai"
    proc = subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(include), *map(str, os_sources), *map(str, runtime_sources), str(host_port), str(test), "-o", str(binary)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError("RT-AI host build failed:\n" + proc.stdout)
    run = subprocess.run([str(binary)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if run.returncode or not all(token in run.stdout for token in PASS_TOKENS):
        raise RuntimeError("RT-AI host tests failed:\n" + run.stdout)
    return run.stdout, sha256(binary)


def _cross_compile(worktree: Path) -> None:
    compiler = shutil.which("riscv64-linux-gnu-gcc")
    if not compiler:
        raise RuntimeError("RISC-V cross compiler is unavailable")
    os_root = worktree / "generated/rt_ai/os"
    os_sources, runtime_sources, _ = _source_lists(worktree)
    sources = [*os_sources, *runtime_sources, os_root / "src/rt_ai_port_rtthread.c"]
    include_flags = [
        "-I", str(os_root / "include"),
        "-I", str(worktree / "generated/platform/rtthread"),
        "-I", str(RTTHREAD / "include"),
        "-I", str(RTTHREAD / "libcpu/risc-v/common64"),
        "-I", str(RTTHREAD / "libcpu/risc-v/common"),
        "-I", str(RTTHREAD / "libcpu/risc-v/virt64"),
        "-I", str(RTTHREAD / "components/finsh"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for index, source in enumerate(sources):
            proc = subprocess.run(
                [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-ffreestanding", *include_flags, "-c", str(source), "-o", str(Path(tmp) / f"{index}.o")],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            if proc.returncode:
                raise RuntimeError(f"RT-AI RT-Thread component compile failed for {source.name}:\n{proc.stdout}")


def _verification(worktree: Path, destination: Path) -> dict[str, Any]:
    host_log, binary_hash = _build_host(worktree, destination)
    _cross_compile(worktree)
    _write(destination / "host.log", host_log)
    trace_line = next((line[11:] for line in host_log.splitlines() if line.startswith("TRACE_JSON ")), None)
    if trace_line is None:
        raise RuntimeError("RT-AI host tests did not emit a C trace JSON artifact")
    trace = json.loads(trace_line)
    Draft202012Validator(json.loads((ROOT / "schemas/airtos_trace.schema.json").read_text(encoding="utf-8"))).validate(trace)
    if not any(event["plan_id"] != trace["plan_id"] for event in trace["events"]) or not any(event["event"] == "quarantine" for event in trace["events"]):
        raise RuntimeError("RT-AI trace did not preserve fallback plan identity and recovery root cause")
    _write(destination / "trace.json", json.dumps(trace, indent=2, sort_keys=True) + "\n")
    dispatch = {(event["job_id"], event["segment_id"]): event["timestamp_us"] for event in trace["events"] if event["event"] == "dispatch"}
    latencies = [event["timestamp_us"] - dispatch[(event["job_id"], event["segment_id"])] for event in trace["events"] if event["event"] == "complete" and (event["job_id"], event["segment_id"]) in dispatch]
    causes = {"success": 0, "timeout": 0, "cancelled": 0, "provider": 0, "stale": 0, "admission": 0, "domain": 0, "evidence": 0, "other": 0}
    cause_by_status = {0: "success", -3: "timeout", -4: "cancelled", -5: "provider", -6: "stale", -7: "admission", -8: "domain", -9: "evidence"}
    for event in trace["events"]:
        causes[cause_by_status.get(event["status"], "other")] += 1
    if causes["timeout"] == 0:
        raise RuntimeError("RT-AI trace metrics did not classify the recovery failure")
    window = max(event["timestamp_us"] for event in trace["events"]) - min(event["timestamp_us"] for event in trace["events"])
    metrics = {
        "schema": "soc-image.airtos-trace-metrics.v1", "run_id": trace["run_id"], "plan_id": trace["plan_id"],
        "event_count": len(trace["events"]), "dropped": trace["dropped"], "observed_window_us": window,
        "completed_segments": len(latencies), "latency_us": {"min": min(latencies, default=0), "max": max(latencies, default=0), "mean": sum(latencies) / len(latencies) if latencies else 0},
        "root_cause_event_counts": causes,
    }
    _write(destination / "trace_metrics.json", json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    compiler = shutil.which("gcc")
    oracle = destination / "oracle_driver"
    build = subprocess.run([compiler, "-O2", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(worktree / "generated/rt_ai/os/include"), str(worktree / "generated/rt_ai/os/src/sim_edf.c"), str(worktree / "generated/rt_ai/runtime/tests/oracle_driver.c"), "-o", str(oracle)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if build.returncode:
        raise RuntimeError("independent oracle driver build failed:\n" + build.stdout)
    oracle_run = subprocess.run([sys.executable, str(worktree / "generated/rt_ai/runtime/tests/oracle.py"), str(oracle)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if oracle_run.returncode or "INDEPENDENT_10000_SCENARIO_ORACLE_PASS" not in oracle_run.stdout:
        raise RuntimeError("independent scheduling oracle failed:\n" + oracle_run.stdout)
    _write(destination / "oracle.log", oracle_run.stdout)
    return {
        "schema": "soc-image.rt-ai-verification.v1",
        "aeg_loader_pass": True,
        "async_provider_pass": True,
        "segment_dag_pass": True,
        "per_resource_edf_pass": True,
        "arena_lease_pass": True,
        "cache_ownership_pass": True,
        "noncoherent_cache_dma_model_pass": True,
        "timeout_cancel_pass": True,
        "epoch_reset_pass": True,
        "late_duplicate_irq_pass": True,
        "finish_time_admission_pass": True,
        "recovery_acknowledgement_pass": True,
        "quarantine_pass": True,
        "trace_v2_pass": True,
        "trace_json_schema_pass": True,
        "trace_metrics_pass": True,
        "evidence_policy_evaluator_pass": True,
        "host_stress_oracles_pass": True,
        "independent_10000_scenario_oracle_pass": True,
        "bounded_reset_poll_pass": True,
        "automatic_fallback_pass": True,
        "rtthread_component_compile_pass": True,
        "host_test_sha256": binary_hash,
    }


def generate_rt_ai_runtime(context: Any) -> dict[str, Any]:
    root = context.worktree / "generated/rt_ai/runtime"
    for source in _runtime_templates():
        relative = source.relative_to(TEMPLATES)
        destination = root / (Path("tests") / relative.name if relative.parts[0] == "tests" else Path("src") / relative.name)
        _copy(source, destination)
    manifest = {
        "schema": "soc-image.rt-ai-runtime-manifest.v1",
        "task_id": context.task_id,
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "generator": "RuntimeAgent",
        "os_manifest_sha256": sha256(context.worktree / "generated/rt_ai/os/manifest.json"),
        "templates": _template_hashes(_runtime_templates()),
        "api": ["rt_ai_load", "rt_ai_session_create", "rt_ai_submit_async_v2", "rt_ai_wait", "rt_ai_cancel", "rt_ai_provider_register", "rt_ai_complete_isr", "rt_ai_reset_device"],
    }
    _write(root / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    report = _verification(context.worktree, root / "build")
    _write(root / "build/verification.json", json.dumps(report, indent=2, sort_keys=True) + "\n")
    return {"status": "passed", "outputs": list(context.outputs), "verification": report}


def verify_rt_ai_runtime(context: Any) -> list[str]:
    errors = [f"missing RT-AI runtime output: {path}" for path in context.outputs if not (context.worktree / path).is_file()]
    if errors:
        return errors
    root = context.worktree / "generated/rt_ai/runtime"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("task_id") != context.task_id or manifest.get("hardware_ir_sha256") != context.hardware_ir_sha256:
        errors.append("RT-AI runtime manifest is not bound to the task and Hardware IR")
    if manifest.get("os_manifest_sha256") != sha256(context.worktree / "generated/rt_ai/os/manifest.json"):
        errors.append("RT-AI runtime is not bound to the promoted OS component")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            report = _verification(context.worktree, Path(tmp))
        if not all(value is True for name, value in report.items() if name.endswith("_pass")):
            errors.append("independent RT-AI verification did not pass")
    except RuntimeError as exc:
        errors.append(str(exc))
    return errors


def selftest() -> None:
    from engine.control import Engine
    from socimage.hardware import derive
    from socimage.intake import create_run

    assert all(path.is_file() for path in _runtime_templates())
    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp) / "run"
        create_run([ROOT / "verification/materials/qemu_virt64_drivers.dts"], run)
        assert derive(run)["ok"]
        result = Engine(run).run_tasks(max_workers=1)
        assert result["ok"], result
        assert result["task_status"]["task:rt_ai_runtime"] == "passed"
        report = json.loads((run / "integration/generated/rt_ai/runtime/build/verification.json").read_text(encoding="utf-8"))
        assert report["per_resource_edf_pass"] and report["late_duplicate_irq_pass"]

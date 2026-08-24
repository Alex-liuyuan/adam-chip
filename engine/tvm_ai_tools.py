"""CompilerAgent tool for the TVM Relax/S-TIR/AEG production path."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import tvm
import tvm_ffi
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from socimage.facts import is_safe, sha256


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = Path(__file__).with_name("tvm_templates")
TVM_ROOT = ROOT / "third_party/tvm"
FFI_INCLUDE = Path(tvm_ffi.__file__).resolve().parent / "include"
TEMPLATE_NAMES = ("compiler.py", "plan_v2.py", "aot_runner.c", "rvv_kernel.c", "aeg_check.c")
CONTRACT_SCHEMAS = {
    "plan.json": ROOT / "schemas/cecap_plan.schema.json",
    "evidence.json": ROOT / "schemas/cecap_evidence.schema.json",
    "airtos_policy.json": ROOT / "schemas/airtos_policy.schema.json",
}


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _target(context: Any) -> dict[str, Any]:
    isa = context.hardware_ir.get("cpu", {}).get("isa")
    if not is_safe(isa) or not isinstance(isa.get("value"), str):
        raise ValueError("CompilerAgent requires an authoritative ISA")
    normalized = isa["value"].lower()
    extension = normalized[4:].split("_", 1)[0] if normalized.startswith("rv64") else ""
    rvv_enabled = "v" in extension
    if not rvv_enabled:
        raise ValueError("Phase 7 RVV AOT requires an authoritative RISC-V vector extension")
    accelerators = context.hardware_ir.get("accelerators", [])
    npu_abi = any(is_safe(item.get("command_abi")) for item in accelerators)
    return {
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "rt_ai_runtime_manifest_sha256": sha256(context.worktree / "generated/rt_ai/runtime/manifest.json"),
        "isa": normalized,
        "rvv_enabled": rvv_enabled,
        "npu_command_abi_confirmed": npu_abi,
    }


def _copy_templates(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in TEMPLATE_NAMES:
        shutil.copyfile(TEMPLATES / name, root / name)


def _run_compiler(root: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(root / "compiler.py"),
            "--out", str(root),
            "--target", str(root / "target.json"),
            "--tvm-root", str(TVM_ROOT),
            "--ffi-include", str(FFI_INCLUDE),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError("TVM compiler pipeline failed:\n" + "\n".join(proc.stdout.splitlines()[-80:]))


def _aeg_runtime_check(worktree: Path, root: Path) -> str:
    compiler = shutil.which("riscv64-linux-gnu-gcc")
    qemu = shutil.which("qemu-riscv64")
    if not compiler or not qemu:
        raise RuntimeError("RISC-V compiler or qemu-riscv64 is unavailable")
    command = [
        compiler,
        "-O2",
        "-static",
        "-march=rv64gc",
        "-mabi=lp64d",
        "-I", str(worktree / "generated/rt_ai/os/include"),
        str(root / "aeg_check.c"),
        str(worktree / "generated/rt_ai/runtime/src/aeg_loader.c"),
        "-o", str(root / "aeg_check"),
    ]
    build = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if build.returncode:
        raise RuntimeError("AEG runtime check build failed:\n" + build.stdout)
    run = subprocess.run([qemu, "-cpu", "max", str(root / "aeg_check"), str(root / "model.aeg")], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if run.returncode or "AEG_RUNTIME_PASS" not in run.stdout:
        raise RuntimeError("AEG runtime round-trip failed:\n" + run.stdout)
    (root / "aeg_check.log").write_text(run.stdout, encoding="utf-8")
    return run.stdout


def _git_revision(path: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()


def _validate_contracts(root: Path) -> None:
    for name, schema_path in CONTRACT_SCHEMAS.items():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(json.loads((root / name).read_text(encoding="utf-8")))
    plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    evidence = json.loads((root / "evidence.json").read_text(encoding="utf-8"))
    policy = json.loads((root / "airtos_policy.json").read_text(encoding="utf-8"))
    identity = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()
    if evidence["plan_id"] != plan["plan_id"] or evidence["evidence_id"] != plan["evidence_sha256"] or policy["policy_id"] != plan["policy_sha256"]:
        raise RuntimeError("CECAP plan, evidence, and AIRTOS policy are not hash-bound")
    if identity({key: value for key, value in plan.items() if key != "plan_id"}) != plan["plan_id"]:
        raise RuntimeError("CECAP plan identity does not match its content")
    if identity({"schema": evidence["schema"], "obligations": evidence["obligations"]}) != evidence["evidence_id"]:
        raise RuntimeError("CECAP evidence identity does not match its obligations")
    if identity({key: value for key, value in policy.items() if key != "policy_id"}) != policy["policy_id"]:
        raise RuntimeError("AIRTOS policy identity does not match its content")
    if not any(item["role"] == "fallback" and item["independently_valid"] for item in plan["plans"]):
        raise RuntimeError("CECAP plan lacks an independently valid fallback")


def generate_tvm_ai_compiler(context: Any) -> dict[str, Any]:
    root = context.worktree / "generated/compiler"
    _copy_templates(root)
    target = _target(context)
    _write(root / "target.json", target)
    _run_compiler(root)
    _validate_contracts(root)
    _aeg_runtime_check(context.worktree, root)
    report = json.loads((root / "verification.json").read_text(encoding="utf-8"))
    report["aeg_runtime_roundtrip_pass"] = True
    _write(root / "verification.json", report)
    manifest = {
        "schema": "soc-image.tvm-ai-compiler-manifest.v1",
        "task_id": context.task_id,
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "generator": "CompilerAgent",
        "target": target,
        "tvm_version": tvm.__version__,
        "tvm_revision": _git_revision(TVM_ROOT),
        "templates": [{"path": name, "sha256": sha256(TEMPLATES / name)} for name in TEMPLATE_NAMES],
        "npu_blob_emitted": False,
        "npu_blocker_sha256": sha256(root / "npu_blocker.json"),
        "cecap_plan_sha256": sha256(root / "plan.json"),
        "cecap_evidence_sha256": sha256(root / "evidence.json"),
        "airtos_policy_sha256": sha256(root / "airtos_policy.json"),
        "rt_ai_manifest_sha256": sha256(context.worktree / "generated/rt_ai/runtime/manifest.json"),
    }
    _write(root / "manifest.json", manifest)
    return {"status": "passed", "outputs": list(context.outputs), "verification": report}


def _independent(context: Any, destination: Path) -> dict[str, Any]:
    generated = destination / "generated"
    _copy_templates(generated)
    _write(generated / "target.json", _target(context))
    _run_compiler(generated)
    _validate_contracts(generated)
    _aeg_runtime_check(context.worktree, generated)
    return json.loads((generated / "verification.json").read_text(encoding="utf-8"))


def verify_tvm_ai_compiler(context: Any) -> list[str]:
    errors = [f"missing compiler output: {path}" for path in context.outputs if not (context.worktree / path).is_file()]
    if errors:
        return errors
    root = context.worktree / "generated/compiler"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("task_id") != context.task_id or manifest.get("hardware_ir_sha256") != context.hardware_ir_sha256:
        errors.append("compiler manifest is not bound to the task and Hardware IR")
    blocker = json.loads((root / "npu_blocker.json").read_text(encoding="utf-8"))
    if not _target(context)["npu_command_abi_confirmed"] and (blocker.get("status") != "blocked" or manifest.get("npu_blob_emitted") is not False):
        errors.append("NPU ABI absence did not force a compiler fallback")
    try:
        _validate_contracts(root)
    except (ValueError, RuntimeError, SchemaError, ValidationError) as exc:
        errors.append(str(exc))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            independent_root = Path(tmp) / "generated"
            report = _independent(context, Path(tmp))
            if not all(value is True for name, value in report.items() if name.endswith("_pass")):
                errors.append("independent TVM compiler verification did not pass")
            for name in ("model.aeg", "plan.json", "evidence.json", "airtos_policy.json", "cpu_output.txt", "rvv_output.txt", "ort_output.txt"):
                if sha256(root / name) != sha256(independent_root / name):
                    errors.append(f"independent compiler output differs: {name}")
    except RuntimeError as exc:
        errors.append(str(exc))
    return errors


def selftest() -> None:
    from engine.control import Engine
    from socimage.hardware import derive
    from socimage.intake import create_run

    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp) / "run"
        create_run([ROOT / "verification/materials/qemu_virt64_drivers.dts"], run)
        assert derive(run)["ok"]
        result = Engine(run).run_tasks(max_workers=1)
        assert result["ok"], result
        assert result["task_status"]["task:tvm_ai_compiler"] == "passed"
        report = json.loads((run / "integration/generated/compiler/verification.json").read_text(encoding="utf-8"))
        assert report["onnxruntime_numerical_diff_pass"] and report["rvv_instruction_check_pass"]

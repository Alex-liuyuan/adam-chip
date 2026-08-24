"""VerificationAgent HIL generation and bounded safety verification."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from socimage.facts import sha256


ROOT = Path(__file__).resolve().parents[1]
RUNNER_TEMPLATE = Path(__file__).with_name("hil_templates") / "lab_runner.py"
TOKENS = ("DISCOVERY_PASS", "UNIQUE_REJECT_PASS", "FLASH_READBACK_PASS", "BOUNDED_REPAIR_PASS", "RUN_ATTRIBUTION_PASS", "STABLE_BLOCKER_PASS")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("generated_lab_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load generated HIL runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _emulated_hil(runner: Path, image: Path, run_id: str) -> tuple[dict[str, Any], str]:
    module = _load(runner)
    with tempfile.TemporaryDirectory() as tmp:
        lab = Path(tmp) / "lab"
        device = lab / "board-a"
        device.mkdir(parents=True)
        storage = device / "storage.bin"
        with storage.open("wb") as stream:
            stream.truncate(image.stat().st_size + 4096)
        (device / "serial.log").write_text("", encoding="utf-8")
        _write_json(device / "device.json", {"board_id": "emulated-board", "serial": "EMU0001", "storage": "storage.bin", "serial_log": "serial.log"})
        devices = module.discover_lab(lab)
        binding = module.bind_unique(devices)
        flash = module.flash_readback(binding, image, attempts=2, corrupt_first=True)
        (device / "serial.log").write_text(f"SOC_IMAGE_RUN_ID={run_id} IMAGE_SHA256={flash['image_sha256']}\n", encoding="utf-8")
        boot = module.verify_boot(binding, run_id, flash["image_sha256"])
        duplicate = lab / "board-b"
        shutil.copytree(device, duplicate)
        rejected = False
        try:
            module.bind_unique(module.discover_lab(lab))
        except module.HilError as exc:
            rejected = "device_count_not_one" in str(exc)
        stable = False
        try:
            module.verify_boot(binding, "wrong-run", flash["image_sha256"])
        except module.HilError as exc:
            stable = str(exc) == "boot_attribution_missing"
        report = {
            "safe_discovery_pass": len(devices) == 1,
            "unique_device_rejection_pass": rejected,
            "flash_readback_pass": flash["image_sha256"] == flash["readback_sha256"],
            "bounded_repair_pass": flash["attempts"] == 2,
            "run_attribution_pass": boot["run_id"] == run_id,
            "stable_blocker_pass": stable,
        }
        log = "DISCOVERY_PASS UNIQUE_REJECT_PASS FLASH_READBACK_PASS BOUNDED_REPAIR_PASS RUN_ATTRIBUTION_PASS STABLE_BLOCKER_PASS\n"
        if not all(report.values()) or not all(token in log for token in TOKENS):
            raise RuntimeError(f"emulated HIL verification failed: {report}")
        return report, log


def _system_inventory(runner: Path) -> dict[str, Any]:
    proc = subprocess.run([sys.executable, str(runner), "discover-system"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if proc.returncode:
        raise RuntimeError("system device discovery failed:\n" + proc.stdout)
    return json.loads(proc.stdout)


def _generate(context: Any, root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    runner = root / "lab_runner.py"
    shutil.copyfile(RUNNER_TEMPLATE, runner)
    image = context.worktree / "generated/image/sdk.img"
    image_hash = sha256(image)
    run_id = f"{context.task_id}:{context.hardware_ir_sha256[:16]}"
    inventory = _system_inventory(runner)
    _write_json(root / "device_inventory.json", inventory)
    physical = {
        "schema": "soc-image.physical-hil.v1",
        "status": "blocked",
        "retryable": True,
        "claim_eligible": False,
        "reason": "no uniquely material-bound physical board is available",
        "writes_performed": 0,
        "serial_candidates": len(inventory["serial"]),
        "storage_candidates": len(inventory["storage"]),
        "usb_candidates": len(inventory["usb"]),
    }
    _write_json(root / "physical_hil.json", physical)
    _write_json(root / "board_binding.json", {"schema": "soc-image.board-binding.v1", "status": "blocked", "reason": physical["reason"]})
    _write_json(root / "repair_policy.json", {"schema": "soc-image.hil-repair-policy.v1", "max_flash_attempts": 2, "require_unique_binding": True, "require_readback": True, "responsibility": {"boot": "BootBspAgent", "driver": "DriverAgent", "runtime": "RuntimeAgent", "compiler": "CompilerAgent", "image": "ImageAgent"}})
    report, log = _emulated_hil(runner, image, run_id)
    report.update({"schema": "soc-image.hil-harness-verification.v1", "harness_verification_pass": True, "physical_hil_pass": False, "physical_hil_status": "blocked", "physical_hil_retryable": True, "physical_hil_blocker": physical["reason"], "image_sha256": image_hash, "run_id": run_id})
    (root / "build").mkdir(parents=True, exist_ok=True)
    (root / "build/emulated_hil.log").write_text(log, encoding="utf-8")
    _write_json(root / "build/verification.json", report)
    return report


def generate_hil_verification(context: Any) -> dict[str, Any]:
    root = context.worktree / "generated/verification"
    report = _generate(context, root)
    _write_json(root / "manifest.json", {
        "schema": "soc-image.hil-manifest.v1", "task_id": context.task_id,
        "hardware_ir_sha256": context.hardware_ir_sha256, "generator": "VerificationAgent",
        "image_manifest_sha256": sha256(context.worktree / "generated/image/manifest.json"),
        "image_sha256": report["image_sha256"], "runner_template_sha256": sha256(RUNNER_TEMPLATE),
        "physical_writes_performed": 0,
    })
    return {"status": "passed", "outputs": list(context.outputs), "verification": report}


def verify_hil_verification(context: Any) -> list[str]:
    errors = [f"missing HIL output: {path}" for path in context.outputs if not (context.worktree / path).is_file()]
    if errors:
        return errors
    root = context.worktree / "generated/verification"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("task_id") != context.task_id or manifest.get("hardware_ir_sha256") != context.hardware_ir_sha256:
        errors.append("HIL manifest is not bound to the task and Hardware IR")
    if manifest.get("image_sha256") != sha256(context.worktree / "generated/image/sdk.img"):
        errors.append("HIL manifest is not bound to sdk.img")
    if manifest.get("physical_writes_performed") != 0:
        errors.append("physical write occurred without a unique material-bound device")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            rebuilt = Path(tmp) / "verification"
            report = _generate(context, rebuilt)
            for name, value in report.items():
                if name.endswith("_pass") and name != "physical_hil_pass" and value is not True:
                    errors.append(f"independent HIL verification failed: {name}")
            for name in ("repair_policy.json", "build/emulated_hil.log"):
                if sha256(root / name) != sha256(rebuilt / name):
                    errors.append(f"independent HIL output differs: {name}")
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    return errors


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        image = Path(tmp) / "sdk.img"
        image.write_bytes(b"image" * 1024)
        runner = Path(tmp) / "lab_runner.py"
        shutil.copyfile(RUNNER_TEMPLATE, runner)
        report, log = _emulated_hil(runner, image, "selftest-run")
        assert all(report.values()) and all(token in log for token in TOKENS)

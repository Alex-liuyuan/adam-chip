"""Build board-native candidates from the selected open-source stack."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from engine.source_discovery_tools import selected_anchor
from socimage.facts import sha256


K230_CONFIG = "k230_canmv_v3_defconfig"
K230_CONTAINER = "ghcr.nju.edu.cn/kendryte/k230_sdk@sha256:1f9f6be7e7bf6fdbc2c718a224e0cf23366ddc7e1e4b5dc3083635b3f02fd22c"
OFFICIAL_CAPABILITIES = (
    "boot_recovery", "micropython", "sd", "usb", "ethernet", "wifi", "camera",
    "display", "audio", "gpio", "i2c", "spi", "uart", "pwm", "adc", "kpu_ai2d",
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run(command: list[str], *, cwd: Path | None = None, log: Path | None = None) -> None:
    if log is None:
        proc = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        output = proc.stdout
    else:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as stream:
            proc = subprocess.run(command, cwd=cwd, text=True, stdout=stream, stderr=subprocess.STDOUT, check=False)
        output = f"see {log}"
    if proc.returncode:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(command)}: {output}")


def _container_digest() -> str:
    proc = subprocess.run(["docker", "image", "inspect", K230_CONTAINER, "--format", "{{.Id}}"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if proc.returncode:
        _run(["docker", "pull", K230_CONTAINER])
        proc = subprocess.run(["docker", "image", "inspect", K230_CONTAINER, "--format", "{{.Id}}"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if proc.returncode or not proc.stdout.strip().startswith("sha256:"):
        raise RuntimeError("pinned K230 SDK build container is unavailable")
    return proc.stdout.strip()


def _locked_file(source: dict[str, Any], relative: str) -> bytes:
    proc = subprocess.run(["git", "show", f"{source['revision']}:{relative}"], cwd=source["path"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode:
        raise RuntimeError(f"locked K230 SDK file is unavailable: {relative}")
    return proc.stdout


def _build_k230(context: Any, source: dict[str, Any], root: Path) -> dict[str, Any]:
    config_path = f"configs/{K230_CONFIG}"
    config = _locked_file(source, config_path)
    if b'CONFIG_UBOOT_DEFCONFIG="k230_canmv_v3"' not in config:
        raise RuntimeError("selected K230 SDK revision has no matching CanMV V3 boot configuration")
    container_id = _container_digest()
    build_log = context.artifact_dir / "build.log"
    with tempfile.TemporaryDirectory(prefix="soc-image-k230-") as tmp:
        checkout = Path(tmp) / "k230-sdk"
        _run(["git", "worktree", "add", "--detach", str(checkout), source["revision"]], cwd=source["path"])
        try:
            _run(["git", "sparse-checkout", "disable"], cwd=checkout)
            toolchain = checkout / "toolchain"
            toolchain.mkdir()
            command = [
                "docker", "run", "--rm", "-u", "root",
                "-v", f"{checkout}:{checkout}", "-v", f"{toolchain}:/opt/toolchain",
                "-w", str(checkout), K230_CONTAINER, "bash", "-lc",
                f"make CONF={K230_CONFIG} prepare_sourcecode && make CONF={K230_CONFIG}",
            ]
            _run(command, log=build_log)
            images = sorted((checkout / "output" / K230_CONFIG / "images").glob("sysimage-sdcard*.img"))
            if not images:
                raise RuntimeError("K230 SDK build did not produce an SD-card image")
            image = images[0]
            destination = context.artifact_dir / "sdk.img"
            shutil.copyfile(image, destination)
        finally:
            _run(["git", "worktree", "remove", "--force", str(checkout)], cwd=source["path"])
    coverage = {
        "schema": "soc-image.official-coverage.v1",
        "reference": "CanMV_K230_V3P0_micropython_v1.8-0-gc2d1f5c_nncase_v2.11.0.img",
        "capabilities": [{"id": name, "status": "unverified"} for name in OFFICIAL_CAPABILITIES],
        "replacement_gate_pass": False,
        "reason": "physical HIL and MicroPython/API compatibility have not passed",
    }
    _write(root / "capability_coverage.json", coverage)
    manifest = {
        "schema": "soc-image.source-stack-manifest.v1",
        "task_id": context.task_id,
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "source_lock_sha256": source["source_lock_sha256"],
        "source": {"id": source["id"], "revision": source["revision"], "config": config_path, "config_sha256": hashlib.sha256(config).hexdigest()},
        "build_container": {"reference": K230_CONTAINER, "image_id": container_id},
        "image": {"name": "sdk.img", "sha256": sha256(context.artifact_dir / "sdk.img"), "bytes": (context.artifact_dir / "sdk.img").stat().st_size},
        "release_class": "unsigned_test_candidate",
        "replacement_gate_pass": False,
        "unlocked_vendor_inputs": ["nncase runtime package", "KModel package", "Wi-Fi firmware", "Buildroot download cache"],
    }
    _write(root / "manifest.json", manifest)
    report = {"schema": "soc-image.source-stack-verification.v1", "image_present_pass": True, "source_lock_pass": True, "container_lock_pass": True, "replacement_gate_pass": False}
    _write(root / "verification.json", report)
    return report


def generate_source_stack_image(context: Any) -> dict[str, Any]:
    source = selected_anchor(context)
    if source["id"] != "k230-sdk":
        raise RuntimeError(f"no board-native source stack adapter for {source['id']}")
    root = context.worktree / "generated/source_stack"
    report = _build_k230(context, source, root)
    return {"status": "passed", "outputs": list(context.outputs), "artifacts": ["sdk.img", "build.log"], "verification": report}


def verify_source_stack_image(context: Any) -> list[str]:
    errors = [f"missing source-stack output: {path}" for path in context.outputs if not (context.worktree / path).is_file()]
    errors.extend(f"missing source-stack artifact: {name}" for name in ("sdk.img", "build.log") if not (context.artifact_dir / name).is_file())
    if errors:
        return errors
    manifest = json.loads((context.worktree / "generated/source_stack/manifest.json").read_text(encoding="utf-8"))
    source = selected_anchor(context)
    image = context.artifact_dir / "sdk.img"
    if manifest.get("task_id") != context.task_id or manifest.get("hardware_ir_sha256") != context.hardware_ir_sha256:
        errors.append("source-stack manifest is not bound to task and Hardware IR")
    if manifest.get("source_lock_sha256") != source["source_lock_sha256"]:
        errors.append("source-stack manifest is not bound to source lock")
    if manifest.get("image", {}).get("sha256") != sha256(image) or manifest.get("image", {}).get("bytes") != image.stat().st_size:
        errors.append("source-stack image hash or size mismatch")
    if image.stat().st_size < 16 * 1024 * 1024:
        errors.append("source-stack image is implausibly small")
    return errors

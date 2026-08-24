"""ImageAgent deterministic image composition and verification tools."""

from __future__ import annotations

import io
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from socimage.facts import sha256


ROOT = Path(__file__).resolve().parents[1]
UNPACK_TEMPLATE = Path(__file__).with_name("image_templates") / "unpack_image.py"
SECTOR = 512
ALIGN_SECTORS = 2048
PARTITION_TYPE = 0xDA


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _files(root: Path, relative: str, *, exclude: tuple[str, ...] = ()) -> list[Path]:
    base = root / relative
    paths = [base] if base.is_file() else sorted(path for path in base.rglob("*") if path.is_file())
    return [path for path in paths if not any(path.match(pattern) for pattern in exclude)]


def _partition_inputs(worktree: Path, metadata: Path) -> dict[str, list[Path]]:
    return {
        "boot": [
            worktree / "generated/platform/manifest.json",
            *_files(worktree, "generated/platform/boot"),
            worktree / "generated/platform/build/rtthread.elf",
            worktree / "generated/platform/build/rtthread.bin",
        ],
        "system": [
            *_files(worktree, "generated/drivers"),
            *_files(worktree, "generated/rt_ai/os"),
            *_files(worktree, "generated/rt_ai/runtime", exclude=("*/build/*", "*/tests/*", "*rt_ai_port_host.c")),
        ],
        "ai": [
            *_files(worktree, "generated/compiler", exclude=("*aeg_check*", "*output.txt", "*verification.json", "*rvv_objdump.txt")),
        ],
        "product": [
            *_files(worktree, "generated/product", exclude=("*/build/*", "*product_smoke.c")),
            metadata,
        ],
    }


def _tar(worktree: Path, paths: list[Path]) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.GNU_FORMAT) as archive:
        entries = [
            (str(path.relative_to(worktree)) if path.is_relative_to(worktree) else f"generated/image/{path.name}", path)
            for path in set(paths)
        ]
        for name, path in sorted(entries):
            content = path.read_bytes()
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(content))
    return stream.getvalue()


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def _compose(worktree: Path, destination: Path, partitions: dict[str, list[Path]], disk_signature: int) -> dict[str, Any]:
    payloads = [(name, _tar(worktree, paths)) for name, paths in partitions.items()]
    mbr = bytearray(SECTOR)
    struct.pack_into("<I", mbr, 440, disk_signature)
    layout = []
    start = ALIGN_SECTORS
    for index, (name, payload) in enumerate(payloads):
        sectors = (len(payload) + SECTOR - 1) // SECTOR
        struct.pack_into("<B3sB3sII", mbr, 446 + index * 16, 0, b"\xff\xff\xff", PARTITION_TYPE, b"\xff\xff\xff", start, sectors)
        layout.append({"name": name, "index": index + 1, "start_lba": start, "sectors": sectors, "payload_sha256": hashlib.sha256(payload).hexdigest(), "payload_bytes": len(payload)})
        start = _align(start + sectors, ALIGN_SECTORS)
    mbr[510:512] = b"\x55\xaa"
    image = bytearray(start * SECTOR)
    image[:SECTOR] = mbr
    for item, (_, payload) in zip(layout, payloads):
        offset = item["start_lba"] * SECTOR
        image[offset:offset + len(payload)] = payload
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(image)
    return {"schema": "soc-image.mbr-layout.v1", "sector_bytes": SECTOR, "alignment_sectors": ALIGN_SECTORS, "partitions": layout, "image_bytes": len(image), "image_sha256": sha256(destination)}


def _ancestry(context: Any) -> dict[str, Any]:
    manifests = []
    for path in sorted((context.worktree / "generated").rglob("manifest.json")):
        if path.is_relative_to(context.worktree / "generated/image") or path.is_relative_to(context.worktree / "generated/evaluation"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("hardware_ir_sha256") != context.hardware_ir_sha256:
            raise ValueError(f"manifest is not bound to Hardware IR: {path}")
        manifests.append({"path": str(path.relative_to(context.worktree)), "sha256": sha256(path), "generator": data.get("generator"), "task_id": data.get("task_id")})
        if data.get("canmv_source_used") is True or data.get("overlay_used") is True or data.get("legacy_rvaic_used") is True:
            raise ValueError(f"prohibited component ancestry: {path}")
    if len(manifests) < 7 or any(not item["generator"] or not item["task_id"] for item in manifests):
        raise ValueError("component manifest ancestry is incomplete")
    return {
        "schema": "soc-image.ancestry.v1",
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "manifests": manifests,
        "official_image_used": False,
        "canmv_source_used": False,
        "target_sdk_used": False,
        "existing_defconfig_used": False,
    }


def _unpack(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "unpacked"
        proc = subprocess.run(
            [sys.executable, str(root / "unpack_image.py"), str(root / "sdk.img"), "--out", str(output)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if proc.returncode:
            raise RuntimeError("image unpack failed:\n" + proc.stdout)
        return json.loads((output / "unpack-result.json").read_text(encoding="utf-8"))


def _generate(context: Any, root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(UNPACK_TEMPLATE, root / "unpack_image.py")
    ancestry = _ancestry(context)
    _write_json(root / "ancestry.json", ancestry)
    initial = _partition_inputs(context.worktree, root / "ancestry.json")
    components = {
        "schema": "soc-image.component-manifest.v1",
        "task_id": context.task_id,
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "components": [
            {"partition": name, "path": str(path.relative_to(context.worktree)) if path.is_relative_to(context.worktree) else f"generated/image/{path.name}", "sha256": sha256(path), "bytes": path.stat().st_size}
            for name, paths in initial.items() for path in paths
        ],
    }
    _write_json(root / "component_manifest.json", components)
    partitions = _partition_inputs(context.worktree, root / "component_manifest.json")
    partitions["product"].append(root / "ancestry.json")
    disk_signature = int(context.hardware_ir_sha256[:8], 16)
    layout = _compose(context.worktree, root / "sdk.img", partitions, disk_signature)
    _write_json(root / "layout.json", layout)
    with tempfile.TemporaryDirectory() as tmp:
        second = Path(tmp) / "sdk.img"
        second_layout = _compose(context.worktree, second, partitions, disk_signature)
        reproducible = layout["image_sha256"] == second_layout["image_sha256"]
    unpacked = _unpack(root)
    extracted = {item["path"]: item["sha256"] for item in unpacked["files"]}
    missing = [item["path"] for item in components["components"] if extracted.get(item["path"]) != item["sha256"]]
    report = {
        "schema": "soc-image.image-verification.v1",
        "reproducible_build_pass": reproducible,
        "mbr_partition_pass": len(layout["partitions"]) == 4,
        "unpack_pass": not missing,
        "component_traceability_pass": not missing,
        "ancestry_policy_pass": not any(ancestry[key] for key in ("official_image_used", "canmv_source_used", "target_sdk_used", "existing_defconfig_used")),
        "sdk_img_sha256": layout["image_sha256"],
    }
    if not all(value is True for key, value in report.items() if key.endswith("_pass")):
        raise RuntimeError(f"image verification failed: {report}; missing={missing}")
    _write_json(root / "build/verification.json", report)
    return report


def generate_source_image(context: Any) -> dict[str, Any]:
    root = context.worktree / "generated/image"
    report = _generate(context, root)
    _write_json(root / "manifest.json", {
        "schema": "soc-image.image-manifest.v1",
        "task_id": context.task_id,
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "generator": "ImageAgent",
        "source_date_epoch": 0,
        "sdk_img_sha256": report["sdk_img_sha256"],
        "unpack_template_sha256": sha256(UNPACK_TEMPLATE),
        "ancestry_sha256": sha256(root / "ancestry.json"),
        "component_manifest_sha256": sha256(root / "component_manifest.json"),
    })
    return {"status": "passed", "outputs": list(context.outputs), "verification": report}


def verify_source_image(context: Any) -> list[str]:
    errors = [f"missing image output: {path}" for path in context.outputs if not (context.worktree / path).is_file()]
    if errors:
        return errors
    root = context.worktree / "generated/image"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("task_id") != context.task_id or manifest.get("hardware_ir_sha256") != context.hardware_ir_sha256:
        errors.append("image manifest is not bound to the task and Hardware IR")
    if manifest.get("sdk_img_sha256") != sha256(root / "sdk.img"):
        errors.append("sdk.img hash does not match image manifest")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            rebuilt = Path(tmp) / "image"
            report = _generate(context, rebuilt)
            if report["sdk_img_sha256"] != manifest.get("sdk_img_sha256"):
                errors.append("independent image rebuild differs")
            for name in ("layout.json", "component_manifest.json", "ancestry.json"):
                if sha256(root / name) != sha256(rebuilt / name):
                    errors.append(f"independent image metadata differs: {name}")
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
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
        assert result["task_status"]["task:source_image"] == "passed"
        report = json.loads((run / "integration/generated/image/build/verification.json").read_text(encoding="utf-8"))
        assert report["reproducible_build_pass"] and report["ancestry_policy_pass"]

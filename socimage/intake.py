"""Create and validate immutable hardware-material run inputs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/intake.schema.json"
LOCK_NAME = "materials.lock.json"
LEGACY_PROJECT_KEYS = {"platform", "target", "runtime", "image_media", "firmware"}
KIND_BY_SUFFIX = {
    ".pdf": "document",
    ".txt": "document",
    ".md": "document",
    ".html": "document",
    ".htm": "document",
    ".doc": "document",
    ".docx": "document",
    ".xls": "document",
    ".xlsx": "document",
    ".csv": "document",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tif": "image",
    ".tiff": "image",
    ".bmp": "image",
    ".svd": "svd",
    ".dts": "dts",
    ".dtsi": "dts",
    ".pdsc": "cmsis_pack",
    ".pack": "cmsis_pack",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return cleaned or "material"


def _project_id(out: Path) -> str:
    return _safe_name(out.name)


def _reject_legacy_project(path: Path) -> None:
    if path.suffix.lower() != ".json":
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    schema = str(data.get("schema", data.get("$schema", ""))).lower()
    if "project_order" in schema or len(LEGACY_PROJECT_KEYS & set(data)) >= 2:
        raise ValueError(f"legacy software project orders are not hardware materials: {path}")


def inspect_materials(paths: Iterable[Path]) -> list[dict[str, Any]]:
    materials: dict[str, dict[str, Any]] = {}
    for supplied in paths:
        path = supplied.expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"hardware material is missing or is not a file: {path}")
        if path.stat().st_size == 0:
            raise ValueError(f"hardware material is empty: {path}")
        _reject_legacy_project(path)
        digest = _sha256(path)
        name = _safe_name(path.name)
        item = {
            "name": name,
            "kind": KIND_BY_SUFFIX.get(path.suffix.lower(), "unknown"),
            "source_path": str(path),
            "stored_path": f"materials/{digest[:16]}-{name}",
            "sha256": digest,
            "bytes": path.stat().st_size,
        }
        existing = materials.get(digest)
        if existing is None or (item["source_path"], item["name"]) < (existing["source_path"], existing["name"]):
            materials[digest] = item
    if not materials:
        raise ValueError("at least one hardware material is required")
    return sorted(materials.values(), key=lambda item: (item["sha256"], item["name"]))


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_lock(data: dict[str, Any]) -> list[str]:
    errors = sorted(Draft202012Validator(_schema()).iter_errors(data), key=lambda item: list(item.path))
    return [error.message for error in errors]


def _lock(project_id: str, materials: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "soc-image.intake.v1",
        "project_id": project_id,
        "materials": materials,
        "software_configuration_accepted": False,
    }


def _same_inputs(existing: dict[str, Any], requested: dict[str, Any]) -> bool:
    identity = lambda data: sorted(
        (item.get("sha256"), item.get("bytes"), item.get("kind")) for item in data.get("materials", [])
    )
    return (
        existing.get("schema") == requested.get("schema")
        and existing.get("project_id") == requested.get("project_id")
        and existing.get("software_configuration_accepted") is False
        and identity(existing) == identity(requested)
    )


def create_run(paths: Iterable[Path], out: Path) -> dict[str, Any]:
    out = out.expanduser().resolve()
    materials = inspect_materials(paths)
    requested = _lock(_project_id(out), materials)
    errors = validate_lock(requested)
    if errors:
        raise ValueError("; ".join(errors))

    lock_path = out / LOCK_NAME
    if out.exists():
        if not lock_path.is_file():
            raise ValueError(f"run directory already exists without {LOCK_NAME}: {out}")
        existing = json.loads(lock_path.read_text(encoding="utf-8"))
        if not _same_inputs(existing, requested):
            raise ValueError(f"run directory is bound to different material content: {out}")
        loaded = load_run(out)
        loaded["created"] = False
        return loaded

    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.intake-", dir=out.parent))
    try:
        (staging / "materials").mkdir()
        for item in materials:
            source = Path(item["source_path"])
            destination = staging / item["stored_path"]
            shutil.copyfile(source, destination)
            if destination.stat().st_size != item["bytes"] or _sha256(destination) != item["sha256"]:
                raise RuntimeError(f"staged material verification failed: {source}")
        for directory in ("artifacts", "candidates", "reports", "release"):
            (staging / directory).mkdir()
        (staging / LOCK_NAME).write_text(json.dumps(requested, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(staging, out)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    loaded = load_run(out)
    loaded["created"] = True
    return loaded


def load_run(out: Path) -> dict[str, Any]:
    out = out.expanduser().resolve()
    lock_path = out / LOCK_NAME
    if not lock_path.is_file():
        raise ValueError(f"run does not contain {LOCK_NAME}: {out}")
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    errors = validate_lock(data)
    if errors:
        return {
            "ok": False,
            "status": "intake_invalid",
            "project_id": data.get("project_id"),
            "run": str(out),
            "materials_lock": str(lock_path),
            "material_count": 0,
            "next_stage": None,
            "errors": errors,
        }
    for item in data.get("materials", []):
        stored = out / str(item.get("stored_path", ""))
        if not stored.is_file():
            errors.append(f"staged material is missing: {stored}")
            continue
        if stored.stat().st_size != item.get("bytes"):
            errors.append(f"staged material size mismatch: {stored}")
        elif _sha256(stored) != item.get("sha256"):
            errors.append(f"staged material hash mismatch: {stored}")
    return {
        "ok": not errors,
        "status": "intake_complete" if not errors else "intake_invalid",
        "project_id": data.get("project_id"),
        "run": str(out),
        "materials_lock": str(lock_path),
        "material_count": len(data.get("materials", [])),
        "next_stage": "hardware_ir" if not errors else None,
        "errors": errors,
    }


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first = root / "soc manual.pdf"
        second = root / "board.svd"
        first.write_bytes(b"soc manual")
        second.write_bytes(b"registers")
        out = root / "board-a"
        created = create_run([first, second, first], out)
        assert created["ok"] and created["created"] and created["material_count"] == 2
        reused = create_run([second, first], out)
        assert reused["ok"] and not reused["created"]
        renamed = root / "renamed.pdf"
        renamed.write_bytes(first.read_bytes())
        reused_by_content = create_run([renamed, second], out)
        assert reused_by_content["ok"] and not reused_by_content["created"]
        staged = json.loads((out / LOCK_NAME).read_text(encoding="utf-8"))
        assert staged["software_configuration_accepted"] is False
        (out / staged["materials"][0]["stored_path"]).write_bytes(b"tampered")
        assert not load_run(out)["ok"]

        legacy = root / "project.json"
        legacy.write_text(json.dumps({"platform": "vendor", "target": "target.json", "runtime": "rtos"}), encoding="utf-8")
        try:
            create_run([legacy], root / "legacy")
        except ValueError as exc:
            assert "legacy software project" in str(exc)
        else:
            raise AssertionError("legacy project order was accepted as hardware material")

        empty = root / "empty.pdf"
        empty.touch()
        try:
            create_run([empty], root / "empty")
        except ValueError as exc:
            assert "empty" in str(exc)
        else:
            raise AssertionError("empty hardware material was accepted")

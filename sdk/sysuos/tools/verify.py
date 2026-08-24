#!/usr/bin/env python3
"""Verify an immutable SDK and an optional external SoC workspace."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


PROVIDERS = ("boot", "device", "media", "accelerator", "image")
STABLE_COMPONENTS = {"micropython", "sysu_compat", "rt_ai", "compiler_runtime"}
FORBIDDEN = {".bin", ".img", ".iso", ".elf", ".so", ".a", ".o", ".der", ".pem", ".key", ".sig"}
PYTHON_CACHE_SUFFIXES = {".pyc", ".pyo"}


def safe(value: object) -> bool:
    return isinstance(value, str) and bool(value) and not Path(value).is_absolute() and ".." not in Path(value).parts


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def is_python_cache(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix.lower() in PYTHON_CACHE_SUFFIXES


def tree_hash(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("project source is missing, not a directory, or a symlink")
    files = []
    for current, directories, names in os.walk(root, followlinks=False):
        for name in [*directories, *names]:
            if (Path(current) / name).is_symlink():
                raise ValueError(f"unsafe project source symlink: {name}")
        files.extend(Path(current) / name for name in names)
    files = sorted((path for path in files if not is_python_cache(path.relative_to(root))), key=lambda path: path.relative_to(root).as_posix())
    if not files or any(not path.is_file() for path in files):
        raise ValueError("project source tree is empty or contains non-files")
    digest = hashlib.sha256()
    for path in files:
        data = path.read_bytes()
        mode = b"100755" if path.stat().st_mode & 0o111 else b"100644"
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + mode + b"\0" + len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def pinned(source: dict) -> bool:
    content = source.get("content_hash", {})
    revision = source.get("revision", "")
    return (
        len(revision) == 40 and all(char in "0123456789abcdef" for char in revision)
        and content.get("algorithm") == "sha256-git-ls-tree-v1" and len(content.get("value", "")) == 64
        and source.get("selected_paths") and all(safe(path) for path in source["selected_paths"])
    )


def identity(source: dict) -> dict:
    return {
        "id": source["repository"], "revision": source["revision"], "content_hash": source["content_hash"]["value"],
        "source_usage": source["source_usage"], "redistribution": source["redistribution"],
    }


def workspace_file(pack_root: Path, value: str, label: str) -> Path:
    path = pack_root / value
    if not safe(value) or path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(pack_root):
        raise ValueError(f"invalid {label}: {value}")
    return path


def verify_provider(root: Path, pack_root: Path, name: str, provider: dict) -> None:
    implementation = provider["implementation"]
    if implementation is None:
        return
    descriptor = workspace_file(pack_root, implementation, f"{name} provider implementation")
    data = load(descriptor)
    Draft202012Validator(load(root / provider["contract"])).validate(data)
    if data["kind"] != name:
        raise ValueError(f"provider kind mismatch: {name}")
    for source in data["sources"]:
        source_path = workspace_file(pack_root, source["path"], f"{name} provider source")
        if set(source) != {"path", "sha256"} or sha256(source_path) != source["sha256"]:
            raise ValueError(f"provider source hash mismatch: {name}")
    for test in data["tests"]:
        workspace_file(pack_root, test, f"{name} provider test")


def verify_pack(root: Path, pack_path: Path, bundled: bool) -> None:
    pack_path = pack_path.expanduser().resolve()
    bundled_root = (root / "soc").resolve()
    if pack_path.is_symlink() or not pack_path.is_file() or (bundled and not pack_path.is_relative_to(bundled_root)):
        raise ValueError("pack is not a regular SoC pack")
    pack_root = pack_path.parent.resolve()
    pack = load(pack_path)
    Draft202012Validator(load(root / "contracts/soc_pack.schema.json")).validate(pack)
    if not bundled and not pack["hardware_materials"]:
        raise ValueError("external SoC workspaces require hardware materials")
    for material in pack["hardware_materials"]:
        path = workspace_file(pack_root, material["stored_path"], "hardware material")
        if path.stat().st_size != material["bytes"] or sha256(path) != material["sha256"]:
            raise ValueError(f"hardware material hash mismatch: {material['name']}")

    plan = load(workspace_file(pack_root, pack["adaptation_plan"], "adaptation plan"))
    Draft202012Validator(load(root / "contracts/adaptation_plan.schema.json")).validate(plan)
    if plan["soc"] != pack["soc"] or plan["board"] != pack["board"] or set(plan["stable_components"]) != STABLE_COMPONENTS:
        raise ValueError("adaptation plan identity or stable components differ")
    tasks = {task["provider"]: task for task in plan["tasks"]}
    if set(tasks) != set(PROVIDERS) or any(task["id"] != f"provider:{name}" for name, task in tasks.items()):
        raise ValueError("adaptation plan must contain one task per provider")
    if plan["base"] is not None:
        base_path = root / "soc" / plan["base"]["soc"] / "pack.json"
        if not base_path.is_file() or sha256(base_path) != plan["base"]["pack_sha256"]:
            raise ValueError("base SoC pack identity mismatch")

    if set(pack["providers"]) != set(PROVIDERS):
        raise ValueError("missing provider replacement contract")
    for name in PROVIDERS:
        provider = pack["providers"][name]
        if (provider.get("replacement_required") is not True
                or provider.get("contract") != f"contracts/{name}_provider.schema.json"
                or not (root / provider["contract"]).is_file()):
            raise ValueError(f"missing provider replacement contract: {name}")
        verify_provider(root, pack_root, name, provider)
        status = tasks[name]["status"]
        if (provider["implementation"] is None) != (status in {"pending", "blocked"}):
            raise ValueError(f"provider implementation and task status disagree: {name}")
        if status in {"candidate", "verified"}:
            for value in tasks[name]["required_outputs"]:
                workspace_file(pack_root, value, f"{name} task output")

    if not all(pinned(item) for item in pack["sources"]):
        raise ValueError("unpinned SoC source descriptor")
    for value in [*pack["patches"], *pack["tests"]]:
        path = workspace_file(pack_root, value, "pack path")
        if path.suffix.lower() in FORBIDDEN:
            raise ValueError(f"forbidden pack artifact: {value}")


def verify(root_path: Path, requested_pack: Path | None = None) -> None:
    if root_path.is_symlink():
        raise ValueError("unsafe SDK root symlink")
    root = root_path.resolve()
    files = {}
    for current, directories, names in os.walk(root, followlinks=False):
        if "__pycache__" in directories:
            raise ValueError(f"generated Python cache artifact: {Path(current) / '__pycache__'}")
        for name in [*directories, *names]:
            if (Path(current) / name).is_symlink():
                raise ValueError(f"unsafe symlink: {name}")
        for name in names:
            path = Path(current) / name
            relative = path.relative_to(root)
            if is_python_cache(relative):
                raise ValueError(f"generated Python cache artifact: {relative}")
            if path.suffix.lower() in FORBIDDEN:
                raise ValueError(f"forbidden binary ancestry: {relative}")
            if name != "manifest.json":
                files[relative.as_posix()] = sha256(path)
    manifest = load(root / "manifest.json")
    if set(manifest) != {"schema", "files"} or manifest.get("schema") != "sysuos.sdk-manifest.v1" or files != manifest["files"]:
        raise ValueError("manifest content mismatch")

    sdk = load(root / "sdk.json")
    lock_path = root / sdk.get("source_context_lock", "")
    lock = load(lock_path)
    locked = {item["repository"]: identity(item) for item in lock.get("sources", [])}
    actual = {identity(item)["id"]: identity(item) for item in sdk.get("source_layers", [])}
    if (set(sdk.get("provider_contracts", [])) != set(PROVIDERS) or not all(pinned(item) for item in sdk.get("source_layers", []))
            or sha256(lock_path) != sdk.get("source_context_lock_sha256") or lock.get("schema") != "sysuos.source-context-lock.v1"
            or len(locked) != len(lock.get("sources", [])) or actual != locked):
        raise ValueError("source context identity mismatch or unpinned source descriptor")

    component_validator = Draft202012Validator(load(root / "contracts/component.schema.json"))
    found = []
    for value in sdk["components"]:
        descriptor = root / value
        if not safe(value) or descriptor.is_symlink() or not descriptor.is_file() or not descriptor.resolve().is_relative_to(root):
            raise ValueError(f"invalid component descriptor: {value}")
        data = load(descriptor)
        component_validator.validate(data)
        found.append(data["id"])
        if "source_context" in data["source"] and data["source"]["source_context"] not in locked:
            raise ValueError(f"unknown component source context: {data['id']}")
        if "project_source" in data["source"]:
            source = data["source"]["project_source"]
            source_path = root / source["project_path"]
            if not safe(source["project_path"]) or source_path.is_symlink() or tree_hash(source_path) != source["content_hash"]:
                raise ValueError(f"project source hash mismatch: {data['id']}")
    if len(found) != len(set(found)) or set(found) != STABLE_COMPONENTS:
        raise ValueError("stable component IDs differ")

    for pack_path in sorted((root / "soc").glob("*/pack.json")):
        verify_pack(root, pack_path, bundled=True)
    if requested_pack is not None:
        verify_pack(root, requested_pack, bundled=requested_pack.resolve().is_relative_to((root / "soc").resolve()))


if __name__ == "__main__":
    try:
        verify(Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parents[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else None)
        print("ok")
    except Exception as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        raise SystemExit(1)

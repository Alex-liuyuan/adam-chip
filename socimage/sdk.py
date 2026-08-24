"""Versioned, deterministic SYSUOS source adaptation kit."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator

from engine.source_discovery_tools import _tree_content_hash
from socimage.intake import inspect_materials


ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "sdk/sysuos"
SDK_SCHEMA = ROOT / "schemas/sysuos_sdk.schema.json"
PACK_SCHEMA = KIT / "contracts/soc_pack.schema.json"
ADAPTATION_SCHEMA = KIT / "contracts/adaptation_plan.schema.json"
PROVIDERS = ("boot", "device", "media", "accelerator", "image")
FORBIDDEN_SUFFIXES = {".bin", ".img", ".iso", ".elf", ".so", ".a", ".o", ".der", ".pem", ".key", ".sig"}
PYTHON_CACHE_SUFFIXES = {".pyc", ".pyo"}
COMPONENTS = {"micropython", "sysu_compat", "rt_ai", "compiler_runtime"}
PROJECT_SOURCES = {
    "rt_ai": ("54dc00ff2b85a977c2f1082c830cfd5fb5801bce", "9114c40b7c63ba6c41f8f3febf4227b0cc4f9cb782aee30acc96537125771b82"),
    "compiler_runtime": ("54dc00ff2b85a977c2f1082c830cfd5fb5801bce", "61c6bc42a35700203e18ad18acde2a4cef360c89c4aafa50dceb1f111bb5c6c2"),
}
CONTEXT_ROOT = ROOT / ".agent-context"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_files(root: Path) -> list[Path]:
    root = root.resolve()
    files = []
    for current, directories, names in os.walk(root, followlinks=False):
        base = Path(current)
        for name in [*directories, *names]:
            path = base / name
            if path.is_symlink():
                raise ValueError(f"unsafe symlink: {path.relative_to(root)}")
        for name in names:
            path = base / name
            if not path.resolve().is_relative_to(root):
                raise ValueError(f"unsafe path: {path}")
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _is_python_cache(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix.lower() in PYTHON_CACHE_SUFFIXES


def _has_python_cache(root: Path) -> bool:
    return any("__pycache__" in directories or any(Path(name).suffix.lower() in PYTHON_CACHE_SUFFIXES for name in names)
               for _, directories, names in os.walk(root, followlinks=False))


def _manifest(root: Path) -> dict[str, str]:
    root = root.resolve()
    return {path.relative_to(root).as_posix(): _sha256(path) for path in _safe_files(root) if path.name != "manifest.json"}


def _tree_hash(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("project source is missing, not a directory, or a symlink")
    files = [path for path in _safe_files(root) if not _is_python_cache(path.relative_to(root.resolve()))]
    if not files or any(not path.is_file() for path in files):
        raise ValueError("project source tree is empty or contains non-files")
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root.resolve()).as_posix().encode()
        mode = b"100755" if path.stat().st_mode & 0o111 else b"100644"
        data = path.read_bytes()
        digest.update(relative + b"\0" + mode + b"\0" + len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def _validate_descriptor(item: dict[str, Any]) -> None:
    if not isinstance(item.get("revision"), str) or len(item["revision"]) != 40 or any(c not in "0123456789abcdef" for c in item["revision"]):
        raise ValueError(f"unpinned source descriptor: {item.get('id', '<unknown>')}")
    content_hash = item.get("content_hash", {})
    if content_hash.get("algorithm") != "sha256-git-ls-tree-v1" or len(content_hash.get("value", "")) != 64:
        raise ValueError(f"unpinned source content: {item.get('id', '<unknown>')}")


def _safe_relative(value: Any) -> bool:
    return isinstance(value, str) and value and not Path(value).is_absolute() and ".." not in Path(value).parts


def _source_identity(item: dict[str, Any]) -> dict[str, str]:
    return {"id": item["repository"], "revision": item["revision"], "content_hash": item["content_hash"]["value"],
            "source_usage": item["source_usage"], "redistribution": item["redistribution"]}


def _locked_contexts(root: Path = ROOT, kit: Path = KIT) -> list[dict[str, Any]]:
    packaged = _json(kit / "source-context.lock.json")
    if set(packaged) != {"schema", "sources"} or packaged["schema"] != "sysuos.source-context-lock.v1":
        raise ValueError("packaged source context lock is invalid")
    manifest = _json(root / "third_party.manifest.json")
    dependencies = _json(root / "third_party.lock.json").get("dependencies", {})
    entries = [item for group in manifest.values() for item in group]
    third_party = (root / "third_party").resolve()
    contexts = []
    for context in packaged["sources"]:
        repository = context.get("repository")
        if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", repository):
            raise ValueError(f"invalid locked source repository: {repository}")
        matches = [item for item in entries if item.get("name") == repository]
        dependency = dependencies.get(repository)
        if len(matches) != 1 or not isinstance(dependency, dict):
            raise ValueError(f"locked source metadata is unavailable: {repository}")
        item = matches[0]
        metadata = ("revision", "source_usage", "license", "redistribution")
        if (item.get("mode") != "pinned_sparse" or dependency.get("kind") != "git"
                or any(item.get(key) != context.get(key) for key in metadata)
                or dependency.get("revision") != context.get("revision")
                or not isinstance(item.get("paths"), list)
                or any(not any(path == sparse or path.startswith(sparse.rstrip("/") + "/")
                               for sparse in item["paths"])
                       for path in context.get("selected_paths", []))):
            raise ValueError(f"locked source metadata differs: {repository}")
        checkout_path = third_party / repository
        checkout = checkout_path.resolve()
        if checkout.parent != third_party or checkout_path.is_symlink() or not checkout.is_dir() or not (checkout / ".git").exists():
            raise ValueError(f"locked source checkout is unavailable: {repository}")
        for path in context["selected_paths"]:
            _tree_content_hash(checkout, context["revision"], [path])
        if _tree_content_hash(checkout, context["revision"], context["selected_paths"]) != context["content_hash"]:
            raise ValueError(f"locked source content differs: {repository}")
        contexts.append(context)
    if len(contexts) != len({item["repository"] for item in contexts}):
        raise ValueError("packaged source context IDs are not unique")
    return contexts


def _resolved_contexts(context_root: Path = CONTEXT_ROOT, root: Path = ROOT, kit: Path = KIT) -> list[dict[str, Any]]:
    paths = sorted(context_root.glob("*/.source-context.json"))
    if not paths:
        return _locked_contexts(root, kit)
    return [_json(path) for path in paths]


def _context_lock(contexts: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema": "sysuos.source-context-lock.v1", "sources": contexts}


def _verify_components(root: Path, sdk: dict[str, Any], contexts: set[str]) -> None:
    validator = Draft202012Validator(_json(root / "contracts/component.schema.json"))
    found = []
    for value in sdk["components"]:
        path = root / value
        if (not _safe_relative(value) or path.is_symlink() or not path.is_file()
                or not path.resolve().is_relative_to(root)):
            raise ValueError(f"invalid component descriptor: {value}")
        component = _json(path)
        validator.validate(component)
        found.append(component["id"])
        if "source_context" in component["source"] and component["source"]["source_context"] not in contexts:
            raise ValueError(f"unknown component source context: {component['id']}")
        if "project_source" in component["source"]:
            source = component["source"]["project_source"]
            source_path = root / source["project_path"]
            if ((source["revision"], source["content_hash"]) != PROJECT_SOURCES.get(component["id"])
                    or not _safe_relative(source["project_path"]) or source_path.is_symlink()
                    or not source_path.resolve().is_relative_to(root.resolve())
                    or _tree_hash(source_path) != source["content_hash"]):
                raise ValueError(f"project source hash mismatch: {component['id']}")
    if len(found) != len(set(found)) or set(found) != COMPONENTS:
        raise ValueError("component IDs must be exactly micropython, sysu_compat, rt_ai, compiler_runtime")


def _verify_provider(root: Path, pack_path: Path, name: str, provider: dict[str, Any]) -> None:
    implementation = provider["implementation"]
    if implementation is None:
        return
    descriptor = pack_path.parent / implementation
    pack_root = pack_path.parent.resolve()
    if not _safe_relative(implementation) or descriptor.is_symlink() or not descriptor.is_file() or not descriptor.resolve().is_relative_to(pack_root):
        raise ValueError(f"invalid {name} provider implementation")
    contract = root / provider["contract"]
    data = _json(descriptor)
    Draft202012Validator(_json(contract)).validate(data)
    if data["kind"] != name:
        raise ValueError(f"provider kind mismatch: {name}")
    for source in data["sources"]:
        source_path = pack_path.parent / source["path"]
        if (not _safe_relative(source["path"]) or source_path.is_symlink() or not source_path.is_file()
                or not source_path.resolve().is_relative_to(pack_root) or _sha256(source_path) != source["sha256"]):
            raise ValueError(f"provider source hash mismatch: {name}")
    for value in data["tests"]:
        test_path = pack_path.parent / value
        if (not _safe_relative(value) or test_path.is_symlink() or not test_path.is_file()
                or not test_path.resolve().is_relative_to(pack_root)):
            raise ValueError(f"invalid provider test: {name}")


def _workspace_file(pack_root: Path, value: str, label: str) -> Path:
    path = pack_root / value
    if (not _safe_relative(value) or path.is_symlink() or not path.is_file()
            or not path.resolve().is_relative_to(pack_root)):
        raise ValueError(f"invalid {label}: {value}")
    return path


def _verify_pack(root: Path, pack_path: Path, bundled: bool) -> dict[str, Any]:
    pack_path = pack_path.expanduser().resolve()
    if (pack_path.is_symlink() or not pack_path.is_file()
            or (bundled and not pack_path.is_relative_to((root / "soc").resolve()))):
        raise ValueError("pack is not a regular SoC pack")
    pack_root = pack_path.parent.resolve()
    pack = _json(pack_path)
    Draft202012Validator(_json(root / "contracts/soc_pack.schema.json")).validate(pack)
    if not bundled and not pack["hardware_materials"]:
        raise ValueError("external SoC workspaces require hardware materials")
    for material in pack["hardware_materials"]:
        path = _workspace_file(pack_root, material["stored_path"], "hardware material")
        if path.stat().st_size != material["bytes"] or _sha256(path) != material["sha256"]:
            raise ValueError(f"hardware material hash mismatch: {material['name']}")

    plan = _json(_workspace_file(pack_root, pack["adaptation_plan"], "adaptation plan"))
    Draft202012Validator(_json(root / "contracts/adaptation_plan.schema.json")).validate(plan)
    if plan["soc"] != pack["soc"] or plan["board"] != pack["board"] or set(plan["stable_components"]) != COMPONENTS:
        raise ValueError("adaptation plan identity or stable components differ")
    tasks = {task["provider"]: task for task in plan["tasks"]}
    if set(tasks) != set(PROVIDERS) or any(task["id"] != f"provider:{name}" for name, task in tasks.items()):
        raise ValueError("adaptation plan must contain one task per provider")
    if plan["base"] is not None:
        base_path = root / "soc" / plan["base"]["soc"] / "pack.json"
        if not base_path.is_file() or _sha256(base_path) != plan["base"]["pack_sha256"]:
            raise ValueError("base SoC pack identity mismatch")

    replacements = pack["providers"]
    if set(replacements) != set(PROVIDERS):
        raise ValueError("missing provider replacement contract")
    for name in PROVIDERS:
        provider = replacements[name]
        if (not provider.get("replacement_required")
                or provider.get("contract") != f"contracts/{name}_provider.schema.json"
                or not (root / provider["contract"]).is_file()):
            raise ValueError(f"missing provider replacement contract: {name}")
        _verify_provider(root, pack_path, name, provider)
        if (provider["implementation"] is None) != (tasks[name]["status"] in {"pending", "blocked"}):
            raise ValueError(f"provider implementation and task status disagree: {name}")
        if tasks[name]["status"] in {"candidate", "verified"}:
            for value in tasks[name]["required_outputs"]:
                _workspace_file(pack_root, value, f"{name} task output")
    for item in pack["sources"]:
        _validate_descriptor(item)
        if any(not _safe_relative(value) for value in item["selected_paths"]):
            raise ValueError(f"unsafe source path: {item['id']}")
    for value in [*pack["patches"], *pack["tests"]]:
        path = _workspace_file(pack_root, value, "pack path")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise ValueError(f"forbidden pack artifact: {value}")
    return pack


def verify_pack(pack_path: Path, sdk_root: Path = KIT) -> dict[str, Any]:
    try:
        pack = _verify_pack(sdk_root.expanduser().resolve(), pack_path, bundled=False)
        return {"ok": True, "status": "verified", "pack": str(pack_path.resolve()), "soc": pack["soc"], "errors": []}
    except Exception as exc:
        return {"ok": False, "status": "blocked", "pack": str(pack_path), "errors": [str(exc)]}


def verify(path: Path, resolved_source_contexts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    supplied = path.expanduser()
    if supplied.is_symlink():
        return {"ok": False, "status": "blocked", "root": str(supplied), "errors": ["unsafe SDK root symlink"]}
    root = supplied.resolve()
    errors: list[str] = []
    try:
        files = _safe_files(root)
        if _has_python_cache(root):
            raise ValueError("generated Python cache artifact")
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError("manifest.json is missing")
        manifest = _json(manifest_path)
        if set(manifest) != {"schema", "files"} or manifest.get("schema") != "sysuos.sdk-manifest.v1" or not isinstance(manifest.get("files"), dict):
            raise ValueError("manifest is invalid")
        expected = manifest.get("files", {})
        actual = _manifest(root)
        if expected != actual:
            raise ValueError("manifest content mismatch")
        sdk = _json(root / "sdk.json")
        Draft202012Validator(_json(SDK_SCHEMA)).validate(sdk)
        lock_path = root / sdk["source_context_lock"]
        lock = _json(lock_path)
        expected_lock = _context_lock(resolved_source_contexts if resolved_source_contexts is not None else _resolved_contexts())
        if (_sha256(lock_path) != sdk["source_context_lock_sha256"] or set(lock) != {"schema", "sources"}
                or lock != expected_lock):
            raise ValueError("source context lock is invalid")
        locked = {item["repository"]: _source_identity(item) for item in lock["sources"]}
        if (len(locked) != len(lock["sources"])
                or {_source_identity(item)["id"]: _source_identity(item) for item in sdk["source_layers"]} != locked):
            raise ValueError("source context identity mismatch")
        _verify_components(root, sdk, set(locked))
        for item in sdk["source_layers"]:
            _validate_descriptor(item)
            if any(not _safe_relative(value) for value in item["selected_paths"]):
                raise ValueError(f"unsafe source path: {item['id']}")
        for file in files:
            relative = file.relative_to(root)
            if _is_python_cache(relative):
                raise ValueError(f"generated Python cache artifact: {relative}")
            if file.suffix.lower() in FORBIDDEN_SUFFIXES:
                raise ValueError(f"forbidden binary ancestry: {relative}")
        for pack_path in sorted((root / "soc").glob("*/pack.json")):
            _verify_pack(root, pack_path, bundled=True)
    except Exception as exc:
        errors.append(str(exc))
    return {"ok": not errors, "status": "verified" if not errors else "blocked", "root": str(root), "errors": errors}


def export(out: Path, resolved_source_contexts: list[dict[str, Any]] | None = None, source_kit: Path = KIT) -> dict[str, Any]:
    contexts = resolved_source_contexts if resolved_source_contexts is not None else _resolved_contexts()
    out = out.expanduser().resolve()
    if out.exists():
        raise ValueError(f"SDK export destination already exists: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{out.name}-", dir=out.parent) as temporary:
        staging = Path(temporary) / "sysuos"
        shutil.copytree(source_kit, staging, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        lock_path = staging / "source-context.lock.json"
        lock_path.write_text(json.dumps(_context_lock(contexts), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        sdk = _json(staging / "sdk.json")
        sdk["source_context_lock_sha256"] = _sha256(lock_path)
        (staging / "sdk.json").write_text(json.dumps(sdk, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (staging / "manifest.json").write_text(json.dumps({"schema": "sysuos.sdk-manifest.v1", "files": _manifest(staging)}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = verify(staging, contexts)
        if not result["ok"]:
            raise ValueError("; ".join(result["errors"]))
        os.replace(staging, out)
    return {**verify(out, contexts), "exported": True}


def init_soc(
    soc: str,
    materials: Iterable[Path],
    out: Path,
    reference_image: Path | None = None,
    board: str | None = None,
    base_soc: str | None = None,
) -> dict[str, Any]:
    if not soc or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in soc):
        raise ValueError("SoC name must contain only letters, digits, '_' or '-'")
    board = board or soc
    if not board or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in board):
        raise ValueError("board name must contain only letters, digits, '_' or '-'")
    out = out.expanduser().resolve()
    if out == KIT.resolve() or out.is_relative_to(KIT.resolve()):
        raise ValueError("SoC workspaces must be outside the immutable SDK")
    if out.exists():
        raise ValueError(f"SoC pack destination already exists: {out}")
    inspected = inspect_materials(materials)
    hardware = [{key: item[key] for key in ("name", "kind", "stored_path", "sha256", "bytes")} for item in inspected]
    reference = None
    if reference_image:
        image = reference_image.expanduser().resolve()
        if not image.is_file() or image.is_symlink():
            raise ValueError("reference image is missing, not a file, or a symlink")
        reference = {"name": image.name, "sha256": _sha256(image), "bytes": image.stat().st_size, "observations": []}
    base = None
    base_pack = None
    if base_soc:
        base_path = KIT / "soc" / base_soc / "pack.json"
        if not base_path.is_file():
            raise ValueError(f"base SoC pack is unavailable: {base_soc}")
        base_pack = _json(base_path)
        base = {"soc": base_soc, "pack_sha256": _sha256(base_path)}
    pack = {
        "schema": "sysuos.soc-pack.v1", "soc": soc, "board": board, "hardware_materials": hardware,
        "reference_image": reference, "adaptation_plan": "adaptation.json",
        "providers": {name: {"contract": f"contracts/{name}_provider.schema.json", "replacement_required": True, "implementation": None} for name in PROVIDERS},
        "sources": [], "patches": [], "tests": [], "blockers": [f"implement {name} provider" for name in PROVIDERS],
    }
    plan = {
        "schema": "sysuos.adaptation-plan.v1", "soc": soc, "board": board, "base": base,
        "stable_components": sorted(COMPONENTS),
        "tasks": [
            {
                "id": f"provider:{name}", "provider": name,
                "action": "assess" if base_pack and base_pack["providers"][name]["implementation"] else "replace",
                "status": "pending",
                "base_implementation": base_pack["providers"][name]["implementation"] if base_pack else None,
                "owned_paths": [f"providers/{name}", f"tests/{name}"],
                "required_outputs": [f"providers/{name}/provider.json", f"tests/{name}/smoke.py"],
            }
            for name in PROVIDERS
        ],
    }
    Draft202012Validator(_json(PACK_SCHEMA)).validate(pack)
    Draft202012Validator(_json(ADAPTATION_SCHEMA)).validate(plan)
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.soc-", dir=out.parent))
    try:
        (staging / "materials").mkdir()
        for source_item, item in zip(inspected, hardware):
            destination = staging / item["stored_path"]
            shutil.copyfile(Path(source_item["source_path"]), destination)
            if destination.stat().st_size != item["bytes"] or _sha256(destination) != item["sha256"]:
                raise RuntimeError(f"material copy verification failed: {source_item['source_path']}")
        (staging / "pack.json").write_text(json.dumps(pack, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (staging / "adaptation.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _verify_pack(KIT.resolve(), staging / "pack.json", bundled=False)
        os.replace(staging, out)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"ok": True, "status": "initialized", "pack": str(out / "pack.json"), "errors": []}


def selftest() -> None:
    contexts = _resolved_contexts()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        fixture = root / "fixture"
        checkout = fixture / "third_party/context"
        checkout.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
        (checkout / "src").mkdir()
        (checkout / "src/locked.txt").write_text("locked\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=checkout, check=True)
        subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "locked"], cwd=checkout, check=True)
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
        context = {"repository": "context", "revision": revision, "selected_paths": ["src/locked.txt"],
                   "content_hash": _tree_content_hash(checkout, revision, ["src/locked.txt"]), "source_usage": "build_tool",
                   "license": "MIT", "redistribution": "allowed_with_license"}
        (fixture / "third_party.manifest.json").write_text(json.dumps({"default": [{"name": "context", "mode": "pinned_sparse", "revision": revision, "paths": ["src"], "source_usage": "build_tool", "license": "MIT", "redistribution": "allowed_with_license"}]}), encoding="utf-8")
        (fixture / "third_party.lock.json").write_text(json.dumps({"dependencies": {"context": {"kind": "git", "revision": revision}}}), encoding="utf-8")
        fixture_kit = fixture / "sdk/sysuos"
        fixture_kit.mkdir(parents=True)
        (fixture_kit / "source-context.lock.json").write_text(json.dumps(_context_lock([context])), encoding="utf-8")
        task_context = fixture / ".agent-context/context"
        task_context.mkdir(parents=True)
        (task_context / ".source-context.json").write_text(json.dumps(context), encoding="utf-8")
        if _resolved_contexts(fixture / "missing", fixture, fixture_kit) != _resolved_contexts(fixture / ".agent-context", fixture, fixture_kit):
            raise RuntimeError("normal-checkout source contexts differ from task-local contexts")
        escaped = {**context, "repository": "../outside-repo"}
        (fixture / "third_party.manifest.json").write_text(json.dumps({"default": [{"name": "../outside-repo", "mode": "pinned_sparse", "revision": revision, "paths": ["src"], "source_usage": "build_tool", "license": "MIT", "redistribution": "allowed_with_license"}]}), encoding="utf-8")
        (fixture / "third_party.lock.json").write_text(json.dumps({"dependencies": {"../outside-repo": {"kind": "git", "revision": revision}}}), encoding="utf-8")
        (fixture_kit / "source-context.lock.json").write_text(json.dumps(_context_lock([escaped])), encoding="utf-8")
        try:
            _locked_contexts(fixture, fixture_kit)
        except ValueError:
            pass
        else:
            raise RuntimeError("traversing source context repository was accepted")
        (fixture / "third_party.manifest.json").write_text(json.dumps({"default": [{"name": "context", "mode": "pinned_sparse", "revision": revision, "paths": ["src"], "source_usage": "build_tool", "license": "MIT", "redistribution": "allowed_with_license"}]}), encoding="utf-8")
        (fixture / "third_party.lock.json").write_text(json.dumps({"dependencies": {"context": {"kind": "git", "revision": revision}}}), encoding="utf-8")
        (fixture_kit / "source-context.lock.json").write_text(json.dumps(_context_lock([context])), encoding="utf-8")
        git_metadata = checkout / ".git"
        hidden_git_metadata = checkout / ".git-hidden"
        git_metadata.rename(hidden_git_metadata)
        try:
            _locked_contexts(fixture, fixture_kit)
        except ValueError:
            pass
        else:
            raise RuntimeError("non-checkout source context was accepted")
        finally:
            hidden_git_metadata.rename(git_metadata)

        exported = root / "sdk"
        if not export(exported, contexts)["ok"] or not verify(exported, contexts)["ok"]:
            raise RuntimeError("SDK export verification failed")
        material = root / "soc.pdf"
        image = root / "reference.img"
        material.write_bytes(b"hardware")
        image.write_bytes(b"reference identity only")
        pack = root / "new-soc"
        if not init_soc("new_soc", [material], pack, image, "new_board", "k230")["ok"]:
            raise RuntimeError("SoC initialization failed")
        data = _json(pack / "pack.json")
        plan = _json(pack / data["adaptation_plan"])
        stored_material = pack / data["hardware_materials"][0]["stored_path"]
        if (data["reference_image"]["sha256"] != _sha256(image) or (pack / image.name).exists()
                or not stored_material.is_file() or plan["base"]["soc"] != "k230"
                or not verify_pack(pack / "pack.json")["ok"]):
            raise RuntimeError("reference image identity handling failed")
        portable_pack = root / "portable-soc"
        created = subprocess.run(
            [sys.executable, str(exported / "tools/create_soc.py"), "portable_soc", str(portable_pack),
             "--board", "portable_board", "--from-soc", "k230", "--material", str(material)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        checked = subprocess.run(
            [sys.executable, str(exported / "tools/verify.py"), str(exported), str(portable_pack / "pack.json")],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        build_check = subprocess.run(
            [sys.executable, str(exported / "tools/build.py"), str(portable_pack / "pack.json")],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if (created.returncode or checked.returncode or build_check.returncode == 0
                or "pending providers" not in (build_check.stdout + build_check.stderr)):
            raise RuntimeError("portable SoC workspace workflow failed")
        portable_data = _json(portable_pack / "pack.json")
        (portable_pack / portable_data["hardware_materials"][0]["stored_path"]).write_bytes(b"tampered")
        tamper_check = subprocess.run(
            [sys.executable, str(exported / "tools/verify.py"), str(exported), str(portable_pack / "pack.json")],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if tamper_check.returncode == 0 or "hardware material hash mismatch" not in (tamper_check.stdout + tamper_check.stderr):
            raise RuntimeError("SoC material tampering was accepted")
        (exported / "sdk.json").write_text("{}\n", encoding="utf-8")
        if verify(exported)["ok"]:
            raise RuntimeError("manifest tampering was accepted")

        def fresh(name: str) -> Path:
            candidate = root / name
            export(candidate, contexts)
            return candidate

        tampered = fresh("tampered-project-source")
        source_file = tampered / "core/rt_ai/source/include/rt_ai.h"
        source_file.write_bytes(source_file.read_bytes() + b"\n")
        (tampered / "manifest.json").write_text(json.dumps({"schema": "sysuos.sdk-manifest.v1", "files": _manifest(tampered)}) + "\n", encoding="utf-8")
        if verify(tampered, contexts)["ok"]:
            raise RuntimeError("project source tampering was accepted")

        temporary_revision = fresh("temporary-project-revision")
        component_path = temporary_revision / "core/rt_ai/component.json"
        component_data = _json(component_path)
        component_data["source"]["project_source"]["revision"] = "482d61da92eceee202b2706e8c15f79c70fd3c95"
        component_path.write_text(json.dumps(component_data) + "\n", encoding="utf-8")
        (temporary_revision / "manifest.json").write_text(json.dumps({"schema": "sysuos.sdk-manifest.v1", "files": _manifest(temporary_revision)}) + "\n", encoding="utf-8")
        if verify(temporary_revision, contexts)["ok"]:
            raise RuntimeError("non-origin project source revision was accepted")

        changed = fresh("changed-source")
        sdk_data = _json(changed / "sdk.json")
        sdk_data["source_layers"][0]["revision"] = "0" * 40
        (changed / "sdk.json").write_text(json.dumps(sdk_data) + "\n", encoding="utf-8")
        lock_data = _json(changed / "source-context.lock.json")
        lock_data["sources"][0]["revision"] = "0" * 40
        (changed / "source-context.lock.json").write_text(json.dumps(lock_data) + "\n", encoding="utf-8")
        sdk_data["source_context_lock_sha256"] = _sha256(changed / "source-context.lock.json")
        (changed / "sdk.json").write_text(json.dumps(sdk_data) + "\n", encoding="utf-8")
        (changed / "manifest.json").write_text(json.dumps({"schema": "sysuos.sdk-manifest.v1", "files": _manifest(changed)}) + "\n", encoding="utf-8")
        if verify(changed, contexts)["ok"]:
            raise RuntimeError("coordinated source identity mismatch was accepted")

        malformed = fresh("malformed-provider")
        pack_path = malformed / "soc/k230/pack.json"
        pack_data = _json(pack_path)
        pack_data["providers"]["boot"]["implementation"] = "boot.json"
        pack_path.write_text(json.dumps(pack_data) + "\n", encoding="utf-8")
        (pack_path.parent / "boot.json").write_text("{}\n", encoding="utf-8")
        (malformed / "manifest.json").write_text(json.dumps({"schema": "sysuos.sdk-manifest.v1", "files": _manifest(malformed)}) + "\n", encoding="utf-8")
        if verify(malformed)["ok"]:
            raise RuntimeError("malformed provider descriptor was accepted")

        binary = fresh("forbidden-binary")
        (binary / "payload.bin").write_bytes(b"binary")
        (binary / "manifest.json").write_text(json.dumps({"schema": "sysuos.sdk-manifest.v1", "files": _manifest(binary)}) + "\n", encoding="utf-8")
        if verify(binary)["ok"]:
            raise RuntimeError("forbidden binary was accepted")

        cached_kit = root / "cached-kit"
        shutil.copytree(KIT, cached_kit)
        cache_dir = cached_kit / "core/compiler_runtime/source/__pycache__"
        cache_file = cache_dir / "socimage-selftest.pyc"
        cache_dir.mkdir(exist_ok=True)
        cache_file.write_bytes(b"realistic generated cache")
        first, second = root / "deterministic-a", root / "deterministic-b"
        export(first, contexts, cached_kit)
        export(second, contexts, cached_kit)
        first_files = _json(first / "manifest.json")["files"]
        if first_files != _json(second / "manifest.json")["files"] or any(_is_python_cache(Path(path)) for path in first_files):
            raise RuntimeError("SDK export is not deterministic and cache-free")
        injected = first / "core/compiler_runtime/source/__pycache__/runtime.cpython-313.pyc"
        injected.parent.mkdir()
        injected.write_bytes(b"injected cache")
        (first / "manifest.json").write_text(json.dumps({"schema": "sysuos.sdk-manifest.v1", "files": _manifest(first)}) + "\n", encoding="utf-8")
        if verify(first, contexts)["ok"]:
            raise RuntimeError("generated Python cache was accepted")

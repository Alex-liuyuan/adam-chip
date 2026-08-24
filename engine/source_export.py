"""Clean exports from promoted, revision-locked source inputs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from engine.source_discovery_tools import LOCK_SCHEMA, _promoted_sources, _resolve_build_source, _safe_source_path, _tree_content_hash
from socimage.facts import sha256


def _archive_environment(checkout: Path, revision: str, paths: list[str], object_directory: Path) -> dict[str, str]:
    object_directory.mkdir()
    git_objects = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-path", "objects"],
        cwd=checkout, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    ).stdout.strip()
    environment = {
        **os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_OBJECT_DIRECTORY": str(object_directory),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": git_objects,
    }
    tree = subprocess.run(
        ["git", "ls-tree", "-r", "-z", revision, "--", *paths],
        cwd=checkout, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    ).stdout
    records = []
    for raw in tree.split(b"\0"):
        if not raw:
            continue
        metadata, name = raw.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split()
        if kind == "blob":
            records.append((mode, object_id, os.fsdecode(name)))
    missing = {
        line.split(maxsplit=1)[0][1:]
        for line in subprocess.run(
            ["git", "rev-list", "--objects", "--missing=print", revision],
            cwd=checkout, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        ).stdout.splitlines()
        if line.startswith("?")
    }
    for mode, object_id, name in records:
        if object_id not in missing:
            continue
        path = checkout / name
        if not path.parent.resolve().is_relative_to(checkout.resolve()):
            raise RuntimeError(f"locked source blob is unavailable: {name}")
        if mode == "120000":
            if not path.is_symlink():
                raise RuntimeError(f"locked source symlink is unavailable or dirty: {name}")
            content = os.readlink(path).encode()
        else:
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(checkout.resolve()):
                raise RuntimeError(f"locked source blob is unavailable or dirty: {name}")
            content = path.read_bytes()
        actual = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        if actual != object_id:
            raise RuntimeError(f"locked source blob is unavailable or dirty: {name}")
        written = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"], cwd=checkout, env=environment,
            input=content, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        ).stdout.decode().strip()
        if written != object_id:
            raise RuntimeError(f"locked source blob hash mismatch: {name}")
    return environment


def _archive(repository: dict[str, Any], checkout: Path, destination: Path) -> None:
    paths = repository["selected_paths"]
    if _tree_content_hash(checkout, repository["revision"], paths) != repository["content_hash"]:
        raise RuntimeError(f"locked source content hash mismatch: {repository['id']}")
    with tempfile.TemporaryDirectory(prefix="soc-image-git-objects-") as temporary:
        temporary_path = Path(temporary)
        environment = _archive_environment(checkout, repository["revision"], paths, temporary_path / "objects")
        archive_path = temporary_path / "source.tar"
        with archive_path.open("wb") as stream:
            proc = subprocess.run(
                ["git", "archive", "--format=tar", repository["revision"], *paths],
                cwd=checkout, env=environment, stdout=stream, stderr=subprocess.PIPE, check=False,
            )
        if proc.returncode:
            raise RuntimeError(f"locked source export failed: {repository['id']}: {proc.stderr.decode(errors='ignore').strip()}")
        destination.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, mode="r:") as archive:
            archive.extractall(destination, filter="data")


def _atomic_export(destination: Path, exporter: Any) -> Any:
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise RuntimeError(f"source export destination already exists: {destination}")
    with tempfile.TemporaryDirectory(prefix=f".{destination.name}-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "export"
        staging.mkdir()
        result = exporter(staging)
        os.replace(staging, destination)
        return result


def _export_build_repository(source: dict[str, Any], destination: Path) -> dict[str, Any]:
    def export(staging: Path) -> dict[str, Any]:
        _archive(source, Path(source["path"]), staging)
        return {
            "id": source["id"], "revision": source["revision"],
            "content_hash": source["content_hash"], "selected_paths": source["selected_paths"],
            "source_lock_sha256": source["source_lock_sha256"],
        }

    return _atomic_export(destination, export)


def export_locked_build_source(context: Any, repository_id: str, destination: Path) -> dict[str, Any]:
    """Export one repository only after resolving it from the promoted build section."""
    lock_path, _, lock = _promoted_sources(context)
    if len([item for item in lock["build"] if item["id"] == repository_id]) != 1:
        raise RuntimeError(f"build source is absent from promoted source lock: {repository_id}")
    source = _resolve_build_source(context, lock_path, lock, repository_id, f"build:{repository_id}")
    return _export_build_repository(source, destination)


def export_project_source_context(chip: Path, request: dict[str, Any], destination: Path) -> dict[str, Any]:
    """Export a task context from the project manifest and lock at its pinned revision."""
    manifest = json.loads((chip / "third_party.manifest.json").read_text(encoding="utf-8"))
    lock = json.loads((chip / "third_party.lock.json").read_text(encoding="utf-8"))
    repository_id = request["repository"]
    entries = [item for group in manifest.values() for item in group if item.get("name") == repository_id]
    dependency = lock.get("dependencies", {}).get(repository_id)
    if len(entries) != 1 or entries[0].get("mode") != "pinned_sparse":
        raise RuntimeError(f"source context requires one pinned_sparse manifest entry: {repository_id}")
    entry = entries[0]
    revision = entry.get("revision")
    if not isinstance(dependency, dict) or dependency.get("kind") != "git" or dependency.get("revision") != revision or not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError(f"source context revision is not identically locked: {repository_id}")
    sparse_paths = entry.get("paths", [])
    selected_paths = request["paths"]
    if not all(_safe_source_path(path) and any(path == sparse or path.startswith(sparse.rstrip("/") + "/") for sparse in sparse_paths) for path in selected_paths):
        raise RuntimeError(f"source context path is outside the locked sparse paths: {repository_id}")
    checkout = chip / "third_party" / repository_id
    if not checkout.is_dir() or not (checkout / ".git").exists():
        raise RuntimeError(f"source context Git checkout is unavailable: {repository_id}")
    content_hash = _tree_content_hash(checkout, revision, selected_paths)
    result = {
        "repository": repository_id, "revision": revision, "selected_paths": selected_paths,
        "content_hash": content_hash, "license": entry.get("license", "NOASSERTION"),
        "redistribution": entry.get("redistribution", "not_declared"),
        "source_usage": entry.get("source_usage", "reference_only"),
    }

    def export(staging: Path) -> dict[str, Any]:
        _archive({"id": repository_id, "revision": revision, "selected_paths": selected_paths, "content_hash": content_hash}, checkout, staging)
        (staging / ".source-context.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result

    return _atomic_export(destination, export)


def _export_internal_stack(lock: dict[str, Any], stack_id: str, policy_root: Path, destination: Path) -> dict[str, Any]:
    Draft202012Validator(json.loads(LOCK_SCHEMA.read_text(encoding="utf-8"))).validate(lock)
    stacks = [item for item in lock["reference_stacks"] if item["id"] == stack_id]
    if len(stacks) != 1 or stacks[0]["decision"] != "internal_evaluation":
        raise RuntimeError(f"internal-evaluation source stack is unavailable: {stack_id}")
    stack = stacks[0]
    repository_ids = [item["repository_id"] for item in stack["repositories"]]
    repositories = {item["id"]: item for item in lock["internal_evaluation"] if item["id"] in repository_ids}
    if len(repository_ids) != len(set(repository_ids)) or set(repositories) != set(repository_ids):
        raise RuntimeError(f"internal-evaluation stack closure is incomplete: {stack_id}")
    policy_root = policy_root.resolve()
    workspace = (policy_root / stack["workspace"]).resolve()
    if not workspace.is_relative_to(policy_root):
        raise RuntimeError(f"internal-evaluation stack workspace escapes policy root: {stack_id}")

    ordered = sorted(stack["repositories"], key=lambda item: (item["path"] != ".", len(Path(item["path"]).parts), item["path"]))

    def export(staging: Path) -> dict[str, Any]:
        exported = []
        for item in ordered:
            path = item["path"]
            if path != "." and not _safe_source_path(path):
                raise RuntimeError(f"internal-evaluation stack path is unsafe: {stack_id}:{path}")
            checkout = workspace if path == "." else (workspace / path).resolve()
            target = staging if path == "." else staging / path
            if not checkout.is_relative_to(workspace) or not checkout.is_dir():
                raise RuntimeError(f"internal-evaluation checkout is unavailable: {stack_id}:{path}")
            if target.is_symlink() or not target.resolve().is_relative_to(staging.resolve()):
                raise RuntimeError(f"internal-evaluation export path escapes destination: {stack_id}:{path}")
            repository = repositories[item["repository_id"]]
            _archive(repository, checkout, target)
            exported.append({"repository_id": repository["id"], "path": path, "revision": repository["revision"], "content_hash": repository["content_hash"]})
        return {"id": stack_id, "decision": stack["decision"], "manifest_sha256": stack["manifest_sha256"], "repositories": exported}

    return _atomic_export(destination, export)


def export_internal_evaluation_stack(context: Any, stack_id: str, destination: Path) -> dict[str, Any]:
    """Export one verified internal-evaluation stack without admitting it to build ancestry."""
    lock_path, _, lock = _promoted_sources(context)
    result = _export_internal_stack(lock, stack_id, Path(getattr(context, "policy_root", LOCK_SCHEMA.parents[1])), destination)
    return {**result, "source_lock_sha256": sha256(lock_path)}


def selftest() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        child = workspace / "vendor/child"
        child.mkdir(parents=True)
        for checkout, files in (
            (workspace, {"README.md": "locked root\n", "LICENSE": "MIT\n"}),
            (child, {"child.c": "locked child\n"}),
        ):
            for name, content in files.items():
                path = checkout / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
            subprocess.run(["git", "add", "."], cwd=checkout, check=True)
            subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "locked"], cwd=checkout, check=True)
        root_revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=workspace, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
        child_revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=child, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
        root_repository = {"id": "stack/root", "revision": root_revision, "content_hash": _tree_content_hash(workspace, root_revision, ["."]), "selected_paths": ["."]}
        child_repository = {"id": "stack/child", "revision": child_revision, "content_hash": _tree_content_hash(child, child_revision, ["."]), "selected_paths": ["."]}
        (workspace / "README.md").write_text("dirty root\n", encoding="utf-8")
        (workspace / "untracked.txt").write_text("dirty\n", encoding="utf-8")
        (child / "child.c").write_text("dirty child\n", encoding="utf-8")
        license_object = subprocess.run(["git", "rev-parse", f"{root_revision}:LICENSE"], cwd=workspace, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
        (workspace / ".git/objects" / license_object[:2] / license_object[2:]).unlink()

        build = root / "build-export"
        _export_build_repository({**root_repository, "path": workspace, "source_lock_sha256": "1" * 64}, build)
        assert (build / "README.md").read_text(encoding="utf-8") == "locked root\n" and not (build / "untracked.txt").exists()

        chip = root / "chip"
        context_checkout = chip / "third_party/context"
        context_checkout.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=context_checkout, check=True)
        (context_checkout / "src").mkdir()
        (context_checkout / "src/locked.txt").write_text("locked context\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=context_checkout, check=True)
        subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "locked"], cwd=context_checkout, check=True)
        context_revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=context_checkout, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
        (chip / "third_party.manifest.json").write_text(json.dumps({"default": [{"name": "context", "mode": "pinned_sparse", "revision": context_revision, "paths": ["src"], "license": "MIT", "redistribution": "allowed_with_license", "source_usage": "build_tool"}]}), encoding="utf-8")
        (chip / "third_party.lock.json").write_text(json.dumps({"dependencies": {"context": {"kind": "git", "revision": context_revision}}}), encoding="utf-8")
        (context_checkout / "src/locked.txt").write_text("dirty context\n", encoding="utf-8")
        (context_checkout / "src/untracked.txt").write_text("untracked\n", encoding="utf-8")
        context_result = export_project_source_context(chip, {"repository": "context", "paths": ["src"]}, root / "context-export")
        assert context_result["revision"] == context_revision
        assert (root / "context-export/src/locked.txt").read_text(encoding="utf-8") == "locked context\n"
        assert not (root / "context-export/src/untracked.txt").exists()

        def locked(repository: dict[str, Any]) -> dict[str, Any]:
            return {**repository, "url": "https://example.invalid/repo", "license": "NOASSERTION", "license_evidence": [], "license_evidence_status": "not_found", "covered_requirements": ["reference_stack:stack"]}

        lock = {
            "schema": "soc-image.source-lock.v3", "hardware_ir_sha256": "1" * 64,
            "reference_profile_sha256": "2" * 64, "software_requirements_sha256": "3" * 64,
            "source_policy_sha256": "4" * 64, "source_candidates_sha256": "5" * 64,
            "reuse_plan_sha256": "6" * 64, "build": [], "build_tools": [], "verification_tools": [],
            "internal_evaluation": [locked(root_repository), locked(child_repository)], "reference_only": [],
            "reference_stacks": [{
                "id": "stack", "decision": "internal_evaluation", "workspace": "workspace",
                "manifest_path": "manifest.xml", "manifest_sha256": "7" * 64,
                "root_repository_id": "stack/root", "repositories": [
                    {"repository_id": "stack/root", "path": "."},
                    {"repository_id": "stack/child", "path": "vendor/child"},
                ],
            }],
            "dependency_edges": [{
                "parent_id": "stack/root", "child_id": "stack/child", "kind": "repo_manifest",
                "path": "vendor/child", "declaration_path": "manifest.xml",
                "declaration_sha256": "7" * 64, "revision": child_revision,
            }],
        }
        exported = root / "stack-export"
        result = _export_internal_stack(lock, "stack", root, exported)
        assert len(result["repositories"]) == 2
        assert (exported / "README.md").read_text(encoding="utf-8") == "locked root\n"
        assert (exported / "vendor/child/child.c").read_text(encoding="utf-8") == "locked child\n"
        assert not (exported / "untracked.txt").exists()
        lock["reference_stacks"][0]["decision"] = "reference_only"
        try:
            _export_internal_stack(lock, "stack", root, root / "rejected")
            raise AssertionError("reference-only stack entered internal-evaluation export")
        except RuntimeError as exc:
            assert "unavailable" in str(exc)


if __name__ == "__main__":
    selftest()

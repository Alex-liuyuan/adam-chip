"""Connect a material-only run to its reusable SYSUOS provider workspace."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from socimage import sdk
from socimage.facts import sha256
from socimage.intake import load_run


PROVIDER_CAPABILITIES = {
    "boot": ("boot_bsp",),
    "device": ("contract_drivers", "simulation_models"),
    "media": ("contract_drivers", "simulation_models", "product_layer"),
    "accelerator": ("rt_ai_os", "rt_ai_runtime", "tvm_ai_compiler", "cecap_airtos_integration"),
    "image": ("product_layer", "source_image", "hil_harness_verification"),
}
PROVIDER_AGENTS = {
    "boot": ("BootBspAgent",),
    "device": ("DriverAgent", "SimulationAgent"),
    "media": ("DriverAgent", "ProductAgent"),
    "accelerator": ("RtAiOsAgent", "RuntimeAgent", "CompilerAgent", "CecapAirtosAgent"),
    "image": ("ProductAgent", "ImageAgent", "VerificationAgent"),
}
ABI = {
    "boot": "sysuos.boot.v1",
    "device": "sysuos.device.v1",
    "media": "sysuos.media.v1",
    "accelerator": "sysuos.accelerator.v1",
    "image": "sysuos.image.v1",
}
PORTABLE_SUFFIXES = {".c", ".h", ".s", ".lds", ".json", ".py", ".txt", ".config", ".repl", ".md", ".log"}
PORTABLE_NAMES = {"Makefile", "Kconfig", "SConstruct", "SConscript"}
MEDIA_CLASSES = {"audio", "camera", "display"}


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def _git(repository: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", *arguments], cwd=repository, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    if process.returncode:
        raise RuntimeError(f"workspace git {' '.join(arguments)} failed: {process.stdout.strip()}")
    return process.stdout.strip()


def _identifier(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return cleaned or fallback


def _material_identity(run: Path) -> str:
    lock = _json(run / "materials.lock.json")
    values = sorted((item["sha256"], item["bytes"], item["kind"]) for item in lock["materials"])
    digest = hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
    return f"ws-{digest}"


def _labels(run: Path) -> tuple[str, str, str | None]:
    requirements = _json(run / "software_requirements.json")
    identities = requirements.get("board_identity", [])
    soc_value = next((item["value"] for item in identities if item["kind"] == "soc"), "")
    board_value = next((item["value"] for item in identities if item["kind"] == "board"), "")
    fallback = _material_identity(run)[3:19]
    soc = _identifier(soc_value, f"soc-{fallback}")
    board = _identifier(board_value, f"board-{fallback}")
    base = soc if (sdk.KIT / "soc" / soc / "pack.json").is_file() else None
    return soc, board, base


def _binding(run: Path) -> dict[str, Any]:
    files = ("materials.lock.json", "hardware_ir.json", "reference_profile.json", "software_requirements.json")
    return {
        "schema": "sysuos.run-workspace-binding.v1",
        "workspace_id": _material_identity(run),
        "inputs": {name: sha256(run / name) for name in files},
    }


def _workspace_paths(run: Path) -> tuple[Path, Path]:
    repository = run / "adaptation-repository"
    return repository, repository / "chip"


def ensure_workspace(run: Path) -> dict[str, Any]:
    run = run.expanduser().resolve()
    intake = load_run(run)
    if not intake["ok"]:
        return {"ok": False, "status": "blocked", "errors": intake["errors"]}
    repository, workspace = _workspace_paths(run)
    binding = _binding(run)
    if workspace.exists():
        return inspect_workspace(run)

    soc, board, base = _labels(run)
    lock = _json(run / "materials.lock.json")
    materials = [run / item["stored_path"] for item in lock["materials"]]
    repository.parent.mkdir(parents=True, exist_ok=True)
    result = sdk.init_soc(soc, materials, workspace, board=board, base_soc=base)
    if not result["ok"]:
        return result
    context = workspace / "context"
    context.mkdir()
    for name in binding["inputs"]:
        shutil.copyfile(run / name, context / name)
    _write_json(context / "binding.json", binding)
    _git(repository, "init", "-q")
    _git(repository, "add", "--", "chip")
    _git(
        repository,
        "-c", "user.name=SoC Image Factory",
        "-c", "user.email=soc-image@localhost",
        "commit", "-q", "-m", "workspace: bind hardware materials and adaptation plan",
    )
    inspected = inspect_workspace(run)
    inspected["created"] = True
    return inspected


def inspect_workspace(run: Path) -> dict[str, Any]:
    run = run.expanduser().resolve()
    repository, workspace = _workspace_paths(run)
    errors: list[str] = []
    pack_path = workspace / "pack.json"
    binding_path = workspace / "context/binding.json"
    if not (repository / ".git").is_dir() or not pack_path.is_file() or not binding_path.is_file():
        errors.append("run-local SYSUOS workspace is missing")
    else:
        checked = sdk.verify_pack(pack_path)
        errors.extend(checked["errors"])
        if _json(binding_path) != _binding(run):
            errors.append("SYSUOS workspace input binding differs from the run")
        if _git(repository, "status", "--porcelain"):
            errors.append("SYSUOS workspace has uncommitted changes")
    provider_status: dict[str, str] = {}
    if pack_path.is_file():
        try:
            plan = _json(workspace / _json(pack_path)["adaptation_plan"])
            provider_status = {task["provider"]: task["status"] for task in plan["tasks"]}
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            errors.append("SYSUOS adaptation plan is unreadable")
    return {
        "ok": not errors and provider_status and all(value == "verified" for value in provider_status.values()),
        "status": "verified" if not errors and provider_status and all(value == "verified" for value in provider_status.values()) else "blocked",
        "workspace": str(workspace),
        "pack": str(pack_path),
        "provider_status": provider_status,
        "errors": errors,
        "created": False,
    }


def _task_rows(run: Path) -> dict[str, dict[str, Any]]:
    connection = sqlite3.connect(run / "state.db")
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """SELECT t.id,t.capability,t.agent,t.status,t.input_hash,t.blocker,
                      a.id AS attempt_id,a.promotion_commit,a.verifier_errors
                 FROM tasks t
            LEFT JOIN attempts a ON a.id=(SELECT id FROM attempts WHERE task_id=t.id ORDER BY created_at DESC,id DESC LIMIT 1)"""
        )
        return {row["capability"]: dict(row) for row in rows}
    finally:
        connection.close()


def _portable(relative: str) -> bool:
    path = Path(relative)
    return path.name in PORTABLE_NAMES or path.suffix.lower() in PORTABLE_SUFFIXES


def _is_test(relative: str) -> bool:
    value = relative.lower()
    return any(token in value for token in ("verification", "test", "smoke", "oracle")) or value.endswith(".log")


def _domain_blocker(provider: str, workspace: Path, integration: Path) -> str | None:
    requirements = _json(workspace / "context/software_requirements.json")
    classes = {item["class"] for item in requirements.get("components", [])}
    if provider == "media" and classes & MEDIA_CLASSES:
        matrix_path = integration / "generated/product/capability_matrix.json"
        if not matrix_path.is_file():
            return "media hardware is present but ProductAgent produced no capability matrix"
        enabled = set(_json(matrix_path).get("enabled", []))
        missing = sorted((classes & MEDIA_CLASSES) - enabled)
        if missing:
            return "media capabilities remain unimplemented: " + ", ".join(missing)
    if provider == "accelerator" and "accelerator" in classes:
        blocker_path = integration / "generated/compiler/npu_blocker.json"
        if not blocker_path.is_file() or _json(blocker_path).get("status") != "enabled":
            return "accelerator hardware is present but its command ABI/backend remains blocked"
    return None


def _snapshot_provider(
    provider: str,
    workspace: Path,
    integration: Path,
    engine_plan: dict[str, Any],
    rows: dict[str, dict[str, Any]],
    hardware_ir_sha256: str,
) -> tuple[str, str, list[str]]:
    capabilities = PROVIDER_CAPABILITIES[provider]
    missing = [name for name in capabilities if name not in rows]
    if missing:
        return "blocked", "required Agent capabilities were not planned: " + ", ".join(missing), []
    incomplete = [f"{name}={rows[name]['status']}" for name in capabilities if rows[name]["status"] != "passed"]
    if incomplete:
        return "blocked", "Agent capabilities are incomplete: " + ", ".join(incomplete), []
    invalid = [
        name for name in capabilities
        if not rows[name].get("attempt_id") or not rows[name].get("promotion_commit")
        or json.loads(rows[name].get("verifier_errors") or "[]")
    ]
    if invalid:
        return "blocked", "Agent results lack independent verification/promotion binding: " + ", ".join(invalid), []
    domain = _domain_blocker(provider, workspace, integration)
    if domain:
        return "blocked", domain, []

    tasks = {task["capability"]: task for task in engine_plan["tasks"]}
    selected = [tasks[name] for name in capabilities]
    copied: list[str] = []
    tests: list[str] = []
    for task in selected:
        for output in task["provider"]["outputs"]:
            source = integration / output
            if not source.is_file() or source.is_symlink() or not _portable(output):
                continue
            relative = f"providers/{provider}/source/{output}"
            destination = workspace / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            copied.append(relative)
            if _is_test(output):
                tests.append(relative)
    if not copied or not tests:
        return "blocked", "verified Agent outputs do not contain portable source and tests", []

    provenance_path = workspace / f"providers/{provider}/provenance.json"
    provenance = {
        "schema": "sysuos.provider-provenance.v1",
        "provider": provider,
        "hardware_ir_sha256": hardware_ir_sha256,
        "agents": list(PROVIDER_AGENTS[provider]),
        "tasks": [
            {
                "id": tasks[name]["id"],
                "input_hash": rows[name]["input_hash"],
                "attempt_id": rows[name]["attempt_id"],
                "promotion_commit": rows[name]["promotion_commit"],
            }
            for name in capabilities
        ],
        "physical_hil_verified": False,
    }
    _write_json(provenance_path, provenance)
    provenance_relative = str(provenance_path.relative_to(workspace))
    copied.append(provenance_relative)
    descriptor_path = workspace / f"providers/{provider}/provider.json"
    descriptor = {
        "schema": f"sysuos.provider.{provider}.v1",
        "kind": provider,
        "abi": ABI[provider] + ".candidate",
        "sources": [{"path": value, "sha256": sha256(workspace / value)} for value in sorted(set(copied))],
        "tests": sorted(set(tests)),
    }
    _write_json(descriptor_path, descriptor)
    return "candidate", "physical target HIL is required before provider verification", descriptor["tests"]


def sync_workspace(run: Path, engine_result: dict[str, Any]) -> dict[str, Any]:
    run = run.expanduser().resolve()
    initial = ensure_workspace(run)
    if initial["errors"]:
        return initial
    repository, workspace = _workspace_paths(run)
    if _git(repository, "status", "--porcelain"):
        return {**initial, "ok": False, "status": "blocked", "errors": ["SYSUOS workspace is dirty before synchronization"]}
    engine_plan = _json(run / "plan.json")
    rows = _task_rows(run)
    pack_path = workspace / "pack.json"
    pack = _json(pack_path)
    plan_path = workspace / pack["adaptation_plan"]
    adaptation = _json(plan_path)
    hardware_hash = sha256(run / "hardware_ir.json")
    blockers: list[str] = []
    all_tests: list[str] = []
    tasks_by_provider = {task["provider"]: task for task in adaptation["tasks"]}
    for provider in sdk.PROVIDERS:
        status, reason, tests = _snapshot_provider(provider, workspace, run / "integration", engine_plan, rows, hardware_hash)
        task = tasks_by_provider[provider]
        task["status"] = status
        task["action"] = "adapt" if status == "candidate" else task["action"]
        implementation = f"providers/{provider}/provider.json" if status in {"candidate", "verified"} else None
        pack["providers"][provider]["implementation"] = implementation
        if implementation:
            task["required_outputs"] = [implementation, tests[0]]
            all_tests.extend(tests)
        if status != "verified":
            blockers.append(f"{provider}: {reason}")
    pack["tests"] = sorted(set(all_tests))
    pack["blockers"] = blockers
    _write_json(plan_path, adaptation)
    _write_json(pack_path, pack)
    verified = sdk.verify_pack(pack_path)
    if not verified["ok"]:
        return {**verified, "workspace": str(workspace), "provider_status": {name: tasks_by_provider[name]["status"] for name in sdk.PROVIDERS}}
    if _git(repository, "status", "--porcelain"):
        _git(repository, "add", "--", "chip")
        _git(
            repository,
            "-c", "user.name=SoC Image Factory",
            "-c", "user.email=soc-image@localhost",
            "commit", "-q", "-m", "agents: synchronize verified provider candidates",
        )
    result = inspect_workspace(run)
    result["engine_status"] = engine_result.get("status")
    return result


def merge_status(engine_result: dict[str, Any], workspace_result: dict[str, Any]) -> dict[str, Any]:
    result = dict(engine_result)
    result.update({
        "ok": bool(engine_result.get("ok")) and bool(workspace_result.get("ok")),
        "status": "product_image_ready" if engine_result.get("ok") and workspace_result.get("ok") else "blocked",
        "soc_workspace": workspace_result.get("workspace"),
        "soc_pack": workspace_result.get("pack"),
        "provider_status": workspace_result.get("provider_status", {}),
        "workspace_errors": workspace_result.get("errors", []),
    })
    return result


def selftest() -> None:
    from socimage.hardware import derive
    from socimage.intake import create_run

    with tempfile.TemporaryDirectory(prefix="adaptation-selftest-") as temporary:
        root = Path(temporary)
        material = root / "new-soc.txt"
        material.write_text("generic SoC hardware manual\n", encoding="utf-8")
        run = root / "run"
        create_run([material], run)
        derived = derive(run)
        if not derived["ok"]:
            raise RuntimeError(f"adaptation selftest Hardware IR failed: {derived}")
        created = ensure_workspace(run)
        assert created["created"] and created["workspace"]
        inspected = inspect_workspace(run)
        assert not inspected["ok"] and set(inspected["provider_status"].values()) == {"pending"}
        reused = ensure_workspace(run)
        assert reused["created"] is False
        binding = Path(inspected["workspace"]) / "context/binding.json"
        original = binding.read_bytes()
        binding.write_text("{}\n", encoding="utf-8")
        assert "SYSUOS workspace input binding differs from the run" in inspect_workspace(run)["errors"]
        binding.write_bytes(original)

        workspace = Path(inspected["workspace"])
        integration = run / "integration"
        _write_json(integration / "generated/platform/manifest.json", {"hardware_ir_sha256": sha256(run / "hardware_ir.json")})
        _write_json(integration / "generated/platform/build/verification.json", {"boot_contract_pass": True})
        engine_plan = {
            "tasks": [{
                "id": "task:boot_bsp",
                "capability": "boot_bsp",
                "provider": {"outputs": [
                    "generated/platform/manifest.json",
                    "generated/platform/build/verification.json",
                ]},
            }],
        }
        rows = {
            "boot_bsp": {
                "status": "passed",
                "input_hash": "1" * 64,
                "attempt_id": "2" * 32,
                "promotion_commit": "3" * 40,
                "verifier_errors": "[]",
            },
        }
        status, reason, tests = _snapshot_provider(
            "boot", workspace, integration, engine_plan, rows, sha256(run / "hardware_ir.json")
        )
        assert status == "candidate" and "physical target HIL" in reason and tests
        descriptor = _json(workspace / "providers/boot/provider.json")
        assert descriptor["kind"] == "boot" and descriptor["sources"] and descriptor["tests"]

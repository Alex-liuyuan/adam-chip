"""SQLite planning, isolated Agent attempts, verification, and promotion."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

from jsonschema import Draft202012Validator

from engine.engineering_agent import EngineeringRequest, run_engineering_agent
from engine.tools import TOOLS, ToolContext
from socimage.facts import sha256


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = Path(__file__).with_name("capabilities.json")
REGISTRY_SCHEMA = ROOT / "schemas/capability.schema.json"
TASK_SCHEMA = ROOT / "schemas/task.schema.json"
TOOL_RESULT_SCHEMA = ROOT / "schemas/tool_result.schema.json"
BASELINE_CAPABILITIES = ("hardware_contract_summary", "source_discovery")
DEFAULT_SOURCE_POLICY = ROOT / "config/source_policy.json"


def _json_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def _git(repo: Path, *args: str, input_text: str | None = None, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if check and proc.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stdout.strip()}")
    return proc.stdout


def _safe_relative(path: str) -> bool:
    value = PurePosixPath(path)
    return bool(path) and not value.is_absolute() and ".." not in value.parts and ".git" not in value.parts


def _within(path: str, prefixes: Iterable[str]) -> bool:
    return _safe_relative(path) and any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(REGISTRY_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(data)
    capabilities = {item["id"]: item for item in data["capabilities"]}
    if len(capabilities) != len(data["capabilities"]):
        raise ValueError("capability IDs must be unique")
    for item in capabilities.values():
        provider = item["provider"]
        if any(not _within(output, provider["owned_paths"]) for output in provider["outputs"]):
            raise ValueError(f"capability {item['id']} declares output outside provider ownership")
        artifact_outputs = [*provider.get("artifact_outputs", []), *provider.get("internal_artifact_outputs", [])]
        if len(artifact_outputs) != len(set(artifact_outputs)) or any(not _safe_relative(output) for output in artifact_outputs):
            raise ValueError(f"capability {item['id']} declares an unsafe external artifact")
    return capabilities


def plan(
    hardware_ir: dict[str, Any],
    profile: dict[str, Any],
    software_requirements: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    hardware_ir_sha256: str,
    reference_profile_sha256: str,
    software_requirements_sha256: str,
    source_policy_sha256: str,
    requested: Iterable[str] = BASELINE_CAPABILITIES,
) -> dict[str, Any]:
    if software_requirements.get("project_id") != hardware_ir.get("project_id"):
        raise ValueError("software requirements project does not match Hardware IR")
    if software_requirements.get("hardware_ir_sha256") != hardware_ir_sha256:
        raise ValueError("software requirements are not bound to Hardware IR")
    enabled = {item["id"] for item in profile.get("enabled_capabilities", [])}
    roots = set(requested)
    roots.update(
        item["id"]
        for item in registry.values()
        if item["activates_on"] and set(item["activates_on"]) <= enabled
    )
    material_text = " ".join(str(item.get("text", "")) for item in hardware_ir.get("observations", [])).lower()
    roots.update(
        item["id"]
        for item in registry.values()
        if item.get("material_selectors") and any(selector.lower() in material_text for selector in item["material_selectors"])
    )
    ordered: list[str] = []
    blockers: list[dict[str, str]] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(capability: str, owner: str) -> None:
        if capability in visited:
            return
        if capability in visiting:
            blockers.append({"capability": owner, "reason": f"dependency cycle at {capability}"})
            return
        item = registry.get(capability)
        if item is None:
            blockers.append({"capability": owner, "reason": f"missing capability: {capability}"})
            return
        visiting.add(capability)
        for dependency in item["depends_on"]:
            visit(dependency, capability)
        visiting.remove(capability)
        visited.add(capability)
        ordered.append(capability)

    for root in sorted(roots):
        visit(root, root)
    task_schema = json.loads(TASK_SCHEMA.read_text(encoding="utf-8"))
    tasks = []
    engine_root = Path(__file__).parent
    tool_inputs = [
        *sorted(engine_root.glob("*.py")),
        *sorted(
            path for path in engine_root.glob("*_templates/**/*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix.lower() not in {".o", ".elf", ".bin", ".pyc", ".pyo"}
        ),
        TOOL_RESULT_SCHEMA,
        ROOT / "schemas/engineering_agent_report.schema.json",
    ]
    toolset_hash = _json_hash({str(path.relative_to(ROOT)): sha256(path) for path in tool_inputs})
    for capability in ordered:
        item = registry[capability]
        task = {
            "id": f"task:{capability}",
            "capability": capability,
            "agent": item["provider"]["agent"],
            "depends_on": [f"task:{value}" for value in item["depends_on"]],
            "input_hash": _json_hash({"hardware_ir_sha256": hardware_ir_sha256, "reference_profile_sha256": reference_profile_sha256, "software_requirements_sha256": software_requirements_sha256, "source_policy_sha256": source_policy_sha256, "capability": item, "toolset_sha256": toolset_hash}),
            "hardware_ir_sha256": hardware_ir_sha256,
            "reference_profile_sha256": reference_profile_sha256,
            "software_requirements_sha256": software_requirements_sha256,
            "source_policy_sha256": source_policy_sha256,
            "toolset_sha256": toolset_hash,
            "provider": item["provider"],
        }
        Draft202012Validator(task_schema).validate(task)
        tasks.append(task)
    return {
        "schema": "soc-image.plan.v1",
        "project_id": hardware_ir["project_id"],
        "hardware_ir_sha256": hardware_ir_sha256,
        "reference_profile_sha256": reference_profile_sha256,
        "software_requirements_sha256": software_requirements_sha256,
        "source_policy_sha256": source_policy_sha256,
        "requested_capabilities": sorted(roots),
        "hardware_blockers": profile.get("blocked_capabilities", []),
        "blockers": blockers,
        "tasks": tasks,
    }


class State:
    def __init__(self, path: Path):
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, capability TEXT NOT NULL, agent TEXT NOT NULL,
                status TEXT NOT NULL, input_hash TEXT NOT NULL, contract TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, blocker TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS attempts (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL, status TEXT NOT NULL,
                candidate_path TEXT NOT NULL, patch_path TEXT, patch_sha256 TEXT,
                verifier_errors TEXT NOT NULL, failure_signature TEXT, promotion_commit TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                sha256 TEXT NOT NULL, path TEXT NOT NULL, bytes INTEGER NOT NULL,
                task_id TEXT NOT NULL, attempt_id TEXT NOT NULL, kind TEXT NOT NULL,
                PRIMARY KEY (sha256, path)
            );
            CREATE TABLE IF NOT EXISTS failures (
                signature TEXT PRIMARY KEY, task_id TEXT NOT NULL, reason TEXT NOT NULL,
                occurrences INTEGER NOT NULL DEFAULT 1, last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self.connection.commit()

    def reconcile(self, plan_data: dict[str, Any]) -> None:
        active = {task["id"] for task in plan_data["tasks"]}
        with self.connection:
            for task in plan_data["tasks"]:
                row = self.connection.execute("SELECT input_hash, status FROM tasks WHERE id=?", (task["id"],)).fetchone()
                status = row["status"] if row and row["input_hash"] == task["input_hash"] and row["status"] != "obsolete" else "pending"
                self.connection.execute(
                    """INSERT INTO tasks(id, capability, agent, status, input_hash, contract, attempts, blocker)
                       VALUES(?,?,?,?,?,?,0,NULL)
                       ON CONFLICT(id) DO UPDATE SET capability=excluded.capability, agent=excluded.agent,
                         status=excluded.status, input_hash=excluded.input_hash, contract=excluded.contract,
                         attempts=CASE WHEN tasks.input_hash=excluded.input_hash THEN tasks.attempts ELSE 0 END,
                         blocker=CASE WHEN tasks.input_hash=excluded.input_hash THEN tasks.blocker ELSE NULL END,
                         updated_at=CURRENT_TIMESTAMP""",
                    (task["id"], task["capability"], task["agent"], status, task["input_hash"], json.dumps(task, sort_keys=True)),
                )
            if active:
                placeholders = ",".join("?" for _ in active)
                self.connection.execute(f"UPDATE tasks SET status='obsolete' WHERE id NOT IN ({placeholders})", tuple(active))
            else:
                self.connection.execute("UPDATE tasks SET status='obsolete'")
            self.connection.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('plan_hash',?)", (_json_hash(plan_data),))

    def recover(self) -> int:
        with self.connection:
            rows = self.connection.execute("SELECT id FROM tasks WHERE status='running'").fetchall()
            self.connection.execute("UPDATE tasks SET status='pending', blocker='recovered interrupted attempt' WHERE status='running'")
            self.connection.execute("UPDATE attempts SET status='interrupted' WHERE status='running'")
        return len(rows)

    def retry_failed(self, max_attempts: int = 2) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE tasks SET status='pending', blocker=NULL WHERE status='failed' AND attempts<?",
                (max_attempts,),
            )

    def retry_blocked(self, max_attempts: int = 2) -> int:
        retryable = []
        for row in self.connection.execute("SELECT id,attempts,blocker FROM tasks WHERE status='blocked'"):
            try:
                blocker = json.loads(row["blocker"] or "{}")
            except json.JSONDecodeError:
                blocker = {}
            if blocker.get("retryable") is True and row["attempts"] < max_attempts:
                retryable.append(row["id"])
        with self.connection:
            self.connection.executemany(
                "UPDATE tasks SET status='pending', blocker=NULL WHERE id=?",
                ((task_id,) for task_id in retryable),
            )
        return len(retryable)

    def task_rows(self) -> list[sqlite3.Row]:
        return self.connection.execute("SELECT * FROM tasks WHERE status!='obsolete' ORDER BY id").fetchall()

    def ready(self) -> list[dict[str, Any]]:
        rows = self.task_rows()
        passed = {row["id"] for row in rows if row["status"] == "passed"}
        result = []
        for row in rows:
            task = json.loads(row["contract"])
            if row["status"] == "pending" and set(task["depends_on"]) <= passed:
                result.append(task)
        return result

    def start(self, task: dict[str, Any], attempt_id: str, candidate: Path) -> None:
        with self.connection:
            self.connection.execute("UPDATE tasks SET status='running', attempts=attempts+1, blocker=NULL WHERE id=?", (task["id"],))
            self.connection.execute(
                "INSERT INTO attempts(id,task_id,status,candidate_path,verifier_errors) VALUES(?,?,?,?,?)",
                (attempt_id, task["id"], "running", str(candidate), "[]"),
            )

    def finish(self, task: dict[str, Any], outcome: dict[str, Any]) -> None:
        status = outcome.get("status", "passed" if outcome["ok"] else "failed")
        blocker = outcome.get("blocker")
        reason = json.dumps(blocker, sort_keys=True) if status == "blocked" else "; ".join(outcome["errors"])
        signature = hashlib.sha256(f"{task['id']}\0{reason}".encode()).hexdigest() if status == "failed" else None
        with self.connection:
            self.connection.execute("UPDATE tasks SET status=?, blocker=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, reason or None, task["id"]))
            self.connection.execute(
                """UPDATE attempts SET status=?,patch_path=?,patch_sha256=?,verifier_errors=?,
                   failure_signature=?,promotion_commit=? WHERE id=?""",
                (status, outcome.get("patch_path"), outcome.get("patch_sha256"), json.dumps(outcome["errors"]), signature, outcome.get("promotion_commit"), outcome["attempt_id"]),
            )
            if signature:
                self.connection.execute(
                    """INSERT INTO failures(signature,task_id,reason) VALUES(?,?,?)
                       ON CONFLICT(signature) DO UPDATE SET occurrences=occurrences+1,last_seen=CURRENT_TIMESTAMP""",
                    (signature, task["id"], reason),
                )
            for artifact in outcome.get("artifacts", []):
                self.connection.execute(
                    "INSERT OR REPLACE INTO artifacts(sha256,path,bytes,task_id,attempt_id,kind) VALUES(?,?,?,?,?,?)",
                    (artifact["sha256"], artifact["path"], artifact["bytes"], task["id"], outcome["attempt_id"], artifact["kind"]),
                )

    def artifact_errors(self) -> list[str]:
        errors = []
        for row in self.connection.execute("SELECT sha256,path,bytes FROM artifacts ORDER BY path"):
            path = Path(row["path"])
            if not path.is_file() or path.stat().st_size != row["bytes"] or sha256(path) != row["sha256"]:
                errors.append(f"artifact integrity failure: {path}")
        return errors

    def metadata(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def close(self) -> None:
        self.connection.close()


class CandidateExecutor:
    def __init__(
        self,
        run: Path,
        integration: Path,
        hardware_ir: dict[str, Any],
        reference_profile: dict[str, Any],
        software_requirements: dict[str, Any],
        source_policy: dict[str, Any],
        tools: dict[str, Callable] | None = None,
        engineer_runner: Callable[[EngineeringRequest], dict[str, Any]] = run_engineering_agent,
    ):
        self.run = run
        self.integration = integration
        self.hardware_ir = hardware_ir
        self.reference_profile = reference_profile
        self.software_requirements = software_requirements
        self.source_policy = source_policy
        self.tools = tools or TOOLS
        self.engineer_runner = engineer_runner
        self.git_lock = threading.Lock()

    def _context(self, task: dict[str, Any], worktree: Path, artifact_dir: Path) -> ToolContext:
        return ToolContext(
            worktree=worktree,
            project_id=self.hardware_ir["project_id"],
            task_id=task["id"],
            hardware_ir_sha256=task["hardware_ir_sha256"],
            hardware_ir=self.hardware_ir,
            outputs=tuple(task["provider"]["outputs"]),
            reference_profile=self.reference_profile,
            reference_profile_sha256=task["reference_profile_sha256"],
            software_requirements=self.software_requirements,
            software_requirements_sha256=task["software_requirements_sha256"],
            source_policy=self.source_policy,
            source_policy_sha256=task["source_policy_sha256"],
            artifact_dir=artifact_dir,
        )

    def _validate_candidate(
        self,
        task: dict[str, Any],
        worktree: Path,
        artifact_dir: Path,
        verifier: Callable | None,
    ) -> tuple[list[str], list[str]]:
        provider = task["provider"]
        changed = self._changed(worktree)
        errors = [f"unauthorized path: {path}" for path in changed if not _within(path, provider["owned_paths"])]
        errors.extend(f"symbolic links are not allowed: {path}" for path in changed if (worktree / path).is_symlink())
        errors.extend(f"missing expected output: {path}" for path in provider["outputs"] if not (worktree / path).is_file())
        artifact_outputs = [*provider.get("artifact_outputs", []), *provider.get("internal_artifact_outputs", [])]
        errors.extend(f"missing expected artifact: {path}" for path in artifact_outputs if not (artifact_dir / path).is_file())
        errors.extend(f"symbolic artifact is not allowed: {path}" for path in artifact_outputs if (artifact_dir / path).is_symlink())
        if verifier is None:
            errors.append("provider verifier is not registered")
        elif not errors:
            errors.extend(verifier(self._context(task, worktree, artifact_dir)))
        return changed, errors

    @staticmethod
    def _engineering_blocker(task: dict[str, Any], result: dict[str, Any], scaffold: dict[str, Any]) -> dict[str, Any]:
        report = result.get("report") if isinstance(result.get("report"), dict) else {}
        reasons = [*result.get("errors", []), *report.get("blockers", [])]
        scaffold_blocker = scaffold.get("blocker") if isinstance(scaffold, dict) else None
        if isinstance(scaffold_blocker, dict) and scaffold_blocker.get("reason"):
            reasons.append(str(scaffold_blocker["reason"]))
        return {
            "code": str(scaffold_blocker.get("code")) if isinstance(scaffold_blocker, dict) and scaffold_blocker.get("code") else "engineering_agent_blocked",
            "reason": "; ".join(dict.fromkeys(reasons)) or "engineering Agent did not produce an implementation",
            "retryable": bool(scaffold_blocker.get("retryable", True)) if isinstance(scaffold_blocker, dict) else True,
            "owner": task["agent"],
        }

    def execute(self, task: dict[str, Any], attempt_id: str) -> dict[str, Any]:
        candidate = self.run / "candidates" / attempt_id
        worktree = candidate / "worktree"
        artifact_dir = candidate / "artifacts"
        candidate.mkdir(parents=True, exist_ok=False)
        artifact_dir.mkdir()
        with self.git_lock:
            _git(self.integration, "worktree", "add", "--detach", str(worktree), "HEAD")
        errors: list[str] = []
        patch = ""
        tool_result: dict[str, Any] = {}
        engineering_results: list[dict[str, Any]] = []
        try:
            provider = task["provider"]
            tool = self.tools.get(provider["tool"])
            verifier = self.tools.get(provider["verify_tool"])
            scaffold_errors: list[str] = []
            if tool is None:
                scaffold_errors.append("provider scaffold tool is not registered")
            else:
                try:
                    result = tool(self._context(task, worktree, artifact_dir))
                    if not isinstance(result, dict):
                        scaffold_errors.append("provider tool returned a non-object result")
                    else:
                        tool_result = result
                        result_schema = json.loads(TOOL_RESULT_SCHEMA.read_text(encoding="utf-8"))
                        validation_errors = sorted(Draft202012Validator(result_schema).iter_errors(result), key=lambda item: list(item.path))
                        scaffold_errors.extend(f"invalid tool result: {error.message}" for error in validation_errors)
                        if result.get("status") == "failed":
                            scaffold_errors.append("provider scaffold tool reported failure")
                    _write_json(candidate / "tool_result.json", result if isinstance(result, dict) else {"result": result})
                except Exception as exc:
                    scaffold_errors.append(f"provider scaffold tool failed: {exc}")
            scaffold = {**tool_result, "scaffold_errors": scaffold_errors}
            first = self.engineer_runner(EngineeringRequest(
                context=self._context(task, worktree, artifact_dir),
                task=task,
                scaffold=scaffold,
                failures=tuple(scaffold_errors),
                round_number=1,
                attempt_id=attempt_id,
                report_dir=candidate,
            ))
            engineering_results.append(first)
            _write_json(candidate / "engineering-result-1.json", first)
            if not first.get("ok"):
                patch_path = candidate / "change.patch"
                patch_path.write_text("", encoding="utf-8")
                return {
                    "ok": False,
                    "status": "blocked",
                    "attempt_id": attempt_id,
                    "candidate_path": str(candidate),
                    "patch_path": str(patch_path),
                    "patch_sha256": sha256(patch_path),
                    "errors": [],
                    "blocker": self._engineering_blocker(task, first, scaffold),
                    "artifacts": [],
                    "engineering": engineering_results,
                }

            changed, errors = self._validate_candidate(task, worktree, artifact_dir, verifier)
            boundary_failure = any(error.startswith(("unauthorized path:", "symbolic")) for error in errors)
            if errors and not boundary_failure:
                second = self.engineer_runner(EngineeringRequest(
                    context=self._context(task, worktree, artifact_dir),
                    task=task,
                    scaffold=scaffold,
                    failures=tuple(errors),
                    round_number=2,
                    attempt_id=attempt_id,
                    report_dir=candidate,
                ))
                engineering_results.append(second)
                _write_json(candidate / "engineering-result-2.json", second)
                if not second.get("ok"):
                    patch_path = candidate / "change.patch"
                    patch_path.write_text("", encoding="utf-8")
                    return {
                        "ok": False,
                        "status": "blocked",
                        "attempt_id": attempt_id,
                        "candidate_path": str(candidate),
                        "patch_path": str(patch_path),
                        "patch_sha256": sha256(patch_path),
                        "errors": [],
                        "blocker": self._engineering_blocker(task, second, scaffold),
                        "artifacts": [],
                        "engineering": engineering_results,
                    }
                changed, errors = self._validate_candidate(task, worktree, artifact_dir, verifier)
            _git(worktree, "add", "-N", "--", ".")
            patch = _git(worktree, "diff", "--binary", "--", ".")
            patch_path = candidate / "change.patch"
            patch_path.write_text(patch, encoding="utf-8")
        finally:
            with self.git_lock:
                _git(self.integration, "worktree", "remove", "--force", str(worktree), check=False)
        outcome = {
            "ok": False,
            "status": "failed",
            "attempt_id": attempt_id,
            "candidate_path": str(candidate),
            "patch_path": str(candidate / "change.patch"),
            "patch_sha256": sha256(candidate / "change.patch") if (candidate / "change.patch").is_file() else None,
            "errors": errors,
            "artifacts": [],
            "engineering": engineering_results,
        }
        if errors:
            return outcome
        with self.git_lock:
            applied = False
            artifacts: list[dict[str, Any]] = []
            try:
                if patch.strip():
                    _git(self.integration, "apply", "--check", str(candidate / "change.patch"))
                    _git(self.integration, "apply", str(candidate / "change.patch"))
                    applied = True
                verification_errors = self.tools[task["provider"]["verify_tool"]](self._context(task, self.integration, artifact_dir))
                if verification_errors:
                    _git(self.integration, "apply", "-R", str(candidate / "change.patch"), check=False)
                    outcome["errors"] = verification_errors
                    return outcome
                artifacts = [self._snapshot(candidate / "change.patch", "patch")]
                for relative in task["provider"]["outputs"]:
                    artifacts.append(self._snapshot(self.integration / relative, "output"))
                for relative in task["provider"].get("artifact_outputs", []):
                    snapshot = self._snapshot(artifact_dir / relative, "external_output")
                    artifacts.append(snapshot)
                    release = self.run / "release" / relative
                    release.parent.mkdir(parents=True, exist_ok=True)
                    temporary = release.with_name(release.name + ".tmp")
                    shutil.copyfile(snapshot["path"], temporary)
                    os.replace(temporary, release)
                for relative in task["provider"].get("internal_artifact_outputs", []):
                    artifacts.append(self._snapshot(artifact_dir / relative, "internal_evaluation_output"))
                changed = self._changed(self.integration)
                if changed:
                    _git(self.integration, "add", "--", *changed)
                    _git(
                        self.integration,
                        "-c", "user.name=SoC Image Factory",
                        "-c", "user.email=soc-image@localhost",
                        "commit", "-m", f"agent: promote {task['id']}",
                    )
                outcome["promotion_commit"] = _git(self.integration, "rev-parse", "HEAD").strip()
            except Exception as exc:
                if applied:
                    _git(self.integration, "reset", "--", ".", check=False)
                    _git(self.integration, "apply", "-R", str(candidate / "change.patch"), check=False)
                outcome["errors"] = [f"promotion failed: {exc}"]
                return outcome
        outcome.update(
            ok=True,
            status="passed",
            blocker=None,
            artifacts=artifacts,
        )
        return outcome

    @staticmethod
    def _changed(worktree: Path) -> list[str]:
        output = _git(worktree, "status", "--porcelain=v1", "-z", "--untracked-files=all")
        entries = output.split("\0")
        paths = []
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if len(entry) < 4:
                continue
            paths.append(entry[3:])
            if "R" in entry[:2] or "C" in entry[:2]:
                if index < len(entries) and entries[index]:
                    paths.append(entries[index])
                    index += 1
        return sorted(set(paths))

    def _snapshot(self, source: Path, kind: str) -> dict[str, Any]:
        digest = sha256(source)
        destination = self.run / "artifacts" / digest / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(source, destination)
        return {"sha256": digest, "path": str(destination), "bytes": destination.stat().st_size, "kind": kind}


class Engine:
    def __init__(
        self,
        run: Path,
        *,
        registry_path: Path = DEFAULT_REGISTRY,
        requested: Iterable[str] = BASELINE_CAPABILITIES,
        source_policy_path: Path = DEFAULT_SOURCE_POLICY,
        tools: dict[str, Callable] | None = None,
        engineer_runner: Callable[[EngineeringRequest], dict[str, Any]] = run_engineering_agent,
    ):
        self.run = run.resolve()
        self.registry_path = registry_path.resolve()
        self.requested = tuple(requested)
        self.source_policy_path = source_policy_path.resolve()
        self.tools = tools
        self.engineer_runner = engineer_runner

    def _inputs(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str, str, str, str]:
        ir_path = self.run / "hardware_ir.json"
        requirements_path = self.run / "software_requirements.json"
        ir = json.loads(ir_path.read_text(encoding="utf-8"))
        profile = json.loads((self.run / "reference_profile.json").read_text(encoding="utf-8"))
        requirements = json.loads(requirements_path.read_text(encoding="utf-8"))
        policy = json.loads(self.source_policy_path.read_text(encoding="utf-8"))
        return ir, profile, requirements, policy, sha256(ir_path), sha256(self.run / "reference_profile.json"), sha256(requirements_path), sha256(self.source_policy_path)

    def _integration(self, ir_hash: str) -> Path:
        path = self.run / "integration"
        if not (path / ".git").exists():
            path.mkdir(parents=True, exist_ok=True)
            _git(path, "init", "-q")
            _write_json(path / ".soc-image-run.json", {"schema": "soc-image.integration.v1", "hardware_ir_sha256": ir_hash})
            _git(path, "add", ".soc-image-run.json")
            _git(path, "-c", "user.name=SoC Image Factory", "-c", "user.email=soc-image@localhost", "commit", "-q", "-m", "control: initialize run integration tree")
        metadata = json.loads((path / ".soc-image-run.json").read_text(encoding="utf-8"))
        if metadata.get("hardware_ir_sha256") != ir_hash:
            raise ValueError("integration tree is bound to a different Hardware IR")
        return path

    def replan(self) -> dict[str, Any]:
        ir, profile, requirements, _, ir_hash, profile_hash, requirements_hash, policy_hash = self._inputs()
        plan_data = plan(ir, profile, requirements, load_registry(self.registry_path), ir_hash, profile_hash, requirements_hash, policy_hash, self.requested)
        _write_json(self.run / "plan.json", plan_data)
        state = State(self.run / "state.db")
        try:
            state.reconcile(plan_data)
        finally:
            state.close()
        return plan_data

    def run_tasks(self, *, max_workers: int = 2, recover: bool = False) -> dict[str, Any]:
        recovered = 0
        retried_blockers = 0
        if recover and (self.run / "state.db").is_file():
            previous = State(self.run / "state.db")
            try:
                recovered = previous.recover()
                previous.retry_failed()
                retried_blockers = previous.retry_blocked()
            finally:
                previous.close()
        plan_data = self.replan()
        ir, profile, requirements, policy, ir_hash, _, _, _ = self._inputs()
        integration = self._integration(ir_hash)
        state = State(self.run / "state.db")
        try:
            integrity_errors = state.artifact_errors()
            if integrity_errors:
                return self._status(state, plan_data, integrity_errors, recovered)
            executor = CandidateExecutor(
                self.run,
                integration,
                ir,
                profile,
                requirements,
                policy,
                self.tools,
                self.engineer_runner,
            )
            while True:
                ready = state.ready()
                if not ready:
                    break
                attempts = {task["id"]: uuid.uuid4().hex for task in ready}
                for task in ready:
                    state.start(task, attempts[task["id"]], self.run / "candidates" / attempts[task["id"]])
                with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
                    futures = {pool.submit(executor.execute, task, attempts[task["id"]]): task for task in ready}
                    for future in as_completed(futures):
                        task = futures[future]
                        try:
                            outcome = future.result()
                        except Exception as exc:
                            outcome = {"ok": False, "status": "failed", "attempt_id": attempts[task["id"]], "errors": [f"attempt crashed: {exc}"], "artifacts": []}
                        state.finish(task, outcome)
            result = self._status(state, plan_data, [], recovered)
            result["retried_blockers"] = retried_blockers
            return result
        finally:
            state.close()

    def status(self) -> dict[str, Any]:
        plan_path = self.run / "plan.json"
        if not plan_path.is_file() or not (self.run / "state.db").is_file():
            return {"ok": False, "status": "control_plane_missing", "run": str(self.run), "errors": ["plan.json or state.db is missing"]}
        plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
        state = State(self.run / "state.db")
        try:
            errors = state.artifact_errors()
            if state.metadata("plan_hash") != _json_hash(plan_data):
                errors.append("plan.json does not match state.db")
            integration = self.run / "integration"
            if integration.is_dir() and _git(integration, "status", "--porcelain", check=False).strip():
                errors.append("integration worktree has unpromoted changes")
            return self._status(state, plan_data, errors, 0)
        finally:
            state.close()

    @staticmethod
    def _status(state: State, plan_data: dict[str, Any], errors: list[str], recovered: int) -> dict[str, Any]:
        rows = state.task_rows()
        task_status = {row["id"]: row["status"] for row in rows}
        failed = [row["id"] for row in rows if row["status"] == "failed"]
        blocked = [row["id"] for row in rows if row["status"] == "blocked"]
        pending = [row["id"] for row in rows if row["status"] in {"pending", "running"}]
        task_blockers = [
            {"task": row["id"], "detail": json.loads(row["blocker"] or "{}")}
            for row in rows if row["status"] == "blocked"
        ]
        control_blockers = [*plan_data.get("blockers", []), *task_blockers, *({"reason": value} for value in errors)]
        ok = not control_blockers and not failed and not blocked and not pending
        return {
            "ok": ok,
            "status": "control_plane_ready" if ok else "blocked",
            "run": str(state.path.parent),
            "plan": str(state.path.parent / "plan.json"),
            "state_db": str(state.path),
            "task_status": task_status,
            "failed_tasks": failed,
            "blocked_tasks": blocked,
            "pending_tasks": pending,
            "control_blockers": control_blockers,
            "hardware_blockers": plan_data.get("hardware_blockers", []),
            "recovered_tasks": recovered,
            "errors": errors,
            "next_stage": "boot_bsp" if ok else None,
        }


def selftest() -> None:
    from socimage.hardware import derive
    from socimage.intake import create_run

    def fake_engineer(request: EngineeringRequest) -> dict[str, Any]:
        blocked = request.scaffold.get("status") == "blocked"
        blocker = request.scaffold.get("blocker", {}).get("reason", "scaffold blocked") if blocked else None
        report = {
            "schema": "soc-image.engineering-agent-report.v1",
            "task_id": request.task["id"],
            "attempt_id": request.attempt_id,
            "agent": request.task["agent"],
            "hardware_ir_sha256": request.task["hardware_ir_sha256"],
            "input_hash": request.task["input_hash"],
            "round": request.round_number,
            "status": "blocked" if blocked else "implemented",
            "summary": "selftest engineer inspected the scaffold",
            "inspected_paths": [request.task["provider"]["outputs"][0]],
            "reused_sources": [],
            "changes": [],
            "commands": [] if blocked else ["selftest scaffold inspection"],
            "blockers": [blocker] if blocker else [],
        }
        return {"ok": not blocked, "status": report["status"], "errors": [], "report": report}

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        svd = root / "soc.svd"
        svd.write_text(
            """<device><name>control</name><size>32</size><access>read-write</access><peripherals>
            <peripheral><name>UART0</name><baseAddress>0x1000</baseAddress><registers><register>
            <name>DATA</name><addressOffset>0</addressOffset><fields><field><name>VALUE</name>
            <bitOffset>0</bitOffset><bitWidth>8</bitWidth></field></fields></register></registers></peripheral>
            </peripherals></device>""",
            encoding="utf-8",
        )
        run = root / "run"
        create_run([svd], run)
        derived = derive(run)
        if not derived["ok"]:
            raise RuntimeError(f"control selftest Hardware IR failed: {derived}")
        engine = Engine(run, requested=("hardware_contract_summary",), engineer_runner=fake_engineer)
        plan_data = engine.replan()
        assert [task["id"] for task in plan_data["tasks"]] == ["task:hardware_contract_summary"]
        requirements_hash = sha256(run / "software_requirements.json")
        assert plan_data["software_requirements_sha256"] == requirements_hash
        assert plan_data["tasks"][0]["software_requirements_sha256"] == requirements_hash
        changed_plan = plan(
            json.loads((run / "hardware_ir.json").read_text(encoding="utf-8")),
            json.loads((run / "reference_profile.json").read_text(encoding="utf-8")),
            json.loads((run / "software_requirements.json").read_text(encoding="utf-8")),
            load_registry(),
            sha256(run / "hardware_ir.json"),
            sha256(run / "reference_profile.json"),
            "f" * 64,
            sha256(DEFAULT_SOURCE_POLICY),
            ("hardware_contract_summary",),
        )
        assert changed_plan["tasks"][0]["input_hash"] != plan_data["tasks"][0]["input_hash"]
        state = State(run / "state.db")
        state.connection.execute("UPDATE tasks SET status='running'")
        state.connection.commit()
        state.close()
        result = engine.run_tasks(recover=True)
        assert result["ok"] and result["recovered_tasks"] == 1, result
        assert (run / "integration/generated/control/hardware_contract_summary.json").is_file()

        tamper_state = State(run / "state.db")
        artifact = Path(tamper_state.connection.execute("SELECT path FROM artifacts WHERE kind='output'").fetchone()["path"])
        artifact.write_text("tampered\n", encoding="utf-8")
        tamper_errors = tamper_state.artifact_errors()
        recorded_artifacts = [dict(row) for row in tamper_state.connection.execute("SELECT sha256,path,bytes FROM artifacts")]
        tamper_state.close()
        assert tamper_errors, {"selected": str(artifact), "recorded": recorded_artifacts}
        tamper_status = engine.status()
        assert not tamper_status["ok"] and tamper_status["errors"], tamper_status

        empty_registry = root / "empty.json"
        _write_json(empty_registry, {"schema": "soc-image.capability-registry.v1", "capabilities": []})
        missing = Engine(run, registry_path=empty_registry).replan()
        assert missing["blockers"] and "missing capability" in missing["blockers"][0]["reason"]
        empty_state = State(run / "state.db")
        assert not empty_state.task_rows()
        empty_state.close()

        bad_registry = root / "bad.json"
        _write_json(
            bad_registry,
            {
                "schema": "soc-image.capability-registry.v1",
                "capabilities": [{
                    "id": "bad", "depends_on": [], "activates_on": [],
                    "provider": {"agent": "HardwareAgent", "tool": "bad", "verify_tool": "verify_bad", "owned_paths": ["generated/control"], "outputs": ["generated/control/expected.txt"]},
                }],
            },
        )

        def bad(context: ToolContext) -> dict[str, Any]:
            (context.worktree / "forbidden.txt").write_text("no\n", encoding="utf-8")
            (context.worktree / context.outputs[0]).parent.mkdir(parents=True, exist_ok=True)
            (context.worktree / context.outputs[0]).write_text("expected\n", encoding="utf-8")
            return {"status": "passed", "outputs": list(context.outputs)}

        bad_run = root / "bad-run"
        create_run([svd], bad_run)
        derive(bad_run)
        bad_result = Engine(bad_run, registry_path=bad_registry, requested=("bad",), tools={"bad": bad, "verify_bad": lambda context: []}, engineer_runner=fake_engineer).run_tasks()
        assert not bad_result["ok"]
        assert not (bad_run / "integration/forbidden.txt").exists()
        bad_engine = Engine(bad_run, registry_path=bad_registry, requested=("bad",), tools={"bad": bad, "verify_bad": lambda context: []}, engineer_runner=fake_engineer)
        assert not bad_engine.run_tasks(recover=True)["ok"]
        bad_state = State(bad_run / "state.db")
        failure = bad_state.connection.execute("SELECT occurrences FROM failures").fetchone()
        bad_state.close()
        assert failure["occurrences"] == 2

        two_registry = root / "two.json"
        capabilities = []
        custom_tools: dict[str, Callable] = {}

        def write_result(context: ToolContext) -> dict[str, Any]:
            (context.worktree / context.outputs[0]).parent.mkdir(parents=True, exist_ok=True)
            (context.worktree / context.outputs[0]).write_text(context.task_id, encoding="utf-8")
            return {"status": "passed", "outputs": list(context.outputs)}

        for name in ("one", "two"):
            capabilities.append({
                "id": name, "depends_on": [], "activates_on": [],
                "provider": {"agent": "HardwareAgent", "tool": f"write_{name}", "verify_tool": f"verify_{name}", "owned_paths": [f"generated/{name}"], "outputs": [f"generated/{name}/result.txt"]},
            })
            custom_tools[f"write_{name}"] = write_result
            custom_tools[f"verify_{name}"] = lambda context: [] if (context.worktree / context.outputs[0]).is_file() else ["missing"]
        capabilities[0]["provider"]["artifact_outputs"] = ["payload.bin"]
        capabilities[1]["provider"]["internal_artifact_outputs"] = ["internal.bin"]

        def write_one(context: ToolContext) -> dict[str, Any]:
            (context.worktree / context.outputs[0]).parent.mkdir(parents=True, exist_ok=True)
            (context.worktree / context.outputs[0]).write_text(context.task_id, encoding="utf-8")
            (context.artifact_dir / "payload.bin").write_bytes(b"external-artifact\n")
            return {"status": "passed", "outputs": list(context.outputs), "artifacts": ["payload.bin"]}

        custom_tools["write_one"] = write_one

        def write_two(context: ToolContext) -> dict[str, Any]:
            (context.worktree / context.outputs[0]).parent.mkdir(parents=True, exist_ok=True)
            (context.worktree / context.outputs[0]).write_text(context.task_id, encoding="utf-8")
            (context.artifact_dir / "internal.bin").write_bytes(b"internal-evaluation\n")
            return {"status": "passed", "outputs": list(context.outputs), "artifacts": ["internal.bin"]}

        custom_tools["write_two"] = write_two
        _write_json(two_registry, {"schema": "soc-image.capability-registry.v1", "capabilities": capabilities})
        parallel_run = root / "parallel-run"
        create_run([svd], parallel_run)
        derive(parallel_run)
        parallel = Engine(parallel_run, registry_path=two_registry, requested=("one", "two"), tools=custom_tools, engineer_runner=fake_engineer).run_tasks(max_workers=2)
        assert parallel["ok"], parallel
        assert (parallel_run / "integration/generated/one/result.txt").is_file()
        assert (parallel_run / "integration/generated/two/result.txt").is_file()
        assert (parallel_run / "release/payload.bin").read_bytes() == b"external-artifact\n"
        assert not (parallel_run / "release/internal.bin").exists()
        parallel_state = State(parallel_run / "state.db")
        internal_artifact = parallel_state.connection.execute("SELECT path FROM artifacts WHERE kind='internal_evaluation_output'").fetchone()
        parallel_state.close()
        assert internal_artifact is not None and Path(internal_artifact["path"]).read_bytes() == b"internal-evaluation\n"

        blocked_registry = root / "blocked.json"
        _write_json(
            blocked_registry,
            {
                "schema": "soc-image.capability-registry.v1",
                "capabilities": [
                    {
                        "id": "physical_probe", "depends_on": [], "activates_on": [],
                        "provider": {
                            "agent": "VerificationAgent", "tool": "physical_probe",
                            "verify_tool": "verify_physical_probe", "owned_paths": ["generated/probe"],
                            "outputs": ["generated/probe/result.json"],
                        },
                    },
                    {
                        "id": "after_probe", "depends_on": ["physical_probe"], "activates_on": [],
                        "provider": {
                            "agent": "CompilerAgent", "tool": "after_probe",
                            "verify_tool": "verify_after_probe", "owned_paths": ["generated/after"],
                            "outputs": ["generated/after/result.json"],
                        },
                    },
                ],
            },
        )

        def physical_probe(context: ToolContext) -> dict[str, Any]:
            output = context.worktree / context.outputs[0]
            _write_json(output, {"status": "blocked", "reason": "physical board is unavailable"})
            return {
                "status": "blocked",
                "outputs": list(context.outputs),
                "blocker": {
                    "code": "physical_board_missing",
                    "reason": "physical board is unavailable",
                    "retryable": True,
                    "owner": "VerificationAgent",
                },
            }

        def after_probe(context: ToolContext) -> dict[str, Any]:
            _write_json(context.worktree / context.outputs[0], {"status": "should_not_run"})
            return {"status": "passed", "outputs": list(context.outputs)}

        blocked_tools = {
            "physical_probe": physical_probe,
            "verify_physical_probe": lambda context: [] if (context.worktree / context.outputs[0]).is_file() else ["missing probe result"],
            "after_probe": after_probe,
            "verify_after_probe": lambda context: [] if (context.worktree / context.outputs[0]).is_file() else ["missing downstream result"],
        }
        blocked_run = root / "blocked-run"
        create_run([svd], blocked_run)
        derive(blocked_run)
        blocked_engine = Engine(blocked_run, registry_path=blocked_registry, requested=("after_probe",), tools=blocked_tools, engineer_runner=fake_engineer)
        blocked_result = blocked_engine.run_tasks()
        assert blocked_result["task_status"] == {"task:after_probe": "pending", "task:physical_probe": "blocked"}, blocked_result
        assert blocked_result["blocked_tasks"] == ["task:physical_probe"]
        assert not (blocked_run / "integration/generated/probe/result.json").exists()
        assert not (blocked_run / "integration/generated/after/result.json").exists()
        resumed = blocked_engine.run_tasks(recover=True)
        assert resumed["retried_blockers"] == 1
        assert resumed["task_status"]["task:physical_probe"] == "blocked"
        blocked_state = State(blocked_run / "state.db")
        probe_row = blocked_state.connection.execute("SELECT attempts,blocker FROM tasks WHERE id='task:physical_probe'").fetchone()
        blocked_state.close()
        assert probe_row["attempts"] == 2
        assert json.loads(probe_row["blocker"])["code"] == "physical_board_missing"
        exhausted = blocked_engine.run_tasks(recover=True)
        assert exhausted["retried_blockers"] == 0
        exhausted_state = State(blocked_run / "state.db")
        assert exhausted_state.connection.execute("SELECT attempts FROM tasks WHERE id='task:physical_probe'").fetchone()["attempts"] == 2
        exhausted_state.close()

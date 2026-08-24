"""Project-internal autonomous coding with isolated verification and promotion."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from jsonschema import Draft202012Validator

from socimage.facts import sha256
from engine.source_export import export_project_source_context


ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = Path("chip")
TASK_SCHEMA = ROOT / "schemas/development_task.schema.json"
AGENT_SCHEMA = ROOT / "schemas/development_agent_report.schema.json"
REVIEW_SCHEMA = ROOT / "schemas/development_review.schema.json"
ModelRunner = Callable[[Path, str, Path, Path, bool], dict[str, Any]]
IsolatedBaseline = tuple[str, bytes]


def _source_path(repository: Path) -> Path:
    repository = repository.resolve()
    if ROOT.resolve().is_relative_to(repository):
        return ROOT.resolve().relative_to(repository)
    return PROJECT_DIR if (repository / PROJECT_DIR).is_dir() else Path(".")


REPOSITORY = Path(subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], cwd=ROOT, text=True,
    stdout=subprocess.PIPE, check=True,
).stdout.strip())


def _repository_paths(paths: list[str], project_path: Path) -> list[str]:
    return [str(project_path / path) if project_path != Path(".") else path for path in paths]


def _git_environment(**values: str) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(values)
    return environment


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def _git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, env=_git_environment(), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    if check and proc.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stdout.strip()}")
    return proc.stdout


def _isolated_checkout(repository: Path, destination: Path, revision: str) -> IsolatedBaseline:
    destination.mkdir(parents=True)
    source_path = _source_path(repository)
    treeish = revision if source_path == Path(".") else f"{revision}:{source_path.as_posix()}"
    with tempfile.NamedTemporaryFile(suffix=".tar") as archive:
        proc = subprocess.run(
            ["git", "archive", "--format=tar", f"--output={archive.name}", f"--prefix={PROJECT_DIR}/", treeish],
            cwd=repository, env=_git_environment(), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if proc.returncode:
            raise RuntimeError(f"git archive failed: {proc.stdout.strip()}")
        with tarfile.open(archive.name) as stream:
            stream.extractall(destination, filter="data")
    _git(destination, "init", "-q")
    _git(destination, "add", "--", str(PROJECT_DIR))
    _git(
        destination, "-c", "user.name=SoC Image Factory", "-c", "user.email=soc-image@localhost", "-c", "core.hooksPath=/dev/null",
        "commit", "-q", "-m", f"isolated base {revision}", "--", str(PROJECT_DIR),
    )
    return _git(destination, "rev-parse", "HEAD").strip(), (destination / ".git/config").read_bytes()


def _install_source_contexts(repository: Path, isolated: Path, contexts: list[dict[str, Any]]) -> tuple[IsolatedBaseline, list[dict[str, Any]]]:
    source_root = repository / _source_path(repository)
    manifests = [
        export_project_source_context(source_root, item, isolated / PROJECT_DIR / ".agent-context" / item["repository"])
        for item in contexts
    ]
    if manifests:
        _git(isolated, "add", "--", f"{PROJECT_DIR}/.agent-context")
        _git(isolated, "-c", "user.name=SoC Image Factory", "-c", "user.email=soc-image@localhost", "-c", "core.hooksPath=/dev/null", "commit", "-q", "--amend", "--no-edit")
    return (_git(isolated, "rev-parse", "HEAD").strip(), (isolated / ".git/config").read_bytes()), manifests


def _safe(path: str) -> bool:
    value = PurePosixPath(path)
    return bool(path) and not value.is_absolute() and ".." not in value.parts and ".git" not in value.parts


def _within(path: str, prefixes: list[str]) -> bool:
    return _safe(path) and any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)


def _status_paths(repo: Path) -> list[str]:
    output = _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = output.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if ("R" in entry[:2] or "C" in entry[:2]) and index < len(entries) and entries[index]:
            paths.append(entries[index])
            index += 1
    return sorted(set(paths))


def _chip_path(repository_path: str, project_path: Path = PROJECT_DIR) -> str | None:
    if project_path == Path("."):
        return repository_path
    prefix = project_path.as_posix().rstrip("/") + "/"
    return repository_path[len(prefix):] if repository_path.startswith(prefix) else None


def _sandbox_executable() -> str | None:
    direct = shutil.which("bwrap")
    if direct:
        return direct
    codex = Path(shutil.which("codex") or "")
    if codex.is_file():
        matches = sorted(codex.resolve().parents[1].glob("node_modules/@openai/codex-linux-*/vendor/*/codex-resources/bwrap"))
        if matches:
            return str(matches[0])
    return None


def _nested_acceptance() -> bool:
    try:
        uid_map = Path("/proc/self/uid_map").read_text(encoding="ascii").split()
    except OSError:
        return False
    return (
        os.environ.get("SOC_IMAGE_ACCEPTANCE_SANDBOX") == "1"
        and ROOT.resolve() in {Path("/mnt/chip"), Path("/mnt")}
        and uid_map == ["0", "0", "1"]
    )


def _run_commands(
    worktree: Path,
    commands: list[list[str]],
    project_path: Path = PROJECT_DIR,
) -> tuple[list[dict[str, Any]], list[str]]:
    reports = []
    errors = []
    nested = _nested_acceptance()
    sandbox = _sandbox_executable()
    if not sandbox:
        return reports, ["acceptance sandbox is unavailable"]
    git_marker = worktree / ".git"
    python_paths = ["/mnt/chip", *[value for value in os.environ.get("PYTHONPATH", "").split(os.pathsep) if value]]
    if not nested:
        venv = (ROOT / ".venv").resolve()
        python_paths.extend(
            str(resolved) for path in sorted((venv / "lib").glob("python*/site-packages"))
            if (resolved := path.resolve()).is_dir() and resolved.is_relative_to(venv)
        )
    for command in commands:
        with tempfile.TemporaryDirectory(prefix="soc-image-acceptance-") as temporary:
            environment = {
                "HOME": os.environ.get("HOME", "/tmp"), "TMPDIR": "/tmp", "XDG_CACHE_HOME": "/tmp/.cache",
                "PIP_CACHE_DIR": "/tmp/.cache/pip", "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "LANG": os.environ.get("LANG", "C.UTF-8"), "LC_ALL": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
                "SOC_IMAGE_ACCEPTANCE_SANDBOX": "1",
                "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": "/mnt",
                "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            }
            if python_paths:
                environment["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(python_paths))
            try:
                sandboxed = [sandbox, "--die-with-parent", "--new-session"]
                if nested:
                    sandboxed.extend(["--unshare-net", "--unshare-ipc", "--unshare-uts", "--unshare-pid"])
                else:
                    sandboxed.append("--unshare-all")
                sandboxed.extend([
                    "--ro-bind", "/", "/",
                    "--bind", str(worktree), "/mnt", "--ro-bind", str(git_marker), "/mnt/.git",
                    "--bind", temporary, "/tmp",
                ])
                if not nested:
                    sandboxed.extend(["--proc", "/proc"])
                sandboxed.extend(["--dev", "/dev"])
                sandboxed.extend([
                    "--chdir", "/mnt" if project_path == Path(".") else f"/mnt/{project_path}",
                    "--", *command,
                ])
                proc = subprocess.run(
                    sandboxed, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    check=False, timeout=900, env=environment,
                )
            except subprocess.TimeoutExpired:
                errors.append(f"command timed out: {' '.join(command)}")
                break
        report = {"command": command, "returncode": proc.returncode, "output": proc.stdout[-12000:]}
        reports.append(report)
        if proc.returncode:
            errors.append(f"command failed ({proc.returncode}): {' '.join(command)}\n{proc.stdout[-4000:]}")
            break
    return reports, errors


def _codex_runner(chip: Path, prompt: str, output: Path, schema: Path, read_only: bool) -> dict[str, Any]:
    executable = shutil.which("codex")
    if not executable:
        return {"ok": False, "error": "global development model executable is unavailable"}
    command = [
        executable, "exec", "--ephemeral", "--color", "never", "--config", 'model_reasoning_effort="low"', "--sandbox",
        "read-only" if read_only else "workspace-write", "--output-schema", str(schema),
        "--output-last-message", str(output), "--cd", str(chip), prompt,
    ]
    timeout_text = os.environ.get("SOC_IMAGE_MODEL_TIMEOUT_SECONDS", "600")
    if not timeout_text.isdigit() or not 60 <= int(timeout_text) <= 1800:
        return {"ok": False, "error": "SOC_IMAGE_MODEL_TIMEOUT_SECONDS must be 60 through 1800"}
    try:
        proc = subprocess.run(
            command,
            env=_git_environment(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null", GIT_CONFIG_NOSYSTEM="1"),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=int(timeout_text),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "global development model timed out"}
    result: dict[str, Any] = {"ok": proc.returncode == 0, "returncode": proc.returncode, "log": proc.stdout[-20000:]}
    if output.is_file():
        try:
            result["report"] = json.loads(output.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            result["error"] = f"model report is not JSON: {exc}"
            result["ok"] = False
    else:
        result["error"] = "model did not produce a structured report"
        result["ok"] = False
    return result


class DevelopmentEngine:
    def __init__(self, task_path: Path, out: Path, *, repository: Path = REPOSITORY, model_runner: ModelRunner = _codex_runner):
        self.task_path = task_path.resolve()
        self.out = out.resolve()
        self.repository = repository.resolve()
        self.project_path = _source_path(self.repository)
        self.chip = self.repository / self.project_path
        self.model_runner = model_runner
        self.task = json.loads(self.task_path.read_text(encoding="utf-8"))
        Draft202012Validator(json.loads(TASK_SCHEMA.read_text(encoding="utf-8"))).validate(self.task)
        if any(not _within(path, self.task["owned_paths"]) for path in self.task["required_outputs"]):
            raise ValueError("required output is outside Agent ownership")
        if any(not _safe(path) for path in self.task.get("context_paths", [])):
            raise ValueError("unsafe context path")
        repositories = [item["repository"] for item in self.task.get("source_contexts", [])]
        if len(repositories) != len(set(repositories)):
            raise ValueError("source context repositories must be unique")
        if any(_within(".agent-context", [path]) or _within(path, [".agent-context"]) for path in self.task["owned_paths"]):
            raise ValueError("source contexts cannot be Agent-owned")
        self.source_context_manifest: list[dict[str, Any]] = []

    def _prompt(self, failures: list[Any]) -> str:
        return """You are the project-internal {agent}. Implement exactly one development task in this isolated Git worktree.

Task contract:
{task}

Rules:
- Inspect the existing code before editing and reuse its patterns.
- Start with owned_paths and context_paths. Read other files only when a direct import or acceptance failure requires it.
- This is an independent source export: local HEAD contains base_revision's project tree but has a different local commit ID. Inspect local HEAD; keep reports bound to the task's base_revision.
- Modify only owned_paths. Do not commit, reset, or create Git worktrees.
- Implement every required_output and run the acceptance commands.
- Do not implement later stages or weaken existing tests and gates.
- Treat reference/evaluation sources as read-only evidence; never copy unlicensed code into production paths.
- Reuse the resolved source contexts instead of reimplementing them. Contexts with source_usage=reference_only or redistribution=file_level_review_required are read-only evidence and cannot be copied without file-level approval.
Resolved source context manifest:
{source_contexts}
- Finish with the required structured report. That report is advisory; deterministic verification remains authoritative.

Previous deterministic failures:
{failures}
""".format(agent=self.task["agent"], task=json.dumps(self.task, indent=2, sort_keys=True), failures=json.dumps(failures, indent=2), source_contexts=json.dumps(self.source_context_manifest, indent=2, sort_keys=True))

    def _review_prompt(self, patch_sha256: str) -> str:
        return """Act as an independent senior verifier. Review only the uncommitted diff for this task:
{task}

Check correctness, security boundaries, fail-closed behavior, provenance, test adequacy, and whether the implementation exceeds owned_paths. Do not edit files. Return fail for any P1 or P2 finding; P3 may pass. Use the required structured review output.
Require reuse of the resolved source contexts rather than reimplementation. Treat reference_only or file_level_review_required sources as read-only evidence that cannot be copied without file-level approval.
Resolved source context manifest:
{source_contexts}
The structured result must bind task_id={task_id}, base_revision={base_revision}, and patch_sha256={patch_sha256} exactly.
""".format(task=json.dumps(self.task, indent=2, sort_keys=True), task_id=self.task["id"], base_revision=self.task["base_revision"], patch_sha256=patch_sha256, source_contexts=json.dumps(self.source_context_manifest, indent=2, sort_keys=True))

    def _inspect_candidate(self, worktree: Path, baseline: IsolatedBaseline) -> tuple[list[str], list[str]]:
        changed = []
        errors = []
        marker = worktree / ".git"
        if not marker.is_dir():
            errors.append("Agent changed isolated Git metadata")
            return changed, errors
        config = marker / "config"
        if not config.is_file() or config.read_bytes() != baseline[1]:
            errors.append("Agent changed isolated Git configuration")
            return changed, errors
        common = _git(worktree, "rev-parse", "--git-common-dir", check=False).strip()
        if not common or (worktree / common).resolve() != marker.resolve():
            errors.append("Agent changed isolated Git metadata")
            return changed, errors
        if _git(worktree, "rev-parse", "HEAD", check=False).strip() != baseline[0]:
            errors.append("Agent changed candidate HEAD")
        repository_paths = _status_paths(worktree)
        for path in repository_paths:
            relative = _chip_path(path)
            if relative is None or not _within(relative, self.task["owned_paths"]):
                errors.append(f"unauthorized path: {path}")
            else:
                changed.append(relative)
                if (worktree / path).is_symlink():
                    errors.append(f"symbolic links are forbidden: {path}")
        if not changed:
            errors.append("Agent produced no owned-path changes")
        for path in self.task["required_outputs"]:
            output = worktree / PROJECT_DIR / path
            if not output.is_file() or output.is_symlink():
                errors.append(f"missing required regular output: {path}")
        return changed, errors

    def _validate_candidate(self, worktree: Path, baseline: IsolatedBaseline) -> tuple[list[str], list[str], list[dict[str, Any]]]:
        changed, errors = self._inspect_candidate(worktree, baseline)
        reports: list[dict[str, Any]] = []
        if not errors:
            reports, command_errors = _run_commands(worktree, self.task["acceptance_commands"])
            errors.extend(command_errors)
            final_changed, final_errors = self._inspect_candidate(worktree, baseline)
            errors.extend(final_errors)
            if final_changed != changed:
                errors.append("acceptance commands changed the candidate path set")
            changed = final_changed
        return changed, errors, reports

    @staticmethod
    def _patch(worktree: Path, changed: list[str], project_path: Path = PROJECT_DIR) -> str:
        paths = _repository_paths(changed, project_path)
        existing = [path for path in paths if (worktree / path).exists()]
        if existing:
            _git(worktree, "add", "-N", "--", *existing)
        return _git(worktree, "diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD", "--", *paths)

    @staticmethod
    def _model_errors(result: dict[str, Any], schema: Path) -> list[str]:
        if not result.get("ok"):
            return [str(result.get("error") or result.get("log") or "model execution failed")]
        report = result.get("report")
        if not isinstance(report, dict):
            return ["model report is not an object"]
        errors = sorted(Draft202012Validator(json.loads(schema.read_text(encoding="utf-8"))).iter_errors(report), key=lambda item: list(item.path))
        return [f"invalid model report: {error.message}" for error in errors]

    def run(self, *, promote: bool = False) -> dict[str, Any]:
        self.out.mkdir(parents=True, exist_ok=True)
        current = _git(self.repository, "rev-parse", "HEAD").strip()
        if current != self.task["base_revision"]:
            return self._finish("blocked", [f"base revision mismatch: expected {self.task['base_revision']}, got {current}"])
        dirty_owned = []
        for path in _status_paths(self.repository):
            relative = _chip_path(path, self.project_path)
            if relative is not None and _within(relative, self.task["owned_paths"]):
                dirty_owned.append(relative)
        if dirty_owned:
            return self._finish("blocked", ["owned paths are dirty: " + ", ".join(dirty_owned)])

        candidate = self.out / "candidate"
        verifier = self.out / "verifier"
        if candidate.exists() or verifier.exists():
            return self._finish("blocked", ["development output already contains a worktree"])
        try:
            candidate_revision = _isolated_checkout(self.repository, candidate, self.task["base_revision"])
            candidate_revision, self.source_context_manifest = _install_source_contexts(self.repository, candidate, self.task.get("source_contexts", []))
        except Exception as exc:
            shutil.rmtree(candidate, ignore_errors=True)
            return self._finish("blocked", [f"source context setup failed: {exc}"])
        failures: list[Any] = []
        attempts = []
        try:
            accepted: tuple[int, list[str], str, Path, dict[str, Any], list[dict[str, Any]]] | None = None
            rejected_patch_hashes: set[str] = set()
            for number in range(1, self.task["max_attempts"] + 1):
                output = self.out / f"agent-attempt-{number}.json"
                model = self.model_runner(candidate / PROJECT_DIR, self._prompt(failures), output, AGENT_SCHEMA, False)
                changed, errors, command_reports = self._validate_candidate(candidate, candidate_revision)
                errors[0:0] = self._model_errors(model, AGENT_SCHEMA)
                model_report = model.get("report", {}) if model.get("ok") else {}
                if not errors and (model_report.get("task_id") != self.task["id"] or model_report.get("base_revision") != self.task["base_revision"]):
                    errors.append("development model report binding mismatch")
                attempt: dict[str, Any] = {
                    "attempt": number, "model": model, "commands": command_reports,
                    "patch_path": None, "patch_sha256": None, "verification_commands": [], "review": None,
                }
                review_feedback = None
                patch = ""
                patch_path: Path | None = None
                if not errors:
                    patch = self._patch(candidate, changed)
                    patch_path = self.out / f"change-attempt-{number}.patch"
                    patch_path.write_text(patch, encoding="utf-8")
                    patch_digest = sha256(patch_path)
                    attempt.update({"patch_path": str(patch_path), "patch_sha256": patch_digest})
                    if patch_digest in rejected_patch_hashes:
                        errors.append("candidate patch was already rejected by independent review")
                        attempt["errors"] = errors
                        attempts.append(attempt)
                        failures.extend(errors)
                        continue
                    try:
                        verifier_revision = _isolated_checkout(self.repository, verifier, self.task["base_revision"])
                        verifier_revision, verifier_contexts = _install_source_contexts(self.repository, verifier, self.task.get("source_contexts", []))
                        if verifier_contexts != self.source_context_manifest:
                            raise RuntimeError("fresh verifier source contexts differ")
                        _git(verifier, "apply", "--check", str(patch_path))
                        _git(verifier, "apply", str(patch_path))
                        if self._patch(verifier, changed) != patch:
                            raise RuntimeError("fresh verifier patch differs before acceptance")
                        verified_changed, verification_errors, verification_commands = self._validate_candidate(verifier, verifier_revision)
                        attempt["verification_commands"] = verification_commands
                        if self._patch(verifier, changed) != patch:
                            verification_errors.append("acceptance commands changed verified patch content")
                        if verified_changed != changed:
                            verification_errors.append("fresh verifier changed-path set differs from candidate")
                        errors.extend(verification_errors)
                        if not verification_errors:
                            review_output = self.out / f"independent-review-attempt-{number}.json"
                            review = self.model_runner(verifier / PROJECT_DIR, self._review_prompt(patch_digest), review_output, REVIEW_SCHEMA, True)
                            attempt["review"] = review
                            review_report = review.get("report", {}) if review.get("ok") else {}
                            review_errors = self._model_errors(review, REVIEW_SCHEMA)
                            if not review_errors and any(review_report.get(name) != value for name, value in {
                                "task_id": self.task["id"], "base_revision": self.task["base_revision"], "patch_sha256": patch_digest,
                            }.items()):
                                review_errors.append("independent review binding mismatch")
                            if not review_errors and (review_report.get("verdict") != "pass" or any(item.get("severity") in {"P1", "P2"} for item in review_report.get("findings", []))):
                                rejected_patch_hashes.add(patch_digest)
                                review_errors.append("independent review reported P1/P2 findings")
                                review_feedback = {"verdict": review_report["verdict"], "findings": review_report["findings"]}
                            post_review_changed, post_review_errors = self._inspect_candidate(verifier, verifier_revision)
                            review_errors.extend(post_review_errors)
                            if post_review_changed != verified_changed or self._patch(verifier, changed) != patch:
                                review_errors.append("independent review changed verified content")
                            errors.extend(review_errors)
                    except Exception as exc:
                        errors.append(f"fresh verifier failed: {exc}")
                    finally:
                        shutil.rmtree(verifier, ignore_errors=True)
                attempt["errors"] = errors
                attempts.append(attempt)
                if not errors:
                    assert patch_path is not None
                    accepted = (number, changed, patch, patch_path, attempt["review"], attempt["verification_commands"])
                    break
                failures.extend(errors)
                if review_feedback is not None:
                    failures.append(review_feedback)
            if accepted is None:
                final = attempts[-1]
                provenance = {}
                if final["patch_path"] is not None:
                    provenance = {
                        "provenance_attempt": final["attempt"], "patch_path": Path(final["patch_path"]),
                        "review": final["review"], "commands": final["verification_commands"],
                    }
                return self._finish("failed", final["errors"], attempts=attempts, **provenance)

            provenance_attempt, changed, patch, patch_path, review, verification_commands = accepted

            promotion_commit = None
            if promote:
                repository_paths = _repository_paths(changed, self.project_path)
                applied = False
                updated = False
                common = Path(_git(self.repository, "rev-parse", "--git-common-dir").strip())
                if not common.is_absolute():
                    common = (self.repository / common).resolve()
                try:
                    with (common / "soc-image-promotion.lock").open("a+", encoding="utf-8") as lock:
                        fcntl.flock(lock, fcntl.LOCK_EX)
                        if _git(self.repository, "rev-parse", "HEAD").strip() != self.task["base_revision"]:
                            raise RuntimeError("repository advanced before promotion")
                        if any(
                            (relative := _chip_path(path, self.project_path)) is not None and _within(relative, self.task["owned_paths"])
                            for path in _status_paths(self.repository)
                        ):
                            raise RuntimeError("owned paths changed before promotion")
                        ref = _git(self.repository, "symbolic-ref", "-q", "HEAD", check=False).strip()
                        if not ref:
                            raise RuntimeError("promotion requires an attached branch")
                        _git(self.repository, "apply", "--check", str(patch_path))
                        _git(self.repository, "apply", str(patch_path))
                        applied = True
                        if self._patch(self.repository, changed, self.project_path) != patch:
                            raise RuntimeError("promotion worktree differs from verified patch")
                        _git(self.repository, "apply", "--cached", str(patch_path))
                        if _git(self.repository, "diff", "--no-ext-diff", "--no-textconv", "--cached", "--binary", "HEAD", "--", *repository_paths) != patch:
                            raise RuntimeError("staged promotion differs from verified patch")
                        with tempfile.NamedTemporaryFile(dir=common, delete=False) as index_file:
                            index_path = Path(index_file.name)
                        index_path.unlink()
                        environment = _git_environment(GIT_INDEX_FILE=str(index_path))
                        try:
                            subprocess.run(["git", "read-tree", self.task["base_revision"]], cwd=self.repository, env=environment, check=True)
                            subprocess.run(["git", "apply", "--cached", str(patch_path)], cwd=self.repository, env=environment, check=True)
                            tree = subprocess.run(["git", "write-tree"], cwd=self.repository, env=environment, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
                        finally:
                            index_path.unlink(missing_ok=True)
                        commit_environment = _git_environment(
                            GIT_AUTHOR_NAME="SoC Image Factory", GIT_AUTHOR_EMAIL="soc-image@localhost",
                            GIT_COMMITTER_NAME="SoC Image Factory", GIT_COMMITTER_EMAIL="soc-image@localhost",
                        )
                        promotion_commit = subprocess.run(
                            ["git", "commit-tree", tree, "-p", self.task["base_revision"]], cwd=self.repository,
                            env=commit_environment, input=self.task["commit_message"] + "\n", text=True,
                            stdout=subprocess.PIPE, check=True,
                        ).stdout.strip()
                        if _git(self.repository, "diff", "--no-ext-diff", "--no-textconv", "--binary", self.task["base_revision"], promotion_commit, "--", *repository_paths) != patch:
                            raise RuntimeError("generated commit differs from verified patch")
                        _git(self.repository, "-c", "core.hooksPath=/dev/null", "update-ref", ref, promotion_commit, self.task["base_revision"])
                        updated = True
                        if _git(self.repository, "rev-parse", "HEAD").strip() != promotion_commit:
                            raise RuntimeError("promotion ref verification failed")
                        if _git(self.repository, "rev-parse", f"{promotion_commit}^").strip() != self.task["base_revision"]:
                            raise RuntimeError("promotion parent verification failed")
                        if _git(self.repository, "diff", "--no-ext-diff", "--no-textconv", "--binary", self.task["base_revision"], promotion_commit, "--", *repository_paths) != patch:
                            raise RuntimeError("promoted commit differs from verified patch")
                        dirty_after = [
                            relative for path in _status_paths(self.repository)
                            if (relative := _chip_path(path, self.project_path)) is not None and _within(relative, self.task["owned_paths"])
                        ]
                        if dirty_after:
                            raise RuntimeError("owned paths changed during promotion: " + ", ".join(dirty_after))
                except Exception as exc:
                    rollback_errors = []
                    if updated and promotion_commit:
                        ref = _git(self.repository, "symbolic-ref", "-q", "HEAD", check=False).strip()
                        if not ref or _git(
                            self.repository, "-c", "core.hooksPath=/dev/null", "update-ref",
                            ref, self.task["base_revision"], promotion_commit, check=False,
                        ).strip():
                            rollback_errors.append("could not atomically restore promotion ref")
                        else:
                            updated = False
                    _git(self.repository, "reset", "--", *repository_paths, check=False)
                    if applied and not updated:
                        _git(self.repository, "apply", "-R", str(patch_path), check=False)
                    dirty_after = [
                        relative for path in _status_paths(self.repository)
                        if (relative := _chip_path(path, self.project_path)) is not None and _within(relative, self.task["owned_paths"])
                    ]
                    if dirty_after:
                        rollback_errors.append("rollback left dirty owned paths: " + ", ".join(dirty_after))
                    return self._finish(
                        "failed", [f"promotion failed: {exc}", *rollback_errors], attempts=attempts,
                        provenance_attempt=provenance_attempt, patch_path=patch_path, review=review, commands=verification_commands,
                    )
            return self._finish(
                "passed", [], attempts=attempts, provenance_attempt=provenance_attempt, patch_path=patch_path,
                review=review, commands=verification_commands, changed=changed, promotion_commit=promotion_commit,
            )
        finally:
            shutil.rmtree(candidate, ignore_errors=True)

    def _finish(self, status: str, errors: list[str], **values: Any) -> dict[str, Any]:
        patch_path = values.get("patch_path")
        report = {
            "schema": "soc-image.development-report.v1", "task_id": self.task["id"],
            "status": status, "base_revision": self.task["base_revision"],
            "task_sha256": sha256(self.task_path),
            "patch_sha256": sha256(patch_path) if isinstance(patch_path, Path) and patch_path.is_file() else None,
            "errors": errors, **{key: value for key, value in values.items() if key != "patch_path"},
        }
        if isinstance(patch_path, Path):
            report["patch_path"] = str(patch_path)
        _write_json(self.out / "report.json", report)
        return report


def selftest() -> None:
    with tempfile.TemporaryDirectory(prefix="development-selftest-") as temporary:
        root = Path(temporary)
        repository = root / "repository"
        chip = repository / "chip"
        chip.mkdir(parents=True)
        (chip / "seed.txt").write_text("seed\n", encoding="utf-8")
        source = chip / "third_party/fixture-source"
        source.mkdir(parents=True)
        (source / "reuse.txt").write_text("reuse me\n", encoding="utf-8")
        _git(source, "init", "-q")
        _git(source, "add", ".")
        _git(source, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "source")
        source_revision = _git(source, "rev-parse", "HEAD").strip()
        _write_json(chip / "third_party.manifest.json", {"default": [{
            "name": "fixture-source", "mode": "pinned_sparse", "revision": source_revision, "paths": ["reuse.txt"],
            "license": "MIT", "redistribution": "allowed_with_license", "source_usage": "build_tool",
        }]})
        _write_json(chip / "third_party.lock.json", {"dependencies": {"fixture-source": {"kind": "git", "revision": source_revision}}})
        _git(repository, "init", "-q")
        _git(repository, "add", ".")
        _git(repository, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "base")
        hook = repository / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nprintf 'hooked\\n' > chip/generated/result.txt\ngit add chip/generated/result.txt\n", encoding="utf-8")
        hook.chmod(0o755)
        reference_hook = repository / ".git/hooks/reference-transaction"
        reference_hook.write_text("#!/bin/sh\n: > reference-hook-called\n", encoding="utf-8")
        reference_hook.chmod(0o755)
        revision = _git(repository, "rev-parse", "HEAD").strip()

        rename_candidate = root / "rename-candidate"
        _isolated_checkout(repository, rename_candidate, revision)
        (rename_candidate / "chip/seed.txt").unlink()
        renamed = rename_candidate / "chip/renamed.txt"
        renamed.write_text("renamed content\n", encoding="utf-8")
        rename_patch = DevelopmentEngine._patch(rename_candidate, ["seed.txt", "renamed.txt"])
        rename_verifier = root / "rename-verifier"
        _isolated_checkout(repository, rename_verifier, revision)
        patch_path = root / "rename.patch"
        patch_path.write_text(rename_patch, encoding="utf-8")
        _git(rename_verifier, "apply", str(patch_path))
        assert not (rename_verifier / "chip/seed.txt").exists()
        assert (rename_verifier / "chip/renamed.txt").read_text(encoding="utf-8") == "renamed content\n"

        task = root / "task.json"
        _write_json(task, {
            "schema": "soc-image.development-task.v1", "id": "fixture", "agent": "FixtureAgent",
            "objective": "Create one verified fixture output through the isolated Agent loop.",
            "base_revision": revision, "owned_paths": ["generated"], "required_outputs": ["generated/result.txt"],
            "source_contexts": [{"repository": "fixture-source", "paths": ["reuse.txt"]}],
            "acceptance_commands": [["python3", "-c", "from pathlib import Path; assert Path('generated/result.txt').read_text() in {'reviewed\\n', 'passed\\n'}"]],
            "max_attempts": 2, "commit_message": "agent: promote fixture task",
        })
        calls = {"developer": 0, "review": 0}
        finding = {"severity": "P1", "file": "generated/result.txt", "line": 1, "detail": "replace the reviewed fixture value"}

        def fake(worktree: Path, prompt: str, output: Path, schema: Path, read_only: bool) -> dict[str, Any]:
            assert (worktree / ".agent-context/fixture-source/reuse.txt").read_text(encoding="utf-8") == "reuse me\n"
            assert "fixture-source" in prompt and "reuse" in prompt.lower()
            if read_only:
                calls["review"] += 1
                bindings = dict(re.findall(r"(task_id|base_revision|patch_sha256)=([a-z0-9_-]+)", prompt))
                report = {
                    **bindings, "verdict": "fail" if calls["review"] == 1 else "pass",
                    "summary": "independent fixture review", "findings": [finding] if calls["review"] == 1 else [],
                }
            else:
                calls["developer"] += 1
                target = worktree / "generated/result.txt"
                target.parent.mkdir(parents=True, exist_ok=True)
                if calls["developer"] == 1:
                    target.write_text("reviewed\n", encoding="utf-8")
                else:
                    assert target.read_text(encoding="utf-8") == "reviewed\n"
                    feedback = json.loads(prompt.rsplit("Previous deterministic failures:\n", 1)[1])
                    assert {"verdict": "fail", "findings": [finding]} in feedback, feedback
                    target.write_text("passed\n", encoding="utf-8")
                report = {"task_id": "fixture", "base_revision": revision, "status": "implemented", "summary": "fixture", "tests": [], "blockers": []}
                assert "Previous deterministic failures" in prompt
            Draft202012Validator(json.loads(schema.read_text(encoding="utf-8"))).validate(report)
            _write_json(output, report)
            return {"ok": True, "report": report, "log": "fixture"}

        report = DevelopmentEngine(task, root / "out", repository=repository, model_runner=fake).run(promote=True)
        assert report["status"] == "passed" and calls == {"developer": 2, "review": 2}, report
        assert (chip / "generated/result.txt").read_text(encoding="utf-8") == "passed\n"
        assert _git(repository, "log", "-1", "--pretty=%s").strip() == "agent: promote fixture task"
        first_patch = root / "out/change-attempt-1.patch"
        second_patch = root / "out/change-attempt-2.patch"
        assert first_patch.is_file() and second_patch.is_file() and first_patch.read_bytes() != second_patch.read_bytes()
        assert _git(repository, "diff", "--binary", revision, "HEAD", "--", "chip/generated/result.txt") == second_patch.read_text(encoding="utf-8")
        assert report["provenance_attempt"] == 2 and report["patch_sha256"] == sha256(second_patch)
        assert report["attempts"][0]["review"]["report"]["findings"] == [finding]
        assert all(attempt["commands"] and attempt["verification_commands"] and attempt["review"] for attempt in report["attempts"])
        assert all((root / f"out/independent-review-attempt-{number}.json").is_file() for number in range(1, 3))
        assert not _git(repository, "config", "--get", "socimage.agent-probe", check=False).strip()
        assert not (repository / "reference-hook-called").exists()

        blocked_task = root / "blocked-task.json"
        blocked_revision = _git(repository, "rev-parse", "HEAD").strip()
        _write_json(blocked_task, {
            "schema": "soc-image.development-task.v1", "id": "blocked", "agent": "FixtureAgent",
            "objective": "Prove that an Agent change outside its owned path is rejected.",
            "base_revision": blocked_revision, "owned_paths": ["allowed"], "required_outputs": ["allowed/result.txt"],
            "source_contexts": [{"repository": "fixture-source", "paths": ["reuse.txt"]}],
            "acceptance_commands": [["python3", "-c", "from pathlib import Path; assert Path('allowed/result.txt').is_file()"]],
            "max_attempts": 1, "commit_message": "agent: reject unauthorized fixture",
        })

        def unauthorized(worktree: Path, prompt: str, output: Path, schema: Path, read_only: bool) -> dict[str, Any]:
            del prompt, read_only
            (worktree / "allowed").mkdir(exist_ok=True)
            (worktree / "allowed/result.txt").write_text("present\n", encoding="utf-8")
            (worktree / "forbidden.txt").write_text("forbidden\n", encoding="utf-8")
            (worktree / ".agent-context/fixture-source/reuse.txt").write_text("copied\n", encoding="utf-8")
            report = {"task_id": "blocked", "base_revision": blocked_revision, "status": "implemented", "summary": "fixture", "tests": [], "blockers": []}
            _write_json(output, report)
            return {"ok": True, "report": report}

        blocked = DevelopmentEngine(blocked_task, root / "blocked-out", repository=repository, model_runner=unauthorized).run(promote=True)
        assert blocked["status"] == "failed" and any(".agent-context" in error for error in blocked["errors"]), blocked
        assert not (chip / "allowed").exists() and not (chip / "forbidden.txt").exists()

        def write_task(name: str, command: list[str], *, attempts: int = 1) -> tuple[Path, str]:
            task_path = root / f"{name}-task.json"
            base = _git(repository, "rev-parse", "HEAD").strip()
            _write_json(task_path, {
                "schema": "soc-image.development-task.v1", "id": name, "agent": "FixtureAgent",
                "objective": f"Exercise the {name} development safety gate.",
                "base_revision": base, "owned_paths": [name], "required_outputs": [f"{name}/result.txt"],
                "acceptance_commands": [command], "max_attempts": attempts,
                "commit_message": f"agent: {name} fixture",
            })
            return task_path, base

        def bound_report(name: str, base: str) -> dict[str, Any]:
            return {"task_id": name, "base_revision": base, "status": "implemented", "summary": "fixture", "tests": [], "blockers": []}

        advisory_task, advisory_base = write_task("advisory-status", ["python3", "-c", "pass"])

        def advisory_status(worktree: Path, prompt: str, output: Path, schema: Path, read_only: bool) -> dict[str, Any]:
            if read_only:
                bindings = dict(re.findall(r"(task_id|base_revision|patch_sha256)=([a-z0-9_-]+)", prompt))
                report = {**bindings, "verdict": "pass", "summary": "review", "findings": []}
            else:
                target = worktree / "advisory-status/result.txt"
                target.parent.mkdir()
                target.write_text("deterministically accepted\n", encoding="utf-8")
                report = {**bound_report("advisory-status", advisory_base), "status": "blocked", "blockers": ["advisory only"]}
            _write_json(output, report)
            return {"ok": True, "report": report}

        advisory_result = DevelopmentEngine(
            advisory_task, root / "advisory-out", repository=repository, model_runner=advisory_status,
        ).run(promote=True)
        assert advisory_result["status"] == "passed" and (chip / "advisory-status/result.txt").is_file(), advisory_result

        repeated_task, repeated_base = write_task("repeated-review", ["python3", "-c", "pass"], attempts=3)
        repeated_calls = {"developer": 0, "review": 0}
        repeated_finding = {"severity": "P2", "file": "repeated-review/result.txt", "line": 1, "detail": "still rejected"}

        def repeated_review(worktree: Path, prompt: str, output: Path, schema: Path, read_only: bool) -> dict[str, Any]:
            if read_only:
                repeated_calls["review"] += 1
                bindings = dict(re.findall(r"(task_id|base_revision|patch_sha256)=([a-z0-9_-]+)", prompt))
                report = {**bindings, "verdict": "fail", "summary": "reject", "findings": [repeated_finding]}
            else:
                repeated_calls["developer"] += 1
                target = worktree / "repeated-review/result.txt"
                target.parent.mkdir(exist_ok=True)
                target.write_text(f"rejected-{repeated_calls['developer']}\n", encoding="utf-8")
                report = bound_report("repeated-review", repeated_base)
            _write_json(output, report)
            return {"ok": True, "report": report}

        repeated_result = DevelopmentEngine(
            repeated_task, root / "repeated-out", repository=repository, model_runner=repeated_review,
        ).run(promote=True)
        assert repeated_result["status"] == "failed" and repeated_calls == {"developer": 3, "review": 3}, repeated_result
        assert len(repeated_result["attempts"]) == 3 and repeated_result["provenance_attempt"] == 3
        assert all((root / f"repeated-out/change-attempt-{number}.patch").is_file() for number in range(1, 4))
        assert all((root / f"repeated-out/independent-review-attempt-{number}.json").is_file() for number in range(1, 4))
        assert not (chip / "repeated-review").exists()

        replay_task, replay_base = write_task("review-replay", ["python3", "-c", "pass"], attempts=2)
        replay_calls = {"developer": 0, "review": 0}

        def review_replay(worktree: Path, prompt: str, output: Path, schema: Path, read_only: bool) -> dict[str, Any]:
            if read_only:
                replay_calls["review"] += 1
                bindings = dict(re.findall(r"(task_id|base_revision|patch_sha256)=([a-z0-9_-]+)", prompt))
                report = {**bindings, "verdict": "fail", "summary": "reject", "findings": [repeated_finding]}
            else:
                replay_calls["developer"] += 1
                target = worktree / "review-replay/result.txt"
                target.parent.mkdir(exist_ok=True)
                target.write_text("same rejected patch\n", encoding="utf-8")
                report = bound_report("review-replay", replay_base)
            _write_json(output, report)
            return {"ok": True, "report": report}

        replay_result = DevelopmentEngine(
            replay_task, root / "replay-out", repository=repository, model_runner=review_replay,
        ).run(promote=True)
        assert replay_result["status"] == "failed" and replay_calls == {"developer": 2, "review": 1}, replay_result
        assert "already rejected" in replay_result["errors"][0]
        assert replay_result["attempts"][1]["review"] is None and not (chip / "review-replay").exists()

        provenance_task, provenance_base = write_task("provenance", ["python3", "-c", "pass"], attempts=2)
        provenance_calls = {"developer": 0, "review": 0}

        def stale_provenance(worktree: Path, prompt: str, output: Path, schema: Path, read_only: bool) -> dict[str, Any]:
            del schema
            if read_only:
                provenance_calls["review"] += 1
                bindings = dict(re.findall(r"(task_id|base_revision|patch_sha256)=([a-z0-9_-]+)", prompt))
                report = {**bindings, "verdict": "fail", "summary": "reject", "findings": [finding]}
            else:
                provenance_calls["developer"] += 1
                if provenance_calls["developer"] == 2:
                    assert finding["detail"] in prompt
                    return {"ok": False, "error": "final developer failure"}
                target = worktree / "provenance/result.txt"
                target.parent.mkdir()
                target.write_text("reviewed\n", encoding="utf-8")
                report = bound_report("provenance", provenance_base)
            _write_json(output, report)
            return {"ok": True, "report": report}

        provenance_out = root / "provenance-out"
        provenance_result = DevelopmentEngine(
            provenance_task, provenance_out, repository=repository, model_runner=stale_provenance,
        ).run()
        assert provenance_result["status"] == "failed" and provenance_calls == {"developer": 2, "review": 1}, provenance_result
        assert provenance_result["patch_sha256"] is None
        assert not {"patch_path", "provenance_attempt", "review", "commands"}.intersection(provenance_result)
        assert provenance_result["attempts"][0]["patch_sha256"] and provenance_result["attempts"][0]["review"]
        assert provenance_result["attempts"][1]["patch_sha256"] is None
        assert provenance_result["attempts"][1]["review"] is None and provenance_result["attempts"][1]["verification_commands"] == []
        assert (provenance_out / "change-attempt-1.patch").is_file()
        assert not (provenance_out / "candidate").exists() and not (provenance_out / "verifier").exists()

        config_task, config_base = write_task("config-tamper", ["python3", "-c", "pass"])

        def change_config(worktree: Path, prompt: str, output: Path, schema: Path, read_only: bool) -> dict[str, Any]:
            del prompt, schema, read_only
            target = worktree / "config-tamper/result.txt"
            target.parent.mkdir()
            target.write_text("ready\n", encoding="utf-8")
            _git(worktree.parent, "config", "core.fsmonitor", "/tmp/untrusted")
            report = bound_report("config-tamper", config_base)
            _write_json(output, report)
            return {"ok": True, "report": report}

        config_result = DevelopmentEngine(config_task, root / "config-out", repository=repository, model_runner=change_config).run()
        assert config_result["status"] == "failed" and "Agent changed isolated Git configuration" in config_result["errors"], config_result

        nondeterministic_task, nondeterministic_base = write_task("nondeterministic", [
            "python3", "-c", "from pathlib import Path; p=Path('nondeterministic/result.txt'); p.write_text(p.read_text()+'x')",
        ])

        def nondeterministic(worktree: Path, prompt: str, output: Path, schema: Path, read_only: bool) -> dict[str, Any]:
            if read_only:
                bindings = dict(re.findall(r"(task_id|base_revision|patch_sha256)=([a-z0-9_-]+)", prompt))
                report = {**bindings, "verdict": "pass", "summary": "review", "findings": []}
            else:
                target = worktree / "nondeterministic/result.txt"
                target.parent.mkdir()
                target.write_text("seed", encoding="utf-8")
                report = bound_report("nondeterministic", nondeterministic_base)
            _write_json(output, report)
            return {"ok": True, "report": report}

        nondeterministic_result = DevelopmentEngine(
            nondeterministic_task, root / "nondeterministic-out", repository=repository, model_runner=nondeterministic,
        ).run()
        assert nondeterministic_result["status"] == "failed"
        assert any("changed verified patch content" in error for error in nondeterministic_result["errors"]), nondeterministic_result
        assert nondeterministic_result["attempts"][0]["review"] is None
        assert not (root / "nondeterministic-out/independent-review-attempt-1.json").exists()

        outside = root / "outside.txt"
        sandbox_task, sandbox_base = write_task("sandbox", [
            "python3", "-c", f"from pathlib import Path; Path({str(outside)!r}).write_text('escaped')",
        ])

        def sandbox_writer(worktree: Path, prompt: str, output: Path, schema: Path, read_only: bool) -> dict[str, Any]:
            del prompt, schema, read_only
            target = worktree / "sandbox/result.txt"
            target.parent.mkdir()
            target.write_text("ready\n", encoding="utf-8")
            report = bound_report("sandbox", sandbox_base)
            _write_json(output, report)
            return {"ok": True, "report": report}

        sandbox_result = DevelopmentEngine(sandbox_task, root / "sandbox-out", repository=repository, model_runner=sandbox_writer).run()
        assert sandbox_result["status"] == "failed" and not outside.exists(), sandbox_result

        stale_task, stale_base = write_task("stale-review", ["python3", "-c", "pass"])

        def stale_review(worktree: Path, prompt: str, output: Path, schema: Path, read_only: bool) -> dict[str, Any]:
            del prompt, schema
            if read_only:
                report = {"task_id": "stale-review", "base_revision": stale_base, "patch_sha256": "0" * 64, "verdict": "pass", "summary": "stale", "findings": []}
            else:
                target = worktree / "stale-review/result.txt"
                target.parent.mkdir()
                target.write_text("ready\n", encoding="utf-8")
                report = bound_report("stale-review", stale_base)
            _write_json(output, report)
            return {"ok": True, "report": report}

        stale_result = DevelopmentEngine(stale_task, root / "stale-out", repository=repository, model_runner=stale_review).run()
        assert stale_result["status"] == "failed" and "independent review binding mismatch" in stale_result["errors"], stale_result

        tamper_task, tamper_base = write_task("git-tamper", ["python3", "-c", "pass"])

        def tamper(worktree: Path, prompt: str, output: Path, schema: Path, read_only: bool) -> dict[str, Any]:
            del prompt, schema, read_only
            target = worktree / "git-tamper/result.txt"
            target.parent.mkdir()
            target.write_text("ready\n", encoding="utf-8")
            marker = worktree.parent / ".git"
            marker.rename(worktree.parent / ".git-hidden")
            marker.write_text("tampered\n", encoding="utf-8")
            report = bound_report("git-tamper", tamper_base)
            _write_json(output, report)
            return {"ok": True, "report": report}

        tamper_result = DevelopmentEngine(tamper_task, root / "tamper-out", repository=repository, model_runner=tamper).run()
        assert tamper_result["status"] == "failed" and any("Git metadata" in error for error in tamper_result["errors"]), tamper_result

        head_task, head_base = write_task("head-tamper", ["python3", "-c", "pass"])

        def move_head(worktree: Path, prompt: str, output: Path, schema: Path, read_only: bool) -> dict[str, Any]:
            del prompt, schema, read_only
            target = worktree / "head-tamper/result.txt"
            target.parent.mkdir()
            target.write_text("ready\n", encoding="utf-8")
            _git(
                worktree.parent, "-c", "user.name=test", "-c", "user.email=test@example.invalid",
                "commit", "--allow-empty", "-q", "-m", "tamper HEAD",
            )
            report = bound_report("head-tamper", head_base)
            _write_json(output, report)
            return {"ok": True, "report": report}

        head_result = DevelopmentEngine(head_task, root / "head-out", repository=repository, model_runner=move_head).run()
        assert head_result["status"] == "failed" and "Agent changed candidate HEAD" in head_result["errors"], head_result

        rollback_task, rollback_base = write_task("rollback", ["python3", "-c", "pass"])

        def promotable(worktree: Path, prompt: str, output: Path, schema: Path, read_only: bool) -> dict[str, Any]:
            if read_only:
                bindings = dict(re.findall(r"(task_id|base_revision|patch_sha256)=([a-z0-9_-]+)", prompt))
                report = {**bindings, "verdict": "pass", "summary": "review", "findings": []}
            else:
                target = worktree / "rollback/result.txt"
                target.parent.mkdir()
                target.write_text("ready\n", encoding="utf-8")
                report = bound_report("rollback", rollback_base)
            _write_json(output, report)
            return {"ok": True, "report": report}

        original_git = globals()["_git"]
        def failing_commit(repo: Path, *args: str, check: bool = True) -> str:
            if "update-ref" in args:
                raise RuntimeError("injected promotion failure")
            return original_git(repo, *args, check=check)
        globals()["_git"] = failing_commit
        try:
            rollback_result = DevelopmentEngine(
                rollback_task, root / "rollback-out", repository=repository, model_runner=promotable,
            ).run(promote=True)
        finally:
            globals()["_git"] = original_git
        assert rollback_result["status"] == "failed" and any("injected promotion failure" in error for error in rollback_result["errors"]), rollback_result
        assert not (chip / "rollback").exists() and not _git(repository, "diff", "--cached", "--", "chip/rollback").strip()

    if not _nested_acceptance():
        reports, errors = _run_commands(
            REPOSITORY,
            [["python3", "-m", "engine.development", "--selftest"]],
            _source_path(REPOSITORY),
        )
        assert not errors, reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    if not args.task or not args.out:
        parser.error("--task and --out are required")
    report = DevelopmentEngine(args.task, args.out).run(promote=args.promote)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

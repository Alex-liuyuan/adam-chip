#!/usr/bin/env python3
"""Enforce ordered, commit-bound implementation phases."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/phase_report.schema.json"
REPORT_SCHEMA = "soc-image.phase-report.v1"


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()


def head_commit() -> str:
    return _git("rev-parse", "HEAD")


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_report(data: dict[str, Any]) -> list[str]:
    errors = sorted(Draft202012Validator(_schema()).iter_errors(data), key=lambda item: list(item.path))
    return [error.message for error in errors]


def report_path(reports_dir: Path, phase: int) -> Path:
    return reports_dir / f"phase-{phase}.json"


def marker_path(reports_dir: Path, phase: int) -> Path:
    return reports_dir / f"phase-{phase}.started.json"


def check_previous(phase: int, reports_dir: Path, current_head: str) -> list[str]:
    if phase == 0:
        return []
    path = report_path(reports_dir, phase - 1)
    if not path.is_file():
        return [f"phase {phase - 1} report is missing: {path}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"phase {phase - 1} report is unreadable: {exc}"]
    errors = validate_report(data)
    if data.get("phase") != phase - 1:
        errors.append(f"expected phase {phase - 1} report")
    if data.get("status") != "passed":
        errors.append(f"phase {phase - 1} did not pass")
    if data.get("next_phase_allowed") != phase:
        errors.append(f"phase {phase - 1} does not authorize phase {phase}")
    if data.get("result_commit") != current_head:
        errors.append("current HEAD does not match the previous phase result_commit")
    return errors


def begin(phase: int, reports_dir: Path, *, current_head: str | None = None) -> dict[str, Any]:
    current_head = current_head or head_commit()
    errors = check_previous(phase, reports_dir, current_head)
    result = {
        "ok": not errors,
        "phase": phase,
        "base_commit": current_head,
        "errors": errors,
    }
    if not errors:
        reports_dir.mkdir(parents=True, exist_ok=True)
        marker_path(reports_dir, phase).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def _artifact(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def complete(
    phase: int,
    reports_dir: Path,
    *,
    status: str,
    commands: list[str],
    tests: list[str],
    artifacts: list[Path],
    blockers: list[str],
) -> dict[str, Any]:
    marker = marker_path(reports_dir, phase)
    if not marker.is_file():
        raise ValueError(f"phase {phase} was not begun: {marker}")
    started = json.loads(marker.read_text(encoding="utf-8"))
    if not started.get("ok"):
        raise ValueError(f"phase {phase} begin gate did not pass")
    result_commit = head_commit()
    base_commit = str(started["base_commit"])
    if status == "passed" and blockers:
        raise ValueError("a passed phase cannot contain blockers")
    if status != "passed" and not blockers:
        raise ValueError("a failed or blocked phase must contain blockers")
    if status == "passed" and _git("status", "--porcelain=v1", "--", "."):
        raise ValueError("chip worktree must be clean before completing a passed phase")
    _git("merge-base", "--is-ancestor", base_commit, result_commit)
    data = {
        "schema": REPORT_SCHEMA,
        "phase": phase,
        "status": status,
        "base_commit": base_commit,
        "result_commit": result_commit,
        "commands": commands,
        "tests": tests,
        "artifacts": [_artifact(path) for path in artifacts],
        "blockers": blockers,
        "next_phase_allowed": phase + 1 if status == "passed" else None,
        "completed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    errors = validate_report(data)
    if errors:
        raise ValueError("; ".join(errors))
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path(reports_dir, phase).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    marker.unlink()
    return data


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        reports = Path(tmp)
        commit0 = "0" * 40
        commit1 = "1" * 40
        assert begin(0, reports, current_head=commit0)["ok"]
        missing = check_previous(1, reports, commit0)
        assert missing and "missing" in missing[0]
        passed = {
            "schema": REPORT_SCHEMA,
            "phase": 0,
            "status": "passed",
            "base_commit": commit0,
            "result_commit": commit1,
            "commands": ["test command"],
            "tests": ["test passed"],
            "artifacts": [],
            "blockers": [],
            "next_phase_allowed": 1,
            "completed_at": "2026-07-31T00:00:00+00:00",
        }
        report_path(reports, 0).write_text(json.dumps(passed), encoding="utf-8")
        assert not check_previous(1, reports, commit1)
        assert check_previous(1, reports, commit0)
        passed["status"] = "failed"
        passed["next_phase_allowed"] = None
        report_path(reports, 0).write_text(json.dumps(passed), encoding="utf-8")
        assert any("did not pass" in error for error in check_previous(1, reports, commit1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    begin_parser = subparsers.add_parser("begin")
    begin_parser.add_argument("--phase", type=int, required=True, choices=range(12))
    begin_parser.add_argument("--reports-dir", default=str(ROOT / "build/phase_reports"))
    complete_parser = subparsers.add_parser("complete")
    complete_parser.add_argument("--phase", type=int, required=True, choices=range(12))
    complete_parser.add_argument("--reports-dir", default=str(ROOT / "build/phase_reports"))
    complete_parser.add_argument("--status", choices=("passed", "failed", "blocked"), required=True)
    complete_parser.add_argument("--command-run", action="append", default=[])
    complete_parser.add_argument("--test", action="append", default=[])
    complete_parser.add_argument("--artifact", action="append", default=[])
    complete_parser.add_argument("--blocker", action="append", default=[])
    subparsers.add_parser("selftest")
    args = parser.parse_args()
    if args.command == "selftest":
        selftest()
        print("ok")
        return 0
    reports_dir = Path(args.reports_dir).resolve()
    if args.command == "begin":
        result = begin(args.phase, reports_dir)
    else:
        result = complete(
            args.phase,
            reports_dir,
            status=args.status,
            commands=args.command_run,
            tests=args.test,
            artifacts=[Path(value).resolve() for value in args.artifact],
            blockers=args.blocker,
        )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok", result.get("status") == "passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())

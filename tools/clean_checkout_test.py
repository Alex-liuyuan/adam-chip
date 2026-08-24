#!/usr/bin/env python3
"""Run strict tests in a detached clean Git worktree."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/bin/python"


def repository_layout() -> tuple[Path, Path]:
    repository = Path(subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout.strip())
    return repository, ROOT.relative_to(repository)


def run(revision: str = "HEAD") -> dict:
    repository, project_path = repository_layout()
    with tempfile.TemporaryDirectory(prefix="soc-image-clean-") as tmp:
        checkout = Path(tmp) / "checkout"
        clone = subprocess.run(
            ["git", "clone", "--no-local", "--no-checkout", str(repository), str(checkout)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if clone.returncode:
            return {"ok": False, "revision": revision, "stage": "clone", "output": clone.stdout}
        selected = subprocess.run(
            ["git", "checkout", "--detach", revision], cwd=checkout, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if selected.returncode:
            return {"ok": False, "revision": revision, "stage": "checkout", "output": selected.stdout}
        proc = subprocess.run(
            [str(PYTHON if PYTHON.is_file() else Path(sys.executable)), "tools/run_strict_tests.py"],
            cwd=checkout / project_path,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "revision": revision,
            "stage": "strict_tests",
            "returncode": proc.returncode,
            "output": proc.stdout,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args()
    report = run(args.revision)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

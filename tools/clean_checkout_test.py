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
REPOSITORY = ROOT.parent
PYTHON = ROOT / ".venv/bin/python"


def run(revision: str = "HEAD") -> dict:
    with tempfile.TemporaryDirectory(prefix="soc-image-clean-") as tmp:
        checkout = Path(tmp) / "checkout"
        add = subprocess.run(
            ["git", "worktree", "add", "--detach", str(checkout), revision],
            cwd=REPOSITORY,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if add.returncode:
            return {"ok": False, "revision": revision, "stage": "worktree_add", "output": add.stdout}
        try:
            proc = subprocess.run(
                [str(PYTHON if PYTHON.is_file() else Path(sys.executable)), "tools/run_strict_tests.py"],
                cwd=checkout / "chip",
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
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(checkout)],
                cwd=REPOSITORY,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args()
    report = run(args.revision)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

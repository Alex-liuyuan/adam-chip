#!/usr/bin/env python3
"""Focused regression gate for the retained SDK image pipeline."""

from __future__ import annotations

import json
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def run(*command: str) -> None:
    proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if proc.returncode:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(command)}\n{proc.stdout}")


def main() -> int:
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py", "*.json"],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, check=True,
    ).stdout.splitlines()
    with tempfile.TemporaryDirectory(prefix="chip-strict-compile-") as compile_dir:
        for index, relative in enumerate(tracked):
            path = ROOT / relative
            if not path.is_file():
                continue
            if path.suffix == ".py":
                py_compile.compile(str(path), cfile=str(Path(compile_dir) / f"{index}.pyc"), doraise=True)
            else:
                json.loads(path.read_text(encoding="utf-8"))

    roles = json.loads((ROOT / "agents/roles.json").read_text(encoding="utf-8"))["roles"]
    assert len(roles) == 8
    for role in roles:
        for action in role["actions"]:
            assert (ROOT / action["tool"]).is_file(), (role["name"], action["id"], action["tool"])

    run(PYTHON, "chip_agents.py", "selftest")
    run(PYTHON, "soc_image.py", "selftest")
    run(PYTHON, "importers/svd_importer.py", "--selftest")
    run(PYTHON, "importers/dts_importer.py", "--selftest")
    run(PYTHON, "tools/phase_gate.py", "selftest")
    run(PYTHON, "tools/reference_artifact.py", "--selftest")
    baseline = json.loads((ROOT / "reference/k230/current_baseline.json").read_text(encoding="utf-8"))
    assert baseline["role"] == "reference_only"
    assert baseline["build_input_allowed"] is False
    assert "build_input" in baseline["prohibited_uses"]
    with tempfile.TemporaryDirectory() as tmp:
        run(PYTHON, "tools/contract_schema_gate.py", "--platform", "canaan_k230", "--out", f"{tmp}/contract")
        run(PYTHON, "tools/project_input_gate.py", "--project", "projects/k230_sdk_project.json", "--out", f"{tmp}/input")
        run(PYTHON, "tools/target_contract_validate.py", "platforms/canaan_k230/target.json", "--out", f"{tmp}/target", "--no-adapt-smoke")
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

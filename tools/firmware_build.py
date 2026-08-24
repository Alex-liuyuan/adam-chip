#!/usr/bin/env python3
"""Dispatch a complete firmware build to the selected platform backend."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.project import load as load_project


def run(project_path: Path, out: Path, *, reuse_existing: bool = False) -> dict:
    project = load_project(project_path)
    config = project.get("firmware")
    if not isinstance(config, dict):
        raise ValueError("project firmware configuration is required")
    backend = importlib.import_module(f"platforms.{project['platform'].replace('-', '_')}.firmware_backend")
    return backend.build(config, out, reuse_existing=reuse_existing)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--out", default=str(ROOT / "build/firmware"))
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args()
    report = run(Path(args.project).resolve(), Path(args.out).resolve(), reuse_existing=bool(args.reuse_existing))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

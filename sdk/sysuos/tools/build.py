#!/usr/bin/env python3
"""Validate an external SoC workspace before invoking its product recipe."""

import json
import subprocess
import sys
from pathlib import Path


pack_path = Path(sys.argv[1]).expanduser().resolve()
root = Path(__file__).resolve().parents[1]
check = subprocess.run(
    [sys.executable, str(Path(__file__).with_name("verify.py")), str(root), str(pack_path)],
    capture_output=True, text=True,
)
if check.returncode:
    raise SystemExit(check.stderr.strip() or check.stdout.strip())
pack = json.loads(pack_path.read_text(encoding="utf-8"))
plan = json.loads((pack_path.parent / pack["adaptation_plan"]).read_text(encoding="utf-8"))
missing = [name for name, provider in pack["providers"].items() if not provider["implementation"]]
if missing:
    tasks = {task["provider"]: task for task in plan["tasks"]}
    detail = ", ".join(f"{name}({tasks[name]['action']})" for name in sorted(missing))
    raise SystemExit("blocked: pending providers: " + detail)
if any(task["status"] != "verified" for task in plan["tasks"]):
    raise SystemExit("blocked: provider implementations exist but adaptation tasks are not independently verified")
if pack["blockers"]:
    raise SystemExit("blocked: unresolved pack blockers: " + "; ".join(pack["blockers"]))
print("provider contracts complete; invoke the product build recipe")

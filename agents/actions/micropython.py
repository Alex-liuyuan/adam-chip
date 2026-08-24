"""Executable MicroPythonAgent workflow."""

from __future__ import annotations

import sys
from pathlib import Path

from agents.actions.common import authorize, blocked, finish, run_action
from agents.project import load as load_project, resolve


AGENT = "MicroPythonAgent"
PYTHON = sys.executable


def run(project_path: Path, out: Path, handoffs: tuple[Path, ...] = ()) -> dict:
    project = load_project(project_path)
    target = resolve(project["target"])
    incoming = tuple(path.resolve() for path in handoffs)
    out = out.resolve()
    errors = authorize(project, target, AGENT, incoming, {("BspBootAgent", "BuildRtThreadBsp")})
    if errors:
        return blocked(project, AGENT, out, errors)
    firmware = out / "01_firmware"
    results = [
        run_action(
            project,
            AGENT,
            "BuildMicroPythonFirmware",
            [PYTHON, "tools/firmware_build.py", "--project", str(project_path.resolve()), "--out", str(firmware)],
            [project_path.resolve(), target, *incoming],
            target,
            firmware,
            ("firmware.img", "firmware_manifest.json", "firmware_build_report.json", "image_analysis/*.json", "build.log"),
        )
    ]
    if not results[-1]["handoff_ready"]:
        return finish(project, AGENT, out, results, 2)
    inspect = out / "02_inspect"
    results.append(
        run_action(
            project,
            AGENT,
            "InspectMicroPythonImage",
            [PYTHON, "tools/firmware_build.py", "--project", str(project_path.resolve()), "--out", str(inspect), "--reuse-existing"],
            [target, firmware / "firmware_manifest.json", Path(results[-1]["result_path"])],
            target,
            inspect,
            ("firmware.img", "firmware_manifest.json", "firmware_build_report.json", "image_analysis/*.json"),
        )
    )
    return finish(project, AGENT, out, results, 2, ["image structure is not physical-board camera, display, or KPU evidence"])

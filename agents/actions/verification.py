"""Executable independent VerificationAgent workflow."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from agents.actions.common import artifact_from_handoffs, authorize, blocked, finish, run_action
from agents.project import load as load_project, resolve


AGENT = "VerificationAgent"
PYTHON = sys.executable


def run(project_path: Path, out: Path, handoffs: tuple[Path, ...] = ()) -> dict:
    project = load_project(project_path)
    target = resolve(project["target"])
    incoming = tuple(path.resolve() for path in handoffs)
    out = out.resolve()
    required = {
        ("DriverAgent", "VerifyDrivers"),
        ("MicroPythonAgent", "InspectMicroPythonImage"),
        ("RtThreadOsAgent", "RunVirtualFirmware"),
    }
    errors = authorize(project, target, AGENT, incoming, required)
    manifest_path = artifact_from_handoffs(incoming, "firmware_manifest.json")
    virtual_report = artifact_from_handoffs(incoming, "virtual_portability_report.json")
    if manifest_path is None:
        errors.append("MicroPython handoff does not contain firmware_manifest.json")
    if virtual_report is None:
        errors.append("RTOS handoff does not contain virtual_portability_report.json")
    if errors:
        return blocked(project, AGENT, out, errors)
    assert manifest_path and virtual_report
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    image = Path(manifest["image"])
    base_image = Path(manifest["base_image"])
    firmware = project["firmware"]
    overlay = resolve(firmware["overlay"])
    product = resolve(firmware["product"])

    results = []
    readback = out / "01_image_readback"
    results.append(
        run_action(
            project,
            AGENT,
            "VerifyProductImage",
            [
                PYTHON,
                "tools/product_image_verify.py",
                "--image",
                str(image),
                "--base-image",
                str(base_image),
                "--overlay",
                str(overlay),
                "--product",
                str(product),
                "--out",
                str(readback),
            ],
            [target, manifest_path, image, base_image, product],
            target,
            readback,
        )
    )
    if not results[-1]["handoff_ready"]:
        return finish(project, AGENT, out, results, 2)
    virtual = out / "02_virtual"
    virtual.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(manifest_path, virtual / "firmware_manifest.json")
    shutil.copyfile(readback / "product_image_verify_report.json", virtual / "product_image_verify_report.json")
    results.append(
        run_action(
            project,
            AGENT,
            "RunVirtualVerification",
            [PYTHON, "tools/sim_verify.py", "--report", str(virtual_report), "--out", str(virtual / "simulation_report.json")],
            [target, virtual_report, Path(results[-1]["result_path"])],
            target,
            virtual,
        )
    )
    return finish(project, AGENT, out, results, 2, ["physical media readback and board HIL require an explicit lab_config"])

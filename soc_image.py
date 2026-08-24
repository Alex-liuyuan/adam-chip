#!/usr/bin/env python3
"""Create and inspect a generic SoC image run from hardware materials only."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from engine.control import Engine, selftest as engine_selftest
from engine.source_discovery_tools import selftest as source_discovery_selftest
from engine.source_export import selftest as source_export_selftest
from engine.evaluation_stack_tools import selftest as evaluation_stack_selftest
from engine.development import selftest as development_selftest
from engine.engineering_agent import selftest as engineering_agent_selftest
from socimage.adaptation import ensure_workspace, inspect_workspace, merge_status, selftest as adaptation_selftest, sync_workspace
from socimage.hardware import derive, load_outputs, selftest as hardware_selftest
from socimage.intake import create_run, selftest as intake_selftest
from socimage import sdk


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="create a run from immutable hardware materials")
    run_parser.add_argument("--material", action="append", required=True)
    run_parser.add_argument("--out", required=True)
    resume_parser = commands.add_parser("resume", help="validate and resume an existing run")
    resume_parser.add_argument("--run", required=True)
    status_parser = commands.add_parser("status", help="show the current run state")
    status_parser.add_argument("--run", required=True)
    commands.add_parser("selftest")
    sdk_parser = commands.add_parser("sdk", help="export and use the SYSUOS source adaptation kit")
    sdk_commands = sdk_parser.add_subparsers(dest="sdk_command", required=True)
    sdk_export = sdk_commands.add_parser("export")
    sdk_export.add_argument("--out", required=True)
    sdk_init = sdk_commands.add_parser("init-soc")
    sdk_init.add_argument("--material", action="append", required=True)
    sdk_init.add_argument("--reference-image")
    sdk_init.add_argument("--soc", required=True)
    sdk_init.add_argument("--board")
    sdk_init.add_argument("--from-soc")
    sdk_init.add_argument("--out", required=True)
    sdk_verify = sdk_commands.add_parser("verify")
    sdk_verify.add_argument("path")
    sdk_verify_pack = sdk_commands.add_parser("verify-pack")
    sdk_verify_pack.add_argument("path")
    sdk_commands.add_parser("selftest")
    args = parser.parse_args()

    try:
        if args.command == "sdk":
            if args.sdk_command == "export":
                result = sdk.export(Path(args.out))
            elif args.sdk_command == "init-soc":
                result = sdk.init_soc(
                    args.soc,
                    [Path(value) for value in args.material],
                    Path(args.out),
                    Path(args.reference_image) if args.reference_image else None,
                    args.board,
                    args.from_soc,
                )
            elif args.sdk_command == "verify":
                result = sdk.verify(Path(args.path))
            elif args.sdk_command == "verify-pack":
                result = sdk.verify_pack(Path(args.path))
            else:
                sdk.selftest()
                print("ok")
                return 0
        elif args.command == "run":
            intake = create_run([Path(value) for value in args.material], Path(args.out))
            hardware = derive(Path(intake["run"])) if intake["ok"] else intake
            if hardware["ok"]:
                workspace = ensure_workspace(Path(intake["run"]))
                if workspace["errors"]:
                    result = workspace
                else:
                    engine = Engine(Path(intake["run"])).run_tasks()
                    result = merge_status(engine, sync_workspace(Path(intake["run"]), engine))
            else:
                result = hardware
        elif args.command == "resume":
            hardware = derive(Path(args.run))
            if hardware["ok"]:
                workspace = ensure_workspace(Path(args.run))
                if workspace["errors"]:
                    result = workspace
                else:
                    engine = Engine(Path(args.run)).run_tasks(recover=True)
                    result = merge_status(engine, sync_workspace(Path(args.run), engine))
            else:
                result = hardware
        elif args.command == "status":
            hardware = load_outputs(Path(args.run))
            if hardware["ok"] and (Path(args.run) / "state.db").is_file():
                result = merge_status(Engine(Path(args.run)).status(), inspect_workspace(Path(args.run)))
            else:
                result = hardware
        else:
            intake_selftest()
            hardware_selftest()
            engine_selftest()
            source_discovery_selftest()
            source_export_selftest()
            evaluation_stack_selftest()
            development_selftest()
            engineering_agent_selftest()
            sdk.selftest()
            adaptation_selftest()
            print("ok")
            return 0
    except (OSError, ValueError, RuntimeError, sqlite3.DatabaseError, json.JSONDecodeError) as exc:
        result = {"ok": False, "status": "blocked", "errors": [str(exc)]}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

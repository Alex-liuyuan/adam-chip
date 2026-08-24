#!/usr/bin/env python3
"""Import PlatformIO project metadata into a target contract draft."""

from __future__ import annotations

import argparse
import configparser
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from importers.common import report, write_json


def infer_isa(value: str) -> str:
    match = re.search(r"rv(32|64)[a-z0-9_]*", value.lower())
    return match.group(0) if match else ""


def import_platformio(path: Path, out: Path) -> dict[str, Any]:
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")
    target: dict[str, Any] = {"hardware_specs": {"platformio": str(path)}}
    observations: list[dict[str, Any]] = []
    sections = [name for name in cfg.sections() if name.startswith("env:")]
    if sections:
        section = cfg[sections[0]]
        board = section.get("board", sections[0].split(":", 1)[1])
        mcu = section.get("board_build.mcu", "")
        upload = section.get("upload_protocol", "")
        target["name"] = board.replace("-", "_")
        isa = infer_isa(mcu)
        if isa:
            target["isa"] = isa
        if upload:
            target["firmware"] = {"image": f"build/{target['name']}/firmware.bin", "download": {"command": upload}}
        observations.append({"section": sections[0], "board": board, "mcu": mcu, "upload_protocol": upload})
    result = report(path, target, observations, "platformio_import_pass")
    write_json(out / "target.draft.json", result)
    return result


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "platformio.ini"
        source.write_text(
            "[env:demo]\nplatform = riscv\nboard = demo-board\nboard_build.mcu = rv64gcv\nupload_protocol = custom\n",
            encoding="utf-8",
        )
        result = import_platformio(source, root / "out")
        assert result["target"]["name"] == "demo_board", result
        assert result["target"]["isa"] == "rv64gcv", result
        assert result["target"]["firmware"]["download"]["command"] == "custom", result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="source")
    parser.add_argument("--out", default=str(ROOT / "build/import_platformio"))
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    if not args.source:
        parser.error("--in is required unless --selftest is used")
    result = import_platformio(Path(args.source).resolve(), Path(args.out).resolve())
    print(__import__("json").dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

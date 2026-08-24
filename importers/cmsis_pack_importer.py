#!/usr/bin/env python3
"""Import CMSIS-Pack PDSC device metadata into a target contract draft."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from importers.common import report, write_json


def strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1]


def first_device(root: ET.Element) -> ET.Element | None:
    for node in root.iter():
        if strip_ns(node.tag) == "device":
            return node
    return None


def infer_isa(core: str) -> str:
    match = re.search(r"rv(32|64)[a-z0-9_]*", core.lower())
    return match.group(0) if match else ""


def import_cmsis_pack(path: Path, out: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    device = first_device(root)
    target: dict[str, Any] = {"hardware_specs": {"cmsis_pack": str(path)}}
    observations: list[dict[str, Any]] = []
    if device is not None:
        target["name"] = device.attrib.get("Dname", path.stem).replace("-", "_")
        vendor = device.attrib.get("Dvendor")
        if vendor:
            target["vendor"] = vendor
        for node in device.iter():
            if strip_ns(node.tag) != "processor":
                continue
            core = node.attrib.get("Dcore", "")
            isa = infer_isa(core)
            observations.append({"processor": node.attrib})
            if isa:
                target["isa"] = isa
    result = report(path, target, observations, "cmsis_pack_import_pass")
    write_json(out / "target.draft.json", result)
    return result


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "demo.pdsc"
        source.write_text(
            '<package><devices><family Dfamily="demo"><device Dname="demo-board" Dvendor="ADAM">'
            '<processor Dcore="RV64GCV"/></device></family></devices></package>',
            encoding="utf-8",
        )
        result = import_cmsis_pack(source, root / "out")
        assert result["target"]["name"] == "demo_board", result
        assert result["target"]["isa"] == "rv64gcv", result
        assert "abi" in result["missing_required_fields"], result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="source")
    parser.add_argument("--out", default=str(ROOT / "build/import_cmsis_pack"))
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    if not args.source:
        parser.error("--in is required unless --selftest is used")
    result = import_cmsis_pack(Path(args.source).resolve(), Path(args.out).resolve())
    print(__import__("json").dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Inspect a platform firmware ELF with its pinned cross binutils."""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run(command: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return proc.returncode == 0, proc.stdout


def inspect(platform: str, elf: Path, prefix: str, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    backend = importlib.import_module(f"platforms.{platform.replace('-', '_')}.bsp_backend")
    required = list(getattr(backend, "SOURCE_SPEC", {}).get("required_symbols", []))
    readelf_ok, header = run([prefix + "readelf", "-h", str(elf)])
    nm_ok, symbols = run([prefix + "nm", str(elf)])
    objdump_ok, sections = run([prefix + "objdump", "-h", str(elf)])
    missing = [name for name in required if name not in symbols]
    entry = ""
    for line in header.splitlines():
        if "Entry point address:" in line:
            entry = line.split(":", 1)[1].strip()
    report = {
        "schema": "adam.elf_inspection.v1",
        "ok": bool(readelf_ok and nm_ok and objdump_ok and entry not in {"", "0x0"} and not missing),
        "elf": str(elf),
        "entry": entry,
        "required_symbols": required,
        "missing_symbols": missing,
        "section_count": sum(1 for line in sections.splitlines() if line.strip()[:1].isdigit()),
        "evidence": {
            "entry_point_pass": bool(readelf_ok and entry not in {"", "0x0"}),
            "driver_stack_link_pass": bool(nm_ok and not missing),
        },
    }
    (out / "elf_inspection_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--elf", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        assert run(["true"])[0]
        print("ok")
        return 0
    report = inspect(args.platform, Path(args.elf).resolve(), args.prefix, Path(args.out).resolve())
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

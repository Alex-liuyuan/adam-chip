#!/usr/bin/env python3
"""Build a platform boot chain through its plugin backend."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build(platform: str, out: Path, cross_prefix: str, jobs: int) -> dict:
    try:
        backend = importlib.import_module(f"platforms.{platform.replace('-', '_')}.boot_backend")
    except ModuleNotFoundError:
        return {"ok": False, "platform": platform, "blockers": ["platform has no boot backend"]}
    builder = getattr(backend, "build_boot_chain", None)
    if not callable(builder):
        return {"ok": False, "platform": platform, "blockers": ["platform does not provide build_boot_chain()"]}
    report = builder(out, cross_prefix, jobs)
    report["platform"] = platform
    report.setdefault("evidence", {})["boot_chain_build_pass"] = bool(report.get("ok"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "boot_build_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = build("example_riscv_board", Path(tmp), "missing-cross-prefix-", 1)
        assert not report["ok"] and report["blockers"], report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default="canaan_k230")
    parser.add_argument("--out", default=str(ROOT / "build/boot"))
    parser.add_argument("--cross-prefix", default="")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    report = build(args.platform, Path(args.out).resolve(), args.cross_prefix, args.jobs)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

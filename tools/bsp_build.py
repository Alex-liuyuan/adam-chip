#!/usr/bin/env python3
"""Build an RT-Thread BSP through a platform plugin."""

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


def build(platform: str, out: Path, toolchain: Path | None, jobs: int) -> dict:
    try:
        backend = importlib.import_module(f"platforms.{platform.replace('-', '_')}.bsp_backend")
    except ModuleNotFoundError:
        return {"ok": False, "platform": platform, "blockers": ["platform has no BSP backend"]}
    builder = getattr(backend, "build_source", None)
    if not callable(builder):
        return {"ok": False, "platform": platform, "blockers": ["platform does not provide build_source()"]}
    report = builder(out, toolchain, jobs)
    report["platform"] = platform
    report["agent"] = "BspBootAgent"
    report["action"] = "BuildRtThreadBsp"
    report["third_party_inputs"] = ["rt-thread", "k230-sdk", "k230-toolchain"] if platform == "canaan_k230" else ["rt-thread"]
    return report


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = build("example_riscv_board", Path(tmp), None, 1)
        assert not report["ok"] and report["blockers"], report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default="canaan_k230")
    parser.add_argument("--out", default=str(ROOT / "build/bsp"))
    parser.add_argument("--toolchain-bin")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    report = build(args.platform, Path(args.out).resolve(), Path(args.toolchain_bin).resolve() if args.toolchain_bin else None, args.jobs)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

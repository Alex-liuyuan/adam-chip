#!/usr/bin/env python3
"""Verify virtual-board simulation evidence."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim import evidence


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good = root / "good.json"
        good.write_text(json.dumps({"ok": True}), encoding="utf-8")
        assert evidence.verify_files([good])["ok"]
        bad_claim = root / "bad_claim.json"
        bad_claim.write_text(json.dumps({"ok": True, "board_verified": True}), encoding="utf-8")
        assert not evidence.verify_files([bad_claim])["ok"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="append", default=[])
    parser.add_argument("--out")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    if not args.report:
        parser.error("--report is required unless --selftest is used")
    report = evidence.verify_files([Path(item).resolve() for item in args.report])
    if args.out:
        Path(args.out).resolve().write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

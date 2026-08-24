#!/usr/bin/env python3
"""Validate the RT-Thread configuration required by RVAIC services."""

import argparse
import json
import re
from pathlib import Path


REQUIRED = ("RT_USING_HEAP", "RT_USING_TIMER_SOFT", "RT_USING_EVENT", "RT_USING_MUTEX", "RT_USING_MESSAGEQUEUE", "RT_USING_FINSH")


def check(path: Path, out: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    missing = [name for name in REQUIRED if not re.search(rf"^#define\s+{name}\b", text, re.MULTILINE)]
    single_core = "RT_USING_SMP" not in text and not re.search(r"#define\s+RT_CPUS_NR\s+[2-9]", text)
    report = {"ok": not missing and bool(single_core), "config": str(path), "missing": missing, "evidence": {"rtthread_config_pass": not missing and bool(single_core), "single_core_amp_pass": bool(single_core)}}
    out.mkdir(parents=True, exist_ok=True)
    (out / "rtthread_config_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = check(Path(args.config), Path(args.out))
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run a generic RT-Thread/RVAIC Renode portability test without board claims."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(out: Path) -> dict:
    stale = out / "report.json"
    stale.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run([sys.executable, str(ROOT / "tools/rtthread_firmware.py"), "--boards", "fe310", "--out", tmp, "--timeout", "30"], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        source = Path(tmp) / "report.json"
        raw = json.loads(source.read_text(encoding="utf-8")) if source.is_file() else {}
    evidence = raw.get("evidence", {})
    boards = raw.get("boards", [])
    portability = bool(boards) and all(
        item.get("compile_pass") and item.get("boot_pass") and item.get("rvaic_app_pass") and item.get("lightweight_conv_reference_pass")
        for item in boards
    )
    report = {
        "ok": portability,
        "scope": "generic_rtthread_fe310_portability",
        "simulated_platform": "fe310",
        "evidence": {
            "rtthread_bsp_build_pass": bool(evidence.get("rtthread_bsp_build_pass")),
            "virtual_firmware_portability_pass": portability,
            "finsh_console_pass": bool(evidence.get("finsh_console_pass")),
            "rvaic_rtthread_app_pass": bool(evidence.get("rvaic_rtthread_app_pass")),
        },
        "not_claimed": ["K230 simulation", "physical board boot"],
        "tool_output": proc.stdout[-2000:],
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "virtual_portability_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = run(Path(args.out))
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

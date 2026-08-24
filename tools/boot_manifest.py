#!/usr/bin/env python3
"""Pack boot component evidence from a boot contract."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from boot import manifest


def parse_component(raw: str) -> tuple[str, Path]:
    name, path = raw.split("=", 1)
    return name, Path(path).resolve()


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        contract = root / "boot.json"
        contract.write_text(json.dumps({"schema": "adam.boot.contract.v1", "target": "demo", "required_components": ["spl", "toc_manifest"]}), encoding="utf-8")
        spl = root / "spl.bin"
        spl.write_bytes(b"spl")
        toc = root / "toc.json"
        toc.write_text('{"entries":[]}', encoding="utf-8")
        ok = manifest.pack(contract, root / "out", {"spl": spl, "toc_manifest": toc})
        assert ok["ok"], ok
        assert ok["evidence"]["toc_manifest_parse_pass"], ok
        bad = manifest.pack(contract, root / "bad", {})
        assert not bad["ok"], bad
        assert "missing boot components" in bad["blockers"][0], bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=str(ROOT / "platforms/canaan_k230/boot.json"))
    parser.add_argument("--component", action="append", default=[])
    parser.add_argument("--out", default=str(ROOT / "build/boot_manifest"))
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    report = manifest.pack(Path(args.contract).resolve(), Path(args.out).resolve(), dict(parse_component(item) for item in args.component))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

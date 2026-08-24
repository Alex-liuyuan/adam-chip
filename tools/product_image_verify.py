#!/usr/bin/env python3
"""Read a product overlay back from an image and verify the preserved boot region."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import k230_image_analyze


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(image: Path, offset: int, relative: str) -> bytes:
    proc = subprocess.run(
        ["mtype", "-i", f"{image}@@{offset}", f"::/{relative}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip())
    return proc.stdout


def verify(image: Path, base_image: Path, overlay: Path, product: Path, out: Path, *, partition_index: int = 2) -> dict[str, Any]:
    image = image.resolve()
    base_image = base_image.resolve()
    overlay = overlay.resolve()
    product_data = json.loads(product.read_text(encoding="utf-8"))
    analysis = k230_image_analyze.analyze(image, out / "analysis")
    base = k230_image_analyze.analyze(base_image, out / "base_analysis")
    partition = next((item for item in analysis["partitions"] if item["index"] == partition_index), None)
    checks: dict[str, bool] = {}
    errors = []
    if partition is None:
        errors.append(f"partition {partition_index} is missing")
    else:
        for source in sorted(path for path in overlay.rglob("*") if path.is_file()):
            relative = source.relative_to(overlay).as_posix()
            try:
                checks[relative] = _digest(_read(image, partition["offset_bytes"], relative)) == _digest(source.read_bytes())
            except RuntimeError as exc:
                checks[relative] = False
                errors.append(f"{relative}: {exc}")
    entrypoint = str(product_data.get("entrypoint", ""))
    evidence = {
        "boot_region_preserved": analysis["pre_partition_boot_region"]["sha256"] == base["pre_partition_boot_region"]["sha256"],
        "overlay_readback_pass": bool(checks) and all(checks.values()),
        "product_entrypoint_present": bool(entrypoint) and checks.get(entrypoint, False),
        "image_partition_contract_pass": len(analysis["partitions"]) >= 2,
    }
    report = {
        "schema": "sysuos.product_image_verify.v1",
        "ok": all(evidence.values()),
        "image": str(image),
        "base_image": str(base_image),
        "product": str(product.resolve()),
        "checks": checks,
        "errors": errors,
        "evidence": evidence,
        "not_claimed": ["image readback is not physical media readback or board boot evidence"],
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "product_image_verify_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        base = root / "base.img"
        base.write_bytes(b"\0" * (512 * 8192))
        with base.open("r+b") as handle:
            handle.seek(510)
            handle.write(b"\x55\xaa")
            handle.seek(446 + 4)
            handle.write(b"\x83")
            handle.seek(446 + 8)
            handle.write((64).to_bytes(4, "little") + (512).to_bytes(4, "little"))
            handle.seek(462 + 4)
            handle.write(b"\x0c")
            handle.seek(462 + 8)
            handle.write((2048).to_bytes(4, "little") + (4096).to_bytes(4, "little"))
        image = root / "product.img"
        image.write_bytes(base.read_bytes())
        spec = f"{image}@@{2048 * 512}"
        subprocess.run(["mformat", "-i", spec, "::"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        overlay = root / "overlay"
        (overlay / "apps").mkdir(parents=True)
        (overlay / "apps/smoke.py").write_text("print('ok')\n", encoding="utf-8")
        subprocess.run(["mcopy", "-i", spec, "-s", str(overlay / "apps"), "::/"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        product = root / "product.json"
        product.write_text(json.dumps({"entrypoint": "apps/smoke.py"}), encoding="utf-8")
        report = verify(image, base, overlay, product, root / "out")
        assert report["ok"], report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image")
    parser.add_argument("--base-image")
    parser.add_argument("--overlay")
    parser.add_argument("--product")
    parser.add_argument("--out", default=str(ROOT / "build/product_image_verify"))
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    if not all((args.image, args.base_image, args.overlay, args.product)):
        parser.error("--image, --base-image, --overlay and --product are required")
    report = verify(Path(args.image), Path(args.base_image), Path(args.overlay), Path(args.product), Path(args.out))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

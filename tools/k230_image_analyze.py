#!/usr/bin/env python3
"""Analyze a K230 SD-card image into a project-consumable layout manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SECTOR = 512


def digest(path: Path, algo: str = "sha256", *, offset: int = 0, size: int | None = None) -> str:
    h = hashlib.new(algo)
    remaining = size
    with path.open("rb") as f:
        f.seek(offset)
        while remaining is None or remaining > 0:
            chunk_size = 1024 * 1024 if remaining is None else min(1024 * 1024, remaining)
            data = f.read(chunk_size)
            if not data:
                break
            h.update(data)
            if remaining is not None:
                remaining -= len(data)
    return h.hexdigest()


def parse_mbr(image: Path) -> list[dict[str, Any]]:
    mbr = image.read_bytes()[:SECTOR]
    if len(mbr) < SECTOR or mbr[510:512] != b"\x55\xaa":
        raise ValueError("image does not contain a valid DOS/MBR signature")
    parts = []
    for idx in range(4):
        entry = mbr[446 + idx * 16 : 446 + (idx + 1) * 16]
        ptype = entry[4]
        start = int.from_bytes(entry[8:12], "little")
        sectors = int.from_bytes(entry[12:16], "little")
        if ptype == 0 or sectors == 0:
            continue
        parts.append(
            {
                "index": idx + 1,
                "type_hex": f"0x{ptype:02x}",
                "bootable": entry[0] == 0x80,
                "start_lba": start,
                "sectors": sectors,
                "offset_bytes": start * SECTOR,
                "size_bytes": sectors * SECTOR,
            }
        )
    return parts


def summarize_tree(root: Path, *, limit: int = 120) -> dict[str, Any]:
    files = []
    total = 0
    counts = {"files": 0, "kmodel": 0, "python": 0, "json": 0}
    for item in sorted(root.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(root).as_posix()
        size = item.stat().st_size
        total += size
        counts["files"] += 1
        suffix = item.suffix.lower()
        if suffix == ".kmodel":
            counts["kmodel"] += 1
        elif suffix == ".py":
            counts["python"] += 1
        elif suffix == ".json":
            counts["json"] += 1
        if len(files) < limit:
            files.append({"path": rel, "size": size})
    return {"root": str(root), "total_file_bytes": total, "counts": counts, "sample_files": files}


def parse_partition_root(value: str) -> tuple[int, Path]:
    idx, raw = value.split("=", 1)
    return int(idx), Path(raw).resolve()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def image_contains(image: Path, needle: str, *, offset: int, size: int) -> bool:
    raw = needle.encode("utf-8")
    overlap = max(len(raw) - 1, 0)
    with image.open("rb") as f:
        f.seek(offset)
        remaining = size
        tail = b""
        while remaining > 0:
            chunk = f.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            if raw in tail + chunk:
                return True
            tail = (tail + chunk)[-overlap:] if overlap else b""
            remaining -= len(chunk)
    return False


def partition_by_index(parts: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    return next((item for item in parts if int(item["index"]) == int(index)), None)


def validate_contract(
    image: Path,
    report: dict[str, Any],
    roots: dict[int, Path],
    contract: dict[str, Any],
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    failures: list[str] = []
    checks["sector_bytes"] = int(report["sector_bytes"]) == int(contract.get("sector_bytes", SECTOR))
    checks["image_size_bytes"] = int(report["image_size_bytes"]) == int(contract.get("image_size_bytes", report["image_size_bytes"]))
    pre = contract.get("pre_partition_boot_region", {})
    if pre:
        checks["boot_region_size"] = int(report["pre_partition_boot_region"]["size_bytes"]) == int(pre.get("size_bytes", -1))
        expected_hash = str(pre.get("sha256", ""))
        checks["boot_region_sha256"] = bool(expected_hash) and report["pre_partition_boot_region"]["sha256"] == expected_hash
        for item in pre.get("required_strings", []):
            key = "boot_string_" + "".join(ch if ch.isalnum() else "_" for ch in str(item)).strip("_").lower()
            checks[key] = image_contains(image, str(item), offset=0, size=int(report["pre_partition_boot_region"]["size_bytes"]))
    expected_parts = contract.get("partitions", [])
    checks["partition_count"] = len(report["partitions"]) >= len(expected_parts)
    for expected in expected_parts:
        idx = int(expected["index"])
        part = partition_by_index(report["partitions"], idx)
        prefix = f"partition_{idx}"
        checks[f"{prefix}_present"] = part is not None
        if not part:
            continue
        for key in ("type_hex", "start_lba", "sectors"):
            if key in expected:
                checks[f"{prefix}_{key}"] = part[key] == expected[key]
        root = roots.get(idx)
        if not root:
            checks[f"{prefix}_filesystem_root_provided"] = False
            continue
        checks[f"{prefix}_filesystem_root_provided"] = root.exists()
        for rel in expected.get("required_files", []):
            checks[f"{prefix}_file_{rel.replace('/', '_')}"] = (root / rel).is_file()
        for rel in expected.get("required_dirs", []):
            checks[f"{prefix}_dir_{rel.replace('/', '_')}"] = (root / rel).is_dir()
        names = [item.name for item in root.rglob("*") if item.is_file()]
        for fragment in expected.get("required_name_fragments", []):
            checks[f"{prefix}_name_fragment_{fragment}"] = any(str(fragment) in name for name in names)
        summary = report.get("filesystem", {}).get(str(idx), {})
        counts = summary.get("counts", {})
        if "min_json_files" in expected:
            checks[f"{prefix}_min_json_files"] = int(counts.get("json", 0)) >= int(expected["min_json_files"])
        if "min_python_files" in expected:
            checks[f"{prefix}_min_python_files"] = int(counts.get("python", 0)) >= int(expected["min_python_files"])
        if "min_kmodel_files" in expected:
            checks[f"{prefix}_min_kmodel_files"] = int(counts.get("kmodel", 0)) >= int(expected["min_kmodel_files"])
    for key, ok in checks.items():
        if not ok:
            failures.append(key)
    return {
        "schema": contract.get("schema", "adam.k230.image_contract.v1"),
        "board": contract.get("board", ""),
        "ok": not failures,
        "checks": checks,
        "failures": failures,
        "not_claimed": contract.get("not_claimed", []),
    }


def analyze(
    image: Path,
    out: Path,
    roots: list[tuple[int, Path]] | None = None,
    contract: Path | None = None,
) -> dict[str, Any]:
    image = image.resolve()
    out.mkdir(parents=True, exist_ok=True)
    parts = parse_mbr(image)
    first_lba = min((p["start_lba"] for p in parts), default=0)
    pre_bytes = first_lba * SECTOR
    partitions = []
    for part in parts:
        partitions.append(
            {
                **part,
                "sha256": digest(image, offset=part["offset_bytes"], size=part["size_bytes"]),
            }
        )
    root_map = dict(roots or [])
    filesystem = {str(idx): summarize_tree(path) for idx, path in root_map.items() if path.exists()}
    report = {
        "ok": True,
        "image": str(image),
        "image_size_bytes": image.stat().st_size,
        "image_md5": digest(image, "md5"),
        "image_sha256": digest(image),
        "sector_bytes": SECTOR,
        "partitions": partitions,
        "pre_partition_boot_region": {
            "size_bytes": pre_bytes,
            "sha256": digest(image, offset=0, size=pre_bytes) if pre_bytes else "",
            "required_for_boot": pre_bytes > 0,
        },
        "filesystem": filesystem,
        "derived_project_requirements": {
            "raw_boot_region_composer_required": pre_bytes > 0,
            "fat_partition_composer_required": any(p["type_hex"] == "0x0c" for p in parts),
            "sdcard_image_required": len(parts) >= 2,
            "kmodel_runtime_present": any(fs["counts"]["kmodel"] > 0 for fs in filesystem.values()),
            "micropython_examples_present": any(fs["counts"]["python"] > 0 for fs in filesystem.values()),
        },
        "evidence": {
            "mbr_signature_pass": bool(parts),
            "partition_layout_pass": len(parts) >= 2,
            "micropython_image_layout_pass": len(parts) >= 2 and pre_bytes > 0,
        },
        "not_claimed": [
            "This is structural analysis, not project ownership of the boot chain.",
            "A derived image must preserve or replace the raw boot region before it can boot.",
        ],
    }
    if contract:
        report["contract"] = validate_contract(image, report, root_map, load_json(contract))
        report["ok"] = bool(report["ok"] and report["contract"]["ok"])
    (out / "k230_image_analysis.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        image = root / "mini.img"
        data = bytearray(SECTOR * 20)
        data[510:512] = b"\x55\xaa"
        entry = bytearray(16)
        entry[4] = 0x0C
        entry[8:12] = (4).to_bytes(4, "little")
        entry[12:16] = (8).to_bytes(4, "little")
        data[446:462] = entry
        image.write_bytes(data)
        fs = root / "p1"
        fs.mkdir()
        (fs / "main.py").write_text("print('ok')\n", encoding="utf-8")
        report = analyze(image, root / "out", [(1, fs)])
        assert report["partitions"][0]["start_lba"] == 4
        assert report["pre_partition_boot_region"]["size_bytes"] == 2048
        assert report["filesystem"]["1"]["counts"]["python"] == 1
        contract = root / "contract.json"
        contract.write_text(
            json.dumps(
                {
                    "sector_bytes": SECTOR,
                    "image_size_bytes": len(data),
                    "pre_partition_boot_region": {"size_bytes": 2048, "sha256": digest(image, offset=0, size=2048)},
                    "partitions": [{"index": 1, "type_hex": "0x0c", "start_lba": 4, "sectors": 8, "required_files": ["main.py"], "min_python_files": 1}],
                }
            ),
            encoding="utf-8",
        )
        checked = analyze(image, root / "checked", [(1, fs)], contract)
        assert checked["contract"]["ok"], checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=False)
    parser.add_argument("--out", default=str(ROOT / "build/k230_image_analysis"))
    parser.add_argument("--partition-root", action="append", default=[], help="optional mounted partition root, e.g. 1=/mnt/p1")
    parser.add_argument("--contract", help="optional K230 image contract JSON")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    if not args.image:
        parser.error("--image is required unless --selftest is used")
    roots = [parse_partition_root(item) for item in args.partition_root]
    report = analyze(Path(args.image), Path(args.out), roots, Path(args.contract).resolve() if args.contract else None)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Index hardware documents without promoting extracted text to contract facts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


ADDRESS = re.compile(r"\b0x[0-9a-fA-F]{6,16}\b")
KEYWORDS = re.compile(r"\b(?:IRQ|interrupt|DDR|SRAM|UART|DMA|NPU|KPU|clock|reset|boot)\b", re.I)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(path: Path, out: Path) -> tuple[str, str]:
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="ignore"), "text"
    tool = shutil.which("pdftotext")
    if not tool:
        raise RuntimeError("pdftotext is required to ingest PDF hardware documents")
    text_path = out / f"{path.stem}.txt"
    proc = subprocess.run([tool, "-layout", str(path), str(text_path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if proc.returncode != 0 or not text_path.exists():
        raise RuntimeError(f"pdftotext failed for {path}: {proc.stdout.strip()}")
    return text_path.read_text(encoding="utf-8", errors="ignore"), "pdftotext"


def ingest(inputs: list[Path], out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    documents = []
    for path in inputs:
        text, extractor = extract(path, out)
        candidate_lines = [line.strip() for line in text.splitlines() if ADDRESS.search(line) or KEYWORDS.search(line)]
        documents.append(
            {
                "path": str(path),
                "sha256": sha256(path),
                "extractor": extractor,
                "text_characters": len(text),
                "candidate_observations": candidate_lines[:500],
            }
        )
    report = {
        "schema": "adam.hardware_document_index.v1",
        "ok": bool(documents) and all(item["text_characters"] > 0 for item in documents),
        "documents": documents,
        "unknown_fields": ["candidate observations require authoritative semantic confirmation before contract merge"],
        "evidence": {
            "hardware_document_index_pass": bool(documents) and all(item["text_characters"] > 0 for item in documents),
            "field_provenance_recorded": bool(documents),
        },
        "not_claimed": ["text extraction is not register, interrupt, DDR, or boot semantic validation"],
    }
    (out / "hardware_document_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "trm.txt"
        source.write_text("UART base 0x10000000 IRQ 5\n", encoding="utf-8")
        report = ingest([source], root / "out")
        assert report["ok"]
        assert report["documents"][0]["candidate_observations"]
        assert report["not_claimed"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--out", default="build/hardware_documents")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        _self_test()
        print("ok")
        return 0
    if not args.input:
        parser.error("at least one --input is required")
    report = ingest([Path(item).resolve() for item in args.input], Path(args.out).resolve())
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Extract deterministic SoC image MBR partitions without external tools."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import tarfile
from pathlib import Path, PurePosixPath


NAMES = ("boot", "system", "ai", "product")


def unpack(image: Path, output: Path) -> dict[str, object]:
    data = image.read_bytes()
    if len(data) < 512 or data[510:512] != b"\x55\xaa":
        raise ValueError("invalid MBR signature")
    files = []
    ranges = []
    for index, name in enumerate(NAMES):
        entry = data[446 + index * 16:462 + index * 16]
        _, _, kind, _, start, sectors = struct.unpack("<B3sB3sII", entry)
        if kind != 0xDA or not start or not sectors:
            raise ValueError(f"invalid {name} partition entry")
        begin, end = start * 512, (start + sectors) * 512
        if end > len(data) or any(begin < prior_end and prior_begin < end for prior_begin, prior_end in ranges):
            raise ValueError(f"invalid {name} partition bounds")
        ranges.append((begin, end))
        with tarfile.open(fileobj=io.BytesIO(data[begin:end]), mode="r:") as archive:
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                if not member.isfile() or path.is_absolute() or ".." in path.parts:
                    raise ValueError(f"unsafe archive member: {member.name}")
                content = archive.extractfile(member).read()
                destination = output.joinpath(*path.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
                files.append({"partition": name, "path": member.name, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)})
    result = {"schema": "soc-image.unpack-result.v1", "image_sha256": hashlib.sha256(data).hexdigest(), "files": files}
    output.mkdir(parents=True, exist_ok=True)
    (output / "unpack-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(unpack(args.image, args.out), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Content-addressed artifact helpers for agent execution."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {"path": str(resolved), "sha256": sha256(resolved), "bytes": resolved.stat().st_size}


def collect(root: Path, *, patterns: tuple[str, ...] = ("**/*",), exclude: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    excluded = set(exclude)
    paths = {path for pattern in patterns for path in root.glob(pattern)}
    return [describe(path) for path in sorted(paths) if path.is_file() and path.name not in excluded]


def verify(item: dict[str, Any]) -> bool:
    path = Path(str(item.get("path", "")))
    return path.is_file() and item.get("sha256") == sha256(path) and item.get("bytes") == path.stat().st_size

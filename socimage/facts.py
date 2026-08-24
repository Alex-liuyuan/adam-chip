"""Provenance-bearing hardware fact helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


SAFE_STATES = {"authoritative", "standard_derived", "board_observed"}
ALL_STATES = SAFE_STATES | {"candidate", "unknown", "conflict"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source(path: Path, locator: str, *, page: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "document": path.name,
        "sha256": sha256(path),
        "locator": locator,
    }
    if page is not None:
        result["page"] = page
    return result


def fact(
    value: Any,
    path: Path,
    locator: str,
    *,
    state: str = "authoritative",
    unit: str = "",
    constraints: list[str] | None = None,
    page: int | None = None,
) -> dict[str, Any]:
    if state not in ALL_STATES:
        raise ValueError(f"invalid hardware fact state: {state}")
    result = {
        "value": value,
        "state": state,
        "sources": [source(path, locator, page=page)],
        "constraints": list(constraints or []),
    }
    if unit:
        result["unit"] = unit
    return result


def is_fact(value: Any) -> bool:
    return isinstance(value, dict) and {"value", "state", "sources", "constraints"} <= set(value)


def is_safe(value: Any) -> bool:
    return is_fact(value) and value["state"] in SAFE_STATES

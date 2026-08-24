"""K230 boot contract backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import contract_path


def contract() -> Path:
    return contract_path("boot")


def build_boot_chain(out: Path, cross_prefix: str, jobs: int = 1) -> dict[str, Any]:
    from boot import u_boot

    return u_boot.build(Path(__file__).resolve().parents[2], contract(), out, cross_prefix, jobs)

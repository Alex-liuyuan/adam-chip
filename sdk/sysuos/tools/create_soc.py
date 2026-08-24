#!/usr/bin/env python3
"""Create an external SoC adaptation workspace from hardware materials."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ("boot", "device", "media", "accelerator", "image")
STABLE_COMPONENTS = ("micropython", "sysu_compat", "rt_ai", "compiler_runtime")
KIND_BY_SUFFIX = {
    ".pdf": "document", ".txt": "document", ".md": "document", ".doc": "document", ".docx": "document",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".svd": "svd", ".dts": "dts", ".dtsi": "dts",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "material"


def load_base(name: str | None) -> tuple[dict | None, dict | None]:
    if name is None:
        return None, None
    path = ROOT / "soc" / name / "pack.json"
    if not path.is_file():
        raise ValueError(f"base SoC pack is unavailable: {name}")
    return json.loads(path.read_text(encoding="utf-8")), {"soc": name, "pack_sha256": sha256(path)}


def inspect_materials(values: list[str]) -> list[tuple[Path, dict]]:
    found: dict[str, tuple[Path, dict]] = {}
    for value in values:
        path = Path(value).expanduser().resolve()
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"invalid hardware material: {path}")
        digest = sha256(path)
        name = safe_name(path.name)
        item = {
            "name": name,
            "kind": KIND_BY_SUFFIX.get(path.suffix.lower(), "unknown"),
            "stored_path": f"materials/{digest[:16]}-{name}",
            "sha256": digest,
            "bytes": path.stat().st_size,
        }
        found.setdefault(digest, (path, item))
    if not found:
        raise ValueError("at least one hardware material is required")
    return [found[key] for key in sorted(found)]


def create(
    soc: str,
    board: str,
    out: Path,
    materials: list[str],
    base_soc: str | None,
    reference_image: str | None,
) -> Path:
    identifier = re.compile(r"^[A-Za-z0-9_-]+$")
    if not identifier.fullmatch(soc) or not identifier.fullmatch(board):
        raise ValueError("SoC and board names may contain only letters, digits, '_' and '-'")
    out = out.expanduser().resolve()
    if out == ROOT or out.is_relative_to(ROOT):
        raise ValueError("SoC workspaces must be outside the immutable SDK")
    if out.exists():
        raise ValueError(f"workspace already exists: {out}")
    inspected = inspect_materials(materials)
    base_pack, base_identity = load_base(base_soc)
    reference = None
    if reference_image:
        image = Path(reference_image).expanduser().resolve()
        if image.is_symlink() or not image.is_file():
            raise ValueError(f"invalid reference image: {image}")
        reference = {"name": image.name, "sha256": sha256(image), "bytes": image.stat().st_size, "observations": []}
    providers = {
        name: {"contract": f"contracts/{name}_provider.schema.json", "replacement_required": True, "implementation": None}
        for name in PROVIDERS
    }
    tasks = []
    for name in PROVIDERS:
        base_implementation = base_pack["providers"][name]["implementation"] if base_pack else None
        tasks.append({
            "id": f"provider:{name}", "provider": name, "action": "assess" if base_implementation else "replace",
            "status": "pending", "base_implementation": base_implementation,
            "owned_paths": [f"providers/{name}", f"tests/{name}"],
            "required_outputs": [f"providers/{name}/provider.json", f"tests/{name}/smoke.py"],
        })
    pack = {
        "schema": "sysuos.soc-pack.v1", "soc": soc, "board": board,
        "hardware_materials": [item for _, item in inspected], "reference_image": reference,
        "adaptation_plan": "adaptation.json", "providers": providers, "sources": [], "patches": [], "tests": [],
        "blockers": [f"implement {name} provider" for name in PROVIDERS],
    }
    plan = {
        "schema": "sysuos.adaptation-plan.v1", "soc": soc, "board": board, "base": base_identity,
        "stable_components": list(STABLE_COMPONENTS), "tasks": tasks,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.soc-", dir=out.parent))
    try:
        (staging / "materials").mkdir()
        for source, item in inspected:
            destination = staging / item["stored_path"]
            shutil.copyfile(source, destination)
            if destination.stat().st_size != item["bytes"] or sha256(destination) != item["sha256"]:
                raise RuntimeError(f"material copy verification failed: {source}")
        (staging / "pack.json").write_text(json.dumps(pack, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (staging / "adaptation.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        check = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("verify.py")), str(ROOT), str(staging / "pack.json")],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if check.returncode:
            raise ValueError(check.stderr.strip() or check.stdout.strip())
        os.replace(staging, out)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return out / "pack.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("soc")
    parser.add_argument("out")
    parser.add_argument("materials", nargs="*")
    parser.add_argument("--material", action="append", default=[])
    parser.add_argument("--board")
    parser.add_argument("--from-soc")
    parser.add_argument("--reference-image")
    args = parser.parse_args()
    try:
        pack = create(
            args.soc,
            args.board or args.soc,
            Path(args.out),
            [*args.materials, *args.material],
            args.from_soc,
            args.reference_image,
        )
        print(json.dumps({"ok": True, "status": "initialized", "pack": str(pack)}, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Load and render editable Agent prompt templates."""

from __future__ import annotations

import json
import os
import string
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPTS = ROOT / "config/agent_prompts.json"
DEFAULT_LOCAL_PROMPTS = ROOT / "config/agent_prompts.local.json"
SCHEMA = "adam.agent_prompts.v1"


def _read(path: Path, *, required: bool) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise ValueError(f"prompt configuration not found: {path}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid prompt configuration {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("prompts"), dict):
        raise ValueError(f"prompt configuration {path} must use schema {SCHEMA} and contain a prompts object")
    return data


def load_prompts(base: Path = DEFAULT_PROMPTS, override: Path | None = None) -> dict[str, dict[str, str]]:
    data = _read(base, required=True)
    configured_override = os.environ.get("ADAM_AGENT_PROMPTS")
    override = Path(configured_override).expanduser() if configured_override else (override or DEFAULT_LOCAL_PROMPTS)
    local = _read(override, required=bool(configured_override))
    prompts = dict(data["prompts"])
    for name, values in local.get("prompts", {}).items():
        current = prompts.get(name, {})
        if not isinstance(current, dict) or not isinstance(values, dict):
            raise ValueError(f"prompt {name!r} must be an object")
        prompts[name] = {**current, **values}
    for name, values in prompts.items():
        if not isinstance(values, dict) or not all(isinstance(values.get(key), str) for key in ("system", "template")):
            raise ValueError(f"prompt {name!r} requires string system and template fields")
    return prompts


def render_prompt(name: str, **variables: Any) -> tuple[str, str]:
    prompts = load_prompts()
    if name not in prompts:
        raise ValueError(f"unknown Agent prompt: {name}")
    entry = prompts[name]
    fields = set()
    for value in (entry["system"], entry["template"]):
        fields.update(
            field_name
            for _, field_name, _, _ in string.Formatter().parse(value)
            if field_name is not None
        )
    missing = sorted(fields - variables.keys())
    if missing:
        raise ValueError(f"prompt {name!r} missing variables: {', '.join(missing)}")
    return entry["system"].format_map(variables), entry["template"].format_map(variables)

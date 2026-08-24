#!/usr/bin/env python3
"""Tiny DMXAPI/OpenAI-compatible JSON client for ADAM tools."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://www.dmxapi.cn"
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_CONFIG = ROOT / "config/llm.local.json"
ENV_KEYS = ("ADAM_LLM_API_KEY", "DMXAPI_API_KEY")


def load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()


def _json_config_path() -> Path:
    return Path(os.environ.get("ADAM_LLM_CONFIG", str(DEFAULT_CONFIG))).expanduser()


def _load_json_config(path: Path | None = None) -> tuple[dict[str, Any], str]:
    path = path or _json_config_path()
    if not path.exists():
        return {}, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return {}, "configuration root must be a JSON object"
    return data, ""


def _usable_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or value in {"...", "PUT_YOUR_API_KEY_HERE", "PUT_YOUR_DMXAPI_KEY_HERE"}:
        return ""
    return value


def effective_config() -> dict[str, Any]:
    data, error = _load_json_config()
    profile = os.environ.get("ADAM_LLM_PROFILE") or str(data.get("active") or "dmxapi")
    profiles = data.get("profiles", {})
    profile_cfg = profiles.get(profile, {}) if isinstance(profiles, dict) else {}
    profile_cfg = profile_cfg if isinstance(profile_cfg, dict) else {}
    if not error and "profiles" in data and not isinstance(profiles, dict):
        error = "profiles must be a JSON object"
    if not error and isinstance(profiles, dict) and profile in profiles and not isinstance(profiles[profile], dict):
        error = f"profile {profile!r} must be a JSON object"
    for field in ("base_url", "model", "api_key_env"):
        value = profile_cfg.get(field, data.get(field))
        if not error and value is not None and not isinstance(value, str):
            error = f"{field} must be a string"

    api_key = ""
    api_key_source = ""
    for name in ENV_KEYS:
        api_key = _usable_key(os.environ.get(name))
        if api_key:
            api_key_source = name
            break
    if not api_key:
        env_name = profile_cfg.get("api_key_env") or data.get("api_key_env")
        if isinstance(env_name, str):
            api_key = _usable_key(os.environ.get(env_name))
            api_key_source = env_name if api_key else ""
    if not api_key:
        api_key = _usable_key(profile_cfg.get("api_key") or data.get("api_key"))
        api_key_source = "config" if api_key else ""

    return {
        "base_url": os.environ.get("ADAM_LLM_BASE_URL") or profile_cfg.get("base_url") or data.get("base_url") or DEFAULT_BASE_URL,
        "model": os.environ.get("ADAM_LLM_MODEL") or profile_cfg.get("model") or data.get("model") or DEFAULT_MODEL,
        "profile": profile,
        "config_path": str(_json_config_path()),
        "config_error": error,
        "api_key": api_key,
        "api_key_source": api_key_source,
    }


def config() -> dict[str, Any]:
    cfg = effective_config()
    return {
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "profile": cfg["profile"],
        "config_path": cfg["config_path"],
        "config_error": cfg["config_error"],
        "api_key_source": cfg["api_key_source"],
        "api_key_configured": bool(cfg["api_key"]),
    }


def endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/chat/completions") else base + "/v1/chat/completions"


def extract_json(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.S)
        if match:
            stripped = match.group(1).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = min((pos for pos in (stripped.find("{"), stripped.find("[")) if pos >= 0), default=-1)
        if start < 0:
            raise
        end = max(stripped.rfind("}"), stripped.rfind("]"))
        if end <= start:
            raise
        return json.loads(stripped[start : end + 1])


def request_text(prompt: str, *, system: str = "", timeout: float = 40.0) -> dict[str, Any]:
    cfg = effective_config()
    if cfg["config_error"]:
        return {"ok": False, "error": "invalid ADAM_LLM_CONFIG: " + cfg["config_error"]}
    if not cfg["api_key"]:
        return {"ok": False, "error": "missing ADAM_LLM_API_KEY, DMXAPI_API_KEY, or config/llm.local.json api_key"}
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": 0,
        "max_tokens": 4096,
    }
    request = urllib.request.Request(
        endpoint(str(cfg["base_url"])),
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + cfg["api_key"], "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": exc.read().decode("utf-8", "replace")[:500]}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return {
        "ok": bool(content),
        "status": 200,
        "model": data.get("model"),
        "profile": cfg["profile"],
        "content": content,
        "usage": data.get("usage", {}),
    }


def request_json(prompt: str, *, system: str = "", timeout: float = 40.0) -> dict[str, Any]:
    result = request_text(prompt, system=system, timeout=timeout)
    if not result.get("ok"):
        return result
    try:
        data = extract_json(str(result["content"]))
    except Exception as exc:
        return {"ok": False, "error": f"json_parse_failed: {type(exc).__name__}: {exc}", "raw": result["content"][:500]}
    return {**result, "json": data}


def selftest() -> None:
    assert endpoint("https://www.dmxapi.cn") == "https://www.dmxapi.cn/v1/chat/completions"
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('prefix {"a": [1, 2]} suffix') == {"a": [1, 2]}
    saved = {key: os.environ.get(key) for key in ("ADAM_LLM_CONFIG", "ADAM_LLM_PROFILE", *ENV_KEYS)}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "llm.json"
            cfg.write_text(
                json.dumps(
                    {
                        "active": "dmxapi",
                        "profiles": {
                            "dmxapi": {"base_url": "https://www.dmxapi.cn", "model": "gpt-5.5", "api_key": "local-key"},
                            "backup": {"base_url": "https://backup.invalid", "model": "backup-model", "api_key_env": "BACKUP_KEY"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            os.environ["ADAM_LLM_CONFIG"] = str(cfg)
            os.environ.pop("ADAM_LLM_PROFILE", None)
            os.environ.pop("ADAM_LLM_API_KEY", None)
            os.environ.pop("DMXAPI_API_KEY", None)
            assert effective_config()["api_key"] == "local-key"
            os.environ["ADAM_LLM_API_KEY"] = "env-key"
            assert effective_config()["api_key_source"] == "ADAM_LLM_API_KEY"
            assert "env-key" not in json.dumps(config())
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ping", action="store_true")
    parser.add_argument("--prompt")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    if args.ping:
        print(json.dumps(request_text("Return exactly: ok", timeout=40.0), indent=2))
        return 0
    if args.prompt:
        result = request_json(args.prompt) if args.json else request_text(args.prompt)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    print(json.dumps(config(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

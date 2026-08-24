"""SourceDiscoveryAgent deterministic open-source selection and locking."""

from __future__ import annotations

import configparser
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from socimage.facts import sha256


ROOT = Path(__file__).resolve().parents[1]
POLICY_SCHEMA = ROOT / "schemas/source_policy.schema.json"
REUSE_PLAN_SCHEMA = ROOT / "schemas/reuse_plan.schema.json"
CANDIDATE_SCHEMA = ROOT / "schemas/source_candidate.schema.json"
LOCK_SCHEMA = ROOT / "schemas/source_lock.schema.json"


class SourceNetworkError(RuntimeError):
    pass


class SourceConfigurationError(RuntimeError):
    pass


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _git(path: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=path, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if proc.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed for {path}: {proc.stdout.strip()}")
    return proc.stdout.strip()


def _queries(context: Any) -> dict[str, Any]:
    requirements = context.software_requirements
    identity = sorted(requirements["board_identity"], key=lambda item: (item["kind"], item["value"].lower()))
    identity_values = [item["value"] for item in identity]
    queries = []
    for role in requirements["software_roles"]:
        queries.append({
            "id": f"role:{role}",
            "target": {"kind": "role", "id": role},
            "terms": sorted({role, " ".join([*identity_values, role]).strip()}),
            "basis": sorted({basis for item in identity for basis in item["basis"]}) or ["software_roles"],
        })
    for component in requirements["components"]:
        queries.append({
            "id": f"component:{component['id']}",
            "target": {"kind": "component", "id": component["id"]},
            "terms": component["search_terms"],
            "basis": component["hardware_basis"],
            "class": component["class"],
            "compatible": component["compatible"],
            "required_interfaces": component["required_interfaces"],
            "evidence_state": component["evidence_state"],
        })
    return {
        "schema": "soc-image.source-queries.v1",
        "software_requirements_sha256": context.software_requirements_sha256,
        "identity": identity,
        "queries": sorted(queries, key=lambda item: item["id"].lower()),
    }


def _requirements(query_contract: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "target": item["target"],
            "mandatory": True,
            "query_terms": item["terms"],
            "basis": item["basis"],
        }
        for item in query_contract["queries"]
    ]


def _api_json(url: str, headers: dict[str, str]) -> Any:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as stream:
        return json.load(stream)


def _forge_search(query: str) -> tuple[list[dict[str, str]], list[str]]:
    encoded = urllib.parse.urlencode({"q": query, "per_page": 3})
    results: list[dict[str, str]] = []
    errors = []
    github_headers = {"Accept": "application/vnd.github+json", "User-Agent": "soc-image-source-discovery"}
    if os.environ.get("GITHUB_TOKEN"):
        github_headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    try:
        data = _api_json(f"https://api.github.com/search/repositories?{encoded}", github_headers)
        results.extend({
            "id": f"github/{item['full_name']}",
            "forge": "github",
            "url": item["clone_url"],
            "description": item.get("description") or "",
            "license": (item.get("license") or {}).get("spdx_id") or "NOASSERTION",
        } for item in data.get("items", []))
    except urllib.error.HTTPError as exc:
        errors.append(f"{'retryable' if exc.code == 429 or exc.code >= 500 else 'fatal'}:github:http_{exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        errors.append(f"retryable:github:{type(exc).__name__}")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"fatal:github:{type(exc).__name__}")
    gitee_headers = {"Accept": "application/json", "User-Agent": "soc-image-source-discovery"}
    gitee_query = {"q": query, "per_page": 3}
    if os.environ.get("GITEE_TOKEN"):
        gitee_headers["Authorization"] = f"token {os.environ['GITEE_TOKEN']}"
    try:
        data = _api_json("https://gitee.com/api/v5/search/repositories?" + urllib.parse.urlencode(gitee_query), gitee_headers)
        results.extend({
            "id": f"gitee/{item['full_name']}",
            "forge": "gitee",
            "url": item.get("html_url", "").rstrip("/") + ".git",
            "description": item.get("description") or "",
            "license": item.get("license") if isinstance(item.get("license"), str) else "NOASSERTION",
        } for item in data)
    except urllib.error.HTTPError as exc:
        errors.append(f"{'retryable' if exc.code == 429 or exc.code >= 500 else 'fatal'}:gitee:http_{exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        errors.append(f"retryable:gitee:{type(exc).__name__}")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"fatal:gitee:{type(exc).__name__}")
    return results, errors


def _remote_git(*args: str, cwd: Path | None = None) -> str:
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        proc = subprocess.run(["git", "-c", "protocol.file.allow=never", *args], cwd=cwd, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise SourceNetworkError(f"git {args[0]} timed out") from exc
    if proc.returncode:
        if any(text in proc.stdout.lower() for text in ("could not resolve", "failed to connect", "connection timed out", "unable to access", "tls", "ssl", "http 403", "error: 403", "http 429", "error: 429", "http 5", "error: 5")):
            raise SourceNetworkError(f"git {args[0]} network failure")
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {proc.stdout.strip()}")
    return proc.stdout.strip()


def _bounded_tree(checkout: Path, revision: str) -> str:
    proc = subprocess.Popen(
        ["git", "ls-tree", "-r", revision], cwd=checkout, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    lines = []
    size = 0
    assert proc.stdout is not None
    for line in proc.stdout:
        size += len(line.encode())
        if len(lines) >= 100_000 or size > 16 * 1024 * 1024:
            proc.kill()
            proc.wait()
            raise RuntimeError("repository tree exceeds static inspection limits")
        lines.append(line.rstrip("\n"))
    if proc.wait() != 0:
        raise RuntimeError("git ls-tree failed during static inspection")
    return "\n".join(lines)


def _inspect_remote(item: dict[str, Any], _build_licenses: list[str]) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(item["url"])
    expected_host = {"github": "github.com", "gitee": "gitee.com"}.get(item["forge"])
    if parsed.scheme != "https" or parsed.hostname != expected_host or parsed.username or parsed.password:
        raise RuntimeError("repository URL is not an allowed HTTPS forge URL")
    revision_line = _remote_git("ls-remote", item["url"], "HEAD").splitlines()
    if len(revision_line) != 1 or not re.fullmatch(r"[0-9a-f]{40}\s+HEAD", revision_line[0]):
        raise RuntimeError("remote HEAD did not resolve to one commit")
    revision = revision_line[0].split()[0]
    with tempfile.TemporaryDirectory() as tmp:
        checkout = Path(tmp) / "repository"
        _remote_git("init", "--quiet", str(checkout))
        _remote_git("remote", "add", "origin", item["url"], cwd=checkout)
        _remote_git("fetch", "--quiet", "--depth", "1", "--filter=blob:none", "origin", revision, cwd=checkout)
        _remote_git("cat-file", "-e", f"{revision}^{{commit}}", cwd=checkout)
        tree = _bounded_tree(checkout, revision)
        paths = [line.split("\t", 1)[1] for line in tree.splitlines() if "\t" in line]
        license_paths = [path for path in paths if Path(path).name.lower().startswith(("license", "copying", "notice"))][:4]
        license_evidence = []
        for path in license_paths:
            size_text = _remote_git("cat-file", "-s", f"{revision}:{path}", cwd=checkout)
            if not size_text.isdigit() or int(size_text) > 1024 * 1024:
                continue
            content = subprocess.run(["git", "show", f"{revision}:{path}"], cwd=checkout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=10).stdout
            if content:
                license_evidence.append({"path": path, "sha256": hashlib.sha256(content).hexdigest()})
    top_paths = sorted({path.split("/", 1)[0] for path in paths})[:32] or ["."]
    return {
        "revision": revision,
        "content_hash": {"algorithm": "sha256-git-ls-tree-v1", "value": hashlib.sha256(tree.encode()).hexdigest()},
        "source_paths": top_paths,
        "license_evidence": license_evidence,
        "license_decision": "reference_only",
        "build_docs": any(Path(path).name.lower().startswith(("readme", "building")) for path in paths),
        "tests": any(part.lower() in {"test", "tests"} for path in paths for part in Path(path).parts),
    }


def _online_candidates(context: Any, query_contract: dict[str, Any]) -> list[dict[str, Any]]:
    identity = {item["kind"]: item["value"].lower() for item in query_contract["identity"]}
    component_queries = [item for item in query_contract["queries"] if item["target"]["kind"] == "component"]
    hardware_name = identity.get("board") or identity.get("soc") or identity.get("architecture") or "embedded"
    searches = [("stack", f"{hardware_name} sdk", [f"role:{role}" for role in ("boot", "bsp", "driver", "image_tool")])]
    role_queries = [item for item in query_contract["queries"] if item["target"]["kind"] == "role" and item["target"]["id"] not in {"boot", "bsp", "driver", "image_tool"}]
    for offset in range(0, len(role_queries), 3):
        batch = role_queries[offset:offset + 3]
        roles = " OR ".join(item["target"]["id"] for item in batch)
        searches.append((f"role-batch:{offset // 3}", f"{hardware_name} {roles}", [item["id"] for item in batch]))
    compatible_queries = [item for item in component_queries if item.get("compatible")]
    searches.extend((item["id"], f"{item['compatible'][0]} driver", [item["id"]]) for item in compatible_queries)
    class_queries = [item for item in component_queries if not item.get("compatible")]
    for offset in range(0, len(class_queries), 4):
        batch = class_queries[offset:offset + 4]
        classes = " OR ".join(sorted({item["class"] for item in batch}))
        searches.append((f"component-batch:{offset // 4}", f"{hardware_name} {classes} driver", [item["id"] for item in batch]))
    found: dict[str, dict[str, Any]] = {}
    network_errors = []
    search = getattr(context, "source_search", _forge_search)
    for query_id, text, covered in searches:
        results, errors = search(text)
        if errors:
            fatal = [error for error in errors if error.startswith("fatal:")]
            if fatal:
                raise SourceConfigurationError(f"{query_id}: {'; '.join(fatal)}")
            network_errors.append(f"{query_id}: {'; '.join(errors)}")
            continue
        for item in results:
            if not item.get("url", "").startswith("https://"):
                continue
            candidate = found.setdefault(item["url"], {**item, "covered_requirements": set()})
            candidate["covered_requirements"].update(covered)
    if network_errors:
        raise SourceNetworkError("; ".join(network_errors))
    inspect = getattr(context, "source_inspect", _inspect_remote)
    candidates = []
    for item in sorted(found.values(), key=lambda value: value["url"].lower()):
        covered = sorted(item.pop("covered_requirements"))
        text = f"{item['id']} {item['description']}".lower()
        normalized_text = re.sub(r"[^a-z0-9]+", "", text)
        board_match = re.sub(r"[^a-z0-9]+", "", identity.get("board", "\0")) in normalized_text
        soc_match = re.sub(r"[^a-z0-9]+", "", identity.get("soc", "\0")) in normalized_text
        level = "exact_board" if board_match else "exact_soc" if soc_match else "compatible_ip" if any(value.split(":", 1)[0] == "component" for value in covered) else "none"
        try:
            inspected = inspect(item, context.source_policy["build_licenses"])
            errors = []
        except SourceNetworkError:
            raise
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            inspected = {"source_paths": ["."], "license_evidence": [], "license_decision": "reference_only", "build_docs": False, "tests": False}
            errors = [str(exc)]
        roles = sorted({value.split(":", 1)[1] for value in covered if value.startswith("role:")}) or ["driver"]
        components = sorted(value.split(":", 1)[1] for value in covered if value.startswith("component:"))
        if not errors and level == "none":
            errors = ["hardware match was not established"]
        usable = not errors and inspected["license_decision"] == "build"
        candidates.append({
            "id": item["id"], "forge": item["forge"], "source_type": "git", "url": item["url"],
            "roles": roles, "components": components, "source_paths": inspected["source_paths"],
            "covered_requirements": covered,
            "match_evidence": [{"requirement_id": requirement, "basis": [f"forge_search:{requirement}"], "source_paths": inspected["source_paths"]} for requirement in covered],
            "match": {"level": level, "architecture_compatible": level != "none", "board_config": level == "exact_board", "os_abi": None, "media_abi": None},
            "license": {"spdx": item["license"], "decision": inspected["license_decision"], "evidence": inspected["license_evidence"]},
            **({"revision": inspected["revision"], "content_hash": inspected["content_hash"], "build_docs": inspected["build_docs"], "tests": inspected["tests"]} if not errors else {}),
            "status": "usable" if usable else "reference_only" if not errors else "rejected",
            "errors": [] if usable else errors,
        })
    return candidates


def _candidate(context: Any, item: dict[str, Any], selector_text: str, selector_weights: dict[str, int]) -> dict[str, Any]:
    checkout = Path(getattr(context, "source_root", ROOT / "third_party")) / item["id"]
    revision = ""
    tree_sha = ""
    tree = ""
    license_evidence = []
    errors = []
    if (checkout / ".git").exists() or (checkout / ".git").is_file():
        try:
            revision = _git(checkout, "rev-parse", "HEAD")
            if item.get("revision") and revision != item["revision"]:
                errors.append(f"revision mismatch: expected {item['revision']}, got {revision}")
            tree = _git(checkout, "ls-tree", "-r", revision, "--", *item["sparse_paths"])
            tree_sha = hashlib.sha256(tree.encode()).hexdigest()
        except RuntimeError as exc:
            errors.append(str(exc))
        for relative in item["license_files"]:
            blob = subprocess.run(["git", "show", f"{revision}:{relative}"], cwd=checkout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if blob.returncode == 0:
                license_evidence.append({"path": relative, "sha256": hashlib.sha256(blob.stdout).hexdigest()})
            else:
                errors.append(f"missing license file in locked revision: {relative}")
    else:
        errors.append("local checkout is unavailable")
    matched = sorted(selector for selector in item["selectors"] if selector == "*" or selector.lower() in selector_text)
    requested_disposition = item.get("disposition", "build")
    license_ok = item["license"] in context.source_policy["build_licenses"] and len(license_evidence) == len(item["license_files"])
    license_decision = requested_disposition if requested_disposition != "build" else "build" if license_ok else "reference_only"
    revision_ok = bool(re.fullmatch(r"[0-9a-f]{40}", revision))
    match_score = min(45, sum(selector_weights.get(value, 5) for value in matched))
    score = 25 + match_score + (10 if checkout.exists() else 0) + (10 if license_ok else 0) + (5 if revision_ok else 0)
    tree_paths = [line.split("\t", 1)[1] for line in tree.splitlines() if "\t" in line]
    return {
        **item,
        "revision": revision,
        "tree_sha256": tree_sha,
        "checkout": f"third_party/{item['id']}",
        "matched_selectors": matched,
        "license_evidence": license_evidence,
        "license_decision": license_decision,
        "eligible": requested_disposition == "build" and license_ok and revision_ok and not errors,
        "score": score,
        "board_config": any("board" in Path(path).parts or "configs" in Path(path).parts for path in tree_paths),
        "build_docs": any(Path(path).name.lower().startswith(("readme", "building", "makefile")) for path in tree_paths),
        "tests": any(part.lower() in {"test", "tests"} for path in tree_paths for part in Path(path).parts),
        "tree_paths": tree_paths,
        "errors": errors,
    }


def _matching_components(item: dict[str, Any], query_contract: dict[str, Any]) -> list[str]:
    selectors = [re.sub(r"[^a-z0-9]+", "", value.lower()) for value in item["selectors"] if value != "*"]
    source_tokens = {token for path in item.get("tree_paths", []) for token in re.split(r"[^a-z0-9]+", path.lower()) if token}
    source_paths = [re.sub(r"[^a-z0-9]+", "", path.lower()) for path in item.get("tree_paths", [])]
    matches = []
    for query in query_contract["queries"]:
        if query["target"]["kind"] != "component":
            continue
        hardware_terms = [query.get("class", ""), *query.get("compatible", [])]
        normalized = [re.sub(r"[^a-z0-9]+", "", value.lower()) for value in hardware_terms]
        policy_match = any(selector and any(selector in value or value in selector for value in normalized if value) for selector in selectors)
        tree_match = any(value in source_tokens or (len(value) >= 4 and any(value in path for path in source_paths)) for value in normalized if value)
        if policy_match or tree_match:
            matches.append(query["target"]["id"])
    return sorted(set(matches))


def _match_level(item: dict[str, Any], query_contract: dict[str, Any], components: list[str]) -> str:
    matched = {re.sub(r"[^a-z0-9]+", "", value.lower()) for value in item["matched_selectors"]}
    identity = {entry["kind"]: re.sub(r"[^a-z0-9]+", "", entry["value"].lower()) for entry in query_contract["identity"]}
    if identity.get("board") and any(value in identity["board"] or identity["board"] in value for value in matched):
        return "exact_board"
    if identity.get("soc") and any(value in identity["soc"] or identity["soc"] in value for value in matched):
        return "exact_soc"
    if components:
        return "compatible_ip"
    return "class" if item["roles"] else "none"


def _architecture_compatible(item: dict[str, Any], query_contract: dict[str, Any], level: str) -> bool:
    architecture = next((entry["value"].lower() for entry in query_contract["identity"] if entry["kind"] == "architecture"), None)
    if architecture is None or "*" in item["selectors"]:
        return True
    selectors = {re.sub(r"[^a-z0-9]+", "", value.lower()) for value in item["selectors"]}
    families = {
        "riscv": {value for value in selectors if value.startswith("rv") or value == "riscv"},
        "arm": {value for value in selectors if value.startswith("arm") or value.startswith("cortex")},
    }
    declared = set().union(*families.values())
    if not declared:
        return True
    family = "riscv" if architecture.startswith(("rv", "riscv")) else "arm" if architecture.startswith(("arm", "cortex")) else architecture
    return bool(families.get(family, set()))


def _policy_candidate_contract(
    context: Any,
    policy_item: dict[str, Any],
    query_contract: dict[str, Any],
    selector_text: str,
    selector_weights: dict[str, int],
) -> dict[str, Any]:
    item = _candidate(context, policy_item, selector_text, selector_weights)
    components = _matching_components(item, query_contract)
    roles = sorted(set(item["roles"]) & set(context.software_requirements["software_roles"]))
    covered = [*(f"role:{role}" for role in roles), *(f"component:{component}" for component in components)]
    match_level = _match_level(item, query_contract, components)
    lockable = bool(re.fullmatch(r"[0-9a-f]{40}", item["revision"])) and bool(item["tree_sha256"]) and not item["errors"]
    status = "usable" if item["eligible"] else "reference_only" if lockable and item["license_decision"] in {"internal_evaluation", "reference_only"} else "rejected"
    return {
        "id": item["id"],
        "forge": "github" if "github.com" in item["url"] else "gitee" if "gitee.com" in item["url"] else "other",
        "source_type": "git", "url": item["url"], "roles": roles, "components": components,
        "source_paths": item["sparse_paths"], "covered_requirements": covered,
        "match_evidence": [{"requirement_id": requirement, "basis": item["matched_selectors"] or ["source_policy"], "source_paths": item["sparse_paths"]} for requirement in covered],
        "match": {
            "level": match_level,
            "architecture_compatible": _architecture_compatible(item, query_contract, match_level),
            "board_config": item["board_config"],
            "os_abi": item.get("os_abi"),
            "media_abi": item.get("media_abi"),
        },
        "license": {"spdx": item["license"], "decision": item["license_decision"], "evidence": item["license_evidence"]},
        **({"revision": item["revision"], "content_hash": {"algorithm": "sha256-git-ls-tree-v1", "value": item["tree_sha256"]}, "build_docs": item["build_docs"], "tests": item["tests"]} if lockable else {}),
        "status": status,
        "errors": item["errors"] or ([] if status != "rejected" else ["source is not eligible for locking"]),
    }


def _candidate_score(candidate: dict[str, Any], anchor: dict[str, Any] | None = None) -> int | None:
    if candidate["status"] != "usable" or candidate["license"]["decision"] != "build" or candidate["license"]["spdx"] == "NOASSERTION" or not candidate["match"]["architecture_compatible"] or candidate["match"]["level"] == "none":
        return None
    score = {"exact_board": 100, "exact_soc": 70, "compatible_ip": 40, "class": 20, "none": 0}[candidate["match"]["level"]]
    score += 15 if candidate["match"].get("board_config") else 0
    if anchor and anchor["match"].get("os_abi") and candidate["match"].get("os_abi") == anchor["match"]["os_abi"]:
        score += 15
    score += 5 if candidate.get("build_docs") else 0
    score += 5 if candidate.get("tests") else 0
    return score


def _solve_stack(context: Any, candidates: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    anchor_roles = {"boot", "bsp", "driver", "image_tool"}
    allowed_licenses = set(context.source_policy["build_licenses"])

    def score(candidate: dict[str, Any], stack_anchor: dict[str, Any] | None = None) -> int | None:
        return _candidate_score(candidate, stack_anchor) if candidate["license"]["spdx"] in allowed_licenses else None

    anchors = [candidate for candidate in candidates if anchor_roles <= set(candidate["roles"]) and score(candidate) is not None]
    anchor = sorted(anchors, key=lambda item: (-int(score(item) or 0), item["url"].lower()))[0] if anchors else None
    entries = []
    selected_roles = []
    selected_components = []
    uncovered = []
    selected_candidates: dict[str, dict[str, Any]] = {}
    abi_needs: dict[str, set[str]] = {}
    os_abi_roles = {"bsp", "driver", "os", "runtime", "product"}
    media_classes = {"accelerator", "audio", "camera", "display", "video"}
    for role in context.software_requirements["software_roles"]:
        choices = [candidate for candidate in candidates if role in candidate["roles"] and score(candidate, anchor) is not None]
        if anchor and role in anchor_roles:
            choices = [anchor]
        if not choices:
            uncovered.append({"target": f"role:{role}", "reason": "no architecture and license compatible source"})
            entries.append({"id": f"role:{role}", "target": {"kind": "role", "id": role}, "disposition": "blocked", "candidate_ids": [], "source_paths": [], "strategy": "blocked", "basis": ["software_requirements.software_roles"]})
            continue
        selected = sorted(choices, key=lambda item: (-int(score(item, anchor) or 0), item["url"].lower()))[0]
        if anchor and selected["id"] != anchor["id"] and role in os_abi_roles:
            if not anchor["match"].get("os_abi") or not selected["match"].get("os_abi"):
                reason = f"OS ABI is unknown for cross-stack role {role}"
                uncovered.append({"target": f"role:{role}", "reason": reason})
                entries.append({"id": f"role:{role}", "target": {"kind": "role", "id": role}, "disposition": "blocked", "candidate_ids": [], "source_paths": [], "strategy": "blocked", "basis": [f"source_candidate:{selected['id']}"]})
                continue
            abi_needs.setdefault(selected["id"], set()).add("os_abi")
        selected_candidates[selected["id"]] = selected
        selected_roles.append({"role": role, "candidate": selected["id"], "score": score(selected, anchor)})
        entries.append({"id": f"role:{role}", "target": {"kind": "role", "id": role}, "disposition": "reuse", "candidate_ids": [selected["id"]], "source_paths": selected["source_paths"], "strategy": "direct" if anchor and selected["id"] == anchor["id"] else "adapt", "basis": [f"source_candidate:{selected['id']}"]})
    for component in context.software_requirements["components"]:
        choices = [candidate for candidate in candidates if component["id"] in candidate["components"] and score(candidate, anchor) is not None]
        if choices:
            selected = sorted(choices, key=lambda item: (-int(score(item, anchor) or 0), item["url"].lower()))[0]
            if anchor and selected["id"] != anchor["id"] and component["class"] in media_classes:
                if not anchor["match"].get("media_abi") or not selected["match"].get("media_abi"):
                    reason = f"media ABI is unknown for cross-stack component {component['id']}"
                    uncovered.append({"target": f"component:{component['id']}", "reason": reason})
                    entries.append({"id": f"component:{component['id']}", "target": {"kind": "component", "id": component["id"]}, "disposition": "blocked", "candidate_ids": [], "source_paths": [], "strategy": "blocked", "basis": component["hardware_basis"]})
                    continue
                abi_needs.setdefault(selected["id"], set()).add("media_abi")
            selected_candidates[selected["id"]] = selected
            selected_components.append({"component": component["id"], "candidate": selected["id"], "score": score(selected, anchor)})
            entries.append({"id": f"component:{component['id']}", "target": {"kind": "component", "id": component["id"]}, "disposition": "reuse", "candidate_ids": [selected["id"]], "source_paths": selected["source_paths"], "strategy": "configure" if anchor and selected["id"] == anchor["id"] else "adapt", "basis": component["hardware_basis"]})
        elif component["generated_mmio_allowed"]:
            entries.append({"id": f"component:{component['id']}", "target": {"kind": "component", "id": component["id"]}, "disposition": "generate", "candidate_ids": [], "source_paths": [], "strategy": "rewrite", "basis": component["hardware_basis"]})
        else:
            reason = "no reusable source and generated MMIO is not allowed"
            uncovered.append({"target": f"component:{component['id']}", "reason": reason})
            entries.append({"id": f"component:{component['id']}", "target": {"kind": "component", "id": component["id"]}, "disposition": "blocked", "candidate_ids": [], "source_paths": [], "strategy": "blocked", "basis": component["hardware_basis"]})
    adapters = []
    if anchor:
        for candidate_id, required_abis in abi_needs.items():
            candidate = selected_candidates[candidate_id]
            for abi in required_abis:
                source_abi = candidate["match"].get(abi)
                anchor_abi = anchor["match"].get(abi)
                if source_abi != anchor_abi:
                    adapters.append({"id": f"adapter:{abi}:{candidate['id']}", "reason": f"{abi} mismatch: {source_abi} -> {anchor_abi}", "from_candidate": candidate["id"], "to_anchor": anchor["id"]})
    adapters = sorted({item["id"]: item for item in adapters}.values(), key=lambda item: item["id"])
    plan = {
        "schema": "soc-image.reuse-plan.v1", "hardware_ir_sha256": context.hardware_ir_sha256,
        "software_requirements_sha256": context.software_requirements_sha256, "source_policy_sha256": context.source_policy_sha256,
        "source_candidates_sha256": "", "anchor": anchor["id"] if anchor else None,
        "entries": entries, "adapter_tasks": adapters, "uncovered": uncovered,
        "coherence": {"passed": bool(anchor) and not uncovered, "reasons": (["no source stack covers boot, BSP, driver framework, and image tool"] if not anchor else []) + [item["reason"] for item in uncovered]},
    }
    selection = {
        "schema": "soc-image.source-selection.v2", "anchor": plan["anchor"], "selected": selected_roles,
        "components": selected_components, "adapter_tasks": adapters,
        "internal_evaluation": sorted(candidate["id"] for candidate in candidates if candidate["license"]["decision"] == "internal_evaluation"),
        "reference_only": sorted(candidate["id"] for candidate in candidates if candidate["license"]["decision"] == "reference_only"),
        "rejected": sorted(candidate["id"] for candidate in candidates if candidate["status"] == "rejected" or score(candidate, anchor) is None and candidate["license"]["decision"] == "build"),
        "uncovered": uncovered,
    }
    return plan, selection


def _safe_source_path(value: str) -> bool:
    path = Path(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _normalized_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SourceConfigurationError(f"dependency URL is not an allowed HTTPS URL: {value}")
    return value.rstrip("/").removesuffix(".git").lower()


def _git_dependency_url(parent_url: str, value: str) -> str:
    return urllib.parse.urljoin(parent_url.rstrip("/") + "/", value) if value.startswith(("./", "../")) else value


def _manifest_remote_url(parent_url: str, value: str) -> str:
    return urllib.parse.urljoin(parent_url, value) if value.startswith(("./", "../")) else value


def _tree_content_hash(checkout: Path, revision: str, paths: list[str]) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{40}", revision) or not paths or not all(_safe_source_path(path) for path in paths):
        raise SourceConfigurationError("locked revision or selected path is invalid")
    _git(checkout, "cat-file", "-e", f"{revision}^{{commit}}")
    tree = _git(checkout, "ls-tree", "-r", revision, "--", *paths)
    if not tree:
        raise SourceConfigurationError(f"selected source paths are absent from {checkout.name}@{revision}")
    return {"algorithm": "sha256-git-ls-tree-v1", "value": hashlib.sha256(tree.encode()).hexdigest()}


def _locked_license_evidence(checkout: Path, revision: str, paths: list[str]) -> list[dict[str, str]]:
    evidence = []
    for path in paths:
        if not _safe_source_path(path):
            raise SourceConfigurationError(f"license evidence path is unsafe: {path}")
        blob = subprocess.run(["git", "show", f"{revision}:{path}"], cwd=checkout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if blob.returncode:
            raise SourceConfigurationError(f"license evidence is absent from locked revision: {path}")
        evidence.append({"path": path, "sha256": hashlib.sha256(blob.stdout).hexdigest()})
    return evidence


def _submodule_dependencies(checkout: Path, revision: str, paths: list[str], parent_url: str) -> list[dict[str, str]]:
    tree = _git(checkout, "ls-tree", "-r", revision, "--", *paths)
    gitlinks = {
        line.split("\t", 1)[1]: line.split()[2]
        for line in tree.splitlines()
        if line.startswith("160000 commit ") and "\t" in line
    }
    if not gitlinks:
        return []
    module = subprocess.run(["git", "show", f"{revision}:.gitmodules"], cwd=checkout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if module.returncode:
        raise SourceConfigurationError(f"gitlinks have no .gitmodules contract in {checkout.name}")
    parser = configparser.ConfigParser()
    parser.read_string(module.stdout.decode("utf-8"))
    urls = {parser[section].get("path", ""): parser[section].get("url", "") for section in parser.sections()}
    dependencies = []
    for path, dependency_revision in sorted(gitlinks.items()):
        url = urls.get(path, "")
        url = _git_dependency_url(parent_url, url)
        dependencies.append({
            "kind": "git_submodule", "path": path, "declaration_path": ".gitmodules",
            "declaration_sha256": hashlib.sha256(module.stdout).hexdigest(), "url": url, "revision": dependency_revision,
        })
    return dependencies


def _manifest_dependencies(checkout: Path, revision: str, paths: list[str], parent_url: str) -> list[dict[str, str]]:
    tree = _git(checkout, "ls-tree", "-r", revision, "--", *paths)
    manifests = [
        line.split("\t", 1)[1]
        for line in tree.splitlines()
        if "\t" in line and Path(line.split("\t", 1)[1]).name in {"default.xml", "manifest.xml"}
    ]
    pending = list(manifests)
    visited = set()
    documents: list[tuple[str, str, ET.Element]] = []
    while pending:
        manifest_path = pending.pop(0)
        if manifest_path in visited:
            continue
        visited.add(manifest_path)
        blob = subprocess.run(["git", "show", f"{revision}:{manifest_path}"], cwd=checkout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if blob.returncode or len(blob.stdout) > 1024 * 1024:
            raise SourceConfigurationError(f"repository manifest is unavailable or too large: {manifest_path}")
        try:
            root = ET.fromstring(blob.stdout)
        except ET.ParseError as exc:
            raise SourceConfigurationError(f"repository manifest is invalid: {manifest_path}: {exc}") from exc
        if root.tag != "manifest":
            continue
        documents.append((manifest_path, hashlib.sha256(blob.stdout).hexdigest(), root))
        for include in root.findall("include"):
            name = include.get("name", "")
            included_path = name
            if not _safe_source_path(included_path):
                raise SourceConfigurationError(f"repository manifest include is unsafe: {manifest_path}:{name}")
            pending.append(included_path)

    known_remotes: dict[str | None, dict[str, str]] = {}
    default_remote = None
    default_revision = None
    for _, _, root in documents:
        known_remotes.update({
            item.get("name"): {
                "fetch": _manifest_remote_url(parent_url, item.get("fetch", "")),
                "revision": item.get("revision", ""),
            }
            for item in root.findall("remote")
        })
        default = root.find("default")
        if default is not None:
            default_remote = default.get("remote") or default_remote
            default_revision = default.get("revision") or default_revision

    projects = []

    def add_project(node: ET.Element, declaration_path: str, declaration_sha256: str, parent_name: str = "", parent_path: str = "") -> None:
        local_name = node.get("name", "")
        name = "/".join(value.strip("/") for value in (parent_name, local_name) if value)
        local_path = node.get("path") or local_name
        path = "/".join(value.strip("/") for value in (parent_path, local_path) if value)
        projects.append({
            "name": name, "path": path, "remote": node.get("remote") or default_remote,
            "revision": node.get("revision", ""), "declaration_path": declaration_path,
            "declaration_sha256": declaration_sha256,
        })
        for child in node.findall("project"):
            add_project(child, declaration_path, declaration_sha256, name, path)

    for manifest_path, manifest_sha256, root in documents:
        if root.find("superproject") is not None:
            raise SourceConfigurationError(f"repository manifest superproject is not supported: {manifest_path}")
        for project in root.findall("project"):
            add_project(project, manifest_path, manifest_sha256)
    for manifest_path, manifest_sha256, root in documents:
        for extension in root.findall("extend-project"):
            matches = [item for item in projects if item["name"] == extension.get("name") and (not extension.get("path") or item["path"] == extension.get("path"))]
            if len(matches) != 1:
                raise SourceConfigurationError(f"repository manifest extend-project is ambiguous: {manifest_path}:{extension.get('name', '')}")
            project = matches[0]
            project["revision"] = extension.get("revision") or project["revision"]
            project["remote"] = extension.get("remote") or project["remote"]
            project["path"] = extension.get("dest-path") or project["path"]
            project["declaration_path"] = manifest_path
            project["declaration_sha256"] = manifest_sha256
        for removal in root.findall("remove-project"):
            matches = [item for item in projects if item["name"] == removal.get("name") and (not removal.get("path") or item["path"] == removal.get("path"))]
            if not matches and not removal.get("optional") == "true":
                raise SourceConfigurationError(f"repository manifest remove-project has no match: {manifest_path}:{removal.get('name', '')}")
            projects = [item for item in projects if item not in matches]

    dependencies = []
    for project in projects:
        remote = known_remotes.get(project["remote"], {})
        dependency_revision = project["revision"] or remote.get("revision") or default_revision or ""
        fetch = remote.get("fetch", "")
        url = urllib.parse.urljoin(fetch.rstrip("/") + "/", project["name"]) if fetch else ""
        dependencies.append({
            "kind": "repo_manifest", "path": project["path"], "declaration_path": project["declaration_path"],
            "declaration_sha256": project["declaration_sha256"], "url": url, "revision": dependency_revision,
        })
    return dependencies


def _repository_license_evidence(checkout: Path, revision: str) -> list[dict[str, str]]:
    names = _git(checkout, "ls-tree", "-r", "--name-only", revision).splitlines()
    candidates = [
        path for path in names
        if len(Path(path).parts) <= 3 and Path(path).name.lower().startswith(("license", "copying", "notice"))
    ]
    paths = []
    for path in candidates:
        size = _git(checkout, "cat-file", "-s", f"{revision}:{path}")
        if size.isdigit() and int(size) <= 1024 * 1024:
            paths.append(path)
        if len(paths) == 8:
            break
    return _locked_license_evidence(checkout, revision, paths)


def _checkout_remote_urls(checkout: Path) -> set[str]:
    urls = set()
    for remote in _git(checkout, "remote").splitlines():
        for url in _git(checkout, "remote", "get-url", "--all", remote).splitlines():
            try:
                urls.add(_normalized_url(url))
            except SourceConfigurationError:
                continue
    return urls


def _reference_stack_lock(context: Any, selector_text: str) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], list[dict[str, str]]]:
    sections: dict[str, list[dict[str, Any]]] = {"internal_evaluation": [], "reference_only": []}
    summaries = []
    edges = []
    policy_root = Path(getattr(context, "policy_root", ROOT)).resolve()
    for stack in context.source_policy.get("reference_stacks", []):
        if not any(selector.lower() in selector_text for selector in stack["selectors"]):
            continue
        workspace = (policy_root / stack["workspace"]).resolve()
        manifest_path = (policy_root / stack["manifest"]).resolve()
        if not workspace.is_relative_to(policy_root) or not manifest_path.is_relative_to(policy_root):
            raise SourceConfigurationError(f"reference stack path escapes policy root: {stack['id']}")
        if not manifest_path.is_file():
            raise SourceConfigurationError(f"reference stack manifest is missing: {stack['id']}")
        manifest_sha256 = sha256(manifest_path)
        try:
            manifest = ET.parse(manifest_path).getroot()
        except ET.ParseError as exc:
            raise SourceConfigurationError(f"reference stack manifest is invalid: {stack['id']}: {exc}") from exc
        if manifest.tag != "manifest" or manifest.findall("include") or manifest.findall("extend-project") or manifest.findall("remove-project") or manifest.find("superproject") is not None:
            raise SourceConfigurationError(f"reference stack requires a frozen flat manifest: {stack['id']}")
        remotes = {
            item.get("name"): {"fetch": item.get("fetch", ""), "revision": item.get("revision", "")}
            for item in manifest.findall("remote")
        }
        default = manifest.find("default")
        default_remote = default.get("remote") if default is not None else None
        default_revision = default.get("revision") if default is not None else None
        projects = manifest.findall("project")
        if len(manifest.findall(".//project")) != len(projects) or len(projects) != stack["expected_repositories"]:
            raise SourceConfigurationError(f"reference stack repository count mismatch: {stack['id']}")
        repositories = []
        root_repository_id = None
        seen_paths = set()
        for project in projects:
            path = project.get("path") or project.get("name", "")
            remote = remotes.get(project.get("remote") or default_remote, {})
            revision = project.get("revision") or remote.get("revision") or default_revision or ""
            if path in seen_paths or not (path == "." or _safe_source_path(path)) or not re.fullmatch(r"[0-9a-f]{40}", revision):
                raise SourceConfigurationError(f"reference stack project is not uniquely revision locked: {stack['id']}:{path}")
            seen_paths.add(path)
            fetch = remote.get("fetch", "")
            name = project.get("name", "")
            url = urllib.parse.urljoin(fetch.rstrip("/") + "/", name) if fetch else ""
            normalized_url = _normalized_url(url)
            checkout = (workspace if path == "." else workspace / path).resolve()
            if not checkout.is_relative_to(workspace):
                raise SourceConfigurationError(f"reference stack checkout escapes workspace: {stack['id']}:{path}")
            if not ((checkout / ".git").exists() or (checkout / ".git").is_file()):
                raise SourceConfigurationError(f"reference stack checkout is missing: {stack['id']}:{path}")
            if normalized_url not in _checkout_remote_urls(checkout):
                raise SourceConfigurationError(f"reference stack checkout remote does not match manifest: {stack['id']}:{path}")
            repository_id = f"{stack['id']}/{'root' if path == '.' else path}"
            license_evidence = _repository_license_evidence(checkout, revision)
            entry = {
                "id": repository_id, "url": url, "revision": revision,
                "content_hash": _tree_content_hash(checkout, revision, ["."]),
                "license": "NOASSERTION", "license_evidence": license_evidence,
                "license_evidence_status": "found" if license_evidence else "not_found",
                "selected_paths": ["."], "covered_requirements": [f"reference_stack:{stack['id']}"],
            }
            sections[stack["decision"]].append(entry)
            repositories.append({"repository_id": repository_id, "path": path})
            if path == ".":
                root_repository_id = repository_id
        if root_repository_id is None:
            raise SourceConfigurationError(f"reference stack has no root project: {stack['id']}")
        for repository in repositories:
            if repository["repository_id"] == root_repository_id:
                continue
            revision = next(item["revision"] for item in sections[stack["decision"]] if item["id"] == repository["repository_id"])
            edges.append({
                "parent_id": root_repository_id, "child_id": repository["repository_id"], "kind": "repo_manifest",
                "path": repository["path"], "declaration_path": stack["manifest"],
                "declaration_sha256": manifest_sha256, "revision": revision,
            })
        summaries.append({
            "id": stack["id"], "decision": stack["decision"], "workspace": stack["workspace"],
            "manifest_path": stack["manifest"], "manifest_sha256": manifest_sha256,
            "root_repository_id": root_repository_id, "repositories": repositories,
        })
    return sections, summaries, edges


def _source_lock(context: Any, candidates_contract: dict[str, Any], reuse_plan: dict[str, Any]) -> dict[str, Any]:
    candidates = {item["id"]: item for item in candidates_contract["candidates"]}
    policy = {item["id"]: item for item in context.source_policy["candidates"]}
    policy_by_url = {_normalized_url(item["url"]): item for item in policy.values()}
    source_root = Path(getattr(context, "source_root", ROOT / "third_party"))
    query_contract = _queries(context)
    selector_text = " ".join(term for query in query_contract["queries"] for term in query["terms"]).lower()
    selector_weights = {
        item["value"].lower(): {"board": 30, "soc": 25, "architecture": 15, "memory": 5}.get(item["kind"], 5)
        for item in query_contract["identity"]
    }
    selected: dict[str, dict[str, Any]] = {}
    covered: dict[str, set[str]] = {}
    selected_paths: dict[str, set[str]] = {}
    for entry in reuse_plan["entries"]:
        if entry["disposition"] != "reuse":
            continue
        for candidate_id in entry["candidate_ids"]:
            selected[candidate_id] = candidates[candidate_id]
            covered.setdefault(candidate_id, set()).add(entry["id"])
            selected_paths.setdefault(candidate_id, set()).update(entry["source_paths"])

    build: dict[str, dict[str, Any]] = {}
    pending: list[tuple[str, Path]] = []

    def locked_repository(candidate: dict[str, Any], paths: list[str], requirements: set[str] | list[str]) -> dict[str, Any]:
        checkout = source_root / candidate["id"]
        entry = {
            "id": candidate["id"], "url": candidate["url"], "revision": candidate["revision"],
            "content_hash": _tree_content_hash(checkout, candidate["revision"], paths),
            "license": candidate["license"]["spdx"],
            "license_evidence": _locked_license_evidence(checkout, candidate["revision"], [item["path"] for item in candidate["license"]["evidence"]]),
            "selected_paths": paths, "covered_requirements": sorted(requirements),
        }
        entry["license_evidence_status"] = "found" if entry["license_evidence"] else "not_found"
        return entry

    for candidate_id in sorted(selected):
        candidate = selected[candidate_id]
        candidate_policy = policy.get(candidate_id)
        expected_candidate = _policy_candidate_contract(
            context, candidate_policy, query_contract, selector_text, selector_weights
        ) if candidate_policy else None
        if (
            candidate["status"] != "usable"
            or candidate["license"]["decision"] != "build"
            or not candidate_policy
            or candidate_policy.get("disposition", "build") != "build"
            or candidate_policy.get("source_usage", "target") != "target"
            or _normalized_url(candidate["url"]) != _normalized_url(candidate_policy["url"])
            or candidate["license"]["spdx"] != candidate_policy["license"]
            or candidate != expected_candidate
        ):
            raise SourceConfigurationError(f"reuse plan selected a non-build candidate: {candidate_id}")
        paths = sorted(selected_paths[candidate_id])
        checkout = source_root / candidate_id
        entry = locked_repository(candidate, paths, covered[candidate_id])
        build[candidate_id] = entry
        pending.append((candidate_id, checkout))

    visited: set[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = set()
    dependency_edges: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    while pending:
        parent_id, checkout = pending.pop(0)
        parent = build[parent_id]
        key = (parent["url"], parent["revision"], tuple(parent["selected_paths"]), tuple(parent["covered_requirements"]))
        if key in visited:
            continue
        visited.add(key)
        dependencies = _submodule_dependencies(checkout, parent["revision"], parent["selected_paths"], parent["url"])
        dependencies.extend(_manifest_dependencies(checkout, parent["revision"], parent["selected_paths"], parent["url"]))
        for dependency in dependencies:
            if not _safe_source_path(dependency["path"]) or not re.fullmatch(r"[0-9a-f]{40}", dependency["revision"]):
                raise SourceConfigurationError(f"transitive dependency is not revision locked: {parent_id}:{dependency['path']}")
            dependency_policy = policy_by_url.get(_normalized_url(dependency["url"]))
            if not dependency_policy or dependency_policy.get("disposition", "build") != "build":
                raise SourceConfigurationError(f"transitive dependency is absent from build source policy: {dependency['url']}")
            dependency_id = dependency_policy["id"]
            edge = {
                "parent_id": parent_id, "child_id": dependency_id, "kind": dependency["kind"],
                "path": dependency["path"], "declaration_path": dependency["declaration_path"],
                "declaration_sha256": dependency["declaration_sha256"], "revision": dependency["revision"],
            }
            dependency_edges[(parent_id, dependency_id, dependency["kind"], dependency["path"], dependency["declaration_path"])] = edge
            dependency_checkout = checkout / dependency["path"]
            if not ((dependency_checkout / ".git").exists() or (dependency_checkout / ".git").is_file()):
                dependency_checkout = source_root / dependency_id
            if not ((dependency_checkout / ".git").exists() or (dependency_checkout / ".git").is_file()):
                raise SourceConfigurationError(f"transitive dependency checkout is missing: {dependency_id}")
            if dependency_id in build:
                if build[dependency_id]["revision"] != dependency["revision"]:
                    raise SourceConfigurationError(f"transitive dependency revision conflict: {dependency_id}")
                build[dependency_id]["selected_paths"] = ["."]
                build[dependency_id]["content_hash"] = _tree_content_hash(dependency_checkout, dependency["revision"], ["."])
                build[dependency_id]["covered_requirements"] = sorted(set(build[dependency_id]["covered_requirements"]) | set(parent["covered_requirements"]))
                pending.append((dependency_id, dependency_checkout))
                continue
            evidence = _locked_license_evidence(dependency_checkout, dependency["revision"], dependency_policy["license_files"])
            if dependency_policy["license"] not in context.source_policy["build_licenses"] or not evidence or len(evidence) != len(dependency_policy["license_files"]):
                raise SourceConfigurationError(f"transitive dependency license is not approved: {dependency_id}")
            build[dependency_id] = {
                "id": dependency_id,
                "url": dependency_policy["url"],
                "revision": dependency["revision"],
                "content_hash": _tree_content_hash(dependency_checkout, dependency["revision"], ["."]),
                "license": dependency_policy["license"],
                "license_evidence": evidence,
                "license_evidence_status": "found",
                "selected_paths": ["."],
                "covered_requirements": parent["covered_requirements"],
            }
            pending.append((dependency_id, dependency_checkout))

    auxiliary = {"build_tools": [], "verification_tools": [], "internal_evaluation": [], "reference_only": []}
    closure_sections = {"build_tool": "build_tools", "verification_tool": "verification_tools", "reference_only": "reference_only"}
    closure_dispositions = {"build_tool": "internal_evaluation", "verification_tool": "reference_only", "reference_only": "reference_only"}
    closure_ids: set[str] = set()
    for root_id in sorted(selected):
        root_policy = policy[root_id]
        companions = root_policy.get("companion_sources", [])
        if companions and root_policy.get("source_usage") != "target":
            raise SourceConfigurationError(f"source closure root is not a target source: {root_id}")
        for companion_id in companions:
            companion_policy = policy.get(companion_id)
            companion = candidates.get(companion_id)
            usage = companion_policy.get("source_usage") if companion_policy else None
            expected = _policy_candidate_contract(
                context, companion_policy, query_contract, selector_text, selector_weights
            ) if companion_policy else None
            if (
                not companion
                or usage not in closure_sections
                or companion_policy.get("disposition", "build") != closure_dispositions.get(usage)
                or not companion_policy.get("revision")
                or companion.get("revision") != companion_policy["revision"]
                or companion != expected
                or not all(key in companion for key in ("revision", "content_hash"))
            ):
                raise SourceConfigurationError(f"source closure companion is not pinned and classified: {root_id}:{companion_id}")
            entry = locked_repository(
                companion, companion_policy["sparse_paths"],
                set(build[root_id]["covered_requirements"]) | {f"closure:{root_id}"},
            )
            if usage != "reference_only" and (
                entry["license"] not in context.source_policy["build_licenses"]
                or not entry["license_evidence"]
                or len(entry["license_evidence"]) != len(companion_policy["license_files"])
            ):
                raise SourceConfigurationError(f"source closure companion license is not approved: {companion_id}")
            if companion_id in closure_ids:
                raise SourceConfigurationError(f"source closure companion is duplicated: {companion_id}")
            closure_ids.add(companion_id)
            auxiliary[closure_sections[usage]].append(entry)

    for candidate in candidates_contract["candidates"]:
        decision = candidate["license"]["decision"]
        usage = policy.get(candidate["id"], {}).get("source_usage")
        if candidate["id"] in build or candidate["id"] in closure_ids or usage in closure_sections or decision not in {"internal_evaluation", "reference_only"} or not all(key in candidate for key in ("revision", "content_hash")):
            continue
        requirements = candidate.get("covered_requirements", [])
        if not requirements:
            continue
        auxiliary[decision].append({
            "id": candidate["id"], "url": candidate["url"], "revision": candidate["revision"],
            "content_hash": candidate["content_hash"], "license": candidate["license"]["spdx"],
            "license_evidence": candidate["license"]["evidence"], "selected_paths": candidate["source_paths"],
            "license_evidence_status": "found" if candidate["license"]["evidence"] else "not_found",
            "covered_requirements": requirements,
        })
    reference_sections, reference_stacks, reference_edges = _reference_stack_lock(context, selector_text)
    for section, repositories in reference_sections.items():
        auxiliary[section].extend(repositories)
    for edge in reference_edges:
        dependency_edges[(edge["parent_id"], edge["child_id"], edge["kind"], edge["path"], edge["declaration_path"])] = edge
    return {
        "schema": "soc-image.source-lock.v3",
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "reference_profile_sha256": context.reference_profile_sha256,
        "software_requirements_sha256": context.software_requirements_sha256,
        "source_policy_sha256": context.source_policy_sha256,
        "source_candidates_sha256": reuse_plan["source_candidates_sha256"],
        "reuse_plan_sha256": "",
        "build": sorted(build.values(), key=lambda item: item["id"]),
        "build_tools": sorted(auxiliary["build_tools"], key=lambda item: item["id"]),
        "verification_tools": sorted(auxiliary["verification_tools"], key=lambda item: item["id"]),
        "internal_evaluation": sorted(auxiliary["internal_evaluation"], key=lambda item: item["id"]),
        "reference_only": sorted(auxiliary["reference_only"], key=lambda item: item["id"]),
        "reference_stacks": sorted(reference_stacks, key=lambda item: item["id"]),
        "dependency_edges": sorted(dependency_edges.values(), key=lambda item: (item["parent_id"], item["child_id"], item["kind"], item["path"])),
    }


def _verification_report(context: Any, query_contract: dict[str, Any], reuse_plan: dict[str, Any], lock_repositories: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "soc-image.source-discovery-verification.v2",
        "coherent_stack_pass": reuse_plan["coherence"]["passed"],
        "mandatory_roles_covered_pass": not any(item["target"].startswith("role:") for item in reuse_plan["uncovered"]),
        "license_gate_pass": all(item["license"] in context.source_policy["build_licenses"] for item in lock_repositories),
        "revision_lock_pass": all(re.fullmatch(r"[0-9a-f]{40}", item["revision"]) for item in lock_repositories) and bool(lock_repositories),
        "hardware_match_pass": bool(query_contract["identity"] or context.software_requirements["components"]),
        "anchor": reuse_plan["anchor"], "adapter_tasks": reuse_plan["adapter_tasks"], "uncovered": reuse_plan["uncovered"],
    }


def _discover(context: Any, root: Path) -> dict[str, Any]:
    Draft202012Validator(json.loads(POLICY_SCHEMA.read_text(encoding="utf-8"))).validate(context.source_policy)
    query_contract = _queries(context)
    selector_text = " ".join(
        term for query in query_contract["queries"] for term in query["terms"]
    ).lower()
    selector_weights = {
        item["value"].lower(): {"board": 30, "soc": 25, "architecture": 15, "memory": 5}.get(item["kind"], 5)
        for item in query_contract["identity"]
    }
    requirements = _requirements(query_contract)
    remote_candidates = _online_candidates(context, query_contract)
    _write(root / "queries.json", query_contract)
    _write(root / "requirements.json", {"schema": "soc-image.source-requirements.v2", "software_requirements_sha256": context.software_requirements_sha256, "requirements": requirements})
    policy_contract = [
        _policy_candidate_contract(context, item, query_contract, selector_text, selector_weights)
        for item in context.source_policy["candidates"]
    ]
    candidate_contract = {
        "schema": "soc-image.source-candidates.v2",
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "software_requirements_sha256": context.software_requirements_sha256,
        "source_policy_sha256": context.source_policy_sha256,
        "candidates": policy_contract + remote_candidates,
    }
    candidate_schema = json.loads(CANDIDATE_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(candidate_schema).validate(candidate_contract)
    _write(root / "candidates.json", candidate_contract)
    reuse_plan, selection = _solve_stack(context, candidate_contract["candidates"])
    reuse_plan["source_candidates_sha256"] = sha256(root / "candidates.json")
    Draft202012Validator(json.loads(REUSE_PLAN_SCHEMA.read_text(encoding="utf-8"))).validate(reuse_plan)
    _write(root / "selection.json", selection)
    _write(root / "reuse_plan.json", reuse_plan)
    lock = _source_lock(context, candidate_contract, reuse_plan)
    lock["reuse_plan_sha256"] = sha256(root / "reuse_plan.json")
    Draft202012Validator(json.loads(LOCK_SCHEMA.read_text(encoding="utf-8"))).validate(lock)
    _write(root / "source.lock.json", lock)
    _write(root / "license_report.json", {
        "schema": "soc-image.source-license-report.v2",
        **{
            section: [{
                "id": item["id"], "license": item["license"],
                "evidence_status": item["license_evidence_status"], "evidence": item["license_evidence"],
            } for item in lock[section]]
            for section in ("build", "build_tools", "verification_tools", "internal_evaluation", "reference_only")
        },
    })
    report = _verification_report(context, query_contract, reuse_plan, lock["build"])
    _write(root / "verification.json", report)
    return report


def _write_manifest(context: Any, root: Path) -> None:
    _write(root / "manifest.json", {
        "schema": "soc-image.source-discovery-manifest.v1",
        "task_id": context.task_id,
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "generator": "SourceDiscoveryAgent",
        "reference_profile_sha256": context.reference_profile_sha256,
        "software_requirements_sha256": context.software_requirements_sha256,
        "source_policy_sha256": context.source_policy_sha256,
        "source_candidates_sha256": sha256(root / "candidates.json"),
        "reuse_plan_sha256": sha256(root / "reuse_plan.json"),
        "source_lock_sha256": sha256(root / "source.lock.json"),
        "verification_sha256": sha256(root / "verification.json"),
    })


def generate_source_discovery(context: Any) -> dict[str, Any]:
    root = context.worktree / "generated/sources"
    existing = [(context.worktree / path).is_file() for path in context.outputs]
    if any(existing):
        stale = False
        try:
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            stale = any(manifest.get(name) != value for name, value in {
                "hardware_ir_sha256": context.hardware_ir_sha256,
                "reference_profile_sha256": context.reference_profile_sha256,
                "software_requirements_sha256": context.software_requirements_sha256,
                "source_policy_sha256": context.source_policy_sha256,
            }.items())
            integrity_errors = [] if stale else verify_source_discovery(context) if all(existing) else ["source discovery output set is incomplete"]
        except (OSError, RuntimeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            integrity_errors = [f"source discovery evidence is unreadable: {exc}"]
        if not stale:
            if integrity_errors:
                return {"status": "blocked", "outputs": [], "blocker": {"code": "source_lock_integrity", "reason": "; ".join(integrity_errors), "retryable": False, "owner": "SourceDiscoveryAgent"}}
            report = json.loads((root / "verification.json").read_text(encoding="utf-8"))
            return {"status": "passed", "outputs": list(context.outputs), "verification": report}
    try:
        report = _discover(context, root)
    except SourceNetworkError as exc:
        return {
            "status": "blocked",
            "outputs": [],
            "blocker": {"code": "source_network_unavailable", "reason": str(exc), "retryable": True, "owner": "SourceDiscoveryAgent"},
        }
    except SourceConfigurationError as exc:
        return {
            "status": "blocked",
            "outputs": [],
            "blocker": {"code": "source_search_configuration", "reason": str(exc), "retryable": False, "owner": "SourceDiscoveryAgent"},
        }
    _write_manifest(context, root)
    if not all(value is True for name, value in report.items() if name.endswith("_pass")):
        return {
            "status": "blocked", "outputs": [],
            "blocker": {"code": "source_stack_incoherent", "reason": json.dumps({"anchor": report.get("anchor"), "uncovered": report.get("uncovered", [])}, sort_keys=True), "retryable": False, "owner": "SourceDiscoveryAgent"},
        }
    return {"status": "passed", "outputs": list(context.outputs), "verification": report}


def verify_source_discovery(context: Any) -> list[str]:
    errors = [f"missing source discovery output: {path}" for path in context.outputs if not (context.worktree / path).is_file()]
    if errors:
        return errors
    root = context.worktree / "generated/sources"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("task_id") != context.task_id or manifest.get("hardware_ir_sha256") != context.hardware_ir_sha256:
        errors.append("source discovery manifest is not task and Hardware IR bound")
    if manifest.get("reference_profile_sha256") != context.reference_profile_sha256 or manifest.get("source_policy_sha256") != context.source_policy_sha256:
        errors.append("source discovery manifest is not profile and policy bound")
    if manifest.get("software_requirements_sha256") != context.software_requirements_sha256:
        errors.append("source discovery manifest is not software requirements bound")
    if manifest.get("source_lock_sha256") != sha256(root / "source.lock.json"):
        errors.append("source lock hash mismatch")
    if manifest.get("verification_sha256") != sha256(root / "verification.json"):
        errors.append("source verification hash mismatch")
    try:
        queries = json.loads((root / "queries.json").read_text(encoding="utf-8"))
        if queries != _queries(context):
            errors.append("source queries do not match software requirements")
        candidates = json.loads((root / "candidates.json").read_text(encoding="utf-8"))
        Draft202012Validator(json.loads(CANDIDATE_SCHEMA.read_text(encoding="utf-8"))).validate(candidates)
        reuse_plan = json.loads((root / "reuse_plan.json").read_text(encoding="utf-8"))
        Draft202012Validator(json.loads(REUSE_PLAN_SCHEMA.read_text(encoding="utf-8"))).validate(reuse_plan)
        if reuse_plan.get("source_candidates_sha256") != sha256(root / "candidates.json"):
            errors.append("reuse plan candidate hash mismatch")
        if manifest.get("source_candidates_sha256") != sha256(root / "candidates.json") or manifest.get("reuse_plan_sha256") != sha256(root / "reuse_plan.json"):
            errors.append("source manifest decision hash mismatch")
        expected_plan, expected_selection = _solve_stack(context, candidates["candidates"])
        expected_plan["source_candidates_sha256"] = sha256(root / "candidates.json")
        selection = json.loads((root / "selection.json").read_text(encoding="utf-8"))
        if reuse_plan != expected_plan or selection != expected_selection:
            errors.append("source stack selection is not the deterministic solver result")
        lock = json.loads((root / "source.lock.json").read_text(encoding="utf-8"))
        Draft202012Validator(json.loads(LOCK_SCHEMA.read_text(encoding="utf-8"))).validate(lock)
        expected_lock = _source_lock(context, candidates, reuse_plan)
        expected_lock["reuse_plan_sha256"] = sha256(root / "reuse_plan.json")
        if lock != expected_lock:
            errors.append("source lock is not the complete candidate and reuse-plan closure")
        verification = json.loads((root / "verification.json").read_text(encoding="utf-8"))
        if verification != _verification_report(context, queries, reuse_plan, lock["build"]):
            errors.append("source verification is not the deterministic solver report")
    except (OSError, RuntimeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    return errors


def _promoted_sources(context: Any) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    root = context.worktree / "generated/sources"
    manifest_path = root / "manifest.json"
    plan_path = root / "reuse_plan.json"
    lock_path = root / "source.lock.json"
    candidates_path = root / "candidates.json"
    if not manifest_path.is_file() or not plan_path.is_file() or not candidates_path.is_file() or not lock_path.is_file():
        raise RuntimeError("promoted source plan and lock are unavailable")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    Draft202012Validator(json.loads(CANDIDATE_SCHEMA.read_text(encoding="utf-8"))).validate(candidates)
    Draft202012Validator(json.loads(REUSE_PLAN_SCHEMA.read_text(encoding="utf-8"))).validate(plan)
    Draft202012Validator(json.loads(LOCK_SCHEMA.read_text(encoding="utf-8"))).validate(lock)
    expected = {
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "reference_profile_sha256": context.reference_profile_sha256,
        "software_requirements_sha256": context.software_requirements_sha256,
        "source_policy_sha256": context.source_policy_sha256,
        "source_candidates_sha256": sha256(candidates_path),
        "reuse_plan_sha256": sha256(plan_path),
    }
    if (
        any(lock.get(name) != value for name, value in expected.items())
        or plan.get("source_candidates_sha256") != expected["source_candidates_sha256"]
        or manifest.get("source_candidates_sha256") != expected["source_candidates_sha256"]
        or manifest.get("reuse_plan_sha256") != expected["reuse_plan_sha256"]
        or manifest.get("source_lock_sha256") != sha256(lock_path)
    ):
        raise RuntimeError("source lock does not match downstream task inputs")
    expected_plan, _ = _solve_stack(context, candidates["candidates"])
    expected_plan["source_candidates_sha256"] = expected["source_candidates_sha256"]
    if plan != expected_plan:
        raise RuntimeError("source plan is not the deterministic solver result")
    expected_lock = _source_lock(context, candidates, plan)
    expected_lock["reuse_plan_sha256"] = expected["reuse_plan_sha256"]
    if lock != expected_lock:
        raise RuntimeError("source lock is not the deterministic build-only closure")
    return lock_path, plan, lock


def _resolve_build_source(context: Any, lock_path: Path, lock: dict[str, Any], candidate_id: str, label: str) -> dict[str, Any]:
    repositories = [item for item in lock["build"] if item["id"] == candidate_id]
    if len(repositories) != 1:
        raise RuntimeError(f"selected build source is absent from lock: {label}")
    repository = repositories[0]
    checkout = Path(getattr(context, "source_root", ROOT / "third_party")) / repository["id"]
    revision = repository["revision"]
    if not checkout.is_dir() or not re.fullmatch(r"[0-9a-f]{40}", revision) or not all(_safe_source_path(path) for path in repository["selected_paths"]):
        raise RuntimeError(f"locked source checkout, revision, or path is invalid: {label}")
    try:
        content_hash = _tree_content_hash(checkout, revision, repository["selected_paths"])
        evidence = _locked_license_evidence(checkout, revision, [item["path"] for item in repository["license_evidence"]])
    except (RuntimeError, SourceConfigurationError) as exc:
        raise RuntimeError(f"locked source cannot be resolved: {label}: {exc}") from exc
    if content_hash != repository["content_hash"] or evidence != repository["license_evidence"]:
        raise RuntimeError(f"locked source content or license hash mismatch: {label}")
    return {**repository, "path": checkout, "source_lock_sha256": sha256(lock_path)}


def _target_source(context: Any, kind: str, identifier: str) -> dict[str, Any]:
    lock_path, plan, lock = _promoted_sources(context)
    entries = [item for item in plan["entries"] if item["target"] == {"kind": kind, "id": identifier} and item["disposition"] == "reuse"]
    if len(entries) != 1 or len(entries[0]["candidate_ids"]) != 1:
        raise RuntimeError(f"source target does not have one compatibility source: {kind}:{identifier}")
    return _resolve_build_source(context, lock_path, lock, entries[0]["candidate_ids"][0], f"{kind}:{identifier}")


def selected_anchor(context: Any) -> dict[str, Any]:
    """Return the verified build-only anchor selected by the coherent stack solver."""
    lock_path, plan, lock = _promoted_sources(context)
    if not plan.get("anchor"):
        raise RuntimeError("source stack has no selected anchor")
    return _resolve_build_source(context, lock_path, lock, plan["anchor"], "anchor")


def selected_component_source(context: Any, requirement_id: str) -> dict[str, Any]:
    """Return the verified build-only source selected for one hardware component."""
    return _target_source(context, "component", requirement_id)


def selected_source(context: Any, role: str) -> dict[str, Any]:
    """Compatibility entry for consumers that still select one primary role source."""
    return _target_source(context, "role", role)


def selftest() -> None:
    policy = json.loads((ROOT / "config/source_policy.json").read_text(encoding="utf-8"))
    Draft202012Validator(json.loads(POLICY_SCHEMA.read_text(encoding="utf-8"))).validate(policy)
    canmv_policy = next(item for item in policy["candidates"] if item["id"] == "canmv-k230")
    assert canmv_policy["license"] == "NOASSERTION" and canmv_policy["disposition"] == "internal_evaluation"
    weights = {"k230": 25, "usb": 5}
    offline = type("Context", (), {"source_policy": policy, "source_root": ROOT / "selftest-does-not-exist"})()
    k230 = _candidate(offline, next(item for item in policy["candidates"] if item["id"] == "k230-sdk"), "k230 usb", weights)
    usb = _candidate(offline, next(item for item in policy["candidates"] if item["id"] == "tinyusb"), "k230 usb", weights)
    canmv = _candidate(offline, canmv_policy, "k230 canmv", weights)
    assert k230["score"] > usb["score"]
    assert canmv["license_decision"] == "internal_evaluation" and not canmv["eligible"]
    reuse_schema = json.loads(REUSE_PLAN_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(reuse_schema)
    for name in ("source_candidate.schema.json", "source_lock.schema.json"):
        Draft202012Validator.check_schema(json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8")))
    with tempfile.TemporaryDirectory() as tmp:
        temporary = Path(tmp)
        source_root = temporary / "sources"
        checkout = source_root / "fixture-stack"
        checkout.mkdir(parents=True)
        (checkout / "LICENSE").write_text("MIT\n", encoding="utf-8")
        (checkout / "README.md").write_text("fixture\n", encoding="utf-8")
        (checkout / "drivers/camera").mkdir(parents=True)
        (checkout / "drivers/camera/camera.c").write_text("/* fixture */\n", encoding="utf-8")
        _git(checkout, "init", "--quiet")
        _git(checkout, "config", "user.email", "selftest@example.invalid")
        _git(checkout, "config", "user.name", "source selftest")
        _git(checkout, "add", "LICENSE", "README.md", "drivers/camera/camera.c")
        _git(checkout, "commit", "--quiet", "-m", "fixture")
        fixture_revision = _git(checkout, "rev-parse", "HEAD")
        (checkout / "LICENSE").write_text("tampered worktree\n", encoding="utf-8")
        evaluation_checkout = source_root / "evaluation-only"
        evaluation_checkout.mkdir()
        (evaluation_checkout / "README.md").write_text("evaluation oracle\n", encoding="utf-8")
        _git(evaluation_checkout, "init", "--quiet")
        _git(evaluation_checkout, "config", "user.email", "selftest@example.invalid")
        _git(evaluation_checkout, "config", "user.name", "source selftest")
        _git(evaluation_checkout, "add", "README.md")
        _git(evaluation_checkout, "commit", "--quiet", "-m", "evaluation")
        companion_revisions = {}
        for name, files in {
            "fixture-build-tool": {"LICENSE": "MIT\n", "tool.py": "print('build tool')\n"},
            "fixture-verification-tool": {"LICENSE": "MIT\n", "inventory.json": "{}\n"},
            "fixture-reference": {"NOTICE": "mixed file-level terms\n", "reference.txt": "review only\n"},
        }.items():
            companion_checkout = source_root / name
            companion_checkout.mkdir()
            for relative, content in files.items():
                (companion_checkout / relative).write_text(content, encoding="utf-8")
            _git(companion_checkout, "init", "--quiet")
            _git(companion_checkout, "config", "user.email", "selftest@example.invalid")
            _git(companion_checkout, "config", "user.name", "source selftest")
            _git(companion_checkout, "add", ".")
            _git(companion_checkout, "commit", "--quiet", "-m", "companion")
            companion_revisions[name] = _git(companion_checkout, "rev-parse", "HEAD")
        fixture_policy = {
            "schema": "soc-image.source-policy.v1",
            "mandatory_roles": policy["mandatory_roles"],
            "build_licenses": ["MIT"],
            "reference_stacks": [],
            "candidates": [{
                "id": "fixture-stack",
                "url": "https://example.invalid/fixture-stack.git",
                "revision": fixture_revision,
                "roles": policy["mandatory_roles"],
                "selectors": ["k230"],
                "license": "MIT",
                "license_files": ["LICENSE"],
                "sparse_paths": ["LICENSE", "README.md", "drivers"],
                "source_usage": "target",
                "companion_sources": ["fixture-build-tool", "fixture-verification-tool", "fixture-reference"],
            }, {
                "id": "fixture-build-tool", "url": "https://example.invalid/build-tool.git",
                "revision": companion_revisions["fixture-build-tool"], "roles": ["product"], "selectors": ["k230"],
                "license": "MIT", "disposition": "internal_evaluation", "license_files": ["LICENSE"],
                "sparse_paths": ["LICENSE", "tool.py"], "source_usage": "build_tool",
            }, {
                "id": "fixture-verification-tool", "url": "https://example.invalid/verification-tool.git",
                "revision": companion_revisions["fixture-verification-tool"], "roles": ["product"], "selectors": ["k230"],
                "license": "MIT", "disposition": "reference_only", "license_files": ["LICENSE"],
                "sparse_paths": ["LICENSE", "inventory.json"], "source_usage": "verification_tool",
            }, {
                "id": "fixture-reference", "url": "https://example.invalid/reference.git",
                "revision": companion_revisions["fixture-reference"], "roles": ["product"], "selectors": ["k230"],
                "license": "MIXED", "disposition": "reference_only", "license_files": ["NOTICE"],
                "sparse_paths": ["reference.txt"], "source_usage": "reference_only",
            }, {
                "id": "evaluation-only",
                "url": "https://example.invalid/evaluation.git",
                "roles": ["product"],
                "selectors": ["k230"],
                "license": "NOASSERTION",
                "disposition": "internal_evaluation",
                "license_files": [],
                "sparse_paths": ["README.md"],
            }],
        }
        network_calls: list[str] = []

        def empty_search(query: str) -> tuple[list[dict[str, str]], list[str]]:
            network_calls.append(query)
            if query.endswith(" sdk"):
                return [{"id": "github/example/k230", "forge": "github", "url": "https://github.com/example/k230.git", "description": "K230 SDK", "license": "MIT"}], []
            return [], []

        def inspect_reference(item: dict[str, Any], licenses: list[str]) -> dict[str, Any]:
            return {
                "revision": "a" * 40,
                "content_hash": {"algorithm": "sha256-git-ls-tree-v1", "value": "b" * 64},
                "source_paths": ["README.md"],
                "license_evidence": [{"path": "LICENSE", "sha256": "c" * 64}],
                "license_decision": "reference_only",
                "build_docs": True,
                "tests": False,
            }

        output_paths = tuple(
            item["provider"]["outputs"]
            for item in json.loads((ROOT / "engine/capabilities.json").read_text(encoding="utf-8"))["capabilities"]
            if item["id"] == "source_discovery"
        )[0]
        worktree = temporary / "worktree"
        worktree.mkdir()
        context = type(
            "Context",
            (),
            {
                "source_root": source_root,
                "source_search": staticmethod(empty_search),
                "source_inspect": staticmethod(inspect_reference),
                "worktree": worktree,
                "task_id": "task:source_discovery",
                "outputs": output_paths,
                "hardware_ir": {
                    "observations": [{"text": "CanMV K230 LPDDR4 camera display audio USB", "sources": [{"locator": "fixture"}]}],
                    "cpu": {"isa": {"value": "rv64gc"}},
                },
                "reference_profile": {"enabled_capabilities": [{"id": "camera", "basis": ["fixture"]}]},
                "software_requirements": {
                    "board_identity": [
                        {"kind": "board", "value": "canmv-k230", "state": "candidate", "basis": ["fixture:board"]},
                        {"kind": "soc", "value": "k230", "state": "candidate", "basis": ["fixture:soc"]},
                        {"kind": "architecture", "value": "riscv", "state": "standard_derived", "basis": ["cpu.isa"]},
                    ],
                    "software_roles": fixture_policy["mandatory_roles"],
                    "components": [{
                        "id": "camera@1000",
                        "class": "camera",
                        "compatible": ["ovti,ov5647"],
                        "required_interfaces": ["clock", "dma", "irq"],
                        "hardware_basis": ["peripherals.camera@1000"],
                        "evidence_state": "candidate",
                        "search_terms": ["canmv-k230 camera driver", "ovti,ov5647 driver"],
                        "reuse_allowed": True,
                        "generated_mmio_allowed": False,
                    }],
                },
                "hardware_ir_sha256": "1" * 64,
                "reference_profile_sha256": "2" * 64,
                "software_requirements_sha256": "3" * 64,
                "source_policy": fixture_policy,
                "source_policy_sha256": "4" * 64,
            },
        )()
        result = generate_source_discovery(context)
        assert result["status"] == "passed", result
        output = worktree / "generated/sources"
        assert not verify_source_discovery(context)
        candidates = json.loads((output / "candidates.json").read_text(encoding="utf-8"))
        Draft202012Validator(json.loads((ROOT / "schemas/source_candidate.schema.json").read_text(encoding="utf-8"))).validate(candidates)
        reuse_plan = json.loads((output / "reuse_plan.json").read_text(encoding="utf-8"))
        Draft202012Validator(reuse_schema).validate(reuse_plan)
        lock_path = output / "source.lock.json"
        lock_text = lock_path.read_text(encoding="utf-8")
        lock = json.loads(lock_text)
        Draft202012Validator(json.loads(LOCK_SCHEMA.read_text(encoding="utf-8"))).validate(lock)
        assert lock["schema"] == "soc-image.source-lock.v3" and [item["id"] for item in lock["build"]] == ["fixture-stack"]
        assert [item["id"] for item in lock["build_tools"]] == ["fixture-build-tool"]
        assert [item["id"] for item in lock["verification_tools"]] == ["fixture-verification-tool"]
        license_report = json.loads((output / "license_report.json").read_text(encoding="utf-8"))
        for section, companion_id in (("build_tools", "fixture-build-tool"), ("verification_tools", "fixture-verification-tool")):
            locked = next(item for item in lock[section] if item["id"] == companion_id)
            reported = next(item for item in license_report[section] if item["id"] == companion_id)
            assert reported["evidence_status"] == "found" and reported["evidence"] == locked["license_evidence"]
        assert any(item["id"] == "fixture-reference" for item in lock["reference_only"])
        for section, companion_id in (("build_tools", "fixture-build-tool"), ("verification_tools", "fixture-verification-tool"), ("reference_only", "fixture-reference")):
            assert next(item for item in lock[section] if item["id"] == companion_id)["revision"] == companion_revisions[companion_id]
        assert [item["id"] for item in lock["internal_evaluation"]] == ["evaluation-only"]
        assert all(item["id"] != "github/example/k230" for item in lock["build"])
        assert selected_anchor(context)["id"] == "fixture-stack"
        assert selected_source(context, "bsp")["id"] == "fixture-stack"
        assert selected_component_source(context, "camera@1000")["id"] == "fixture-stack"
        from engine.source_export import export_locked_build_source
        exported_build = temporary / "public-build-export"
        export_locked_build_source(context, "fixture-stack", exported_build)
        assert (exported_build / "README.md").read_text(encoding="utf-8") == "fixture\n"
        try:
            export_locked_build_source(context, "evaluation-only", temporary / "rejected-evaluation-export")
            raise AssertionError("internal-evaluation source entered build export")
        except RuntimeError as exc:
            assert "absent from promoted source lock" in str(exc)
        for companion_id in ("fixture-build-tool", "fixture-verification-tool", "fixture-reference"):
            try:
                export_locked_build_source(context, companion_id, temporary / f"rejected-{companion_id}")
                raise AssertionError(f"non-target source entered build export: {companion_id}")
            except RuntimeError as exc:
                assert "absent from promoted source lock" in str(exc)
        assert reuse_plan["anchor"] == "fixture-stack"
        assert len(reuse_plan["entries"]) == len(fixture_policy["mandatory_roles"]) + len(context.software_requirements["components"])
        queries = json.loads((output / "queries.json").read_text(encoding="utf-8"))
        camera_query = next(item for item in queries["queries"] if item["id"] == "component:camera@1000")
        assert camera_query["terms"] == ["canmv-k230 camera driver", "ovti,ov5647 driver"]
        assert all("observations" not in json.dumps(item) for item in queries["queries"])
        assert len(network_calls) == 4
        assert generate_source_discovery(context)["status"] == "passed"
        assert len(network_calls) == 4
        fixture = next(item for item in candidates["candidates"] if item["id"] == "fixture-stack")
        assert fixture["license"]["evidence"][0]["sha256"] == hashlib.sha256(b"MIT\n").hexdigest()
        remote = next(item for item in candidates["candidates"] if item["id"] == "github/example/k230")
        assert remote["status"] == "reference_only" and remote["license"]["decision"] == "reference_only"
        assert all(item["id"] != "evaluation-only" for item in lock["build"])
        evaluation_candidate = next(item for item in candidates["candidates"] if item["id"] == "evaluation-only")
        poisoned_candidate = {
            **evaluation_candidate,
            "status": "usable",
            "license": {**evaluation_candidate["license"], "decision": "build", "spdx": "MIT", "evidence": [{"path": "README.md", "sha256": "0" * 64}]},
            "errors": [],
        }
        poisoned_plan = {
            "source_candidates_sha256": "0" * 64,
            "entries": [{"id": "role:product", "target": {"kind": "role", "id": "product"}, "disposition": "reuse", "candidate_ids": ["evaluation-only"], "source_paths": ["README.md"], "strategy": "direct", "basis": ["fixture"]}],
        }
        try:
            _source_lock(context, {"candidates": [poisoned_candidate]}, poisoned_plan)
            raise AssertionError("internal evaluation source entered build after synchronized candidate and plan rewrite")
        except SourceConfigurationError as exc:
            assert "non-build candidate" in str(exc)
        fixture_candidate = next(item for item in candidates["candidates"] if item["id"] == "fixture-stack")
        rewritten_fixture = {**fixture_candidate, "roles": ["boot"], "covered_requirements": ["role:boot"]}
        try:
            _source_lock(context, {"candidates": [rewritten_fixture]}, {
                "source_candidates_sha256": "0" * 64,
                "entries": [{"id": "role:boot", "target": {"kind": "role", "id": "boot"}, "disposition": "reuse", "candidate_ids": ["fixture-stack"], "source_paths": fixture_candidate["source_paths"], "strategy": "direct", "basis": ["fixture"]}],
            })
            raise AssertionError("policy build candidate rewrite entered source lock")
        except SourceConfigurationError as exc:
            assert "non-build candidate" in str(exc)

        invalid_revision = json.loads(lock_text)
        invalid_revision["build"][0]["revision"] = "short"
        try:
            Draft202012Validator(json.loads(LOCK_SCHEMA.read_text(encoding="utf-8"))).validate(invalid_revision)
            raise AssertionError("short source revision passed lock schema")
        except ValidationError:
            pass
        unsafe_path = json.loads(lock_text)
        unsafe_path["build"][0]["selected_paths"] = ["../escape"]
        _write(lock_path, unsafe_path)
        assert generate_source_discovery(context)["blocker"]["code"] == "source_lock_integrity"
        lock_path.write_text(lock_text, encoding="utf-8")
        changed_hash = json.loads(lock_text)
        changed_hash["build"][0]["content_hash"]["value"] = "0" * 64
        _write(lock_path, changed_hash)
        assert generate_source_discovery(context)["blocker"]["code"] == "source_lock_integrity"
        lock_path.write_text(lock_text, encoding="utf-8")
        reference_in_build = json.loads(lock_text)
        reference_in_build["build"].append(reference_in_build["reference_only"][0])
        _write(lock_path, reference_in_build)
        assert generate_source_discovery(context)["blocker"]["code"] == "source_lock_integrity"
        lock_path.write_text(lock_text, encoding="utf-8")

        base_candidate = {
            "forge": "other", "source_type": "git", "url": "https://example.invalid/source.git",
            "components": [], "source_paths": ["src"], "covered_requirements": [], "match_evidence": [],
            "license": {"spdx": "MIT", "decision": "build", "evidence": [{"path": "LICENSE", "sha256": "d" * 64}]},
            "revision": "e" * 40, "content_hash": {"algorithm": "sha256-git-ls-tree-v1", "value": "f" * 64},
            "build_docs": True, "tests": True, "status": "usable", "errors": [],
        }
        anchor_candidate = {**base_candidate, "id": "anchor", "roles": ["boot", "bsp", "driver", "os", "runtime", "image_tool"], "match": {"level": "exact_soc", "architecture_compatible": True, "board_config": True, "os_abi": "rt-smart", "media_abi": "vendor-media"}}
        product_candidate = {**base_candidate, "id": "product", "url": "https://example.invalid/product.git", "roles": ["product"], "match": {"level": "class", "architecture_compatible": True, "board_config": False, "os_abi": "rt-thread", "media_abi": None}}
        camera_candidate = {**base_candidate, "id": "camera", "url": "https://example.invalid/camera.git", "roles": ["driver"], "components": ["camera0"], "source_paths": ["drivers/camera"], "match": {"level": "exact_board", "architecture_compatible": True, "board_config": True, "os_abi": "rt-smart", "media_abi": "vendor-media"}}
        boot_competitor = {**base_candidate, "id": "boot-only", "url": "https://example.invalid/boot.git", "roles": ["boot"], "match": {"level": "exact_board", "architecture_compatible": True, "board_config": True, "os_abi": "rt-smart", "media_abi": "vendor-media"}}
        component_requirement = {"id": "camera0", "class": "camera", "hardware_basis": ["peripherals.camera0"], "generated_mmio_allowed": False}
        solver_context = type("SolverContext", (), {"hardware_ir_sha256": "1" * 64, "software_requirements_sha256": "3" * 64, "source_policy_sha256": "4" * 64, "source_policy": {"build_licenses": ["MIT"]}, "software_requirements": {"software_roles": ["boot", "bsp", "driver", "os", "runtime", "product", "image_tool"], "components": [component_requirement]}})()
        solved, solved_selection = _solve_stack(solver_context, [anchor_candidate, product_candidate, camera_candidate, boot_competitor])
        assert solved["anchor"] == "anchor" and solved["coherence"]["passed"]
        assert solved["adapter_tasks"] == [{"id": "adapter:os_abi:product", "reason": "os_abi mismatch: rt-thread -> rt-smart", "from_candidate": "product", "to_anchor": "anchor"}]
        assert next(item for item in solved_selection["selected"] if item["role"] == "boot")["candidate"] == "anchor"
        assert solved_selection["components"] == [{"component": "camera0", "candidate": "camera", "score": 140}]
        architecture_conflict = {**anchor_candidate, "id": "wrong-arch", "match": {**anchor_candidate["match"], "architecture_compatible": False}}
        unknown_license = {**anchor_candidate, "id": "unknown-license", "license": {**anchor_candidate["license"], "spdx": "NOASSERTION"}}
        assert _candidate_score(architecture_conflict) is None and _candidate_score(unknown_license) is None
        unknown_media = {**camera_candidate, "id": "unknown-media", "match": {**camera_candidate["match"], "media_abi": None}}
        blocked_media, _ = _solve_stack(solver_context, [anchor_candidate, product_candidate, unknown_media])
        assert not blocked_media["coherence"]["passed"] and any("media ABI is unknown" in item["reason"] for item in blocked_media["uncovered"])

        dependency = temporary / "dependency-origin"
        dependency.mkdir()
        (dependency / "LICENSE").write_text("MIT\n", encoding="utf-8")
        (dependency / "dep.c").write_text("/* dependency */\n", encoding="utf-8")
        _git(dependency, "init", "--quiet")
        _git(dependency, "config", "user.email", "selftest@example.invalid")
        _git(dependency, "config", "user.name", "source selftest")
        _git(dependency, "add", ".")
        _git(dependency, "commit", "--quiet", "-m", "dependency")
        dependency_revision = _git(dependency, "rev-parse", "HEAD")
        parent = temporary / "parent"
        parent.mkdir()
        (parent / "LICENSE").write_text("MIT\n", encoding="utf-8")
        _git(parent, "init", "--quiet")
        _git(parent, "config", "user.email", "selftest@example.invalid")
        _git(parent, "config", "user.name", "source selftest")
        _git(parent, "-c", "protocol.file.allow=always", "submodule", "add", "--quiet", str(dependency), "vendor/dep")
        (parent / ".gitmodules").write_text('[submodule "vendor/dep"]\n\tpath = vendor/dep\n\turl = ./dep.git\n', encoding="utf-8")
        (parent / "included.xml").write_text(
            f'<manifest><remote name="origin" fetch="./parent.git/" revision="{"f" * 40}"/></manifest>\n',
            encoding="utf-8",
        )
        (parent / "manifests").mkdir()
        (parent / "manifests/manifest.xml").write_text(
            f'<manifest><project name="dep.git" path="vendor/original" remote="origin"/><extend-project name="dep.git" revision="{dependency_revision}" dest-path="vendor/dep"/><include name="included.xml"/></manifest>\n',
            encoding="utf-8",
        )
        _git(parent, "add", ".")
        _git(parent, "commit", "--quiet", "-m", "parent")
        parent_revision = _git(parent, "rev-parse", "HEAD")
        assert len(_submodule_dependencies(parent, parent_revision, ["."], "https://example.invalid/org/parent.git")) == 1
        manifest_dependencies = _manifest_dependencies(parent, parent_revision, ["."], "https://example.invalid/org/parent.git")
        assert len(manifest_dependencies) == 1 and manifest_dependencies[0]["revision"] == dependency_revision and manifest_dependencies[0]["path"] == "vendor/dep"
        nested_manifest = temporary / "nested-manifest"
        nested_manifest.mkdir()
        (nested_manifest / "manifest.xml").write_text(
            f'<manifest><remote name="origin" fetch="https://example.invalid/src/" revision="{dependency_revision}"/><default remote="origin"/><project name="outer" path="vendor"><project name="dep.git" path="inner"/></project></manifest>\n',
            encoding="utf-8",
        )
        _git(nested_manifest, "init", "--quiet")
        _git(nested_manifest, "config", "user.email", "selftest@example.invalid")
        _git(nested_manifest, "config", "user.name", "source selftest")
        _git(nested_manifest, "add", "manifest.xml")
        _git(nested_manifest, "commit", "--quiet", "-m", "nested manifest")
        nested_dependencies = _manifest_dependencies(nested_manifest, _git(nested_manifest, "rev-parse", "HEAD"), ["."], "https://example.invalid/manifests.git")
        assert {(item["path"], item["revision"]) for item in nested_dependencies} == {("vendor", dependency_revision), ("vendor/inner", dependency_revision)}
        parent_policy = {
            "id": "parent", "url": "https://example.invalid/org/parent.git",
            "roles": ["boot", "bsp", "driver", "image_tool"], "selectors": ["fixture"],
            "license": "MIT", "license_files": ["LICENSE"], "sparse_paths": ["."],
        }
        dependency_context = type("DependencyContext", (), {
            "hardware_ir_sha256": "1" * 64, "reference_profile_sha256": "2" * 64,
            "software_requirements_sha256": "3" * 64, "source_policy_sha256": "4" * 64,
            "source_root": temporary, "source_policy": {
                "build_licenses": ["MIT"],
                "candidates": [parent_policy],
            },
            "software_requirements": {
                "board_identity": [{"kind": "board", "value": "fixture", "state": "candidate", "basis": ["fixture"]}],
                "software_roles": ["boot", "bsp", "driver", "image_tool"], "components": [],
            },
        })()
        dependency_queries = _queries(dependency_context)
        parent_candidate = _policy_candidate_contract(
            dependency_context, parent_policy, dependency_queries,
            " ".join(term for query in dependency_queries["queries"] for term in query["terms"]).lower(),
            {"fixture": 30},
        )
        dependency_plan = {
            "source_candidates_sha256": "5" * 64,
            "entries": [{"id": "role:boot", "target": {"kind": "role", "id": "boot"}, "disposition": "reuse", "candidate_ids": ["parent"], "source_paths": ["."], "strategy": "direct", "basis": ["fixture"]}],
        }
        dependency_contract = {"candidates": [parent_candidate]}
        try:
            _source_lock(dependency_context, dependency_contract, dependency_plan)
            raise AssertionError("unlisted transitive dependency entered build lock")
        except SourceConfigurationError as exc:
            assert "absent from build source policy" in str(exc)
        dependency_context.source_policy["candidates"].append({
            "id": "dep", "url": "https://example.invalid/org/parent.git/dep.git", "roles": ["driver"], "selectors": ["fixture"],
            "license": "MIT", "license_files": ["LICENSE"], "sparse_paths": ["."],
        })
        detached_dependency = temporary / "detached-dependency"
        (parent / "vendor/dep").rename(detached_dependency)
        try:
            _source_lock(dependency_context, dependency_contract, dependency_plan)
            raise AssertionError("missing transitive checkout entered build lock")
        except SourceConfigurationError as exc:
            assert "checkout is missing" in str(exc)
        detached_dependency.rename(parent / "vendor/dep")
        dependency_lock = _source_lock(dependency_context, dependency_contract, dependency_plan)
        assert {item["id"] for item in dependency_lock["build"]} == {"parent", "dep"}
        assert {(item["kind"], item["declaration_path"]) for item in dependency_lock["dependency_edges"]} == {
            ("git_submodule", ".gitmodules"), ("repo_manifest", "manifests/manifest.xml")
        }
        reference_manifest = temporary / "reference.lock.xml"
        reference_manifest.write_text(
            f'<manifest><remote name="origin" fetch="https://example.invalid/"/><project name="org/parent" path="." remote="origin" revision="{parent_revision}"/><project name="org/dep" path="vendor/dep" remote="origin" revision="{dependency_revision}"/></manifest>\n',
            encoding="utf-8",
        )
        _git(parent, "remote", "add", "github", "https://example.invalid/org/parent")
        _git(parent / "vendor/dep", "remote", "add", "github", "https://example.invalid/org/dep")
        dependency_context.policy_root = temporary
        dependency_context.source_policy["reference_stacks"] = [{
            "id": "fixture-reference", "decision": "internal_evaluation", "selectors": ["fixture"],
            "workspace": "parent", "manifest": "reference.lock.xml", "expected_repositories": 2,
        }]
        reference_lock = _source_lock(dependency_context, dependency_contract, dependency_plan)
        assert len(reference_lock["reference_stacks"]) == 1
        assert len(reference_lock["reference_stacks"][0]["repositories"]) == 2
        assert len([item for item in reference_lock["internal_evaluation"] if item["id"].startswith("fixture-reference/")]) == 2
        reference_entries = [item for item in reference_lock["internal_evaluation"] if item["id"].startswith("fixture-reference/")]
        assert {item["license_evidence_status"] for item in reference_entries} == {"found"}
        _git(parent / "vendor/dep", "remote", "set-url", "github", "https://example.invalid/org/wrong")
        try:
            _source_lock(dependency_context, dependency_contract, dependency_plan)
            raise AssertionError("mismatched reference remote entered source lock")
        except SourceConfigurationError as exc:
            assert "remote does not match manifest" in str(exc)
        _git(parent / "vendor/dep", "remote", "set-url", "github", "https://example.invalid/org/dep")

        context.source_search = lambda query: ([], ["github: timeout"])
        original_worktree = context.worktree
        context.worktree = temporary / "blocked-worktree"
        context.worktree.mkdir()
        blocked = generate_source_discovery(context)
        assert blocked["status"] == "blocked" and blocked["outputs"] == []
        assert blocked["blocker"]["retryable"] is True
        context.worktree = original_worktree
        verification_path = output / "verification.json"
        verification_text = verification_path.read_text(encoding="utf-8")
        verification = json.loads(verification_text)
        verification["anchor"] = "tampered"
        _write(verification_path, verification)
        verification_integrity = generate_source_discovery(context)
        assert verification_integrity["status"] == "blocked" and verification_integrity["blocker"]["code"] == "source_lock_integrity"
        verification_path.write_text(verification_text, encoding="utf-8")
        (output / "candidates.json").write_text("{}\n", encoding="utf-8")
        integrity = generate_source_discovery(context)
        assert integrity["status"] == "blocked" and integrity["blocker"]["retryable"] is False
        context.software_requirements_sha256 = "5" * 64
        stale = generate_source_discovery(context)
        assert stale["status"] == "blocked" and stale["blocker"]["code"] == "source_network_unavailable"
        try:
            _online_candidates(context, _queries(context))
            raise AssertionError("network failure was not blocked")
        except SourceNetworkError:
            pass

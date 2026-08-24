#!/usr/bin/env python3
"""Fetch closest public driver sources into a local reuse corpus."""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:
    from tools.driver_adapt import PERIPHERAL_KEYWORDS, hardware_profile, load_target
except ModuleNotFoundError:  # pragma: no cover
    from driver_adapt import PERIPHERAL_KEYWORDS, hardware_profile, load_target


ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = (".c", ".h", ".cc", ".cpp")
SKIP_PARTS = {".github", "applications", "benchmark", "benchmarks", "docs", "test", "tests", "examples"}
SEED_REPOS = (
    {"full_name": "RT-Thread/rt-thread", "default_branch": "master", "html_url": "https://github.com/RT-Thread/rt-thread"},
    {
        "full_name": "kendryte/kendryte-standalone-sdk",
        "default_branch": "develop",
        "html_url": "https://github.com/kendryte/kendryte-standalone-sdk",
    },
    {"full_name": "Nuclei-Software/NMSIS", "default_branch": "master", "html_url": "https://github.com/Nuclei-Software/NMSIS"},
    {"full_name": "hathach/tinyusb", "default_branch": "master", "html_url": "https://github.com/hathach/tinyusb"},
    {"full_name": "T-head-Semi/wujian100_open", "default_branch": "master", "html_url": "https://github.com/T-head-Semi/wujian100_open"},
)
LOCAL_SEEDS = {
    "RT-Thread/rt-thread": ROOT / "third_party/rt-thread",
    "kendryte/kendryte-standalone-sdk": ROOT / "third_party/kendryte-standalone-sdk",
    "Nuclei-Software/NMSIS": ROOT / "third_party/NMSIS",
    "hathach/tinyusb": ROOT / "third_party/tinyusb",
    "T-head-Semi/wujian100_open": ROOT / "third_party/wujian100_open",
}


def api_json(url: str, timeout: float = 20.0) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "adam-chip-driver-reuse"})
    with urllib.request.urlopen(req, timeout=timeout) as fh:  # noqa: S310 - public GitHub API URL built below.
        return json.loads(fh.read().decode("utf-8"))


def fetch_text(url: str, timeout: float = 20.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "adam-chip-driver-reuse"})
    with urllib.request.urlopen(req, timeout=timeout) as fh:  # noqa: S310 - public raw GitHub URL built below.
        return fh.read().decode("utf-8", errors="ignore")


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value).strip("_") or "repo"


def repo_queries(profile: dict[str, Any]) -> list[str]:
    queries = [
        "RT-Thread RISC-V UART driver",
        "RT-Thread DMA driver RISC-V",
        "RISC-V PLIC CLINT RT-Thread driver",
    ]
    if profile.get("uart", {}).get("kind"):
        queries.append(f"RT-Thread {profile['uart']['kind']} UART driver")
    if "usb" in profile.get("peripherals", []):
        queries += ["TinyUSB RT-Thread USB device driver", "TinyUSB RISC-V board support package"]
    if profile.get("npu", {}).get("enabled"):
        queries += ["Kendryte KPU RT-Thread driver", "RISC-V NPU driver RT-Thread"]
    return queries


def search_repos(query: str, limit: int) -> list[dict[str, Any]]:
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": query, "sort": "stars", "order": "desc", "per_page": str(limit)}
    )
    return api_json(url).get("items", [])


def matching_paths(tree: dict[str, Any], peripherals: list[str], limit: int) -> list[dict[str, str]]:
    paths = []
    for item in tree.get("tree", []):
        path = item.get("path", "")
        low = path.lower()
        if item.get("type") != "blob" or not low.endswith(SUFFIXES):
            continue
        if any(part in SKIP_PARTS for part in low.split("/")):
            continue
        matched, score = score_path(path, peripherals)
        if matched:
            paths.append({"path": path, "peripherals": ",".join(matched), "score": str(score)})
    paths.sort(key=lambda entry: (-int(entry["score"]), entry["path"]))
    return paths[:limit]


def score_path(path: str, peripherals: list[str]) -> tuple[list[str], int]:
    low = path.lower()
    base = Path(low).name
    matched = [
        name
        for name in peripherals
        if any(keyword in low for keyword in PERIPHERAL_KEYWORDS.get(name, (name,)))
    ]
    if not matched:
        return [], 0
    score = 0
    if any(token in low for token in ("risc-v", "riscv", "k210", "kendryte")):
        score += 30
    if any(token in low for token in ("drivers/", "/driver", "bsp/")):
        score += 10
    if "tinyusb" in low or "hw/bsp" in low:
        score += 8
    if low.endswith(".c"):
        score += 12
    for name in matched:
        if any(keyword in base for keyword in PERIPHERAL_KEYWORDS.get(name, (name,))):
            score += 20
        if name == "npu" and "kpu" in low:
            score += 40
        if name == "usb" and ("tinyusb" in low or "hw/bsp" in low):
            score += 35
    return matched, score


def fetch_repo_files(repo: dict[str, Any], peripherals: list[str], out: Path, per_repo: int) -> list[dict[str, str]]:
    full = repo["full_name"]
    branch = repo.get("default_branch") or "main"
    tree_url = f"https://api.github.com/repos/{full}/git/trees/{urllib.parse.quote(branch)}?recursive=1"
    tree = api_json(tree_url)
    files = []
    repo_dir = out / safe_name(full.replace("/", "__"))
    for item in matching_paths(tree, peripherals, per_repo):
        raw = f"https://raw.githubusercontent.com/{full}/{urllib.parse.quote(branch)}/{urllib.parse.quote(item['path'])}"
        try:
            text = fetch_text(raw)
        except (OSError, urllib.error.URLError):
            continue
        if len(text) > 512 * 1024:
            continue
        dst = repo_dir / item["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
        files.append(
            {
                "repo": full,
                "url": repo.get("html_url", f"https://github.com/{full}"),
                "branch": branch,
                "path": item["path"],
                "local_path": str(dst),
                "peripherals": item["peripherals"].split(","),
            }
        )
    return files


def fetch_local_seed_files(repo: dict[str, Any], peripherals: list[str], out: Path, per_repo: int) -> list[dict[str, str]]:
    full = repo["full_name"]
    source = LOCAL_SEEDS.get(full)
    if not source or not source.exists():
        return []
    scored = []
    for path in source.rglob("*"):
        if ".git" in path.parts or not path.is_file() or not path.name.lower().endswith(SUFFIXES):
            continue
        rel = path.relative_to(source).as_posix()
        if any(part in SKIP_PARTS for part in rel.lower().split("/")):
            continue
        matched, score = score_path(rel, peripherals)
        if matched:
            scored.append((score, rel, matched, path))
    scored.sort(key=lambda item: (-item[0], item[1]))
    files = []
    repo_dir = out / safe_name(full.replace("/", "__"))
    for _, rel, matched, src in scored[:per_repo]:
        dst = repo_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        files.append(
            {
                "repo": full,
                "url": repo.get("html_url", f"https://github.com/{full}"),
                "branch": "local_checkout",
                "path": rel,
                "local_path": str(dst),
                "peripherals": matched,
            }
        )
    return files


def fetch(target_path: Path, out: Path, repo_limit: int, per_repo: int) -> dict[str, Any]:
    target = load_target(target_path)
    profile = hardware_profile(target)
    out.mkdir(parents=True, exist_ok=True)
    repos: dict[str, dict[str, Any]] = {repo["full_name"]: dict(repo) for repo in SEED_REPOS}
    errors = []
    if repo_limit > 0:
        for query in repo_queries(profile):
            try:
                for repo in search_repos(query, repo_limit):
                    repos.setdefault(repo["full_name"], repo)
            except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
                errors.append({"query": query, "error": f"{type(exc).__name__}: {exc}"})
    files = []
    for repo in repos.values():
        before = len(files)
        if repo_limit > 0:
            try:
                files.extend(fetch_repo_files(repo, profile["peripherals"], out, per_repo))
            except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
                errors.append({"repo": repo.get("full_name"), "error": f"{type(exc).__name__}: {exc}"})
        if len(files) == before:
            files.extend(fetch_local_seed_files(repo, profile["peripherals"], out, per_repo))
    index = {
        "ok": bool(files),
        "target": profile["target"],
        "mode": "github_driver_reuse",
        "repo_count": len(repos),
        "file_count": len(files),
        "files": files,
        "errors": errors[:20],
        "evidence": {
            "similar_driver_retrieved": bool(files),
            "reference_patch_plan_recorded": bool(files),
        },
    }
    (out / "driver_reuse_index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    (out / ".fetched").write_text("github_driver_reuse\n", encoding="utf-8")
    return index


def selftest() -> None:
    queries = repo_queries(
        {
            "target": "demo",
            "peripherals": ["uart", "dma", "npu"],
            "uart": {"kind": "ns16550"},
            "npu": {"enabled": True},
        }
    )
    assert any("ns16550" in item.lower() for item in queries)
    tree = {"tree": [{"type": "blob", "path": "bsp/demo/drivers/drv_uart.c"}, {"type": "blob", "path": "docs/uart.c"}]}
    assert matching_paths(tree, ["uart"], 4)[0]["path"].endswith("drv_uart.c")
    usb_tree = {"tree": [{"type": "blob", "path": "hw/bsp/board/family.c"}, {"type": "blob", "path": "src/device/usbd.c"}]}
    assert matching_paths(usb_tree, ["usb"], 4)[0]["path"].endswith("usbd.c")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?")
    parser.add_argument("--out", default=str(ROOT / "third_party/driver_reuse"))
    parser.add_argument("--repo-limit", type=int, default=0)
    parser.add_argument("--per-repo", type=int, default=8)
    parser.add_argument("--allow-empty", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    if not args.target:
        parser.error("target is required unless --selftest is used")
    report = fetch(Path(args.target).resolve(), Path(args.out).resolve(), args.repo_limit, args.per_repo)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] or args.allow_empty else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from engine.product_tools import _trust


def mutate_digest(value: str, index: int) -> str:
    position = index % len(value)
    replacement = "0" if value[position] != "0" else "1"
    return value[:position] + replacement + value[position + 1 :]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rejected(plan: Path, evidence: Path, destination: Path) -> bool:
    try:
        _trust(plan, evidence, destination)
    except (KeyError, RuntimeError, ValueError):
        return True
    return False


def run(material_root: Path, repetitions: int, output: Path) -> int:
    plan_source = material_root / "plan.json"
    evidence_source = material_root / "evidence.json"
    evidence_base = json.loads(evidence_source.read_text(encoding="utf-8"))
    classes = {
        "valid": 0,
        "artifact_digest_mismatch": 0,
        "artifact_missing": 0,
        "artifact_path_escape": 0,
        "verifier_digest_mismatch": 0,
        "verifier_missing": 0,
    }
    with tempfile.TemporaryDirectory(prefix="airtos-trust-material-") as temporary:
        root = Path(temporary)
        shutil.copy2(plan_source, root / "plan.json")
        for obligation in evidence_base["obligations"]:
            for artifact in obligation["artifacts"]:
                shutil.copy2(material_root / artifact["path"], root / artifact["path"])
            verifier = obligation["verifier"]["name"].split(".", 1)[1]
            shutil.copy2(material_root / verifier, root / verifier)
        evidence_path = root / "evidence.json"
        destination = root / "generated"
        for iteration in range(repetitions):
            write_json(evidence_path, evidence_base)
            try:
                _trust(root / "plan.json", evidence_path, destination)
            except (KeyError, RuntimeError, ValueError):
                classes["valid"] += 1

            mutated = copy.deepcopy(evidence_base)
            artifacts = [artifact for item in mutated["obligations"] for artifact in item["artifacts"]]
            artifact = artifacts[iteration % len(artifacts)]
            artifact["sha256"] = mutate_digest(artifact["sha256"], iteration)
            write_json(evidence_path, mutated)
            if not rejected(root / "plan.json", evidence_path, destination):
                classes["artifact_digest_mismatch"] += 1

            mutated = copy.deepcopy(evidence_base)
            artifacts = [artifact for item in mutated["obligations"] for artifact in item["artifacts"]]
            artifacts[iteration % len(artifacts)]["path"] = f"missing-{iteration}.bin"
            write_json(evidence_path, mutated)
            if not rejected(root / "plan.json", evidence_path, destination):
                classes["artifact_missing"] += 1

            mutated = copy.deepcopy(evidence_base)
            mutated["obligations"][iteration % len(mutated["obligations"])]["artifacts"][0]["path"] = "../outside"
            write_json(evidence_path, mutated)
            if not rejected(root / "plan.json", evidence_path, destination):
                classes["artifact_path_escape"] += 1

            mutated = copy.deepcopy(evidence_base)
            verifier = mutated["obligations"][iteration % len(mutated["obligations"])]["verifier"]
            verifier["sha256"] = mutate_digest(verifier["sha256"], iteration)
            write_json(evidence_path, mutated)
            if not rejected(root / "plan.json", evidence_path, destination):
                classes["verifier_digest_mismatch"] += 1

            mutated = copy.deepcopy(evidence_base)
            mutated["obligations"][iteration % len(mutated["obligations"])]["verifier"]["name"] = "CompilerAgent.missing.py"
            write_json(evidence_path, mutated)
            if not rejected(root / "plan.json", evidence_path, destination):
                classes["verifier_missing"] += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("class,cases,failures\n" + "".join(
        f"{name},{repetitions},{failures}\n" for name, failures in classes.items()
    ), encoding="utf-8")
    total = repetitions * len(classes)
    failures = sum(classes.values())
    print(f"TRUST_MATERIAL_SUMMARY classes={len(classes)} cases={total} failures={failures}")
    return 0 if failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--materials", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=300)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repetitions <= 0:
        parser.error("--repetitions must be positive")
    return run(args.materials.resolve(), args.repetitions, args.output.resolve())


if __name__ == "__main__":
    raise SystemExit(main())

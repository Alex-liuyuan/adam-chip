#!/usr/bin/env python3
"""Build and run deterministic AIRTOS loader and scheduling experiments."""

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import random
import struct
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INCLUDE = ROOT / "engine/rt_ai_templates/include"
LOADER = ROOT / "engine/rt_ai_templates/runtime/aeg_loader.c"
SIM_EDF = ROOT / "engine/rt_ai_templates/os/sim_edf.c"
SEED = 0xCECA2026
PENDING, RUNNING, DONE = 0, 2, 3
RESOURCE_COUNT = 4
COST_PALETTE = (4, 10, 1, 50, 55, 61)
MUTATION_CLASSES = (
    "magic", "version", "header_size", "total_size", "section_count", "duplicate_section",
    "zero_entry_size", "directory_offset", "entry_count_overflow", "plan_binding", "resource",
    "zero_wcet", "recovery_budget", "domain_rank", "truncated",
)


def run(command: list[str], *, input_data: bytes | str | None = None) -> tuple[bytes, float]:
    started = time.monotonic_ns()
    proc = subprocess.run(command, input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=isinstance(input_data, str), check=False)
    elapsed = (time.monotonic_ns() - started) / 1e9
    if proc.returncode:
        stderr = proc.stderr if isinstance(proc.stderr, str) else proc.stderr.decode(errors="replace")
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(command)}\n{stderr}")
    stdout = proc.stdout.encode() if isinstance(proc.stdout, str) else proc.stdout
    return stdout, elapsed


def compile_drivers(out: Path) -> dict[str, Path]:
    drivers: dict[str, Path] = {}
    specifications = {
        "aeg_host": (["gcc", "-std=c11", "-O2"], ROOT / "experiments/airtos/aeg_stream_driver.c", [LOADER]),
        "schedule_host": (["gcc", "-std=c11", "-O2"], ROOT / "experiments/airtos/schedule_driver.c", [SIM_EDF]),
        "aeg_riscv64": (["riscv64-linux-gnu-gcc", "-std=c11", "-O2", "-static", "-march=rv64gc", "-mabi=lp64d"], ROOT / "experiments/airtos/aeg_stream_driver.c", [LOADER]),
        "schedule_riscv64": (["riscv64-linux-gnu-gcc", "-std=c11", "-O2", "-static", "-march=rv64gc", "-mabi=lp64d"], ROOT / "experiments/airtos/schedule_driver.c", [SIM_EDF]),
    }
    for name, (compiler, driver, sources) in specifications.items():
        destination = out / "bin" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        command = [*compiler, "-Wall", "-Wextra", "-Werror", "-I", str(INCLUDE), str(driver),
                   *map(str, sources), "-o", str(destination)]
        run(command)
        drivers[name] = destination
    return drivers


def sections(blob: bytes) -> dict[int, tuple[int, int, int]]:
    count = struct.unpack_from("<H", blob, 12)[0]
    return {struct.unpack_from("<H", blob, 64 + 16 * index)[0]:
            (struct.unpack_from("<H", blob, 66 + 16 * index)[0],
             struct.unpack_from("<I", blob, 68 + 16 * index)[0],
             struct.unpack_from("<I", blob, 72 + 16 * index)[0]) for index in range(count)}


def personalized(base: bytes, case_id: str) -> bytearray:
    blob = bytearray(base)
    metadata = sections(base)[2][1]
    digest = hashlib.sha256(case_id.encode()).digest()
    blob[20:52] = digest
    blob[metadata:metadata + 32] = digest
    return blob


def mutate(base: bytes, class_names: tuple[str, ...], index: int) -> bytes:
    sec = sections(base)
    segment = sec[1][1]
    recovery = sec[7][1]
    domain = sec[8][1]
    blob = personalized(base, "+".join(class_names) + f":{index}")
    truncate = False
    for class_name in class_names:
        if class_name == "magic": struct.pack_into("<I", blob, 0, 0xA0000000 | index)
        elif class_name == "version": struct.pack_into("<H", blob, 4, 3 + index % 253)
        elif class_name == "header_size": struct.pack_into("<H", blob, 6, 1 + index % 63)
        elif class_name == "total_size": struct.pack_into("<I", blob, 8, len(blob) + 1 + index)
        elif class_name == "section_count": struct.pack_into("<H", blob, 12, 9 + index % 8)
        elif class_name == "duplicate_section": struct.pack_into("<H", blob, 80, 1)
        elif class_name == "zero_entry_size": struct.pack_into("<H", blob, 66, 0)
        elif class_name == "directory_offset": struct.pack_into("<I", blob, 68, index % 64)
        elif class_name == "entry_count_overflow": struct.pack_into("<I", blob, 72, 0xFFFFFFFF - index)
        elif class_name == "plan_binding": blob[20 + index % 32] ^= 0x80
        elif class_name == "resource": blob[segment + 2] = 4 + index % 252
        elif class_name == "zero_wcet": struct.pack_into("<I", blob, segment + 16, 0)
        elif class_name == "recovery_budget": struct.pack_into("<I", blob, recovery + 4 * (index % 4), 0)
        elif class_name == "domain_rank": blob[domain] = 0 if index % 2 == 0 else 5 + index % 251
        elif class_name == "truncated": truncate = True
        else: raise ValueError(class_name)
    return bytes(blob[:len(blob) - 1 - index % 128] if truncate else blob)


def mutation_corpus(base: bytes) -> tuple[bytes, list[dict[str, object]], list[int]]:
    stream = bytearray()
    manifest: list[dict[str, object]] = []
    expected: list[int] = []
    cases: list[tuple[str, int, bytes, int, str]] = []
    for index in range(300):
        legal = bytes(personalized(base, f"legal:{index}"))
        cases.append(("legal", index, legal, 0, "legal"))
    for class_name in MUTATION_CLASSES:
        for index in range(300):
            cases.append((class_name, index, mutate(base, (class_name,), index), -1, "single"))
    for left, right in itertools.combinations(MUTATION_CLASSES, 2):
        for index in range(30):
            cases.append((f"{left}+{right}", index, mutate(base, (left, right), index), -1, "pairwise"))
    for ordinal, (class_name, index, blob, wanted, design) in enumerate(cases):
        offset = len(stream)
        stream.extend(struct.pack("<I", len(blob)))
        stream.extend(blob)
        digest = hashlib.sha256(blob).hexdigest()
        manifest.append({"ordinal": ordinal, "class": class_name, "case": index, "offset": offset,
                         "size": len(blob), "sha256": digest, "expected_status": wanted, "design": design})
        expected.append(wanted)
    return bytes(stream), manifest, expected


def evaluate_loader(name: str, command: list[str], corpus: bytes, expected: list[int], out: Path) -> dict[str, object]:
    stdout, elapsed = run(command, input_data=corpus)
    rows = stdout.decode().splitlines()
    actual = [int(row.split()[1]) for row in rows]
    if len(actual) != len(expected): raise AssertionError(f"{name}: {len(actual)} rows, expected {len(expected)}")
    mismatches = [index for index, pair in enumerate(zip(actual, expected)) if pair[0] != pair[1]]
    (out / f"{name}.csv").write_text("ordinal,status\n" + "".join(f"{i},{status}\n" for i, status in enumerate(actual)))
    return {"cases": len(expected), "mismatches": len(mismatches), "first_mismatch": mismatches[:1], "elapsed_s": elapsed}


def dependencies(count: int, shape: str, rng: random.Random) -> list[int]:
    masks = [0] * count
    if shape == "chain":
        for index in range(1, count): masks[index] = 1 << (index - 1)
    elif shape == "diamond" and count >= 4:
        masks[1] = masks[2] = 1
        masks[3] = (1 << 1) | (1 << 2)
        for index in range(4, count): masks[index] = 1 << (index - 1)
    elif shape == "fork_join" and count >= 3:
        for index in range(1, count - 1): masks[index] = 1
        masks[-1] = sum(1 << index for index in range(1, count - 1))
    else:
        for index in range(1, count):
            candidates = [dependency for dependency in range(index) if rng.random() < 0.3]
            masks[index] = sum(1 << dependency for dependency in candidates)
    return masks


def make_job(rng: random.Random, now: int, segment_count: int, shape: str, allow_state: bool) -> dict[str, object]:
    masks = dependencies(segment_count, shape, rng)
    segments = [{"resource": rng.randrange(RESOURCE_COUNT), "state": PENDING, "dependencies": masks[index],
                 "cost": rng.choice(COST_PALETTE)} for index in range(segment_count)]
    release = now + rng.randrange(0, 8)
    if allow_state and rng.random() < 0.25:
        release = max(0, now - rng.randrange(0, 8))
        runnable = [index for index, segment in enumerate(segments) if segment["dependencies"] == 0]
        running = rng.choice(runnable)
        segments[running]["state"] = RUNNING
    total = sum(int(segment["cost"]) for segment in segments)
    deadline = max(now + 1, release + total + rng.randrange(-total // 2, total + 20))
    budgets = [0] * RESOURCE_COUNT
    periods = [0] * RESOURCE_COUNT
    relative = max(1, deadline - release)
    if rng.random() < 0.2:
        resource = rng.randrange(RESOURCE_COUNT)
        budgets[resource] = rng.choice(COST_PALETTE)
        periods[resource] = max(budgets[resource], rng.choice((50, 100, 200)))
    return {"release": release, "deadline": deadline, "relative_deadline": relative,
            "budget": budgets, "period": periods, "segments": segments}


def make_scenario(rng: random.Random, scenario_id: int, stress: bool) -> dict[str, object]:
    now = rng.randrange(0, 1000)
    shapes = ("chain", "diamond", "fork_join", "branches")
    if stress:
        job_count, lower, upper = rng.randrange(5, 8), 2, 16
    else:
        job_count, lower, upper = rng.randrange(0, 4), 1, 8
    jobs = [make_job(rng, now, rng.randrange(lower, upper + 1), shapes[(scenario_id + index) % 4], True)
            for index in range(job_count)]
    running_resources: set[int] = set()
    for job in jobs:
        for segment in job["segments"]:
            if segment["state"] != RUNNING: continue
            resource = int(segment["resource"])
            if resource in running_resources:
                segment["state"] = PENDING
            else:
                running_resources.add(resource)
    candidate = make_job(rng, now, rng.randrange(lower, upper + 1), shapes[scenario_id % 4], False)
    candidate["release"] = now
    return {"id": scenario_id, "kind": "stress" if stress else "small", "source": "cecap_plan_cost_palette_model_domain",
            "now": now, "jobs": jobs, "candidate": candidate}


def dbf_ok(jobs: list[dict[str, object]], now: int, horizon: int) -> bool:
    if horizon <= now: return False
    interval = horizon - now
    for resource in range(RESOURCE_COUNT):
        demand = 0
        for job in jobs:
            if int(job["deadline"]) <= horizon:
                demand += sum(int(segment["cost"]) for segment in job["segments"]
                              if int(segment["resource"]) == resource and int(segment["state"]) != DONE)
            budget, period = int(job["budget"][resource]), int(job["period"][resource])
            if budget and period:
                first = period + int(job["relative_deadline"])
                if interval >= first: demand += (1 + (interval - first) // period) * budget
        if demand > interval: return False
    return True


def execution_cost(segment: dict[str, object]) -> int:
    return max(int(segment["cost"]), int(segment.get("guard_cost", segment["cost"])))


def oracle(scenario: dict[str, object], policy: str = "edf") -> tuple[int, int]:
    now = int(scenario["now"])
    jobs = [*scenario["jobs"], scenario["candidate"]]
    states = [[int(segment["state"]) for segment in job["segments"]] for job in jobs]
    finishes = [[0 for _ in job["segments"]] for job in jobs]
    busy = [0] * RESOURCE_COUNT
    remaining = 0
    admissible = all(dbf_ok(jobs, now, int(job["deadline"])) for job in jobs)
    for job_index, job in enumerate(jobs):
        for segment_index, segment in enumerate(job["segments"]):
            if states[job_index][segment_index] == DONE: continue
            remaining += 1
            if states[job_index][segment_index] == RUNNING:
                resource = int(segment["resource"])
                finishes[job_index][segment_index] = now + execution_cost(segment)
                busy[resource] = max(busy[resource], finishes[job_index][segment_index])
    current = now
    while remaining:
        progress = False
        for job_index, job in enumerate(jobs):
            for segment_index, _ in enumerate(job["segments"]):
                if states[job_index][segment_index] == RUNNING and finishes[job_index][segment_index] <= current:
                    states[job_index][segment_index] = DONE
                    remaining -= 1
                    progress = True
        for resource in range(RESOURCE_COUNT):
            if busy[resource] > current: continue
            best: tuple[int, int, int] | None = None
            for job_index, job in enumerate(jobs):
                if int(job["release"]) > current: continue
                for segment_index, segment in enumerate(job["segments"]):
                    mask = int(segment["dependencies"])
                    ready = all(not (mask & (1 << dependency)) or states[job_index][dependency] == DONE
                                for dependency in range(segment_index))
                    if states[job_index][segment_index] == PENDING and int(segment["resource"]) == resource and ready:
                        if policy == "edf": key = (int(job["deadline"]), job_index, segment_index)
                        elif policy == "fifo": key = (int(job["release"]), job_index, segment_index)
                        elif policy == "fixed_priority": key = (job_index, job_index, segment_index)
                        else: raise ValueError(policy)
                        if best is None or key < best: best = key
            if best is not None:
                _, job_index, segment_index = best
                states[job_index][segment_index] = RUNNING
                finishes[job_index][segment_index] = current + execution_cost(jobs[job_index]["segments"][segment_index])
                busy[resource] = finishes[job_index][segment_index]
                progress = True
        if not remaining: break
        future = [finishes[j][s] for j, job in enumerate(jobs) for s in range(len(job["segments"]))
                  if states[j][s] == RUNNING and finishes[j][s] > current]
        future += [int(job["release"]) for job in jobs if int(job["release"]) > current]
        if not future or (not progress and min(future) <= current): return -7, 0
        current = min(future)
    completed = [max(finish, default=0) for finish in finishes]
    if any(finish > int(job["deadline"]) for finish, job in zip(completed, jobs)): admissible = False
    return (0 if admissible else -7), completed[-1]


def scenario_values(scenario: dict[str, object]) -> list[int]:
    values: list[int] = [int(scenario["id"]), int(scenario["now"]), len(scenario["jobs"])]
    for job in scenario["jobs"]:
        values.extend((int(job["release"]), int(job["deadline"]), len(job["segments"]), int(job["relative_deadline"])))
        for budget, period in zip(job["budget"], job["period"]): values.extend((int(budget), int(period)))
        for segment in job["segments"]:
            values.extend((int(segment["resource"]), int(segment["state"]), int(segment["dependencies"]), int(segment["cost"])))
    candidate = scenario["candidate"]
    values.extend((int(candidate["deadline"]), len(candidate["segments"]), int(candidate["relative_deadline"])))
    for budget, period in zip(candidate["budget"], candidate["period"]): values.extend((int(budget), int(period)))
    for segment in candidate["segments"]:
        cost = int(segment["cost"])
        coherency = 1 if cost > 1 and int(segment["resource"]) in (1, 2, 3) else 0
        recovery = min(2, max(0, cost - coherency - 1))
        values.extend((int(segment["resource"]), int(segment["dependencies"]), cost - coherency - recovery, coherency, recovery))
    return values


def serialize_scenarios(scenarios: list[dict[str, object]]) -> str:
    rows: list[str] = []
    for scenario in scenarios:
        rows.append(" ".join(map(str, scenario_values(scenario))))
    return "\n".join(rows) + "\n"


def evaluate_schedule(name: str, command: list[str], scenarios: list[dict[str, object]], out: Path) -> dict[str, object]:
    expected = [oracle(scenario) for scenario in scenarios]
    stdout, elapsed = run(command, input_data=serialize_scenarios(scenarios))
    actual = [(int(parts[1]), int(parts[2])) for row in stdout.decode().splitlines() if (parts := row.split())]
    if len(actual) != len(expected): raise AssertionError(f"{name}: {len(actual)} rows, expected {len(expected)}")
    mismatches = [index for index, pair in enumerate(zip(actual, expected)) if pair[0] != pair[1]]
    (out / f"{name}.csv").write_text("scenario,status,finish,expected_status,expected_finish\n" +
        "".join(f"{i},{got[0]},{got[1]},{wanted[0]},{wanted[1]}\n" for i, (got, wanted) in enumerate(zip(actual, expected))))
    return {"scenarios": len(scenarios), "exact_matches": len(scenarios) - len(mismatches),
            "mismatches": len(mismatches), "first_mismatch": mismatches[:1], "elapsed_s": elapsed}


def bounded_grid() -> list[dict[str, object]]:
    scenarios: list[dict[str, object]] = []
    factors = itertools.product(range(2), range(2), (PENDING, RUNNING), (1, 4, 10, 50),
                                (1, 4, 10, 50), (2, 8, 32, 96), (2, 8, 32, 96))
    for scenario_id, (existing_resource, candidate_resource, state, existing_cost, candidate_cost,
                      existing_slack, candidate_slack) in enumerate(factors, 1_000_000):
        existing = {"release": 0, "deadline": existing_slack, "relative_deadline": existing_slack,
                    "budget": [0] * RESOURCE_COUNT, "period": [0] * RESOURCE_COUNT,
                    "segments": [{"resource": existing_resource, "state": state, "dependencies": 0,
                                  "cost": existing_cost}]}
        candidate = {"release": 0, "deadline": candidate_slack, "relative_deadline": candidate_slack,
                     "budget": [0] * RESOURCE_COUNT, "period": [0] * RESOURCE_COUNT,
                     "segments": [{"resource": candidate_resource, "state": PENDING, "dependencies": 0,
                                   "cost": candidate_cost}]}
        scenarios.append({"id": scenario_id, "kind": "bounded_grid", "source": "cartesian_boundary_grid",
                          "now": 0, "jobs": [existing], "candidate": candidate})
    return scenarios


def decision_metrics(expected: list[int], actual: list[int]) -> dict[str, int]:
    true_accept = sum(wanted == 0 and got == 0 for wanted, got in zip(expected, actual))
    true_reject = sum(wanted != 0 and got != 0 for wanted, got in zip(expected, actual))
    false_accept = sum(wanted != 0 and got == 0 for wanted, got in zip(expected, actual))
    false_reject = sum(wanted == 0 and got != 0 for wanted, got in zip(expected, actual))
    return {"true_accept": true_accept, "true_reject": true_reject,
            "false_accept": false_accept, "false_reject": false_reject}


def analyze_baselines(scenarios: list[dict[str, object]], out: Path) -> dict[str, object]:
    expected_pairs = [oracle(scenario) for scenario in scenarios]
    expected = [status for status, _ in expected_pairs]
    decisions: dict[str, list[int]] = {
        "no_admission": [0] * len(scenarios),
        "candidate_only": [oracle({**scenario, "jobs": []})[0] for scenario in scenarios],
        "fifo": [oracle(scenario, "fifo")[0] for scenario in scenarios],
        "fixed_priority": [oracle(scenario, "fixed_priority")[0] for scenario in scenarios],
        "simedf_plus": expected,
    }
    with (out / "core2_baselines.csv").open("w") as stream:
        stream.write("scenario,oracle," + ",".join(decisions) + "\n")
        for index, scenario in enumerate(scenarios):
            stream.write(f"{scenario['id']},{expected[index]}," +
                         ",".join(str(decisions[name][index]) for name in decisions) + "\n")
    return {name: decision_metrics(expected, values) for name, values in decisions.items()}


def analyze_wcet(scenarios: list[dict[str, object]], out: Path) -> dict[str, object]:
    accepted = [scenario for scenario in scenarios if oracle(scenario)[0] == 0]
    results: dict[str, object] = {}
    rows = ["q,accepted_under_wcet,actual_deadline_misses,model_valid\n"]
    for numerator, denominator in ((1, 2), (4, 5), (1, 1), (21, 20), (6, 5)):
        scaled: list[dict[str, object]] = []
        for scenario in accepted:
            item = copy.deepcopy(scenario)
            for job in [*item["jobs"], item["candidate"]]:
                for segment in job["segments"]:
                    segment["guard_cost"] = int(segment["cost"])
                    segment["cost"] = max(1, (int(segment["cost"]) * numerator + denominator - 1) // denominator)
            scaled.append(item)
        misses = sum(oracle(item)[0] != 0 for item in scaled)
        label = f"{numerator / denominator:.2f}"
        results[label] = {"accepted_under_wcet": len(accepted), "actual_deadline_misses": misses,
                          "model_valid": numerator <= denominator}
        rows.append(f"{label},{len(accepted)},{misses},{str(numerator <= denominator).lower()}\n")
    (out / "core2_wcet_sensitivity.csv").write_text("".join(rows))
    return results


def write_rtthread_corpus(path: Path, loader_stream: bytes, manifest: list[dict[str, object]],
                          scenarios: list[dict[str, object]]) -> dict[str, object]:
    payload = bytearray(struct.pack("<IIIII", 0x46545241, 1, 0, len(manifest), len(scenarios)))
    for row in manifest:
        offset, size = int(row["offset"]), int(row["size"])
        blob = loader_stream[offset + 4:offset + 4 + size]
        payload.extend(struct.pack("<Ii", size, int(row["expected_status"])))
        payload.extend(blob)
    for scenario in scenarios:
        wanted, finish = oracle(scenario)
        values = scenario_values(scenario)
        payload.extend(struct.pack("<IiQ", len(values), wanted, finish))
        payload.extend(struct.pack("<" + "Q" * len(values), *values))
    struct.pack_into("<I", payload, 8, len(payload))
    path.write_bytes(payload)
    return {"bytes": len(payload), "loader_cases": len(manifest), "schedule_scenarios": len(scenarios),
            "sha256": hashlib.sha256(payload).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aeg", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stress-seeds", type=int, default=30)
    args = parser.parse_args()
    if args.stress_seeds < 1: parser.error("--stress-seeds must be positive")
    args.out.mkdir(parents=True, exist_ok=True)
    drivers = compile_drivers(args.out)
    base = args.aeg.read_bytes()
    corpus, manifest, expected = mutation_corpus(base)
    (args.out / "core1_mutations.bin").write_bytes(corpus)
    (args.out / "core1_manifest.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in manifest))
    results: dict[str, object] = {"schema": "airtos.formal-software.v2", "seed": SEED,
        "stress_seed_count": args.stress_seeds, "base_aeg_sha256": hashlib.sha256(base).hexdigest(),
        "core1": {"single_classes": len(MUTATION_CLASSES), "pairwise_classes": len(tuple(itertools.combinations(MUTATION_CLASSES, 2)))},
        "core2": {}, "analysis": {}}
    results["core1"]["host"] = evaluate_loader("core1_host", [str(drivers["aeg_host"])], corpus, expected, args.out)
    results["core1"]["qemu_riscv64"] = evaluate_loader("core1_qemu", ["qemu-riscv64", "-cpu", "max", str(drivers["aeg_riscv64"])], corpus, expected, args.out)
    rng = random.Random(SEED)
    small = [make_scenario(rng, index, False) for index in range(10000)]
    stress = [make_scenario(rng, 10000 + index, True) for index in range(5000)]
    grid = bounded_grid()
    multiseed: list[dict[str, object]] = []
    for seed_index in range(args.stress_seeds):
        seeded = random.Random(SEED + seed_index + 1)
        multiseed.extend(make_scenario(seeded, 2_000_000 + seed_index * 250 + index, True) for index in range(250))
    (args.out / "schedule_scenarios_v1.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in small))
    (args.out / "stress_scenarios_v1.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in stress))
    (args.out / "bounded_grid_v1.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in grid))
    (args.out / "multiseed_stress_v1.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in multiseed))
    for label, scenarios in (("small", small), ("stress", stress), ("bounded", grid), ("multiseed", multiseed)):
        results["core2"][f"host_{label}"] = evaluate_schedule(f"core2_host_{label}", [str(drivers["schedule_host"])], scenarios, args.out)
        results["core2"][f"qemu_{label}"] = evaluate_schedule(f"core2_qemu_{label}", ["qemu-riscv64", "-cpu", "max", str(drivers["schedule_riscv64"])], scenarios, args.out)
    results["analysis"]["baselines"] = analyze_baselines(small, args.out)
    results["analysis"]["wcet_sensitivity"] = analyze_wcet(small, args.out)
    results["analysis"]["rtthread_corpus"] = write_rtthread_corpus(
        args.out / "rtthread_formal_corpus.bin", corpus, manifest, [*small, *stress, *grid, *multiseed])
    failures = [f"{core}.{platform}" for core in ("core1", "core2")
                for platform, result in results[core].items()
                if isinstance(result, dict) and "mismatches" in result and result["mismatches"]]
    results["status"] = "FAIL" if failures else "PASS"
    results["failed_checks"] = failures
    (args.out / "summary.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(json.dumps(results, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

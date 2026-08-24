#!/usr/bin/env python3
"""Validate and summarize the AIRTOS K230 hardware-in-the-loop logs."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def matches(pattern: str, value: str) -> list[tuple[str, ...]]:
    found = re.findall(pattern, value, re.MULTILINE)
    if not found:
        raise ValueError(f"missing pattern {pattern!r}")
    return found


def csv_rows(path: Path, columns: int) -> list[list[str]]:
    return [row for row in csv.reader(text(path).splitlines()) if len(row) == columns and row[1].isdigit()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--long-log", default="core4/long_hil_24min_formal.log")
    parser.add_argument("--minimum-duration-seconds", type=int, default=1440)
    args = parser.parse_args()
    root = args.result / "logs"
    summary: dict[str, object] = {}

    admission = matches(r"ADMISSION class=(\S+) cases=(\d+) failures=(\d+)", text(root / "core1/admission.log"))
    diagnostics = matches(r"DIAGNOSTIC_SUMMARY cases=(\d+) pairwise_classes=(\d+) macro_f1=([\d.]+)", text(root / "core1/diagnostics.log"))[0]
    transactions = []
    for path in sorted((root / "core1").glob("transactions_*.log")):
        transactions.extend(matches(r"TRANSACTIONS threads=(\d+) operations=(\d+) accepted=(\d+) rejected=(\d+) overlaps=(\d+) partial_commits=(\d+)", text(path)))
    health = matches(r"HEALTH_RACE cases=(\d+) failures=(\d+) rollback_leaks=(\d+)", text(root / "core1/health_race.log"))[0]
    trust = matches(r"TRUST_ROTATION roots=\S+ cases=(\d+) failures=(\d+)", text(root / "core1/trust_rotation.log"))[0]
    summary["core1"] = {
        "admission_cases": sum(int(row[1]) for row in admission),
        "admission_failures": sum(int(row[2]) for row in admission),
        "diagnostic_cases": int(diagnostics[0]),
        "diagnostic_macro_f1": float(diagnostics[2]),
        "transaction_operations": sum(int(row[1]) for row in transactions),
        "transaction_accepted": sum(int(row[2]) for row in transactions),
        "transaction_rejected": sum(int(row[3]) for row in transactions),
        "overlaps": sum(int(row[4]) for row in transactions),
        "partial_commits": sum(int(row[5]) for row in transactions),
        "health_race_cases": int(health[0]),
        "health_race_failures": int(health[1]) + int(health[2]),
        "trust_rotation_cases": int(trust[0]),
        "trust_rotation_failures": int(trust[1]),
    }

    formal = matches(r"AIRTOS_K230_FORMAL loader_cases=(\d+) loader_failures=(\d+) schedule_cases=(\d+) schedule_failures=(\d+) bytes=(\d+)", text(root / "core2/formal_replay.log"))[0]
    overhead: dict[str, dict[str, int]] = {}
    for row in csv_rows(root / "core2/control_overhead.csv", 7):
        values = overhead.setdefault(row[0], {"max_batch_p99_ns": 0, "max_ns": 0})
        values["max_batch_p99_ns"] = max(values["max_batch_p99_ns"], int(row[5]))
        values["max_ns"] = max(values["max_ns"], int(row[6]))
    aot: dict[str, dict[str, int]] = {}
    for name in ("cpu", "rvv"):
        rows = csv_rows(root / f"core2/aot_{name}_timing.csv", 8)
        aot[name] = {
            "cases": sum(int(row[2]) for row in rows),
            "max_batch_p99_ns": max(int(row[5]) for row in rows),
            "max_ns": max(int(row[6]) for row in rows),
            "failures": max(int(row[7]) for row in rows),
        }
    plan = json.loads(text(args.plan))
    deadline_us = int(plan["arrival_model"]["relative_deadline_us"])
    primary_wcet_us = int(plan["plans"][0]["segments"][0]["wcet_us"])
    fallback_wcet_us = int(plan["plans"][1]["segments"][0]["wcet_us"])
    admission_threshold_ns = min(1_000_000, int(0.05 * deadline_us * 1000))
    steady_p99_ns = max(overhead[name]["max_batch_p99_ns"] for name in ("queue_push_pop", "trace", "complete_isr"))
    summary["core2"] = {
        "loader_cases": int(formal[0]),
        "loader_failures": int(formal[1]),
        "schedule_cases": int(formal[2]),
        "schedule_failures": int(formal[3]),
        "corpus_bytes": int(formal[4]),
        "control_overhead": overhead,
        "aot": aot,
        "plan_deadline_us": deadline_us,
        "plan_primary_wcet_us": primary_wcet_us,
        "plan_fallback_wcet_us": fallback_wcet_us,
        "p99_admission_threshold_ns": admission_threshold_ns,
        "p99_control_threshold_pass": max(value["max_batch_p99_ns"] for value in overhead.values()) < admission_threshold_ns,
        "steady_state_five_percent_pass": steady_p99_ns < int(0.05 * primary_wcet_us * 1000),
        "primary_observed_max_within_plan_wcet": aot["rvv"]["max_ns"] <= primary_wcet_us * 1000,
        "fallback_observed_max_within_plan_wcet": aot["cpu"]["max_ns"] <= fallback_wcet_us * 1000,
    }

    allocators = []
    for path in sorted((root / "core3").glob("allocator_*.log")):
        allocators.extend(matches(r"CONCURRENCY_PROBE threads=(\d+) attempts=(\d+) successful_leases=(\d+) overlaps=(\d+) canary_corruptions=(\d+) cross_session_diffs=(\d+) generation_race_failures=(\d+) rollback_leaks=(\d+)", text(path)))
    dma = []
    negative = []
    for path in sorted((root / "core3").glob("dma_*.log")):
        value = text(path)
        dma.extend(matches(r"AIRTOS_K230_DMA cases=(\d+) size=(\d+) failures=(\d+) elapsed_ns=(\d+) mean_ns=(\d+)", value))
        negative.extend(matches(r"AIRTOS_K230_DMA_NEGATIVE cases=(\d+) omit_clean_detected=(\d+) omit_invalidate_detected=(\d+) errors=(\d+)", value))
    summary["core3"] = {
        "allocator_attempts": sum(int(row[1]) for row in allocators),
        "successful_leases": sum(int(row[2]) for row in allocators),
        "allocator_safety_failures": sum(sum(int(value) for value in row[3:]) for row in allocators),
        "dma_cases": sum(int(row[0]) for row in dma),
        "dma_failures": sum(int(row[2]) for row in dma),
        "dma_sizes": {row[1]: {"cases": int(row[0]), "mean_ns": int(row[4])} for row in dma},
        "negative_omit_clean_detected": sum(int(row[1]) for row in negative),
        "negative_omit_invalidate_detected": sum(int(row[2]) for row in negative),
        "negative_errors": sum(int(row[3]) for row in negative),
    }

    stale = matches(r"STALE_REPLAY repetitions_per_class=(\d+) wrong_device=(\d+) wrong_epoch=(\d+) wrong_cookie=(\d+) cancel_late=(\d+) reset_late=(\d+) same_epoch_old_cookie=(\d+) duplicate=(\d+)", text(root / "core4/stale_replay.log"))[0]
    lifecycle = matches(r"AIRTOS_K230_GSDMA_LIFECYCLE cases=(\d+) failures=(\d+) median_ns=(\d+) p95_ns=(\d+) p99_ns=(\d+) max_ns=(\d+)", text(root / "core4/gsdma_lifecycle.log"))[0]
    classifier = matches(r"TRACE_CLASSIFIER cases=(\d+) macro_f1=([\d.]+) top3_recall=([\d.]+) status_only_macro_f1=([\d.]+) gate_bypass=(\d+)", text(root / "core4/trace_classifier.log"))[0]
    robust = matches(r"TRACE_ROBUSTNESS cases=(\d+).* macro_f1=([\d.]+) accuracy=([\d.]+) failures=(\d+)", text(root / "core4/trace_robustness.log"))[0]
    recovery = matches(r"RECOVERY class=\S+ episodes=(\d+) failures=(\d+)", text(root / "core4/recovery.log"))
    budgets = matches(r"RECOVERY_BUDGET k=\d+ class=\S+ episodes=(\d+) failures=(\d+)", text(root / "core4/recovery_budget.log"))
    gates = matches(r"FALLBACK_GATE gate=\S+ episodes=(\d+) bypasses=(\d+)", text(root / "core4/fallback_gates.log"))
    cookie = matches(r"COOKIE_WRAP_PROBE first_epoch=(\d+) first_cookie=(\d+) second_epoch=(\d+) second_cookie=(\d+) checksum=(\d+)", text(root / "core4/cookie_wrap.log"))[0]
    long_path = root / args.long_log
    long_state: dict[str, object] = {"status": "NOT_STARTED"}
    if long_path.exists():
        long_text = text(long_path)
        results = re.findall(r"AIRTOS_K230_LONG_(?:HEARTBEAT|RESULT) elapsed_seconds=(\d+) jobs=(\d+) data_failures=(\d+) device_failures=(\d+) lifecycle_failures=(\d+) temperature_c=([-\d.]+)", long_text)
        if results:
            latest = results[-1]
            completed = "AIRTOS_K230_LONG_PASS" in long_text
            long_state = {
                "status": "COMPLETE" if completed else "IN_PROGRESS",
                "elapsed_seconds": int(latest[0]),
                "jobs": int(latest[1]),
                "data_failures": int(latest[2]),
                "device_failures": int(latest[3]),
                "lifecycle_failures": int(latest[4]),
                "temperature_c": float(latest[5]),
                "minimum_duration_seconds": args.minimum_duration_seconds,
                "completion_criteria_pass": completed and int(latest[0]) >= args.minimum_duration_seconds and int(latest[1]) >= 1000000
                    and all(int(value) == 0 for value in latest[2:5]),
            }
    summary["core4"] = {
        "stale_events": int(stale[0]) * 7,
        "stale_failures": sum(int(value) for value in stale[1:]),
        "device_lifecycle_cases": int(lifecycle[0]),
        "device_lifecycle_failures": int(lifecycle[1]),
        "device_lifecycle_p99_ns": int(lifecycle[4]),
        "device_lifecycle_max_ns": int(lifecycle[5]),
        "trace_cases": int(classifier[0]),
        "trace_macro_f1": float(classifier[1]),
        "trace_top3_recall": float(classifier[2]),
        "trace_gate_bypass": int(classifier[4]),
        "trace_robust_cases": int(robust[0]),
        "trace_robust_macro_f1": float(robust[1]),
        "trace_robust_failures": int(robust[3]),
        "recovery_episodes": sum(int(row[0]) for row in recovery),
        "recovery_failures": sum(int(row[1]) for row in recovery),
        "recovery_budget_episodes": sum(int(row[0]) for row in budgets),
        "recovery_budget_failures": sum(int(row[1]) for row in budgets),
        "fallback_gate_episodes": sum(int(row[0]) for row in gates),
        "fallback_gate_bypasses": sum(int(row[1]) for row in gates),
        "cookie_wrap_pass": cookie == ("1", "4294967295", "2", "1", "2"),
        "long_hil": long_state,
    }

    expected = (
        summary["core1"]["admission_cases"] == 3900
        and summary["core1"]["admission_failures"] == 0
        and summary["core1"]["diagnostic_cases"] == 23400
        and summary["core1"]["transaction_operations"] == 400000
        and summary["core1"]["overlaps"] == 0
        and summary["core1"]["partial_commits"] == 0
        and summary["core1"]["health_race_cases"] == 300
        and summary["core1"]["health_race_failures"] == 0
        and summary["core1"]["trust_rotation_cases"] == 1500
        and summary["core1"]["trust_rotation_failures"] == 0
        and summary["core2"]["loader_cases"] == 7950
        and summary["core2"]["loader_failures"] == 0
        and summary["core2"]["schedule_cases"] == 24548
        and summary["core2"]["schedule_failures"] == 0
        and summary["core3"]["allocator_attempts"] == 1000000
        and summary["core3"]["allocator_safety_failures"] == 0
        and summary["core3"]["dma_cases"] == 1000000
        and summary["core3"]["dma_failures"] == 0
        and summary["core4"]["stale_events"] == 700000
        and summary["core4"]["stale_failures"] == 0
        and summary["core4"]["recovery_episodes"] == 1500
        and summary["core4"]["recovery_failures"] == 0
        and summary["core4"]["recovery_budget_episodes"] == 4800
        and summary["core4"]["recovery_budget_failures"] == 0
        and summary["core4"]["fallback_gate_episodes"] == 1200
        and summary["core4"]["fallback_gate_bypasses"] == 0
        and summary["core4"]["cookie_wrap_pass"]
    )
    summary["short_experiments_pass"] = expected
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"AIRTOS_K230_SUMMARY_PASS output={args.output}" if expected else "AIRTOS_K230_SUMMARY_FAIL")
    return 0 if expected else 1


if __name__ == "__main__":
    raise SystemExit(main())

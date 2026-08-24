#!/usr/bin/env python3
"""Validate and summarize one complete K230 mixed 24-hour log."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def latest(pattern: str, value: str) -> tuple[str, ...] | None:
    found = re.findall(pattern, value)
    return found[-1] if found else None


def summarize(raw: bytes) -> dict[str, object]:
    value = raw.replace(b"\x00", b"").decode("utf-8", errors="replace").replace("\r", "")
    temperatures = [float(item) for item in re.findall(
        r"AIRTOS_K230_LONG_(?:START|HEARTBEAT|RESULT).*?temperature_c=([-\d.]+)", value)]
    long_heartbeats = set(re.findall(r"AIRTOS_K230_LONG_HEARTBEAT elapsed_seconds=(\d+)", value))
    compute_heartbeats = set(re.findall(r"AIRTOS_K230_COMPUTE_HEARTBEAT elapsed_seconds=(\d+)", value))
    long_result = latest(
        r"AIRTOS_K230_LONG_RESULT elapsed_seconds=(\d+) jobs=(\d+) data_failures=(\d+) "
        r"device_failures=(\d+) lifecycle_failures=(\d+) temperature_c=([-\d.]+)", value)
    compute_result = latest(
        r"AIRTOS_K230_COMPUTE_RESULT elapsed_seconds=(\d+) batches=(\d+) jobs=(\d+) "
        r"runtime_failures=(\d+) numeric_failures=(\d+) lease_failures=(\d+) "
        r"stale_failures=(\d+) deadline_failures=(\d+) maximum_batch_us=(\d+)", value)
    mixed_result = latest(
        r"AIRTOS_K230_MIXED_RESULT elapsed_seconds=(\d+) frames=(\d+) object_inferences=(\d+) "
        r"face_inferences=(\d+) camera_restarts=(\d+) kpu_restarts=(\d+) frame_failures=(\d+) "
        r"inference_failures=(\d+) (?:ide_interrupts=(\d+) )?lifecycle_failures=(\d+) maximum_frame_ms=(\d+)", value)
    summary: dict[str, object] = {
        "schema": "airtos.k230-full-24h.v1",
        "duration_requirement_seconds": 86400,
        "long": None,
        "compute": None,
        "mixed": None,
        "observations": {
            "long_heartbeat_count": len(long_heartbeats),
            "compute_heartbeat_count": len(compute_heartbeats),
            "temperature_min_c": min(temperatures) if temperatures else None,
            "temperature_max_c": max(temperatures) if temperatures else None,
            "camera_create_events": value.count("VsiCamDeviceCreate hw:0-vt:0 created"),
            "buffer_reference_warnings": value.count("someone is using vb now"),
            "sensor_power_warnings": value.count("kd_mpi_sensor_power_set, error(1)"),
        },
    }
    failed: list[str] = []
    start_markers = (
        "AIRTOS_K230_FULL_24H_HOST_START ",
        "AIRTOS_K230_LONG_START duration_seconds=86400 minimum_jobs=1000000",
        "AIRTOS_K230_COMPUTE_START duration_seconds=86400 minimum_batches=1000000 sessions=4 deadline_us=300000",
        "AIRTOS_K230_MIXED_START duration_seconds=86400 heartbeat_seconds=60 models=2",
    )
    for marker in start_markers:
        if marker not in value:
            failed.append("missing_start_" + marker.split()[0].lower())
    if long_result is None:
        failed.append("missing_long_result")
    else:
        summary["long"] = dict(zip(
            ("elapsed_seconds", "jobs", "data_failures", "device_failures", "lifecycle_failures", "temperature_c"),
            (*map(int, long_result[:5]), float(long_result[5])), strict=True))
        if int(long_result[0]) < 86400 or int(long_result[1]) < 1_000_000 or any(map(int, long_result[2:5])):
            failed.append("long_threshold")
    if compute_result is None:
        failed.append("missing_compute_result")
    else:
        summary["compute"] = dict(zip(
            ("elapsed_seconds", "batches", "jobs", "runtime_failures", "numeric_failures", "lease_failures",
             "stale_failures", "deadline_failures", "maximum_batch_us"), map(int, compute_result), strict=True))
        if (int(compute_result[0]) < 86400 or int(compute_result[1]) < 1_000_000
                or int(compute_result[2]) != 4 * int(compute_result[1]) or any(map(int, compute_result[3:8]))):
            failed.append("compute_threshold")
    if mixed_result is None:
        failed.append("missing_mixed_result")
    else:
        summary["mixed"] = dict(zip(
            ("elapsed_seconds", "frames", "object_inferences", "face_inferences", "camera_restarts", "kpu_restarts",
             "frame_failures", "inference_failures", "ide_interrupts", "lifecycle_failures", "maximum_frame_ms"),
            (int(item) if item is not None else 0 for item in mixed_result), strict=True))
        if (int(mixed_result[0]) < 86400 or int(mixed_result[1]) == 0
                or int(mixed_result[2]) != int(mixed_result[1]) or int(mixed_result[3]) == 0
                or int(mixed_result[4]) == 0 or int(mixed_result[5]) == 0
                or int(mixed_result[6]) != 0 or int(mixed_result[7]) != 0 or int(mixed_result[9]) != 0):
            failed.append("mixed_threshold")
    for marker in ("AIRTOS_K230_LONG_PASS", "AIRTOS_K230_COMPUTE_PASS", "AIRTOS_K230_MIXED_PASS",
                   "AIRTOS_K230_FULL_24H_PASS"):
        if marker not in value:
            failed.append("missing_" + marker.lower())
    if re.search(r"AIRTOS_K230_(?:LONG|COMPUTE|MIXED)_FAIL", value):
        failed.append("failure_marker")
    summary["failed_checks"] = failed
    summary["status"] = "PASS" if not failed else "INCOMPLETE_OR_FAIL"
    return summary


def selftest() -> None:
    sample = b"\n".join((
        b"AIRTOS_K230_FULL_24H_HOST_START 2026-08-05T00:00:00Z",
        b"AIRTOS_K230_LONG_START duration_seconds=86400 minimum_jobs=1000000 heartbeat_jobs=100000 temperature_c=40.0",
        b"AIRTOS_K230_COMPUTE_START duration_seconds=86400 minimum_batches=1000000 sessions=4 deadline_us=300000",
        b"AIRTOS_K230_MIXED_START duration_seconds=86400 heartbeat_seconds=60 models=2",
        b"AIRTOS_K230_LONG_RESULT elapsed_seconds=86400 jobs=1000000 data_failures=0 device_failures=0 lifecycle_failures=0 temperature_c=55.0",
        b"AIRTOS_K230_LONG_PASS",
        b"AIRTOS_K230_COMPUTE_RESULT elapsed_seconds=86400 batches=1000000 jobs=4000000 runtime_failures=0 numeric_failures=0 lease_failures=0 stale_failures=0 deadline_failures=0 maximum_batch_us=90000",
        b"AIRTOS_K230_COMPUTE_PASS",
        b"AIRTOS_K230_MIXED_RESULT elapsed_seconds=86400 frames=100 object_inferences=100 face_inferences=10 camera_restarts=1 kpu_restarts=2 frame_failures=0 inference_failures=0 ide_interrupts=1 lifecycle_failures=0 maximum_frame_ms=90",
        b"AIRTOS_K230_MIXED_PASS",
        b"AIRTOS_K230_FULL_24H_PASS",
    ))
    assert summarize(sample)["status"] == "PASS"
    assert summarize(sample.replace(b"frame_failures=0", b"frame_failures=1"))["status"] != "PASS"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, nargs="?")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("AIRTOS_K230_FULL_24H_SUMMARY_SELFTEST_PASS")
        return 0
    if args.log is None:
        parser.error("log is required unless --selftest is used")
    summary = summarize(args.log.read_bytes())
    payload = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

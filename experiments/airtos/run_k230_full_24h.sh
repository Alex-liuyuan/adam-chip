#!/usr/bin/env bash
set -euo pipefail

root=/root/myproject/adam/chip
result_dir="$root/docs/paper_orchestra_trilogy/paper3_airtos/results/airtos-exp-v8-20260805-k230-24h"
log="$result_dir/logs/core4/full_24h_formal.log"
manifest="$result_dir/formal_24h_environment.env"
compute_binary="$result_dir/k230_compute_long_hil"
compute_binary_source="$root/docs/paper_orchestra_trilogy/paper3_airtos/results/airtos-exp-v7-20260805-k230-24h/k230_compute_long_hil"

mkdir -p "$result_dir/logs/core4"
if [[ -e "$log" || -e "$manifest" ]]; then
    echo "formal 24-hour artifacts already exist; refusing to overwrite" >&2
    exit 2
fi
if [[ ! -x "$compute_binary" ]]; then
    cp "$compute_binary_source" "$compute_binary"
fi

{
    echo "experiment_id=AIRTOS-K230-260805-003"
    echo "start_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "earliest_valid_end_utc=$(date -u -d '+24 hours' +%Y-%m-%dT%H:%M:%SZ)"
    echo "board=CanMV-K230-LP4_V3.0"
    echo "architecture=RISC-V_64_with_vector_extension"
    echo "duration_seconds=86400"
    echo "transport_timeout_seconds=90000"
    echo "data_minimum_jobs=1000000"
    echo "compute_minimum_batches=1000000"
    echo "compute_sessions=4"
    echo "compute_deadline_us=300000"
    echo "camera=OV5647"
    echo "models=object_detection,face_detection"
    echo "console=/dev/serial/by-id/usb-1a86_USB_Dual_Serial_5C78109061-if00"
    echo "ide=/dev/serial/by-id/usb-Kendryte_CanMV_001000000-if00"
    echo "transport_sha256=$(sha256sum "$root/experiments/airtos/k230_hil_transport.py" | cut -d ' ' -f1)"
    echo "data_source_sha256=$(sha256sum "$root/experiments/airtos/k230_long_hil.c" | cut -d ' ' -f1)"
    echo "compute_source_sha256=$(sha256sum "$root/experiments/airtos/k230_compute_long_hil.c" | cut -d ' ' -f1)"
    echo "mixed_source_sha256=$(sha256sum "$root/experiments/airtos/k230_mixed_24h.py" | cut -d ' ' -f1)"
    echo "compute_binary_sha256=$(sha256sum "$compute_binary" | cut -d ' ' -f1)"
} >"$manifest"

exec >>"$log" 2>&1
echo "AIRTOS_K230_FULL_24H_HOST_START $(date -u +%Y-%m-%dT%H:%M:%SZ)"
exec python3 "$root/experiments/airtos/k230_hil_transport.py" mixed \
    "$root/experiments/airtos/k230_mixed_24h.py" \
    --command '/sdcard/airtos/long_hil 86400 1000000 100000 /sdcard/airtos/long_hil.log &' \
    --command '/sdcard/airtos/compute_long_hil 86400 1000000 10000 300000 /sdcard/airtos/compute_24h.log &' \
    --verify-command 'cat /sdcard/airtos/long_hil.log' \
    --verify-command 'cat /sdcard/airtos/compute_24h.log' \
    --verify-command 'cat /sdcard/airtos/mixed_24h.log' \
    --duration 86400 \
    --heartbeat 60 \
    --timeout 90000

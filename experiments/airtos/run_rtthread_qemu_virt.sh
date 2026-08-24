#!/usr/bin/env bash
set -Eeuo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
out=${1:?usage: run_rtthread_qemu_virt.sh OUT_DIR}
platform=$root/build/phase_reports/phase10-final/integration/generated/platform
target_include=$root/results/airtos/airtos-exp-v1-20260804-hostqemu/production_rt_ai_repaired/integration/generated/rt_ai/os/include
test ! -e "$out"
mkdir -p "$out/staging"
trap 'status=$?; printf "exit_status=%s\n" "$status" > "$out/RUN_FAILED"; exit "$status"' ERR

cp -a "$platform/." "$out/staging/"
cp "$root/experiments/airtos/rtthread_qemu_main.c" "$out/staging/rtthread/main.c"
cp "$root/experiments/airtos/rtthread_generated_SConscript" "$out/staging/rtthread/SConscript"

export RTT_ROOT=$root/third_party/rt-thread
export RTT_EXEC_PATH=/usr/bin
export RTT_CC_PREFIX=riscv64-linux-gnu-
export AIRTOS_ROOT=$root
export AIRTOS_TARGET_INCLUDE=$target_include
export SOURCE_DATE_EPOCH=0

(cd "$out/staging/rtthread" && scons -c >/dev/null && scons -j2) > "$out/build.log" 2>&1
timeout 20s qemu-system-riscv64 -nographic -machine virt -m 256M \
    -kernel "$out/staging/rtthread/rtthread.elf" > "$out/run.log" 2>&1
test "$(grep -c '^AIRTOS_RTTHREAD_PASS machine=virt64 ' "$out/run.log")" -eq 1
test "$(grep -c 'RT -     Thread' "$out/run.log")" -eq 1

{
    date -u +generated_at=%Y-%m-%dT%H:%M:%SZ
    printf 'qemu='; qemu-system-riscv64 --version | head -1
    printf 'compiler='; riscv64-linux-gnu-gcc -dumpfullversion
    printf 'git_commit='; git -C "$root" rev-parse HEAD
    printf 'firmware_sha256='; sha256sum "$out/staging/rtthread/rtthread.elf" | cut -d' ' -f1
} > "$out/environment.env"
find "$out" -type f ! -path '*/staging/build/*' ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > "$out/SHA256SUMS"
printf 'status=PASS\n' > "$out/RUN_PASS"

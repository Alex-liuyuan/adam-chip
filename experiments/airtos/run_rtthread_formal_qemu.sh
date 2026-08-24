#!/usr/bin/env bash
set -Eeuo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
out=$(realpath -m "${1:?usage: run_rtthread_formal_qemu.sh OUT_DIR CORPUS [PLATFORM [TARGET_INCLUDE]]}")
corpus=$(realpath "${2:?usage: run_rtthread_formal_qemu.sh OUT_DIR CORPUS [PLATFORM [TARGET_INCLUDE]]}")
platform=$(realpath "${3:-${AIRTOS_RTTHREAD_PLATFORM:-$root/build/phase_reports/phase10-final/integration/generated/platform}}")
target_include=$(realpath "${4:-${AIRTOS_TARGET_INCLUDE:-$root/results/airtos/airtos-exp-v1-20260804-hostqemu/production_rt_ai_repaired/integration/generated/rt_ai/os/include}}")
test ! -e "$out"
test -f "$corpus"
test -f "$platform/rtthread/SConstruct"
test -f "$target_include/rt_ai_target.h"
sync "$corpus"
mkdir -p "$out/staging"
trap 'status=$?; printf "exit_status=%s\n" "$status" > "$out/RUN_FAILED"; exit "$status"' ERR

cp -a "$platform/." "$out/staging/"
cp "$root/experiments/airtos/rtthread_formal_main.c" "$out/staging/rtthread/main.c"
cp "$root/experiments/airtos/rtthread_generated_SConscript" "$out/staging/rtthread/SConscript"
sed -i 's/^#define RT_MAIN_THREAD_STACK_SIZE .*/#define RT_MAIN_THREAD_STACK_SIZE 32768/' \
    "$out/staging/rtthread/rtconfig.h"

export RTT_ROOT=$root/third_party/rt-thread
export RTT_EXEC_PATH=/usr/bin
export RTT_CC_PREFIX=riscv64-linux-gnu-
export AIRTOS_ROOT=$root
export AIRTOS_TARGET_INCLUDE=$target_include
export SOURCE_DATE_EPOCH=0

(cd "$out/staging/rtthread" && scons -c >/dev/null && scons -j2) > "$out/build.log" 2>&1
boot_pass=0
for attempt in 1 2; do
    attempt_log="$out/run_attempt_${attempt}.log"
    if timeout 180s qemu-system-riscv64 -nographic -monitor none -machine virt -m 256M \
        -device loader,file="$corpus",addr=0x88000000,force-raw=on \
        -kernel "$out/staging/rtthread/rtthread.elf" </dev/null > "$attempt_log" 2>&1 && \
        test "$(grep -a -c '^AIRTOS_RTTHREAD_FORMAL_PASS machine=virt64 coherency_cases=1000000' "$attempt_log")" -eq 1; then
        cp "$attempt_log" "$out/run.log"
        boot_pass=1
        break
    fi
done
test "$boot_pass" -eq 1

{
    date -u +generated_at=%Y-%m-%dT%H:%M:%SZ
    printf 'qemu='; qemu-system-riscv64 --version | head -1
    printf 'compiler='; riscv64-linux-gnu-gcc -dumpfullversion
    printf 'git_commit='; git -C "$root" rev-parse HEAD
    printf 'corpus_sha256='; sha256sum "$corpus" | cut -d' ' -f1
    printf 'firmware_sha256='; sha256sum "$out/staging/rtthread/rtthread.elf" | cut -d' ' -f1
    printf 'main_thread_stack_bytes=32768\n'
} > "$out/environment.env"
find "$out" -type f ! -path '*/staging/build/*' ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > "$out/SHA256SUMS"
printf 'status=PASS\n' > "$out/RUN_PASS"

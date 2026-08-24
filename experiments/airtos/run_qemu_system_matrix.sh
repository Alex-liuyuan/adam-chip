#!/usr/bin/env bash
set -Eeuo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
out=$(realpath -m "${1:?usage: run_qemu_system_matrix.sh OUT_DIR CORPUS [TARGET_INCLUDE]}")
corpus=$(realpath "${2:?usage: run_qemu_system_matrix.sh OUT_DIR CORPUS [TARGET_INCLUDE]}")
target_include=$(realpath "${3:-${AIRTOS_TARGET_INCLUDE:-$root/results/airtos/airtos-exp-v1-20260804-hostqemu/production_rt_ai_repaired/integration/generated/rt_ai/os/include}}")
test ! -e "$out"
test -f "$corpus"
test -f "$target_include/rt_ai_target.h"
sync "$corpus"
mkdir -p "$out"/{bin,logs}
trap 'status=$?; printf "exit_status=%s\n" "$status" > "$out/RUN_FAILED"; exit "$status"' ERR

common=(-std=c11 -Os -g -ffreestanding -fno-builtin -fdata-sections -ffunction-sections
    -mthumb -mfloat-abi=soft -Wall -Wextra -Werror -I"$root/engine/rt_ai_templates/include"
    -I"$target_include" -nostdlib -Wl,--gc-sections)

{
    date -u +generated_at=%Y-%m-%dT%H:%M:%SZ
    printf 'qemu='; qemu-system-arm --version | head -1
    printf 'compiler='; arm-none-eabi-gcc -dumpfullversion
    printf 'git_commit='; git -C "$root" rev-parse HEAD
    printf 'target_header_sha256='; sha256sum "$target_include/rt_ai_target.h" | cut -d' ' -f1
    printf 'corpus_sha256='; sha256sum "$corpus" | cut -d' ' -f1
} > "$out/environment.env"

run_machine() {
    local machine=$1 cpu=$2 linker=$3
    local elf=$out/bin/$machine.elf log=$out/logs/$machine.log
    arm-none-eabi-gcc "${common[@]}" -mcpu="$cpu" -T"$linker" -DMACHINE_NAME=\"$machine\" \
        -DCORPUS_PATH=\"$(realpath "$corpus")\" "$root/experiments/airtos/qemu_arm_formal.c" \
        "$root/experiments/airtos/coherency_formal.c" "$root/engine/rt_ai_templates/runtime/aeg_loader.c" \
        "$root/engine/rt_ai_templates/os/coherency.c" "$root/engine/rt_ai_templates/os/plan_select.c" \
        "$root/engine/rt_ai_templates/os/sim_edf.c" -lgcc -o "$elf"
    timeout 300s qemu-system-arm -M "$machine" -cpu "$cpu" -nographic -monitor none \
        -semihosting-config enable=on,target=native -kernel "$elf" </dev/null > "$log" 2>&1
    test "$(grep -c "^AIRTOS_ARM_FORMAL_PASS machine=$machine loader_cases=7950 schedule_cases=24548 coherency_cases=1000000 failures=0" "$log")" -eq 1
}

run_machine mps2-an385 cortex-m3 "$root/experiments/airtos/qemu_mps2.ld"
run_machine mps2-an386 cortex-m4 "$root/experiments/airtos/qemu_mps2.ld"
run_machine mps2-an500 cortex-m7 "$root/experiments/airtos/qemu_mps2.ld"
run_machine lm3s6965evb cortex-m3 "$root/experiments/airtos/qemu_lm3s6965evb.ld"

find "$out" -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > "$out/SHA256SUMS"
printf 'status=PASS\n' > "$out/RUN_PASS"

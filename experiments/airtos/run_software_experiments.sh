#!/usr/bin/env bash
set -Eeuo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
out=${1:?usage: run_software_experiments.sh OUT_DIR [AEG [TARGET_INCLUDE [TRUST_MATERIALS [RTTHREAD_PLATFORM]]]]}
aeg=${2:-${AIRTOS_AEG:-$root/results/airtos/airtos-exp-v1-20260804-hostqemu/apparatus/compiler_corrected/model.aeg}}
target_include=${3:-${AIRTOS_TARGET_INCLUDE:-$root/results/airtos/airtos-exp-v1-20260804-hostqemu/production_rt_ai_repaired/integration/generated/rt_ai/os/include}}
trust_materials=${4:-${AIRTOS_TRUST_MATERIALS:-$(dirname "$aeg")}}
rtthread_platform=${5:-${AIRTOS_RTTHREAD_PLATFORM:-$root/build/phase_reports/phase10-final/integration/generated/platform}}
test ! -e "$out"
test -f "$aeg"
test -f "$target_include/rt_ai_target.h"
mkdir -p "$out"/{bin,core1,core2,core3,core4,regression}
trap 'status=$?; printf "exit_status=%s\n" "$status" > "$out/RUN_FAILED"; exit "$status"' ERR

{
    date -u +generated_at=%Y-%m-%dT%H:%M:%SZ
    printf 'kernel='; uname -srmo
    printf 'gcc='; gcc -dumpfullversion
    printf 'riscv_gcc='; riscv64-linux-gnu-gcc -dumpfullversion
    printf 'qemu='; qemu-riscv64 --version | head -1
    printf 'python='; python3 --version
    printf 'git_commit='; git -C "$root" rev-parse HEAD
    printf 'aeg='; realpath "$aeg"
    printf 'aeg_sha256='; sha256sum "$aeg" | cut -d' ' -f1
    printf 'target_header='; realpath "$target_include/rt_ai_target.h"
    printf 'target_header_sha256='; sha256sum "$target_include/rt_ai_target.h" | cut -d' ' -f1
} > "$out/environment.env"

python3 "$root/experiments/airtos/formal_suite.py" --aeg "$aeg" --out "$out/core12" \
    > "$out/core12.stdout.log" 2> "$out/core12.stderr.log"

sources=(
    "$root/engine/rt_ai_templates/runtime/aeg_loader.c"
    "$root/engine/rt_ai_templates/runtime/evidence.c"
    "$root/engine/rt_ai_templates/runtime/session.c"
    "$root/engine/rt_ai_templates/runtime/rt_ai_port_host.c"
    "$root/engine/rt_ai_templates/os/admission.c"
    "$root/engine/rt_ai_templates/os/coherency.c"
    "$root/engine/rt_ai_templates/os/coordinator.c"
    "$root/engine/rt_ai_templates/os/plan_select.c"
    "$root/engine/rt_ai_templates/os/recovery.c"
    "$root/engine/rt_ai_templates/os/resource_queue.c"
    "$root/engine/rt_ai_templates/os/sim_edf.c"
    "$root/engine/rt_ai_templates/os/tensor_memory.c"
    "$root/engine/rt_ai_templates/os/trace.c"
)
common=(-std=c11 -O2 -Wall -Wextra -Werror -pthread -I"$root/engine/rt_ai_templates/include" -I"$target_include")
riscv=(-static -march=rv64gc -mabi=lp64d)

build_pair() {
    local source=$1 name=$2
    gcc "${common[@]}" "$source" "${sources[@]}" -o "$out/bin/${name}_host"
    riscv64-linux-gnu-gcc "${common[@]}" "${riscv[@]}" "$source" "${sources[@]}" -o "$out/bin/${name}_riscv64"
}

build_pair "$root/experiments/airtos/admission_harness.c" admission_harness
gcc "${common[@]}" -DAIRTOS_COHERENCY_FORMAL_MAIN "$root/experiments/airtos/coherency_formal.c" \
    "$root/engine/rt_ai_templates/os/coherency.c" "$root/engine/rt_ai_templates/os/plan_select.c" \
    -o "$out/bin/coherency_formal_host"
riscv64-linux-gnu-gcc "${common[@]}" "${riscv[@]}" -DAIRTOS_COHERENCY_FORMAL_MAIN \
    "$root/experiments/airtos/coherency_formal.c" "$root/engine/rt_ai_templates/os/coherency.c" \
    "$root/engine/rt_ai_templates/os/plan_select.c" -o "$out/bin/coherency_formal_riscv64"
gcc "${common[@]}" "$root/experiments/airtos/concurrency_probe.c" "${sources[@]}" -o "$out/bin/concurrency_probe_host"
build_pair "$root/experiments/airtos/stale_replay.c" stale_replay
build_pair "$root/experiments/airtos/recovery_harness.c" recovery_harness
build_pair "$root/experiments/airtos/cookie_wrap_probe.c" cookie_wrap_probe
gcc "${common[@]}" "$root/experiments/airtos/overhead_benchmark.c" "${sources[@]}" \
    -o "$out/bin/overhead_benchmark_host"

"$out/bin/admission_harness_host" admission "$aeg" 300 > "$out/core1/admission_host.log"
qemu-riscv64 -cpu max "$out/bin/admission_harness_riscv64" admission "$aeg" 300 > "$out/core1/admission_qemu.log"
"$out/bin/admission_harness_host" diagnostics "$aeg" 300 > "$out/core1/diagnostics_host.log"
qemu-riscv64 -cpu max "$out/bin/admission_harness_riscv64" diagnostics "$aeg" 300 > "$out/core1/diagnostics_qemu.log"
"$out/bin/admission_harness_host" health_race "$aeg" 300 > "$out/core1/health_race_host.log"
qemu-riscv64 -cpu max "$out/bin/admission_harness_riscv64" health_race "$aeg" 300 > "$out/core1/health_race_qemu.log"
"$out/bin/admission_harness_host" trust_rotation "$aeg" 300 > "$out/core1/trust_rotation_host.log"
qemu-riscv64 -cpu max "$out/bin/admission_harness_riscv64" trust_rotation "$aeg" 300 > "$out/core1/trust_rotation_qemu.log"
python3 "$root/experiments/airtos/trust_material_harness.py" --materials "$trust_materials" \
    --repetitions 300 --output "$out/core1/trust_material.csv" > "$out/core1/trust_material.log"
for threads in 2 4 8 16; do
    "$out/bin/admission_harness_host" transactions "$aeg" "$threads" 100000 \
        > "$out/core1/transactions_${threads}.log"
done
"$out/bin/coherency_formal_host" 1000000 > "$out/core3/coherency_host.log"
qemu-riscv64 -cpu max "$out/bin/coherency_formal_riscv64" 1000000 > "$out/core3/coherency_qemu.log"

"$out/bin/overhead_benchmark_host" "$aeg" > "$out/core2/overhead_host.csv"
size "$out/bin/overhead_benchmark_host" > "$out/core2/overhead_binary_size.log"

for threads in 2 4 8 16; do
    "$out/bin/concurrency_probe_host" "$threads" "$((250000 / threads))" \
        > "$out/core3/allocator_${threads}.log"
done

"$out/bin/stale_replay_host" 100000 > "$out/core4/stale_host.log"
qemu-riscv64 -cpu max "$out/bin/stale_replay_riscv64" 100000 > "$out/core4/stale_qemu.log"
"$out/bin/recovery_harness_host" "$aeg" 300 > "$out/core4/recovery_host.log"
qemu-riscv64 -cpu max "$out/bin/recovery_harness_riscv64" "$aeg" 300 > "$out/core4/recovery_qemu.log"
"$out/bin/recovery_harness_host" budget "$aeg" 300 > "$out/core4/recovery_budget_host.log"
qemu-riscv64 -cpu max "$out/bin/recovery_harness_riscv64" budget "$aeg" 300 > "$out/core4/recovery_budget_qemu.log"
"$out/bin/recovery_harness_host" gates "$aeg" 300 > "$out/core4/fallback_gates_host.log"
qemu-riscv64 -cpu max "$out/bin/recovery_harness_riscv64" gates "$aeg" 300 > "$out/core4/fallback_gates_qemu.log"
"$out/bin/recovery_harness_host" trace "$aeg" 100 > "$out/core4/trace_classifier_host.log"
qemu-riscv64 -cpu max "$out/bin/recovery_harness_riscv64" trace "$aeg" 100 > "$out/core4/trace_classifier_qemu.log"
"$out/bin/recovery_harness_host" trace_robust "$aeg" 300 > "$out/core4/trace_robustness_host.log"
qemu-riscv64 -cpu max "$out/bin/recovery_harness_riscv64" trace_robust "$aeg" 300 > "$out/core4/trace_robustness_qemu.log"
"$out/bin/cookie_wrap_probe_host" > "$out/core4/cookie_host.log"
qemu-riscv64 -cpu max "$out/bin/cookie_wrap_probe_riscv64" > "$out/core4/cookie_qemu.log"

gcc "${common[@]}" "$root/engine/rt_ai_templates/tests/test_rt_ai.c" "${sources[@]}" \
    -o "$out/bin/test_rt_ai_host"
gcc "${common[@]}" -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer \
    "$root/engine/rt_ai_templates/tests/test_rt_ai.c" "${sources[@]}" -o "$out/bin/test_rt_ai_asan"
riscv64-linux-gnu-gcc "${common[@]}" "${riscv[@]}" \
    "$root/engine/rt_ai_templates/tests/test_rt_ai.c" "${sources[@]}" -o "$out/bin/test_rt_ai_riscv64"
"$out/bin/test_rt_ai_host" > "$out/regression/host.log"
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 \
    "$out/bin/test_rt_ai_asan" > "$out/regression/asan_ubsan.log"
qemu-riscv64 -cpu max "$out/bin/test_rt_ai_riscv64" > "$out/regression/qemu.log"

bash "$root/experiments/airtos/run_rtthread_formal_qemu.sh" \
    "$out/core2/rtthread_virt" "$out/core12/rtthread_formal_corpus.bin" \
    "$rtthread_platform" "$target_include"
bash "$root/experiments/airtos/run_qemu_system_matrix.sh" \
    "$out/core2/arm_system_matrix" "$out/core12/rtthread_formal_corpus.bin" "$target_include"

find "$out" -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > "$out/SHA256SUMS"
printf 'status=PASS\n' > "$out/RUN_PASS"

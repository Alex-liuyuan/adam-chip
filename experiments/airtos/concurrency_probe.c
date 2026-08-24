#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rt_ai_internal.h"

#define ARENA_BYTES 256U

typedef struct {
    rt_ai_runtime_t *runtime;
    atomic_int *owners;
    atomic_uint *successful_leases;
    atomic_uint *overlaps;
    atomic_uint *canary_corruptions;
    atomic_uint *reference_diffs;
    unsigned id;
    unsigned operations;
} worker_arg_t;

static void *worker(void *opaque)
{
    worker_arg_t *arg = (worker_arg_t *)opaque;
    uint32_t random = UINT32_C(0x9e3779b9) ^ arg->id;
    unsigned operation;
    for (operation = 0U; operation < arg->operations; ++operation) {
        rt_ai_arena_lease_t lease;
        size_t payload_size;
        size_t index;
        uint8_t guard;
        uint8_t inverse_guard;
        int conflict = 0;
        random = random * UINT32_C(1664525) + UINT32_C(1013904223);
        payload_size = (random >> 8U) % 16U + 1U;
        if (rt_ai_arena_lease(arg->runtime, payload_size + 2U, &lease) != RT_AI_OK) continue;
        atomic_fetch_add(arg->successful_leases, 1U);
        for (index = lease.offset; index < lease.offset + lease.size; ++index) {
            int expected = -1;
            if (!atomic_compare_exchange_strong(&arg->owners[index], &expected, (int)arg->id)) {
                atomic_fetch_add(arg->overlaps, 1U);
                conflict = 1;
            }
        }
        guard = (uint8_t)(UINT8_C(0xa5) ^ (uint8_t)arg->id ^ (uint8_t)operation);
        inverse_guard = (uint8_t)(guard ^ UINT8_MAX);
        if (!conflict) {
            arg->runtime->arena[lease.offset] = guard;
            arg->runtime->arena[lease.offset + lease.size - 1U] = inverse_guard;
            for (index = 1U; index + 1U < lease.size; ++index)
                arg->runtime->arena[lease.offset + index] = (uint8_t)(guard + (uint8_t)index * UINT8_C(17));
            sched_yield();
            if (arg->runtime->arena[lease.offset] != guard ||
                arg->runtime->arena[lease.offset + lease.size - 1U] != inverse_guard)
                atomic_fetch_add(arg->canary_corruptions, 1U);
            for (index = 1U; index + 1U < lease.size; ++index)
                if (arg->runtime->arena[lease.offset + index] != (uint8_t)(guard + (uint8_t)index * UINT8_C(17)))
                    atomic_fetch_add(arg->reference_diffs, 1U);
        }
        for (index = lease.offset; index < lease.offset + lease.size; ++index)
            if (atomic_load(&arg->owners[index]) == (int)arg->id) atomic_store(&arg->owners[index], -1);
        rt_ai_arena_release(arg->runtime, &lease);
    }
    return NULL;
}

int main(int argc, char **argv)
{
    uint8_t arena[ARENA_BYTES];
    rt_ai_runtime_t runtime;
    unsigned thread_count = 8U;
    unsigned operations = 10000U;
    pthread_t *threads;
    worker_arg_t *arguments;
    atomic_int owners[ARENA_BYTES];
    atomic_uint successful_leases = 0U;
    atomic_uint overlaps = 0U;
    atomic_uint canary_corruptions = 0U;
    atomic_uint reference_diffs = 0U;
    unsigned generation_race_failures = 0U;
    unsigned rollback_leaks = 0U;
    unsigned index;

    if (argc == 3) {
        thread_count = (unsigned)strtoul(argv[1], NULL, 10);
        operations = (unsigned)strtoul(argv[2], NULL, 10);
    } else if (argc != 1) return 2;
    if (thread_count < 2U || thread_count > 16U || operations == 0U) return 2;
    threads = (pthread_t *)calloc(thread_count, sizeof(*threads));
    arguments = (worker_arg_t *)calloc(thread_count, sizeof(*arguments));
    if (threads == NULL || arguments == NULL) return 3;
    memset(arena, 0, sizeof(arena));
    assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
    for (index = 0U; index < ARENA_BYTES; ++index) atomic_init(&owners[index], -1);
    for (index = 0U; index < thread_count; ++index) {
        arguments[index] = (worker_arg_t){&runtime, owners, &successful_leases, &overlaps,
            &canary_corruptions, &reference_diffs, index, operations};
        assert(pthread_create(&threads[index], NULL, worker, &arguments[index]) == 0);
    }
    for (index = 0U; index < thread_count; ++index) assert(pthread_join(threads[index], NULL) == 0);
    for (index = 0U; index < 10000U; ++index) {
        rt_ai_arena_lease_t stale, interfering;
        uint32_t generation;
        if (rt_ai_arena_probe(&runtime, 8U, &stale, &generation) != RT_AI_OK ||
            rt_ai_arena_lease(&runtime, 8U, &interfering) != RT_AI_OK) {
            ++generation_race_failures;
            continue;
        }
        rt_ai_arena_release(&runtime, &interfering);
        if (rt_ai_arena_commit(&runtime, &stale, generation) != RT_AI_BUSY || stale.used) ++generation_race_failures;
    }
    for (index = 0U; index < RT_AI_MAX_LEASES; ++index) if (runtime.leases[index].used) ++rollback_leaks;
    printf("CONCURRENCY_PROBE threads=%u attempts=%u successful_leases=%u overlaps=%u "
           "canary_corruptions=%u cross_session_diffs=%u generation_race_failures=%u rollback_leaks=%u\n",
        thread_count, thread_count * operations, atomic_load(&successful_leases), atomic_load(&overlaps),
        atomic_load(&canary_corruptions), atomic_load(&reference_diffs), generation_race_failures, rollback_leaks);
    free(arguments);
    free(threads);
    return atomic_load(&overlaps) == 0U && atomic_load(&canary_corruptions) == 0U &&
        atomic_load(&reference_diffs) == 0U && generation_race_failures == 0U && rollback_leaks == 0U ? 0 : 1;
}

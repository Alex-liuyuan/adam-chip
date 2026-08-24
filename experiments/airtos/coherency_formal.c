#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "coherency_formal.h"
#include "rt_ai_internal.h"
#include "rt_ai_target.h"

#define FORMAL_ARENA_SIZE 384U
#define FORMAL_LEASE_OFFSET 64U
#define FORMAL_LEASE_SIZE 256U

enum { ACTION_CLEAN = 1U, ACTION_INVALIDATE = 2U, ACTION_BARRIER = 3U };
enum {
    MODE_COMPLETE = 0U,
    MODE_MISSING_CLEAN,
    MODE_MISSING_INVALIDATE,
    MODE_FAIL_CLEAN,
    MODE_FAIL_INVALIDATE,
    MODE_FAIL_BARRIER,
    MODE_LEGACY,
    MODE_NO_BARRIER,
    MODE_COUNT
};

typedef struct {
    uint8_t *arena;
    uint8_t action[8];
    size_t offset[8];
    size_t size[8];
    uint8_t count;
    uint8_t fail_action;
} observer_t;

typedef struct {
    uint8_t action[8];
    uint8_t count;
    int status;
} expected_t;

static int record(observer_t *observer, uint8_t action, void *address, size_t size)
{
    uint8_t index = observer->count;
    if (index < sizeof(observer->action)) {
        observer->action[index] = action;
        observer->offset[index] = address == NULL ? 0U : (size_t)((uint8_t *)address - observer->arena);
        observer->size[index] = size;
    }
    ++observer->count;
    return observer->fail_action == action ? RT_AI_ERR_PROVIDER : RT_AI_OK;
}

static int clean_range(void *opaque, void *address, size_t size)
{
    return record((observer_t *)opaque, ACTION_CLEAN, address, size);
}

static int invalidate_range(void *opaque, void *address, size_t size)
{
    return record((observer_t *)opaque, ACTION_INVALIDATE, address, size);
}

static int barrier(void *opaque)
{
    return record((observer_t *)opaque, ACTION_BARRIER, NULL, 0U);
}

static void clean_legacy(void *opaque, void *address, size_t size)
{
    (void)record((observer_t *)opaque, ACTION_CLEAN, address, size);
}

static void invalidate_legacy(void *opaque, void *address, size_t size)
{
    (void)record((observer_t *)opaque, ACTION_INVALIDATE, address, size);
}

static void append(expected_t *expected, uint8_t action)
{
    expected->action[expected->count++] = action;
}

static expected_t expected_before(uint8_t flags, uint8_t mode, int valid)
{
    expected_t expected;
    memset(&expected, 0, sizeof(expected));
    if (!valid) { expected.status = RT_AI_ERR_INVALID; return expected; }
    if ((flags & RT_AI_SEGMENT_CLEAN_INPUT) != 0U) {
        if (mode == MODE_MISSING_CLEAN) { expected.status = RT_AI_ERR_PROVIDER; return expected; }
        append(&expected, ACTION_CLEAN);
        if (mode == MODE_FAIL_CLEAN) { expected.status = RT_AI_ERR_PROVIDER; return expected; }
    }
    if (mode != MODE_NO_BARRIER) {
        append(&expected, ACTION_BARRIER);
        if (mode == MODE_FAIL_BARRIER) { expected.status = RT_AI_ERR_PROVIDER; return expected; }
    }
    expected.status = RT_AI_OK;
    return expected;
}

static expected_t expected_after(uint8_t flags, uint8_t mode, int valid)
{
    expected_t expected;
    memset(&expected, 0, sizeof(expected));
    if (!valid) { expected.status = RT_AI_ERR_INVALID; return expected; }
    if (mode != MODE_NO_BARRIER) {
        append(&expected, ACTION_BARRIER);
        if (mode == MODE_FAIL_BARRIER) { expected.status = RT_AI_ERR_PROVIDER; return expected; }
    }
    if ((flags & RT_AI_SEGMENT_INVALIDATE_OUTPUT) != 0U) {
        if (mode == MODE_MISSING_INVALIDATE) { expected.status = RT_AI_ERR_PROVIDER; return expected; }
        append(&expected, ACTION_INVALIDATE);
        if (mode == MODE_FAIL_INVALIDATE) { expected.status = RT_AI_ERR_PROVIDER; return expected; }
    }
    if (mode != MODE_NO_BARRIER) append(&expected, ACTION_BARRIER);
    expected.status = RT_AI_OK;
    return expected;
}

static int observation_matches(const observer_t *observer, const expected_t *expected,
    size_t aligned_offset, size_t aligned_size)
{
    uint8_t index;
    if (observer->count != expected->count) return 0;
    for (index = 0U; index < expected->count; ++index) {
        if (observer->action[index] != expected->action[index]) return 0;
        if (expected->action[index] != ACTION_BARRIER &&
            (observer->offset[index] != aligned_offset || observer->size[index] != aligned_size)) return 0;
    }
    return 1;
}

static void configure_provider(rt_ai_provider_t *provider, observer_t *observer, uint8_t mode)
{
    memset(provider, 0, sizeof(*provider));
    provider->resource = RT_AI_RESOURCE_DMA;
    provider->user = observer;
    if (mode == MODE_LEGACY) {
        provider->clean = clean_legacy;
        provider->invalidate = invalidate_legacy;
    } else {
        if (mode != MODE_MISSING_CLEAN) provider->clean_range = clean_range;
        if (mode != MODE_MISSING_INVALIDATE) provider->invalidate_range = invalidate_range;
    }
    if (mode != MODE_NO_BARRIER) provider->barrier = barrier;
    if (mode == MODE_FAIL_CLEAN) observer->fail_action = ACTION_CLEAN;
    else if (mode == MODE_FAIL_INVALIDATE) observer->fail_action = ACTION_INVALIDATE;
    else if (mode == MODE_FAIL_BARRIER) observer->fail_action = ACTION_BARRIER;
}

static uint32_t run_case(uint32_t case_id, uint32_t *negative)
{
    static uint8_t arena[FORMAL_ARENA_SIZE];
    rt_ai_runtime_t runtime;
    rt_ai_session_t session;
    rt_ai_job_t job;
    rt_ai_provider_t provider;
    observer_t observer;
    expected_t expected;
    size_t offset = (size_t)((case_id * UINT32_C(37) + case_id / UINT32_C(17)) % (FORMAL_LEASE_SIZE + 33U));
    size_t size = (size_t)((case_id * UINT32_C(53) + UINT32_C(1)) % 193U) + 1U;
    uint8_t flags = (uint8_t)((case_id / UINT32_C(3)) & 3U);
    uint8_t mode = (uint8_t)((case_id / UINT32_C(11)) % MODE_COUNT);
    int valid = offset <= FORMAL_LEASE_SIZE && size <= FORMAL_LEASE_SIZE - offset;
    size_t start = valid ? offset - offset % RT_AI_CACHE_LINE_BYTES : 0U;
    size_t end = valid ? offset + size : 0U;
    size_t aligned_size;
    uint32_t failures = 0U;
    int status;
    if (valid && end % RT_AI_CACHE_LINE_BYTES != 0U) {
        size_t add = RT_AI_CACHE_LINE_BYTES - end % RT_AI_CACHE_LINE_BYTES;
        end = add > FORMAL_LEASE_SIZE - end ? FORMAL_LEASE_SIZE : end + add;
    }
    aligned_size = valid ? end - start : 0U;
    memset(&runtime, 0, sizeof(runtime));
    memset(&session, 0, sizeof(session));
    memset(&job, 0, sizeof(job));
    memset(&observer, 0, sizeof(observer));
    runtime.arena = arena;
    runtime.arena_size = sizeof(arena);
    session.runtime = &runtime;
    session.aeg.header.segment_count = 1U;
    session.aeg.segments = session.aeg.storage;
    job.session = &session;
    job.lease.offset = FORMAL_LEASE_OFFSET;
    job.lease.size = FORMAL_LEASE_SIZE;
    job.lease.used = 1U;
    session.aeg.storage[0].resource = RT_AI_RESOURCE_DMA;
    session.aeg.storage[0].flags = flags;
    session.aeg.storage[0].arena_offset = (uint32_t)offset;
    session.aeg.storage[0].arena_size = (uint32_t)size;
    observer.arena = arena;
    configure_provider(&provider, &observer, mode);
    runtime.providers[RT_AI_RESOURCE_DMA] = provider;

    job.buffer_owner[0] = 7U;
    expected = expected_before(flags, mode, valid);
    status = rt_ai_coherency_before(&job, 0U);
    if (expected.status != RT_AI_OK) ++*negative;
    if (status != expected.status || !observation_matches(&observer, &expected,
        FORMAL_LEASE_OFFSET + start, aligned_size) ||
        job.buffer_owner[0] != (status == RT_AI_OK ? 1U : 7U)) ++failures;

    memset(&observer, 0, sizeof(observer));
    observer.arena = arena;
    configure_provider(&provider, &observer, mode);
    runtime.providers[RT_AI_RESOURCE_DMA] = provider;
    job.buffer_owner[0] = 7U;
    expected = expected_after(flags, mode, valid);
    status = rt_ai_coherency_after(&job, 0U);
    if (expected.status != RT_AI_OK) ++*negative;
    if (status != expected.status || !observation_matches(&observer, &expected,
        FORMAL_LEASE_OFFSET + start, aligned_size) ||
        job.buffer_owner[0] != (status == RT_AI_OK ? 0U : 7U)) ++failures;
    return failures;
}

int airtos_coherency_formal_run(uint32_t case_count, uint32_t *negative_cases, uint32_t *failures)
{
    uint32_t case_id;
    if (case_count == 0U || negative_cases == NULL || failures == NULL || RT_AI_CACHE_LINE_BYTES == 0U) return 0;
    *negative_cases = 0U;
    *failures = 0U;
    for (case_id = 0U; case_id < case_count; ++case_id) *failures += run_case(case_id, negative_cases);
    return *failures == 0U;
}

#ifdef AIRTOS_COHERENCY_FORMAL_MAIN
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
    uint32_t cases = UINT32_C(1000000), negative = 0U, failures = 0U;
    if (argc == 2) cases = (uint32_t)strtoul(argv[1], NULL, 10);
    if (!airtos_coherency_formal_run(cases, &negative, &failures)) {
        printf("AIRTOS_COHERENCY_FORMAL_FAIL cases=%u negative=%u failures=%u\n", cases, negative, failures);
        return 1;
    }
    printf("AIRTOS_COHERENCY_FORMAL_PASS cases=%u negative=%u failures=0\n", cases, negative);
    return 0;
}
#endif

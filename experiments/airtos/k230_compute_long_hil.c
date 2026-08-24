#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "rt_ai.h"

#define SESSION_COUNT 4U
#define TENSOR_COUNT 8U

typedef struct {
    float input[TENSOR_COUNT];
    float constant[TENSOR_COUNT];
    float output[TENSOR_COUNT];
    uint32_t epoch;
    uint32_t cookie;
    uint64_t submissions;
    uint64_t numeric_failures;
} provider_state_t;

static uint64_t now_us(void)
{
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) return 0U;
    return (uint64_t)value.tv_sec * UINT64_C(1000000) + (uint64_t)value.tv_nsec / UINT64_C(1000);
}

static uint64_t monotonic_seconds(void)
{
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) return 0U;
    return (uint64_t)value.tv_sec;
}

static void sleep_us(long microseconds)
{
    struct timespec value;
    value.tv_sec = microseconds / 1000000L;
    value.tv_nsec = microseconds % 1000000L * 1000L;
    while (nanosleep(&value, &value) != 0) { }
}

static void emit(FILE *log, const char *format, ...)
{
    va_list arguments;
    va_start(arguments, format);
    vprintf(format, arguments);
    va_end(arguments);
    fflush(stdout);
    if (log != NULL) {
        va_start(arguments, format);
        vfprintf(log, format, arguments);
        va_end(arguments);
        fflush(log);
    }
}

static int rvv_add_relu(const float *input, const float *constant, float *output, size_t count)
{
    const float zero = 0.0f;
    while (count != 0U) {
        size_t vl;
        __asm__ volatile(
            "vsetvli %0,%4,e32,m1,ta,ma\n\t"
            "vle32.v v0,(%1)\n\t"
            "vle32.v v1,(%2)\n\t"
            "vfadd.vv v2,v0,v1\n\t"
            "vfmax.vf v2,v2,%5\n\t"
            "vse32.v v2,(%3)"
            : "=&r"(vl)
            : "r"(input), "r"(constant), "r"(output), "r"(count), "f"(zero)
            : "v0", "v1", "v2", "memory");
        input += vl;
        constant += vl;
        output += vl;
        count -= vl;
    }
    return 0;
}

static int submit(void *opaque, const rt_ai_aeg_segment_t *segment, uint32_t epoch, uint32_t cookie)
{
    provider_state_t *state = opaque;
    unsigned index;
    (void)segment;
    state->epoch = epoch;
    state->cookie = cookie;
    (void)rvv_add_relu(state->input, state->constant, state->output, TENSOR_COUNT);
    for (index = 0U; index < TENSOR_COUNT; ++index) {
        float expected = state->input[index] + state->constant[index];
        if (expected < 0.0f) expected = 0.0f;
        if (state->output[index] != expected) ++state->numeric_failures;
    }
    ++state->submissions;
    return RT_AI_OK;
}

static int leases_overlap(const rt_ai_job_t *left, const rt_ai_job_t *right)
{
    return left->lease.offset < right->lease.offset + right->lease.size &&
        right->lease.offset < left->lease.offset + left->lease.size;
}

int main(int argc, char **argv)
{
    uint64_t duration_seconds = argc > 1 ? strtoull(argv[1], NULL, 10) : UINT64_C(86400);
    uint64_t minimum_batches = argc > 2 ? strtoull(argv[2], NULL, 10) : UINT64_C(1000000);
    uint64_t heartbeat_batches = argc > 3 ? strtoull(argv[3], NULL, 10) : UINT64_C(10000);
    uint64_t deadline_us = argc > 4 ? strtoull(argv[4], NULL, 10) : UINT64_C(100000);
    const char *log_path = argc > 5 ? argv[5] : "/sdcard/airtos/compute_24h.log";
    uint8_t arena[SESSION_COUNT * 64U];
    rt_ai_runtime_t runtime;
    rt_ai_aeg_t aeg;
    rt_ai_provider_t provider;
    rt_ai_session_t sessions[SESSION_COUNT];
    provider_state_t state = {0};
    FILE *log = fopen(log_path, "w");
    uint64_t started = monotonic_seconds(), batches = 0U, jobs = 0U;
    uint64_t runtime_failures = 0U, lease_failures = 0U, stale_failures = 0U, deadline_failures = 0U;
    uint64_t maximum_batch_us = 0U;
    unsigned index;

    if (duration_seconds == 0U || minimum_batches == 0U || heartbeat_batches == 0U || deadline_us == 0U || log == NULL)
        return 2;
    memset(&runtime, 0, sizeof(runtime));
    memset(&aeg, 0, sizeof(aeg));
    memset(&provider, 0, sizeof(provider));
    aeg.header.magic = RT_AI_AEG_MAGIC;
    aeg.header.version = RT_AI_AEG_VERSION;
    aeg.header.segment_count = 1U;
    aeg.header.arena_size = 64U;
    aeg.storage[0].id = 1U;
    aeg.storage[0].resource = RT_AI_RESOURCE_RVV;
    aeg.storage[0].arena_size = 64U;
    aeg.segments = aeg.storage;
    aeg.wcet_us[0] = 1000U;
    aeg.relative_deadline_us = (uint32_t)(deadline_us > UINT32_MAX ? UINT32_MAX : deadline_us);
    aeg.deployable = 1U;
    aeg.legacy = 1U;
    provider.resource = RT_AI_RESOURCE_RVV;
    provider.submit = submit;
    provider.user = &state;
    for (index = 0U; index < TENSOR_COUNT; ++index) {
        state.input[index] = (float)index - 4.0f;
        state.constant[index] = (float)index;
    }
    if (rt_ai_runtime_init(&runtime, arena, sizeof(arena)) != RT_AI_OK ||
        rt_ai_provider_register(&runtime, &provider) != RT_AI_OK)
        return 2;
    for (index = 0U; index < SESSION_COUNT; ++index)
        if (rt_ai_session_create(&runtime, &aeg, &sessions[index]) != RT_AI_OK) return 2;

    emit(log, "AIRTOS_K230_COMPUTE_START duration_seconds=%" PRIu64 " minimum_batches=%" PRIu64
        " sessions=%u deadline_us=%" PRIu64 "\n", duration_seconds, minimum_batches, SESSION_COUNT, deadline_us);
    while (monotonic_seconds() - started < duration_seconds || batches < minimum_batches) {
        rt_ai_job_t current[SESSION_COUNT];
        uint64_t batch_started = now_us();
        uint64_t sent_completions = state.submissions;
        unsigned finished = 0U;
        memset(current, 0, sizeof(current));
        for (index = 0U; index < SESSION_COUNT; ++index) {
            uint64_t release = now_us();
            if (rt_ai_submit_async(&sessions[index], release, release + deadline_us, &current[index]) != RT_AI_OK)
                ++runtime_failures;
        }
        for (index = 0U; index < SESSION_COUNT; ++index) {
            unsigned right;
            for (right = index + 1U; right < SESSION_COUNT; ++right)
                if (leases_overlap(&current[index], &current[right])) ++lease_failures;
        }
        while (finished < SESSION_COUNT && now_us() - batch_started <= deadline_us) {
            (void)rt_ai_poll(&runtime, now_us());
            if (state.submissions > sent_completions) {
                if (rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_RVV, state.epoch - 1U, state.cookie, RT_AI_OK) != RT_AI_ERR_STALE)
                    ++stale_failures;
                if (rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_RVV, state.epoch, state.cookie, RT_AI_OK) != RT_AI_OK)
                    ++runtime_failures;
                sent_completions = state.submissions;
            }
            sleep_us(1100L);
            (void)rt_ai_poll(&runtime, now_us());
            finished = 0U;
            for (index = 0U; index < SESSION_COUNT; ++index)
                if (rt_ai_wait(&current[index]) == RT_AI_OK) ++finished;
        }
        if (finished != SESSION_COUNT) {
            ++deadline_failures;
            for (index = 0U; index < SESSION_COUNT; ++index)
                if (rt_ai_wait(&current[index]) == RT_AI_BUSY) (void)rt_ai_cancel(&current[index]);
        }
        for (index = 0U; index < SESSION_COUNT; ++index)
            if (current[index].lease.used || sessions[index].busy) ++lease_failures;
        {
            uint64_t elapsed = now_us() - batch_started;
            if (elapsed > maximum_batch_us) maximum_batch_us = elapsed;
        }
        ++batches;
        jobs += SESSION_COUNT;
        if (batches % heartbeat_batches == 0U)
            emit(log, "AIRTOS_K230_COMPUTE_HEARTBEAT elapsed_seconds=%" PRIu64 " batches=%" PRIu64
                " jobs=%" PRIu64 " runtime_failures=%" PRIu64 " numeric_failures=%" PRIu64
                " lease_failures=%" PRIu64 " stale_failures=%" PRIu64 " deadline_failures=%" PRIu64
                " maximum_batch_us=%" PRIu64 "\n", monotonic_seconds() - started, batches, jobs,
                runtime_failures, state.numeric_failures, lease_failures, stale_failures, deadline_failures, maximum_batch_us);
        sleep_us(1000L);
    }
    emit(log, "AIRTOS_K230_COMPUTE_RESULT elapsed_seconds=%" PRIu64 " batches=%" PRIu64
        " jobs=%" PRIu64 " runtime_failures=%" PRIu64 " numeric_failures=%" PRIu64
        " lease_failures=%" PRIu64 " stale_failures=%" PRIu64 " deadline_failures=%" PRIu64
        " maximum_batch_us=%" PRIu64 "\n", monotonic_seconds() - started, batches, jobs,
        runtime_failures, state.numeric_failures, lease_failures, stale_failures, deadline_failures, maximum_batch_us);
    if (runtime_failures == 0U && state.numeric_failures == 0U && lease_failures == 0U &&
        stale_failures == 0U && deadline_failures == 0U)
        emit(log, "AIRTOS_K230_COMPUTE_PASS\n");
    else
        emit(log, "AIRTOS_K230_COMPUTE_FAIL\n");
    fclose(log);
    return runtime_failures == 0U && state.numeric_failures == 0U && lease_failures == 0U &&
        stale_failures == 0U && deadline_failures == 0U ? 0 : 1;
}

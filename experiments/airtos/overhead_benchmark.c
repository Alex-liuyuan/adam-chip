#include <assert.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "rt_ai_internal.h"

#define SAMPLES 1000U
#define BATCHES 30U
#define WARMUPS 10U

typedef struct {
    uint8_t *blob;
    size_t blob_size;
    rt_ai_aeg_t aeg;
    rt_ai_runtime_t runtime;
    uint8_t *arena;
    size_t arena_size;
    rt_ai_schedule_snapshot_t snapshot;
    rt_ai_session_t session;
    rt_ai_job_t job;
} context_t;

static uint64_t now_ns(void)
{
    struct timespec value;
    assert(clock_gettime(CLOCK_MONOTONIC, &value) == 0);
    return (uint64_t)value.tv_sec * UINT64_C(1000000000) + (uint64_t)value.tv_nsec;
}

static int compare_u64(const void *left, const void *right)
{
    uint64_t a = *(const uint64_t *)left, b = *(const uint64_t *)right;
    return (a > b) - (a < b);
}

static void setup_completion(context_t *context)
{
    rt_ai_runtime_t *runtime = &context->runtime;
    rt_ai_job_t *job = &context->job;
    memset(runtime, 0, sizeof(*runtime));
    memset(job, 0, sizeof(*job));
    runtime->arena = context->arena;
    runtime->arena_size = context->arena_size;
    runtime->epoch[RT_AI_RESOURCE_CPU] = 1U;
    runtime->active_job[RT_AI_RESOURCE_CPU] = job;
    runtime->active_cookie[RT_AI_RESOURCE_CPU] = 1U;
    runtime->resource_state[RT_AI_RESOURCE_CPU] = RT_AI_RESOURCE_RUNNING;
    job->session = &context->session;
    job->state = RT_AI_JOB_RUNNING;
    job->status = RT_AI_BUSY;
    job->segment_state[0] = RT_AI_SEG_RUNNING;
    job->lease = (rt_ai_arena_lease_t){0U, 64U, 1U};
    runtime->leases[0] = job->lease;
    runtime->jobs[0] = job;
    context->session.runtime = runtime;
    context->session.busy = 1U;
}

static int operation(context_t *context, unsigned kind)
{
    rt_ai_arena_lease_t lease;
    rt_ai_queue_item_t item, popped;
    rt_ai_aeg_t decoded;
    uint64_t finish;
    switch (kind) {
    case 0U:
        return RT_AI_OK;
    case 1U:
        return rt_ai_load(context->blob, context->blob_size, &decoded);
    case 2U:
        return rt_ai_sim_edf(&context->aeg, &context->snapshot,
            context->aeg.relative_deadline_us, &finish);
    case 3U:
        item.job = &context->job;
        item.segment_index = 0U;
        item.deadline_us = 100U;
        if (rt_ai_queue_push(&context->runtime.queues[RT_AI_RESOURCE_CPU], &item) != RT_AI_OK) return RT_AI_ERR_RESOURCE;
        return rt_ai_queue_pop(&context->runtime.queues[RT_AI_RESOURCE_CPU], &popped);
    case 4U:
        if (rt_ai_arena_lease(&context->runtime, 64U, &lease) != RT_AI_OK) return RT_AI_ERR_RESOURCE;
        rt_ai_arena_release(&context->runtime, &lease);
        return RT_AI_OK;
    case 5U:
        rt_ai_trace(&context->runtime, 1U, &context->job, 1U, 1U,
            RT_AI_RESOURCE_CPU, RT_AI_TRACE_DISPATCH, RT_AI_OK);
        return RT_AI_OK;
    case 6U:
        return rt_ai_complete_isr(&context->runtime, RT_AI_RESOURCE_CPU, 1U, 1U, RT_AI_OK);
    default:
        return RT_AI_ERR_INVALID;
    }
}

int main(int argc, char **argv)
{
    static const char *names[] = {"clock", "load", "simedf", "queue_push_pop", "lease_release", "trace", "complete_isr"};
    context_t context;
    FILE *stream;
    long blob_size;
    uint64_t samples[SAMPLES];
    unsigned kind, batch, sample;
    if (argc != 2) return 2;
    memset(&context, 0, sizeof(context));
    stream = fopen(argv[1], "rb");
    if (stream == NULL || fseek(stream, 0L, SEEK_END) != 0 || (blob_size = ftell(stream)) <= 0L ||
        fseek(stream, 0L, SEEK_SET) != 0) return 2;
    context.blob = (uint8_t *)malloc((size_t)blob_size);
    if (context.blob == NULL || fread(context.blob, 1U, (size_t)blob_size, stream) != (size_t)blob_size) return 2;
    fclose(stream);
    context.blob_size = (size_t)blob_size;
    if (rt_ai_load(context.blob, context.blob_size, &context.aeg) != RT_AI_OK) return 2;
    context.arena_size = context.aeg.header.arena_size < 256U ? 256U : context.aeg.header.arena_size;
    context.arena = (uint8_t *)calloc(context.arena_size, 1U);
    if (context.arena == NULL || rt_ai_runtime_init(&context.runtime, context.arena, context.arena_size) != RT_AI_OK) return 2;
    context.snapshot.now_us = 0U;
    context.session.runtime = &context.runtime;
    context.session.aeg = context.aeg;
    context.session.aeg.segments = context.session.aeg.storage;
    context.session.aeg.header.segment_count = 1U;
    context.session.aeg.storage[0] = (rt_ai_aeg_segment_t){1U, RT_AI_RESOURCE_CPU, 0U, 0U, 0U, 64U};
    context.session.aeg.wcet_us[0] = 1U;
    context.job.session = &context.session;
    context.job.job_id = 1U;
    context.job.run_id = 1U;
    puts("operation,batch,samples,median_ns,p95_ns,p99_ns,max_ns");
    for (kind = 0U; kind < sizeof(names) / sizeof(names[0]); ++kind) {
        for (sample = 0U; sample < WARMUPS; ++sample) {
            int status;
            if (kind == 6U) setup_completion(&context);
            status = operation(&context, kind);
            if (status != RT_AI_OK) {
                fprintf(stderr, "operation=%s phase=warmup sample=%u status=%d\n", names[kind], sample, status);
                return 1;
            }
        }
        for (batch = 0U; batch < BATCHES; ++batch) {
            for (sample = 0U; sample < SAMPLES; ++sample) {
                uint64_t start, end;
                int status;
                if (kind == 6U) setup_completion(&context);
                start = now_ns();
                status = operation(&context, kind);
                end = now_ns();
                if (status != RT_AI_OK) {
                    fprintf(stderr, "operation=%s phase=measure batch=%u sample=%u status=%d\n",
                        names[kind], batch, sample, status);
                    return 1;
                }
                samples[sample] = end - start;
            }
            qsort(samples, SAMPLES, sizeof(samples[0]), compare_u64);
            printf("%s,%u,%u,%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 "\n",
                names[kind], batch, SAMPLES, samples[SAMPLES / 2U], samples[949U], samples[989U], samples[999U]);
        }
    }
    free(context.arena);
    free(context.blob);
    return 0;
}

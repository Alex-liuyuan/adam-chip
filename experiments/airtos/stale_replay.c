#include <assert.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rt_ai.h"

typedef struct {
    rt_ai_job_state_t job_state;
    uint8_t segment_state;
    rt_ai_job_t *active_job;
    uint32_t active_cookie;
    uint32_t epoch;
    uint32_t schedule_generation;
    uint64_t trace_sequence;
} state_snapshot_t;

static void setup(rt_ai_runtime_t *runtime, rt_ai_session_t *session, rt_ai_job_t *job, uint8_t arena[64],
    uint32_t epoch, uint32_t cookie)
{
    assert(rt_ai_runtime_init(runtime, arena, 64U) == RT_AI_OK);
    memset(session, 0, sizeof(*session));
    memset(job, 0, sizeof(*job));
    session->runtime = runtime;
    session->busy = 1U;
    session->aeg.header.segment_count = 1U;
    session->aeg.storage[0] = (rt_ai_aeg_segment_t){1U, RT_AI_RESOURCE_CPU, 0U, 0U, 0U, 64U};
    session->aeg.segments = session->aeg.storage;
    job->session = session;
    job->state = RT_AI_JOB_RUNNING;
    job->status = RT_AI_BUSY;
    job->segment_state[0] = 2U;
    job->job_id = 1U;
    job->lease = (rt_ai_arena_lease_t){0U, 64U, 1U};
    runtime->leases[0] = job->lease;
    runtime->jobs[0] = job;
    runtime->active_job[RT_AI_RESOURCE_CPU] = job;
    runtime->active_segment[RT_AI_RESOURCE_CPU] = 0U;
    runtime->active_cookie[RT_AI_RESOURCE_CPU] = cookie;
    runtime->epoch[RT_AI_RESOURCE_CPU] = epoch;
    runtime->resource_state[RT_AI_RESOURCE_CPU] = RT_AI_RESOURCE_RUNNING;
}

static state_snapshot_t snapshot(const rt_ai_runtime_t *runtime, const rt_ai_job_t *job)
{
    return (state_snapshot_t){job->state, job->segment_state[0], runtime->active_job[RT_AI_RESOURCE_CPU],
        runtime->active_cookie[RT_AI_RESOURCE_CPU], runtime->epoch[RT_AI_RESOURCE_CPU],
        runtime->schedule_generation, runtime->trace_sequence};
}

static int unchanged(state_snapshot_t before, state_snapshot_t after)
{
    return before.job_state == after.job_state && before.segment_state == after.segment_state &&
        before.active_job == after.active_job && before.active_cookie == after.active_cookie &&
        before.epoch == after.epoch && before.schedule_generation == after.schedule_generation &&
        before.trace_sequence == after.trace_sequence;
}

int main(int argc, char **argv)
{
    uint64_t repetitions = argc == 2 ? strtoull(argv[1], NULL, 10) : UINT64_C(100000);
    uint64_t failures[7] = {0};
    uint64_t iteration;
    unsigned class_id;
    if (repetitions == 0U) return 2;
    for (class_id = 0U; class_id < 7U; ++class_id) {
        for (iteration = 0U; iteration < repetitions; ++iteration) {
            uint8_t arena[64] = {0};
            rt_ai_runtime_t runtime;
            rt_ai_session_t session;
            rt_ai_job_t job;
            state_snapshot_t before;
            int status;
            setup(&runtime, &session, &job, arena, 7U, 11U);
            if (class_id == 3U) {
                runtime.active_job[RT_AI_RESOURCE_CPU] = NULL;
                runtime.active_cookie[RT_AI_RESOURCE_CPU] = 0U;
                runtime.resource_state[RT_AI_RESOURCE_CPU] = RT_AI_RESOURCE_HEALTHY;
            } else if (class_id == 4U) {
                runtime.epoch[RT_AI_RESOURCE_CPU] = 8U;
                runtime.active_cookie[RT_AI_RESOURCE_CPU] = 12U;
            } else if (class_id == 5U) {
                runtime.active_cookie[RT_AI_RESOURCE_CPU] = 12U;
            }
            if (class_id == 6U) {
                status = rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, 7U, 11U, RT_AI_OK);
                if (status != RT_AI_OK) { ++failures[class_id]; continue; }
                before = snapshot(&runtime, &job);
                status = rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, 7U, 11U, RT_AI_OK);
            } else {
                before = snapshot(&runtime, &job);
                if (class_id == 0U) status = rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_RVV, 7U, 11U, RT_AI_OK);
                else if (class_id == 1U) status = rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, 6U, 11U, RT_AI_OK);
                else if (class_id == 2U) status = rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, 7U, 10U, RT_AI_OK);
                else if (class_id == 3U) status = rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, 7U, 11U, RT_AI_OK);
                else if (class_id == 4U) status = rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, 7U, 11U, RT_AI_OK);
                else status = rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, 7U, 11U, RT_AI_OK);
            }
            {
                state_snapshot_t after = snapshot(&runtime, &job);
                if (status != RT_AI_ERR_STALE || !unchanged(before, after)) {
                    if (iteration == 0U)
                        fprintf(stderr, "class=%u status=%d before=(%d,%u,%p,%u,%u,%u,%" PRIu64
                            ") after=(%d,%u,%p,%u,%u,%u,%" PRIu64 ")\n", class_id, status,
                            before.job_state, before.segment_state, (void *)before.active_job, before.active_cookie,
                            before.epoch, before.schedule_generation, before.trace_sequence,
                            after.job_state, after.segment_state, (void *)after.active_job, after.active_cookie,
                            after.epoch, after.schedule_generation, after.trace_sequence);
                    ++failures[class_id];
                }
            }
        }
    }
    printf("STALE_REPLAY repetitions_per_class=%" PRIu64
           " wrong_device=%" PRIu64 " wrong_epoch=%" PRIu64 " wrong_cookie=%" PRIu64
           " cancel_late=%" PRIu64 " reset_late=%" PRIu64 " same_epoch_old_cookie=%" PRIu64
           " duplicate=%" PRIu64 "\n",
        repetitions, failures[0], failures[1], failures[2], failures[3], failures[4], failures[5], failures[6]);
    for (class_id = 0U; class_id < 7U; ++class_id) if (failures[class_id] != 0U) return 1;
    return 0;
}

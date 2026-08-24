#include <string.h>
#include "rt_ai_internal.h"

void rt_ai_admission_snapshot(const rt_ai_runtime_t *runtime, uint64_t now_us, rt_ai_schedule_snapshot_t *snapshot)
{
    uint16_t slot;
    memset(snapshot, 0, sizeof(*snapshot));
    snapshot->generation = runtime->schedule_generation;
    snapshot->now_us = now_us;
    for (slot = 0U; slot < RT_AI_MAX_JOBS && snapshot->job_count < RT_AI_MAX_JOBS; ++slot) {
        const rt_ai_job_t *job = runtime->jobs[slot];
        rt_ai_sim_job_t *target;
        uint16_t segment;
        if (job == NULL || job->recovering) continue;
        target = &snapshot->jobs[snapshot->job_count++];
        target->release_us = job->release_us;
        target->deadline_us = job->deadline_us;
        target->segment_count = rt_ai_job_segment_count(job);
        target->relative_deadline_us = job->session->aeg.relative_deadline_us;
        memcpy(target->reservation_budget_us, job->session->aeg.reservation_budget_us, sizeof(target->reservation_budget_us));
        memcpy(target->reservation_period_us, job->session->aeg.reservation_period_us, sizeof(target->reservation_period_us));
        for (segment = 0U; segment < target->segment_count; ++segment) {
            const rt_ai_aeg_segment_t *selected = rt_ai_job_segment(job, segment);
            rt_ai_sim_segment_t *item = &target->segments[segment];
            item->resource = selected->resource;
            item->state = job->segment_state[segment] == RT_AI_SEG_HELD ? RT_AI_SEG_RUNNING : job->segment_state[segment];
            item->dependency_mask = selected->dependency_mask;
            item->cost_us = (uint64_t)rt_ai_job_wcet(job, segment) + rt_ai_job_coherency_cost(job, segment) + rt_ai_job_recovery_cost(job, segment);
            if (job->segment_state[segment] == RT_AI_SEG_RUNNING || job->segment_state[segment] == RT_AI_SEG_HELD) {
                uint64_t elapsed = now_us > runtime->active_started_us[item->resource] ? now_us - runtime->active_started_us[item->resource] : 0U;
                item->cost_us = elapsed < item->cost_us ? item->cost_us - elapsed : 0U;
            }
        }
    }
}

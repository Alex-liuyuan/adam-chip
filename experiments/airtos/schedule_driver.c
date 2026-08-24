#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "rt_ai_internal.h"

static int read_job(rt_ai_sim_job_t *job)
{
    unsigned segment_count;
    unsigned resource;
    unsigned state;
    unsigned index;
    if (scanf("%" SCNu64 " %" SCNu64 " %u %u", &job->release_us, &job->deadline_us,
            &segment_count, &job->relative_deadline_us) != 4 || segment_count == 0U || segment_count > RT_AI_MAX_SEGMENTS)
        return 0;
    job->segment_count = (uint16_t)segment_count;
    for (index = 0U; index < RT_AI_MAX_RESOURCES; ++index)
        if (scanf("%u %u", &job->reservation_budget_us[index], &job->reservation_period_us[index]) != 2) return 0;
    for (index = 0U; index < segment_count; ++index) {
        if (scanf("%u %u %" SCNu32 " %" SCNu64, &resource, &state,
                &job->segments[index].dependency_mask, &job->segments[index].cost_us) != 4 ||
            resource >= RT_AI_MAX_RESOURCES || state > RT_AI_SEG_DONE)
            return 0;
        job->segments[index].resource = (uint8_t)resource;
        job->segments[index].state = (uint8_t)state;
    }
    return 1;
}

int main(void)
{
    uint64_t scenario;
    while (scanf("%" SCNu64, &scenario) == 1) {
        rt_ai_schedule_snapshot_t snapshot;
        rt_ai_aeg_t candidate;
        rt_ai_aeg_segment_t segments[RT_AI_MAX_SEGMENTS];
        uint64_t deadline;
        uint64_t finish = 0U;
        unsigned job_count;
        unsigned segment_count;
        unsigned relative_deadline;
        unsigned index;
        int status;
        memset(&snapshot, 0, sizeof(snapshot));
        memset(&candidate, 0, sizeof(candidate));
        if (scanf("%" SCNu64 " %u", &snapshot.now_us, &job_count) != 2 || job_count > RT_AI_MAX_JOBS) return 2;
        snapshot.job_count = (uint16_t)job_count;
        for (index = 0U; index < job_count; ++index) if (!read_job(&snapshot.jobs[index])) return 3;
        if (scanf("%" SCNu64 " %u %u", &deadline, &segment_count, &relative_deadline) != 3 ||
            segment_count == 0U || segment_count > RT_AI_MAX_SEGMENTS)
            return 4;
        candidate.header.segment_count = (uint16_t)segment_count;
        candidate.relative_deadline_us = relative_deadline;
        for (index = 0U; index < RT_AI_MAX_RESOURCES; ++index)
            if (scanf("%u %u", &candidate.reservation_budget_us[index], &candidate.reservation_period_us[index]) != 2) return 5;
        for (index = 0U; index < segment_count; ++index) {
            unsigned resource;
            uint32_t dependency_mask;
            if (scanf("%u %" SCNu32 " %" SCNu32 " %" SCNu32 " %" SCNu32, &resource, &dependency_mask,
                    &candidate.wcet_us[index], &candidate.coherency_cost_us[index], &candidate.recovery_cost_us[index]) != 5 ||
                resource >= RT_AI_MAX_RESOURCES)
                return 6;
            segments[index] = (rt_ai_aeg_segment_t){(uint16_t)(index + 1U), (uint8_t)resource, 0U,
                dependency_mask, 0U, 1U};
        }
        candidate.segments = segments;
        status = rt_ai_sim_edf(&candidate, &snapshot, deadline, &finish);
        printf("%" PRIu64 " %d %" PRIu64 "\n", scenario, status, finish);
    }
    return ferror(stdin) ? 7 : 0;
}

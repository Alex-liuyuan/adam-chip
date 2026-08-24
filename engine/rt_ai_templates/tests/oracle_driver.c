#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include "rt_ai_internal.h"

int main(void)
{
    unsigned scenario;
    while (scanf("%u", &scenario) == 1) {
        rt_ai_schedule_snapshot_t snapshot;
        rt_ai_aeg_t candidate;
        rt_ai_aeg_segment_t segments[2];
        unsigned jobs, index, resource0, resource1;
        uint64_t deadline, cost0, cost1, finish = 0U;
        int status;
        memset(&snapshot, 0, sizeof(snapshot));
        memset(&candidate, 0, sizeof(candidate));
        if (scanf("%" SCNu64 " %u", &snapshot.now_us, &jobs) != 2 || jobs > RT_AI_MAX_JOBS) return 2;
        snapshot.job_count = (uint16_t)jobs;
        for (index = 0U; index < jobs; ++index) {
            rt_ai_sim_job_t *job = &snapshot.jobs[index];
            if (scanf("%" SCNu64 " %" SCNu64 " %" SCNu64 " %u %" SCNu64 " %u", &job->release_us, &job->deadline_us, &cost0, &resource0, &cost1, &resource1) != 6) return 3;
            job->segment_count = 2U;
            job->segments[0] = (rt_ai_sim_segment_t){(uint8_t)resource0, RT_AI_SEG_PENDING, 0U, cost0};
            job->segments[1] = (rt_ai_sim_segment_t){(uint8_t)resource1, RT_AI_SEG_PENDING, 1U, cost1};
        }
        if (scanf("%" SCNu64 " %" SCNu64 " %u %" SCNu64 " %u", &deadline, &cost0, &resource0, &cost1, &resource1) != 5) return 4;
        segments[0] = (rt_ai_aeg_segment_t){1U, (uint8_t)resource0, 0U, 0U, 0U, 1U};
        segments[1] = (rt_ai_aeg_segment_t){2U, (uint8_t)resource1, 0U, 1U, 1U, 1U};
        candidate.header.segment_count = 2U;
        candidate.segments = segments;
        candidate.wcet_us[0] = (uint32_t)cost0;
        candidate.wcet_us[1] = (uint32_t)cost1;
        status = rt_ai_sim_edf(&candidate, &snapshot, deadline, &finish);
        printf("%u %d %" PRIu64 "\n", scenario, status, finish);
    }
    return 0;
}

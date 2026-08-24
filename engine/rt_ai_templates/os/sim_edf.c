#include <string.h>
#include "rt_ai_internal.h"

#define SIM_PENDING 0U
#define SIM_RUNNING 1U
#define SIM_DONE 2U

static int dbf_ok(const rt_ai_sim_job_t jobs[RT_AI_MAX_JOBS + 1U], uint16_t count, uint64_t now_us, uint64_t horizon)
{
    uint8_t resource;
    uint16_t job;
    if (horizon <= now_us) return 0;
    for (resource = 0U; resource < RT_AI_MAX_RESOURCES; ++resource) {
        uint64_t demand = 0U;
        uint64_t interval = horizon - now_us;
        for (job = 0U; job < count; ++job) {
            uint16_t segment;
            if (jobs[job].deadline_us <= horizon)
                for (segment = 0U; segment < jobs[job].segment_count; ++segment)
                    if (jobs[job].segments[segment].resource == resource && jobs[job].segments[segment].state != RT_AI_SEG_DONE)
                        demand += jobs[job].segments[segment].cost_us;
            if (jobs[job].reservation_period_us[resource] != 0U && jobs[job].reservation_budget_us[resource] != 0U) {
                uint64_t first_future_deadline = (uint64_t)jobs[job].reservation_period_us[resource] + jobs[job].relative_deadline_us;
                if (interval >= first_future_deadline)
                    demand += (UINT64_C(1) + (interval - first_future_deadline) / jobs[job].reservation_period_us[resource]) * jobs[job].reservation_budget_us[resource];
            }
        }
        if (demand > interval) return 0;
    }
    return 1;
}

int rt_ai_sim_edf(const rt_ai_aeg_t *aeg, const rt_ai_schedule_snapshot_t *snapshot, uint64_t deadline_us, uint64_t *finish_us)
{
    rt_ai_sim_job_t jobs[RT_AI_MAX_JOBS + 1U];
    uint8_t state[RT_AI_MAX_JOBS + 1U][RT_AI_MAX_SEGMENTS] = {{0}};
    uint64_t finish[RT_AI_MAX_JOBS + 1U][RT_AI_MAX_SEGMENTS] = {{0}};
    uint64_t resource_busy[RT_AI_MAX_RESOURCES] = {0};
    uint64_t now;
    uint16_t count;
    uint16_t job;
    uint16_t remaining = 0U;
    int admissible = 1;
    if (aeg == NULL || snapshot == NULL || finish_us == NULL || snapshot->job_count > RT_AI_MAX_JOBS) return RT_AI_ERR_INVALID;
    *finish_us = 0U;
    memcpy(jobs, snapshot->jobs, (size_t)snapshot->job_count * sizeof(jobs[0]));
    count = snapshot->job_count + 1U;
    memset(&jobs[count - 1U], 0, sizeof(jobs[0]));
    jobs[count - 1U].release_us = snapshot->now_us;
    jobs[count - 1U].deadline_us = deadline_us;
    jobs[count - 1U].segment_count = aeg->header.segment_count;
    jobs[count - 1U].relative_deadline_us = aeg->relative_deadline_us;
    memcpy(jobs[count - 1U].reservation_budget_us, aeg->reservation_budget_us, sizeof(aeg->reservation_budget_us));
    memcpy(jobs[count - 1U].reservation_period_us, aeg->reservation_period_us, sizeof(aeg->reservation_period_us));
    for (job = 0U; job < count; ++job) {
        uint16_t segment;
        for (segment = 0U; segment < jobs[job].segment_count; ++segment) {
            if (job == count - 1U) {
                jobs[job].segments[segment].resource = aeg->segments[segment].resource;
                jobs[job].segments[segment].dependency_mask = aeg->segments[segment].dependency_mask;
                jobs[job].segments[segment].cost_us = (uint64_t)aeg->wcet_us[segment] + aeg->coherency_cost_us[segment] + aeg->recovery_cost_us[segment];
                jobs[job].segments[segment].state = RT_AI_SEG_PENDING;
            }
            if (jobs[job].segments[segment].state == RT_AI_SEG_DONE) state[job][segment] = SIM_DONE;
            else { state[job][segment] = jobs[job].segments[segment].state == RT_AI_SEG_RUNNING ? SIM_RUNNING : SIM_PENDING; ++remaining; }
            if (state[job][segment] == SIM_RUNNING) {
                uint8_t resource = jobs[job].segments[segment].resource;
                finish[job][segment] = snapshot->now_us + jobs[job].segments[segment].cost_us;
                if (finish[job][segment] > resource_busy[resource]) resource_busy[resource] = finish[job][segment];
            }
        }
    }
    for (job = 0U; job < count; ++job)
        if (!dbf_ok(jobs, count, snapshot->now_us, jobs[job].deadline_us)) admissible = 0;
    now = snapshot->now_us;
    while (remaining != 0U) {
        int progress = 0;
        uint8_t resource;
        for (job = 0U; job < count; ++job) {
            uint16_t segment;
            for (segment = 0U; segment < jobs[job].segment_count; ++segment)
                if (state[job][segment] == SIM_RUNNING && finish[job][segment] <= now) {
                    state[job][segment] = SIM_DONE; --remaining; progress = 1;
                }
        }
        for (resource = 0U; resource < RT_AI_MAX_RESOURCES; ++resource) if (resource_busy[resource] <= now) {
            uint16_t best_job = count;
            uint16_t best_segment = 0U;
            for (job = 0U; job < count; ++job) {
                uint16_t segment;
                if (jobs[job].release_us > now) continue;
                for (segment = 0U; segment < jobs[job].segment_count; ++segment) {
                    uint16_t dependency;
                    int ready = 1;
                    if (state[job][segment] != SIM_PENDING || jobs[job].segments[segment].resource != resource) continue;
                    for (dependency = 0U; dependency < segment; ++dependency)
                        if ((jobs[job].segments[segment].dependency_mask & (UINT32_C(1) << dependency)) != 0U && state[job][dependency] != SIM_DONE) ready = 0;
                    if (ready && (best_job == count || jobs[job].deadline_us < jobs[best_job].deadline_us)) { best_job = job; best_segment = segment; }
                }
            }
            if (best_job != count) {
                state[best_job][best_segment] = SIM_RUNNING;
                finish[best_job][best_segment] = now + jobs[best_job].segments[best_segment].cost_us;
                resource_busy[resource] = finish[best_job][best_segment];
                progress = 1;
            }
        }
        if (remaining == 0U) break;
        {
            uint64_t next = UINT64_MAX;
            for (job = 0U; job < count; ++job) {
                uint16_t segment;
                if (jobs[job].release_us > now && jobs[job].release_us < next) next = jobs[job].release_us;
                for (segment = 0U; segment < jobs[job].segment_count; ++segment)
                    if (state[job][segment] == SIM_RUNNING && finish[job][segment] > now && finish[job][segment] < next) next = finish[job][segment];
            }
            if (next == UINT64_MAX || (!progress && next <= now)) return RT_AI_ERR_ADMISSION;
            now = next;
        }
    }
    for (job = 0U; job < count; ++job) {
        uint16_t segment;
        uint64_t completed = 0U;
        for (segment = 0U; segment < jobs[job].segment_count; ++segment) if (finish[job][segment] > completed) completed = finish[job][segment];
        if (job == count - 1U) *finish_us = completed;
        if (completed > jobs[job].deadline_us) admissible = 0;
    }
    return admissible ? RT_AI_OK : RT_AI_ERR_ADMISSION;
}

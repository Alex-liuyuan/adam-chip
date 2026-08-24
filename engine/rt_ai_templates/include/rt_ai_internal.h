#ifndef RT_AI_INTERNAL_H
#define RT_AI_INTERNAL_H

#include "rt_ai.h"

enum {
    RT_AI_SEG_PENDING = 0,
    RT_AI_SEG_QUEUED = 1,
    RT_AI_SEG_RUNNING = 2,
    RT_AI_SEG_DONE = 3,
    RT_AI_SEG_HELD = 4
};

int rt_ai_queue_push(rt_ai_resource_queue_t *queue, const rt_ai_queue_item_t *item);
int rt_ai_queue_pop(rt_ai_resource_queue_t *queue, rt_ai_queue_item_t *item);
void rt_ai_queue_remove_job(rt_ai_resource_queue_t *queue, const rt_ai_job_t *job);
int rt_ai_arena_lease(rt_ai_runtime_t *runtime, size_t size, rt_ai_arena_lease_t *lease);
int rt_ai_arena_probe(const rt_ai_runtime_t *runtime, size_t size, rt_ai_arena_lease_t *lease, uint32_t *generation);
int rt_ai_arena_commit(rt_ai_runtime_t *runtime, rt_ai_arena_lease_t *lease, uint32_t generation);
void rt_ai_arena_release(rt_ai_runtime_t *runtime, rt_ai_arena_lease_t *lease);
typedef struct {
    uint8_t resource;
    uint8_t state;
    uint32_t dependency_mask;
    uint64_t cost_us;
} rt_ai_sim_segment_t;
typedef struct {
    uint64_t release_us;
    uint64_t deadline_us;
    uint16_t segment_count;
    rt_ai_sim_segment_t segments[RT_AI_MAX_SEGMENTS];
    uint32_t reservation_budget_us[RT_AI_MAX_RESOURCES];
    uint32_t reservation_period_us[RT_AI_MAX_RESOURCES];
    uint32_t relative_deadline_us;
} rt_ai_sim_job_t;
typedef struct {
    uint32_t generation;
    uint64_t now_us;
    uint16_t job_count;
    rt_ai_sim_job_t jobs[RT_AI_MAX_JOBS];
} rt_ai_schedule_snapshot_t;
void rt_ai_admission_snapshot(const rt_ai_runtime_t *runtime, uint64_t now_us, rt_ai_schedule_snapshot_t *snapshot);
int rt_ai_sim_edf(const rt_ai_aeg_t *aeg, const rt_ai_schedule_snapshot_t *snapshot, uint64_t deadline_us, uint64_t *finish_us);
uint16_t rt_ai_job_segment_count(const rt_ai_job_t *job);
void rt_ai_select_aeg(const rt_ai_aeg_t *source, int fallback, rt_ai_aeg_t *selected);
const rt_ai_aeg_segment_t *rt_ai_job_segment(const rt_ai_job_t *job, uint16_t index);
uint32_t rt_ai_job_wcet(const rt_ai_job_t *job, uint16_t index);
uint32_t rt_ai_job_coherency_cost(const rt_ai_job_t *job, uint16_t index);
uint32_t rt_ai_job_recovery_cost(const rt_ai_job_t *job, uint16_t index);
int rt_ai_coherency_before(rt_ai_job_t *job, uint16_t segment_index);
int rt_ai_coherency_after(rt_ai_job_t *job, uint16_t segment_index);
void rt_ai_trace(rt_ai_runtime_t *runtime, uint64_t now_us, const rt_ai_job_t *job, uint64_t cookie, uint16_t segment_id, uint8_t resource, uint16_t event, int status);
void rt_ai_trace_decision(rt_ai_runtime_t *runtime, uint64_t now_us, const rt_ai_session_t *session,
    uint64_t run_id, uint8_t resource, uint16_t event, int status);
void rt_ai_finish_job(rt_ai_job_t *job, rt_ai_job_state_t state, int status);
int rt_ai_abort_job(rt_ai_job_t *job, rt_ai_job_state_t state, int status);
void rt_ai_recovery_poll(rt_ai_runtime_t *runtime, uint64_t now_us);
unsigned long rt_ai_port_lock(void);
void rt_ai_port_unlock(unsigned long level);
uint64_t rt_ai_port_now_us(void);

#endif

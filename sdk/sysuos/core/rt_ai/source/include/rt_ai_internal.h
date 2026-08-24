#ifndef RT_AI_INTERNAL_H
#define RT_AI_INTERNAL_H

#include "rt_ai.h"

enum {
    RT_AI_SEG_PENDING = 0,
    RT_AI_SEG_QUEUED = 1,
    RT_AI_SEG_RUNNING = 2,
    RT_AI_SEG_DONE = 3
};

int rt_ai_queue_push(rt_ai_resource_queue_t *queue, const rt_ai_queue_item_t *item);
int rt_ai_queue_pop(rt_ai_resource_queue_t *queue, rt_ai_queue_item_t *item);
void rt_ai_queue_remove_job(rt_ai_resource_queue_t *queue, const rt_ai_job_t *job);
int rt_ai_arena_lease(rt_ai_runtime_t *runtime, size_t size, rt_ai_arena_lease_t *lease);
void rt_ai_arena_release(rt_ai_runtime_t *runtime, rt_ai_arena_lease_t *lease);
void rt_ai_coherency_before(rt_ai_job_t *job, uint16_t segment_index);
void rt_ai_coherency_after(rt_ai_job_t *job, uint16_t segment_index);
void rt_ai_trace(rt_ai_runtime_t *runtime, uint64_t now_us, uint32_t cookie, uint16_t segment_id, int16_t event);
void rt_ai_finish_job(rt_ai_job_t *job, rt_ai_job_state_t state, int status);
int rt_ai_abort_job(rt_ai_job_t *job, rt_ai_job_state_t state, int status);
unsigned long rt_ai_port_lock(void);
void rt_ai_port_unlock(unsigned long level);

#endif

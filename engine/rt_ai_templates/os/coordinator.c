#include "rt_ai_internal.h"

static int dependencies_done(const rt_ai_job_t *job, uint16_t segment_index)
{
    uint32_t mask = rt_ai_job_segment(job, segment_index)->dependency_mask;
    uint16_t index;
    for (index = 0U; index < rt_ai_job_segment_count(job); ++index) {
        if ((mask & (UINT32_C(1) << index)) != 0U && job->segment_state[index] != RT_AI_SEG_DONE) return 0;
    }
    return 1;
}

static int all_done(const rt_ai_job_t *job)
{
    uint16_t index;
    for (index = 0U; index < rt_ai_job_segment_count(job); ++index)
        if (job->segment_state[index] != RT_AI_SEG_DONE) return 0;
    return 1;
}

static uint64_t budget_end(const rt_ai_runtime_t *runtime, uint8_t resource)
{
    rt_ai_job_t *job = runtime->active_job[resource];
    uint16_t segment_index = runtime->active_segment[resource];
    uint64_t budget = (uint64_t)rt_ai_job_wcet(job, segment_index) +
        rt_ai_job_coherency_cost(job, segment_index) + rt_ai_job_recovery_cost(job, segment_index);
    uint64_t started = runtime->active_started_us[resource];
    return budget > UINT64_MAX - started ? UINT64_MAX : started + budget;
}

static void release_completed(rt_ai_runtime_t *runtime, uint8_t resource, uint64_t now_us)
{
    rt_ai_job_t *job = runtime->active_job[resource];
    uint16_t segment_index = runtime->active_segment[resource];
    const rt_ai_aeg_segment_t *segment = rt_ai_job_segment(job, segment_index);
    uint32_t cookie = runtime->active_cookie[resource];
    runtime->active_job[resource] = NULL;
    runtime->active_cookie[resource] = 0U;
    runtime->resource_state[resource] = RT_AI_RESOURCE_HEALTHY;
    job->segment_state[segment_index] = RT_AI_SEG_DONE;
    ++runtime->schedule_generation;
    rt_ai_trace(runtime, now_us, job, cookie, segment->id, resource, RT_AI_TRACE_COMPLETE, RT_AI_OK);
    if (all_done(job)) rt_ai_finish_job(job, RT_AI_JOB_COMPLETE, RT_AI_OK);
}

static int enqueue_ready(rt_ai_job_t *job)
{
    uint16_t index;
    for (index = 0U; index < rt_ai_job_segment_count(job); ++index) {
        const rt_ai_aeg_segment_t *segment = rt_ai_job_segment(job, index);
        rt_ai_queue_item_t item;
        int status;
        if (job->segment_state[index] != RT_AI_SEG_PENDING || !dependencies_done(job, index)) continue;
        item.job = job;
        item.segment_index = index;
        item.deadline_us = job->deadline_us;
        status = rt_ai_queue_push(&job->session->runtime->queues[segment->resource], &item);
        if (status != RT_AI_OK) return status;
        job->segment_state[index] = RT_AI_SEG_QUEUED;
    }
    return RT_AI_OK;
}

static int dispatch(rt_ai_runtime_t *runtime, uint8_t resource, uint64_t now_us)
{
    rt_ai_queue_item_t item;
    const rt_ai_aeg_segment_t *segment;
    rt_ai_provider_t *provider;
    uint32_t cookie;
    int status;
    if (runtime->resource_state[resource] != RT_AI_RESOURCE_HEALTHY || runtime->active_job[resource] != NULL) return RT_AI_OK;
    if (rt_ai_queue_pop(&runtime->queues[resource], &item) != RT_AI_OK) return RT_AI_OK;
    segment = rt_ai_job_segment(item.job, item.segment_index);
    provider = &runtime->providers[resource];
    if (runtime->next_cookie[resource] == 0U) {
        if (runtime->epoch[resource] == UINT32_MAX) {
            runtime->resource_state[resource] = RT_AI_RESOURCE_QUARANTINED;
            (void)rt_ai_abort_job(item.job, RT_AI_JOB_FAILED, RT_AI_ERR_STALE);
            return RT_AI_ERR_STALE;
        }
        ++runtime->epoch[resource];
        runtime->next_cookie[resource] = 1U;
    }
    cookie = runtime->next_cookie[resource]++;
    item.job->cookie[item.segment_index] = cookie;
    item.job->segment_state[item.segment_index] = RT_AI_SEG_RUNNING;
    item.job->state = RT_AI_JOB_RUNNING;
    runtime->active_job[resource] = item.job;
    runtime->resource_state[resource] = RT_AI_RESOURCE_RUNNING;
    runtime->active_segment[resource] = item.segment_index;
    runtime->active_cookie[resource] = cookie;
    runtime->active_started_us[resource] = now_us;
    ++runtime->schedule_generation;
    status = rt_ai_coherency_before(item.job, item.segment_index);
    if (status != RT_AI_OK) {
        rt_ai_trace(runtime, now_us, item.job, cookie, segment->id, resource, RT_AI_TRACE_COHERENCY_ERROR, status);
        runtime->active_job[resource] = NULL;
        runtime->active_cookie[resource] = 0U;
        runtime->resource_state[resource] = RT_AI_RESOURCE_HEALTHY;
        (void)rt_ai_abort_job(item.job, RT_AI_JOB_FAILED, status);
        return status;
    }
    rt_ai_trace(runtime, now_us, item.job, cookie, segment->id, resource, RT_AI_TRACE_DISPATCH, RT_AI_OK);
    status = provider->submit(provider->user, segment, runtime->epoch[resource], cookie);
    if (status != RT_AI_OK) {
        runtime->active_job[resource] = NULL;
        runtime->active_cookie[resource] = 0U;
        runtime->resource_state[resource] = RT_AI_RESOURCE_HEALTHY;
        (void)rt_ai_abort_job(item.job, RT_AI_JOB_FAILED, RT_AI_ERR_PROVIDER);
        return RT_AI_ERR_PROVIDER;
    }
    return RT_AI_OK;
}

int rt_ai_poll(rt_ai_runtime_t *runtime, uint64_t now_us)
{
    uint16_t index;
    uint8_t resource;
    int result = RT_AI_OK;
    unsigned long level;
    if (runtime == NULL) return RT_AI_ERR_INVALID;
    level = rt_ai_port_lock();
    runtime->last_now_us = now_us;
    rt_ai_recovery_poll(runtime, now_us);
    for (resource = 0U; resource < RT_AI_MAX_RESOURCES; ++resource)
        if (runtime->active_job[resource] != NULL &&
            runtime->active_job[resource]->segment_state[runtime->active_segment[resource]] == RT_AI_SEG_HELD &&
            now_us >= budget_end(runtime, resource))
            release_completed(runtime, resource, now_us);
    for (index = 0U; index < RT_AI_MAX_JOBS; ++index) {
        rt_ai_job_t *job = runtime->jobs[index];
        int status;
        if (job == NULL || job->recovering) continue;
        if (now_us >= job->deadline_us) {
            (void)rt_ai_abort_job(job, RT_AI_JOB_FAILED, RT_AI_ERR_TIMEOUT);
            result = RT_AI_ERR_TIMEOUT;
            continue;
        }
        status = enqueue_ready(job);
        if (status != RT_AI_OK) {
            (void)rt_ai_abort_job(job, RT_AI_JOB_FAILED, status);
            result = status;
        }
    }
    for (resource = 0U; resource < RT_AI_MAX_RESOURCES; ++resource) {
        int status;
        if (!runtime->provider_valid[resource]) continue;
        status = dispatch(runtime, resource, now_us);
        if (status != RT_AI_OK) result = status;
    }
    rt_ai_port_unlock(level);
    return result;
}

int rt_ai_complete_isr(rt_ai_runtime_t *runtime, uint8_t device_id, uint32_t epoch, uint32_t cookie, int status)
{
    rt_ai_job_t *job;
    uint16_t segment_index;
    const rt_ai_aeg_segment_t *segment;
    uint64_t now_us;
    unsigned long level;
    if (runtime == NULL || device_id >= RT_AI_MAX_RESOURCES) return RT_AI_ERR_INVALID;
    level = rt_ai_port_lock();
    job = runtime->active_job[device_id];
    if (epoch != runtime->epoch[device_id] || job == NULL || cookie != runtime->active_cookie[device_id]) {
        rt_ai_port_unlock(level);
        return RT_AI_ERR_STALE;
    }
    segment_index = runtime->active_segment[device_id];
    segment = rt_ai_job_segment(job, segment_index);
    if (job->segment_state[segment_index] != RT_AI_SEG_RUNNING) {
        rt_ai_port_unlock(level);
        return RT_AI_ERR_STALE;
    }
    if (status != RT_AI_OK) {
        runtime->active_job[device_id] = NULL;
        runtime->active_cookie[device_id] = 0U;
        runtime->resource_state[device_id] = RT_AI_RESOURCE_HEALTHY;
        ++runtime->schedule_generation;
        (void)rt_ai_abort_job(job, RT_AI_JOB_FAILED, status);
        rt_ai_port_unlock(level);
        return status;
    }
    status = rt_ai_coherency_after(job, segment_index);
    if (status != RT_AI_OK) {
        now_us = rt_ai_port_now_us();
        rt_ai_trace(runtime, now_us, job, cookie, segment->id, device_id, RT_AI_TRACE_COHERENCY_ERROR, status);
        runtime->active_job[device_id] = NULL;
        runtime->active_cookie[device_id] = 0U;
        runtime->resource_state[device_id] = RT_AI_RESOURCE_HEALTHY;
        ++runtime->schedule_generation;
        (void)rt_ai_abort_job(job, RT_AI_JOB_FAILED, status);
        rt_ai_port_unlock(level);
        return status;
    }
    now_us = rt_ai_port_now_us();
    if (now_us < budget_end(runtime, device_id)) {
        job->segment_state[segment_index] = RT_AI_SEG_HELD;
        ++runtime->schedule_generation;
    } else release_completed(runtime, device_id, now_us);
    rt_ai_port_unlock(level);
    return RT_AI_OK;
}

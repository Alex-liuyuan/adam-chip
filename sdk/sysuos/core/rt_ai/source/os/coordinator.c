#include "rt_ai_internal.h"

static int dependencies_done(const rt_ai_job_t *job, uint16_t segment_index)
{
    uint32_t mask = job->session->aeg.segments[segment_index].dependency_mask;
    uint16_t index;
    for (index = 0U; index < job->session->aeg.header.segment_count; ++index) {
        if ((mask & (UINT32_C(1) << index)) != 0U && job->segment_state[index] != RT_AI_SEG_DONE) return 0;
    }
    return 1;
}

static int all_done(const rt_ai_job_t *job)
{
    uint16_t index;
    for (index = 0U; index < job->session->aeg.header.segment_count; ++index)
        if (job->segment_state[index] != RT_AI_SEG_DONE) return 0;
    return 1;
}

static int enqueue_ready(rt_ai_job_t *job)
{
    uint16_t index;
    for (index = 0U; index < job->session->aeg.header.segment_count; ++index) {
        const rt_ai_aeg_segment_t *segment = &job->session->aeg.segments[index];
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
    if (runtime->active_job[resource] != NULL) return RT_AI_OK;
    if (rt_ai_queue_pop(&runtime->queues[resource], &item) != RT_AI_OK) return RT_AI_OK;
    segment = &item.job->session->aeg.segments[item.segment_index];
    provider = &runtime->providers[resource];
    cookie = runtime->next_cookie++;
    if (cookie == 0U) cookie = runtime->next_cookie++;
    item.job->cookie[item.segment_index] = cookie;
    item.job->segment_state[item.segment_index] = RT_AI_SEG_RUNNING;
    item.job->state = RT_AI_JOB_RUNNING;
    runtime->active_job[resource] = item.job;
    runtime->active_segment[resource] = item.segment_index;
    runtime->active_cookie[resource] = cookie;
    rt_ai_coherency_before(item.job, item.segment_index);
    rt_ai_trace(runtime, now_us, cookie, segment->id, 1);
    status = provider->submit(provider->user, segment, runtime->epoch[resource], cookie);
    if (status != RT_AI_OK) {
        runtime->active_job[resource] = NULL;
        runtime->active_cookie[resource] = 0U;
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
    for (index = 0U; index < RT_AI_MAX_JOBS; ++index) {
        rt_ai_job_t *job = runtime->jobs[index];
        int status;
        if (job == NULL) continue;
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
    unsigned long level;
    if (runtime == NULL || device_id >= RT_AI_MAX_RESOURCES) return RT_AI_ERR_INVALID;
    level = rt_ai_port_lock();
    job = runtime->active_job[device_id];
    if (epoch != runtime->epoch[device_id] || job == NULL || cookie != runtime->active_cookie[device_id]) {
        rt_ai_port_unlock(level);
        return RT_AI_ERR_STALE;
    }
    segment_index = runtime->active_segment[device_id];
    segment = &job->session->aeg.segments[segment_index];
    runtime->active_job[device_id] = NULL;
    runtime->active_cookie[device_id] = 0U;
    if (status != RT_AI_OK) {
        (void)rt_ai_abort_job(job, RT_AI_JOB_FAILED, status);
        rt_ai_port_unlock(level);
        return status;
    }
    rt_ai_coherency_after(job, segment_index);
    job->segment_state[segment_index] = RT_AI_SEG_DONE;
    rt_ai_trace(runtime, 0U, cookie, segment->id, 2);
    if (all_done(job)) rt_ai_finish_job(job, RT_AI_JOB_COMPLETE, RT_AI_OK);
    rt_ai_port_unlock(level);
    return RT_AI_OK;
}

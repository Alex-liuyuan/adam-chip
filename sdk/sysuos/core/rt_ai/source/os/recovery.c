#include "rt_ai_internal.h"

void rt_ai_finish_job(rt_ai_job_t *job, rt_ai_job_state_t state, int status)
{
    uint16_t index;
    rt_ai_runtime_t *runtime;
    if (job == NULL || job->session == NULL) return;
    runtime = job->session->runtime;
    job->state = state;
    job->status = status;
    job->session->busy = 0U;
    for (index = 0U; index < RT_AI_MAX_JOBS; ++index) {
        if (runtime->jobs[index] == job) runtime->jobs[index] = NULL;
    }
}

int rt_ai_abort_job(rt_ai_job_t *job, rt_ai_job_state_t state, int status)
{
    uint16_t resource;
    rt_ai_runtime_t *runtime;
    if (job == NULL || job->session == NULL || job->state < RT_AI_JOB_PENDING || job->state > RT_AI_JOB_RUNNING)
        return RT_AI_ERR_INVALID;
    runtime = job->session->runtime;
    for (resource = 0U; resource < RT_AI_MAX_RESOURCES; ++resource) {
        rt_ai_queue_remove_job(&runtime->queues[resource], job);
        if (runtime->active_job[resource] == job) {
            rt_ai_provider_t *provider = &runtime->providers[resource];
            if (provider->cancel != NULL)
                (void)provider->cancel(provider->user, runtime->epoch[resource], runtime->active_cookie[resource]);
            runtime->active_job[resource] = NULL;
            runtime->active_cookie[resource] = 0U;
        }
    }
    rt_ai_finish_job(job, state, status);
    return RT_AI_OK;
}

int rt_ai_cancel(rt_ai_job_t *job)
{
    int status;
    unsigned long level = rt_ai_port_lock();
    status = rt_ai_abort_job(job, RT_AI_JOB_CANCELLED, RT_AI_ERR_CANCELLED);
    rt_ai_port_unlock(level);
    return status;
}

int rt_ai_reset_device(rt_ai_runtime_t *runtime, uint8_t device_id)
{
    rt_ai_job_t *job;
    rt_ai_provider_t *provider;
    unsigned long level;
    if (runtime == NULL || device_id >= RT_AI_MAX_RESOURCES || !runtime->provider_valid[device_id]) return RT_AI_ERR_INVALID;
    level = rt_ai_port_lock();
    ++runtime->epoch[device_id];
    provider = &runtime->providers[device_id];
    if (provider->reset != NULL) (void)provider->reset(provider->user, runtime->epoch[device_id]);
    job = runtime->active_job[device_id];
    if (job != NULL) (void)rt_ai_abort_job(job, RT_AI_JOB_FAILED, RT_AI_ERR_TIMEOUT);
    runtime->active_job[device_id] = NULL;
    runtime->active_cookie[device_id] = 0U;
    rt_ai_port_unlock(level);
    return RT_AI_OK;
}

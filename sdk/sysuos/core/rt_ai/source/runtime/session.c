#include <string.h>
#include "rt_ai_internal.h"

int rt_ai_runtime_init(rt_ai_runtime_t *runtime, void *arena, size_t arena_size)
{
    uint8_t resource;
    if (runtime == NULL || arena == NULL || arena_size == 0U) return RT_AI_ERR_INVALID;
    memset(runtime, 0, sizeof(*runtime));
    runtime->arena = (uint8_t *)arena;
    runtime->arena_size = arena_size;
    runtime->next_cookie = 1U;
    for (resource = 0U; resource < RT_AI_MAX_RESOURCES; ++resource) runtime->epoch[resource] = 1U;
    return RT_AI_OK;
}

int rt_ai_provider_register(rt_ai_runtime_t *runtime, const rt_ai_provider_t *provider)
{
    if (runtime == NULL || provider == NULL || provider->resource >= RT_AI_MAX_RESOURCES || provider->submit == NULL)
        return RT_AI_ERR_INVALID;
    runtime->providers[provider->resource] = *provider;
    runtime->provider_valid[provider->resource] = 1U;
    return RT_AI_OK;
}

int rt_ai_session_create(rt_ai_runtime_t *runtime, const rt_ai_aeg_t *aeg, rt_ai_session_t *session)
{
    int status;
    if (runtime == NULL || aeg == NULL || aeg->segments == NULL || session == NULL) return RT_AI_ERR_INVALID;
    memset(session, 0, sizeof(*session));
    status = rt_ai_arena_lease(runtime, aeg->header.arena_size, &session->lease);
    if (status != RT_AI_OK) return status;
    session->runtime = runtime;
    session->aeg = *aeg;
    session->aeg.segments = session->aeg.storage;
    return RT_AI_OK;
}

int rt_ai_session_destroy(rt_ai_session_t *session)
{
    if (session == NULL || session->runtime == NULL || session->busy) return RT_AI_ERR_INVALID;
    rt_ai_arena_release(session->runtime, &session->lease);
    session->runtime = NULL;
    return RT_AI_OK;
}

int rt_ai_submit_async(rt_ai_session_t *session, uint64_t now_us, uint64_t deadline_us, rt_ai_job_t *job)
{
    uint16_t index;
    rt_ai_runtime_t *runtime;
    unsigned long level;
    if (session == NULL || session->runtime == NULL || job == NULL || session->busy || deadline_us <= now_us)
        return RT_AI_ERR_INVALID;
    runtime = session->runtime;
    for (index = 0U; index < session->aeg.header.segment_count; ++index) {
        if (!runtime->provider_valid[session->aeg.segments[index].resource]) return RT_AI_ERR_RESOURCE;
    }
    level = rt_ai_port_lock();
    for (index = 0U; index < RT_AI_MAX_JOBS; ++index) {
        if (runtime->jobs[index] == NULL) {
            memset(job, 0, sizeof(*job));
            job->session = session;
            job->deadline_us = deadline_us;
            job->state = RT_AI_JOB_PENDING;
            job->status = RT_AI_BUSY;
            runtime->jobs[index] = job;
            session->busy = 1U;
            rt_ai_port_unlock(level);
            return RT_AI_OK;
        }
    }
    rt_ai_port_unlock(level);
    return RT_AI_ERR_RESOURCE;
}

int rt_ai_wait(const rt_ai_job_t *job)
{
    if (job == NULL) return RT_AI_ERR_INVALID;
    if (job->state == RT_AI_JOB_COMPLETE) return RT_AI_OK;
    if (job->state == RT_AI_JOB_FAILED || job->state == RT_AI_JOB_CANCELLED) return job->status;
    return RT_AI_BUSY;
}

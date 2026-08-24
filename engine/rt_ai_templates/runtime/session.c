#include <string.h>
#include "rt_ai_internal.h"

static int provider_healthy(rt_ai_runtime_t *runtime, uint8_t resource)
{
    rt_ai_provider_t *provider;
    if (resource >= RT_AI_MAX_RESOURCES || !runtime->provider_valid[resource] || runtime->resource_state[resource] >= RT_AI_RESOURCE_CANCEL_PENDING) return 0;
    provider = &runtime->providers[resource];
    return provider->health == NULL || provider->health(provider->user) == RT_AI_OK;
}

static int reject_submit(rt_ai_session_t *session, const rt_ai_submit_policy_t *policy,
    rt_ai_admission_result_t *result, rt_ai_admission_stage_t stage, int status)
{
    uint16_t event = RT_AI_TRACE_RETRY_REJECT;
    uint8_t resource = RT_AI_RESOURCE_CPU;
    result->stage = stage;
    result->status = status;
    if (stage == RT_AI_ADMISSION_DOMAIN) event = RT_AI_TRACE_DOMAIN_REJECT;
    else if (stage == RT_AI_ADMISSION_EVIDENCE) event = RT_AI_TRACE_EVIDENCE_REJECT;
    else if (stage == RT_AI_ADMISSION_PROVIDER) event = RT_AI_TRACE_PROVIDER_REJECT;
    else if (stage == RT_AI_ADMISSION_MEMORY) event = RT_AI_TRACE_MEMORY_REJECT;
    else if (stage == RT_AI_ADMISSION_DEADLINE) event = RT_AI_TRACE_DEADLINE_REJECT;
    if (session != NULL && session->runtime != NULL && policy != NULL) {
        if (session->aeg.header.segment_count != 0U && session->aeg.segments[0].resource < RT_AI_MAX_RESOURCES)
            resource = session->aeg.segments[0].resource;
        rt_ai_trace_decision(session->runtime, policy->now_us, session, policy->run_id, resource, event, status);
    }
    return status;
}

int rt_ai_runtime_init(rt_ai_runtime_t *runtime, void *arena, size_t arena_size)
{
    uint8_t resource;
    if (runtime == NULL || arena == NULL || arena_size == 0U) return RT_AI_ERR_INVALID;
    memset(runtime, 0, sizeof(*runtime));
    runtime->arena = (uint8_t *)arena;
    runtime->arena_size = arena_size;
    runtime->next_job_id = 1U;
    for (resource = 0U; resource < RT_AI_MAX_RESOURCES; ++resource) {
        runtime->epoch[resource] = 1U;
        runtime->next_cookie[resource] = 1U;
        runtime->resource_state[resource] = RT_AI_RESOURCE_HEALTHY;
    }
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
    if (runtime == NULL || aeg == NULL || aeg->segments == NULL || session == NULL || !aeg->deployable || aeg->header.version != RT_AI_AEG_VERSION) return RT_AI_ERR_INVALID;
    memset(session, 0, sizeof(*session));
    session->runtime = runtime;
    session->aeg = *aeg;
    session->aeg.segments = session->aeg.storage;
    return RT_AI_OK;
}

int rt_ai_session_create_v2(rt_ai_runtime_t *runtime, const rt_ai_aeg_t *aeg, const rt_ai_trust_bundle_t *trust, rt_ai_evaluation_result_t *evaluation, rt_ai_session_t *session)
{
    if (runtime == NULL || aeg == NULL || session == NULL || rt_ai_evaluate_deployment(aeg, trust, evaluation) != RT_AI_OK) return RT_AI_ERR_EVIDENCE;
    memset(session, 0, sizeof(*session));
    session->runtime = runtime;
    session->aeg = *aeg;
    session->aeg.segments = session->aeg.storage;
    session->trust = *trust;
    session->trust_valid = 1U;
    return RT_AI_OK;
}

int rt_ai_session_destroy(rt_ai_session_t *session)
{
    if (session == NULL || session->runtime == NULL || session->busy) return RT_AI_ERR_INVALID;
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
    if (!session->aeg.legacy) return RT_AI_ERR_INVALID;
    runtime = session->runtime;
    for (index = 0U; index < session->aeg.header.segment_count; ++index) {
        if (!runtime->provider_valid[session->aeg.segments[index].resource]) return RT_AI_ERR_RESOURCE;
    }
    level = rt_ai_port_lock();
    for (index = 0U; index < RT_AI_MAX_JOBS; ++index) {
        if (runtime->jobs[index] == NULL) {
            uint32_t lease_generation;
            memset(job, 0, sizeof(*job));
            job->session = session;
            job->release_us = now_us;
            job->deadline_us = deadline_us;
            job->state = RT_AI_JOB_PENDING;
            job->status = RT_AI_BUSY;
            if (rt_ai_arena_probe(runtime, session->aeg.header.arena_size, &job->lease, &lease_generation) != RT_AI_OK ||
                rt_ai_arena_commit(runtime, &job->lease, lease_generation) != RT_AI_OK) {
                rt_ai_port_unlock(level);
                return RT_AI_ERR_RESOURCE;
            }
            runtime->jobs[index] = job;
            session->busy = 1U;
            ++runtime->schedule_generation;
            rt_ai_port_unlock(level);
            return RT_AI_OK;
        }
    }
    rt_ai_port_unlock(level);
    return RT_AI_ERR_RESOURCE;
}

int rt_ai_submit_async_v2(rt_ai_session_t *session, const rt_ai_invocation_t *invocation, const rt_ai_submit_policy_t *policy, rt_ai_admission_result_t *result, rt_ai_job_t *job)
{
    rt_ai_runtime_t *runtime;
    uint8_t attempt;
    int use_fallback = 0;
    uint16_t index;
    if (result == NULL) return RT_AI_ERR_INVALID;
    memset(result, 0, sizeof(*result));
    if (session == NULL || session->runtime == NULL || invocation == NULL || policy == NULL || job == NULL ||
        invocation->input == NULL || invocation->output == NULL || invocation->input_size == 0U || invocation->output_size == 0U) {
        result->stage = RT_AI_ADMISSION_BINDING; result->status = RT_AI_ERR_INVALID; return result->status;
    }
    if (invocation->input_size != session->aeg.input_bytes || invocation->output_size != session->aeg.output_bytes ||
        invocation->input_rank != session->aeg.input_rank || invocation->input_dtype != session->aeg.input_dtype ||
        invocation->input_layout != session->aeg.input_layout || memcmp(invocation->input_shape, session->aeg.input_shape, sizeof(invocation->input_shape)) != 0 ||
        invocation->input_size > session->aeg.header.arena_size || invocation->output_size > session->aeg.header.arena_size - invocation->input_size ||
        memcmp(invocation->plan_sha256, session->aeg.plan_sha256, 32U) != 0) {
        return reject_submit(session, policy, result, RT_AI_ADMISSION_DOMAIN, RT_AI_ERR_DOMAIN);
    }
    if (!session->aeg.deployable || session->aeg.legacy) {
        return reject_submit(session, policy, result, RT_AI_ADMISSION_EVIDENCE, RT_AI_ERR_EVIDENCE);
    }
    if (policy->deadline_us <= policy->now_us || policy->deadline_us - policy->now_us > session->aeg.relative_deadline_us ||
        (session->has_submitted && policy->now_us - session->last_submit_us < session->aeg.minimum_interarrival_us)) {
        return reject_submit(session, policy, result, RT_AI_ADMISSION_DEADLINE, RT_AI_ERR_ADMISSION);
    }
    runtime = session->runtime;
    for (index = 0U; index < session->aeg.header.segment_count; ++index) {
        uint8_t resource = session->aeg.segments[index].resource;
        if (!provider_healthy(runtime, resource)) use_fallback = 1;
    }
    if (use_fallback) {
        if (session->aeg.fallback_segment_count == 0U)
            return reject_submit(session, policy, result, RT_AI_ADMISSION_PROVIDER, RT_AI_ERR_RESOURCE);
        for (index = 0U; index < session->aeg.fallback_segment_count; ++index)
            if (!provider_healthy(runtime, session->aeg.fallback_storage[index].resource))
                return reject_submit(session, policy, result, RT_AI_ADMISSION_PROVIDER, RT_AI_ERR_RESOURCE);
    }
    for (attempt = 0U; attempt < (policy->max_retries == 0U ? 1U : policy->max_retries); ++attempt) {
        rt_ai_schedule_snapshot_t snapshot;
        rt_ai_aeg_t candidate;
        rt_ai_arena_lease_t lease;
        uint32_t lease_generation;
        uint16_t slot = RT_AI_MAX_JOBS;
        unsigned long level = rt_ai_port_lock();
        if (session->busy) { rt_ai_port_unlock(level); return reject_submit(session, policy, result, RT_AI_ADMISSION_RETRY, RT_AI_BUSY); }
        for (index = 0U; index < RT_AI_MAX_JOBS; ++index) if (runtime->jobs[index] == NULL) { slot = index; break; }
        if (slot == RT_AI_MAX_JOBS || rt_ai_arena_probe(runtime, session->aeg.header.arena_size, &lease, &lease_generation) != RT_AI_OK) {
            rt_ai_port_unlock(level); return reject_submit(session, policy, result, RT_AI_ADMISSION_MEMORY, RT_AI_ERR_RESOURCE);
        }
        rt_ai_admission_snapshot(runtime, policy->now_us, &snapshot);
        rt_ai_port_unlock(level);
        rt_ai_select_aeg(&session->aeg, use_fallback, &candidate);
        result->status = rt_ai_sim_edf(&candidate, &snapshot, policy->deadline_us, &result->predicted_finish_us);
        if (result->status != RT_AI_OK)
            return reject_submit(session, policy, result, RT_AI_ADMISSION_DEADLINE, result->status);
        level = rt_ai_port_lock();
        if (runtime->schedule_generation != snapshot.generation || runtime->jobs[slot] != NULL || session->busy ||
            rt_ai_arena_commit(runtime, &lease, lease_generation) != RT_AI_OK) { rt_ai_port_unlock(level); continue; }
        for (index = 0U; index < candidate.header.segment_count; ++index) {
            uint8_t resource = candidate.segments[index].resource;
            if (!provider_healthy(runtime, resource)) {
                rt_ai_arena_release(runtime, &lease);
                rt_ai_port_unlock(level);
                return reject_submit(session, policy, result, RT_AI_ADMISSION_PROVIDER, RT_AI_ERR_RESOURCE);
            }
        }
        memset(job, 0, sizeof(*job));
        job->session = session; job->release_us = policy->now_us; job->deadline_us = policy->deadline_us; job->state = RT_AI_JOB_PENDING; job->status = RT_AI_BUSY; job->lease = lease;
        job->job_id = runtime->next_job_id++; job->run_id = policy->run_id;
        job->use_fallback = (uint8_t)use_fallback;
        runtime->jobs[slot] = job; session->busy = 1U; session->last_submit_us = policy->now_us; session->has_submitted = 1U; ++runtime->schedule_generation;
        result->stage = RT_AI_ADMISSION_ACCEPTED; result->status = RT_AI_OK; result->generation = runtime->schedule_generation;
        rt_ai_port_unlock(level);
        return RT_AI_OK;
    }
    return reject_submit(session, policy, result, RT_AI_ADMISSION_RETRY, RT_AI_BUSY);
}

int rt_ai_wait(const rt_ai_job_t *job)
{
    if (job == NULL) return RT_AI_ERR_INVALID;
    if (job->state == RT_AI_JOB_COMPLETE) return RT_AI_OK;
    if (job->state == RT_AI_JOB_FAILED || job->state == RT_AI_JOB_CANCELLED) return job->status;
    return RT_AI_BUSY;
}

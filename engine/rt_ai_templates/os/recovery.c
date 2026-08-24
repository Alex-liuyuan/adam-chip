#include "rt_ai_internal.h"

static int fallback_admissible(rt_ai_runtime_t *runtime, rt_ai_job_t *job)
{
    rt_ai_evaluation_result_t evaluation;
    rt_ai_schedule_snapshot_t snapshot;
    rt_ai_aeg_t fallback;
    uint64_t finish_us;
    uint16_t index;
    int lease_active = 0;
    if (!job->session->trust_valid || rt_ai_evaluate_deployment(&job->session->aeg, &job->session->trust, &evaluation) != RT_AI_OK)
        return RT_AI_ERR_EVIDENCE;
    for (index = 0U; index < RT_AI_MAX_LEASES; ++index)
        if (runtime->leases[index].used && runtime->leases[index].offset == job->lease.offset && runtime->leases[index].size == job->lease.size)
            lease_active = 1;
    if (!job->lease.used || !lease_active) return RT_AI_ERR_RESOURCE;
    for (index = 0U; index < job->session->aeg.fallback_segment_count; ++index) {
        const rt_ai_aeg_segment_t *segment = &job->session->aeg.fallback_storage[index];
        rt_ai_provider_t *provider;
        if (segment->arena_offset > job->lease.size || segment->arena_size > job->lease.size - segment->arena_offset ||
            !runtime->provider_valid[segment->resource] || runtime->resource_state[segment->resource] >= RT_AI_RESOURCE_CANCEL_PENDING)
            return RT_AI_ERR_RESOURCE;
        provider = &runtime->providers[segment->resource];
        if (provider->health != NULL && provider->health(provider->user) != RT_AI_OK) return RT_AI_ERR_PROVIDER;
    }
    rt_ai_select_aeg(&job->session->aeg, 1, &fallback);
    rt_ai_admission_snapshot(runtime, runtime->last_now_us, &snapshot);
    return rt_ai_sim_edf(&fallback, &snapshot, job->deadline_us, &finish_us);
}

static void trace_recovery_issue(rt_ai_runtime_t *runtime, uint8_t resource, uint16_t event, int status)
{
    rt_ai_job_t *job = runtime->recovery_job[resource] != NULL ? runtime->recovery_job[resource] : runtime->active_job[resource];
    if (job != NULL)
        rt_ai_trace(runtime, runtime->last_now_us, job, runtime->active_cookie[resource],
            rt_ai_job_segment(job, runtime->active_segment[resource])->id, resource, event, status);
}

void rt_ai_finish_job(rt_ai_job_t *job, rt_ai_job_state_t state, int status)
{
    uint16_t index;
    rt_ai_runtime_t *runtime;
    if (job == NULL || job->session == NULL) return;
    runtime = job->session->runtime;
    job->state = state;
    job->status = status;
    job->recovering = 0U;
    job->session->busy = 0U;
    rt_ai_arena_release(runtime, &job->lease);
    for (index = 0U; index < RT_AI_MAX_JOBS; ++index)
        if (runtime->jobs[index] == job) runtime->jobs[index] = NULL;
    ++runtime->schedule_generation;
}

static void recovery_done(rt_ai_runtime_t *runtime, uint8_t resource, int quarantined)
{
    rt_ai_job_t *job = runtime->recovery_job[resource];
    if (job != NULL && quarantined)
        rt_ai_trace(runtime, runtime->last_now_us, job, runtime->active_cookie[resource], rt_ai_job_segment(job, runtime->active_segment[resource])->id,
            resource, RT_AI_TRACE_QUARANTINE, job->terminal_status);
    runtime->active_job[resource] = NULL;
    runtime->active_cookie[resource] = 0U;
    runtime->recovery_job[resource] = NULL;
    runtime->resource_state[resource] = quarantined ? RT_AI_RESOURCE_QUARANTINED : RT_AI_RESOURCE_HEALTHY;
    if (!quarantined) runtime->reset_attempts[resource] = 0U;
    ++runtime->schedule_generation;
    if (job != NULL && job->pending_recovery != 0U) {
        if (quarantined) job->recovery_quarantined = 1U;
        --job->pending_recovery;
        if (job->pending_recovery == 0U && job->recovery_quarantined && job->terminal_state == RT_AI_JOB_FAILED &&
            job->session->aeg.fallback_segment_count != 0U && runtime->last_now_us < job->deadline_us) {
            int admission = fallback_admissible(runtime, job);
            if (admission == RT_AI_OK) {
                uint16_t segment;
                for (segment = 0U; segment < RT_AI_MAX_SEGMENTS; ++segment) job->segment_state[segment] = RT_AI_SEG_PENDING;
                job->use_fallback = 1U;
                rt_ai_trace(runtime, runtime->last_now_us, job, 0U, job->session->aeg.fallback_storage[0].id,
                    job->session->aeg.fallback_storage[0].resource, RT_AI_TRACE_FALLBACK, RT_AI_OK);
                job->recovering = 0U;
                job->recovery_quarantined = 0U;
                job->state = RT_AI_JOB_PENDING;
                job->status = RT_AI_BUSY;
                ++runtime->schedule_generation;
                return;
            }
            rt_ai_trace(runtime, runtime->last_now_us, job, 0U, job->session->aeg.fallback_storage[0].id,
                job->session->aeg.fallback_storage[0].resource, RT_AI_TRACE_FALLBACK, admission);
        }
        if (job->pending_recovery == 0U) rt_ai_finish_job(job, job->terminal_state, job->terminal_status);
    }
}

static void begin_reset(rt_ai_runtime_t *runtime, uint8_t resource, uint64_t now_us);

static void reset_failed(rt_ai_runtime_t *runtime, uint8_t resource, uint64_t now_us)
{
    rt_ai_job_t *job = runtime->recovery_job[resource];
    uint32_t limit = job != NULL && job->session->aeg.max_reset_attempts != 0U ? job->session->aeg.max_reset_attempts : 1U;
    if (runtime->reset_attempts[resource] < limit) begin_reset(runtime, resource, now_us);
    else recovery_done(runtime, resource, 1);
}

static void begin_reinit(rt_ai_runtime_t *runtime, uint8_t resource, uint64_t now_us)
{
    rt_ai_provider_t *provider = &runtime->providers[resource];
    if (provider->reinit_poll == NULL) { recovery_done(runtime, resource, 0); return; }
    runtime->resource_state[resource] = RT_AI_RESOURCE_REINIT_PENDING;
    runtime->recovery_deadline_us[resource] = now_us +
        (runtime->recovery_job[resource] != NULL ? runtime->recovery_job[resource]->session->aeg.reinit_timeout_us : 1000U);
}

static void begin_reset(rt_ai_runtime_t *runtime, uint8_t resource, uint64_t now_us)
{
    rt_ai_provider_t *provider = &runtime->providers[resource];
    int status;
    ++runtime->reset_attempts[resource];
    ++runtime->epoch[resource];
    runtime->resource_state[resource] = RT_AI_RESOURCE_RESET_PENDING;
    if (runtime->recovery_job[resource] != NULL)
        rt_ai_trace(runtime, now_us, runtime->recovery_job[resource], runtime->active_cookie[resource],
            rt_ai_job_segment(runtime->recovery_job[resource], runtime->active_segment[resource])->id, resource, RT_AI_TRACE_RESET, RT_AI_OK);
    status = provider->reset_begin != NULL ? provider->reset_begin(provider->user, runtime->epoch[resource]) :
        (provider->reset != NULL ? provider->reset(provider->user, runtime->epoch[resource]) : RT_AI_ERR_PROVIDER);
    if (status != RT_AI_OK) {
        trace_recovery_issue(runtime, resource, RT_AI_TRACE_RESET_BEGIN_ERROR, status);
        reset_failed(runtime, resource, now_us);
        return;
    }
    if (provider->reset_poll == NULL) { begin_reinit(runtime, resource, now_us); return; }
    runtime->recovery_deadline_us[resource] = now_us +
        (runtime->recovery_job[resource] != NULL ? runtime->recovery_job[resource]->session->aeg.reset_timeout_us : 500U);
}

int rt_ai_abort_job(rt_ai_job_t *job, rt_ai_job_state_t state, int status)
{
    uint16_t resource;
    rt_ai_runtime_t *runtime;
    if (job == NULL || job->session == NULL || job->state < RT_AI_JOB_PENDING || job->state > RT_AI_JOB_RUNNING || job->recovering)
        return RT_AI_ERR_INVALID;
    runtime = job->session->runtime;
    job->terminal_state = state;
    job->terminal_status = status;
    for (resource = 0U; resource < RT_AI_MAX_RESOURCES; ++resource) {
        rt_ai_provider_t *provider = &runtime->providers[resource];
        rt_ai_queue_remove_job(&runtime->queues[resource], job);
        if (runtime->active_job[resource] != job) continue;
        rt_ai_trace(runtime, runtime->last_now_us, job, runtime->active_cookie[resource],
            rt_ai_job_segment(job, runtime->active_segment[resource])->id, (uint8_t)resource, RT_AI_TRACE_CANCEL, status);
        if (job->segment_state[runtime->active_segment[resource]] == RT_AI_SEG_HELD) {
            runtime->active_job[resource] = NULL;
            runtime->active_cookie[resource] = 0U;
            runtime->resource_state[resource] = RT_AI_RESOURCE_HEALTHY;
            continue;
        }
        if (provider->cancel_begin != NULL && provider->cancel_poll != NULL) {
            int begin_status = provider->cancel_begin(provider->user, runtime->epoch[resource], runtime->active_cookie[resource]);
            if (begin_status != RT_AI_OK && begin_status != RT_AI_BUSY) {
                runtime->recovery_job[resource] = job;
                ++job->pending_recovery;
                trace_recovery_issue(runtime, (uint8_t)resource, RT_AI_TRACE_CANCEL_ERROR, begin_status);
                begin_reset(runtime, (uint8_t)resource, runtime->last_now_us);
                continue;
            }
            runtime->resource_state[resource] = RT_AI_RESOURCE_CANCEL_PENDING;
            runtime->recovery_job[resource] = job;
            runtime->recovery_deadline_us[resource] = runtime->last_now_us + job->session->aeg.cancel_ack_timeout_us;
            ++job->pending_recovery;
        } else {
            if (provider->cancel != NULL) (void)provider->cancel(provider->user, runtime->epoch[resource], runtime->active_cookie[resource]);
            runtime->active_job[resource] = NULL;
            runtime->active_cookie[resource] = 0U;
            runtime->resource_state[resource] = RT_AI_RESOURCE_HEALTHY;
        }
    }
    if (job->pending_recovery == 0U) rt_ai_finish_job(job, state, status);
    else job->recovering = 1U;
    return RT_AI_OK;
}

void rt_ai_recovery_poll(rt_ai_runtime_t *runtime, uint64_t now_us)
{
    uint8_t resource;
    for (resource = 0U; resource < RT_AI_MAX_RESOURCES; ++resource) {
        rt_ai_provider_t *provider = &runtime->providers[resource];
        if (runtime->resource_state[resource] == RT_AI_RESOURCE_CANCEL_PENDING) {
            int status = provider->cancel_poll(provider->user, runtime->epoch[resource], runtime->active_cookie[resource]);
            if (status == RT_AI_OK) recovery_done(runtime, resource, 0);
            else if (status != RT_AI_BUSY || now_us >= runtime->recovery_deadline_us[resource]) {
                trace_recovery_issue(runtime, resource,
                    status == RT_AI_BUSY ? RT_AI_TRACE_RECOVERY_TIMEOUT : RT_AI_TRACE_CANCEL_ERROR, status);
                begin_reset(runtime, resource, now_us);
            }
        } else if (runtime->resource_state[resource] == RT_AI_RESOURCE_RESET_PENDING) {
            int status = provider->reset_poll(provider->user, runtime->epoch[resource]);
            if (status == RT_AI_OK) begin_reinit(runtime, resource, now_us);
            else if (status != RT_AI_BUSY || now_us >= runtime->recovery_deadline_us[resource]) {
                trace_recovery_issue(runtime, resource,
                    status == RT_AI_BUSY ? RT_AI_TRACE_RECOVERY_TIMEOUT : RT_AI_TRACE_RESET_POLL_ERROR, status);
                reset_failed(runtime, resource, now_us);
            }
        } else if (runtime->resource_state[resource] == RT_AI_RESOURCE_REINIT_PENDING) {
            int status = provider->reinit_poll(provider->user, runtime->epoch[resource]);
            int health_status = status == RT_AI_OK && provider->health != NULL ? provider->health(provider->user) : RT_AI_OK;
            if (status == RT_AI_OK && health_status == RT_AI_OK) recovery_done(runtime, resource, 0);
            else if (status != RT_AI_BUSY || now_us >= runtime->recovery_deadline_us[resource]) {
                trace_recovery_issue(runtime, resource,
                    status == RT_AI_BUSY ? RT_AI_TRACE_RECOVERY_TIMEOUT : RT_AI_TRACE_REINIT_ERROR,
                    status != RT_AI_OK ? status : health_status);
                reset_failed(runtime, resource, now_us);
            }
        }
    }
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
    unsigned long level;
    if (runtime == NULL || device_id >= RT_AI_MAX_RESOURCES || !runtime->provider_valid[device_id]) return RT_AI_ERR_INVALID;
    level = rt_ai_port_lock();
    job = runtime->active_job[device_id];
    if (job != NULL && !job->recovering) {
        job->terminal_state = RT_AI_JOB_FAILED;
        job->terminal_status = RT_AI_ERR_TIMEOUT;
        job->recovering = 1U;
        job->pending_recovery = 1U;
        runtime->recovery_job[device_id] = job;
    }
    begin_reset(runtime, device_id, runtime->last_now_us);
    rt_ai_port_unlock(level);
    return RT_AI_OK;
}

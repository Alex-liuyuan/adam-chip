#include "rvaic.h"

#include <string.h>

#ifdef RT_USING_HEAP
#include <rtthread.h>
#endif

typedef struct
{
    rvaic_job_t *jobs[RVAIC_MAX_SERVICE_JOBS];
    rvaic_service_stats_t stats;
    rvaic_backend_queue_state_t cpu;
    rvaic_backend_queue_state_t rvv;
    rvaic_backend_queue_state_t npu;
} rvaic_service_t;

static rvaic_service_t g_service;
static int g_service_running;

#define RVAIC_SERVICE_EVENT_JOB 0x01u
#define RVAIC_SERVICE_EVENT_STOP 0x02u

#ifdef RT_USING_HEAP
static rt_thread_t g_service_thread;

#ifdef RT_USING_EVENT
static rt_event_t g_service_event;
#endif

static void rvaic_service_thread_entry(void *parameter)
{
    (void)parameter;
    while (g_service_running)
    {
#ifdef RT_USING_EVENT
        if (g_service_event)
        {
            (void)rt_event_recv(
                g_service_event,
                RVAIC_SERVICE_EVENT_JOB | RVAIC_SERVICE_EVENT_STOP,
                RT_EVENT_FLAG_OR | RT_EVENT_FLAG_CLEAR,
                1,
                RT_NULL);
        }
        else
#endif
        {
            rt_thread_mdelay(1);
        }
        (void)rvaic_service_step();
    }
}
#endif

static rvaic_backend_queue_state_t *queue_for_mask(uint32_t backend_mask)
{
    if (backend_mask & RVAIC_BACKEND_NPU)
    {
        return &g_service.npu;
    }
    if (backend_mask & RVAIC_BACKEND_RVV)
    {
        return &g_service.rvv;
    }
    return &g_service.cpu;
}

static rvaic_backend_queue_state_t *runnable_queue_for_mask(uint32_t backend_mask)
{
    if ((backend_mask & RVAIC_BACKEND_NPU) && g_service.npu.credits > 0u)
    {
        return &g_service.npu;
    }
    if ((backend_mask & RVAIC_BACKEND_RVV) && g_service.rvv.credits > 0u)
    {
        return &g_service.rvv;
    }
    if ((backend_mask & RVAIC_BACKEND_CPU) && g_service.cpu.credits > 0u)
    {
        return &g_service.cpu;
    }
    return 0;
}

static int queued_count(void)
{
    int count = 0;
    for (int i = 0; i < RVAIC_MAX_SERVICE_JOBS; i++)
    {
        if (g_service.jobs[i])
        {
            count++;
        }
    }
    return count;
}

static int select_job(void)
{
    int selected = -1;
    uint32_t best_priority = 0u;

    for (int i = 0; i < RVAIC_MAX_SERVICE_JOBS; i++)
    {
        const rvaic_job_t *job = g_service.jobs[i];
        if (!job)
        {
            continue;
        }
        if (job->dependency && !job->dependency->signaled)
        {
            continue;
        }
        if (!runnable_queue_for_mask(job->backend_mask))
        {
            continue;
        }
        if (selected < 0 || job->priority > best_priority)
        {
            selected = i;
            best_priority = job->priority;
        }
    }
    return selected;
}

int rvaic_service_init(void)
{
    memset(&g_service, 0, sizeof(g_service));
    g_service_running = 0;
#ifdef RT_USING_HEAP
    g_service_thread = 0;
#ifdef RT_USING_EVENT
    g_service_event = 0;
#endif
#endif
    g_service.cpu.backend_mask = RVAIC_BACKEND_CPU;
    g_service.cpu.credits = 1u;
    g_service.rvv.backend_mask = RVAIC_BACKEND_RVV;
    g_service.rvv.credits = 1u;
    g_service.npu.backend_mask = RVAIC_BACKEND_NPU;
    g_service.npu.credits = 1u;
    return 0;
}

int rvaic_backend_lock(uint32_t backend_mask)
{
    queue_for_mask(backend_mask)->credits = 0u;
    return 0;
}

int rvaic_backend_unlock(uint32_t backend_mask)
{
    queue_for_mask(backend_mask)->credits = 1u;
    return 0;
}

int rvaic_service_start(void)
{
    g_service_running = 1;
#ifdef RT_USING_HEAP
#ifdef RT_USING_EVENT
    if (!g_service_event)
    {
        g_service_event = rt_event_create("rvaic_evt", RT_IPC_FLAG_PRIO);
        if (!g_service_event)
        {
            g_service_running = 0;
            return -1;
        }
    }
#endif
    if (!g_service_thread)
    {
        g_service_thread = rt_thread_create("rvaic", rvaic_service_thread_entry, RT_NULL, 2048, 20, 10);
        if (!g_service_thread)
        {
            g_service_running = 0;
            return -1;
        }
        rt_thread_startup(g_service_thread);
    }
#endif
    return 0;
}

int rvaic_service_stop(void)
{
    g_service_running = 0;
#if defined(RT_USING_HEAP) && defined(RT_USING_EVENT)
    if (g_service_event)
    {
        (void)rt_event_send(g_service_event, RVAIC_SERVICE_EVENT_STOP);
    }
#endif
    return 0;
}

int rvaic_service_submit(rvaic_job_t *job)
{
    rvaic_backend_queue_state_t *queue;

    if (!job)
    {
        return -1;
    }
    for (int i = 0; i < RVAIC_MAX_SERVICE_JOBS; i++)
    {
        if (!g_service.jobs[i])
        {
            g_service.jobs[i] = job;
            job->state = RVAIC_JOB_PENDING;
            queue = queue_for_mask(job->backend_mask);
            queue->queued++;
            g_service.stats.submitted++;
            g_service.stats.queued = (uint32_t)queued_count();
#if defined(RT_USING_HEAP) && defined(RT_USING_EVENT)
            if (g_service_event)
            {
                (void)rt_event_send(g_service_event, RVAIC_SERVICE_EVENT_JOB);
            }
#endif
            return 0;
        }
    }
    job->state = RVAIC_JOB_FAILED;
    job->status = RVAIC_STATUS_QUEUE_FULL;
    return RVAIC_STATUS_QUEUE_FULL;
}

int rvaic_service_post_event(uint32_t event_id, rvaic_job_t *job)
{
    (void)event_id;
    return rvaic_service_submit(job);
}

int rvaic_service_step(void)
{
    int selected = select_job();
    rvaic_job_t *job;
    rvaic_backend_queue_state_t *queue;
    rvaic_backend_queue_state_t *run_queue;
    int status;

    if (selected < 0)
    {
        g_service.stats.queued = (uint32_t)queued_count();
        return 0;
    }

    job = g_service.jobs[selected];
    queue = queue_for_mask(job->backend_mask);
    run_queue = runnable_queue_for_mask(job->backend_mask);
    if (!run_queue)
    {
        return 0;
    }
    g_service.jobs[selected] = 0;
    if (queue->queued > 0u)
    {
        queue->queued--;
    }
    run_queue->running++;

    if (job->state == RVAIC_JOB_CANCELLED)
    {
        status = RVAIC_STATUS_CANCELLED;
        job->status = status;
        job->state = RVAIC_JOB_CANCELLED;
        g_service.stats.cancelled++;
    }
    else
    {
        status = rvaic_submit(job);
        if (status == RVAIC_STATUS_TIMEOUT)
        {
            g_service.stats.timed_out++;
            if (rvaic_backend_reset(job->backend_mask) == 0)
            {
                g_service.stats.resets++;
            }
        }
    }

    if (run_queue->running > 0u)
    {
        run_queue->running--;
    }
    run_queue->completed++;
    g_service.stats.completed++;
    g_service.stats.queued = (uint32_t)queued_count();
    return status;
}

int rvaic_service_watchdog_tick(uint32_t elapsed_us)
{
    int timed_out = 0;

    for (int i = 0; i < RVAIC_MAX_SERVICE_JOBS; i++)
    {
        rvaic_job_t *job = g_service.jobs[i];
        if (job && rvaic_timeout_check(job, elapsed_us) == RVAIC_STATUS_TIMEOUT)
        {
            rvaic_backend_queue_state_t *queue = queue_for_mask(job->backend_mask);
            g_service.jobs[i] = 0;
            if (queue->queued > 0u)
            {
                queue->queued--;
            }
            g_service.stats.timed_out++;
            g_service.stats.completed++;
            timed_out++;
            if (rvaic_backend_reset(job->backend_mask) == 0)
            {
                g_service.stats.resets++;
            }
        }
    }
    g_service.stats.queued = (uint32_t)queued_count();
    return timed_out;
}

int rvaic_service_drain(void)
{
    int status = 0;

    while (queued_count() > 0)
    {
        int before = queued_count();
        int step_status = rvaic_service_step();
        if (step_status != 0)
        {
            status = step_status;
        }
        if (queued_count() == before)
        {
            return status != 0 ? status : -1;
        }
    }
    return status;
}

int rvaic_service_stats(rvaic_service_stats_t *stats)
{
    if (!stats)
    {
        return -1;
    }
    g_service.stats.queued = (uint32_t)queued_count();
    *stats = g_service.stats;
    return 0;
}

int rvaic_backend_queue_state(uint32_t backend_mask, rvaic_backend_queue_state_t *state)
{
    if (!state)
    {
        return -1;
    }
    *state = *queue_for_mask(backend_mask);
    return 0;
}

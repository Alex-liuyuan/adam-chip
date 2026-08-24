#include "rvaic.h"

const rt_ai_model_t *rt_ai_model_find(const char *name)
{
    return rvaic_model_find(name);
}

int rt_ai_model_admit(const rt_ai_model_t *model, const rt_ai_admission_policy_t *policy)
{
    size_t arena_available = 0u;
    uint32_t backend_mask = 0u;

    if (policy)
    {
        arena_available = policy->arena_available;
        backend_mask = policy->backend_mask;
    }
    else
    {
        arena_available = rvaic_arena_pool_available();
    }
    return rvaic_model_admit(model, arena_available, backend_mask);
}

int rt_ai_model_unload(const char *name)
{
    return rvaic_model_unregister(name);
}

int rt_ai_submit(rt_ai_job_t *job, rt_ai_fence_t **completion)
{
    if (!job)
    {
        return -1;
    }
    if (completion)
    {
        *completion = job->fence;
    }
    return rvaic_service_submit(job);
}

int rt_ai_cancel(rt_ai_job_t *job)
{
    return rvaic_cancel(job);
}

#ifdef RT_USING_HEAP
rt_object_t rt_ai_model_object_register(const char *name, const rt_ai_model_t *model)
{
    if (rvaic_model_register(name, model) != 0)
    {
        return RT_NULL;
    }
    return rt_custom_object_create(name, (void *)model, RT_NULL);
}

rt_object_t rt_ai_model_object_find(const char *name)
{
    return rt_object_find(name, RT_Object_Class_Custom);
}
#endif

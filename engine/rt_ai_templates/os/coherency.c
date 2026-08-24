#include "rt_ai_internal.h"
#include "rt_ai_target.h"

static int range(rt_ai_job_t *job, const rt_ai_aeg_segment_t *segment, void **address, size_t *size)
{
    size_t line = RT_AI_CACHE_LINE_BYTES;
    size_t start;
    size_t end;
    if (line == 0U || segment->arena_offset > job->lease.size || segment->arena_size > job->lease.size - segment->arena_offset) return RT_AI_ERR_INVALID;
    start = segment->arena_offset - segment->arena_offset % line;
    end = segment->arena_offset + segment->arena_size;
    if (end % line != 0U) {
        size_t add = line - end % line;
        end = add > job->lease.size - end ? job->lease.size : end + add;
    }
    *address = job->session->runtime->arena + job->lease.offset + start;
    *size = end - start;
    return RT_AI_OK;
}

int rt_ai_coherency_before(rt_ai_job_t *job, uint16_t segment_index)
{
    const rt_ai_aeg_segment_t *segment = rt_ai_job_segment(job, segment_index);
    rt_ai_provider_t *provider = &job->session->runtime->providers[segment->resource];
    void *address;
    size_t size;
    int status = range(job, segment, &address, &size);
    if (status != RT_AI_OK) return status;
    if ((segment->flags & RT_AI_SEGMENT_CLEAN_INPUT) != 0U) {
        if (provider->clean_range != NULL) status = provider->clean_range(provider->user, address, size);
        else if (provider->clean != NULL) provider->clean(provider->user, address, size);
        else status = RT_AI_ERR_PROVIDER;
    }
    if (status == RT_AI_OK && provider->barrier != NULL) status = provider->barrier(provider->user);
    if (status == RT_AI_OK) job->buffer_owner[segment_index] = 1U;
    return status;
}

int rt_ai_coherency_after(rt_ai_job_t *job, uint16_t segment_index)
{
    const rt_ai_aeg_segment_t *segment = rt_ai_job_segment(job, segment_index);
    rt_ai_provider_t *provider = &job->session->runtime->providers[segment->resource];
    void *address;
    size_t size;
    int status = range(job, segment, &address, &size);
    if (status != RT_AI_OK) return status;
    if (provider->barrier != NULL) status = provider->barrier(provider->user);
    if ((segment->flags & RT_AI_SEGMENT_INVALIDATE_OUTPUT) != 0U) {
        if (status != RT_AI_OK) return status;
        if (provider->invalidate_range != NULL) status = provider->invalidate_range(provider->user, address, size);
        else if (provider->invalidate != NULL) provider->invalidate(provider->user, address, size);
        else status = RT_AI_ERR_PROVIDER;
    }
    if (status == RT_AI_OK && provider->barrier != NULL) status = provider->barrier(provider->user);
    if (status == RT_AI_OK) job->buffer_owner[segment_index] = 0U;
    return status;
}

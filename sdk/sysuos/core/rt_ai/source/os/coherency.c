#include "rt_ai_internal.h"

static void *segment_address(rt_ai_job_t *job, const rt_ai_aeg_segment_t *segment)
{
    return job->session->runtime->arena + job->session->lease.offset + segment->arena_offset;
}

void rt_ai_coherency_before(rt_ai_job_t *job, uint16_t segment_index)
{
    const rt_ai_aeg_segment_t *segment = &job->session->aeg.segments[segment_index];
    rt_ai_provider_t *provider = &job->session->runtime->providers[segment->resource];
    if ((segment->flags & RT_AI_SEGMENT_CLEAN_INPUT) != 0U && provider->clean != NULL)
        provider->clean(provider->user, segment_address(job, segment), segment->arena_size);
}

void rt_ai_coherency_after(rt_ai_job_t *job, uint16_t segment_index)
{
    const rt_ai_aeg_segment_t *segment = &job->session->aeg.segments[segment_index];
    rt_ai_provider_t *provider = &job->session->runtime->providers[segment->resource];
    if ((segment->flags & RT_AI_SEGMENT_INVALIDATE_OUTPUT) != 0U && provider->invalidate != NULL)
        provider->invalidate(provider->user, segment_address(job, segment), segment->arena_size);
}

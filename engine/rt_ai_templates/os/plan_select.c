#include "rt_ai_internal.h"

void rt_ai_select_aeg(const rt_ai_aeg_t *source, int fallback, rt_ai_aeg_t *selected)
{
    uint16_t index;
    *selected = *source;
    if (!fallback) { selected->segments = selected->storage; return; }
    selected->header.segment_count = source->fallback_segment_count;
    for (index = 0U; index < source->fallback_segment_count; ++index) {
        selected->storage[index] = source->fallback_storage[index];
        selected->wcet_us[index] = source->fallback_wcet_us[index];
        selected->coherency_cost_us[index] = source->fallback_coherency_cost_us[index];
        selected->recovery_cost_us[index] = source->fallback_recovery_cost_us[index];
    }
    selected->segments = selected->storage;
}

uint16_t rt_ai_job_segment_count(const rt_ai_job_t *job)
{
    return job->use_fallback ? job->session->aeg.fallback_segment_count : job->session->aeg.header.segment_count;
}

const rt_ai_aeg_segment_t *rt_ai_job_segment(const rt_ai_job_t *job, uint16_t index)
{
    return job->use_fallback ? &job->session->aeg.fallback_storage[index] : &job->session->aeg.segments[index];
}

uint32_t rt_ai_job_wcet(const rt_ai_job_t *job, uint16_t index)
{
    return job->use_fallback ? job->session->aeg.fallback_wcet_us[index] : job->session->aeg.wcet_us[index];
}

uint32_t rt_ai_job_coherency_cost(const rt_ai_job_t *job, uint16_t index)
{
    return job->use_fallback ? job->session->aeg.fallback_coherency_cost_us[index] : job->session->aeg.coherency_cost_us[index];
}

uint32_t rt_ai_job_recovery_cost(const rt_ai_job_t *job, uint16_t index)
{
    return job->use_fallback ? job->session->aeg.fallback_recovery_cost_us[index] : job->session->aeg.recovery_cost_us[index];
}

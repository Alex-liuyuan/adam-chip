#include "rt_ai_internal.h"

void rt_ai_trace(rt_ai_runtime_t *runtime, uint64_t now_us, uint32_t cookie, uint16_t segment_id, int16_t event)
{
    rt_ai_trace_entry_t *entry;
    if (runtime == NULL) return;
    entry = &runtime->trace[runtime->trace_head % RT_AI_TRACE_DEPTH];
    entry->timestamp_us = now_us;
    entry->cookie = cookie;
    entry->segment_id = segment_id;
    entry->event = event;
    runtime->trace_head = (uint16_t)(runtime->trace_head + 1U);
}

const rt_ai_trace_entry_t *rt_ai_trace_data(const rt_ai_runtime_t *runtime, uint16_t *count)
{
    if (runtime == NULL || count == NULL) return NULL;
    *count = runtime->trace_head < RT_AI_TRACE_DEPTH ? runtime->trace_head : RT_AI_TRACE_DEPTH;
    return runtime->trace;
}

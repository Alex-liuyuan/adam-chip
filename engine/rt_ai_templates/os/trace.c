#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "rt_ai_internal.h"

static int append(char *output, size_t capacity, size_t *used, const char *format, ...)
{
    int count;
    va_list args;
    if (*used >= capacity) return RT_AI_ERR_RESOURCE;
    va_start(args, format);
    count = vsnprintf(output + *used, capacity - *used, format, args);
    va_end(args);
    if (count < 0 || (size_t)count >= capacity - *used) return RT_AI_ERR_RESOURCE;
    *used += (size_t)count;
    return RT_AI_OK;
}

void rt_ai_trace(rt_ai_runtime_t *runtime, uint64_t now_us, const rt_ai_job_t *job, uint64_t cookie, uint16_t segment_id, uint8_t resource, uint16_t event, int status)
{
    rt_ai_trace_entry_t *entry;
    uint64_t sequence;
    if (runtime == NULL || job == NULL) return;
    sequence = runtime->trace_sequence++;
    if (sequence >= RT_AI_TRACE_DEPTH) ++runtime->trace_dropped;
    entry = &runtime->trace[sequence % RT_AI_TRACE_DEPTH];
    memset(entry, 0, sizeof(*entry));
    entry->sequence = sequence;
    entry->timestamp_us = now_us;
    entry->job_id = job->job_id;
    entry->cookie = cookie;
    entry->run_id = job->run_id;
    memcpy(entry->plan_id, job->use_fallback ? job->session->aeg.fallback_plan_sha256 : job->session->aeg.plan_sha256, sizeof(entry->plan_id));
    entry->segment_id = segment_id;
    entry->resource = resource;
    entry->epoch = runtime->epoch[resource];
    entry->event = event;
    entry->status = status;
    entry->queue_depth = runtime->queues[resource].count;
}

void rt_ai_trace_decision(rt_ai_runtime_t *runtime, uint64_t now_us, const rt_ai_session_t *session,
    uint64_t run_id, uint8_t resource, uint16_t event, int status)
{
    rt_ai_trace_entry_t *entry;
    uint64_t sequence;
    if (runtime == NULL || session == NULL || resource >= RT_AI_MAX_RESOURCES) return;
    sequence = runtime->trace_sequence++;
    if (sequence >= RT_AI_TRACE_DEPTH) ++runtime->trace_dropped;
    entry = &runtime->trace[sequence % RT_AI_TRACE_DEPTH];
    memset(entry, 0, sizeof(*entry));
    entry->sequence = sequence;
    entry->timestamp_us = now_us;
    entry->run_id = run_id;
    memcpy(entry->plan_id, session->aeg.plan_sha256, sizeof(entry->plan_id));
    entry->resource = resource;
    entry->epoch = runtime->epoch[resource];
    entry->event = event;
    entry->status = status;
    entry->queue_depth = runtime->queues[resource].count;
}

int rt_ai_trace_snapshot(const rt_ai_runtime_t *runtime, rt_ai_trace_entry_t *entries, uint16_t capacity, uint16_t *count, uint64_t *dropped)
{
    uint64_t available;
    uint64_t start;
    uint16_t index;
    if (runtime == NULL || entries == NULL || count == NULL || dropped == NULL || capacity == 0U) return RT_AI_ERR_INVALID;
    available = runtime->trace_sequence < RT_AI_TRACE_DEPTH ? runtime->trace_sequence : RT_AI_TRACE_DEPTH;
    if (available > capacity) available = capacity;
    start = runtime->trace_sequence - available;
    for (index = 0U; index < available; ++index) entries[index] = runtime->trace[(start + index) % RT_AI_TRACE_DEPTH];
    *count = (uint16_t)available;
    *dropped = runtime->trace_sequence - available;
    return RT_AI_OK;
}

int rt_ai_trace_json(const rt_ai_runtime_t *runtime, char *output, size_t capacity, size_t *written)
{
    static const char *resources[] = {"cpu", "rvv", "npu", "dma"};
    static const char *events[] = {"unknown", "dispatch", "complete", "cancel", "reset", "quarantine", "fallback",
        "domain_reject", "evidence_reject", "provider_reject", "memory_reject", "deadline_reject", "retry_reject",
        "cancel_error", "reset_begin_error", "reset_poll_error", "reinit_error", "recovery_timeout", "coherency_error"};
    rt_ai_trace_entry_t entries[RT_AI_TRACE_DEPTH];
    uint16_t count, index, byte;
    uint64_t dropped;
    size_t used = 0U;
    int status;
    if (output == NULL || written == NULL) return RT_AI_ERR_INVALID;
    status = rt_ai_trace_snapshot(runtime, entries, RT_AI_TRACE_DEPTH, &count, &dropped);
    if (status != RT_AI_OK || count == 0U) return RT_AI_ERR_INVALID;
    for (index = 1U; index < count; ++index) if (entries[index].run_id != entries[0].run_id) return RT_AI_ERR_INVALID;
    if (append(output, capacity, &used, "{\"schema\":\"soc-image.airtos-trace.v2\",\"run_id\":\"%064llx\",\"plan_id\":\"", (unsigned long long)entries[0].run_id) != RT_AI_OK) return RT_AI_ERR_RESOURCE;
    for (byte = 0U; byte < 32U; ++byte) if (append(output, capacity, &used, "%02x", entries[0].plan_id[byte]) != RT_AI_OK) return RT_AI_ERR_RESOURCE;
    if (append(output, capacity, &used, "\",\"dropped\":%llu,\"events\":[", (unsigned long long)dropped) != RT_AI_OK) return RT_AI_ERR_RESOURCE;
    for (index = 0U; index < count; ++index) {
        const rt_ai_trace_entry_t *entry = &entries[index];
        if (entry->resource >= RT_AI_MAX_RESOURCES) return RT_AI_ERR_INVALID;
        if (append(output, capacity, &used,
            "%s{\"sequence\":%llu,\"timestamp_us\":%llu,\"job_id\":%llu,\"cookie\":%llu,\"plan_id\":\"",
            index == 0U ? "" : ",", (unsigned long long)entry->sequence, (unsigned long long)entry->timestamp_us,
            (unsigned long long)entry->job_id, (unsigned long long)entry->cookie) != RT_AI_OK) return RT_AI_ERR_RESOURCE;
        for (byte = 0U; byte < 32U; ++byte) if (append(output, capacity, &used, "%02x", entry->plan_id[byte]) != RT_AI_OK) return RT_AI_ERR_RESOURCE;
        if (append(output, capacity, &used,
            "\",\"segment_id\":%u,\"resource\":\"%s\",\"epoch\":%u,\"event\":\"%s\",\"status\":%d,\"queue_depth\":%u}",
            entry->segment_id, resources[entry->resource], entry->epoch,
            entry->event < sizeof(events) / sizeof(events[0]) ? events[entry->event] : events[0],
            entry->status, entry->queue_depth) != RT_AI_OK) return RT_AI_ERR_RESOURCE;
    }
    if (append(output, capacity, &used, "]}") != RT_AI_OK) return RT_AI_ERR_RESOURCE;
    *written = used;
    return RT_AI_OK;
}

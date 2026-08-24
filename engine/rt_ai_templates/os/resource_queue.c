#include "rt_ai_internal.h"

int rt_ai_queue_push(rt_ai_resource_queue_t *queue, const rt_ai_queue_item_t *item)
{
    uint16_t index;
    if (queue == NULL || item == NULL || queue->count >= RT_AI_MAX_QUEUE) return RT_AI_ERR_RESOURCE;
    index = queue->count;
    while (index > 0U && queue->items[index - 1U].deadline_us > item->deadline_us) {
        queue->items[index] = queue->items[index - 1U];
        --index;
    }
    queue->items[index] = *item;
    ++queue->count;
    return RT_AI_OK;
}

int rt_ai_queue_pop(rt_ai_resource_queue_t *queue, rt_ai_queue_item_t *item)
{
    uint16_t index;
    if (queue == NULL || item == NULL || queue->count == 0U) return RT_AI_BUSY;
    *item = queue->items[0];
    --queue->count;
    for (index = 0U; index < queue->count; ++index) queue->items[index] = queue->items[index + 1U];
    return RT_AI_OK;
}

void rt_ai_queue_remove_job(rt_ai_resource_queue_t *queue, const rt_ai_job_t *job)
{
    uint16_t read_index;
    uint16_t write_index = 0U;
    if (queue == NULL) return;
    for (read_index = 0U; read_index < queue->count; ++read_index) {
        if (queue->items[read_index].job != job) queue->items[write_index++] = queue->items[read_index];
    }
    queue->count = write_index;
}

#include <string.h>
#include "rt_ai.h"

int rt_ai_load(const void *blob, size_t size, rt_ai_aeg_t *aeg)
{
    rt_ai_aeg_header_t header;
    uint16_t index;
    if (blob == NULL || aeg == NULL || size < sizeof(rt_ai_aeg_header_t)) return RT_AI_ERR_INVALID;
    memcpy(&header, blob, sizeof(header));
    if (header.magic != RT_AI_AEG_MAGIC || header.version != RT_AI_AEG_VERSION || header.reserved != 0U ||
        header.segment_count == 0U || header.segment_count > RT_AI_MAX_SEGMENTS ||
        size < sizeof(header) + (size_t)header.segment_count * sizeof(rt_ai_aeg_segment_t)) return RT_AI_ERR_INVALID;
    memset(aeg, 0, sizeof(*aeg));
    aeg->header = header;
    for (index = 0U; index < header.segment_count; ++index) {
        const uint8_t *source = (const uint8_t *)blob + sizeof(header) + (size_t)index * sizeof(rt_ai_aeg_segment_t);
        rt_ai_aeg_segment_t *segment = &aeg->storage[index];
        uint16_t previous;
        uint32_t valid_dependencies = index == 0U ? 0U : (UINT32_C(1) << index) - 1U;
        memcpy(segment, source, sizeof(*segment));
        if (segment->resource >= RT_AI_MAX_RESOURCES ||
            (segment->dependency_mask & ~valid_dependencies) != 0U ||
            segment->arena_size == 0U || segment->arena_offset > header.arena_size ||
            segment->arena_size > header.arena_size - segment->arena_offset) return RT_AI_ERR_INVALID;
        for (previous = 0U; previous < index; ++previous)
            if (aeg->storage[previous].id == segment->id) return RT_AI_ERR_INVALID;
    }
    aeg->segments = aeg->storage;
    return RT_AI_OK;
}

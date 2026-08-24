#include <string.h>
#include "rt_ai.h"

#define AEG2_HEADER_SIZE 64U
#define AEG2_SECTION_SIZE 16U
#define AEG2_MAX_SECTIONS 8U
#define AEG2_SECTION_SEGMENTS 1U
#define AEG2_SECTION_METADATA 2U
#define AEG2_SECTION_EVIDENCE 3U
#define AEG2_SECTION_FALLBACKS 4U
#define AEG2_SECTION_RESERVATIONS 5U
#define AEG2_SECTION_ARRIVAL 6U
#define AEG2_SECTION_RECOVERY 7U
#define AEG2_SECTION_DOMAIN 8U

typedef struct {
    uint16_t type;
    uint16_t entry_size;
    uint32_t offset;
    uint32_t count;
    uint32_t end;
} aeg2_section_t;

static uint16_t read_u16(const uint8_t *value)
{
    return (uint16_t)value[0] | (uint16_t)((uint16_t)value[1] << 8);
}

static uint32_t read_u32(const uint8_t *value)
{
    return (uint32_t)value[0] | ((uint32_t)value[1] << 8) | ((uint32_t)value[2] << 16) | ((uint32_t)value[3] << 24);
}

static int nonzero_hash(const uint8_t *value)
{
    uint16_t index;
    for (index = 0U; index < 32U; ++index) if (value[index] != 0U) return 1;
    return 0;
}

static int validate_segment(rt_ai_aeg_t *aeg, uint16_t index)
{
    rt_ai_aeg_segment_t *segment = &aeg->storage[index];
    uint16_t previous;
    uint32_t valid_dependencies = index == 0U ? 0U : (UINT32_C(1) << index) - 1U;
    if (segment->resource >= RT_AI_MAX_RESOURCES ||
        (segment->dependency_mask & ~valid_dependencies) != 0U || segment->arena_size == 0U ||
        segment->arena_offset > aeg->header.arena_size || segment->arena_size > aeg->header.arena_size - segment->arena_offset)
        return RT_AI_ERR_INVALID;
    for (previous = 0U; previous < index; ++previous)
        if (aeg->storage[previous].id == segment->id) return RT_AI_ERR_INVALID;
    return RT_AI_OK;
}

static int load_v1(const uint8_t *blob, size_t size, rt_ai_aeg_t *aeg)
{
    uint16_t index;
    uint16_t count;
    uint32_t arena_size;
    size_t required;
    if (size < 16U || read_u16(blob + 4U) != RT_AI_AEG_VERSION || read_u32(blob + 12U) != 0U) return RT_AI_ERR_INVALID;
    count = read_u16(blob + 6U);
    arena_size = read_u32(blob + 8U);
    if (count == 0U || count > RT_AI_MAX_SEGMENTS) return RT_AI_ERR_INVALID;
    required = 16U + (size_t)count * 16U;
    if (size < required) return RT_AI_ERR_INVALID;
    memset(aeg, 0, sizeof(*aeg));
    aeg->header.magic = RT_AI_AEG_MAGIC;
    aeg->header.version = RT_AI_AEG_VERSION;
    aeg->header.segment_count = count;
    aeg->header.arena_size = arena_size;
    aeg->legacy = 1U;
    for (index = 0U; index < count; ++index) {
        const uint8_t *source = blob + 16U + (size_t)index * 16U;
        rt_ai_aeg_segment_t *segment = &aeg->storage[index];
        segment->id = read_u16(source);
        segment->resource = source[2];
        segment->flags = source[3];
        segment->dependency_mask = read_u32(source + 4U);
        segment->arena_offset = read_u32(source + 8U);
        segment->arena_size = read_u32(source + 12U);
        if (validate_segment(aeg, index) != RT_AI_OK) return RT_AI_ERR_INVALID;
    }
    aeg->segments = aeg->storage;
    return RT_AI_OK;
}

static const aeg2_section_t *find_section(const aeg2_section_t *sections, uint16_t count, uint16_t type)
{
    uint16_t index;
    for (index = 0U; index < count; ++index) if (sections[index].type == type) return &sections[index];
    return NULL;
}

static int load_v2(const uint8_t *blob, size_t size, rt_ai_aeg_t *aeg)
{
    aeg2_section_t sections[AEG2_MAX_SECTIONS];
    const aeg2_section_t *segments;
    const aeg2_section_t *metadata;
    const aeg2_section_t *evidence;
    const aeg2_section_t *fallbacks;
    const aeg2_section_t *reservations;
    const aeg2_section_t *arrival;
    const aeg2_section_t *recovery;
    const aeg2_section_t *domain;
    uint32_t total_size;
    uint32_t directory_end;
    uint16_t section_count;
    uint16_t index;
    if (size < AEG2_HEADER_SIZE || read_u16(blob + 4U) != RT_AI_AEG_V2_VERSION ||
        read_u16(blob + 6U) != AEG2_HEADER_SIZE || (read_u16(blob + 14U) & 1U) == 0U) return RT_AI_ERR_INVALID;
    total_size = read_u32(blob + 8U);
    section_count = read_u16(blob + 12U);
    if (section_count == 0U || section_count > AEG2_MAX_SECTIONS || total_size > size) return RT_AI_ERR_INVALID;
    directory_end = AEG2_HEADER_SIZE + (uint32_t)section_count * AEG2_SECTION_SIZE;
    if (total_size < directory_end || !nonzero_hash(blob + 20U)) return RT_AI_ERR_INVALID;
    for (index = 0U; index < section_count; ++index) {
        const uint8_t *entry = blob + AEG2_HEADER_SIZE + (size_t)index * AEG2_SECTION_SIZE;
        uint32_t bytes;
        uint16_t previous;
        sections[index].type = read_u16(entry);
        sections[index].entry_size = read_u16(entry + 2U);
        sections[index].offset = read_u32(entry + 4U);
        sections[index].count = read_u32(entry + 8U);
        if (read_u32(entry + 12U) != 0U || sections[index].entry_size == 0U ||
            sections[index].count > UINT32_MAX / sections[index].entry_size) return RT_AI_ERR_INVALID;
        bytes = sections[index].count * sections[index].entry_size;
        if (sections[index].offset < directory_end || sections[index].offset > total_size || bytes > total_size - sections[index].offset) return RT_AI_ERR_INVALID;
        sections[index].end = sections[index].offset + bytes;
        for (previous = 0U; previous < index; ++previous) {
            if (sections[previous].type == sections[index].type) return RT_AI_ERR_INVALID;
            if (sections[index].offset < sections[previous].end && sections[previous].offset < sections[index].end) return RT_AI_ERR_INVALID;
        }
    }
    segments = find_section(sections, section_count, AEG2_SECTION_SEGMENTS);
    metadata = find_section(sections, section_count, AEG2_SECTION_METADATA);
    evidence = find_section(sections, section_count, AEG2_SECTION_EVIDENCE);
    fallbacks = find_section(sections, section_count, AEG2_SECTION_FALLBACKS);
    reservations = find_section(sections, section_count, AEG2_SECTION_RESERVATIONS);
    arrival = find_section(sections, section_count, AEG2_SECTION_ARRIVAL);
    recovery = find_section(sections, section_count, AEG2_SECTION_RECOVERY);
    domain = find_section(sections, section_count, AEG2_SECTION_DOMAIN);
    if (segments == NULL || metadata == NULL || evidence == NULL || fallbacks == NULL || reservations == NULL || arrival == NULL || recovery == NULL || domain == NULL ||
        segments->entry_size != 32U || segments->count == 0U || segments->count > RT_AI_MAX_SEGMENTS ||
        metadata->entry_size != 256U || metadata->count != 1U || evidence->entry_size != 132U || evidence->count == 0U || evidence->count > RT_AI_MAX_EVIDENCE ||
        fallbacks->entry_size != 32U || fallbacks->count == 0U || fallbacks->count > RT_AI_MAX_SEGMENTS || reservations->entry_size != 16U ||
        reservations->count == 0U || reservations->count > RT_AI_MAX_RESOURCES || arrival->entry_size != 8U || arrival->count != 1U ||
        recovery->entry_size != 16U || recovery->count != 1U || domain->entry_size != 28U || domain->count != 1U) return RT_AI_ERR_INVALID;
    memset(aeg, 0, sizeof(*aeg));
    aeg->header.magic = RT_AI_AEG_V2_MAGIC;
    aeg->header.version = RT_AI_AEG_V2_VERSION;
    aeg->header.segment_count = (uint16_t)segments->count;
    aeg->header.arena_size = read_u32(blob + 16U);
    memcpy(aeg->plan_sha256, blob + 20U, 32U);
    if (memcmp(blob + metadata->offset, aeg->plan_sha256, 32U) != 0 ||
        !nonzero_hash(blob + metadata->offset + 32U) || !nonzero_hash(blob + metadata->offset + 64U)) return RT_AI_ERR_INVALID;
    memcpy(aeg->evidence_sha256, blob + metadata->offset + 32U, 32U);
    memcpy(aeg->policy_sha256, blob + metadata->offset + 64U, 32U);
    memcpy(aeg->model_sha256, blob + metadata->offset + 96U, 32U);
    memcpy(aeg->target_sha256, blob + metadata->offset + 128U, 32U);
    memcpy(aeg->runtime_abi_sha256, blob + metadata->offset + 160U, 32U);
    memcpy(aeg->provider_abi_sha256, blob + metadata->offset + 192U, 32U);
    memcpy(aeg->fallback_plan_sha256, blob + metadata->offset + 224U, 32U);
    if (!nonzero_hash(aeg->model_sha256) || !nonzero_hash(aeg->target_sha256) || !nonzero_hash(aeg->runtime_abi_sha256) || !nonzero_hash(aeg->provider_abi_sha256)) return RT_AI_ERR_INVALID;
    for (index = 0U; index < segments->count; ++index) {
        const uint8_t *source = blob + segments->offset + (size_t)index * 32U;
        rt_ai_aeg_segment_t *segment = &aeg->storage[index];
        segment->id = read_u16(source);
        segment->resource = source[2];
        segment->flags = source[3];
        segment->dependency_mask = read_u32(source + 4U);
        segment->arena_offset = read_u32(source + 8U);
        segment->arena_size = read_u32(source + 12U);
        aeg->wcet_us[index] = read_u32(source + 16U);
        aeg->coherency_cost_us[index] = read_u32(source + 20U);
        aeg->recovery_cost_us[index] = read_u32(source + 24U);
        aeg->fallback_plan_id[index] = read_u16(source + 28U);
        aeg->evidence_index[index] = read_u16(source + 30U);
        if (aeg->wcet_us[index] == 0U || aeg->fallback_plan_id[index] == 0U ||
            aeg->evidence_index[index] >= evidence->count || validate_segment(aeg, index) != RT_AI_OK) return RT_AI_ERR_INVALID;
    }
    for (index = 0U; index < evidence->count; ++index) {
        const uint8_t *record = blob + evidence->offset + (size_t)index * 132U;
        if (!nonzero_hash(record) || !nonzero_hash(record + 32U) || !nonzero_hash(record + 64U) || !nonzero_hash(record + 96U) ||
            record[128] != 1U || record[129] >= RT_AI_MAX_RESOURCES || read_u16(record + 130U) != 0U) return RT_AI_ERR_INVALID;
        memcpy(aeg->obligation_sha256[index], record, 32U);
        memcpy(aeg->scope_sha256[index], record + 32U, 32U);
        memcpy(aeg->artifact_sha256[index], record + 64U, 32U);
        memcpy(aeg->verifier_sha256[index], record + 96U, 32U);
        aeg->evidence_status[index] = record[128];
        aeg->evidence_resource[index] = record[129];
    }
    aeg->evidence_count = (uint8_t)evidence->count;
    aeg->fallback_segment_count = (uint16_t)fallbacks->count;
    for (index = 0U; index < fallbacks->count; ++index) {
        const uint8_t *record = blob + fallbacks->offset + (size_t)index * 32U;
        rt_ai_aeg_segment_t *segment = &aeg->fallback_storage[index];
        uint16_t previous;
        uint32_t valid_dependencies = index == 0U ? 0U : (UINT32_C(1) << index) - 1U;
        segment->id = read_u16(record);
        segment->resource = record[2];
        segment->flags = record[3];
        segment->dependency_mask = read_u32(record + 4U);
        segment->arena_offset = read_u32(record + 8U);
        segment->arena_size = read_u32(record + 12U);
        aeg->fallback_wcet_us[index] = read_u32(record + 16U);
        aeg->fallback_coherency_cost_us[index] = read_u32(record + 20U);
        aeg->fallback_recovery_cost_us[index] = read_u32(record + 24U);
        aeg->fallback_evidence[index] = read_u16(record + 30U);
        if (segment->id == 0U || segment->resource >= RT_AI_MAX_RESOURCES || (segment->dependency_mask & ~valid_dependencies) != 0U ||
            segment->arena_size == 0U || segment->arena_offset > aeg->header.arena_size || segment->arena_size > aeg->header.arena_size - segment->arena_offset ||
            aeg->fallback_wcet_us[index] == 0U || read_u16(record + 28U) == 0U || aeg->fallback_evidence[index] >= evidence->count) return RT_AI_ERR_INVALID;
        for (previous = 0U; previous < index; ++previous) if (aeg->fallback_storage[previous].id == segment->id) return RT_AI_ERR_INVALID;
    }
    aeg->minimum_interarrival_us = read_u32(blob + arrival->offset);
    aeg->relative_deadline_us = read_u32(blob + arrival->offset + 4U);
    if (aeg->minimum_interarrival_us == 0U || aeg->relative_deadline_us == 0U) return RT_AI_ERR_INVALID;
    aeg->cancel_ack_timeout_us = read_u32(blob + recovery->offset);
    aeg->reset_timeout_us = read_u32(blob + recovery->offset + 4U);
    aeg->reinit_timeout_us = read_u32(blob + recovery->offset + 8U);
    aeg->max_reset_attempts = read_u32(blob + recovery->offset + 12U);
    if (aeg->cancel_ack_timeout_us == 0U || aeg->reset_timeout_us == 0U || aeg->reinit_timeout_us == 0U || aeg->max_reset_attempts == 0U) return RT_AI_ERR_INVALID;
    aeg->input_rank = blob[domain->offset];
    aeg->input_dtype = blob[domain->offset + 1U];
    aeg->input_layout = blob[domain->offset + 2U];
    if (aeg->input_rank == 0U || aeg->input_rank > 4U || aeg->input_dtype == 0U || aeg->input_layout == 0U || blob[domain->offset + 3U] != 0U) return RT_AI_ERR_INVALID;
    for (index = 0U; index < 4U; ++index) aeg->input_shape[index] = read_u32(blob + domain->offset + 4U + (size_t)index * 4U);
    aeg->input_bytes = read_u32(blob + domain->offset + 20U);
    aeg->output_bytes = read_u32(blob + domain->offset + 24U);
    if (aeg->input_bytes == 0U || aeg->output_bytes == 0U) return RT_AI_ERR_INVALID;
    for (index = 0U; index < reservations->count; ++index) {
        const uint8_t *record = blob + reservations->offset + (size_t)index * 16U;
        uint8_t resource = record[0];
        if (resource >= RT_AI_MAX_RESOURCES || record[1] != 0U || record[2] != 0U || record[3] != 0U ||
            read_u32(record + 4U) == 0U || read_u32(record + 8U) == 0U || read_u32(record + 12U) != 0U ||
            aeg->reservation_period_us[resource] != 0U) return RT_AI_ERR_INVALID;
        aeg->reservation_budget_us[resource] = read_u32(record + 4U);
        aeg->reservation_period_us[resource] = read_u32(record + 8U);
    }
    aeg->segments = aeg->storage;
    aeg->deployable = 1U;
    return RT_AI_OK;
}

int rt_ai_load(const void *blob, size_t size, rt_ai_aeg_t *aeg)
{
    const uint8_t *bytes = (const uint8_t *)blob;
    if (blob == NULL || aeg == NULL || size < 4U) return RT_AI_ERR_INVALID;
    if (read_u32(bytes) == RT_AI_AEG_MAGIC) return load_v1(bytes, size, aeg);
    if (read_u32(bytes) == RT_AI_AEG_V2_MAGIC) return load_v2(bytes, size, aeg);
    return RT_AI_ERR_INVALID;
}

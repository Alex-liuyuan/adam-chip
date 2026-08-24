#include "rt_ai_internal.h"

int rt_ai_arena_probe(const rt_ai_runtime_t *runtime, size_t size, rt_ai_arena_lease_t *lease, uint32_t *generation)
{
    size_t candidate = 0U;
    uint16_t slot;
    uint16_t index;
    if (runtime == NULL || lease == NULL || generation == NULL || size == 0U || size > runtime->arena_size) return RT_AI_ERR_INVALID;
    for (;;) {
        size_t next = runtime->arena_size;
        int overlap = 0;
        for (index = 0U; index < RT_AI_MAX_LEASES; ++index) {
            const rt_ai_arena_lease_t *current = &runtime->leases[index];
            if (!current->used) continue;
            if (candidate < current->offset + current->size && current->offset < candidate + size) {
                candidate = current->offset + current->size;
                overlap = 1;
                break;
            }
            if (current->offset >= candidate && current->offset < next) next = current->offset;
        }
        if (overlap) continue;
        if (candidate + size <= next && candidate + size <= runtime->arena_size) break;
        return RT_AI_ERR_RESOURCE;
    }
    for (slot = 0U; slot < RT_AI_MAX_LEASES; ++slot) if (!runtime->leases[slot].used) break;
    if (slot == RT_AI_MAX_LEASES) return RT_AI_ERR_RESOURCE;
    lease->offset = candidate;
    lease->size = size;
    lease->used = 0U;
    *generation = runtime->lease_generation;
    return RT_AI_OK;
}

int rt_ai_arena_commit(rt_ai_runtime_t *runtime, rt_ai_arena_lease_t *lease, uint32_t generation)
{
    uint16_t slot;
    uint16_t index;
    if (runtime == NULL || lease == NULL || lease->used || generation != runtime->lease_generation) return RT_AI_BUSY;
    for (index = 0U; index < RT_AI_MAX_LEASES; ++index) {
        const rt_ai_arena_lease_t *current = &runtime->leases[index];
        if (current->used && lease->offset < current->offset + current->size && current->offset < lease->offset + lease->size) return RT_AI_BUSY;
    }
    for (slot = 0U; slot < RT_AI_MAX_LEASES; ++slot) if (!runtime->leases[slot].used) {
        lease->used = 1U;
        runtime->leases[slot] = *lease;
        ++runtime->lease_generation;
        return RT_AI_OK;
    }
    return RT_AI_ERR_RESOURCE;
}

int rt_ai_arena_lease(rt_ai_runtime_t *runtime, size_t size, rt_ai_arena_lease_t *lease)
{
    uint32_t generation;
    unsigned long level = rt_ai_port_lock();
    int status = rt_ai_arena_probe(runtime, size, lease, &generation);
    if (status == RT_AI_OK) status = rt_ai_arena_commit(runtime, lease, generation);
    rt_ai_port_unlock(level);
    return status;
}

void rt_ai_arena_release(rt_ai_runtime_t *runtime, rt_ai_arena_lease_t *lease)
{
    uint16_t index;
    if (runtime == NULL || lease == NULL || !lease->used) return;
    for (index = 0U; index < RT_AI_MAX_LEASES; ++index) {
        if (runtime->leases[index].used && runtime->leases[index].offset == lease->offset && runtime->leases[index].size == lease->size) {
            runtime->leases[index].used = 0U;
            ++runtime->lease_generation;
            break;
        }
    }
    lease->used = 0U;
}

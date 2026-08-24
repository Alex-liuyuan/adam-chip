#include "rvaic.h"

#include <stdint.h>
#include <string.h>

typedef struct
{
    uint8_t *base;
    size_t size;
    uint32_t next_id;
    rvaic_arena_reservation_t reservations[RVAIC_MAX_ARENA_RESERVATIONS];
} arena_pool_t;

static arena_pool_t g_pool;

static size_t align_up(size_t value, size_t alignment)
{
    if (alignment == 0u)
    {
        alignment = sizeof(void *);
    }
    return (value + alignment - 1u) & ~(alignment - 1u);
}

static int overlaps(size_t left_start, size_t left_size, const rvaic_arena_reservation_t *right)
{
    size_t left_end = left_start + left_size;
    size_t right_start = right->offset;
    size_t right_end = right->offset + right->size;

    return left_start < right_end && right_start < left_end;
}

static int store_reservation(size_t offset, size_t size, uint32_t exclusive, rvaic_arena_reservation_t *reservation)
{
    for (int i = 0; i < RVAIC_MAX_ARENA_RESERVATIONS; i++)
    {
        if (!g_pool.reservations[i].in_use)
        {
            g_pool.reservations[i].id = g_pool.next_id++;
            g_pool.reservations[i].offset = offset;
            g_pool.reservations[i].size = size;
            g_pool.reservations[i].exclusive = exclusive ? 1u : 0u;
            g_pool.reservations[i].in_use = 1;
            *reservation = g_pool.reservations[i];
            return 0;
        }
    }
    return RVAIC_STATUS_QUEUE_FULL;
}

int rvaic_arena_pool_init(void *arena, size_t size)
{
    if (!arena || size == 0u)
    {
        return -1;
    }
    memset(&g_pool, 0, sizeof(g_pool));
    g_pool.base = (uint8_t *)arena;
    g_pool.size = size;
    g_pool.next_id = 1u;
    return 0;
}

int rvaic_arena_pool_ready(void)
{
    return g_pool.base != 0;
}

int rvaic_arena_reserve(size_t size, size_t alignment, uint32_t exclusive, rvaic_arena_reservation_t *reservation)
{
    size_t offset;

    if (!g_pool.base || size == 0u || !reservation)
    {
        return -1;
    }
    if (alignment == 0u)
    {
        alignment = sizeof(void *);
    }
    if ((alignment & (alignment - 1u)) != 0u)
    {
        return -1;
    }

    offset = align_up(0u, alignment);
    while (offset <= g_pool.size && size <= g_pool.size - offset)
    {
        int moved = 0;
        for (int i = 0; i < RVAIC_MAX_ARENA_RESERVATIONS; i++)
        {
            if (g_pool.reservations[i].in_use && overlaps(offset, size, &g_pool.reservations[i]))
            {
                offset = align_up(g_pool.reservations[i].offset + g_pool.reservations[i].size, alignment);
                moved = 1;
                break;
            }
        }
        if (!moved)
        {
            for (int i = 0; i < RVAIC_MAX_ARENA_RESERVATIONS; i++)
            {
                if (!g_pool.reservations[i].in_use)
                {
                    return store_reservation(offset, size, exclusive, reservation);
                }
            }
            return RVAIC_STATUS_QUEUE_FULL;
        }
    }
    return RVAIC_STATUS_NO_RESOURCE;
}

int rvaic_arena_reserve_at(size_t size, size_t alignment, size_t offset, uint32_t exclusive, rvaic_arena_reservation_t *reservation)
{
    if (!g_pool.base || size == 0u || !reservation)
    {
        return -1;
    }
    if (alignment == 0u)
    {
        alignment = sizeof(void *);
    }
    if ((alignment & (alignment - 1u)) != 0u)
    {
        return -1;
    }
    if (offset != align_up(offset, alignment))
    {
        return -1;
    }
    if (offset > g_pool.size || size > g_pool.size - offset)
    {
        return RVAIC_STATUS_NO_RESOURCE;
    }
    for (int i = 0; i < RVAIC_MAX_ARENA_RESERVATIONS; i++)
    {
        if (g_pool.reservations[i].in_use && overlaps(offset, size, &g_pool.reservations[i]))
        {
            return RVAIC_STATUS_NO_RESOURCE;
        }
    }
    return store_reservation(offset, size, exclusive, reservation);
}

int rvaic_arena_release(rvaic_arena_reservation_t *reservation)
{
    if (!reservation || !reservation->in_use)
    {
        return -1;
    }
    for (int i = 0; i < RVAIC_MAX_ARENA_RESERVATIONS; i++)
    {
        if (g_pool.reservations[i].in_use && g_pool.reservations[i].id == reservation->id)
        {
            memset(&g_pool.reservations[i], 0, sizeof(g_pool.reservations[i]));
            memset(reservation, 0, sizeof(*reservation));
            return 0;
        }
    }
    return -1;
}

size_t rvaic_arena_pool_size(void)
{
    return g_pool.size;
}

size_t rvaic_arena_pool_available(void)
{
    size_t used = 0u;

    if (!g_pool.base)
    {
        return 0u;
    }
    for (int i = 0; i < RVAIC_MAX_ARENA_RESERVATIONS; i++)
    {
        if (g_pool.reservations[i].in_use)
        {
            used += g_pool.reservations[i].size;
        }
    }
    if (used >= g_pool.size)
    {
        return 0u;
    }
    return g_pool.size - used;
}

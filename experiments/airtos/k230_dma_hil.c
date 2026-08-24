#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "k_gsdma_comm.h"
#include "mpi_gsdma_api.h"
#include "mpi_sys_api.h"

#define NEGATIVE_CASES 100U
#define TIMEOUT_MS 1000

typedef struct {
    k_u64 physical;
    uint8_t *virtual;
} buffer_t;

static volatile uint32_t cache_probe_sink;

static uint64_t now_ns(void)
{
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) return 0U;
    return (uint64_t)value.tv_sec * UINT64_C(1000000000) + (uint64_t)value.tv_nsec;
}

static void pattern(uint8_t *data, size_t size, uint32_t seed)
{
    size_t index;
    uint32_t value = seed | 1U;
    for (index = 0U; index < size; ++index) {
        value = value * UINT32_C(1664525) + UINT32_C(1013904223);
        data[index] = (uint8_t)(value >> 24U);
    }
}

static int transfer(const buffer_t *source, const buffer_t *destination, size_t size)
{
    k_sdma_memcpy_t request;
    memset(&request, 0, sizeof(request));
    request.src_phys_addr = source->physical;
    request.dst_phys_addr = destination->physical;
    request.size = size;
    request.timeout_ms = TIMEOUT_MS;
    return kd_mpi_gsdma_sdma_memcpy(&request) == K_SUCCESS;
}

static int allocate(buffer_t *buffer, const char *name, size_t size)
{
    void *address = NULL;
    if (kd_mpi_sys_mmz_alloc_cached(&buffer->physical, &address, name, NULL, (k_u32)size) != K_SUCCESS || address == NULL)
        return 0;
    buffer->virtual = address;
    return 1;
}

static void release(buffer_t *buffer)
{
    if (buffer->virtual != NULL) (void)kd_mpi_sys_mmz_free(buffer->physical, buffer->virtual);
    buffer->virtual = NULL;
}

static int negative_clean(buffer_t *source, buffer_t *destination, size_t size, uint32_t seed)
{
    memset(source->virtual, 0, size);
    memset(destination->virtual, 0, size);
    if (kd_mpi_sys_mmz_flush_cache(source->physical, source->virtual, (k_u32)size) != K_SUCCESS ||
        kd_mpi_sys_mmz_flush_cache(destination->physical, destination->virtual, (k_u32)size) != K_SUCCESS) return -1;
    pattern(source->virtual, size, seed);
    if (!transfer(source, destination, size) ||
        kd_mpi_sys_mmz_invalidate_cache(destination->physical, destination->virtual, (k_u32)size) != K_SUCCESS) return -1;
    return memcmp(source->virtual, destination->virtual, size) != 0;
}

static int negative_invalidate(buffer_t *source, buffer_t *destination, size_t size, uint32_t seed)
{
    size_t offset;
    uint32_t cached = 0U;
    pattern(source->virtual, size, seed);
    memset(destination->virtual, 0xA5, size);
    if (kd_mpi_sys_mmz_flush_cache(source->physical, source->virtual, (k_u32)size) != K_SUCCESS ||
        kd_mpi_sys_mmz_flush_cache(destination->physical, destination->virtual, (k_u32)size) != K_SUCCESS) return -1;
    for (offset = 0U; offset < size; offset += 64U) cached += destination->virtual[offset];
    cached += destination->virtual[size - 1U];
    cache_probe_sink = cached;
    if (!transfer(source, destination, size)) return -1;
    return memcmp(source->virtual, destination->virtual, size) != 0;
}

int main(int argc, char **argv)
{
    uint64_t repetitions = argc > 1 ? strtoull(argv[1], NULL, 10) : UINT64_C(1000000);
    size_t size = argc > 2 ? (size_t)strtoul(argv[2], NULL, 10) : 256U;
    buffer_t source = {0}, destination = {0};
    k_gsdma_dev_attr_t attributes;
    uint64_t started, elapsed, failures = 0U, iteration;
    unsigned clean_detected = 0U, invalidate_detected = 0U, negative_errors = 0U, index;
    int status = 1;
    if (repetitions == 0U || size < 64U || size > 1024U * 1024U) return 2;
    if (!allocate(&source, "airtos_dma_src", size) || !allocate(&destination, "airtos_dma_dst", size)) goto done;
    if (kd_mpi_gsdma_init() != K_SUCCESS) goto done;
    memset(&attributes, 0, sizeof(attributes));
    attributes.outstanding = 7U;
    attributes.ckg_bypass = 0xFFU;
    attributes.arbitration_weight = UINT32_C(0x444210);
    if (kd_mpi_gsdma_set_dev_attr(&attributes) != K_SUCCESS) goto deinit;
    for (index = 0U; index < NEGATIVE_CASES; ++index) {
        int observed = negative_clean(&source, &destination, size, UINT32_C(0xC1000000) + index);
        if (observed < 0) ++negative_errors;
        else clean_detected += (unsigned)observed;
        observed = negative_invalidate(&source, &destination, size, UINT32_C(0x1A000000) + index);
        if (observed < 0) ++negative_errors;
        else invalidate_detected += (unsigned)observed;
    }
    printf("AIRTOS_K230_DMA_NEGATIVE cases=%u omit_clean_detected=%u omit_invalidate_detected=%u errors=%u\n",
        NEGATIVE_CASES, clean_detected, invalidate_detected, negative_errors);
    started = now_ns();
    for (iteration = 0U; iteration < repetitions; ++iteration) {
        pattern(source.virtual, size, (uint32_t)iteration ^ UINT32_C(0xA17A2026));
        memset(destination.virtual, 0, size);
        if (kd_mpi_sys_mmz_flush_cache(source.physical, source.virtual, (k_u32)size) != K_SUCCESS ||
            kd_mpi_sys_mmz_flush_cache(destination.physical, destination.virtual, (k_u32)size) != K_SUCCESS ||
            !transfer(&source, &destination, size) ||
            kd_mpi_sys_mmz_invalidate_cache(destination.physical, destination.virtual, (k_u32)size) != K_SUCCESS ||
            memcmp(source.virtual, destination.virtual, size) != 0) {
            ++failures;
            if (failures <= 5U) printf("AIRTOS_K230_DMA_MISMATCH iteration=%" PRIu64 "\n", iteration);
        }
    }
    elapsed = now_ns() - started;
    printf("AIRTOS_K230_DMA cases=%" PRIu64 " size=%zu failures=%" PRIu64
           " elapsed_ns=%" PRIu64 " mean_ns=%" PRIu64 "\n",
        repetitions, size, failures, elapsed, elapsed / repetitions);
    if (negative_errors == 0U && clean_detected != 0U && invalidate_detected != 0U && failures == 0U) {
        puts("AIRTOS_K230_DMA_PASS");
        status = 0;
    } else if (failures == 0U) {
        puts("AIRTOS_K230_DMA_NEGATIVE_NOT_OBSERVABLE");
    } else {
        puts("AIRTOS_K230_DMA_FAIL");
    }
deinit:
    (void)kd_mpi_gsdma_deinit();
done:
    release(&destination);
    release(&source);
    return status;
}

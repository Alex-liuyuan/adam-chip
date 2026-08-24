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

typedef struct {
    k_u64 physical;
    uint8_t *virtual;
} buffer_t;

static uint64_t now_ns(void)
{
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) return 0U;
    return (uint64_t)value.tv_sec * UINT64_C(1000000000) + (uint64_t)value.tv_nsec;
}

static int compare_u64(const void *left, const void *right)
{
    uint64_t a = *(const uint64_t *)left, b = *(const uint64_t *)right;
    return (a > b) - (a < b);
}

static void pattern(uint8_t *data, size_t size, uint32_t seed)
{
    size_t index;
    for (index = 0U; index < size; ++index) {
        seed = seed * UINT32_C(1664525) + UINT32_C(1013904223);
        data[index] = (uint8_t)(seed >> 24U);
    }
}

static int allocate(buffer_t *buffer, const char *name, size_t size)
{
    void *address = NULL;
    if (kd_mpi_sys_mmz_alloc_cached(&buffer->physical, &address, name, NULL, (k_u32)size) != K_SUCCESS || address == NULL)
        return 0;
    buffer->virtual = address;
    return 1;
}

static int configure(void)
{
    k_gsdma_dev_attr_t attributes;
    memset(&attributes, 0, sizeof(attributes));
    attributes.outstanding = 7U;
    attributes.ckg_bypass = 0xFFU;
    attributes.arbitration_weight = UINT32_C(0x444210);
    return kd_mpi_gsdma_init() == K_SUCCESS && kd_mpi_gsdma_set_dev_attr(&attributes) == K_SUCCESS;
}

static int copy(const buffer_t *source, const buffer_t *destination, size_t size)
{
    k_sdma_memcpy_t request;
    memset(&request, 0, sizeof(request));
    request.src_phys_addr = source->physical;
    request.dst_phys_addr = destination->physical;
    request.size = size;
    request.timeout_ms = 1000;
    return kd_mpi_gsdma_sdma_memcpy(&request) == K_SUCCESS;
}

int main(int argc, char **argv)
{
    unsigned repetitions = argc == 2 ? (unsigned)strtoul(argv[1], NULL, 10) : 300U;
    const size_t size = 256U;
    buffer_t source = {0}, destination = {0};
    uint64_t *samples;
    unsigned failures = 0U, iteration;

    if (repetitions == 0U || (samples = calloc(repetitions, sizeof(*samples))) == NULL) return 2;
    if (!allocate(&source, "airtos_lifecycle_src", size) || !allocate(&destination, "airtos_lifecycle_dst", size)) return 2;
    if (!configure()) return 2;
    for (iteration = 0U; iteration < repetitions; ++iteration) {
        uint64_t started = now_ns();
        if (kd_mpi_gsdma_deinit() != K_SUCCESS || !configure()) {
            ++failures;
            continue;
        }
        pattern(source.virtual, size, UINT32_C(0xA1700000) + iteration);
        memset(destination.virtual, 0, size);
        if (kd_mpi_sys_mmz_flush_cache(source.physical, source.virtual, size) != K_SUCCESS ||
            kd_mpi_sys_mmz_flush_cache(destination.physical, destination.virtual, size) != K_SUCCESS ||
            !copy(&source, &destination, size) ||
            kd_mpi_sys_mmz_invalidate_cache(destination.physical, destination.virtual, size) != K_SUCCESS ||
            memcmp(source.virtual, destination.virtual, size) != 0) ++failures;
        samples[iteration] = now_ns() - started;
    }
    (void)kd_mpi_gsdma_deinit();
    (void)kd_mpi_sys_mmz_free(destination.physical, destination.virtual);
    (void)kd_mpi_sys_mmz_free(source.physical, source.virtual);
    qsort(samples, repetitions, sizeof(samples[0]), compare_u64);
    printf("AIRTOS_K230_GSDMA_LIFECYCLE cases=%u failures=%u median_ns=%" PRIu64
           " p95_ns=%" PRIu64 " p99_ns=%" PRIu64 " max_ns=%" PRIu64 "\n",
        repetitions, failures, samples[repetitions / 2U], samples[(repetitions * 95U) / 100U],
        samples[(repetitions * 99U) / 100U], samples[repetitions - 1U]);
    free(samples);
    if (failures == 0U) {
        puts("AIRTOS_K230_GSDMA_LIFECYCLE_PASS");
        return 0;
    }
    puts("AIRTOS_K230_GSDMA_LIFECYCLE_FAIL");
    return 1;
}

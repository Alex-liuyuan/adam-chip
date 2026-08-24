#define _POSIX_C_SOURCE 200809L

#include <fcntl.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "k_gsdma_comm.h"
#include "mpi_gsdma_api.h"
#include "mpi_sys_api.h"

#define MAX_TRANSFER_SIZE 65536U

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

static void emit(FILE *log, const char *format, ...)
{
    va_list arguments;
    va_start(arguments, format);
    vprintf(format, arguments);
    va_end(arguments);
    fflush(stdout);
    if (log != NULL) {
        va_start(arguments, format);
        vfprintf(log, format, arguments);
        va_end(arguments);
        fflush(log);
    }
}

static void pattern(uint8_t *data, size_t size, uint32_t seed)
{
    size_t index;
    for (index = 0U; index < size; ++index) {
        seed = seed * UINT32_C(1664525) + UINT32_C(1013904223);
        data[index] = (uint8_t)(seed >> 24U);
    }
}

static int allocate(buffer_t *buffer, const char *name)
{
    void *address = NULL;
    if (kd_mpi_sys_mmz_alloc_cached(&buffer->physical, &address, name, NULL, MAX_TRANSFER_SIZE) != K_SUCCESS || address == NULL)
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

static int transfer(const buffer_t *source, const buffer_t *destination, size_t size)
{
    k_sdma_memcpy_t request;
    memset(&request, 0, sizeof(request));
    request.src_phys_addr = source->physical;
    request.dst_phys_addr = destination->physical;
    request.size = size;
    request.timeout_ms = 1000;
    return kd_mpi_gsdma_sdma_memcpy(&request) == K_SUCCESS;
}

static double temperature(void)
{
    static int descriptor = -1;
    double value = -273.15;
    if (descriptor < 0) descriptor = open("/dev/ts", O_RDWR);
    if (descriptor >= 0 && read(descriptor, &value, sizeof(value)) == (ssize_t)sizeof(value)) return value;
    return -273.15;
}

int main(int argc, char **argv)
{
    static const size_t sizes[] = {64U, 256U, 4096U, 65536U};
    uint64_t duration_seconds = argc > 1 ? strtoull(argv[1], NULL, 10) : UINT64_C(86400);
    uint64_t minimum_jobs = argc > 2 ? strtoull(argv[2], NULL, 10) : UINT64_C(1000000);
    uint64_t heartbeat_jobs = argc > 3 ? strtoull(argv[3], NULL, 10) : UINT64_C(100000);
    const char *log_path = argc > 4 ? argv[4] : "/sdcard/airtos/long_hil.log";
    buffer_t source = {0}, destination = {0};
    FILE *log = fopen(log_path, "w");
    uint64_t started = now_ns(), jobs = 0U, data_failures = 0U, device_failures = 0U, lifecycle_failures = 0U;

    if (duration_seconds == 0U || minimum_jobs == 0U || heartbeat_jobs == 0U || log == NULL) return 2;
    if (!allocate(&source, "airtos_long_src") || !allocate(&destination, "airtos_long_dst") || !configure()) return 2;
    emit(log, "AIRTOS_K230_LONG_START duration_seconds=%" PRIu64 " minimum_jobs=%" PRIu64
        " heartbeat_jobs=%" PRIu64 " temperature_c=%.3f\n", duration_seconds, minimum_jobs, heartbeat_jobs, temperature());
    while ((now_ns() - started) / UINT64_C(1000000000) < duration_seconds || jobs < minimum_jobs) {
        size_t size = sizes[jobs % (sizeof(sizes) / sizeof(sizes[0]))];
        pattern(source.virtual, size, (uint32_t)jobs ^ UINT32_C(0xA17A2026));
        memset(destination.virtual, 0, size);
        if (kd_mpi_sys_mmz_flush_cache(source.physical, source.virtual, (k_u32)size) != K_SUCCESS ||
            kd_mpi_sys_mmz_flush_cache(destination.physical, destination.virtual, (k_u32)size) != K_SUCCESS ||
            !transfer(&source, &destination, size) ||
            kd_mpi_sys_mmz_invalidate_cache(destination.physical, destination.virtual, (k_u32)size) != K_SUCCESS) {
            ++device_failures;
        } else if (memcmp(source.virtual, destination.virtual, size) != 0) {
            ++data_failures;
        }
        ++jobs;
        if (jobs % UINT64_C(100000) == 0U) {
            if (kd_mpi_gsdma_deinit() != K_SUCCESS || !configure()) ++lifecycle_failures;
        }
        if (jobs % heartbeat_jobs == 0U) {
            emit(log, "AIRTOS_K230_LONG_HEARTBEAT elapsed_seconds=%" PRIu64 " jobs=%" PRIu64
                " data_failures=%" PRIu64 " device_failures=%" PRIu64 " lifecycle_failures=%" PRIu64
                " temperature_c=%.3f\n", (now_ns() - started) / UINT64_C(1000000000), jobs,
                data_failures, device_failures, lifecycle_failures, temperature());
        }
    }
    emit(log, "AIRTOS_K230_LONG_RESULT elapsed_seconds=%" PRIu64 " jobs=%" PRIu64
        " data_failures=%" PRIu64 " device_failures=%" PRIu64 " lifecycle_failures=%" PRIu64
        " temperature_c=%.3f\n", (now_ns() - started) / UINT64_C(1000000000), jobs,
        data_failures, device_failures, lifecycle_failures, temperature());
    if (data_failures == 0U && device_failures == 0U && lifecycle_failures == 0U) emit(log, "AIRTOS_K230_LONG_PASS\n");
    else emit(log, "AIRTOS_K230_LONG_FAIL\n");
    (void)kd_mpi_gsdma_deinit();
    (void)kd_mpi_sys_mmz_free(destination.physical, destination.virtual);
    (void)kd_mpi_sys_mmz_free(source.physical, source.virtual);
    fclose(log);
    return data_failures == 0U && device_failures == 0U && lifecycle_failures == 0U ? 0 : 1;
}

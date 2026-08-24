#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "tvm/ffi/c_api.h"

#define BATCHES 30U
#define SAMPLES 1000U
#define WARMUPS 10U

extern int32_t __tvm_ffi_main(void *self, void *args, int32_t num_args, void *result);

void TVMFFIErrorSetRaisedFromCStrParts(const char *kind, const char **parts, int32_t count)
{
    int32_t index;
    fprintf(stderr, "%s: ", kind);
    for (index = 0; index < count; ++index) if (parts[index] != NULL) fputs(parts[index], stderr);
    fputc('\n', stderr);
}

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

static int output_is_correct(const float output[8])
{
    static const float expected[8] = {0.0f, 0.0f, 0.0f, 2.0f, 4.0f, 6.0f, 8.0f, 10.0f};
    return memcmp(output, expected, sizeof(expected)) == 0;
}

int main(void)
{
    float input[8] = {-4.0f, -3.0f, -2.0f, -1.0f, 0.0f, 1.0f, 2.0f, 3.0f};
    float constant[8] = {0.0f, 1.0f, 2.0f, 3.0f, 4.0f, 5.0f, 6.0f, 7.0f};
    float output[8] = {0};
#ifdef RVV_MODEL
    int64_t shape[1] = {8};
    const int dimensions = 1;
    const char *model = "rvv";
#else
    int64_t shape[2] = {1, 8};
    const int dimensions = 2;
    const char *model = "cpu";
#endif
    DLTensor tensors[3];
    TVMFFIAny arguments[3], result;
    uint64_t samples[SAMPLES];
    unsigned batch, sample, failures = 0U;
    int index;

    memset(tensors, 0, sizeof(tensors));
    memset(arguments, 0, sizeof(arguments));
    memset(&result, 0, sizeof(result));
    for (index = 0; index < 3; ++index) {
        tensors[index].device.device_type = kDLCPU;
        tensors[index].dtype.code = kDLFloat;
        tensors[index].dtype.bits = 32;
        tensors[index].dtype.lanes = 1;
        tensors[index].ndim = dimensions;
        tensors[index].shape = shape;
        arguments[index].type_index = 0;
        arguments[index].v_ptr = &tensors[index];
    }
    tensors[0].data = input;
    tensors[1].data = constant;
    tensors[2].data = output;
    for (sample = 0U; sample < WARMUPS; ++sample)
        if (__tvm_ffi_main(NULL, arguments, 3, &result) != 0) return 2;
    puts("model,batch,samples,median_ns,p95_ns,p99_ns,max_ns,failures");
    for (batch = 0U; batch < BATCHES; ++batch) {
        memset(output, 0, sizeof(output));
        for (sample = 0U; sample < SAMPLES; ++sample) {
            uint64_t started = now_ns();
            int status = __tvm_ffi_main(NULL, arguments, 3, &result);
            samples[sample] = now_ns() - started;
            if (status != 0) ++failures;
        }
        if (!output_is_correct(output)) ++failures;
        qsort(samples, SAMPLES, sizeof(samples[0]), compare_u64);
        printf("%s,%u,%u,%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%u\n",
            model, batch, SAMPLES, samples[500], samples[949], samples[989], samples[999], failures);
    }
    printf("AIRTOS_K230_AOT model=%s cases=%u failures=%u\n", model, BATCHES * SAMPLES, failures);
    if (failures == 0U) {
        puts("AIRTOS_K230_AOT_PASS");
        return 0;
    }
    puts("AIRTOS_K230_AOT_FAIL");
    return 1;
}

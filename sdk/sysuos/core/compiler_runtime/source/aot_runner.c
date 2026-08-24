#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "tvm/ffi/c_api.h"

extern int32_t __tvm_ffi_main(void *self, void *args, int32_t num_args, void *result);

void TVMFFIErrorSetRaisedFromCStrParts(const char *kind, const char **parts, int32_t count)
{
    int32_t index;
    fprintf(stderr, "%s: ", kind);
    for (index = 0; index < count; ++index) if (parts[index] != NULL) fputs(parts[index], stderr);
    fputc('\n', stderr);
}

int main(void)
{
    float input[8] = {-4.0f, -3.0f, -2.0f, -1.0f, 0.0f, 1.0f, 2.0f, 3.0f};
    float constant[8] = {0.0f, 1.0f, 2.0f, 3.0f, 4.0f, 5.0f, 6.0f, 7.0f};
    float output[8] = {0};
    int64_t shape_1d[1] = {8};
    int64_t shape_2d[2] = {1, 8};
    DLTensor tensors[3];
    TVMFFIAny args[3];
    TVMFFIAny result;
    int index;
    memset(tensors, 0, sizeof(tensors));
    memset(args, 0, sizeof(args));
    memset(&result, 0, sizeof(result));
    for (index = 0; index < 3; ++index) {
        tensors[index].device.device_type = kDLCPU;
        tensors[index].device.device_id = 0;
        tensors[index].dtype.code = kDLFloat;
        tensors[index].dtype.bits = 32;
        tensors[index].dtype.lanes = 1;
#ifdef RVV_MODEL
        tensors[index].ndim = 1;
        tensors[index].shape = shape_1d;
#else
        tensors[index].ndim = 2;
        tensors[index].shape = shape_2d;
#endif
        args[index].type_index = 0;
        args[index].v_ptr = &tensors[index];
    }
    tensors[0].data = input;
    tensors[1].data = constant;
    tensors[2].data = output;
    if (__tvm_ffi_main(NULL, args, 3, &result) != 0) return 2;
    fputs("OUTPUT", stdout);
    for (index = 0; index < 8; ++index) printf(" %.9g", output[index]);
    fputc('\n', stdout);
    return 0;
}

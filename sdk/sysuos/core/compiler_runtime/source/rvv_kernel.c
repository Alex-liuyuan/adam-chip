#include <stddef.h>

int soc_image_rvv_add_relu(const float *input, const float *constant, float *output, size_t count)
{
    const float zero = 0.0f;
    while (count != 0U) {
        size_t vl;
        __asm__ volatile(
            "vsetvli %0,%4,e32,m1,ta,ma\n\t"
            "vle32.v v0,(%1)\n\t"
            "vle32.v v1,(%2)\n\t"
            "vfadd.vv v2,v0,v1\n\t"
            "vfmax.vf v2,v2,%5\n\t"
            "vse32.v v2,(%3)"
            : "=&r"(vl)
            : "r"(input), "r"(constant), "r"(output), "r"(count), "f"(zero)
            : "v0", "v1", "v2", "memory");
        input += vl;
        constant += vl;
        output += vl;
        count -= vl;
    }
    return 0;
}

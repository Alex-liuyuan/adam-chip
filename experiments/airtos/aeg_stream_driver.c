#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "rt_ai.h"

int main(void)
{
    uint32_t size;
    uint64_t index = 0U;
    while (fread(&size, sizeof(size), 1U, stdin) == 1U) {
        uint8_t *blob;
        rt_ai_aeg_t aeg;
        int status;
        if (size == 0U || size > UINT32_C(1048576)) return 2;
        blob = (uint8_t *)malloc(size);
        if (blob == NULL) return 3;
        if (fread(blob, 1U, size, stdin) != size) { free(blob); return 4; }
        status = rt_ai_load(blob, size, &aeg);
        free(blob);
        printf("%" PRIu64 " %d\n", index++, status);
    }
    return ferror(stdin) ? 5 : 0;
}

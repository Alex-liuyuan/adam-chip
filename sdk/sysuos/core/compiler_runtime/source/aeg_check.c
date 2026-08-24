#include <stdio.h>
#include <stdlib.h>
#include "rt_ai.h"

int main(int argc, char **argv)
{
    unsigned char buffer[4096];
    rt_ai_aeg_t aeg;
    FILE *stream;
    size_t size;
    if (argc != 2) return 2;
    stream = fopen(argv[1], "rb");
    if (stream == NULL) return 3;
    size = fread(buffer, 1, sizeof(buffer), stream);
    fclose(stream);
    if (rt_ai_load(buffer, size, &aeg) != RT_AI_OK) return 4;
    printf("AEG_RUNTIME_PASS segments=%u arena=%u\n", aeg.header.segment_count, aeg.header.arena_size);
    return 0;
}

#include <stddef.h>

void *memset(void *destination, int value, size_t size)
{
    unsigned char *bytes = (unsigned char *)destination;
    while (size-- != 0U) *bytes++ = (unsigned char)value;
    return destination;
}

void *memcpy(void *destination, const void *source, size_t size)
{
    unsigned char *out = (unsigned char *)destination;
    const unsigned char *in = (const unsigned char *)source;
    while (size-- != 0U) *out++ = *in++;
    return destination;
}

int memcmp(const void *left, const void *right, size_t size)
{
    const unsigned char *a = (const unsigned char *)left;
    const unsigned char *b = (const unsigned char *)right;
    while (size-- != 0U) {
        if (*a != *b) return (int)*a - (int)*b;
        ++a;
        ++b;
    }
    return 0;
}

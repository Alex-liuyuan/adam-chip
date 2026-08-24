#include <stdatomic.h>
#include <time.h>
#include <stdint.h>

/* ponytail: process-wide lock; move it into rt_ai_runtime_t if host contention becomes material. */
static atomic_flag rt_ai_host_lock = ATOMIC_FLAG_INIT;

unsigned long rt_ai_port_lock(void)
{
    while (atomic_flag_test_and_set_explicit(&rt_ai_host_lock, memory_order_acquire)) { }
    return 0UL;
}

void rt_ai_port_unlock(unsigned long level)
{
    (void)level;
    atomic_flag_clear_explicit(&rt_ai_host_lock, memory_order_release);
}
uint64_t rt_ai_port_now_us(void)
{
    struct timespec value;
    (void)timespec_get(&value, TIME_UTC);
    return (uint64_t)value.tv_sec * UINT64_C(1000000) + (uint64_t)value.tv_nsec / 1000U;
}

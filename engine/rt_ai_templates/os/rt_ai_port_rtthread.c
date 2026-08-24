#include <rtthread.h>

unsigned long rt_ai_port_lock(void)
{
    return (unsigned long)rt_hw_interrupt_disable();
}

void rt_ai_port_unlock(unsigned long level)
{
    rt_hw_interrupt_enable((rt_base_t)level);
}

uint64_t rt_ai_port_now_us(void)
{
    return (uint64_t)rt_tick_get() * UINT64_C(1000000) / RT_TICK_PER_SECOND;
}

#include <stddef.h>
#include <stdint.h>

#include "rt_ai.h"

#ifndef MACHINE_NAME
#define MACHINE_NAME "unknown"
#endif

extern uint32_t _stack_top;
extern uint32_t _sidata;
extern uint32_t _sdata;
extern uint32_t _edata;
extern uint32_t _sbss;
extern uint32_t _ebss;

void reset_handler(void);
static void default_handler(void);

__attribute__((section(".isr_vector"), used))
static void (*const vectors[])(void) = {
    (void (*)(void))&_stack_top,
    reset_handler,
    default_handler, default_handler, default_handler, default_handler,
    default_handler, default_handler, default_handler, default_handler,
    default_handler, default_handler, default_handler, default_handler,
    default_handler, default_handler
};

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

static int semihost(unsigned operation, const void *argument)
{
    register unsigned r0 __asm("r0") = operation;
    register const void *r1 __asm("r1") = argument;
    __asm volatile("bkpt 0xab" : "+r"(r0) : "r"(r1) : "memory");
    return (int)r0;
}

static void write0(const char *text) { (void)semihost(4U, text); }

__attribute__((noreturn)) static void finish(unsigned status)
{
    uint32_t arguments[2] = {UINT32_C(0x20026), status};
    (void)semihost(0x20U, arguments);
    for (;;) { }
}

unsigned long rt_ai_port_lock(void)
{
    unsigned long state;
    __asm volatile("mrs %0, primask\ncpsid i" : "=r"(state) :: "memory");
    return state;
}

void rt_ai_port_unlock(unsigned long state)
{
    __asm volatile("msr primask, %0" :: "r"(state) : "memory");
}

uint64_t rt_ai_port_now_us(void)
{
    static uint64_t logical_time;
    return ++logical_time;
}

typedef struct {
    float input[8];
    float constant[8];
    float output[8];
    uint32_t epoch;
    uint32_t cookie;
    unsigned submissions;
} provider_state_t;

static int submit(void *opaque, const rt_ai_aeg_segment_t *segment, uint32_t epoch, uint32_t cookie)
{
    provider_state_t *state = (provider_state_t *)opaque;
    unsigned index;
    if (segment->arena_size == 0U) return RT_AI_ERR_PROVIDER;
    for (index = 0U; index < 8U; ++index) {
        float value = state->input[index] + state->constant[index];
        state->output[index] = value > 0.0f ? value : 0.0f;
    }
    state->epoch = epoch;
    state->cookie = cookie;
    ++state->submissions;
    return RT_AI_OK;
}

static int range_action(void *opaque, void *address, size_t size)
{
    (void)opaque;
    return address != NULL && size != 0U ? RT_AI_OK : RT_AI_ERR_PROVIDER;
}

static int barrier(void *opaque)
{
    (void)opaque;
    __asm volatile("dmb" ::: "memory");
    return RT_AI_OK;
}

static int check(int condition, const char *failure)
{
    if (condition) return 1;
    write0("AIRTOS_SYSTEM_MACHINE_FAIL machine=" MACHINE_NAME " check=");
    write0(failure);
    write0("\n");
    return 0;
}

static int probe(void)
{
    static uint8_t arena[128];
    static rt_ai_runtime_t runtime;
    static rt_ai_session_t session;
    static rt_ai_job_t first;
    static rt_ai_job_t second;
    static provider_state_t state;
    static const uint8_t package[] = {
        0x41, 0x45, 0x47, 0x31, 0x01, 0x00, 0x01, 0x00,
        0x40, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x01, 0x00, 0x00, 0x03, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x40, 0x00, 0x00, 0x00
    };
    rt_ai_aeg_t aeg;
    rt_ai_provider_t provider;
    unsigned index;

    if (!check(rt_ai_load(package, sizeof(package), &aeg) == RT_AI_OK, "loader_legal")) return 0;
    if (!check(rt_ai_load(package, sizeof(package) - 1U, &aeg) == RT_AI_ERR_INVALID, "loader_truncated")) return 0;
    if (!check(rt_ai_load(package, sizeof(package), &aeg) == RT_AI_OK, "loader_reload")) return 0;
    aeg.deployable = 1U;

    memset(&provider, 0, sizeof(provider));
    provider.resource = RT_AI_RESOURCE_CPU;
    provider.submit = submit;
    provider.clean_range = range_action;
    provider.invalidate_range = range_action;
    provider.barrier = barrier;
    provider.user = &state;
    for (index = 0U; index < 8U; ++index) {
        state.input[index] = (float)index - 4.0f;
        state.constant[index] = 1.0f;
    }
    if (!check(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK, "runtime_init")) return 0;
    if (!check(rt_ai_provider_register(&runtime, &provider) == RT_AI_OK, "provider_register")) return 0;
    if (!check(rt_ai_session_create(&runtime, &aeg, &session) == RT_AI_OK, "session_create")) return 0;

    runtime.next_cookie[RT_AI_RESOURCE_CPU] = UINT32_MAX;
    if (!check(rt_ai_submit_async(&session, 1U, 100U, &first) == RT_AI_OK, "submit_first")) return 0;
    if (!check(rt_ai_poll(&runtime, 1U) == RT_AI_OK && state.submissions == 1U, "dispatch_first")) return 0;
    if (!check(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, state.epoch - 1U, state.cookie, RT_AI_OK) == RT_AI_ERR_STALE,
               "stale_epoch")) return 0;
    if (!check(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, state.epoch, state.cookie, RT_AI_OK) == RT_AI_OK &&
               rt_ai_wait(&first) == RT_AI_OK, "complete_first")) return 0;
    for (index = 0U; index < 8U; ++index) {
        float expected = state.input[index] + state.constant[index];
        if (expected < 0.0f) expected = 0.0f;
        if (!check(state.output[index] == expected, "add_relu")) return 0;
    }

    if (!check(rt_ai_submit_async(&session, 2U, 100U, &second) == RT_AI_OK, "submit_second")) return 0;
    if (!check(rt_ai_poll(&runtime, 2U) == RT_AI_OK && state.submissions == 2U, "dispatch_second")) return 0;
    if (!check(first.cookie[0] == UINT32_MAX && second.cookie[0] == 1U &&
               runtime.epoch[RT_AI_RESOURCE_CPU] == 2U, "cookie_wrap")) return 0;
    if (!check(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, state.epoch, state.cookie, RT_AI_OK) == RT_AI_OK &&
               rt_ai_wait(&second) == RT_AI_OK, "complete_second")) return 0;
    if (!check(rt_ai_session_destroy(&session) == RT_AI_OK, "session_destroy")) return 0;

    write0("AIRTOS_SYSTEM_MACHINE_PASS machine=" MACHINE_NAME
           " loader=2 inference=2 stale_rejected=1 cookie_wrap=1\n");
    return 1;
}

void reset_handler(void)
{
    uint32_t *source = &_sidata;
    uint32_t *destination;
    for (destination = &_sdata; destination < &_edata; ++destination) *destination = *source++;
    for (destination = &_sbss; destination < &_ebss; ++destination) *destination = 0U;
    finish(probe() ? 0U : 1U);
}

static void default_handler(void) { finish(2U); }

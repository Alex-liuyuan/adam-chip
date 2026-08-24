#include <stdint.h>
#include <string.h>

#include <rtthread.h>
#include "rt_ai.h"

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
    return address != RT_NULL && size != 0U ? RT_AI_OK : RT_AI_ERR_PROVIDER;
}

static int barrier(void *opaque)
{
    (void)opaque;
    __asm volatile("fence iorw, iorw" ::: "memory");
    return RT_AI_OK;
}

static int run_probe(void)
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

#define CHECK(expression, name) do { if (!(expression)) { rt_kprintf("AIRTOS_RTTHREAD_FAIL check=%s\n", name); return 0; } } while (0)
    CHECK(rt_ai_load(package, sizeof(package), &aeg) == RT_AI_OK, "loader_legal");
    CHECK(rt_ai_load(package, sizeof(package) - 1U, &aeg) == RT_AI_ERR_INVALID, "loader_truncated");
    CHECK(rt_ai_load(package, sizeof(package), &aeg) == RT_AI_OK, "loader_reload");
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
    CHECK(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK, "runtime_init");
    CHECK(rt_ai_provider_register(&runtime, &provider) == RT_AI_OK, "provider_register");
    CHECK(rt_ai_session_create(&runtime, &aeg, &session) == RT_AI_OK, "session_create");
    runtime.next_cookie[RT_AI_RESOURCE_CPU] = UINT32_MAX;
    CHECK(rt_ai_submit_async(&session, 1U, 100U, &first) == RT_AI_OK, "submit_first");
    CHECK(rt_ai_poll(&runtime, 1U) == RT_AI_OK && state.submissions == 1U, "dispatch_first");
    CHECK(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, state.epoch - 1U, state.cookie, RT_AI_OK) == RT_AI_ERR_STALE,
          "stale_epoch");
    CHECK(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, state.epoch, state.cookie, RT_AI_OK) == RT_AI_OK &&
          rt_ai_wait(&first) == RT_AI_OK, "complete_first");
    for (index = 0U; index < 8U; ++index) {
        float expected = state.input[index] + state.constant[index];
        if (expected < 0.0f) expected = 0.0f;
        CHECK(state.output[index] == expected, "add_relu");
    }
    CHECK(rt_ai_submit_async(&session, 2U, 100U, &second) == RT_AI_OK, "submit_second");
    CHECK(rt_ai_poll(&runtime, 2U) == RT_AI_OK && state.submissions == 2U, "dispatch_second");
    CHECK(first.cookie[0] == UINT32_MAX && second.cookie[0] == 1U &&
          runtime.epoch[RT_AI_RESOURCE_CPU] == 2U, "cookie_wrap");
    CHECK(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, state.epoch, state.cookie, RT_AI_OK) == RT_AI_OK &&
          rt_ai_wait(&second) == RT_AI_OK, "complete_second");
    CHECK(rt_ai_session_destroy(&session) == RT_AI_OK, "session_destroy");
#undef CHECK
    return 1;
}

int main(void)
{
    int passed = run_probe();
    if (passed) rt_kprintf("AIRTOS_RTTHREAD_PASS machine=virt64 loader=2 inference=2 stale_rejected=1 cookie_wrap=1\n");
    *(volatile uint32_t *)(uintptr_t)UINT32_C(0x00100000) = passed ? UINT32_C(0x5555) : UINT32_C(0x3333);
    for (;;) { }
}

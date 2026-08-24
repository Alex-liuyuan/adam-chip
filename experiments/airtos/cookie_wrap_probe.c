#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "rt_ai.h"

typedef struct {
    uint32_t epoch[2];
    uint32_t cookie[2];
    unsigned submissions;
    uint32_t checksum;
} host_provider_t;

static int submit(void *opaque, const rt_ai_aeg_segment_t *segment, uint32_t epoch, uint32_t cookie)
{
    host_provider_t *provider = (host_provider_t *)opaque;
    unsigned index = provider->submissions++;
    if (index < 2U) {
        provider->epoch[index] = epoch;
        provider->cookie[index] = cookie;
    }
    provider->checksum = provider->checksum * UINT32_C(33) + segment->id + cookie;
    return RT_AI_OK;
}

int main(void)
{
    uint8_t arena[64];
    rt_ai_runtime_t runtime;
    rt_ai_provider_t provider;
    host_provider_t host = {0};
    rt_ai_aeg_t aeg;
    rt_ai_session_t session;
    rt_ai_job_t first;
    rt_ai_job_t second;

    memset(&provider, 0, sizeof(provider));
    memset(&aeg, 0, sizeof(aeg));
    assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
    provider.resource = RT_AI_RESOURCE_CPU;
    provider.submit = submit;
    provider.user = &host;
    assert(rt_ai_provider_register(&runtime, &provider) == RT_AI_OK);
    aeg.header.version = RT_AI_AEG_VERSION;
    aeg.header.segment_count = 1U;
    aeg.header.arena_size = sizeof(arena);
    aeg.storage[0] = (rt_ai_aeg_segment_t){1U, RT_AI_RESOURCE_CPU, 0U, 0U, 0U, sizeof(arena)};
    aeg.segments = aeg.storage;
    aeg.deployable = 1U;
    aeg.legacy = 1U;
    assert(rt_ai_session_create(&runtime, &aeg, &session) == RT_AI_OK);

    runtime.next_cookie[RT_AI_RESOURCE_CPU] = UINT32_MAX;
    assert(rt_ai_submit_async(&session, 1U, 100U, &first) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 1U) == RT_AI_OK);
    assert(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, host.epoch[0], host.cookie[0], RT_AI_OK) == RT_AI_OK);
    assert(rt_ai_submit_async(&session, 2U, 100U, &second) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 2U) == RT_AI_OK);

    printf("COOKIE_WRAP_PROBE first_epoch=%u first_cookie=%u second_epoch=%u second_cookie=%u checksum=%u\n",
        host.epoch[0], host.cookie[0], host.epoch[1], host.cookie[1], host.checksum);
    return host.cookie[0] == UINT32_MAX && host.cookie[1] == 1U && host.epoch[1] > host.epoch[0] ? 0 : 1;
}

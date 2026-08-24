#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "rt_ai.h"

typedef struct {
    int submits;
    int cancels;
    int resets;
    int cleans;
    int invalidates;
    uint32_t epoch;
    uint32_t cookie;
    uint16_t segment_id;
} mock_t;

typedef struct {
    rt_ai_aeg_header_t header;
    rt_ai_aeg_segment_t segments[3];
} package_t;

static int mock_submit(void *user, const rt_ai_aeg_segment_t *segment, uint32_t epoch, uint32_t cookie)
{
    mock_t *mock = (mock_t *)user;
    ++mock->submits;
    mock->epoch = epoch;
    mock->cookie = cookie;
    mock->segment_id = segment->id;
    return RT_AI_OK;
}

static int mock_cancel(void *user, uint32_t epoch, uint32_t cookie)
{
    mock_t *mock = (mock_t *)user;
    ++mock->cancels;
    mock->epoch = epoch;
    mock->cookie = cookie;
    return RT_AI_OK;
}

static int mock_reset(void *user, uint32_t epoch)
{
    mock_t *mock = (mock_t *)user;
    ++mock->resets;
    mock->epoch = epoch;
    return RT_AI_OK;
}

static void mock_clean(void *user, void *address, size_t size)
{
    mock_t *mock = (mock_t *)user;
    assert(address != NULL && size != 0U);
    ++mock->cleans;
}

static void mock_invalidate(void *user, void *address, size_t size)
{
    mock_t *mock = (mock_t *)user;
    assert(address != NULL && size != 0U);
    ++mock->invalidates;
}

static package_t package(unsigned count)
{
    package_t value;
    memset(&value, 0, sizeof(value));
    value.header.magic = RT_AI_AEG_MAGIC;
    value.header.version = RT_AI_AEG_VERSION;
    value.header.segment_count = (uint16_t)count;
    value.header.arena_size = 64U;
    return value;
}

static void register_provider(rt_ai_runtime_t *runtime, mock_t *mock, uint8_t resource)
{
    rt_ai_provider_t provider;
    memset(&provider, 0, sizeof(provider));
    provider.resource = resource;
    provider.submit = mock_submit;
    provider.cancel = mock_cancel;
    provider.reset = mock_reset;
    provider.clean = mock_clean;
    provider.invalidate = mock_invalidate;
    provider.user = mock;
    assert(rt_ai_provider_register(runtime, &provider) == RT_AI_OK);
}

static rt_ai_aeg_t load_package(package_t *blob)
{
    rt_ai_aeg_t aeg;
    size_t size = sizeof(blob->header) + blob->header.segment_count * sizeof(blob->segments[0]);
    assert(rt_ai_load(blob, size, &aeg) == RT_AI_OK);
    return aeg;
}

static void test_loader(void)
{
    package_t blob = package(2U);
    rt_ai_aeg_t aeg;
    blob.segments[0] = (rt_ai_aeg_segment_t){1U, RT_AI_RESOURCE_CPU, 0U, 0U, 0U, 16U};
    blob.segments[1] = (rt_ai_aeg_segment_t){2U, RT_AI_RESOURCE_DMA, 0U, 1U, 16U, 16U};
    assert(rt_ai_load(&blob, sizeof(blob.header) - 1U, &aeg) == RT_AI_ERR_INVALID);
    assert(rt_ai_load(&blob, sizeof(blob.header) + 2U * sizeof(blob.segments[0]), &aeg) == RT_AI_OK);
    blob.segments[0].dependency_mask = 2U;
    assert(rt_ai_load(&blob, sizeof(blob.header) + 2U * sizeof(blob.segments[0]), &aeg) == RT_AI_ERR_INVALID);
    blob.segments[0].dependency_mask = 0U;
    blob.segments[1].arena_size = 65U;
    assert(rt_ai_load(&blob, sizeof(blob.header) + 2U * sizeof(blob.segments[0]), &aeg) == RT_AI_ERR_INVALID);
    blob.segments[1].arena_size = 16U;
    blob.segments[1].id = blob.segments[0].id;
    assert(rt_ai_load(&blob, sizeof(blob.header) + 2U * sizeof(blob.segments[0]), &aeg) == RT_AI_ERR_INVALID);
}

static void test_edf(void)
{
    uint8_t arena[256];
    rt_ai_runtime_t runtime;
    mock_t cpu = {0};
    package_t blob = package(1U);
    rt_ai_aeg_t aeg;
    rt_ai_session_t late_session;
    rt_ai_session_t early_session;
    rt_ai_job_t late_job;
    rt_ai_job_t early_job;
    blob.segments[0] = (rt_ai_aeg_segment_t){10U, RT_AI_RESOURCE_CPU, 0U, 0U, 0U, 16U};
    aeg = load_package(&blob);
    assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
    register_provider(&runtime, &cpu, RT_AI_RESOURCE_CPU);
    assert(rt_ai_session_create(&runtime, &aeg, &late_session) == RT_AI_OK);
    assert(rt_ai_session_create(&runtime, &aeg, &early_session) == RT_AI_OK);
    assert(late_session.lease.offset != early_session.lease.offset);
    assert(rt_ai_submit_async(&late_session, 0U, 100U, &late_job) == RT_AI_OK);
    assert(rt_ai_submit_async(&early_session, 0U, 50U, &early_job) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 1U) == RT_AI_OK);
    assert(runtime.active_job[RT_AI_RESOURCE_CPU] == &early_job);
    assert(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, cpu.epoch, cpu.cookie, RT_AI_OK) == RT_AI_OK);
    assert(rt_ai_wait(&early_job) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 2U) == RT_AI_OK);
    assert(runtime.active_job[RT_AI_RESOURCE_CPU] == &late_job);
    assert(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, cpu.epoch, cpu.cookie, RT_AI_OK) == RT_AI_OK);
    assert(rt_ai_session_destroy(&early_session) == RT_AI_OK);
    assert(rt_ai_session_destroy(&late_session) == RT_AI_OK);
}

static void test_dag_concurrency_and_cache(void)
{
    uint8_t arena[256];
    rt_ai_runtime_t runtime;
    mock_t cpu = {0};
    mock_t dma = {0};
    package_t chain = package(2U);
    package_t parallel = package(2U);
    rt_ai_aeg_t chain_aeg;
    rt_ai_aeg_t parallel_aeg;
    rt_ai_session_t chain_session;
    rt_ai_session_t parallel_session;
    rt_ai_job_t chain_job;
    rt_ai_job_t parallel_job;
    chain.segments[0] = (rt_ai_aeg_segment_t){20U, RT_AI_RESOURCE_CPU, 0U, 0U, 0U, 16U};
    chain.segments[1] = (rt_ai_aeg_segment_t){21U, RT_AI_RESOURCE_DMA, RT_AI_SEGMENT_CLEAN_INPUT | RT_AI_SEGMENT_INVALIDATE_OUTPUT, 1U, 16U, 16U};
    parallel.segments[0] = (rt_ai_aeg_segment_t){30U, RT_AI_RESOURCE_CPU, 0U, 0U, 0U, 16U};
    parallel.segments[1] = (rt_ai_aeg_segment_t){31U, RT_AI_RESOURCE_DMA, RT_AI_SEGMENT_CLEAN_INPUT | RT_AI_SEGMENT_INVALIDATE_OUTPUT, 0U, 16U, 16U};
    chain_aeg = load_package(&chain);
    parallel_aeg = load_package(&parallel);
    assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
    register_provider(&runtime, &cpu, RT_AI_RESOURCE_CPU);
    register_provider(&runtime, &dma, RT_AI_RESOURCE_DMA);
    assert(rt_ai_session_create(&runtime, &chain_aeg, &chain_session) == RT_AI_OK);
    assert(rt_ai_submit_async(&chain_session, 0U, 100U, &chain_job) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 1U) == RT_AI_OK);
    assert(cpu.submits == 1 && dma.submits == 0);
    assert(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, cpu.epoch, cpu.cookie, RT_AI_OK) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 2U) == RT_AI_OK);
    assert(dma.submits == 1 && dma.cleans == 1);
    assert(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_DMA, dma.epoch, dma.cookie, RT_AI_OK) == RT_AI_OK);
    assert(dma.invalidates == 1 && rt_ai_wait(&chain_job) == RT_AI_OK);
    assert(rt_ai_session_destroy(&chain_session) == RT_AI_OK);

    assert(rt_ai_session_create(&runtime, &parallel_aeg, &parallel_session) == RT_AI_OK);
    assert(rt_ai_submit_async(&parallel_session, 10U, 100U, &parallel_job) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 11U) == RT_AI_OK);
    assert(runtime.active_job[RT_AI_RESOURCE_CPU] == &parallel_job);
    assert(runtime.active_job[RT_AI_RESOURCE_DMA] == &parallel_job);
    assert(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, cpu.epoch, cpu.cookie, RT_AI_OK) == RT_AI_OK);
    assert(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_DMA, dma.epoch, dma.cookie, RT_AI_OK) == RT_AI_OK);
    assert(rt_ai_wait(&parallel_job) == RT_AI_OK);
    assert(rt_ai_session_destroy(&parallel_session) == RT_AI_OK);
}

static void test_timeout_cancel_reset_irq(void)
{
    uint8_t arena[128];
    rt_ai_runtime_t runtime;
    mock_t dma = {0};
    package_t blob = package(1U);
    rt_ai_aeg_t aeg;
    rt_ai_session_t session;
    rt_ai_job_t job;
    uint32_t old_epoch;
    uint32_t old_cookie;
    blob.segments[0] = (rt_ai_aeg_segment_t){40U, RT_AI_RESOURCE_DMA, RT_AI_SEGMENT_CLEAN_INPUT, 0U, 0U, 16U};
    aeg = load_package(&blob);
    assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
    register_provider(&runtime, &dma, RT_AI_RESOURCE_DMA);
    assert(rt_ai_session_create(&runtime, &aeg, &session) == RT_AI_OK);
    assert(rt_ai_submit_async(&session, 0U, 10U, &job) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 1U) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 10U) == RT_AI_ERR_TIMEOUT);
    assert(rt_ai_wait(&job) == RT_AI_ERR_TIMEOUT && dma.cancels == 1);
    assert(rt_ai_session_destroy(&session) == RT_AI_OK);

    assert(rt_ai_session_create(&runtime, &aeg, &session) == RT_AI_OK);
    assert(rt_ai_submit_async(&session, 20U, 100U, &job) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 21U) == RT_AI_OK);
    old_epoch = dma.epoch;
    old_cookie = dma.cookie;
    assert(rt_ai_reset_device(&runtime, RT_AI_RESOURCE_DMA) == RT_AI_OK);
    assert(dma.resets == 1 && rt_ai_wait(&job) == RT_AI_ERR_TIMEOUT);
    assert(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_DMA, old_epoch, old_cookie, RT_AI_OK) == RT_AI_ERR_STALE);
    assert(rt_ai_session_destroy(&session) == RT_AI_OK);

    assert(rt_ai_session_create(&runtime, &aeg, &session) == RT_AI_OK);
    assert(rt_ai_submit_async(&session, 30U, 100U, &job) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 31U) == RT_AI_OK);
    old_epoch = dma.epoch;
    old_cookie = dma.cookie;
    assert(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_DMA, old_epoch, old_cookie, RT_AI_OK) == RT_AI_OK);
    assert(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_DMA, old_epoch, old_cookie, RT_AI_OK) == RT_AI_ERR_STALE);
    assert(rt_ai_session_destroy(&session) == RT_AI_OK);

    assert(rt_ai_session_create(&runtime, &aeg, &session) == RT_AI_OK);
    assert(rt_ai_submit_async(&session, 40U, 100U, &job) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 41U) == RT_AI_OK);
    assert(rt_ai_cancel(&job) == RT_AI_OK && rt_ai_wait(&job) == RT_AI_ERR_CANCELLED);
    assert(rt_ai_session_destroy(&session) == RT_AI_OK);
}

int main(void)
{
    test_loader();
    test_edf();
    test_dag_concurrency_and_cache();
    test_timeout_cancel_reset_irq();
    puts("AEG_PASS ASYNC_PASS DAG_PASS EDF_PASS ARENA_PASS CACHE_PASS TIMEOUT_PASS CANCEL_PASS EPOCH_PASS IRQ_PASS");
    return 0;
}

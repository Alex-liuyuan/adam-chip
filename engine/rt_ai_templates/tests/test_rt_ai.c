#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "rt_ai.h"
#include "rt_ai_internal.h"

typedef struct {
    int submits;
    int cancels;
    int resets;
    int reset_polls;
    int cleans;
    int invalidates;
    int cancel_polls;
    int cancel_ack_after;
    int reinit_status;
    int health_calls;
    int health_fail_after;
    uint32_t epoch;
    uint32_t cookie;
    uint16_t segment_id;
} mock_t;

typedef struct {
    uint8_t *cpu;
    uint8_t device[64];
    int coherent;
    int cpu_dirty;
    int device_dirty;
    int ordered;
    int barriers;
} cache_model_t;

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

static int mock_cancel_begin(void *user, uint32_t epoch, uint32_t cookie)
{
    return mock_cancel(user, epoch, cookie);
}

static int mock_cancel_poll(void *user, uint32_t epoch, uint32_t cookie)
{
    mock_t *mock = (mock_t *)user;
    (void)epoch;
    (void)cookie;
    ++mock->cancel_polls;
    return mock->cancel_polls >= mock->cancel_ack_after ? RT_AI_OK : RT_AI_BUSY;
}

static int mock_reset_begin(void *user, uint32_t epoch)
{
    return mock_reset(user, epoch);
}

static int mock_reset_poll(void *user, uint32_t epoch)
{
    mock_t *mock = (mock_t *)user;
    (void)epoch;
    ++mock->reset_polls;
    return RT_AI_OK;
}

static int mock_reinit_poll(void *user, uint32_t epoch)
{
    mock_t *mock = (mock_t *)user;
    (void)epoch;
    return mock->reinit_status;
}

static int mock_health(void *user)
{
    mock_t *mock = (mock_t *)user;
    ++mock->health_calls;
    return mock->health_fail_after != 0 && mock->health_calls >= mock->health_fail_after ? RT_AI_ERR_PROVIDER : RT_AI_OK;
}

static int cache_clean(void *user, void *address, size_t size)
{
    cache_model_t *model = (cache_model_t *)user;
    assert(address == model->cpu && size == sizeof(model->device));
    memcpy(model->device, model->cpu, size);
    model->cpu_dirty = 0;
    model->ordered = 0;
    return RT_AI_OK;
}

static int cache_invalidate(void *user, void *address, size_t size)
{
    cache_model_t *model = (cache_model_t *)user;
    assert(address == model->cpu && size == sizeof(model->device) && model->ordered);
    memcpy(model->cpu, model->device, size);
    model->device_dirty = 0;
    model->ordered = 0;
    return RT_AI_OK;
}

static int cache_barrier(void *user)
{
    cache_model_t *model = (cache_model_t *)user;
    model->ordered = 1;
    ++model->barriers;
    return RT_AI_OK;
}

static int cache_submit(void *user, const rt_ai_aeg_segment_t *segment, uint32_t epoch, uint32_t cookie)
{
    cache_model_t *model = (cache_model_t *)user;
    (void)segment; (void)epoch; (void)cookie;
    if (model->coherent) ++model->cpu[0];
    else {
        assert(model->ordered);
        ++model->device[0];
        model->device_dirty = 1;
        model->ordered = 0;
    }
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

static void load_package(package_t *blob, rt_ai_aeg_t *aeg)
{
    size_t size = sizeof(blob->header) + blob->header.segment_count * sizeof(blob->segments[0]);
    assert(rt_ai_load(blob, size, aeg) == RT_AI_OK);
    assert(aeg->legacy && !aeg->deployable);
    aeg->deployable = 1U; /* Scheduling fixtures bypass deployment admission. */
}

static void authorize_fallback_package(rt_ai_aeg_t *aeg, rt_ai_trust_bundle_t *trust)
{
    uint16_t index;
    memset(trust, 0, sizeof(*trust));
    aeg->header.version = RT_AI_AEG_V2_VERSION;
    aeg->legacy = 0U;
    aeg->deployable = 1U;
    aeg->minimum_interarrival_us = 100U;
    aeg->relative_deadline_us = 1000000U;
    aeg->input_rank = 1U;
    aeg->input_dtype = 1U;
    aeg->input_layout = 1U;
    aeg->input_shape[0] = 8U;
    aeg->input_bytes = 32U;
    aeg->output_bytes = 32U;
    aeg->evidence_count = 2U;
    aeg->evidence_index[0] = 0U;
    aeg->fallback_evidence[0] = 1U;
    aeg->evidence_resource[0] = aeg->segments[0].resource;
    aeg->evidence_resource[1] = aeg->fallback_storage[0].resource;
    memset(aeg->plan_sha256, 1, 32U);
    memset(aeg->evidence_sha256, 2, 32U);
    memset(aeg->policy_sha256, 3, 32U);
    memset(aeg->model_sha256, 4, 32U);
    memset(aeg->target_sha256, 5, 32U);
    memset(aeg->runtime_abi_sha256, 6, 32U);
    memset(aeg->provider_abi_sha256, 7, 32U);
    memset(aeg->fallback_plan_sha256, 8, 32U);
    memcpy(trust->plan_sha256, aeg->plan_sha256, 32U);
    memcpy(trust->evidence_sha256, aeg->evidence_sha256, 32U);
    memcpy(trust->policy_sha256, aeg->policy_sha256, 32U);
    memcpy(trust->model_sha256, aeg->model_sha256, 32U);
    memcpy(trust->target_sha256, aeg->target_sha256, 32U);
    memcpy(trust->runtime_abi_sha256, aeg->runtime_abi_sha256, 32U);
    memcpy(trust->provider_abi_sha256, aeg->provider_abi_sha256, 32U);
    for (index = 0U; index < 2U; ++index) {
        memset(aeg->obligation_sha256[index], 9 + index, 32U);
        memset(aeg->scope_sha256[index], 11 + index, 32U);
        memset(aeg->artifact_sha256[index], 13 + index, 32U);
        memset(aeg->verifier_sha256[index], 15 + index, 32U);
        aeg->evidence_status[index] = 1U;
        memcpy(trust->obligation_sha256[index], aeg->obligation_sha256[index], 32U);
        memcpy(trust->scope_sha256[index], aeg->scope_sha256[index], 32U);
        memcpy(trust->artifact_sha256[index], aeg->artifact_sha256[index], 32U);
        memcpy(trust->verifier_sha256[index], aeg->verifier_sha256[index], 32U);
        memcpy(trust->allowed_verifier_sha256[index], aeg->verifier_sha256[index], 32U);
        trust->evidence_resource[index] = aeg->evidence_resource[index];
    }
    trust->obligation_count = 2U;
    trust->allowed_verifier_count = 2U;
}

static void submit_authorized(rt_ai_session_t *session, rt_ai_job_t *job, uint64_t now_us)
{
    uint8_t input[32] = {0};
    uint8_t output[32] = {0};
    rt_ai_invocation_t invocation;
    rt_ai_submit_policy_t policy = {now_us, now_us + 1000000U, 1U, 2U};
    rt_ai_admission_result_t result;
    memset(&invocation, 0, sizeof(invocation));
    invocation.input = input;
    invocation.input_size = sizeof(input);
    invocation.output = output;
    invocation.output_size = sizeof(output);
    invocation.input_rank = 1U;
    invocation.input_dtype = 1U;
    invocation.input_layout = 1U;
    invocation.input_shape[0] = 8U;
    memcpy(invocation.plan_sha256, session->aeg.plan_sha256, 32U);
    assert(rt_ai_submit_async_v2(session, &invocation, &policy, &result, job) == RT_AI_OK);
}

static int poll_port_time(rt_ai_runtime_t *runtime)
{
    return rt_ai_poll(runtime, rt_ai_port_now_us());
}

static void test_loader(void)
{
    package_t blob = package(2U);
    rt_ai_aeg_t aeg;
    blob.segments[0] = (rt_ai_aeg_segment_t){1U, RT_AI_RESOURCE_CPU, 0U, 0U, 0U, 16U};
    blob.segments[1] = (rt_ai_aeg_segment_t){2U, RT_AI_RESOURCE_DMA, 0U, 1U, 16U, 16U};
    assert(rt_ai_load(&blob, sizeof(blob.header) - 1U, &aeg) == RT_AI_ERR_INVALID);
    assert(rt_ai_load(&blob, sizeof(blob.header) + 2U * sizeof(blob.segments[0]), &aeg) == RT_AI_OK);
    assert(aeg.legacy && !aeg.deployable);
    blob.segments[0].dependency_mask = 2U;
    assert(rt_ai_load(&blob, sizeof(blob.header) + 2U * sizeof(blob.segments[0]), &aeg) == RT_AI_ERR_INVALID);
    blob.segments[0].dependency_mask = 0U;
    blob.segments[1].arena_size = 65U;
    assert(rt_ai_load(&blob, sizeof(blob.header) + 2U * sizeof(blob.segments[0]), &aeg) == RT_AI_ERR_INVALID);
    blob.segments[1].arena_size = 16U;
    blob.segments[1].id = blob.segments[0].id;
    assert(rt_ai_load(&blob, sizeof(blob.header) + 2U * sizeof(blob.segments[0]), &aeg) == RT_AI_ERR_INVALID);
}

static void test_evidence_policy(void)
{
    rt_ai_aeg_t aeg;
    rt_ai_aeg_segment_t primary = {1U, RT_AI_RESOURCE_CPU, 0U, 0U, 0U, 16U};
    rt_ai_trust_bundle_t trust;
    rt_ai_evaluation_result_t result;
    memset(&aeg, 0, sizeof(aeg));
    memset(&trust, 0, sizeof(trust));
    aeg.header.segment_count = 1U;
    aeg.segments = &primary;
    aeg.fallback_segment_count = 1U;
    aeg.fallback_storage[0] = (rt_ai_aeg_segment_t){2U, RT_AI_RESOURCE_CPU, 0U, 0U, 0U, 16U};
    aeg.evidence_count = 1U;
    aeg.evidence_status[0] = 1U;
    aeg.evidence_resource[0] = RT_AI_RESOURCE_CPU;
    aeg.evidence_index[0] = 0U;
    aeg.fallback_evidence[0] = 0U;
    aeg.minimum_interarrival_us = 100U;
    aeg.relative_deadline_us = 100U;
    aeg.cancel_ack_timeout_us = 10U;
    aeg.reset_timeout_us = 10U;
    aeg.reinit_timeout_us = 10U;
    aeg.deployable = 1U;
    memset(aeg.plan_sha256, 1, 32U);
    memset(aeg.evidence_sha256, 2, 32U);
    memset(aeg.policy_sha256, 3, 32U);
    memset(aeg.model_sha256, 4, 32U);
    memset(aeg.target_sha256, 5, 32U);
    memset(aeg.runtime_abi_sha256, 6, 32U);
    memset(aeg.provider_abi_sha256, 7, 32U);
    memset(aeg.obligation_sha256[0], 8, 32U);
    memset(aeg.scope_sha256[0], 9, 32U);
    memset(aeg.artifact_sha256[0], 10, 32U);
    memset(aeg.verifier_sha256[0], 11, 32U);
    memcpy(&trust, &aeg.plan_sha256, 7U * 32U);
    memcpy(trust.obligation_sha256[0], aeg.obligation_sha256[0], 32U);
    memcpy(trust.scope_sha256[0], aeg.scope_sha256[0], 32U);
    memcpy(trust.artifact_sha256[0], aeg.artifact_sha256[0], 32U);
    memcpy(trust.verifier_sha256[0], aeg.verifier_sha256[0], 32U);
    memcpy(trust.allowed_verifier_sha256[0], aeg.verifier_sha256[0], 32U);
    trust.evidence_resource[0] = RT_AI_RESOURCE_CPU;
    trust.obligation_count = 1U;
    trust.allowed_verifier_count = 1U;
    assert(rt_ai_evaluate_deployment(&aeg, &trust, &result) == RT_AI_OK && result.reason == 0U);
    aeg.model_sha256[0] ^= 1U;
    assert(rt_ai_evaluate_deployment(&aeg, &trust, &result) == RT_AI_ERR_EVIDENCE && result.reason == 2U);
    aeg.model_sha256[0] ^= 1U; aeg.runtime_abi_sha256[0] ^= 1U;
    assert(rt_ai_evaluate_deployment(&aeg, &trust, &result) == RT_AI_ERR_EVIDENCE && result.reason == 2U);
    aeg.runtime_abi_sha256[0] ^= 1U; aeg.provider_abi_sha256[0] ^= 1U;
    assert(rt_ai_evaluate_deployment(&aeg, &trust, &result) == RT_AI_ERR_EVIDENCE && result.reason == 2U);
    aeg.provider_abi_sha256[0] ^= 1U; aeg.verifier_sha256[0][0] ^= 1U;
    assert(rt_ai_evaluate_deployment(&aeg, &trust, &result) == RT_AI_ERR_EVIDENCE && result.reason == 3U);
    aeg.verifier_sha256[0][0] ^= 1U; aeg.evidence_status[0] = 0U;
    assert(rt_ai_evaluate_deployment(&aeg, &trust, &result) == RT_AI_ERR_EVIDENCE && result.reason == 3U);
    aeg.evidence_status[0] = 1U; aeg.evidence_count = 0U;
    assert(rt_ai_evaluate_deployment(&aeg, &trust, &result) == RT_AI_ERR_EVIDENCE && result.reason == 3U);
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
    load_package(&blob, &aeg);
    assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
    register_provider(&runtime, &cpu, RT_AI_RESOURCE_CPU);
    assert(rt_ai_session_create(&runtime, &aeg, &late_session) == RT_AI_OK);
    assert(rt_ai_session_create(&runtime, &aeg, &early_session) == RT_AI_OK);
    assert(rt_ai_submit_async(&late_session, 0U, 100U, &late_job) == RT_AI_OK);
    assert(rt_ai_submit_async(&early_session, 0U, 50U, &early_job) == RT_AI_OK);
    assert(late_job.lease.offset != early_job.lease.offset);
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
    load_package(&chain, &chain_aeg);
    load_package(&parallel, &parallel_aeg);
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

static void test_wcet_temporal_isolation(void)
{
    uint8_t arena[128];
    rt_ai_runtime_t runtime;
    mock_t cpu = {0};
    package_t blob = package(1U);
    rt_ai_aeg_t aeg;
    rt_ai_session_t session;
    rt_ai_job_t job;
    uint64_t now_us = rt_ai_port_now_us();
    blob.segments[0] = (rt_ai_aeg_segment_t){32U, RT_AI_RESOURCE_CPU, 0U, 0U, 0U, 64U};
    load_package(&blob, &aeg);
    aeg.wcet_us[0] = 100000U;
    assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
    register_provider(&runtime, &cpu, RT_AI_RESOURCE_CPU);
    assert(rt_ai_session_create(&runtime, &aeg, &session) == RT_AI_OK);
    assert(rt_ai_submit_async(&session, now_us, now_us + 1000000U, &job) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, now_us) == RT_AI_OK);
    assert(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, cpu.epoch, cpu.cookie, RT_AI_OK) == RT_AI_OK);
    assert(rt_ai_wait(&job) == RT_AI_BUSY && job.segment_state[0] == RT_AI_SEG_HELD);
    assert(rt_ai_poll(&runtime, now_us + 99999U) == RT_AI_OK && rt_ai_wait(&job) == RT_AI_BUSY);
    assert(rt_ai_poll(&runtime, now_us + 100000U) == RT_AI_OK && rt_ai_wait(&job) == RT_AI_OK);
    assert(rt_ai_session_destroy(&session) == RT_AI_OK);
}

static uint8_t run_cache_model(uint8_t flags, int coherent, int *barriers)
{
    uint8_t arena[128] = {0};
    rt_ai_runtime_t runtime;
    package_t blob = package(1U);
    rt_ai_aeg_t aeg;
    rt_ai_session_t session;
    rt_ai_job_t job;
    rt_ai_provider_t provider;
    cache_model_t model;
    blob.segments[0] = (rt_ai_aeg_segment_t){35U, RT_AI_RESOURCE_DMA, flags, 0U, 0U, 64U};
    load_package(&blob, &aeg);
    assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
    memset(&model, 0, sizeof(model));
    model.cpu = arena;
    model.coherent = coherent;
    memset(&provider, 0, sizeof(provider));
    provider.resource = RT_AI_RESOURCE_DMA;
    provider.submit = cache_submit;
    provider.clean_range = cache_clean;
    provider.invalidate_range = cache_invalidate;
    provider.barrier = cache_barrier;
    provider.user = &model;
    assert(rt_ai_provider_register(&runtime, &provider) == RT_AI_OK);
    assert(rt_ai_session_create(&runtime, &aeg, &session) == RT_AI_OK);
    arena[0] = 41U;
    model.cpu_dirty = 1;
    assert(rt_ai_submit_async(&session, 0U, 100U, &job) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 1U) == RT_AI_OK);
    assert(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_DMA, runtime.epoch[RT_AI_RESOURCE_DMA], job.cookie[0], RT_AI_OK) == RT_AI_OK);
    assert(rt_ai_wait(&job) == RT_AI_OK);
    *barriers = model.barriers;
    assert(rt_ai_session_destroy(&session) == RT_AI_OK);
    return arena[0];
}

static void test_noncoherent_cache_model(void)
{
    int barriers;
    assert(run_cache_model(0U, 1, &barriers) == 42U);
    assert(run_cache_model(RT_AI_SEGMENT_CLEAN_INPUT | RT_AI_SEGMENT_INVALIDATE_OUTPUT, 0, &barriers) == 42U && barriers == 3);
    assert(run_cache_model(RT_AI_SEGMENT_INVALIDATE_OUTPUT, 0, &barriers) == 1U);
    assert(run_cache_model(RT_AI_SEGMENT_CLEAN_INPUT, 0, &barriers) == 41U);
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
    load_package(&blob, &aeg);
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

static void test_admission(void)
{
    uint8_t arena[128];
    uint8_t input[32] = {0};
    uint8_t output[32] = {0};
    rt_ai_runtime_t runtime;
    mock_t cpu = {0};
    package_t blob = package(1U);
    rt_ai_aeg_t aeg;
    rt_ai_session_t session;
    rt_ai_job_t job;
    rt_ai_invocation_t invocation;
    rt_ai_submit_policy_t policy = {0U, 20U, 1U, 2U};
    rt_ai_admission_result_t result;
    rt_ai_trace_entry_t trace[4];
    char trace_json[2048];
    size_t trace_json_size;
    uint16_t trace_count;
    uint64_t dropped;
    blob.segments[0] = (rt_ai_aeg_segment_t){50U, RT_AI_RESOURCE_CPU, 0U, 0U, 0U, 64U};
    load_package(&blob, &aeg);
    aeg.legacy = 0U;
    memset(aeg.plan_sha256, 0x5a, sizeof(aeg.plan_sha256));
    aeg.wcet_us[0] = 10U;
    aeg.coherency_cost_us[0] = 1U;
    aeg.recovery_cost_us[0] = 10U;
    aeg.reservation_budget_us[RT_AI_RESOURCE_CPU] = 21U;
    aeg.reservation_period_us[RT_AI_RESOURCE_CPU] = 100U;
    aeg.minimum_interarrival_us = 100U;
    aeg.relative_deadline_us = 100U;
    aeg.input_rank = 1U;
    aeg.input_dtype = 1U;
    aeg.input_layout = 1U;
    aeg.input_shape[0] = 8U;
    aeg.input_bytes = sizeof(input);
    aeg.output_bytes = sizeof(output);
    memset(&invocation, 0, sizeof(invocation));
    memset(&job, 0, sizeof(job));
    invocation.input = input; invocation.input_size = sizeof(input);
    invocation.output = output; invocation.output_size = sizeof(output);
    invocation.input_rank = 1U; invocation.input_dtype = 1U; invocation.input_layout = 1U; invocation.input_shape[0] = 8U;
    memcpy(invocation.plan_sha256, aeg.plan_sha256, sizeof(invocation.plan_sha256));
    assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
    register_provider(&runtime, &cpu, RT_AI_RESOURCE_CPU);
    assert(rt_ai_session_create(&runtime, &aeg, &session) == RT_AI_OK);
    runtime.providers[RT_AI_RESOURCE_CPU].health = mock_health;
    cpu.health_fail_after = 2;
    policy.deadline_us = 100U;
    assert(rt_ai_submit_async_v2(&session, &invocation, &policy, &result, &job) == RT_AI_ERR_RESOURCE);
    assert(result.stage == RT_AI_ADMISSION_PROVIDER && !job.lease.used);
    cpu.health_calls = 0;
    cpu.health_fail_after = 0;
    policy.deadline_us = 20U;
    assert(rt_ai_submit_async_v2(&session, &invocation, &policy, &result, &job) == RT_AI_ERR_ADMISSION);
    assert(result.stage == RT_AI_ADMISSION_DEADLINE && !job.lease.used);
    policy.deadline_us = 100U;
    assert(rt_ai_submit_async_v2(&session, &invocation, &policy, &result, &job) == RT_AI_OK);
    assert(result.stage == RT_AI_ADMISSION_ACCEPTED && job.lease.used);
    assert(rt_ai_poll(&runtime, 1U) == RT_AI_OK);
    assert(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, cpu.epoch, cpu.cookie, RT_AI_OK) == RT_AI_OK);
    assert(rt_ai_wait(&job) == RT_AI_OK && !job.lease.used);
    assert(rt_ai_trace_snapshot(&runtime, trace, 4U, &trace_count, &dropped) == RT_AI_OK);
    assert(trace_count == 4U && dropped == 0U &&
        trace[0].event == RT_AI_TRACE_PROVIDER_REJECT && trace[1].event == RT_AI_TRACE_DEADLINE_REJECT &&
        trace[2].event == RT_AI_TRACE_DISPATCH && trace[3].event == RT_AI_TRACE_COMPLETE &&
        trace[0].sequence < trace[1].sequence && trace[1].sequence < trace[2].sequence &&
        trace[2].sequence < trace[3].sequence && trace[3].timestamp_us != 0U);
    assert(rt_ai_trace_json(&runtime, trace_json, sizeof(trace_json), &trace_json_size) == RT_AI_OK);
    assert(trace_json_size > 0U && strstr(trace_json, "\"run_id\":\"0000000000000000000000000000000000000000000000000000000000000001\"") != NULL);
    assert(rt_ai_trace_json(&runtime, trace_json, 8U, &trace_json_size) == RT_AI_ERR_RESOURCE);
    assert(rt_ai_session_destroy(&session) == RT_AI_OK);
}

static void test_acknowledged_recovery(void)
{
    uint8_t arena[128];
    rt_ai_runtime_t runtime;
    mock_t dma = {0};
    package_t blob = package(1U);
    rt_ai_aeg_t aeg;
    rt_ai_session_t session;
    rt_ai_job_t job;
    blob.segments[0] = (rt_ai_aeg_segment_t){60U, RT_AI_RESOURCE_DMA, 0U, 0U, 0U, 64U};
    load_package(&blob, &aeg);
    aeg.cancel_ack_timeout_us = 50U;
    aeg.reinit_timeout_us = 100U;
    assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
    register_provider(&runtime, &dma, RT_AI_RESOURCE_DMA);
    dma.cancel_ack_after = 2;
    dma.reinit_status = RT_AI_OK;
    runtime.providers[RT_AI_RESOURCE_DMA].cancel_begin = mock_cancel_begin;
    runtime.providers[RT_AI_RESOURCE_DMA].cancel_poll = mock_cancel_poll;
    runtime.providers[RT_AI_RESOURCE_DMA].reset_begin = mock_reset_begin;
    runtime.providers[RT_AI_RESOURCE_DMA].reinit_poll = mock_reinit_poll;
    runtime.providers[RT_AI_RESOURCE_DMA].health = mock_health;
    assert(rt_ai_session_create(&runtime, &aeg, &session) == RT_AI_OK);
    assert(rt_ai_submit_async(&session, 0U, 100U, &job) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 1U) == RT_AI_OK);
    assert(rt_ai_cancel(&job) == RT_AI_OK && rt_ai_wait(&job) == RT_AI_BUSY && job.lease.used);
    assert(rt_ai_poll(&runtime, 2U) == RT_AI_OK && rt_ai_wait(&job) == RT_AI_BUSY);
    assert(rt_ai_poll(&runtime, 3U) == RT_AI_OK && rt_ai_wait(&job) == RT_AI_ERR_CANCELLED && !job.lease.used);
    assert(runtime.resource_state[RT_AI_RESOURCE_DMA] == RT_AI_RESOURCE_HEALTHY);
    assert(rt_ai_session_destroy(&session) == RT_AI_OK);

    dma.cancel_polls = 0;
    dma.cancel_ack_after = 1000;
    dma.reinit_status = RT_AI_ERR_PROVIDER;
    assert(rt_ai_session_create(&runtime, &aeg, &session) == RT_AI_OK);
    assert(rt_ai_submit_async(&session, 10U, 200U, &job) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 11U) == RT_AI_OK);
    assert(rt_ai_cancel(&job) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 62U) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, 63U) == RT_AI_OK);
    assert(runtime.resource_state[RT_AI_RESOURCE_DMA] == RT_AI_RESOURCE_QUARANTINED);
    assert(rt_ai_wait(&job) == RT_AI_ERR_CANCELLED && !job.lease.used);
    assert(rt_ai_session_destroy(&session) == RT_AI_OK);
}

static void test_bounded_reset_and_fallback(void)
{
    uint8_t arena[128];
    rt_ai_runtime_t runtime;
    mock_t dma = {0};
    mock_t cpu = {0};
    package_t blob = package(1U);
    rt_ai_aeg_t aeg;
    rt_ai_trust_bundle_t trust;
    rt_ai_evaluation_result_t evaluation;
    rt_ai_session_t session;
    rt_ai_job_t job;
    char trace_json[8192];
    size_t trace_json_size;
    blob.segments[0] = (rt_ai_aeg_segment_t){80U, RT_AI_RESOURCE_DMA, 0U, 0U, 0U, 64U};
    load_package(&blob, &aeg);
    aeg.wcet_us[0] = 5U;
    aeg.cancel_ack_timeout_us = 10U;
    aeg.reset_timeout_us = 10U;
    aeg.reinit_timeout_us = 10U;
    aeg.max_reset_attempts = 2U;
    aeg.fallback_segment_count = 1U;
    aeg.fallback_storage[0] = (rt_ai_aeg_segment_t){81U, RT_AI_RESOURCE_CPU, 0U, 0U, 0U, 64U};
    aeg.fallback_wcet_us[0] = 5U;
    authorize_fallback_package(&aeg, &trust);
    assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
    register_provider(&runtime, &dma, RT_AI_RESOURCE_DMA);
    register_provider(&runtime, &cpu, RT_AI_RESOURCE_CPU);
    dma.reinit_status = RT_AI_ERR_PROVIDER;
    runtime.providers[RT_AI_RESOURCE_DMA].reset_begin = mock_reset_begin;
    runtime.providers[RT_AI_RESOURCE_DMA].reset_poll = mock_reset_poll;
    runtime.providers[RT_AI_RESOURCE_DMA].reinit_poll = mock_reinit_poll;
    assert(rt_ai_session_create_v2(&runtime, &aeg, &trust, &evaluation, &session) == RT_AI_OK);
    submit_authorized(&session, &job, rt_ai_port_now_us());
    assert(poll_port_time(&runtime) == RT_AI_OK);
    assert(rt_ai_reset_device(&runtime, RT_AI_RESOURCE_DMA) == RT_AI_OK);
    assert(runtime.resource_state[RT_AI_RESOURCE_DMA] == RT_AI_RESOURCE_RESET_PENDING && job.lease.used);
    assert(poll_port_time(&runtime) == RT_AI_OK);
    assert(runtime.resource_state[RT_AI_RESOURCE_DMA] == RT_AI_RESOURCE_REINIT_PENDING);
    assert(poll_port_time(&runtime) == RT_AI_OK);
    assert(runtime.resource_state[RT_AI_RESOURCE_DMA] == RT_AI_RESOURCE_RESET_PENDING);
    assert(poll_port_time(&runtime) == RT_AI_OK);
    assert(poll_port_time(&runtime) == RT_AI_OK);
    assert(runtime.resource_state[RT_AI_RESOURCE_DMA] == RT_AI_RESOURCE_QUARANTINED && dma.resets == 2);
    assert(job.use_fallback && job.lease.used && runtime.active_job[RT_AI_RESOURCE_CPU] == &job);
    assert(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, cpu.epoch, cpu.cookie, RT_AI_OK) == RT_AI_OK);
    assert(rt_ai_poll(&runtime, runtime.active_started_us[RT_AI_RESOURCE_CPU] + aeg.fallback_wcet_us[0]) == RT_AI_OK);
    assert(rt_ai_wait(&job) == RT_AI_OK && !job.lease.used);
    assert(rt_ai_trace_json(&runtime, trace_json, sizeof(trace_json), &trace_json_size) == RT_AI_OK && trace_json_size > 0U);
    assert(strstr(trace_json, "\"event\":\"quarantine\"") != NULL && strstr(trace_json, "\"event\":\"fallback\"") != NULL);
    printf("TRACE_JSON %s\n", trace_json);
    assert(rt_ai_session_destroy(&session) == RT_AI_OK);

    memset(&dma, 0, sizeof(dma));
    memset(&cpu, 0, sizeof(cpu));
    aeg.fallback_wcet_us[0] = 2000000U;
    assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
    register_provider(&runtime, &dma, RT_AI_RESOURCE_DMA);
    register_provider(&runtime, &cpu, RT_AI_RESOURCE_CPU);
    dma.reinit_status = RT_AI_ERR_PROVIDER;
    runtime.providers[RT_AI_RESOURCE_DMA].reset_begin = mock_reset_begin;
    runtime.providers[RT_AI_RESOURCE_DMA].reset_poll = mock_reset_poll;
    runtime.providers[RT_AI_RESOURCE_DMA].reinit_poll = mock_reinit_poll;
    assert(rt_ai_session_create_v2(&runtime, &aeg, &trust, &evaluation, &session) == RT_AI_OK);
    submit_authorized(&session, &job, rt_ai_port_now_us());
    assert(poll_port_time(&runtime) == RT_AI_OK);
    assert(rt_ai_reset_device(&runtime, RT_AI_RESOURCE_DMA) == RT_AI_OK);
    assert(poll_port_time(&runtime) == RT_AI_OK);
    assert(poll_port_time(&runtime) == RT_AI_OK);
    assert(poll_port_time(&runtime) == RT_AI_OK);
    assert(poll_port_time(&runtime) == RT_AI_OK);
    assert(runtime.resource_state[RT_AI_RESOURCE_DMA] == RT_AI_RESOURCE_QUARANTINED);
    assert(!job.use_fallback && rt_ai_wait(&job) == RT_AI_ERR_TIMEOUT && !job.lease.used);
    assert(rt_ai_trace_json(&runtime, trace_json, sizeof(trace_json), &trace_json_size) == RT_AI_OK);
    assert(strstr(trace_json, "\"event\":\"fallback\",\"status\":-7") != NULL);
    assert(rt_ai_session_destroy(&session) == RT_AI_OK);

    memset(&dma, 0, sizeof(dma));
    memset(&cpu, 0, sizeof(cpu));
    aeg.fallback_wcet_us[0] = 5U;
    assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
    register_provider(&runtime, &dma, RT_AI_RESOURCE_DMA);
    register_provider(&runtime, &cpu, RT_AI_RESOURCE_CPU);
    dma.reinit_status = RT_AI_ERR_PROVIDER;
    runtime.providers[RT_AI_RESOURCE_DMA].reset_begin = mock_reset_begin;
    runtime.providers[RT_AI_RESOURCE_DMA].reset_poll = mock_reset_poll;
    runtime.providers[RT_AI_RESOURCE_DMA].reinit_poll = mock_reinit_poll;
    assert(rt_ai_session_create_v2(&runtime, &aeg, &trust, &evaluation, &session) == RT_AI_OK);
    submit_authorized(&session, &job, rt_ai_port_now_us());
    session.trust.model_sha256[0] ^= 1U;
    assert(poll_port_time(&runtime) == RT_AI_OK);
    assert(rt_ai_reset_device(&runtime, RT_AI_RESOURCE_DMA) == RT_AI_OK);
    assert(poll_port_time(&runtime) == RT_AI_OK);
    assert(poll_port_time(&runtime) == RT_AI_OK);
    assert(poll_port_time(&runtime) == RT_AI_OK);
    assert(poll_port_time(&runtime) == RT_AI_OK);
    assert(!job.use_fallback && rt_ai_wait(&job) == RT_AI_ERR_TIMEOUT && !job.lease.used);
    assert(rt_ai_trace_json(&runtime, trace_json, sizeof(trace_json), &trace_json_size) == RT_AI_OK);
    assert(strstr(trace_json, "\"event\":\"fallback\",\"status\":-9") != NULL);
    assert(rt_ai_session_destroy(&session) == RT_AI_OK);
}

static void test_stress_oracles(void)
{
    uint8_t arena[128];
    rt_ai_runtime_t runtime;
    rt_ai_aeg_t aeg;
    rt_ai_aeg_segment_t segment = {70U, RT_AI_RESOURCE_CPU, 0U, 0U, 0U, 64U};
    rt_ai_schedule_snapshot_t snapshot;
    rt_ai_arena_lease_t lease;
    rt_ai_trace_entry_t trace[RT_AI_TRACE_DEPTH];
    rt_ai_session_t session;
    rt_ai_job_t job;
    uint64_t finish;
    uint64_t dropped;
    uint16_t count;
    uint32_t generation;
    rt_ai_arena_lease_t held[RT_AI_MAX_LEASES] = {{0}};
    uint8_t shadow[sizeof(arena)] = {0};
    uint32_t random = 1U;
    unsigned index;
    memset(&aeg, 0, sizeof(aeg));
    aeg.header.segment_count = 1U;
    aeg.header.arena_size = 64U;
    aeg.segments = &segment;
    aeg.reservation_budget_us[RT_AI_RESOURCE_CPU] = 1000U;
    memset(&snapshot, 0, sizeof(snapshot));
    for (index = 0U; index < 10000U; ++index) {
        uint64_t expected_finish;
        aeg.wcet_us[0] = index % 97U + 1U;
        aeg.coherency_cost_us[0] = index % 3U;
        aeg.recovery_cost_us[0] = index % 5U;
        snapshot.now_us = index;
        finish = 0U;
        expected_finish = index + aeg.wcet_us[0] + aeg.coherency_cost_us[0] + aeg.recovery_cost_us[0];
        assert(rt_ai_sim_edf(&aeg, &snapshot, expected_finish, &finish) == RT_AI_OK);
        assert(finish == expected_finish);
        assert(rt_ai_sim_edf(&aeg, &snapshot, finish - 1U, &finish) == RT_AI_ERR_ADMISSION);
        assert(finish == expected_finish);
    }
    assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
    for (index = 0U; index < 100000U; ++index)
        assert(rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, 0U, index + 1U, RT_AI_OK) == RT_AI_ERR_STALE);
    for (index = 0U; index < 1000000U; ++index) {
        unsigned slot;
        random = random * UINT32_C(1664525) + UINT32_C(1013904223);
        slot = random % RT_AI_MAX_LEASES;
        if (held[slot].used) {
            size_t byte;
            for (byte = held[slot].offset; byte < held[slot].offset + held[slot].size; ++byte) { assert(shadow[byte]); shadow[byte] = 0U; }
            rt_ai_arena_release(&runtime, &held[slot]);
        } else {
            size_t requested = (random >> 8) % 24U + 1U;
            size_t expected = 0U;
            size_t byte;
            int found = 0;
            for (expected = 0U; expected + requested <= sizeof(arena); ++expected) {
                found = 1;
                for (byte = expected; byte < expected + requested; ++byte) if (shadow[byte]) found = 0;
                if (found) break;
            }
            if (found) {
                assert(rt_ai_arena_probe(&runtime, requested, &lease, &generation) == RT_AI_OK);
                assert(lease.offset == expected && rt_ai_arena_commit(&runtime, &lease, generation) == RT_AI_OK);
                held[slot] = lease;
                for (byte = lease.offset; byte < lease.offset + lease.size; ++byte) { assert(!shadow[byte]); shadow[byte] = 1U; }
            } else assert(rt_ai_arena_probe(&runtime, requested, &lease, &generation) == RT_AI_ERR_RESOURCE);
        }
    }
    for (index = 0U; index < RT_AI_MAX_LEASES; ++index) if (held[index].used) rt_ai_arena_release(&runtime, &held[index]);
    {
        rt_ai_arena_lease_t competing;
        uint32_t competing_generation;
        assert(rt_ai_arena_probe(&runtime, 64U, &lease, &generation) == RT_AI_OK);
        assert(rt_ai_arena_probe(&runtime, 64U, &competing, &competing_generation) == RT_AI_OK);
        assert(rt_ai_arena_commit(&runtime, &lease, generation) == RT_AI_OK);
        assert(rt_ai_arena_commit(&runtime, &competing, competing_generation) == RT_AI_BUSY);
        rt_ai_arena_release(&runtime, &lease);
    }
    memset(&session, 0, sizeof(session));
    memset(&job, 0, sizeof(job));
    session.aeg = aeg;
    job.session = &session;
    job.job_id = 1U;
    job.run_id = 2U;
    for (index = 0U; index < RT_AI_TRACE_DEPTH + 10U; ++index)
        rt_ai_trace(&runtime, index + 1U, &job, index, segment.id, RT_AI_RESOURCE_CPU, 1U, RT_AI_OK);
    assert(rt_ai_trace_snapshot(&runtime, trace, RT_AI_TRACE_DEPTH, &count, &dropped) == RT_AI_OK);
    assert(count == RT_AI_TRACE_DEPTH && dropped == 10U);
    for (index = 1U; index < count; ++index) assert(trace[index - 1U].sequence + 1U == trace[index].sequence);
}

int main(void)
{
    test_loader();
    test_evidence_policy();
    test_edf();
    test_dag_concurrency_and_cache();
    test_wcet_temporal_isolation();
    test_noncoherent_cache_model();
    test_timeout_cancel_reset_irq();
    test_admission();
    test_acknowledged_recovery();
    test_bounded_reset_and_fallback();
    test_stress_oracles();
    puts("AEG_PASS EVIDENCE_POLICY_PASS ASYNC_PASS DAG_PASS EDF_PASS WCET_ISOLATION_PASS ARENA_PASS CACHE_PASS CACHE_MODEL_PASS TIMEOUT_PASS CANCEL_PASS EPOCH_PASS IRQ_PASS ADMISSION_PASS RECOVERY_ACK_PASS QUARANTINE_PASS RESET_BOUND_PASS FALLBACK_PASS TRACE_V2_PASS STRESS_PASS");
    return 0;
}

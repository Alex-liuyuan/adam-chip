#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "soc_driver.h"
#include "rt_ai.h"
#include "soc_product.h"
#include "model_aeg.h"
#include "cecap_trust.h"

#define SOC_CAP_UART (1U << 0)
#define SOC_CAP_DMA (1U << 1)
#define SOC_CAP_AI (1U << 2)
#define SOC_CAP_RVV (1U << 3)

extern int soc_image_rvv_add_relu(const float *input, const float *constant, float *output, size_t count);

typedef struct {
    uint32_t epoch;
    uint32_t cookie;
    int submitted;
} ai_provider_state_t;

static int ai_submit(void *user, const rt_ai_aeg_segment_t *segment, uint32_t epoch, uint32_t cookie)
{
    ai_provider_state_t *state = (ai_provider_state_t *)user;
    if (segment->resource != RT_AI_RESOURCE_RVV) return RT_AI_ERR_PROVIDER;
    state->epoch = epoch;
    state->cookie = cookie;
    state->submitted = 1;
    return RT_AI_OK;
}

uint32_t soc_product_capabilities(void)
{
    return SOC_CAP_UART | SOC_CAP_DMA | SOC_CAP_AI | SOC_CAP_RVV;
}

int soc_product_uart_smoke(void)
{
    return soc_uart_putc('P', 8U);
}

int soc_product_dma_smoke(void)
{
    soc_dma_start(UINT32_C(0x1000), UINT32_C(0x2000), 64U);
    return soc_dma_wait(8U);
}

int soc_product_ai_smoke(void)
{
    uint8_t arena[128];
    float input[8] = {-4.0f, -3.0f, -2.0f, -1.0f, 0.0f, 1.0f, 2.0f, 3.0f};
    float constant[8] = {0.0f, 1.0f, 2.0f, 3.0f, 4.0f, 5.0f, 6.0f, 7.0f};
    float expected[8] = {0.0f, 0.0f, 0.0f, 2.0f, 4.0f, 6.0f, 8.0f, 10.0f};
    float output[8] = {0};
    rt_ai_runtime_t runtime;
    rt_ai_aeg_t aeg;
    rt_ai_session_t session;
    rt_ai_job_t job;
    rt_ai_provider_t provider;
    rt_ai_invocation_t invocation;
    rt_ai_submit_policy_t policy;
    rt_ai_admission_result_t admission;
    rt_ai_evaluation_result_t evaluation;
    ai_provider_state_t provider_state;
    unsigned index;
    memset(&provider, 0, sizeof(provider));
    memset(&invocation, 0, sizeof(invocation));
    memset(&policy, 0, sizeof(policy));
    memset(&provider_state, 0, sizeof(provider_state));
    if (rt_ai_load(soc_model_aeg, soc_model_aeg_size, &aeg) != RT_AI_OK) return -1;
    if (rt_ai_runtime_init(&runtime, arena, sizeof(arena)) != RT_AI_OK) return -2;
    provider.resource = RT_AI_RESOURCE_RVV;
    provider.submit = ai_submit;
    provider.user = &provider_state;
    if (rt_ai_provider_register(&runtime, &provider) != RT_AI_OK) return -3;
    if (rt_ai_session_create_v2(&runtime, &aeg, &soc_model_trust, &evaluation, &session) != RT_AI_OK) return -4;
    invocation.input = input;
    invocation.input_size = sizeof(input);
    invocation.output = output;
    invocation.output_size = sizeof(output);
    invocation.input_rank = 2U;
    invocation.input_dtype = 1U;
    invocation.input_layout = 1U;
    invocation.input_shape[0] = 1U;
    invocation.input_shape[1] = 8U;
    memcpy(invocation.plan_sha256, aeg.plan_sha256, sizeof(invocation.plan_sha256));
    policy.deadline_us = 100U;
    policy.run_id = 1U;
    policy.max_retries = 3U;
    if (rt_ai_submit_async_v2(&session, &invocation, &policy, &admission, &job) != RT_AI_OK) return -5;
    if (rt_ai_poll(&runtime, 1U) != RT_AI_OK || !provider_state.submitted) return -6;
    if (soc_image_rvv_add_relu(input, constant, output, 8U) != 0) return -7;
    if (rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_RVV, provider_state.epoch, provider_state.cookie, RT_AI_OK) != RT_AI_OK) return -8;
    if (rt_ai_wait(&job) != RT_AI_OK) return -9;
    for (index = 0U; index < 8U; ++index) if (output[index] != expected[index]) return -10;
    return rt_ai_session_destroy(&session);
}

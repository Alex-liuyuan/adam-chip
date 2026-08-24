#include <assert.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rt_ai_internal.h"

enum { CANCEL_ERROR, RESET_BEGIN_ERROR, RESET_POLL_ERROR, REINIT_ERROR, POLL_TIMEOUT, HEALTHY, HEALTH_ERROR };
enum { GATE_NORMAL, GATE_EVIDENCE, GATE_PROVIDER, GATE_LEASE, GATE_SCHEDULE };

typedef struct {
    int mode;
    float input[8];
    float constant[8];
    float output[8];
    uint32_t epoch;
    uint32_t cookie;
    unsigned resets;
    atomic_uint submissions;
} provider_t;

static int submit(void *opaque, const rt_ai_aeg_segment_t *segment, uint32_t epoch, uint32_t cookie)
{
    provider_t *provider = (provider_t *)opaque;
    unsigned index;
    provider->epoch = epoch;
    provider->cookie = cookie;
    for (index = 0U; index < 8U; ++index) {
        float value = provider->input[index] + provider->constant[index];
        provider->output[index] = value > 0.0f ? value : 0.0f;
    }
    atomic_fetch_add(&provider->submissions, 1U);
    return segment->arena_size == 0U ? RT_AI_ERR_PROVIDER : RT_AI_OK;
}
static int cancel_begin(void *opaque, uint32_t epoch, uint32_t cookie)
{
    provider_t *provider = (provider_t *)opaque;
    (void)epoch; (void)cookie;
    return provider->mode == CANCEL_ERROR ? RT_AI_ERR_PROVIDER : RT_AI_OK;
}
static int cancel_poll(void *opaque, uint32_t epoch, uint32_t cookie)
{
    provider_t *provider = (provider_t *)opaque;
    (void)epoch; (void)cookie;
    return provider->mode == POLL_TIMEOUT ? RT_AI_BUSY : RT_AI_ERR_PROVIDER;
}
static int reset_begin(void *opaque, uint32_t epoch)
{
    provider_t *provider = (provider_t *)opaque;
    provider->epoch = epoch;
    ++provider->resets;
    return provider->mode == RESET_BEGIN_ERROR ? RT_AI_ERR_PROVIDER : RT_AI_OK;
}
static int reset_poll(void *opaque, uint32_t epoch)
{
    provider_t *provider = (provider_t *)opaque;
    (void)epoch;
    if (provider->mode == RESET_POLL_ERROR) return RT_AI_ERR_PROVIDER;
    if (provider->mode == POLL_TIMEOUT) return RT_AI_BUSY;
    return RT_AI_OK;
}
static int reinit_poll(void *opaque, uint32_t epoch)
{
    provider_t *provider = (provider_t *)opaque;
    (void)epoch;
    if (provider->mode == REINIT_ERROR) return RT_AI_ERR_PROVIDER;
    if (provider->mode == POLL_TIMEOUT) return RT_AI_BUSY;
    return RT_AI_OK;
}
static int health(void *opaque) { return ((provider_t *)opaque)->mode == HEALTH_ERROR ? RT_AI_ERR_PROVIDER : RT_AI_OK; }
static int range_action(void *opaque, void *address, size_t size)
{
    (void)opaque;
    if (address == NULL || size == 0U) return RT_AI_ERR_PROVIDER;
    atomic_thread_fence(memory_order_seq_cst);
    return RT_AI_OK;
}
static int barrier(void *opaque) { (void)opaque; atomic_thread_fence(memory_order_seq_cst); return RT_AI_OK; }

static int load_aeg(const char *path, rt_ai_aeg_t *aeg)
{
    uint8_t blob[4096];
    FILE *stream = fopen(path, "rb");
    size_t size;
    if (stream == NULL) return 0;
    size = fread(blob, 1U, sizeof(blob), stream);
    fclose(stream);
    return rt_ai_load(blob, size, aeg) == RT_AI_OK;
}

static void make_trust(const rt_ai_aeg_t *aeg, rt_ai_trust_bundle_t *trust)
{
    unsigned index;
    memset(trust, 0, sizeof(*trust));
    memcpy(trust->plan_sha256, aeg->plan_sha256, 32U);
    memcpy(trust->evidence_sha256, aeg->evidence_sha256, 32U);
    memcpy(trust->policy_sha256, aeg->policy_sha256, 32U);
    memcpy(trust->model_sha256, aeg->model_sha256, 32U);
    memcpy(trust->target_sha256, aeg->target_sha256, 32U);
    memcpy(trust->runtime_abi_sha256, aeg->runtime_abi_sha256, 32U);
    memcpy(trust->provider_abi_sha256, aeg->provider_abi_sha256, 32U);
    trust->obligation_count = aeg->evidence_count;
    trust->allowed_verifier_count = aeg->evidence_count;
    for (index = 0U; index < aeg->evidence_count; ++index) {
        memcpy(trust->obligation_sha256[index], aeg->obligation_sha256[index], 32U);
        memcpy(trust->scope_sha256[index], aeg->scope_sha256[index], 32U);
        memcpy(trust->artifact_sha256[index], aeg->artifact_sha256[index], 32U);
        memcpy(trust->verifier_sha256[index], aeg->verifier_sha256[index], 32U);
        memcpy(trust->allowed_verifier_sha256[index], aeg->verifier_sha256[index], 32U);
        trust->evidence_resource[index] = aeg->evidence_resource[index];
    }
}

static void register_provider(rt_ai_runtime_t *runtime, provider_t *state, uint8_t resource)
{
    rt_ai_provider_t provider;
    memset(&provider, 0, sizeof(provider));
    provider.resource = resource;
    provider.submit = submit;
    provider.cancel_begin = cancel_begin;
    provider.cancel_poll = cancel_poll;
    provider.reset_begin = reset_begin;
    provider.reset_poll = reset_poll;
    provider.reinit_poll = reinit_poll;
    provider.health = health;
    provider.clean_range = range_action;
    provider.invalidate_range = range_action;
    provider.barrier = barrier;
    provider.user = state;
    assert(rt_ai_provider_register(runtime, &provider) == RT_AI_OK);
}

static void capture_trace(const rt_ai_runtime_t *runtime, uint16_t *event, int *status)
{
    uint64_t start = runtime->trace_sequence > RT_AI_TRACE_DEPTH ? runtime->trace_sequence - RT_AI_TRACE_DEPTH : 0U;
    uint64_t sequence;
    if (event == NULL || status == NULL) return;
    *event = 0U; *status = RT_AI_OK;
    for (sequence = start; sequence < runtime->trace_sequence; ++sequence) {
        const rt_ai_trace_entry_t *entry = &runtime->trace[sequence % RT_AI_TRACE_DEPTH];
        if (entry->event == RT_AI_TRACE_FALLBACK && entry->status != RT_AI_OK) {
            *event = entry->event;
            *status = entry->status;
            return;
        }
        if (*event == 0U && entry->event >= RT_AI_TRACE_CANCEL_ERROR) {
            *event = entry->event;
            *status = entry->status;
        }
    }
}

static int episode(const rt_ai_aeg_t *base, const rt_ai_trust_bundle_t *trust, int mode,
    uint32_t reset_limit, int gate, uint16_t *observed_event, int *observed_status,
    unsigned noise_events, uint64_t *observed_dropped)
{
    uint8_t arena[128] = {0};
    rt_ai_runtime_t runtime;
    rt_ai_session_t session;
    rt_ai_evaluation_result_t evaluation;
    rt_ai_admission_result_t result;
    rt_ai_job_t job;
    rt_ai_invocation_t invocation;
    rt_ai_submit_policy_t policy = {1U, 1U + base->relative_deadline_us, 1U, 4U};
    provider_t primary = {.mode = mode};
    provider_t fallback = {.mode = HEALTHY};
    uint64_t now = 1U;
    unsigned index;
    assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
    register_provider(&runtime, &primary, RT_AI_RESOURCE_RVV);
    register_provider(&runtime, &fallback, RT_AI_RESOURCE_CPU);
    if (rt_ai_session_create_v2(&runtime, base, trust, &evaluation, &session) != RT_AI_OK) return 1;
    for (index = 0U; index < noise_events; ++index) {
        static const uint16_t events[] = {RT_AI_TRACE_DOMAIN_REJECT, RT_AI_TRACE_EVIDENCE_REJECT,
            RT_AI_TRACE_PROVIDER_REJECT, RT_AI_TRACE_MEMORY_REJECT, RT_AI_TRACE_DEADLINE_REJECT,
            RT_AI_TRACE_RETRY_REJECT};
        rt_ai_trace_decision(&runtime, now, &session, policy.run_id, (uint8_t)(index % RT_AI_MAX_RESOURCES),
            events[index % (sizeof(events) / sizeof(events[0]))], RT_AI_ERR_ADMISSION);
    }
    memset(&invocation, 0, sizeof(invocation));
    invocation.input = primary.input; invocation.input_size = sizeof(primary.input);
    invocation.output = primary.output; invocation.output_size = sizeof(primary.output);
    memcpy(invocation.input_shape, base->input_shape, sizeof(invocation.input_shape));
    invocation.input_rank = base->input_rank; invocation.input_dtype = base->input_dtype; invocation.input_layout = base->input_layout;
    memcpy(invocation.plan_sha256, base->plan_sha256, 32U);
    if (rt_ai_submit_async_v2(&session, &invocation, &policy, &result, &job) != RT_AI_OK ||
        rt_ai_poll(&runtime, now) != RT_AI_OK || atomic_load(&primary.submissions) != 1U)
        return 1;
    session.aeg.max_reset_attempts = reset_limit;
    if (gate == GATE_EVIDENCE) session.trust_valid = 0U;
    else if (gate == GATE_PROVIDER) fallback.mode = HEALTH_ERROR;
    else if (gate == GATE_LEASE) rt_ai_arena_release(&runtime, &job.lease);
    else if (gate == GATE_SCHEDULE) session.aeg.fallback_wcet_us[0] = (uint32_t)job.deadline_us;
    if (mode == CANCEL_ERROR) {
        if (rt_ai_cancel(&job) != RT_AI_OK) return 1;
    } else if (rt_ai_reset_device(&runtime, RT_AI_RESOURCE_RVV) != RT_AI_OK) return 1;
    for (index = 0U; index < 32U && job.recovering; ++index) {
        now = mode == POLL_TIMEOUT ? runtime.recovery_deadline_us[RT_AI_RESOURCE_RVV] : now + 1U;
        (void)rt_ai_poll(&runtime, now);
    }
    if (mode == CANCEL_ERROR) {
        capture_trace(&runtime, observed_event, observed_status);
        if (observed_dropped != NULL) *observed_dropped = runtime.trace_dropped;
        return job.state == RT_AI_JOB_CANCELLED && !job.recovering && primary.resets == 1U ? 0 : 1;
    }
    if (gate != GATE_NORMAL) {
        capture_trace(&runtime, observed_event, observed_status);
        if (observed_dropped != NULL) *observed_dropped = runtime.trace_dropped;
        return job.state == RT_AI_JOB_FAILED && !job.recovering && !job.use_fallback ? 0 : 1;
    }
    if (mode == POLL_TIMEOUT) {
        capture_trace(&runtime, observed_event, observed_status);
        if (observed_dropped != NULL) *observed_dropped = runtime.trace_dropped;
        return job.state == RT_AI_JOB_FAILED && !job.recovering && !job.use_fallback &&
            runtime.resource_state[RT_AI_RESOURCE_RVV] == RT_AI_RESOURCE_QUARANTINED &&
            primary.resets == reset_limit ? 0 : 1;
    }
    if (job.recovering || !job.use_fallback || runtime.resource_state[RT_AI_RESOURCE_RVV] != RT_AI_RESOURCE_QUARANTINED ||
        primary.resets != reset_limit)
        return 1;
    if (rt_ai_poll(&runtime, now) != RT_AI_OK || atomic_load(&fallback.submissions) != 1U ||
        rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, fallback.epoch, fallback.cookie, RT_AI_OK) != RT_AI_OK ||
        rt_ai_wait(&job) != RT_AI_OK)
        return 1;
    capture_trace(&runtime, observed_event, observed_status);
    if (observed_dropped != NULL) *observed_dropped = runtime.trace_dropped;
    return 0;
}

static int predicted_class(uint16_t event, int status)
{
    if (event == RT_AI_TRACE_CANCEL_ERROR) return 0;
    if (event == RT_AI_TRACE_RESET_BEGIN_ERROR) return 1;
    if (event == RT_AI_TRACE_RESET_POLL_ERROR) return 2;
    if (event == RT_AI_TRACE_REINIT_ERROR) return 3;
    if (event == RT_AI_TRACE_RECOVERY_TIMEOUT) return 4;
    if (event == RT_AI_TRACE_FALLBACK && status == RT_AI_ERR_EVIDENCE) return 5;
    if (event == RT_AI_TRACE_FALLBACK && status == RT_AI_ERR_PROVIDER) return 6;
    if (event == RT_AI_TRACE_FALLBACK && status == RT_AI_ERR_ADMISSION) return 7;
    return -1;
}

static int status_only_class(int status)
{
    if (status == RT_AI_ERR_EVIDENCE) return 5;
    if (status == RT_AI_ERR_ADMISSION) return 7;
    if (status == RT_AI_BUSY) return 4;
    return status == RT_AI_ERR_PROVIDER ? 0 : -1;
}

static double macro_f1(const unsigned confusion[8][8])
{
    unsigned label, other;
    double total = 0.0;
    for (label = 0U; label < 8U; ++label) {
        unsigned tp = confusion[label][label], fp = 0U, fn = 0U;
        for (other = 0U; other < 8U; ++other) if (other != label) {
            fp += confusion[other][label];
            fn += confusion[label][other];
        }
        if (2U * tp + fp + fn != 0U) total += 2.0 * (double)tp / (double)(2U * tp + fp + fn);
    }
    return total / 8.0;
}

static int run_budget_matrix(const rt_ai_aeg_t *aeg, const rt_ai_trust_bundle_t *trust, unsigned repetitions)
{
    static const uint32_t limits[] = {1U, 2U, 3U, 5U};
    static const int modes[] = {RESET_BEGIN_ERROR, RESET_POLL_ERROR, REINIT_ERROR, POLL_TIMEOUT};
    static const char *names[] = {"reset_begin_error", "reset_poll_error", "reinit_error", "poll_timeout"};
    unsigned limit, mode, iteration, failures = 0U;
    for (limit = 0U; limit < sizeof(limits) / sizeof(limits[0]); ++limit)
        for (mode = 0U; mode < sizeof(modes) / sizeof(modes[0]); ++mode) {
            unsigned class_failures = 0U;
            for (iteration = 0U; iteration < repetitions; ++iteration)
                class_failures += episode(aeg, trust, modes[mode], limits[limit], GATE_NORMAL, NULL, NULL, 0U, NULL);
            failures += class_failures;
            printf("RECOVERY_BUDGET k=%u class=%s episodes=%u failures=%u\n",
                limits[limit], names[mode], repetitions, class_failures);
        }
    return failures == 0U ? 0 : 1;
}

static int run_fallback_gates(const rt_ai_aeg_t *aeg, const rt_ai_trust_bundle_t *trust, unsigned repetitions)
{
    static const int gates[] = {GATE_EVIDENCE, GATE_PROVIDER, GATE_LEASE, GATE_SCHEDULE};
    static const char *names[] = {"evidence", "provider", "active_lease", "simedf"};
    unsigned gate, iteration, failures = 0U;
    for (gate = 0U; gate < sizeof(gates) / sizeof(gates[0]); ++gate) {
        unsigned class_failures = 0U;
        for (iteration = 0U; iteration < repetitions; ++iteration)
            class_failures += episode(aeg, trust, RESET_POLL_ERROR, 2U, gates[gate], NULL, NULL, 0U, NULL);
        failures += class_failures;
        printf("FALLBACK_GATE gate=%s episodes=%u bypasses=%u\n", names[gate], repetitions, class_failures);
    }
    return failures == 0U ? 0 : 1;
}

static int run_trace_corpus(const rt_ai_aeg_t *aeg, const rt_ai_trust_bundle_t *trust, unsigned repetitions)
{
    static const int modes[] = {CANCEL_ERROR, RESET_BEGIN_ERROR, RESET_POLL_ERROR, REINIT_ERROR, POLL_TIMEOUT,
        RESET_POLL_ERROR, RESET_POLL_ERROR, RESET_POLL_ERROR};
    static const int gates[] = {GATE_NORMAL, GATE_NORMAL, GATE_NORMAL, GATE_NORMAL, GATE_NORMAL,
        GATE_EVIDENCE, GATE_PROVIDER, GATE_SCHEDULE};
    unsigned trace_confusion[8][8] = {{0}}, status_confusion[8][8] = {{0}};
    unsigned truth, iteration, failures = 0U, top3_hits = 0U;
    for (truth = 0U; truth < 8U; ++truth)
        for (iteration = 0U; iteration < repetitions; ++iteration) {
            uint16_t event = 0U;
            int status = RT_AI_OK;
            int predicted, status_predicted;
            failures += episode(aeg, trust, modes[truth], 2U, gates[truth], &event, &status, 0U, NULL);
            predicted = predicted_class(event, status);
            status_predicted = status_only_class(status);
            if (predicted >= 0) ++trace_confusion[truth][(unsigned)predicted];
            if (status_predicted >= 0) ++status_confusion[truth][(unsigned)status_predicted];
            if (predicted == (int)truth) ++top3_hits;
            printf("TRACE_CASE truth=%u event=%u status=%d predicted=%d\n", truth, event, status, predicted);
        }
    printf("TRACE_CLASSIFIER cases=%u macro_f1=%.6f top3_recall=%.6f status_only_macro_f1=%.6f gate_bypass=%u\n",
        8U * repetitions, macro_f1(trace_confusion), (double)top3_hits / (double)(8U * repetitions),
        macro_f1(status_confusion), failures);
    return failures == 0U && macro_f1(trace_confusion) >= 0.90 &&
        (double)top3_hits / (double)(8U * repetitions) >= 0.95 ? 0 : 1;
}

static int run_trace_robustness(const rt_ai_aeg_t *aeg, const rt_ai_trust_bundle_t *trust, unsigned repetitions)
{
    static const int modes[] = {CANCEL_ERROR, RESET_BEGIN_ERROR, RESET_POLL_ERROR, REINIT_ERROR, POLL_TIMEOUT,
        RESET_POLL_ERROR, RESET_POLL_ERROR, RESET_POLL_ERROR};
    static const int gates[] = {GATE_NORMAL, GATE_NORMAL, GATE_NORMAL, GATE_NORMAL, GATE_NORMAL,
        GATE_EVIDENCE, GATE_PROVIDER, GATE_SCHEDULE};
    unsigned confusion[8][8] = {{0}};
    unsigned truth, iteration, failures = 0U, classified = 0U, wrapped = 0U;
    for (truth = 0U; truth < 8U; ++truth)
        for (iteration = 0U; iteration < repetitions; ++iteration) {
            uint16_t event = 0U;
            int status = RT_AI_OK;
            uint64_t dropped = 0U;
            int predicted;
            failures += episode(aeg, trust, modes[truth], 2U, gates[truth], &event, &status,
                65U + iteration % 64U, &dropped);
            predicted = predicted_class(event, status);
            if (predicted >= 0) {
                ++confusion[truth][(unsigned)predicted];
                if (predicted == (int)truth) ++classified;
            }
            if (dropped != 0U) ++wrapped;
        }
    printf("TRACE_ROBUSTNESS cases=%u noise_events=65..128 wrapped=%u macro_f1=%.6f accuracy=%.6f failures=%u\n",
        8U * repetitions, wrapped, macro_f1(confusion), (double)classified / (double)(8U * repetitions), failures);
    return failures == 0U && wrapped == 8U * repetitions && macro_f1(confusion) >= 0.90 &&
        (double)classified / (double)(8U * repetitions) >= 0.95 ? 0 : 1;
}

int main(int argc, char **argv)
{
    static const char *names[] = {"cancel_error", "reset_begin_error", "reset_poll_error", "reinit_error", "poll_timeout"};
    rt_ai_aeg_t aeg;
    rt_ai_trust_bundle_t trust;
    unsigned repetitions;
    unsigned mode;
    unsigned failures[5] = {0};
    unsigned iteration;
    const char *command = "legacy";
    const char *path;
    if (argc == 3) path = argv[1];
    else if (argc == 4) { command = argv[1]; path = argv[2]; }
    else return 2;
    if (!load_aeg(path, &aeg)) return 2;
    repetitions = (unsigned)strtoul(argv[argc - 1], NULL, 10);
    if (repetitions == 0U) return 2;
    make_trust(&aeg, &trust);
    if (strcmp(command, "budget") == 0) return run_budget_matrix(&aeg, &trust, repetitions);
    if (strcmp(command, "gates") == 0) return run_fallback_gates(&aeg, &trust, repetitions);
    if (strcmp(command, "trace") == 0) return run_trace_corpus(&aeg, &trust, repetitions);
    if (strcmp(command, "trace_robust") == 0) return run_trace_robustness(&aeg, &trust, repetitions);
    if (strcmp(command, "legacy") != 0) return 2;
    for (mode = 0U; mode < 5U; ++mode) {
        for (iteration = 0U; iteration < repetitions; ++iteration)
            failures[mode] += episode(&aeg, &trust, (int)mode, aeg.max_reset_attempts, GATE_NORMAL,
                NULL, NULL, 0U, NULL);
        printf("RECOVERY class=%s episodes=%u failures=%u\n", names[mode], repetitions, failures[mode]);
    }
    for (mode = 0U; mode < 5U; ++mode) if (failures[mode] != 0U) return 1;
    return 0;
}

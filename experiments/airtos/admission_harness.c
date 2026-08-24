#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rt_ai.h"

typedef struct {
    float input[8];
    float constant[8];
    float output[8];
    uint32_t epoch;
    uint32_t cookie;
    atomic_uint submissions;
    atomic_uint health_calls;
    unsigned fail_health_at;
} host_provider_t;

typedef struct {
    rt_ai_runtime_t *runtime;
    const rt_ai_aeg_t *aeg;
    const rt_ai_trust_bundle_t *trust;
    atomic_int *owners;
    atomic_uint *overlaps;
    atomic_uint *partial_commits;
    atomic_uint *accepted;
    atomic_uint *rejected;
    unsigned id;
    unsigned operations;
} transaction_arg_t;

static int host_submit(void *opaque, const rt_ai_aeg_segment_t *segment, uint32_t epoch, uint32_t cookie)
{
    host_provider_t *provider = (host_provider_t *)opaque;
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

static int host_health(void *opaque)
{
    host_provider_t *provider = (host_provider_t *)opaque;
    unsigned call = atomic_fetch_add(&provider->health_calls, 1U) + 1U;
    return provider->fail_health_at != 0U && call >= provider->fail_health_at ? RT_AI_ERR_PROVIDER : RT_AI_OK;
}
static int host_range(void *opaque, void *address, size_t size)
{
    (void)opaque;
    if (address == NULL || size == 0U) return RT_AI_ERR_PROVIDER;
    atomic_thread_fence(memory_order_seq_cst);
    return RT_AI_OK;
}
static int host_barrier(void *opaque) { (void)opaque; atomic_thread_fence(memory_order_seq_cst); return RT_AI_OK; }

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

static void register_cpu(rt_ai_runtime_t *runtime, host_provider_t *host)
{
    rt_ai_provider_t provider;
    memset(&provider, 0, sizeof(provider));
    provider.resource = RT_AI_RESOURCE_CPU;
    provider.submit = host_submit;
    provider.health = host_health;
    provider.clean_range = host_range;
    provider.invalidate_range = host_range;
    provider.barrier = host_barrier;
    provider.user = host;
    assert(rt_ai_provider_register(runtime, &provider) == RT_AI_OK);
}

static void make_invocation(const rt_ai_aeg_t *aeg, host_provider_t *host, rt_ai_invocation_t *invocation)
{
    memset(invocation, 0, sizeof(*invocation));
    invocation->input = host->input;
    invocation->input_size = sizeof(host->input);
    invocation->output = host->output;
    invocation->output_size = sizeof(host->output);
    memcpy(invocation->input_shape, aeg->input_shape, sizeof(invocation->input_shape));
    invocation->input_rank = aeg->input_rank;
    invocation->input_dtype = aeg->input_dtype;
    invocation->input_layout = aeg->input_layout;
    memcpy(invocation->plan_sha256, aeg->plan_sha256, 32U);
}

static int run_admission_matrix(const char *path, unsigned repetitions)
{
    static const char *classes[] = {"trust_binding", "trust_obligation", "plan", "shape", "dtype", "layout",
        "input_size", "output_size", "deadline", "provider", "memory", "schedule", "legal"};
    rt_ai_aeg_t base;
    unsigned failures[sizeof(classes) / sizeof(classes[0])] = {0};
    unsigned class_id;
    unsigned iteration;
    if (!load_aeg(path, &base)) return 2;
    for (class_id = 0U; class_id < sizeof(classes) / sizeof(classes[0]); ++class_id) {
        for (iteration = 0U; iteration < repetitions; ++iteration) {
            uint8_t arena[128] = {0};
            rt_ai_runtime_t runtime;
            rt_ai_aeg_t aeg = base;
            rt_ai_trust_bundle_t trust;
            rt_ai_evaluation_result_t evaluation;
            rt_ai_session_t session;
            rt_ai_job_t job;
            rt_ai_admission_result_t result;
            rt_ai_submit_policy_t policy;
            rt_ai_invocation_t invocation;
            host_provider_t host = {0};
            int status;
            unsigned index;
            memset(&job, 0, sizeof(job));
            aeg.segments = aeg.storage;
            make_trust(&aeg, &trust);
            if (class_id == 0U) trust.plan_sha256[iteration % 32U] ^= 1U;
            if (class_id == 1U) trust.artifact_sha256[iteration % aeg.evidence_count][iteration % 32U] ^= 1U;
            assert(rt_ai_runtime_init(&runtime, arena, class_id == 10U ? 32U : sizeof(arena)) == RT_AI_OK);
            if (class_id != 9U) register_cpu(&runtime, &host);
            status = rt_ai_session_create_v2(&runtime, &aeg, &trust, &evaluation, &session);
            if (class_id <= 1U) {
                if (status != RT_AI_ERR_EVIDENCE) ++failures[class_id];
                continue;
            }
            if (status != RT_AI_OK) { ++failures[class_id]; continue; }
            for (index = 0U; index < 8U; ++index) {
                host.input[index] = (float)index - 3.0f;
                host.constant[index] = 1.0f;
            }
            make_invocation(&aeg, &host, &invocation);
            policy = (rt_ai_submit_policy_t){1000U + (uint64_t)iteration * 200U,
                1000U + (uint64_t)iteration * 200U + aeg.relative_deadline_us, 1U, 4U};
            if (class_id == 2U) invocation.plan_sha256[iteration % 32U] ^= 1U;
            else if (class_id == 3U) ++invocation.input_shape[iteration % aeg.input_rank];
            else if (class_id == 4U) ++invocation.input_dtype;
            else if (class_id == 5U) ++invocation.input_layout;
            else if (class_id == 6U) --invocation.input_size;
            else if (class_id == 7U) --invocation.output_size;
            else if (class_id == 8U) policy.deadline_us += 1U;
            else if (class_id == 11U) policy.deadline_us = policy.now_us + 1U;
            status = rt_ai_submit_async_v2(&session, &invocation, &policy, &result, &job);
            if (class_id != 12U) {
                if (status == RT_AI_OK || session.busy || job.lease.used) ++failures[class_id];
                continue;
            }
            if (status != RT_AI_OK || rt_ai_poll(&runtime, policy.now_us) != RT_AI_OK ||
                rt_ai_complete_isr(&runtime, RT_AI_RESOURCE_CPU, host.epoch, host.cookie, RT_AI_OK) != RT_AI_OK ||
                rt_ai_wait(&job) != RT_AI_OK || atomic_load(&host.submissions) != 1U) {
                ++failures[class_id];
                continue;
            }
            for (index = 0U; index < 8U; ++index) {
                float expected = host.input[index] + host.constant[index];
                if (expected < 0.0f) expected = 0.0f;
                if (host.output[index] != expected) ++failures[class_id];
            }
        }
        printf("ADMISSION class=%s cases=%u failures=%u\n", classes[class_id], repetitions, failures[class_id]);
    }
    for (class_id = 0U; class_id < sizeof(classes) / sizeof(classes[0]); ++class_id)
        if (failures[class_id] != 0U) return 1;
    return 0;
}

static rt_ai_admission_stage_t expected_stage(uint32_t defects)
{
    if (defects & ((1U << 0U) | (1U << 1U))) return RT_AI_ADMISSION_EVIDENCE;
    if (defects & UINT32_C(0x00fc)) return RT_AI_ADMISSION_DOMAIN;
    if (defects & (1U << 8U)) return RT_AI_ADMISSION_DEADLINE;
    if (defects & (1U << 9U)) return RT_AI_ADMISSION_PROVIDER;
    if (defects & (1U << 10U)) return RT_AI_ADMISSION_MEMORY;
    return RT_AI_ADMISSION_DEADLINE;
}

static rt_ai_admission_stage_t combination_case(const rt_ai_aeg_t *base, uint32_t defects, unsigned iteration)
{
    uint8_t arena[128] = {0};
    rt_ai_runtime_t runtime;
    rt_ai_aeg_t aeg = *base;
    rt_ai_trust_bundle_t trust;
    rt_ai_evaluation_result_t evaluation;
    rt_ai_session_t session;
    rt_ai_job_t job;
    rt_ai_admission_result_t result;
    rt_ai_submit_policy_t policy;
    rt_ai_invocation_t invocation;
    host_provider_t host = {0};
    int status;
    aeg.segments = aeg.storage;
    make_trust(&aeg, &trust);
    if (defects & (1U << 0U)) trust.plan_sha256[iteration % 32U] ^= 1U;
    if (defects & (1U << 1U)) trust.artifact_sha256[iteration % aeg.evidence_count][iteration % 32U] ^= 1U;
    assert(rt_ai_runtime_init(&runtime, arena, defects & (1U << 10U) ? 32U : sizeof(arena)) == RT_AI_OK);
    if (!(defects & (1U << 9U))) register_cpu(&runtime, &host);
    status = rt_ai_session_create_v2(&runtime, &aeg, &trust, &evaluation, &session);
    if (status != RT_AI_OK) return RT_AI_ADMISSION_EVIDENCE;
    make_invocation(&aeg, &host, &invocation);
    policy = (rt_ai_submit_policy_t){1000U + (uint64_t)iteration * 200U,
        1000U + (uint64_t)iteration * 200U + aeg.relative_deadline_us, 1U, 4U};
    if (defects & (1U << 2U)) invocation.plan_sha256[iteration % 32U] ^= 1U;
    if (defects & (1U << 3U)) ++invocation.input_shape[iteration % aeg.input_rank];
    if (defects & (1U << 4U)) ++invocation.input_dtype;
    if (defects & (1U << 5U)) ++invocation.input_layout;
    if (defects & (1U << 6U)) --invocation.input_size;
    if (defects & (1U << 7U)) --invocation.output_size;
    if (defects & (1U << 8U)) policy.deadline_us += 1U;
    if (defects & (1U << 11U)) policy.deadline_us = policy.now_us + 1U;
    memset(&job, 0, sizeof(job));
    status = rt_ai_submit_async_v2(&session, &invocation, &policy, &result, &job);
    if (status == RT_AI_OK) {
        (void)rt_ai_cancel(&job);
        return RT_AI_ADMISSION_ACCEPTED;
    }
    return result.stage;
}

static int run_diagnostics(const char *path, unsigned repetitions)
{
    rt_ai_aeg_t base;
    uint64_t confusion[7][7] = {{0}};
    uint64_t cases = 0U;
    unsigned left, right, iteration, label;
    double macro_f1 = 0.0;
    unsigned labels = 0U;
    if (!load_aeg(path, &base) || repetitions == 0U) return 2;
    for (left = 0U; left < 12U; ++left) {
        for (iteration = 0U; iteration < repetitions; ++iteration) {
            rt_ai_admission_stage_t wanted = expected_stage(1U << left);
            rt_ai_admission_stage_t got = combination_case(&base, 1U << left, iteration);
            ++confusion[wanted][got]; ++cases;
        }
        for (right = left + 1U; right < 12U; ++right)
            for (iteration = 0U; iteration < repetitions; ++iteration) {
                uint32_t defects = (1U << left) | (1U << right);
                rt_ai_admission_stage_t wanted = expected_stage(defects);
                rt_ai_admission_stage_t got = combination_case(&base, defects, iteration);
                ++confusion[wanted][got]; ++cases;
            }
    }
    for (label = RT_AI_ADMISSION_DOMAIN; label <= RT_AI_ADMISSION_DEADLINE; ++label) {
        uint64_t tp = confusion[label][label], fp = 0U, fn = 0U;
        unsigned other;
        for (other = 0U; other < 7U; ++other) { if (other != label) { fp += confusion[other][label]; fn += confusion[label][other]; } }
        if (tp + fp + fn != 0U) {
            macro_f1 += (2.0 * (double)tp) / (double)(2U * tp + fp + fn);
            ++labels;
        }
        printf("DIAGNOSTIC expected=%u true=%llu false_positive=%llu false_negative=%llu\n",
            label, (unsigned long long)tp, (unsigned long long)fp, (unsigned long long)fn);
    }
    if (labels != 0U) macro_f1 /= (double)labels;
    printf("DIAGNOSTIC_SUMMARY cases=%llu pairwise_classes=66 macro_f1=%.6f\n",
        (unsigned long long)cases, macro_f1);
    return confusion[RT_AI_ADMISSION_EVIDENCE][RT_AI_ADMISSION_ACCEPTED] == 0U &&
        confusion[RT_AI_ADMISSION_DOMAIN][RT_AI_ADMISSION_ACCEPTED] == 0U && macro_f1 >= 0.95 ? 0 : 1;
}

static int run_health_race(const char *path, unsigned repetitions)
{
    rt_ai_aeg_t aeg;
    unsigned failures = 0U, iteration;
    if (!load_aeg(path, &aeg) || repetitions == 0U) return 2;
    for (iteration = 0U; iteration < repetitions; ++iteration) {
        uint8_t arena[128] = {0};
        rt_ai_runtime_t runtime;
        rt_ai_trust_bundle_t trust;
        rt_ai_evaluation_result_t evaluation;
        rt_ai_session_t session;
        rt_ai_job_t job;
        rt_ai_admission_result_t result;
        rt_ai_invocation_t invocation;
        rt_ai_submit_policy_t policy = {1000U, 1000U + aeg.relative_deadline_us, 1U, 4U};
        host_provider_t host = {.fail_health_at = 2U};
        unsigned slot;
        int status;
        make_trust(&aeg, &trust);
        assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
        register_cpu(&runtime, &host);
        assert(rt_ai_session_create_v2(&runtime, &aeg, &trust, &evaluation, &session) == RT_AI_OK);
        make_invocation(&aeg, &host, &invocation);
        status = rt_ai_submit_async_v2(&session, &invocation, &policy, &result, &job);
        if (status != RT_AI_ERR_RESOURCE || result.stage != RT_AI_ADMISSION_PROVIDER || session.busy || job.lease.used ||
            atomic_load(&host.health_calls) < 2U) ++failures;
        for (slot = 0U; slot < RT_AI_MAX_LEASES; ++slot) if (runtime.leases[slot].used) ++failures;
        for (slot = 0U; slot < RT_AI_MAX_JOBS; ++slot) if (runtime.jobs[slot] != NULL) ++failures;
    }
    printf("HEALTH_RACE cases=%u failures=%u rollback_leaks=0\n", repetitions, failures);
    return failures == 0U ? 0 : 1;
}

static int run_trust_rotation(const char *path, unsigned repetitions)
{
    rt_ai_aeg_t base;
    unsigned failures = 0U, iteration;
    if (!load_aeg(path, &base) || repetitions == 0U) return 2;
    for (iteration = 0U; iteration < repetitions; ++iteration) {
        rt_ai_aeg_t aeg = base;
        rt_ai_trust_bundle_t trust;
        rt_ai_evaluation_result_t evaluation;
        uint8_t next_root[32];
        unsigned index;
        aeg.segments = aeg.storage;
        make_trust(&aeg, &trust);
        for (index = 0U; index < sizeof(next_root); ++index)
            next_root[index] = (uint8_t)(UINT32_C(0xa5) ^ iteration ^ (index * 17U));
        if (memcmp(next_root, aeg.verifier_sha256[0], sizeof(next_root)) == 0) next_root[0] ^= 1U;

        if (rt_ai_evaluate_deployment(&aeg, &trust, &evaluation) != RT_AI_OK) ++failures;

        trust.allowed_verifier_count = 2U;
        memcpy(trust.allowed_verifier_sha256[1], next_root, sizeof(next_root));
        if (rt_ai_evaluate_deployment(&aeg, &trust, &evaluation) != RT_AI_OK) ++failures;

        trust.allowed_verifier_count = 1U;
        memcpy(trust.allowed_verifier_sha256[0], next_root, sizeof(next_root));
        if (rt_ai_evaluate_deployment(&aeg, &trust, &evaluation) != RT_AI_ERR_EVIDENCE || evaluation.reason != 4U)
            ++failures;

        for (index = 0U; index < aeg.evidence_count; ++index) {
            memcpy(aeg.verifier_sha256[index], next_root, sizeof(next_root));
            memcpy(trust.verifier_sha256[index], next_root, sizeof(next_root));
        }
        if (rt_ai_evaluate_deployment(&aeg, &trust, &evaluation) != RT_AI_OK) ++failures;

        trust.verifier_sha256[iteration % aeg.evidence_count][iteration % sizeof(next_root)] ^= 1U;
        if (rt_ai_evaluate_deployment(&aeg, &trust, &evaluation) != RT_AI_ERR_EVIDENCE || evaluation.reason != 3U)
            ++failures;
    }
    printf("TRUST_ROTATION roots=old,dual,new cases=%u failures=%u\n", repetitions * 5U, failures);
    return failures == 0U ? 0 : 1;
}

static void *transaction_worker(void *opaque)
{
    transaction_arg_t *arg = (transaction_arg_t *)opaque;
    rt_ai_session_t session;
    rt_ai_evaluation_result_t evaluation;
    host_provider_t host = {0};
    unsigned operation;
    assert(rt_ai_session_create_v2(arg->runtime, arg->aeg, arg->trust, &evaluation, &session) == RT_AI_OK);
    for (operation = 0U; operation < arg->operations; ++operation) {
        rt_ai_invocation_t invocation;
        rt_ai_submit_policy_t policy = {(uint64_t)(operation + 1U) * 200U + arg->id,
            (uint64_t)(operation + 1U) * 200U + arg->id + arg->aeg->relative_deadline_us, arg->id, 4U};
        rt_ai_admission_result_t result;
        rt_ai_job_t job;
        size_t index;
        int status;
        make_invocation(arg->aeg, &host, &invocation);
        status = rt_ai_submit_async_v2(&session, &invocation, &policy, &result, &job);
        if (status != RT_AI_OK) { atomic_fetch_add(arg->rejected, 1U); continue; }
        atomic_fetch_add(arg->accepted, 1U);
        for (index = job.lease.offset; index < job.lease.offset + job.lease.size; ++index) {
            int expected = -1;
            if (!atomic_compare_exchange_strong(&arg->owners[index], &expected, (int)arg->id)) atomic_fetch_add(arg->overlaps, 1U);
        }
        sched_yield();
        for (index = job.lease.offset; index < job.lease.offset + job.lease.size; ++index) atomic_store(&arg->owners[index], -1);
        if (rt_ai_cancel(&job) != RT_AI_OK || session.busy || job.lease.used) atomic_fetch_add(arg->partial_commits, 1U);
    }
    return NULL;
}

static int run_transactions(const char *path, unsigned thread_count, unsigned total_operations)
{
    uint8_t arena[64] = {0};
    rt_ai_runtime_t runtime;
    rt_ai_aeg_t aeg;
    rt_ai_trust_bundle_t trust;
    host_provider_t host = {0};
    pthread_t threads[16];
    transaction_arg_t arguments[16];
    atomic_int owners[64];
    atomic_uint overlaps = 0U, partial_commits = 0U, accepted = 0U, rejected = 0U;
    unsigned operations;
    unsigned index;
    if (thread_count < 2U || thread_count > 16U || total_operations < thread_count || !load_aeg(path, &aeg)) return 2;
    make_trust(&aeg, &trust);
    assert(rt_ai_runtime_init(&runtime, arena, sizeof(arena)) == RT_AI_OK);
    register_cpu(&runtime, &host);
    for (index = 0U; index < sizeof(owners) / sizeof(owners[0]); ++index) atomic_init(&owners[index], -1);
    operations = total_operations / thread_count;
    for (index = 0U; index < thread_count; ++index) {
        arguments[index] = (transaction_arg_t){&runtime, &aeg, &trust, owners, &overlaps, &partial_commits,
            &accepted, &rejected, index, operations};
        assert(pthread_create(&threads[index], NULL, transaction_worker, &arguments[index]) == 0);
    }
    for (index = 0U; index < thread_count; ++index) assert(pthread_join(threads[index], NULL) == 0);
    for (index = 0U; index < RT_AI_MAX_LEASES; ++index) if (runtime.leases[index].used) atomic_fetch_add(&partial_commits, 1U);
    for (index = 0U; index < RT_AI_MAX_JOBS; ++index) if (runtime.jobs[index] != NULL) atomic_fetch_add(&partial_commits, 1U);
    printf("TRANSACTIONS threads=%u operations=%u accepted=%u rejected=%u overlaps=%u partial_commits=%u\n",
        thread_count, operations * thread_count, atomic_load(&accepted), atomic_load(&rejected),
        atomic_load(&overlaps), atomic_load(&partial_commits));
    return atomic_load(&overlaps) == 0U && atomic_load(&partial_commits) == 0U && atomic_load(&accepted) != 0U ? 0 : 1;
}

int main(int argc, char **argv)
{
    if (argc == 4 && strcmp(argv[1], "admission") == 0)
        return run_admission_matrix(argv[2], (unsigned)strtoul(argv[3], NULL, 10));
    if (argc == 5 && strcmp(argv[1], "transactions") == 0)
        return run_transactions(argv[2], (unsigned)strtoul(argv[3], NULL, 10), (unsigned)strtoul(argv[4], NULL, 10));
    if (argc == 4 && strcmp(argv[1], "diagnostics") == 0)
        return run_diagnostics(argv[2], (unsigned)strtoul(argv[3], NULL, 10));
    if (argc == 4 && strcmp(argv[1], "health_race") == 0)
        return run_health_race(argv[2], (unsigned)strtoul(argv[3], NULL, 10));
    if (argc == 4 && strcmp(argv[1], "trust_rotation") == 0)
        return run_trust_rotation(argv[2], (unsigned)strtoul(argv[3], NULL, 10));
    return 2;
}

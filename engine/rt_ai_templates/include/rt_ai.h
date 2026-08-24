#ifndef RT_AI_H
#define RT_AI_H

#include <stddef.h>
#include <stdint.h>

#define RT_AI_AEG_MAGIC UINT32_C(0x31474541)
#define RT_AI_AEG_VERSION UINT16_C(1)
#define RT_AI_AEG_V2_MAGIC UINT32_C(0x32474541)
#define RT_AI_AEG_V2_VERSION UINT16_C(2)
#define RT_AI_MAX_SEGMENTS 16U
#define RT_AI_MAX_RESOURCES 4U
#define RT_AI_MAX_JOBS 8U
#define RT_AI_MAX_QUEUE 32U
#define RT_AI_MAX_LEASES 8U
#define RT_AI_TRACE_DEPTH 64U
#define RT_AI_MAX_EVIDENCE 8U

enum {
    RT_AI_OK = 0,
    RT_AI_BUSY = 1,
    RT_AI_ERR_INVALID = -1,
    RT_AI_ERR_RESOURCE = -2,
    RT_AI_ERR_TIMEOUT = -3,
    RT_AI_ERR_CANCELLED = -4,
    RT_AI_ERR_PROVIDER = -5,
    RT_AI_ERR_STALE = -6,
    RT_AI_ERR_ADMISSION = -7,
    RT_AI_ERR_DOMAIN = -8,
    RT_AI_ERR_EVIDENCE = -9
};

typedef enum {
    RT_AI_RESOURCE_CPU = 0,
    RT_AI_RESOURCE_RVV = 1,
    RT_AI_RESOURCE_NPU = 2,
    RT_AI_RESOURCE_DMA = 3
} rt_ai_resource_t;

typedef enum {
    RT_AI_JOB_IDLE = 0,
    RT_AI_JOB_PENDING,
    RT_AI_JOB_RUNNING,
    RT_AI_JOB_COMPLETE,
    RT_AI_JOB_FAILED,
    RT_AI_JOB_CANCELLED
} rt_ai_job_state_t;

typedef enum {
    RT_AI_RESOURCE_HEALTHY = 0,
    RT_AI_RESOURCE_RUNNING,
    RT_AI_RESOURCE_CANCEL_PENDING,
    RT_AI_RESOURCE_RESET_PENDING,
    RT_AI_RESOURCE_REINIT_PENDING,
    RT_AI_RESOURCE_QUARANTINED
} rt_ai_resource_state_t;

enum {
    RT_AI_SEGMENT_CLEAN_INPUT = 1U,
    RT_AI_SEGMENT_INVALIDATE_OUTPUT = 2U
};

enum {
    RT_AI_TRACE_DISPATCH = 1U,
    RT_AI_TRACE_COMPLETE,
    RT_AI_TRACE_CANCEL,
    RT_AI_TRACE_RESET,
    RT_AI_TRACE_QUARANTINE,
    RT_AI_TRACE_FALLBACK,
    RT_AI_TRACE_DOMAIN_REJECT,
    RT_AI_TRACE_EVIDENCE_REJECT,
    RT_AI_TRACE_PROVIDER_REJECT,
    RT_AI_TRACE_MEMORY_REJECT,
    RT_AI_TRACE_DEADLINE_REJECT,
    RT_AI_TRACE_RETRY_REJECT,
    RT_AI_TRACE_CANCEL_ERROR,
    RT_AI_TRACE_RESET_BEGIN_ERROR,
    RT_AI_TRACE_RESET_POLL_ERROR,
    RT_AI_TRACE_REINIT_ERROR,
    RT_AI_TRACE_RECOVERY_TIMEOUT,
    RT_AI_TRACE_COHERENCY_ERROR
};

typedef struct {
    uint16_t id;
    uint8_t resource;
    uint8_t flags;
    uint32_t dependency_mask;
    uint32_t arena_offset;
    uint32_t arena_size;
} rt_ai_aeg_segment_t;

typedef struct {
    uint32_t magic;
    uint16_t version;
    uint16_t segment_count;
    uint32_t arena_size;
    uint32_t reserved;
} rt_ai_aeg_header_t;

typedef struct {
    rt_ai_aeg_header_t header;
    const rt_ai_aeg_segment_t *segments;
    rt_ai_aeg_segment_t storage[RT_AI_MAX_SEGMENTS];
    rt_ai_aeg_segment_t fallback_storage[RT_AI_MAX_SEGMENTS];
    uint32_t wcet_us[RT_AI_MAX_SEGMENTS];
    uint32_t coherency_cost_us[RT_AI_MAX_SEGMENTS];
    uint32_t recovery_cost_us[RT_AI_MAX_SEGMENTS];
    uint16_t fallback_plan_id[RT_AI_MAX_SEGMENTS];
    uint16_t evidence_index[RT_AI_MAX_SEGMENTS];
    uint32_t fallback_wcet_us[RT_AI_MAX_SEGMENTS];
    uint32_t fallback_coherency_cost_us[RT_AI_MAX_SEGMENTS];
    uint32_t fallback_recovery_cost_us[RT_AI_MAX_SEGMENTS];
    uint16_t fallback_evidence[RT_AI_MAX_SEGMENTS];
    uint16_t fallback_segment_count;
    uint32_t reservation_budget_us[RT_AI_MAX_RESOURCES];
    uint32_t reservation_period_us[RT_AI_MAX_RESOURCES];
    uint32_t minimum_interarrival_us;
    uint32_t relative_deadline_us;
    uint32_t cancel_ack_timeout_us;
    uint32_t reset_timeout_us;
    uint32_t reinit_timeout_us;
    uint32_t max_reset_attempts;
    uint32_t input_shape[4];
    uint32_t input_bytes;
    uint32_t output_bytes;
    uint8_t input_rank;
    uint8_t input_dtype;
    uint8_t input_layout;
    uint8_t plan_sha256[32];
    uint8_t evidence_sha256[32];
    uint8_t policy_sha256[32];
    uint8_t model_sha256[32];
    uint8_t target_sha256[32];
    uint8_t runtime_abi_sha256[32];
    uint8_t provider_abi_sha256[32];
    uint8_t fallback_plan_sha256[32];
    uint8_t obligation_sha256[RT_AI_MAX_EVIDENCE][32];
    uint8_t scope_sha256[RT_AI_MAX_EVIDENCE][32];
    uint8_t artifact_sha256[RT_AI_MAX_EVIDENCE][32];
    uint8_t verifier_sha256[RT_AI_MAX_EVIDENCE][32];
    uint8_t evidence_status[RT_AI_MAX_EVIDENCE];
    uint8_t evidence_resource[RT_AI_MAX_EVIDENCE];
    uint8_t evidence_count;
    uint8_t deployable;
    uint8_t legacy;
} rt_ai_aeg_t;

typedef struct {
    uint8_t plan_sha256[32];
    uint8_t evidence_sha256[32];
    uint8_t policy_sha256[32];
    uint8_t model_sha256[32];
    uint8_t target_sha256[32];
    uint8_t runtime_abi_sha256[32];
    uint8_t provider_abi_sha256[32];
    uint8_t obligation_sha256[RT_AI_MAX_EVIDENCE][32];
    uint8_t scope_sha256[RT_AI_MAX_EVIDENCE][32];
    uint8_t artifact_sha256[RT_AI_MAX_EVIDENCE][32];
    uint8_t verifier_sha256[RT_AI_MAX_EVIDENCE][32];
    uint8_t evidence_resource[RT_AI_MAX_EVIDENCE];
    uint8_t obligation_count;
    uint8_t allowed_verifier_sha256[RT_AI_MAX_EVIDENCE][32];
    uint8_t allowed_verifier_count;
} rt_ai_trust_bundle_t;

typedef struct {
    int status;
    uint16_t obligation_index;
    uint16_t reason;
} rt_ai_evaluation_result_t;

typedef struct rt_ai_job rt_ai_job_t;
typedef struct rt_ai_runtime rt_ai_runtime_t;

typedef struct {
    uint8_t resource;
    int (*submit)(void *user, const rt_ai_aeg_segment_t *segment, uint32_t epoch, uint32_t cookie);
    int (*cancel)(void *user, uint32_t epoch, uint32_t cookie);
    int (*reset)(void *user, uint32_t epoch);
    int (*cancel_begin)(void *user, uint32_t epoch, uint32_t cookie);
    int (*cancel_poll)(void *user, uint32_t epoch, uint32_t cookie);
    int (*reset_begin)(void *user, uint32_t epoch);
    int (*reset_poll)(void *user, uint32_t epoch);
    int (*reinit_poll)(void *user, uint32_t epoch);
    int (*health)(void *user);
    void (*clean)(void *user, void *address, size_t size);
    void (*invalidate)(void *user, void *address, size_t size);
    int (*clean_range)(void *user, void *address, size_t size);
    int (*invalidate_range)(void *user, void *address, size_t size);
    int (*barrier)(void *user);
    void *user;
} rt_ai_provider_t;

typedef struct {
    rt_ai_job_t *job;
    uint16_t segment_index;
    uint64_t deadline_us;
} rt_ai_queue_item_t;

typedef struct {
    rt_ai_queue_item_t items[RT_AI_MAX_QUEUE];
    uint16_t count;
} rt_ai_resource_queue_t;

typedef struct {
    size_t offset;
    size_t size;
    uint8_t used;
} rt_ai_arena_lease_t;

typedef struct {
    const void *input;
    size_t input_size;
    void *output;
    size_t output_size;
    uint32_t input_shape[4];
    uint8_t input_rank;
    uint8_t input_dtype;
    uint8_t input_layout;
    uint8_t plan_sha256[32];
} rt_ai_invocation_t;

typedef struct {
    uint64_t now_us;
    uint64_t deadline_us;
    uint64_t run_id;
    uint8_t max_retries;
} rt_ai_submit_policy_t;

typedef enum {
    RT_AI_ADMISSION_ACCEPTED = 0,
    RT_AI_ADMISSION_BINDING,
    RT_AI_ADMISSION_DOMAIN,
    RT_AI_ADMISSION_EVIDENCE,
    RT_AI_ADMISSION_PROVIDER,
    RT_AI_ADMISSION_MEMORY,
    RT_AI_ADMISSION_DEADLINE,
    RT_AI_ADMISSION_RETRY
} rt_ai_admission_stage_t;

typedef struct {
    rt_ai_admission_stage_t stage;
    int status;
    uint64_t predicted_finish_us;
    uint32_t generation;
} rt_ai_admission_result_t;

typedef struct {
    uint64_t sequence;
    uint64_t timestamp_us;
    uint64_t job_id;
    uint64_t cookie;
    uint64_t run_id;
    uint8_t plan_id[32];
    uint16_t segment_id;
    uint8_t resource;
    uint32_t epoch;
    uint16_t event;
    int status;
    uint16_t queue_depth;
} rt_ai_trace_entry_t;

typedef struct {
    rt_ai_runtime_t *runtime;
    rt_ai_aeg_t aeg;
    rt_ai_trust_bundle_t trust;
    rt_ai_arena_lease_t lease;
    uint64_t last_submit_us;
    uint8_t has_submitted;
    uint8_t busy;
    uint8_t trust_valid;
} rt_ai_session_t;

struct rt_ai_job {
    rt_ai_session_t *session;
    uint64_t release_us;
    uint64_t deadline_us;
    uint32_t cookie[RT_AI_MAX_SEGMENTS];
    uint8_t segment_state[RT_AI_MAX_SEGMENTS];
    rt_ai_arena_lease_t lease;
    rt_ai_job_state_t state;
    int status;
    rt_ai_job_state_t terminal_state;
    int terminal_status;
    uint8_t pending_recovery;
    uint8_t recovering;
    uint8_t recovery_quarantined;
    uint64_t job_id;
    uint64_t run_id;
    uint8_t buffer_owner[RT_AI_MAX_SEGMENTS];
    uint8_t use_fallback;
};

struct rt_ai_runtime {
    uint8_t *arena;
    size_t arena_size;
    rt_ai_provider_t providers[RT_AI_MAX_RESOURCES];
    uint8_t provider_valid[RT_AI_MAX_RESOURCES];
    uint32_t epoch[RT_AI_MAX_RESOURCES];
    uint32_t next_cookie[RT_AI_MAX_RESOURCES];
    uint64_t next_job_id;
    rt_ai_job_t *jobs[RT_AI_MAX_JOBS];
    rt_ai_job_t *active_job[RT_AI_MAX_RESOURCES];
    uint16_t active_segment[RT_AI_MAX_RESOURCES];
    uint32_t active_cookie[RT_AI_MAX_RESOURCES];
    uint64_t active_started_us[RT_AI_MAX_RESOURCES];
    rt_ai_resource_queue_t queues[RT_AI_MAX_RESOURCES];
    rt_ai_arena_lease_t leases[RT_AI_MAX_LEASES];
    uint32_t lease_generation;
    uint32_t schedule_generation;
    rt_ai_resource_state_t resource_state[RT_AI_MAX_RESOURCES];
    rt_ai_job_t *recovery_job[RT_AI_MAX_RESOURCES];
    uint64_t recovery_deadline_us[RT_AI_MAX_RESOURCES];
    uint64_t last_now_us;
    uint32_t reset_attempts[RT_AI_MAX_RESOURCES];
    rt_ai_trace_entry_t trace[RT_AI_TRACE_DEPTH];
    uint64_t trace_sequence;
    uint64_t trace_dropped;
};

int rt_ai_runtime_init(rt_ai_runtime_t *runtime, void *arena, size_t arena_size);
int rt_ai_load(const void *blob, size_t size, rt_ai_aeg_t *aeg);
int rt_ai_provider_register(rt_ai_runtime_t *runtime, const rt_ai_provider_t *provider);
int rt_ai_session_create(rt_ai_runtime_t *runtime, const rt_ai_aeg_t *aeg, rt_ai_session_t *session);
int rt_ai_session_create_v2(rt_ai_runtime_t *runtime, const rt_ai_aeg_t *aeg, const rt_ai_trust_bundle_t *trust, rt_ai_evaluation_result_t *evaluation, rt_ai_session_t *session);
int rt_ai_evaluate_deployment(const rt_ai_aeg_t *aeg, const rt_ai_trust_bundle_t *trust, rt_ai_evaluation_result_t *result);
int rt_ai_session_destroy(rt_ai_session_t *session);
int rt_ai_submit_async(rt_ai_session_t *session, uint64_t now_us, uint64_t deadline_us, rt_ai_job_t *job);
int rt_ai_submit_async_v2(rt_ai_session_t *session, const rt_ai_invocation_t *invocation, const rt_ai_submit_policy_t *policy, rt_ai_admission_result_t *result, rt_ai_job_t *job);
int rt_ai_poll(rt_ai_runtime_t *runtime, uint64_t now_us);
int rt_ai_wait(const rt_ai_job_t *job);
int rt_ai_cancel(rt_ai_job_t *job);
int rt_ai_complete_isr(rt_ai_runtime_t *runtime, uint8_t device_id, uint32_t epoch, uint32_t cookie, int status);
int rt_ai_reset_device(rt_ai_runtime_t *runtime, uint8_t device_id);
int rt_ai_trace_snapshot(const rt_ai_runtime_t *runtime, rt_ai_trace_entry_t *entries, uint16_t capacity, uint16_t *count, uint64_t *dropped);
int rt_ai_trace_json(const rt_ai_runtime_t *runtime, char *output, size_t capacity, size_t *written);

#endif

#ifndef RVAIC_H
#define RVAIC_H

#include <stddef.h>
#include <stdint.h>

#if defined(__has_include)
#if __has_include(<rtconfig.h>)
#include <rtconfig.h>
#endif
#endif

typedef struct rvaic_session rvaic_session_t;

#define RVAIC_MODEL_MAGIC 0x52564149u
#define RVAIC_MODEL_VERSION 1u
#define RVAIC_MAX_IO 4
#define RVAIC_MAX_OPS 16
#define RVAIC_MAX_NPU_QUEUE 8
#define RVAIC_MAX_MODELS 8
#define RVAIC_MAX_BACKENDS 4
#define RVAIC_MAX_SESSIONS 4
#define RVAIC_MAX_SERVICE_JOBS 8
#define RVAIC_MAX_ARENA_RESERVATIONS 8

#define RVAIC_DTYPE_FLOAT32 0
#define RVAIC_DTYPE_INT8 1
#define RVAIC_DTYPE_INT32 2
#define RVAIC_DTYPE_FLOAT16 3
#define RVAIC_DTYPE_UINT8 4

#define RVAIC_BACKEND_CPU 0x1u
#define RVAIC_BACKEND_RVV 0x2u
#define RVAIC_BACKEND_NPU 0x4u

#define RVAIC_EVIDENCE_E0 0u
#define RVAIC_EVIDENCE_E1 1u
#define RVAIC_EVIDENCE_E2 2u
#define RVAIC_EVIDENCE_E3 3u
#define RVAIC_EVIDENCE_E4 4u
#define RVAIC_EVIDENCE_E5 5u
#define RVAIC_EVIDENCE_E6 6u

#define RVAIC_PLAN_REJECT_UNVERIFIED 0x01u
#define RVAIC_PLAN_REJECT_BACKEND 0x02u
#define RVAIC_PLAN_REJECT_MEMORY 0x04u
#define RVAIC_PLAN_REJECT_DEADLINE 0x08u
#define RVAIC_PLAN_REJECT_EVIDENCE 0x10u
#define RVAIC_PLAN_REJECT_TARGET 0x20u

#define RVAIC_JOB_PENDING 1u
#define RVAIC_JOB_RUNNING 2u
#define RVAIC_JOB_DONE 3u
#define RVAIC_JOB_CANCELLED 4u
#define RVAIC_JOB_FAILED 5u

#define RVAIC_STATUS_CANCELLED -2
#define RVAIC_STATUS_TIMEOUT -3
#define RVAIC_STATUS_QUEUE_FULL -4
#define RVAIC_STATUS_NO_RESOURCE -5
#define RVAIC_STATUS_INVALID_PLAN -6

typedef struct
{
    void *data;
    int32_t ndim;
    int32_t shape[8];
    int32_t stride[8];
    int32_t dtype;
    float scale;
    int32_t zero_point;
} rvaic_tensor_t;

typedef int (*rvaic_run_fn)(void *user, const rvaic_tensor_t *inputs, rvaic_tensor_t *outputs);
typedef int (*rvaic_op_fn)(void *user, const rvaic_tensor_t *inputs, rvaic_tensor_t *outputs);
typedef void (*rvaic_callback_t)(void *user_data, int status);

typedef struct
{
    volatile int signaled;
    int status;
    rvaic_callback_t callback;
    void *user_data;
} rvaic_fence_t;

typedef struct
{
    int opcode;
    uint32_t legal_backend_mask;
    size_t workspace_bytes;
} rvaic_node_desc_t;

typedef struct
{
    uint32_t queue_depth;
    size_t arena_available;
} rvaic_runtime_state_t;

typedef struct
{
    const rvaic_tensor_t *inputs;
    rvaic_tensor_t *outputs;
    void *user;
} rvaic_exec_context_t;

typedef struct
{
    const char *name;
    const char *target_hash;
    uint32_t backend_mask;
    size_t arena_bytes;
    uint32_t expected_latency_us;
    uint32_t verified;
    uint32_t evidence_level;
    uint32_t required_evidence_level;
} rvaic_plan_t;

typedef struct
{
    uint32_t accepted;
    uint32_t reject_mask;
    size_t arena_free_bytes;
    uint32_t backend_mask;
    uint32_t deadline_us;
    uint32_t min_evidence_level;
    uint32_t target_hash_match;
} rvaic_plan_admission_result_t;

typedef struct
{
    uint32_t id;
    size_t offset;
    size_t size;
    uint32_t exclusive;
    int in_use;
} rvaic_arena_reservation_t;

typedef struct
{
    const char *model_name;
    size_t arena_bytes;
    size_t alignment;
    uint32_t exclusive;
    const char *scope;
    size_t offset;
    uint32_t mutual_exclusion_group;
    uint32_t parallel_group;
} rvaic_admission_entry_t;

typedef struct
{
    const char *name;
    uint32_t backend_mask;
    int (*supports)(const rvaic_node_desc_t *node);
    int (*estimate_cost)(const rvaic_node_desc_t *node, const rvaic_runtime_state_t *state);
    int (*prepare)(const rvaic_node_desc_t *node);
    int (*execute)(const rvaic_node_desc_t *node, rvaic_exec_context_t *context);
    int (*synchronize)(void);
    int (*reset)(void);
} rvaic_backend_ops_t;

typedef struct
{
    uint32_t opcode;
    uint64_t src_addr;
    uint64_t dst_addr;
    uint32_t bytes;
    uintptr_t command;
    uint32_t timeout_ticks;
} rvaic_npu_command_t;

typedef int (*rvaic_npu_submit_fn)(void *user, const rvaic_npu_command_t *command);

typedef struct
{
    uint32_t runs;
    uint32_t op_dispatches;
    uint32_t npu_submits;
    uint32_t jobs;
    uint32_t service_submits;
    uint32_t service_completions;
    uint32_t service_timeouts;
    uint32_t service_cancellations;
    uint32_t backend_dispatches;
    size_t arena_used;
    int last_status;
} rvaic_profile_t;

typedef struct
{
    uint32_t magic;
    uint32_t version;
    int32_t input_count;
    int32_t output_count;
    const char *name;
    uint32_t model_version;
    uint32_t required_abi;
    uint32_t required_features;
    const char *target_hash;
    size_t flash_bytes;
    size_t persistent_bytes;
    size_t stack_bytes;
    const rvaic_node_desc_t *nodes;
    size_t node_count;
    void *arena;
    size_t arena_size;
    rvaic_run_fn run;
    void *user;
} rvaic_model_t;

typedef struct
{
    rvaic_session_t *session;
    const rvaic_tensor_t *inputs;
    rvaic_tensor_t *outputs;
    uint32_t priority;
    uint32_t deadline_us;
    uint32_t timeout_us;
    uint32_t backend_mask;
    const rvaic_fence_t *dependency;
    rvaic_fence_t *fence;
    rvaic_callback_t callback;
    void *user_data;
    int status;
    uint32_t state;
} rvaic_job_t;

typedef struct
{
    uint32_t submitted;
    uint32_t queued;
    uint32_t completed;
    uint32_t cancelled;
    uint32_t timed_out;
    uint32_t resets;
} rvaic_service_stats_t;

typedef struct
{
    uint32_t backend_mask;
    uint32_t queued;
    uint32_t running;
    uint32_t completed;
    uint32_t credits;
} rvaic_backend_queue_state_t;

typedef rvaic_model_t rt_ai_model_t;
typedef rvaic_job_t rt_ai_job_t;
typedef rvaic_fence_t rt_ai_fence_t;
typedef rvaic_plan_t rt_ai_plan_t;

typedef struct
{
    size_t arena_available;
    uint32_t backend_mask;
} rt_ai_admission_policy_t;

int rvaic_init(void);
int rvaic_runtime_set_target_hash(const char *target_hash);
const char *rvaic_runtime_target_hash(void);
int rvaic_allocator_init(void *arena, size_t size);
void *rvaic_alloc(size_t size, size_t alignment);
size_t rvaic_allocator_used(void);
int rvaic_arena_pool_init(void *arena, size_t size);
int rvaic_arena_pool_ready(void);
int rvaic_arena_reserve(size_t size, size_t alignment, uint32_t exclusive, rvaic_arena_reservation_t *reservation);
int rvaic_arena_reserve_at(size_t size, size_t alignment, size_t offset, uint32_t exclusive, rvaic_arena_reservation_t *reservation);
int rvaic_arena_release(rvaic_arena_reservation_t *reservation);
size_t rvaic_arena_pool_size(void);
size_t rvaic_arena_pool_available(void);
int rvaic_model_register(const char *name, const rvaic_model_t *model);
int rvaic_model_unregister(const char *name);
const rvaic_model_t *rvaic_model_find(const char *name);
size_t rvaic_model_count(void);
uint32_t rvaic_model_ref_count(const char *name);
int rvaic_model_admit(const rvaic_model_t *model, size_t arena_available, uint32_t backend_mask);
int rvaic_model_admit_contract(const rvaic_model_t *model, const rvaic_admission_entry_t *entries, size_t count, size_t arena_available, uint32_t backend_mask);
int rvaic_model_reserve_contract(
    const rvaic_model_t *model,
    const rvaic_admission_entry_t *entries,
    size_t count,
    uint32_t backend_mask,
    rvaic_arena_reservation_t *reservation);
int rvaic_backend_register(const rvaic_backend_ops_t *ops);
const rvaic_backend_ops_t *rvaic_backend_find(const char *name);
int rvaic_backend_lock(uint32_t backend_mask);
int rvaic_backend_unlock(uint32_t backend_mask);
int rvaic_backend_reset(uint32_t backend_mask);
int rvaic_register_cpu_fallback(int opcode, rvaic_op_fn fn, void *user);
int rvaic_dispatch_op(int opcode, const rvaic_tensor_t *inputs, rvaic_tensor_t *outputs);
int rvaic_npu_set_submitter(rvaic_npu_submit_fn fn, void *user);
int rvaic_npu_submit(const rvaic_npu_command_t *command);
int rvaic_profile(rvaic_profile_t *profile);
rvaic_session_t *rvaic_session_create(const void *model, size_t model_size);
rvaic_session_t *rvaic_session_create_with_admission(
    const void *model,
    size_t model_size,
    const rvaic_admission_entry_t *entries,
    size_t count,
    uint32_t backend_mask);
int rvaic_set_input(rvaic_session_t *session, int index, const rvaic_tensor_t *tensor);
int rvaic_run(rvaic_session_t *session);
int rvaic_get_output(rvaic_session_t *session, int index, rvaic_tensor_t *tensor);
int rvaic_submit(rvaic_job_t *job);
int rvaic_job_wait(const rvaic_job_t *job, uint32_t timeout_ticks);
int rvaic_cancel(rvaic_job_t *job);
int rvaic_timeout_check(rvaic_job_t *job, uint32_t elapsed_us);
int rvaic_fence_wait(const rvaic_fence_t *fence, uint32_t timeout_ticks);
int rvaic_service_init(void);
int rvaic_service_start(void);
int rvaic_service_stop(void);
int rvaic_service_submit(rvaic_job_t *job);
int rvaic_service_post_event(uint32_t event_id, rvaic_job_t *job);
int rvaic_service_step(void);
int rvaic_service_drain(void);
int rvaic_service_watchdog_tick(uint32_t elapsed_us);
int rvaic_service_stats(rvaic_service_stats_t *stats);
int rvaic_backend_queue_state(uint32_t backend_mask, rvaic_backend_queue_state_t *state);
const rvaic_plan_t *rvaic_plan_select(const rvaic_plan_t *plans, size_t count, size_t arena_available, uint32_t backend_mask, uint32_t deadline_us);
int rvaic_plan_admit(
    const rvaic_plan_t *plan,
    size_t arena_free_bytes,
    uint32_t backend_mask,
    uint32_t deadline_us,
    uint32_t min_evidence_level,
    rvaic_plan_admission_result_t *result);
const rvaic_plan_t *rvaic_plan_select_with_evidence(
    const rvaic_plan_t *plans,
    size_t count,
    size_t arena_available,
    uint32_t backend_mask,
    uint32_t deadline_us,
    uint32_t min_evidence_level,
    rvaic_plan_admission_result_t *result);
int rvaic_plan_execute(rvaic_session_t *session, const rvaic_plan_t *plan, const rvaic_tensor_t *inputs, rvaic_tensor_t *outputs, rvaic_fence_t *fence);
void rvaic_session_destroy(const rvaic_session_t *session);

const rt_ai_model_t *rt_ai_model_find(const char *name);
int rt_ai_model_admit(const rt_ai_model_t *model, const rt_ai_admission_policy_t *policy);
int rt_ai_model_unload(const char *name);
int rt_ai_submit(rt_ai_job_t *job, rt_ai_fence_t **completion);
int rt_ai_cancel(rt_ai_job_t *job);

#ifdef RT_USING_HEAP
#include <rtthread.h>
rt_object_t rt_ai_model_object_register(const char *name, const rt_ai_model_t *model);
rt_object_t rt_ai_model_object_find(const char *name);
#endif

#endif

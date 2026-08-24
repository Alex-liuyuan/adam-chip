#ifndef RT_AI_H
#define RT_AI_H

#include <stddef.h>
#include <stdint.h>

#define RT_AI_AEG_MAGIC UINT32_C(0x31474541)
#define RT_AI_AEG_VERSION UINT16_C(1)
#define RT_AI_MAX_SEGMENTS 16U
#define RT_AI_MAX_RESOURCES 4U
#define RT_AI_MAX_JOBS 8U
#define RT_AI_MAX_QUEUE 32U
#define RT_AI_MAX_LEASES 8U
#define RT_AI_TRACE_DEPTH 64U

enum {
    RT_AI_OK = 0,
    RT_AI_BUSY = 1,
    RT_AI_ERR_INVALID = -1,
    RT_AI_ERR_RESOURCE = -2,
    RT_AI_ERR_TIMEOUT = -3,
    RT_AI_ERR_CANCELLED = -4,
    RT_AI_ERR_PROVIDER = -5,
    RT_AI_ERR_STALE = -6
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

enum {
    RT_AI_SEGMENT_CLEAN_INPUT = 1U,
    RT_AI_SEGMENT_INVALIDATE_OUTPUT = 2U
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
} rt_ai_aeg_t;

typedef struct rt_ai_job rt_ai_job_t;
typedef struct rt_ai_runtime rt_ai_runtime_t;

typedef struct {
    uint8_t resource;
    int (*submit)(void *user, const rt_ai_aeg_segment_t *segment, uint32_t epoch, uint32_t cookie);
    int (*cancel)(void *user, uint32_t epoch, uint32_t cookie);
    int (*reset)(void *user, uint32_t epoch);
    void (*clean)(void *user, void *address, size_t size);
    void (*invalidate)(void *user, void *address, size_t size);
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
    uint64_t timestamp_us;
    uint32_t cookie;
    uint16_t segment_id;
    int16_t event;
} rt_ai_trace_entry_t;

typedef struct {
    rt_ai_runtime_t *runtime;
    rt_ai_aeg_t aeg;
    rt_ai_arena_lease_t lease;
    uint8_t busy;
} rt_ai_session_t;

struct rt_ai_job {
    rt_ai_session_t *session;
    uint64_t deadline_us;
    uint32_t cookie[RT_AI_MAX_SEGMENTS];
    uint8_t segment_state[RT_AI_MAX_SEGMENTS];
    rt_ai_job_state_t state;
    int status;
};

struct rt_ai_runtime {
    uint8_t *arena;
    size_t arena_size;
    rt_ai_provider_t providers[RT_AI_MAX_RESOURCES];
    uint8_t provider_valid[RT_AI_MAX_RESOURCES];
    uint32_t epoch[RT_AI_MAX_RESOURCES];
    uint32_t next_cookie;
    rt_ai_job_t *jobs[RT_AI_MAX_JOBS];
    rt_ai_job_t *active_job[RT_AI_MAX_RESOURCES];
    uint16_t active_segment[RT_AI_MAX_RESOURCES];
    uint32_t active_cookie[RT_AI_MAX_RESOURCES];
    rt_ai_resource_queue_t queues[RT_AI_MAX_RESOURCES];
    rt_ai_arena_lease_t leases[RT_AI_MAX_LEASES];
    rt_ai_trace_entry_t trace[RT_AI_TRACE_DEPTH];
    uint16_t trace_head;
};

int rt_ai_runtime_init(rt_ai_runtime_t *runtime, void *arena, size_t arena_size);
int rt_ai_load(const void *blob, size_t size, rt_ai_aeg_t *aeg);
int rt_ai_provider_register(rt_ai_runtime_t *runtime, const rt_ai_provider_t *provider);
int rt_ai_session_create(rt_ai_runtime_t *runtime, const rt_ai_aeg_t *aeg, rt_ai_session_t *session);
int rt_ai_session_destroy(rt_ai_session_t *session);
int rt_ai_submit_async(rt_ai_session_t *session, uint64_t now_us, uint64_t deadline_us, rt_ai_job_t *job);
int rt_ai_poll(rt_ai_runtime_t *runtime, uint64_t now_us);
int rt_ai_wait(const rt_ai_job_t *job);
int rt_ai_cancel(rt_ai_job_t *job);
int rt_ai_complete_isr(rt_ai_runtime_t *runtime, uint8_t device_id, uint32_t epoch, uint32_t cookie, int status);
int rt_ai_reset_device(rt_ai_runtime_t *runtime, uint8_t device_id);
const rt_ai_trace_entry_t *rt_ai_trace_data(const rt_ai_runtime_t *runtime, uint16_t *count);

#endif

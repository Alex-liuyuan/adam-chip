#include "rvaic.h"

#include <string.h>

#ifdef RT_USING_HEAP
#include <rtthread.h>
#endif

struct rvaic_session
{
    const rvaic_model_t *model;
    rvaic_tensor_t inputs[RVAIC_MAX_IO];
    rvaic_tensor_t outputs[RVAIC_MAX_IO];
    rvaic_arena_reservation_t arena_reservation;
    int has_arena_reservation;
    int in_use;
};

struct rvaic_op_entry
{
    int opcode;
    rvaic_op_fn fn;
    void *user;
};

struct rvaic_model_entry
{
    const char *name;
    const rvaic_model_t *model;
    uint32_t ref_count;
};

static struct rvaic_session g_sessions[RVAIC_MAX_SESSIONS];
static struct rvaic_op_entry g_ops[RVAIC_MAX_OPS];
static struct rvaic_model_entry g_models[RVAIC_MAX_MODELS];
static rvaic_backend_ops_t g_backends[RVAIC_MAX_BACKENDS];
static uint8_t *g_arena;
static size_t g_arena_size;
static size_t g_arena_used;
static rvaic_npu_submit_fn g_npu_submit;
static void *g_npu_user;
static const char *g_runtime_target_hash;
static rvaic_profile_t g_profile;

static void signal_fence(rvaic_fence_t *fence, int status)
{
    if (!fence)
    {
        return;
    }
    fence->status = status;
    fence->signaled = 1;
    if (fence->callback)
    {
        fence->callback(fence->user_data, status);
    }
}

static size_t arena_available(void)
{
    if (g_arena_size <= g_arena_used)
    {
        return 0u;
    }
    return g_arena_size - g_arena_used;
}

static int valid_session(const rvaic_session_t *session)
{
    if (!session)
    {
        return 0;
    }
    for (int i = 0; i < RVAIC_MAX_SESSIONS; i++)
    {
        if (session == &g_sessions[i] && g_sessions[i].in_use)
        {
            return 1;
        }
    }
    return 0;
}

static int target_hash_matches(const char *target_hash)
{
    if (!target_hash || !target_hash[0])
    {
        return 1;
    }
    if (!g_runtime_target_hash || !g_runtime_target_hash[0])
    {
        return 0;
    }
    return strcmp(target_hash, g_runtime_target_hash) == 0;
}

static struct rvaic_session *alloc_session(void)
{
    for (int i = 0; i < RVAIC_MAX_SESSIONS; i++)
    {
        if (!g_sessions[i].in_use)
        {
            return &g_sessions[i];
        }
    }
    return 0;
}

static struct rvaic_model_entry *model_entry_by_name(const char *name)
{
    if (!name)
    {
        return 0;
    }
    for (int i = 0; i < RVAIC_MAX_MODELS; i++)
    {
        if (g_models[i].name && strcmp(g_models[i].name, name) == 0)
        {
            return &g_models[i];
        }
    }
    return 0;
}

static struct rvaic_model_entry *model_entry_by_model(const rvaic_model_t *model)
{
    for (int i = 0; i < RVAIC_MAX_MODELS; i++)
    {
        if (g_models[i].model == model)
        {
            return &g_models[i];
        }
    }
    return 0;
}

static const rvaic_admission_entry_t *find_admission_entry(
    const rvaic_model_t *model,
    const rvaic_admission_entry_t *entries,
    size_t count)
{
    if (!model || !model->name || !entries)
    {
        return 0;
    }
    for (size_t i = 0; i < count; i++)
    {
        if (entries[i].model_name && strcmp(entries[i].model_name, model->name) == 0)
        {
            return &entries[i];
        }
    }
    return 0;
}

static size_t session_available(const struct rvaic_session *session)
{
    size_t available = rvaic_arena_pool_ready() ? rvaic_arena_pool_available() : arena_available();

    if (session && session->has_arena_reservation)
    {
        available += session->arena_reservation.size;
    }
    if (!rvaic_arena_pool_ready() && session && session->model && session->model->arena && session->model->arena_size > available)
    {
        available = session->model->arena_size;
    }
    return available;
}

static int valid_model(const rvaic_model_t *model)
{
    if (!model || model->magic != RVAIC_MODEL_MAGIC || model->version != RVAIC_MODEL_VERSION || !model->run)
    {
        return 0;
    }
    if (model->input_count < 0 || model->input_count > RVAIC_MAX_IO)
    {
        return 0;
    }
    if (model->output_count < 0 || model->output_count > RVAIC_MAX_IO)
    {
        return 0;
    }
    if (model->required_abi != 0u && model->required_abi != RVAIC_MODEL_VERSION)
    {
        return 0;
    }
    return 1;
}

static uint32_t plan_evidence_level(const rvaic_plan_t *plan)
{
    if (!plan)
    {
        return RVAIC_EVIDENCE_E0;
    }
    if (plan->evidence_level != 0u)
    {
        return plan->evidence_level;
    }
    return plan->verified ? RVAIC_EVIDENCE_E3 : RVAIC_EVIDENCE_E0;
}

static uint32_t plan_required_evidence_level(const rvaic_plan_t *plan, uint32_t min_evidence_level)
{
    uint32_t required = min_evidence_level == 0u ? RVAIC_EVIDENCE_E3 : min_evidence_level;

    if (plan && plan->required_evidence_level > required)
    {
        required = plan->required_evidence_level;
    }
    return required;
}

int rvaic_init(void)
{
    for (int i = 0; i < RVAIC_MAX_SESSIONS; i++)
    {
        memset(&g_sessions[i], 0, sizeof(g_sessions[i]));
    }
    g_arena = 0;
    g_arena_size = 0;
    g_arena_used = 0;
    g_npu_submit = 0;
    g_npu_user = 0;
    g_runtime_target_hash = 0;
    g_profile.runs = 0;
    g_profile.op_dispatches = 0;
    g_profile.npu_submits = 0;
    g_profile.jobs = 0;
    g_profile.service_submits = 0;
    g_profile.service_completions = 0;
    g_profile.service_timeouts = 0;
    g_profile.service_cancellations = 0;
    g_profile.backend_dispatches = 0;
    g_profile.arena_used = 0;
    g_profile.last_status = 0;
    for (int i = 0; i < RVAIC_MAX_OPS; i++)
    {
        g_ops[i].opcode = -1;
        g_ops[i].fn = 0;
        g_ops[i].user = 0;
    }
    for (int i = 0; i < RVAIC_MAX_MODELS; i++)
    {
        g_models[i].name = 0;
        g_models[i].model = 0;
        g_models[i].ref_count = 0;
    }
    for (int i = 0; i < RVAIC_MAX_BACKENDS; i++)
    {
        g_backends[i].name = 0;
        g_backends[i].backend_mask = 0;
        g_backends[i].supports = 0;
        g_backends[i].estimate_cost = 0;
        g_backends[i].prepare = 0;
        g_backends[i].execute = 0;
        g_backends[i].synchronize = 0;
        g_backends[i].reset = 0;
    }
    return 0;
}

int rvaic_runtime_set_target_hash(const char *target_hash)
{
    if (!target_hash || !target_hash[0])
    {
        return -1;
    }
    g_runtime_target_hash = target_hash;
    return 0;
}

const char *rvaic_runtime_target_hash(void)
{
    return g_runtime_target_hash;
}

int rvaic_allocator_init(void *arena, size_t size)
{
    if (!arena || size == 0u)
    {
        return -1;
    }
    g_arena = (uint8_t *)arena;
    g_arena_size = size;
    g_arena_used = 0;
    g_profile.arena_used = 0;
    return 0;
}

void *rvaic_alloc(size_t size, size_t alignment)
{
    size_t aligned;
    uintptr_t base;
    uintptr_t current;
    uintptr_t aligned_addr;

    if (!g_arena || size == 0u)
    {
        return 0;
    }
    if (alignment == 0u)
    {
        alignment = sizeof(void *);
    }
    if ((alignment & (alignment - 1u)) != 0u)
    {
        return 0;
    }

    base = (uintptr_t)g_arena;
    current = base + g_arena_used;
    aligned_addr = (current + alignment - 1u) & ~((uintptr_t)alignment - 1u);
    aligned = (size_t)(aligned_addr - base);
    if (aligned > g_arena_size || size > g_arena_size - aligned)
    {
        return 0;
    }
    g_arena_used = aligned + size;
    g_profile.arena_used = g_arena_used;
    return g_arena + aligned;
}

size_t rvaic_allocator_used(void)
{
    return g_arena_used;
}

int rvaic_model_register(const char *name, const rvaic_model_t *model)
{
    if (!name || !name[0] || !valid_model(model))
    {
        return -1;
    }
    for (int i = 0; i < RVAIC_MAX_MODELS; i++)
    {
        if (g_models[i].name && strcmp(g_models[i].name, name) == 0)
        {
            if (g_models[i].ref_count != 0u && g_models[i].model != model)
            {
                return -1;
            }
            g_models[i].model = model;
            return 0;
        }
    }
    for (int i = 0; i < RVAIC_MAX_MODELS; i++)
    {
        if (!g_models[i].name)
        {
            g_models[i].name = name;
            g_models[i].model = model;
            g_models[i].ref_count = 0;
            return 0;
        }
    }
    return -1;
}

int rvaic_model_unregister(const char *name)
{
    struct rvaic_model_entry *entry = model_entry_by_name(name);

    if (!entry || entry->ref_count != 0u)
    {
        return -1;
    }
    memset(entry, 0, sizeof(*entry));
    return 0;
}

const rvaic_model_t *rvaic_model_find(const char *name)
{
    if (!name)
    {
        return 0;
    }
    for (int i = 0; i < RVAIC_MAX_MODELS; i++)
    {
        if (g_models[i].name && strcmp(g_models[i].name, name) == 0)
        {
            return g_models[i].model;
        }
    }
    return 0;
}

size_t rvaic_model_count(void)
{
    size_t count = 0;
    for (int i = 0; i < RVAIC_MAX_MODELS; i++)
    {
        if (g_models[i].name)
        {
            count++;
        }
    }
    return count;
}

uint32_t rvaic_model_ref_count(const char *name)
{
    struct rvaic_model_entry *entry = model_entry_by_name(name);

    return entry ? entry->ref_count : 0u;
}

int rvaic_model_admit(const rvaic_model_t *model, size_t arena_free_bytes, uint32_t backend_mask)
{
    if (!valid_model(model))
    {
        return -1;
    }
    if (backend_mask == 0u)
    {
        backend_mask = RVAIC_BACKEND_CPU | RVAIC_BACKEND_RVV | RVAIC_BACKEND_NPU;
    }
    if (model->required_features != 0u && (model->required_features & backend_mask) != model->required_features)
    {
        return -1;
    }
    if (!target_hash_matches(model->target_hash))
    {
        return -1;
    }
    if (model->arena_size != 0u && model->arena_size > arena_free_bytes)
    {
        return -1;
    }
    return 0;
}

int rvaic_model_admit_contract(
    const rvaic_model_t *model,
    const rvaic_admission_entry_t *entries,
    size_t count,
    size_t arena_free_bytes,
    uint32_t backend_mask)
{
    if (rvaic_model_admit(model, arena_free_bytes, backend_mask) != 0)
    {
        return -1;
    }
    if (!entries || count == 0u)
    {
        return 0;
    }
    for (size_t i = 0; i < count; i++)
    {
        const rvaic_admission_entry_t *entry = &entries[i];
        if (!entry->model_name || !model->name || strcmp(entry->model_name, model->name) != 0)
        {
            continue;
        }
        if (entry->alignment != 0u && (entry->alignment & (entry->alignment - 1u)) != 0u)
        {
            return -1;
        }
        if (entry->offset > arena_free_bytes || entry->arena_bytes > arena_free_bytes - entry->offset)
        {
            return -1;
        }
        if (model->arena_size != 0u && entry->arena_bytes != model->arena_size)
        {
            return -1;
        }
        return 0;
    }
    return -1;
}

int rvaic_model_reserve_contract(
    const rvaic_model_t *model,
    const rvaic_admission_entry_t *entries,
    size_t count,
    uint32_t backend_mask,
    rvaic_arena_reservation_t *reservation)
{
    const rvaic_admission_entry_t *entry;

    if (!reservation || !rvaic_arena_pool_ready())
    {
        return -1;
    }
    if (rvaic_model_admit_contract(model, entries, count, rvaic_arena_pool_size(), backend_mask) != 0)
    {
        return -1;
    }
    entry = find_admission_entry(model, entries, count);
    if (!entry)
    {
        return -1;
    }
    return rvaic_arena_reserve_at(entry->arena_bytes, entry->alignment, entry->offset, entry->exclusive, reservation);
}

int rvaic_backend_register(const rvaic_backend_ops_t *ops)
{
    if (!ops || !ops->name || !ops->name[0] || ops->backend_mask == 0u)
    {
        return -1;
    }
    for (int i = 0; i < RVAIC_MAX_BACKENDS; i++)
    {
        if (g_backends[i].name && strcmp(g_backends[i].name, ops->name) == 0)
        {
            g_backends[i] = *ops;
            return 0;
        }
    }
    for (int i = 0; i < RVAIC_MAX_BACKENDS; i++)
    {
        if (!g_backends[i].name)
        {
            g_backends[i] = *ops;
            return 0;
        }
    }
    return -1;
}

const rvaic_backend_ops_t *rvaic_backend_find(const char *name)
{
    if (!name)
    {
        return 0;
    }
    for (int i = 0; i < RVAIC_MAX_BACKENDS; i++)
    {
        if (g_backends[i].name && strcmp(g_backends[i].name, name) == 0)
        {
            return &g_backends[i];
        }
    }
    return 0;
}

int rvaic_backend_reset(uint32_t backend_mask)
{
    int reset_seen = 0;

    for (int i = 0; i < RVAIC_MAX_BACKENDS; i++)
    {
        if (g_backends[i].name && (g_backends[i].backend_mask & backend_mask) != 0u && g_backends[i].reset)
        {
            int status = g_backends[i].reset();
            reset_seen = 1;
            if (status != 0)
            {
                g_profile.last_status = status;
                return status;
            }
        }
    }
    g_profile.last_status = reset_seen ? 0 : -1;
    return reset_seen ? 0 : -1;
}

int rvaic_register_cpu_fallback(int opcode, rvaic_op_fn fn, void *user)
{
    if (opcode < 0 || !fn)
    {
        return -1;
    }
    for (int i = 0; i < RVAIC_MAX_OPS; i++)
    {
        if (g_ops[i].opcode == opcode || g_ops[i].opcode < 0)
        {
            g_ops[i].opcode = opcode;
            g_ops[i].fn = fn;
            g_ops[i].user = user;
            return 0;
        }
    }
    return -1;
}

int rvaic_dispatch_op(int opcode, const rvaic_tensor_t *inputs, rvaic_tensor_t *outputs)
{
    for (int i = 0; i < RVAIC_MAX_OPS; i++)
    {
        if (g_ops[i].opcode == opcode && g_ops[i].fn)
        {
            int status = g_ops[i].fn(g_ops[i].user, inputs, outputs);
            g_profile.op_dispatches++;
            g_profile.last_status = status;
            return status;
        }
    }
    g_profile.last_status = -1;
    return -1;
}

int rvaic_npu_set_submitter(rvaic_npu_submit_fn fn, void *user)
{
    g_npu_submit = fn;
    g_npu_user = user;
    return 0;
}

int rvaic_npu_submit(const rvaic_npu_command_t *command)
{
    int status;

    if (!command || !g_npu_submit)
    {
        g_profile.last_status = -1;
        return -1;
    }
    status = g_npu_submit(g_npu_user, command);
    g_profile.npu_submits++;
    g_profile.last_status = status;
    return status;
}

int rvaic_profile(rvaic_profile_t *profile)
{
    if (!profile)
    {
        return -1;
    }
    *profile = g_profile;
    return 0;
}

rvaic_session_t *rvaic_session_create(const void *model, size_t model_size)
{
    const rvaic_model_t *compiled = (const rvaic_model_t *)model;
    struct rvaic_session *session;
    size_t available;

    if (!compiled || model_size < sizeof(*compiled))
    {
        return 0;
    }
    if (!valid_model(compiled))
    {
        return 0;
    }
    available = rvaic_arena_pool_ready() ? rvaic_arena_pool_available() : arena_available();
    if (!rvaic_arena_pool_ready() && compiled->arena && compiled->arena_size > available)
    {
        available = compiled->arena_size;
    }
    if (rvaic_model_admit(compiled, available, 0u) != 0)
    {
        return 0;
    }
    session = alloc_session();
    if (!session)
    {
        return 0;
    }
    memset(session, 0, sizeof(*session));

    if (compiled->arena_size > 0u && rvaic_arena_pool_ready())
    {
        if (rvaic_arena_reserve(compiled->arena_size, 8u, 1u, &session->arena_reservation) != 0)
        {
            return 0;
        }
        session->has_arena_reservation = 1;
    }
    else if (compiled->arena && compiled->arena_size > 0u)
    {
        if (rvaic_allocator_init(compiled->arena, compiled->arena_size) != 0)
        {
            return 0;
        }
    }

    session->model = compiled;
    session->in_use = 1;
    {
        struct rvaic_model_entry *entry = model_entry_by_model(compiled);
        if (entry)
        {
            entry->ref_count++;
        }
    }
    return session;
}

rvaic_session_t *rvaic_session_create_with_admission(
    const void *model,
    size_t model_size,
    const rvaic_admission_entry_t *entries,
    size_t count,
    uint32_t backend_mask)
{
    const rvaic_model_t *compiled = (const rvaic_model_t *)model;
    struct rvaic_session *session;

    if (!compiled || model_size < sizeof(*compiled) || !valid_model(compiled))
    {
        return 0;
    }
    session = alloc_session();
    if (!session)
    {
        return 0;
    }
    memset(session, 0, sizeof(*session));

    if (compiled->arena_size > 0u)
    {
        if (rvaic_model_reserve_contract(compiled, entries, count, backend_mask, &session->arena_reservation) != 0)
        {
            memset(session, 0, sizeof(*session));
            return 0;
        }
        session->has_arena_reservation = 1;
    }
    else if (rvaic_model_admit_contract(compiled, entries, count, rvaic_arena_pool_ready() ? rvaic_arena_pool_size() : session_available(session), backend_mask) != 0)
    {
        memset(session, 0, sizeof(*session));
        return 0;
    }

    session->model = compiled;
    session->in_use = 1;
    {
        struct rvaic_model_entry *entry = model_entry_by_model(compiled);
        if (entry)
        {
            entry->ref_count++;
        }
    }
    return session;
}

int rvaic_set_input(rvaic_session_t *session, int index, const rvaic_tensor_t *tensor)
{
    if (!valid_session(session) || !tensor || index < 0 || index >= session->model->input_count)
    {
        return -1;
    }

    session->inputs[index] = *tensor;
    return 0;
}

int rvaic_run(rvaic_session_t *session)
{
    int status;

    if (!valid_session(session))
    {
        return -1;
    }

    status = session->model->run(session->model->user, session->inputs, session->outputs);
    g_profile.runs++;
    g_profile.last_status = status;
    return status;
}

int rvaic_get_output(rvaic_session_t *session, int index, rvaic_tensor_t *tensor)
{
    if (!valid_session(session) || !tensor || index < 0 || index >= session->model->output_count)
    {
        return -1;
    }

    *tensor = session->outputs[index];
    return 0;
}

int rvaic_submit(rvaic_job_t *job)
{
    int status;

    if (!job)
    {
        return -1;
    }
    if (!valid_session(job->session))
    {
        job->state = RVAIC_JOB_FAILED;
        return -1;
    }
    if (job->state == RVAIC_JOB_CANCELLED)
    {
        job->status = RVAIC_STATUS_CANCELLED;
        signal_fence(job->fence, job->status);
        return job->status;
    }
    if (job->dependency && !job->dependency->signaled)
    {
        job->state = RVAIC_JOB_PENDING;
        job->status = -1;
        return -1;
    }
    if (job->dependency && job->dependency->status != 0)
    {
        job->state = RVAIC_JOB_FAILED;
        job->status = job->dependency->status;
        signal_fence(job->fence, job->status);
        return job->status;
    }
    if (rvaic_model_admit(job->session->model, session_available(job->session), job->backend_mask) != 0)
    {
        job->status = -1;
        job->state = RVAIC_JOB_FAILED;
        signal_fence(job->fence, job->status);
        return -1;
    }
    job->state = RVAIC_JOB_RUNNING;
    if (job->inputs)
    {
        for (int i = 0; i < job->session->model->input_count; i++)
        {
            job->session->inputs[i] = job->inputs[i];
        }
    }
    status = rvaic_run(job->session);
    if (status == 0 && job->outputs)
    {
        for (int i = 0; i < job->session->model->output_count; i++)
        {
            job->outputs[i] = job->session->outputs[i];
        }
    }
    job->status = status;
    job->state = RVAIC_JOB_DONE;
    g_profile.jobs++;
    signal_fence(job->fence, status);
    if (job->callback)
    {
        job->callback(job->user_data, status);
    }
    return status;
}

int rvaic_job_wait(const rvaic_job_t *job, uint32_t timeout_ticks)
{
    (void)timeout_ticks;
    if (!job)
    {
        return -1;
    }
    return job->status;
}

int rvaic_cancel(rvaic_job_t *job)
{
    if (!job || job->state == RVAIC_JOB_DONE)
    {
        return -1;
    }
    job->state = RVAIC_JOB_CANCELLED;
    job->status = RVAIC_STATUS_CANCELLED;
    signal_fence(job->fence, job->status);
    if (job->callback)
    {
        job->callback(job->user_data, job->status);
    }
    return 0;
}

int rvaic_timeout_check(rvaic_job_t *job, uint32_t elapsed_us)
{
    if (!job)
    {
        return -1;
    }
    if (job->timeout_us == 0u || elapsed_us <= job->timeout_us)
    {
        return 0;
    }
    job->state = RVAIC_JOB_DONE;
    job->status = RVAIC_STATUS_TIMEOUT;
    signal_fence(job->fence, job->status);
    if (job->callback)
    {
        job->callback(job->user_data, job->status);
    }
    return RVAIC_STATUS_TIMEOUT;
}

int rvaic_fence_wait(const rvaic_fence_t *fence, uint32_t timeout_ticks)
{
    if (!fence || !fence->signaled)
    {
#ifdef RT_USING_HEAP
        uint32_t waited = 0u;
        while (fence && !fence->signaled && (timeout_ticks == 0u || waited < timeout_ticks))
        {
            rt_thread_mdelay(1);
            waited++;
        }
        if (fence && fence->signaled)
        {
            return fence->status;
        }
#else
        (void)timeout_ticks;
#endif
        return -1;
    }
    return fence->status;
}

int rvaic_plan_admit(
    const rvaic_plan_t *plan,
    size_t arena_free_bytes,
    uint32_t backend_mask,
    uint32_t deadline_us,
    uint32_t min_evidence_level,
    rvaic_plan_admission_result_t *result)
{
    uint32_t reject = 0u;
    uint32_t required;

    if (backend_mask == 0u)
    {
        backend_mask = RVAIC_BACKEND_CPU | RVAIC_BACKEND_RVV | RVAIC_BACKEND_NPU;
    }
    required = plan_required_evidence_level(plan, min_evidence_level);

    if (!plan || !plan->verified)
    {
        reject |= RVAIC_PLAN_REJECT_UNVERIFIED;
    }
    if (!plan || (plan->backend_mask & backend_mask) == 0u)
    {
        reject |= RVAIC_PLAN_REJECT_BACKEND;
    }
    if (plan && plan->arena_bytes > arena_free_bytes)
    {
        reject |= RVAIC_PLAN_REJECT_MEMORY;
    }
    if (plan && deadline_us != 0u && plan->expected_latency_us > deadline_us)
    {
        reject |= RVAIC_PLAN_REJECT_DEADLINE;
    }
    if (plan_evidence_level(plan) < required)
    {
        reject |= RVAIC_PLAN_REJECT_EVIDENCE;
    }
    if (plan && !target_hash_matches(plan->target_hash))
    {
        reject |= RVAIC_PLAN_REJECT_TARGET;
    }
    if (result)
    {
        result->accepted = reject == 0u ? 1u : 0u;
        result->reject_mask = reject;
        result->arena_free_bytes = arena_free_bytes;
        result->backend_mask = backend_mask;
        result->deadline_us = deadline_us;
        result->min_evidence_level = required;
        result->target_hash_match = (reject & RVAIC_PLAN_REJECT_TARGET) == 0u ? 1u : 0u;
    }
    return reject == 0u ? 0 : RVAIC_STATUS_INVALID_PLAN;
}

const rvaic_plan_t *rvaic_plan_select_with_evidence(
    const rvaic_plan_t *plans,
    size_t count,
    size_t arena_free_bytes,
    uint32_t backend_mask,
    uint32_t deadline_us,
    uint32_t min_evidence_level,
    rvaic_plan_admission_result_t *result)
{
    const rvaic_plan_t *best = 0;
    rvaic_plan_admission_result_t current;

    if (!plans)
    {
        return 0;
    }
    for (size_t i = 0; i < count; i++)
    {
        if (rvaic_plan_admit(&plans[i], arena_free_bytes, backend_mask, deadline_us, min_evidence_level, &current) != 0)
        {
            if (result && !best)
            {
                *result = current;
            }
            continue;
        }
        if (!best || plans[i].expected_latency_us < best->expected_latency_us)
        {
            best = &plans[i];
            if (result)
            {
                *result = current;
            }
        }
    }
    return best;
}

const rvaic_plan_t *rvaic_plan_select(const rvaic_plan_t *plans, size_t count, size_t arena_free_bytes, uint32_t backend_mask, uint32_t deadline_us)
{
    return rvaic_plan_select_with_evidence(plans, count, arena_free_bytes, backend_mask, deadline_us, RVAIC_EVIDENCE_E3, 0);
}

int rvaic_plan_execute(rvaic_session_t *session, const rvaic_plan_t *plan, const rvaic_tensor_t *inputs, rvaic_tensor_t *outputs, rvaic_fence_t *fence)
{
    int status;

    if (!valid_session(session) || rvaic_plan_admit(plan, session_available(session), plan ? plan->backend_mask : 0u, 0u, RVAIC_EVIDENCE_E3, 0) != 0)
    {
        signal_fence(fence, RVAIC_STATUS_INVALID_PLAN);
        return RVAIC_STATUS_INVALID_PLAN;
    }
    if (rvaic_model_admit(session->model, session_available(session), plan->backend_mask) != 0)
    {
        signal_fence(fence, -1);
        return -1;
    }
    if (inputs)
    {
        for (int i = 0; i < session->model->input_count; i++)
        {
            session->inputs[i] = inputs[i];
        }
    }
    status = rvaic_run(session);
    if (status == 0 && outputs)
    {
        for (int i = 0; i < session->model->output_count; i++)
        {
            outputs[i] = session->outputs[i];
        }
    }
    signal_fence(fence, status);
    return status;
}

void rvaic_session_destroy(const rvaic_session_t *session)
{
    rvaic_session_t *mutable_session = (rvaic_session_t *)session;

    if (valid_session(session))
    {
        if (mutable_session->has_arena_reservation)
        {
            (void)rvaic_arena_release(&mutable_session->arena_reservation);
        }
        {
            struct rvaic_model_entry *entry = model_entry_by_model(mutable_session->model);
            if (entry && entry->ref_count > 0u)
            {
                entry->ref_count--;
            }
        }
        memset(mutable_session, 0, sizeof(*mutable_session));
    }
}

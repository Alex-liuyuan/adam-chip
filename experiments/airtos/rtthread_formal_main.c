#include <stdint.h>
#include <string.h>

#include <rtthread.h>
#include "rt_ai_internal.h"
#include "coherency_formal.h"

#define CORPUS_ADDRESS UINT64_C(0x88000000)
#define CORPUS_MAGIC UINT32_C(0x46545241)

typedef struct {
    const uint8_t *cursor;
    const uint8_t *end;
} reader_t;

static uint32_t u32(reader_t *reader)
{
    uint32_t value = 0U;
    if ((size_t)(reader->end - reader->cursor) >= sizeof(value)) {
        memcpy(&value, reader->cursor, sizeof(value));
        reader->cursor += sizeof(value);
    }
    return value;
}

static int32_t i32(reader_t *reader) { return (int32_t)u32(reader); }

static uint64_t u64(reader_t *reader)
{
    uint64_t value = 0U;
    if ((size_t)(reader->end - reader->cursor) >= sizeof(value)) {
        memcpy(&value, reader->cursor, sizeof(value));
        reader->cursor += sizeof(value);
    }
    return value;
}

static int read_job(reader_t *words, rt_ai_sim_job_t *job)
{
    uint64_t segment_count;
    unsigned index;
    job->release_us = u64(words);
    job->deadline_us = u64(words);
    segment_count = u64(words);
    job->relative_deadline_us = (uint32_t)u64(words);
    if (segment_count == 0U || segment_count > RT_AI_MAX_SEGMENTS) return 0;
    job->segment_count = (uint16_t)segment_count;
    for (index = 0U; index < RT_AI_MAX_RESOURCES; ++index) {
        job->reservation_budget_us[index] = (uint32_t)u64(words);
        job->reservation_period_us[index] = (uint32_t)u64(words);
    }
    for (index = 0U; index < job->segment_count; ++index) {
        uint64_t resource = u64(words);
        uint64_t state = u64(words);
        if (resource >= RT_AI_MAX_RESOURCES || state > RT_AI_SEG_DONE) return 0;
        job->segments[index].resource = (uint8_t)resource;
        job->segments[index].state = (uint8_t)state;
        job->segments[index].dependency_mask = (uint32_t)u64(words);
        job->segments[index].cost_us = u64(words);
    }
    return 1;
}

static int run_schedule(reader_t *corpus, uint64_t *scenario_id)
{
    uint32_t word_count = u32(corpus);
    int expected_status = i32(corpus);
    uint64_t expected_finish = u64(corpus);
    reader_t words;
    rt_ai_schedule_snapshot_t snapshot;
    rt_ai_aeg_t candidate;
    rt_ai_aeg_segment_t segments[RT_AI_MAX_SEGMENTS];
    uint64_t deadline;
    uint64_t finish = 0U;
    uint64_t job_count;
    uint64_t segment_count;
    unsigned index;
    int status;
    if ((uint64_t)(corpus->end - corpus->cursor) < (uint64_t)word_count * sizeof(uint64_t)) return 0;
    words.cursor = corpus->cursor;
    words.end = corpus->cursor + (size_t)word_count * sizeof(uint64_t);
    corpus->cursor = words.end;
    memset(&snapshot, 0, sizeof(snapshot));
    memset(&candidate, 0, sizeof(candidate));
    *scenario_id = u64(&words);
    snapshot.now_us = u64(&words);
    job_count = u64(&words);
    if (job_count > RT_AI_MAX_JOBS) return 0;
    snapshot.job_count = (uint16_t)job_count;
    for (index = 0U; index < snapshot.job_count; ++index) if (!read_job(&words, &snapshot.jobs[index])) return 0;
    deadline = u64(&words);
    segment_count = u64(&words);
    candidate.relative_deadline_us = (uint32_t)u64(&words);
    if (segment_count == 0U || segment_count > RT_AI_MAX_SEGMENTS) return 0;
    candidate.header.segment_count = (uint16_t)segment_count;
    for (index = 0U; index < RT_AI_MAX_RESOURCES; ++index) {
        candidate.reservation_budget_us[index] = (uint32_t)u64(&words);
        candidate.reservation_period_us[index] = (uint32_t)u64(&words);
    }
    for (index = 0U; index < candidate.header.segment_count; ++index) {
        uint64_t resource = u64(&words);
        uint32_t dependency = (uint32_t)u64(&words);
        if (resource >= RT_AI_MAX_RESOURCES) return 0;
        candidate.wcet_us[index] = (uint32_t)u64(&words);
        candidate.coherency_cost_us[index] = (uint32_t)u64(&words);
        candidate.recovery_cost_us[index] = (uint32_t)u64(&words);
        segments[index] = (rt_ai_aeg_segment_t){(uint16_t)(index + 1U), (uint8_t)resource, 0U,
            dependency, 0U, 1U};
    }
    if (words.cursor != words.end) return 0;
    candidate.segments = segments;
    status = rt_ai_sim_edf(&candidate, &snapshot, deadline, &finish);
    return status == expected_status && finish == expected_finish;
}

static int run_formal(void)
{
    const uint8_t *base = (const uint8_t *)(uintptr_t)CORPUS_ADDRESS;
    reader_t corpus = {base, base + UINT32_C(64) * 1024U * 1024U};
    uint32_t magic = u32(&corpus);
    uint32_t version = u32(&corpus);
    uint32_t total_size = u32(&corpus);
    uint32_t loader_count = u32(&corpus);
    uint32_t schedule_count = u32(&corpus);
    uint32_t loader_failures = 0U, schedule_failures = 0U;
    uint32_t index;
    if (magic != CORPUS_MAGIC || version != 1U || total_size < 20U || total_size > UINT32_C(64) * 1024U * 1024U)
        return 0;
    corpus.end = base + total_size;
    for (index = 0U; index < loader_count; ++index) {
        uint32_t size = u32(&corpus);
        int expected = i32(&corpus);
        rt_ai_aeg_t aeg;
        int status;
        if ((size_t)(corpus.end - corpus.cursor) < size) return 0;
        status = rt_ai_load(corpus.cursor, size, &aeg);
        corpus.cursor += size;
        if (status != expected) ++loader_failures;
    }
    for (index = 0U; index < schedule_count; ++index) {
        uint64_t scenario_id = 0U;
        if (!run_schedule(&corpus, &scenario_id)) {
            if (schedule_failures < 5U) rt_kprintf("AIRTOS_RTTHREAD_FORMAL_MISMATCH scenario=%llu\n", scenario_id);
            ++schedule_failures;
        }
    }
    rt_kprintf("AIRTOS_RTTHREAD_FORMAL loader_cases=%u loader_failures=%u schedule_cases=%u schedule_failures=%u bytes=%u\n",
        loader_count, loader_failures, schedule_count, schedule_failures, total_size);
    return corpus.cursor == corpus.end && loader_failures == 0U && schedule_failures == 0U;
}

int main(void)
{
    uint32_t coherency_negative = 0U, coherency_failures = 0U;
    int passed = run_formal() && airtos_coherency_formal_run(UINT32_C(1000000), &coherency_negative, &coherency_failures);
    rt_kprintf("AIRTOS_RTTHREAD_COHERENCY cases=1000000 negative=%u failures=%u\n",
        coherency_negative, coherency_failures);
    if (passed) rt_kprintf("AIRTOS_RTTHREAD_FORMAL_PASS machine=virt64 coherency_cases=1000000\n");
    else rt_kprintf("AIRTOS_RTTHREAD_FORMAL_FAIL machine=virt64\n");
    *(volatile uint32_t *)(uintptr_t)UINT32_C(0x00100000) = passed ? UINT32_C(0x5555) : UINT32_C(0x3333);
    for (;;) { }
}

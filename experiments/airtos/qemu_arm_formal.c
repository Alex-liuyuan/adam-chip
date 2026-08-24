#include <stddef.h>
#include <stdint.h>

#include "rt_ai_internal.h"
#include "coherency_formal.h"

#ifndef MACHINE_NAME
#define MACHINE_NAME "unknown"
#endif
#ifndef CORPUS_PATH
#define CORPUS_PATH "rtthread_formal_corpus.bin"
#endif

#define CORPUS_MAGIC UINT32_C(0x46545241)
#define LOADER_BUFFER_SIZE 2048U
#define WORD_BUFFER_COUNT 1024U

extern uint32_t _stack_top, _sidata, _sdata, _edata, _sbss, _ebss;
void reset_handler(void);
static void default_handler(void);

__attribute__((section(".isr_vector"), used))
static void (*const vectors[])(void) = {
    (void (*)(void))&_stack_top, reset_handler,
    default_handler, default_handler, default_handler, default_handler,
    default_handler, default_handler, default_handler, default_handler,
    default_handler, default_handler, default_handler, default_handler,
    default_handler, default_handler
};

void *memset(void *destination, int value, size_t size)
{
    uint8_t *bytes = (uint8_t *)destination;
    while (size-- != 0U) *bytes++ = (uint8_t)value;
    return destination;
}

void *memcpy(void *destination, const void *source, size_t size)
{
    uint8_t *out = (uint8_t *)destination;
    const uint8_t *in = (const uint8_t *)source;
    while (size-- != 0U) *out++ = *in++;
    return destination;
}

int memcmp(const void *left, const void *right, size_t size)
{
    const uint8_t *a = (const uint8_t *)left, *b = (const uint8_t *)right;
    while (size-- != 0U) {
        if (*a != *b) return (int)*a - (int)*b;
        ++a;
        ++b;
    }
    return 0;
}

static int semihost(uint32_t operation, const void *argument)
{
    register uint32_t r0 __asm("r0") = operation;
    register const void *r1 __asm("r1") = argument;
    __asm volatile("bkpt 0xab" : "+r"(r0) : "r"(r1) : "memory");
    return (int)r0;
}

static void write0(const char *text) { (void)semihost(4U, text); }

__attribute__((noreturn)) static void finish(uint32_t status)
{
    uint32_t arguments[2] = {UINT32_C(0x20026), status};
    (void)semihost(0x20U, arguments);
    for (;;) { }
}

typedef struct {
    int handle;
    uint32_t consumed;
} stream_t;

typedef struct {
    const uint8_t *cursor;
    const uint8_t *end;
} reader_t;

static int stream_read(stream_t *stream, void *buffer, uint32_t size)
{
    uint32_t arguments[3] = {(uint32_t)stream->handle, (uint32_t)(uintptr_t)buffer, size};
    int unread = semihost(6U, arguments);
    if (unread != 0) return 0;
    stream->consumed += size;
    return 1;
}

static uint32_t stream_u32(stream_t *stream, int *ok)
{
    uint8_t bytes[4];
    if (!stream_read(stream, bytes, sizeof(bytes))) { *ok = 0; return 0U; }
    return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8U) |
        ((uint32_t)bytes[2] << 16U) | ((uint32_t)bytes[3] << 24U);
}

static uint64_t read_u64(reader_t *reader)
{
    uint64_t value = 0U;
    if ((size_t)(reader->end - reader->cursor) < sizeof(value)) return 0U;
    memcpy(&value, reader->cursor, sizeof(value));
    reader->cursor += sizeof(value);
    return value;
}

static int read_job(reader_t *words, rt_ai_sim_job_t *job)
{
    uint64_t segment_count;
    unsigned index;
    job->release_us = read_u64(words);
    job->deadline_us = read_u64(words);
    segment_count = read_u64(words);
    job->relative_deadline_us = (uint32_t)read_u64(words);
    if (segment_count == 0U || segment_count > RT_AI_MAX_SEGMENTS) return 0;
    job->segment_count = (uint16_t)segment_count;
    for (index = 0U; index < RT_AI_MAX_RESOURCES; ++index) {
        job->reservation_budget_us[index] = (uint32_t)read_u64(words);
        job->reservation_period_us[index] = (uint32_t)read_u64(words);
    }
    for (index = 0U; index < job->segment_count; ++index) {
        uint64_t resource = read_u64(words), state = read_u64(words);
        if (resource >= RT_AI_MAX_RESOURCES || state > RT_AI_SEG_DONE) return 0;
        job->segments[index].resource = (uint8_t)resource;
        job->segments[index].state = (uint8_t)state;
        job->segments[index].dependency_mask = (uint32_t)read_u64(words);
        job->segments[index].cost_us = read_u64(words);
    }
    return 1;
}

static int run_schedule(const uint64_t *buffer, uint32_t word_count, int expected_status, uint64_t expected_finish)
{
    reader_t words = {(const uint8_t *)buffer, (const uint8_t *)(buffer + word_count)};
    rt_ai_schedule_snapshot_t snapshot;
    rt_ai_aeg_t candidate;
    rt_ai_aeg_segment_t segments[RT_AI_MAX_SEGMENTS];
    uint64_t deadline, finish = 0U, job_count, segment_count;
    unsigned index;
    (void)read_u64(&words);
    memset(&snapshot, 0, sizeof(snapshot));
    memset(&candidate, 0, sizeof(candidate));
    snapshot.now_us = read_u64(&words);
    job_count = read_u64(&words);
    if (job_count > RT_AI_MAX_JOBS) return 0;
    snapshot.job_count = (uint16_t)job_count;
    for (index = 0U; index < snapshot.job_count; ++index) if (!read_job(&words, &snapshot.jobs[index])) return 0;
    deadline = read_u64(&words);
    segment_count = read_u64(&words);
    candidate.relative_deadline_us = (uint32_t)read_u64(&words);
    if (segment_count == 0U || segment_count > RT_AI_MAX_SEGMENTS) return 0;
    candidate.header.segment_count = (uint16_t)segment_count;
    for (index = 0U; index < RT_AI_MAX_RESOURCES; ++index) {
        candidate.reservation_budget_us[index] = (uint32_t)read_u64(&words);
        candidate.reservation_period_us[index] = (uint32_t)read_u64(&words);
    }
    for (index = 0U; index < candidate.header.segment_count; ++index) {
        uint64_t resource = read_u64(&words);
        uint32_t dependency = (uint32_t)read_u64(&words);
        if (resource >= RT_AI_MAX_RESOURCES) return 0;
        candidate.wcet_us[index] = (uint32_t)read_u64(&words);
        candidate.coherency_cost_us[index] = (uint32_t)read_u64(&words);
        candidate.recovery_cost_us[index] = (uint32_t)read_u64(&words);
        segments[index] = (rt_ai_aeg_segment_t){(uint16_t)(index + 1U), (uint8_t)resource, 0U, dependency, 0U, 1U};
    }
    if (words.cursor != words.end) return 0;
    candidate.segments = segments;
    return rt_ai_sim_edf(&candidate, &snapshot, deadline, &finish) == expected_status && finish == expected_finish;
}

static int run_formal(void)
{
    static uint8_t loader_buffer[LOADER_BUFFER_SIZE];
    static uint64_t word_buffer[WORD_BUFFER_COUNT];
    static const char path[] = CORPUS_PATH;
    uint32_t open_arguments[3] = {(uint32_t)(uintptr_t)path, 1U, sizeof(path) - 1U};
    stream_t stream;
    uint32_t magic, version, total_size, loader_count, schedule_count;
    uint32_t loader_failures = 0U, schedule_failures = 0U, coherency_negative = 0U, coherency_failures = 0U, index;
    int ok = 1;
    stream.handle = semihost(1U, open_arguments);
    stream.consumed = 0U;
    if (stream.handle < 0) return 0;
    magic = stream_u32(&stream, &ok);
    version = stream_u32(&stream, &ok);
    total_size = stream_u32(&stream, &ok);
    loader_count = stream_u32(&stream, &ok);
    schedule_count = stream_u32(&stream, &ok);
    if (!ok || magic != CORPUS_MAGIC || version != 1U || total_size < 20U) return 0;
    for (index = 0U; index < loader_count; ++index) {
        uint32_t size = stream_u32(&stream, &ok);
        int expected = (int32_t)stream_u32(&stream, &ok);
        rt_ai_aeg_t aeg;
        if (!ok || size > sizeof(loader_buffer) || !stream_read(&stream, loader_buffer, size)) return 0;
        if (rt_ai_load(loader_buffer, size, &aeg) != expected) ++loader_failures;
    }
    for (index = 0U; index < schedule_count; ++index) {
        uint32_t word_count = stream_u32(&stream, &ok);
        int expected = (int32_t)stream_u32(&stream, &ok);
        uint32_t low = stream_u32(&stream, &ok), high = stream_u32(&stream, &ok);
        uint64_t expected_finish = (uint64_t)low | ((uint64_t)high << 32U);
        if (!ok || word_count > WORD_BUFFER_COUNT ||
            !stream_read(&stream, word_buffer, word_count * sizeof(word_buffer[0]))) return 0;
        if (!run_schedule(word_buffer, word_count, expected, expected_finish)) ++schedule_failures;
    }
    {
        uint32_t close_argument = (uint32_t)stream.handle;
        if (semihost(2U, &close_argument) != 0) return 0;
    }
    if (stream.consumed != total_size) return 0;
    if (!airtos_coherency_formal_run(UINT32_C(1000000), &coherency_negative, &coherency_failures)) return 0;
    if (loader_failures == 0U && schedule_failures == 0U && coherency_failures == 0U) {
        write0("AIRTOS_ARM_FORMAL_PASS machine=" MACHINE_NAME " loader_cases=7950 schedule_cases=24548 coherency_cases=1000000 failures=0\n");
        return 1;
    }
    write0("AIRTOS_ARM_FORMAL_FAIL machine=" MACHINE_NAME "\n");
    return 0;
}

void reset_handler(void)
{
    uint32_t *source = &_sidata, *destination;
    for (destination = &_sdata; destination < &_edata; ++destination) *destination = *source++;
    for (destination = &_sbss; destination < &_ebss; ++destination) *destination = 0U;
    finish(run_formal() ? 0U : 1U);
}

static void default_handler(void) { finish(2U); }

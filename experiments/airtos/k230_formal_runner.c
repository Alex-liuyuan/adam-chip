#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rt_ai_internal.h"

#define CORPUS_MAGIC UINT32_C(0x46545241)

typedef struct {
    const uint64_t *cursor;
    const uint64_t *end;
} words_t;

static uint64_t word(words_t *words)
{
    return words->cursor < words->end ? *words->cursor++ : 0U;
}

static int read_job(words_t *words, rt_ai_sim_job_t *job)
{
    uint64_t count;
    unsigned index;
    job->release_us = word(words);
    job->deadline_us = word(words);
    count = word(words);
    job->relative_deadline_us = (uint32_t)word(words);
    if (count == 0U || count > RT_AI_MAX_SEGMENTS) return 0;
    job->segment_count = (uint16_t)count;
    for (index = 0U; index < RT_AI_MAX_RESOURCES; ++index) {
        job->reservation_budget_us[index] = (uint32_t)word(words);
        job->reservation_period_us[index] = (uint32_t)word(words);
    }
    for (index = 0U; index < job->segment_count; ++index) {
        uint64_t resource = word(words), state = word(words);
        if (resource >= RT_AI_MAX_RESOURCES || state > RT_AI_SEG_DONE) return 0;
        job->segments[index].resource = (uint8_t)resource;
        job->segments[index].state = (uint8_t)state;
        job->segments[index].dependency_mask = (uint32_t)word(words);
        job->segments[index].cost_us = word(words);
    }
    return 1;
}

static int run_schedule(const uint64_t *values, uint32_t count, int expected_status, uint64_t expected_finish)
{
    words_t words = {values, values + count};
    rt_ai_schedule_snapshot_t snapshot;
    rt_ai_aeg_t candidate;
    rt_ai_aeg_segment_t segments[RT_AI_MAX_SEGMENTS];
    uint64_t deadline, finish = 0U, job_count, segment_count;
    unsigned index;
    int status;
    memset(&snapshot, 0, sizeof(snapshot));
    memset(&candidate, 0, sizeof(candidate));
    (void)word(&words); /* scenario ID */
    snapshot.now_us = word(&words);
    job_count = word(&words);
    if (job_count > RT_AI_MAX_JOBS) return 0;
    snapshot.job_count = (uint16_t)job_count;
    for (index = 0U; index < snapshot.job_count; ++index)
        if (!read_job(&words, &snapshot.jobs[index])) return 0;
    deadline = word(&words);
    segment_count = word(&words);
    candidate.relative_deadline_us = (uint32_t)word(&words);
    if (segment_count == 0U || segment_count > RT_AI_MAX_SEGMENTS) return 0;
    candidate.header.segment_count = (uint16_t)segment_count;
    for (index = 0U; index < RT_AI_MAX_RESOURCES; ++index) {
        candidate.reservation_budget_us[index] = (uint32_t)word(&words);
        candidate.reservation_period_us[index] = (uint32_t)word(&words);
    }
    for (index = 0U; index < candidate.header.segment_count; ++index) {
        uint64_t resource = word(&words);
        uint32_t dependency = (uint32_t)word(&words);
        if (resource >= RT_AI_MAX_RESOURCES) return 0;
        candidate.wcet_us[index] = (uint32_t)word(&words);
        candidate.coherency_cost_us[index] = (uint32_t)word(&words);
        candidate.recovery_cost_us[index] = (uint32_t)word(&words);
        segments[index] = (rt_ai_aeg_segment_t){(uint16_t)(index + 1U), (uint8_t)resource, 0U,
            dependency, 0U, 1U};
    }
    if (words.cursor != words.end) return 0;
    candidate.segments = segments;
    status = rt_ai_sim_edf(&candidate, &snapshot, deadline, &finish);
    return status == expected_status && finish == expected_finish;
}

static int read_exact(FILE *stream, void *buffer, size_t size)
{
    return fread(buffer, 1U, size, stream) == size;
}

int main(int argc, char **argv)
{
    FILE *stream;
    uint32_t header[5], loader_failures = 0U, schedule_failures = 0U, index;
    uint64_t consumed = sizeof(header);
    if (argc != 2 || (stream = fopen(argv[1], "rb")) == NULL || !read_exact(stream, header, sizeof(header))) return 2;
    if (header[0] != CORPUS_MAGIC || header[1] != 1U || header[2] < sizeof(header)) return 2;
    for (index = 0U; index < header[3]; ++index) {
        uint32_t size;
        int32_t expected;
        uint8_t *blob;
        rt_ai_aeg_t aeg;
        if (!read_exact(stream, &size, sizeof(size)) || !read_exact(stream, &expected, sizeof(expected)) ||
            size == 0U || (blob = malloc(size)) == NULL || !read_exact(stream, blob, size)) return 2;
        if (rt_ai_load(blob, size, &aeg) != expected) ++loader_failures;
        free(blob);
        consumed += 8U + size;
    }
    for (index = 0U; index < header[4]; ++index) {
        uint32_t count;
        int32_t expected;
        uint64_t finish, *values;
        if (!read_exact(stream, &count, sizeof(count)) || !read_exact(stream, &expected, sizeof(expected)) ||
            !read_exact(stream, &finish, sizeof(finish)) || count == 0U ||
            (values = malloc((size_t)count * sizeof(*values))) == NULL ||
            !read_exact(stream, values, (size_t)count * sizeof(*values))) return 2;
        if (!run_schedule(values, count, expected, finish)) ++schedule_failures;
        free(values);
        consumed += 16U + (uint64_t)count * sizeof(*values);
    }
    fclose(stream);
    printf("AIRTOS_K230_FORMAL loader_cases=%u loader_failures=%u schedule_cases=%u schedule_failures=%u bytes=%" PRIu64 "\n",
        header[3], loader_failures, header[4], schedule_failures, consumed);
    if (consumed == header[2] && loader_failures == 0U && schedule_failures == 0U) {
        puts("AIRTOS_K230_FORMAL_PASS");
        return 0;
    }
    puts("AIRTOS_K230_FORMAL_FAIL");
    return 1;
}

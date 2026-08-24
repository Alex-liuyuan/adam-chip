#include "rvaic.h"

#include <assert.h>
#include <string.h>

extern const rvaic_model_t demo_model;

int demo_run(void *user, const rvaic_tensor_t *inputs, rvaic_tensor_t *outputs)
{
    (void)user;
    outputs[0] = inputs[0];
    return 0;
}

int main(void)
{
    int values[2] = {7, 9};
    rvaic_tensor_t input;
    rvaic_tensor_t output;
    rvaic_job_t job;
    rvaic_backend_ops_t cpu_backend;
    rvaic_session_t *session;

    memset(&input, 0, sizeof(input));
    memset(&output, 0, sizeof(output));
    memset(&job, 0, sizeof(job));
    memset(&cpu_backend, 0, sizeof(cpu_backend));
    input.data = values;
    input.ndim = 1;
    input.shape[0] = 2;

    assert(rvaic_init() == 0);
    cpu_backend.name = "cpu";
    cpu_backend.backend_mask = RVAIC_BACKEND_CPU;
    assert(rvaic_backend_register(&cpu_backend) == 0);
    assert(rvaic_backend_find("cpu") != 0);
    assert(rvaic_model_register("demo", &demo_model) == 0);
    assert(rvaic_model_count() == 1);
    session = rvaic_session_create(rvaic_model_find("demo"), sizeof(demo_model));
    assert(session != 0);
    job.session = session;
    job.inputs = &input;
    job.outputs = &output;
    job.backend_mask = RVAIC_BACKEND_CPU;
    assert(rvaic_submit(&job) == 0);
    assert(rvaic_job_wait(&job, 0) == 0);
    assert(output.data == values);
    assert(output.shape[0] == 2);
    rvaic_session_destroy(session);

    return 0;
}

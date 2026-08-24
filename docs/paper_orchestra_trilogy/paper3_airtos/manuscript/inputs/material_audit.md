# AIRTOS Material Audit Before Manuscript Drafting

## 1. Source Precedence

The manuscript uses two complementary authorities rather than one flat ordering.

For the research question, theory, innovation boundary, and paper organization, `theoretical_design.md` is the primary source. Its seven industry problems, joint `Admit` predicate, `SimEDF+`, lease/coherency/recovery semantics, conditional theorems, four-core evaluation design, and N1--N6 proof obligations define what the paper is about. The shared trilogy framework and verified literature review supply the upstream evidence semantics and novelty boundary.

For implementation and empirical strength, claims are resolved in this order:

1. Raw v6 serial logs and the current production/runtime source code.
2. The recomputed v6 `summary.json` and status files.
3. The v6 experiment report, anomaly log, material passport, and frozen protocol.
4. The implementation blueprint and secondary summaries.
5. The initial RT-Thread AI-OS research plan, which is historical design context rather than a description of the delivered system.

This separation preserves the theoretical paper rather than reducing it to a test report, while preventing outdated plans or unchecked prose from expanding empirical claims.

The IEEE package determines format. The supplied IoT Journal paper determines the expected density and broad systems-paper structure, but no prose, figures, or claims are copied from it.

## 2. What AIRTOS Actually Is

AIRTOS is a portable C runtime governance layer that executes on RT-Smart and can be replayed on host and QEMU environments. It consumes an evidence-carrying AEG v2 plan and decides whether the plan may enter the live runtime. Its novelty is not EDF, DAG scheduling, NPU sharing, cache maintenance, or timeout APIs individually. It combines plan qualification, live-resource checks, memory-time atomicity, explicit coherency, and recovery attribution in one admission and execution path.

The current artifact is not a completed RT-Thread kernel fork, not a new general-purpose RTOS, and not the kernel-reservation/LWP architecture described in `initial_research_plan.md`. The production coordinator still uses a polling entry point and a broad port lock around dispatch/provider work. Consequently, the paper must use “runtime” or “governance layer,” not “native AI operating system,” and must not claim CPU reservation, protected control-task jitter, RT-Smart process isolation, or event-driven ISR/worker decomposition.

## 3. Plan and Runtime Contract

The tested plan contains one float32 Add+ReLU operator over shape `[1,8]`, a 64-byte arena, a 100 us minimum interarrival time, and a 100 us relative deadline. Its primary RVV segment has registered costs of 4 us WCET, 1 us coherency, and 50 us recovery. Its CPU fallback has 10 us WCET, 1 us coherency, and 50 us recovery. The plan requires `rv64gc`, little-endian execution, and coherent plan buffers. Evidence records independently bind CPU and RVV generated code and numerical outputs to the declared domain.

At session creation, AIRTOS checks plan, evidence, policy, model, target, runtime-ABI, and provider-ABI hashes; per-obligation scope, artifact, verifier, resource, verified status, and verifier allowlisting; plus primary/fallback evidence-resource consistency.

At submission, it checks the invocation plan hash, shape, dtype, layout, input/output byte sizes, deployment/evidence status, deadline and minimum interarrival, provider health, arena availability, and schedule feasibility. The effective predicate is:

`Parse AND Bind AND Domain AND Evidence AND Provider AND Memory AND Coherence AND Sched AND Recoverable`.

The memory-time transaction is optimistic: under the runtime lock it chooses a job slot, probes an arena interval, captures lease and schedule generations, and snapshots admitted work. It runs `SimEDF+` outside the lock, then reacquires the lock and commits the lease and job only if the slot, session, provider, and both generations remain valid. No fallible step follows the arena commit before job publication; provider-health failure releases the committed lease before rejection.

## 4. Scheduling Semantics

Jobs contain segment DAGs over CPU, RVV, NPU, and DMA resource identifiers. Only dependency-ready segments enter stable per-resource EDF queues. Running segments are non-preemptive in both the runtime model and simulator. `SimEDF+` reconstructs all admitted jobs and the candidate, includes active residual, coherency and recovery charges, advances each resource independently, checks reservation demand at job deadlines, and rechecks every old and new deadline.

The runtime deliberately delays logical completion until `start + registered budget` when hardware finishes early. This prevents an early predecessor from releasing a low-priority successor that can occupy another non-preemptive device before a higher-priority job becomes ready. The conditional deadline theorem therefore requires runtime/simulator equivalence, modelled arrivals and faults, atomic admission, and actual execution no greater than the registered cost.

The v6 board replay ran the loader and simulator against frozen expected outcomes. It establishes implementation consistency for 7,950 loader cases and 24,548 scheduling scenarios; it is not an execution of 24,548 physical heterogeneous workloads and does not validate the original WCET table.

## 5. Memory and Coherency Semantics

The arena allocator uses generation-checked first-fit leases and rejects overlap at commit. The inter-session theorem additionally assumes the provider accesses only declared ranges; it does not prove alias correctness within one session.

For a segment, AIRTOS rounds its declared range to cache lines within the active lease, performs an optional clean, then a barrier before submit; after completion it performs a barrier, optional invalidate, and a final barrier. The K230 physical test used cached MMZ buffers and GSDMA physical addresses. Each of four sizes ran 250,000 complete transfers. Omitted clean and omitted invalidate were tested 100 times per size after making stale destination data observable. Thus the physical result supports the tested K230 buffer/engine/size contract, not arbitrary DMA engines, alignments, shared cache lines, or chips.

## 6. Completion and Recovery Semantics

A completion is accepted only when device/resource, current epoch, active job, active cookie, and running segment state agree. Cookie wrap increments the epoch before cookie reuse. On cancellation or timeout, AIRTOS polls cancellation, increments epoch before reset, polls reset and reinitialization within plan-provided timeouts, repeats up to `max_reset_attempts`, and otherwise quarantines the resource. The failed job retains its lease until recovery closes or fallback completes.

Fallback is not an unconditional jump. It re-evaluates the session trust bundle, confirms the original lease is still active and covers every fallback range, checks fallback-provider health, snapshots current admitted work, and calls `SimEDF+` with the fallback plan and the original absolute deadline.

The 700,000 stale-event cases and 7,500 recovery/budget/fallback cases executed the production state-machine code on the board but used controlled in-process fault callbacks. They support finite state-machine consistency, not naturally late driver interrupts, physical reset timing, or production NPU/DMA fault recovery. The 300 GSDMA lifecycle cases did call the physical library and verified a copy after deinitialize/reinitialize, but this is device reopen/reinitialization rather than a chip hard reset.

## 7. Trace and Feedback Semantics

Trace entries carry logical sequence, monotonic timestamp, run ID, plan hash, job, segment, resource, epoch, cookie, event, status, and queue depth. Ring snapshots are chronological and report dropped entries. The classifier maps eight synthetic root-cause classes to the next experiment. A new plan still needs a new hash, evidence, and admission record. Macro-F1 and top-3 results of 1.0 apply only to the frozen synthetic labels, including the 2,400 noise/ring-wrap cases; they do not establish external validity on natural workloads.

## 8. Exact Evidence Outcomes

- Core 1: 3,900 admission cases, 23,400 diagnostic cases, 300 provider-health races, 1,500 trust-root decisions, and 400,000 concurrent transactions. No unsafe admission failure, overlap, rollback leak, or partial commit was observed.
- Core 2: 7,950 loader cases and 24,548 simulator/oracle replay cases had zero mismatch. CPU and RVV Add+ReLU each ran 30,000 measured calls with zero numeric failure.
- Core 3: 1,000,000 allocation attempts produced 948,950 successful leases with zero tracked safety failure. One million physical DMA transfers had zero byte mismatch; all 800 omitted-operation controls were observable.
- Core 4: 700,000 stale events, 1,500 legacy recovery episodes, 4,800 recovery-budget episodes, 1,200 fallback-gate episodes, 800 base trace cases, 2,400 robust trace cases, and 300 physical GSDMA lifecycle cases met their finite-domain endpoints.
- Short HIL: 1,440 seconds, 6,685,424 DMA iterations, device deinitialize/reinitialize every 100,000 iterations, and zero data/device/lifecycle failures. Temperature was 49.103--52.706 C; the final reading was 52.406 C. This was not a multi-model or NPU workload.

## 9. Negative Findings That Must Remain Visible

The CPU fallback observed maximum was 19.926 us against a 10 us registered WCET. The RVV primary observed maximum was 19.778 us against a 4 us registered WCET. Although each path's maximum batch p99 was 1.592 us, a percentile cannot replace a worst-case contract. The current K230 plan therefore cannot support a hard-real-time conclusion.

The maximum batch p99 among the seven control operations was 3.741 us, below 5% of the 100 us plan deadline. However, the preregistered steady-state requirement below 5% of the shortest 4 us segment is 0.2 us and failed. The paper may report the deadline-relative threshold pass but must withdraw the strict “low overhead relative to segment cost” claim.

The original 24-hour run was stopped after 258 seconds because the protocol changed; its 1,200,000 iterations do not enter the 24-minute denominator. A full 24-hour result remains unavailable.

## 10. Defensible Paper Claims

The strongest defensible claim is that AIRTOS makes an evidence-carrying acceleration plan a first-class runtime admission object and maintains finite-domain safety invariants across qualification, memory-time commit, plan-driven ownership transitions, stale-event rejection, and fallback gating.

The paper may claim:

- implementation consistency within the frozen loader, admission, transaction, simulator, allocator, and recovery corpora;
- physical cache/DMA consistency within the single tested K230 configuration and four aligned sizes;
- no observed data/device/lifecycle counterexample during the 24-minute DMA lifecycle run;
- a negative timing audit that detects plan-WCET inapplicability instead of masking it with p99.

The paper may not claim:

- a new RTOS kernel, general AI OS, CPU reservation, or RT-Smart process isolation;
- unconditional or K230 hard-real-time safety for the tested plan;
- general NPU behavior or any NPU performance result;
- naturally late IRQ handling, hard-reset recovery, or bounded physical reset time;
- power efficiency, 24-hour stability, board-to-board variability, or broad workload generalization;
- that finite zero-failure corpora prove absence of future failures.

## 11. Manuscript Narrative

The paper should open with the qualification gap between compiler plans and live heterogeneous state, not with a generic claim that edge AI needs another scheduler. Related work should establish that EDF, heterogeneous DAG runtimes, NPU multi-tenancy, DMA ownership, and runtime assurance already exist. The method should then present AIRTOS as their evidence-governed composition around a consumer-checkable plan.

Evaluation should be organized by claim, not by a list of test programs. The WCET failure is a central result: AIRTOS's governance path can identify that a structurally and numerically valid plan is not timing-valid on the measured board. Discussion must separate implementation consistency, physical coherency, controlled state-machine injection, physical lifecycle calls, and short-duration DMA stress.

Four new figures will later depict architecture, admission/recovery flow, finite-domain validation coverage, and the WCET contract failure. No legacy figure will be used.

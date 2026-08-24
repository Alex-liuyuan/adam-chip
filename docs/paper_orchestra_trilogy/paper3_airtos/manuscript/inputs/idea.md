# AIRTOS: An Evidence-Constrained Runtime for Heterogeneous Edge AI Systems

## Problem Statement

Edge-AI jobs are not single RTOS threads. A compiled inference plan is a segment DAG spanning CPU, vector, accelerator, and DMA resources, with non-preemptive device work, bounded contiguous memory, non-coherent ownership transitions, and completions that may arrive after timeout or device reinitialization. Existing compiler, scheduler, and accelerator-runtime mechanisms address parts of this path, but a plan may still be structurally valid while being unsuitable for the current target, evidence policy, provider state, memory state, arrival model, or recovery budget.

## Core Hypothesis

An RTOS can govern heterogeneous AI plans more safely when admission treats evidence, applicability domain, provider health, memory leases, coherency actions, schedule feasibility, and recoverability as one atomic decision. The claim is conditional and finite-domain: deadline safety requires valid WCET and arrival bounds; physical coherency is asserted only for the tested CanMV-K230-LP4 V3.0 configuration; bounded runs search for counterexamples but do not prove indefinite reliability.

## System Model

A job is \(J_i=(id_i,P_i,r_i,d_i,\kappa_i,\chi_i)\), where \(P_i\) is a compiler-produced plan, \(r_i\) and \(d_i\) are release and absolute deadline, \(\kappa_i\) is the minimum evidence policy, and \(\chi_i\) is the recovery policy. A segment is \(s=(id,res,C,Pred,off,size,flags)\), with resource \(res\in\{CPU,RVV,NPU,DMA\}\), registered execution bound \(C\), predecessor set, lease-relative buffer range, and coherency actions.

The joint predicate is:

\[
Admit(J_i,R_t) \iff Parse\land Bind\land Domain\land Evidence\land Provider\land Memory\land Coherence\land Sched\land Recoverable.
\]

Schedule feasibility is evaluated by a conservative discrete-event simulation \(SimEDF^+\) that uses per-resource, non-preemptive EDF queues, DAG releases, running residuals, coherency and recovery charges, and reservation/demand checks. It rechecks every admitted deadline after inserting the candidate.

## Method

1. Validate package structure and hashes; bind the plan to target, model, shape, dtype, layout, ABI, and required evidence.
2. Check provider health and plan-driven clean, invalidate, barrier, and buffer-range obligations.
3. Probe a non-overlapping arena lease, take a schedule snapshot, run \(SimEDF^+\), then commit lease and job atomically only if both generations remain unchanged; otherwise retry or reject without partial state.
4. Dispatch dependency-ready segments through stable per-resource EDF queues.
5. Associate each dispatch with `(device, epoch, cookie)`; accept completion only when all identifiers match the active command.
6. Consume bounded cancel/reset/reinitialize attempts, quarantine exhausted devices, and re-run the complete admission gate before fallback.
7. Export plan-, run-, epoch-, and segment-attributed trace. Trace can propose a new experiment but cannot elevate evidence or bypass admission.

## Implementation Scope

Production paths are implemented in `engine/rt_ai_templates/runtime/session.c`, `evidence.c`, `aeg_loader.c`, `os/sim_edf.c`, `recovery.c`, `coordinator.c`, `tensor_memory.c`, `coherency.c`, and `trace.c`. Experiments live in `experiments/airtos/`. The physical target is one CanMV-K230-LP4 V3.0 board running RT-Smart. The fixed board workload is an Add+ReLU plan with CPU fallback and RVV primary execution paths; no general NPU evaluation is claimed.

## Contributions

- A single evidence-constrained admission predicate that binds compiler evidence and applicability to live RTOS resource, memory, timing, coherency, and recovery state.
- An optimistic atomic lease-and-schedule transaction that prevents half-admitted jobs under concurrency.
- Runtime governance for heterogeneous segment DAGs through per-resource EDF, explicit ownership transitions, and epoch-cookie stale-event isolation.
- Bounded recovery, quarantine, and fallback re-admission, plus a non-self-certifying trace-to-experiment interface.
- A preregistered finite-domain evaluation spanning host/QEMU consistency and one K230 board, including negative results where measured maxima violate registered WCETs.

## Claim Boundaries

- The evaluation uses one CanMV-K230-LP4 V3.0 board and a fixed Add+ReLU plan.
- No general NPU, power, 24-hour stability, or board-to-board result is available.
- Software-injected stale events are not physical late driver interrupts.
- Device reopen/reinitialization is not a hard reset.
- Observed CPU and RVV maxima exceed the registered plan WCETs; therefore the experiment does not establish a hard-real-time guarantee.
- Zero failures in finite corpora and a 24-minute run mean only that no counterexample was observed in those runs.

## Four-Figure Requirement

All four manuscript figures must be generated anew from this project. Do not copy, trace, or modify the legacy images under `paper3_airtos/figures/`.

1. AIRTOS architecture and evidence flow, derived from the joint predicate and production modules.
2. Atomic admission, dispatch, stale-event rejection, bounded recovery, and fallback re-admission flow.
3. Validation coverage by experimental core with exact tested event/operation counts and zero observed safety failures.
4. K230 timing-contract audit comparing CPU/RVV p99 and maxima with registered WCETs, showing the negative hard-real-time result.

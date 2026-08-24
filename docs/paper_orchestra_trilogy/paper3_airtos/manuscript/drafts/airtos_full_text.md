# AIRTOS: Evidence-Constrained Admission, Resource Governance, and Recovery for Heterogeneous Edge AI

## Abstract

Heterogeneous edge-AI execution spans CPU, vector, accelerator, and DMA resources while sharing bounded memory and non-coherent buffers. A compiler-generated plan can therefore be structurally valid yet inapplicable to the current target, evidence policy, provider state, memory state, arrival model, or recovery budget. This paper presents AIRTOS, an evidence-constrained runtime governance layer that treats a compiler plan as a first-class admission object. AIRTOS evaluates a joint predicate over package parsing, binding, applicability domain, evidence coverage, provider availability, memory, coherency, schedulability, and recoverability. It combines generation-checked arena allocation with conservative multi-resource schedule simulation in one atomic admission transaction, dispatches dependency-ready segments through stable per-resource earliest-deadline-first queues, executes plan-declared cache ownership transitions, rejects stale completions by device epoch and dispatch cookie, and re-applies the complete gate before fallback. We evaluate these mechanisms in four claim-oriented experimental cores and on one CanMV-K230-LP4 V3.0 board running RT-Smart. The frozen corpus produced no observed safety failure in 3,900 admission cases, 400,000 concurrent admission transactions, 24,548 simulator-oracle comparisons, 1,000,000 allocation attempts, 1,000,000 physical DMA transfers, 700,000 stale-event injections, or 7,500 recovery and fallback episodes. All 800 omitted-cache-operation controls were detected. A 24-minute run completed 6,685,424 physical DMA lifecycle iterations without an observed data, device-call, or lifecycle failure. The timing audit also exposed a material contract boundary: measured CPU and RVV maxima of 19.926 and 19.778 us exceeded their registered 10 and 4 us bounds. Thus, AIRTOS supports evidence-governed admission and finite-domain runtime invariants on the tested configuration while correctly withholding a hard-real-time conclusion when the plan's timing evidence is inapplicable.

**Index Terms:** Edge AI, heterogeneous computing, admission control, real-time systems, runtime assurance, DMA coherency, fault recovery.

## 1. Introduction

Edge inference increasingly crosses a qualification boundary that conventional deployment interfaces leave implicit. A compiler emits an execution plan, yet the plan enters a live system whose provider health, contiguous memory, cache ownership, outstanding device commands, and admitted workload can differ from the conditions under which that plan was produced. Moreover, an inference is not necessarily one schedulable thread. It can be a directed acyclic graph (DAG) of CPU, vector, accelerator, and DMA segments with resource-specific execution bounds and asynchronous completions. Structural validity and numerical correctness alone therefore do not establish that a plan is eligible to run in the current state.

The broader toolchain has three responsibilities. Compilation constructs an execution plan for a target chip. Evidence production states the conditions under which that plan is correct and the inputs to which it applies. AIRTOS provides the third stage: runtime governance between the qualified plan and physical execution. In this stage, a plan is not dispatched merely because an inference function exists. It must establish current eligibility with respect to its evidence, invocation, providers, memory, other deadline commitments, coherency actions, and recovery policy. AIRTOS therefore acts as a consumer-side admission boundary rather than another compiler pass or a new general-purpose kernel.

Real-time scheduling theory makes the assumptions behind timing guarantees explicit. Classical earliest-deadline-first (EDF) results and sporadic-task feasibility analysis depend on bounded execution and defined arrival models [@liu1973scheduling; @baruah1990preemptively]; execution-time assurance work further shows that the strength of a timing claim is inseparable from the bounds supplied to the scheduler [@vestal2007preemptive]. Heterogeneous task runtimes and schedulers already express DAG dependencies, locality, and resource types [@topcuoglu2002performanceeffective; @augonnet2011starpu; @bauer2012legion; @rossbach2011ptask; @lin2022typeaware]. Accelerator-sharing systems likewise address preemption, spatial partitioning, memory pressure, and multi-model quality of service [@choi2020prema; @ghodrati2020planaria; @kim2023moca; @kim2023dream]. These mechanisms provide essential foundations, but they normally begin after the workload and its execution bounds have been accepted as valid inputs.

This paper presents AIRTOS, an evidence-constrained runtime governance layer for heterogeneous edge-AI plans. AIRTOS treats a compiler plan as a first-class admission object and evaluates a joint predicate over parsing, binding, applicability domain, evidence coverage, provider availability, memory, coherency, schedulability, and recoverability. Admission probes an arena lease, captures the current schedule, evaluates a conservative multi-resource simulation, and commits memory and job state only if their generations remain unchanged. During execution, dependency-ready segments enter stable per-resource EDF queues. Plan-declared ownership transitions govern cache and DMA operations, while a device epoch and dispatch cookie scope completion events. Recovery consumes a bounded policy, quarantines an exhausted resource, and subjects a fallback to the same evidence, provider, lease, and schedule checks before execution.

The design follows the separation principle used in runtime assurance: a complex producer may propose an action, but a smaller consumer-side mechanism decides whether that action is admissible in the present state [@seto1998simplex; @hobbs2023runtime]. Runtime observations are similarly restricted. Trace records can select a subsequent compiler experiment, but they cannot elevate evidence or install a new plan directly; every candidate must return through verification and admission. This preserves the distinction between observing an execution and establishing a reusable claim, consistent with runtime-verification practice [@leucker2009brief].

We evaluate AIRTOS through four claim-oriented cores and a short physical hardware-in-the-loop (HIL) run. The frozen corpus covers package and admission decisions, concurrent memory-schedule transactions, independent scheduling-oracle comparisons, arena leases, physical DMA transfers with negative coherency controls, stale-event and recovery state transitions, fallback gates, and trace classification. On one CanMV-K230-LP4 V3.0 board, one million physical transfers produced no byte mismatch, and omission controls detected all 800 intentionally missing ownership operations. The timing audit is equally important: CPU and RVV maximum observations exceeded their registered 10 and 4 us execution bounds, respectively. AIRTOS therefore identifies the tested plan as outside its timing contract rather than converting favorable percentiles into an unsupported hard-real-time claim.

This work makes four contributions:

1. It defines evidence-constrained admission that combines plan qualification with live resource, memory, coherency, scheduling, and recovery state.
2. It implements an optimistic atomic lease-and-schedule transaction that prevents half-admitted jobs under concurrent submissions.
3. It unifies dependency-aware resource governance, explicit ownership transitions, and epoch-scoped completion and recovery semantics.
4. It provides a preregistered, finite-domain evaluation that reports both invariant checks and a negative timing-contract result.

The contribution is this governed composition and its consumer-checkable boundaries. EDF, heterogeneous DAG execution, accelerator sharing, DMA ownership, and timeout handling remain established mechanisms.

## 2. Background and Related Work

### 2.1 Real-Time and Heterogeneous DAG Scheduling

Liu and Layland establish the classical uniprocessor foundation for EDF under periodic-task assumptions [@liu1973scheduling], while processor-demand analysis extends feasibility reasoning to sporadic workloads [@baruah1990preemptively]. Vestal makes execution-time assurance an explicit scheduling dimension [@vestal2007preemptive]. AIRTOS retains this discipline: its deadline statement is conditional on registered segment costs, non-preemptive blocking, modeled arrivals, coherency charges, and recovery charges. Its simulator rechecks the deadlines of all admitted jobs after a candidate insertion instead of treating EDF priority as a timing proof.

HEFT schedules precedence-constrained tasks across heterogeneous processors using rank-based list scheduling [@topcuoglu2002performanceeffective]. StarPU combines task scheduling with heterogeneous data management [@augonnet2011starpu]; Legion expresses independence and locality through logical regions [@bauer2012legion]; and PTask makes accelerator work and dataflow visible to the operating system [@rossbach2011ptask]. Type-aware federated scheduling gives real-time semantics to typed heterogeneous DAGs [@lin2022typeaware]. AIRTOS does not present DAG queues or per-resource EDF as new scheduling algorithms. It places these mechanisms downstream of an evidence and applicability gate and couples their admission result to a generation-checked memory transaction and recovery state.

### 2.2 Accelerator Runtimes and Multi-Tenant AI

Accelerator sharing spans different hardware assumptions. PREMA exploits preemptible NPU execution [@choi2020prema], whereas Planaria partitions an accelerator spatially among tenants [@ghodrati2020planaria]. MoCA adapts execution around multi-tenant memory behavior [@kim2023moca], and DREAM targets dynamic real-time multi-model edge workloads [@kim2023dream]. Salus exposes fine-grained GPU sharing primitives and distinguishes persistent from transient memory [@yu2019salus]; Clockwork pursues predictable DNN serving through controlled execution and explicit timing information [@gujarati2020serving]. These systems establish that scheduling, memory, and latency must be governed jointly, but their admitted unit is generally a model or execution request rather than a plan carrying separately checkable domain and evidence obligations. AIRTOS addresses that qualification boundary and does not compare throughput across incompatible accelerator capabilities.

Embedded inference systems demonstrate how tightly runtime design is coupled to constrained memory and platform support. TensorFlow Lite Micro provides an embedded inference runtime for small devices [@david2021tensorflow], and MLPerf Tiny establishes reproducible measurement practices for such platforms [@banbury2021mlperf]. AIRTOS focuses on a different layer: deciding whether a particular evidence-carrying heterogeneous plan may enter the live runtime, then maintaining its memory, timing, ownership, and recovery obligations.

### 2.3 Runtime Assurance, Coherency, and Recovery

Simplex separates a high-performance controller from a trusted baseline and decision module [@seto1998simplex]; modern runtime-assurance work generalizes that structure as a safety filter around complex components [@hobbs2023runtime]. Runtime verification studies how execution events are checked against specified properties [@leucker2009brief]. AIRTOS applies the same separation at the compiler-runtime boundary: a producer supplies a plan and evidence, while the runtime independently checks eligibility against current state. Its trace is observational and can only propose a new experiment, preventing an execution from certifying its own replacement.

DMA synchronization specifications already define fences and ownership transitions for asynchronous devices [@documentation2026buffer; @documentation2026dma]. AIRTOS does not redefine those primitives. Instead, the plan names the buffer range and required clean, barrier, and invalidate actions; the runtime checks that the range lies within the active lease and invokes provider hooks at the ownership boundary. Completion attribution then adds an orthogonal device-generation rule: an event is accepted only when resource, epoch, active command, and cookie agree. This prevents an event associated with an earlier device generation from completing a newly active segment.

Finally, the evaluation uses an independent scheduling oracle rather than deriving expected answers from the runtime under test, following the broader testing principle that oracle construction is part of the validity argument [@barr2015oracle]. Together, these lines of work motivate AIRTOS as a governance layer that composes established scheduling, task-runtime, assurance, and DMA mechanisms around one consumer-checkable plan contract.

## 3. System Model and Problem Formulation

### 3.1 Jobs, Plans, and Runtime State

An admitted job is

\[
J_i=(id_i,P_i,r_i,d_i,\kappa_i,\chi_i),
\]

where \(P_i\) is the compiler-produced plan, \(r_i\) is release time, \(d_i\) is an absolute deadline, \(\kappa_i\) is the minimum evidence policy, and \(\chi_i\) is a recovery policy. A plan contains a segment DAG \(G_i=(V_i,E_i)\). Each segment is

\[
s=(id,res,C,Pred,off,size,flags),
\]

where \(res\in\{CPU,RVV,NPU,DMA\}\), \(C\) is a registered execution bound including the costs used by admission, \(Pred\) is the predecessor set, \(off\) and \(size\) identify a lease-relative buffer range, and \(flags\) declare ownership actions. A segment becomes ready only after job release and completion of every predecessor:

\[
Ready(s,t)\iff t\ge r_i\land\forall u\in Pred(s), state(u)=done.
\]

The runtime state is

\[
R_t=(\{Q_r\},\{A_r\},\mathcal L,\mathcal C,
\{epoch_r\},\{cookie_r\},D_t,Z_t),
\]

where \(Q_r\) and \(A_r\) are the ready queue and active segment for resource \(r\), \(\mathcal L\) is the set of active arena leases, \(\mathcal C\) is the ownership state of plan buffers, \(D_t\) records provider health and recovery state, and \(Z_t\) is the attributable trace. Each resource queue is ordered by the owning job's absolute deadline, with stable FIFO order for equal deadlines. Running device segments are non-preemptive in the current model.

### 3.2 Evidence-Constrained Admission

AIRTOS admits a candidate only when nine conditions hold jointly:

\[
\begin{aligned}
Admit(J_i,R_t)\iff{}&Parse\land Bind\land Domain\land Evidence\\
&\land Provider\land Memory\land Coherence\\
&\land Sched\land Recoverable.
\end{aligned}
\]

`Parse` covers package structure and safe decoding. `Bind` links package, plan, model, target, runtime ABI, provider ABI, and fallback identities. `Domain` covers input shape, dtype, layout, and byte ranges. `Evidence` requires every obligation selected by policy \(\kappa_i\) to have the expected scope, artifact, verifier identity, resource binding, and verified status. `Provider` requires the resources named by the selected plan to be registered and healthy. `Memory` requires a non-overlapping arena lease containing every declared range. `Coherence` requires supported ownership actions for every cross-domain transition. `Sched` requires the candidate and every previously admitted job to meet their deadlines in conservative simulation. `Recoverable` requires a valid recovery policy and a provider state that is neither pending recovery nor quarantined.

The scheduling term is evaluated by \(SimEDF^+\), a discrete-event simulation with per-resource non-preemptive EDF, DAG releases, the residual of any running segment, coherency and recovery charges, and reservation demand. For a running segment with start time \(t_s\), the simulation uses a residual bounded by

\[
C_s^{rem}=\max(0,C_s-(t-t_s))+O_s^{coh}+O_s^{rec}.
\]

The candidate passes only if every simulated completion satisfies

\[
Sched(J_i,R_t)\iff
\forall J_j\in\mathcal J_{admitted}\cup\{J_i\},
\widehat F_j\le d_j,
\]

and the reservation demand at each checked horizon does not exceed resource supply. This all-job check is necessary because an earlier-deadline candidate can be feasible for itself while delaying a previously admitted job beyond its deadline.

### 3.3 Safety Properties and Conditional Timing

The design maintains several properties, each with explicit assumptions.

**Lease isolation.** Let an active lease be \(l_i=(base_i,size_i,owner_i)\). If the allocator maintains pairwise non-overlap, the loader confines every segment range to its plan arena, and providers access only declared ranges, then no segment of one session can address another session's lease:

\[
i\ne j\Rightarrow
[base_i,base_i+size_i)\cap[base_j,base_j+size_j)=\varnothing.
\]

This statement concerns inter-session isolation; within-session alias validity remains part of the compiler plan.

**DAG order.** If a segment enters a resource queue only when all predecessors are complete and only queued segments can be dispatched, every dispatch sequence is a topological extension of the plan DAG. Per-resource EDF determines order among ready segments but does not bypass dependencies.

**Epoch isolation.** A completion event carries \((r,e,c,status)\), while the runtime records the current epoch, active job, active segment, and cookie for resource \(r\). The event is accepted only if

\[
Accept(irq,R_t)\iff e=epoch_r\land c=cookie_r
\land A_r\ne\varnothing.
\]

A reset advances the epoch. An event from an earlier epoch therefore cannot mutate a command in the new generation. After a valid completion, active state and cookie association are cleared, so a duplicate event in the same epoch is also rejected. Cookie wrap advances the epoch before reuse.

**Conditional data consistency.** For a non-coherent buffer, AIRTOS models ownership transitions

\[
CPU_{dirty}\xrightarrow{clean+barrier}Device
\xrightarrow{complete+invalidate}CPU_{valid}.
\]

If the plan declares the correct range and actions, provider hooks implement them for the target cache and DMA engine, and the device obeys its completion semantics, device reads observe submitted CPU data and post-completion CPU reads observe device output.

**Conditional deadline safety.** Let a segment dispatch at \(a_s\), complete in hardware at \(h_s\), and have registered budget \(C_s\). AIRTOS exposes logical completion at

\[
\ell_s=\max(h_s,a_s+C_s).
\]

Holding early completion to the modeled boundary keeps successor releases and non-preemptive resource occupancy aligned with \(SimEDF^+\). If actual execution and charged overhead do not exceed their registered bounds, arrivals and faults remain inside the modeled reservation, every job passes atomic admission, and runtime tie-breaking matches simulation, the simulated and logical runtime schedules coincide by induction over discrete events. Therefore, a passing all-job schedule check preserves the deadline invariant. If an observed execution exceeds its registered bound, the plan has left this timing domain and must be requalified.

## 4. AIRTOS Design

### 4.1 Evidence Flow and Runtime Governance

AIRTOS consumes an AEG v2 package containing plan identity, evidence identity, policy and target bindings, input domain, segment DAG, execution costs, arena size, ownership actions, reservation parameters, fallback identity, and recovery budget. Session creation validates package structure before accessing payload objects, compares the package against a consumer-side trust bundle, and checks each evidence obligation independently. Submission then adds invocation-specific checks and the current state of providers, memory, admitted work, and recovery.

**[Figure 1 near here: AIRTOS architecture and evidence flow. The new figure will show the evidence-carrying plan crossing structural, binding, domain, evidence, provider, memory, coherency, schedule, and recovery gates before resource governance, with attributed trace returning only a candidate experiment.]**

This structure makes the compiler-runtime boundary explicit. The producer supplies claims and supporting identities; the consumer determines whether they apply to the current invocation and machine state. No single successful check substitutes for another. A healthy provider cannot compensate for an invalid evidence binding, and a feasible schedule cannot compensate for an unavailable arena or unsupported ownership transition.

### 4.2 Atomic Lease and Schedule Admission

Memory and time are admitted as one optimistic transaction. Under the runtime lock, submission selects a free job slot, probes a first-fit arena interval, captures the lease generation, snapshots admitted work, and captures the schedule generation. It releases the lock while \(SimEDF^+\) evaluates the candidate. On reacquiring the lock, it verifies that the slot and session remain available, provider health is still valid, and both generations still match. Only then does it commit the lease, initialize the job, publish the slot, and advance schedule state.

If simulation rejects the candidate, no lease is committed. If either generation changes, submission retries against a fresh snapshot. If provider health changes at the final check, a committed lease is released before rejection. No fallible operation remains between successful arena commit and job publication. The linearization point is therefore the locked publication of both lease-backed job state and the schedule generation.

The transaction protects against two distinct time-of-check/time-of-use races. A concurrent allocation can invalidate a previously probed interval, and a concurrent admission or completion can invalidate the schedule snapshot. The lease generation detects the first, and the schedule generation detects the second. Joint validation avoids exposing a state in which memory is reserved without an admitted job or a job is visible without its lease.

### 4.3 Resource and Coherency Governance

Each resource owns a stable EDF queue. A segment enters that queue only when all predecessors are done. When the resource is idle, AIRTOS dispatches the queue head, assigns a cookie, records the current epoch, performs pre-submit ownership actions, and invokes the registered provider. Independent segments on different resources may progress concurrently, while each resource's active segment remains non-preemptive.

Arena leases define session-level physical isolation. Segment offsets are interpreted relative to the active lease, and coherency operations are rejected if their rounded cache-line range would escape that lease. Before a device submission, AIRTOS optionally cleans the declared range and issues a barrier. After accepted completion, it issues a barrier, optionally invalidates the declared range, and issues a final barrier. The plan controls which transitions are required; the provider implements the platform-specific operation.

This arrangement improves auditability. Ownership intent is visible in the plan, range enforcement is visible in the runtime, and hardware behavior is tested at the provider boundary. It also separates mechanism from evidence: the same state machine can be replayed on host or QEMU, but physical data-consistency support requires a target on which omission controls produce observable stale data.

### 4.4 Epoch-Scoped Recovery and Fallback

A timeout first initiates cancellation. If cancellation does not confirm quiescence within its budget, recovery advances the device epoch and begins reset, followed by reinitialization and a health check. Reset and reinitialization attempts are bounded by the package policy. Exhausting the configured count moves the resource to `Quarantined`, which excludes it from subsequent provider admission.

For cancellation budget \(\Delta_c\), reset budget \(\Delta_r\), reinitialization budget \(\Delta_i\), and at most \(K_r\) attempts, model-level closure is bounded by

\[
T_{close}\le \Delta_c+K_r(\Delta_r+\Delta_i)+O(K_r).
\]

The failed job retains its lease while recovery remains open. Fallback is not an unconditional branch: AIRTOS re-evaluates session trust and evidence, confirms that the original lease is active and contains every fallback range, checks fallback-provider health, snapshots the current schedule, and calls \(SimEDF^+\) with the original absolute deadline. Only a passing fallback is installed and returned to pending execution.

**[Figure 2 near here: Atomic admission and recovery flow. The new figure will show generation-checked lease/schedule commit, dependency-ready dispatch, epoch-cookie completion acceptance, bounded cancel/reset/reinitialize transitions, quarantine, and full fallback re-admission.]**

### 4.5 Attributable, Non-Self-Certifying Trace

Trace entries include logical sequence, monotonic timestamp, run identifier, plan identity, job and segment, resource, epoch, cookie, event, status, and queue depth. Chronological export remains stable across ring wrap and reports dropped records. A classifier maps attributed symptoms such as queue contention, DMA delay, kernel delay, arena pressure, WCET mismatch, reset activity, and coherency faults to a candidate next experiment.

The output is advisory by construction. A trace cannot modify the loaded plan, change a verified flag, or elevate an evidence policy. A new candidate receives a new identity and must pass compiler-side verification and the complete AIRTOS admission predicate. The feedback path can therefore improve experimental selection without creating a circular proof in which the observation used to propose a change also certifies the changed artifact.

## 5. Implementation

### 5.1 Production Runtime Paths

The implementation is a portable C governance layer integrated with RT-Smart rather than a replacement kernel. The production path separates package parsing, evidence evaluation, session and submission management, schedule simulation, coordination, memory leasing, coherency, recovery, and tracing.

The loader validates section bounds, counts, dependencies, resource identifiers, hashes, numerical ranges, recovery policy, and plan/fallback structure before constructing a session object. Evidence evaluation compares plan, policy, model, target, runtime-ABI, and provider-ABI identities and iterates over obligation records, including artifact and verifier identities and allowlisting. Session creation caches the validated plan and trust decision.

Submission performs domain, interarrival, deadline, provider, lease, and schedule checks. The admission simulator reconstructs admitted jobs and the candidate in an independent simulation state, including active residuals and reservations. Runtime queues maintain dependency-ready order, while the coordinator is entered through a polling interface and serializes state transitions through the platform lock. Completion entry points apply the epoch-cookie predicate before post-device ownership actions and successor release.

The arena allocator uses generation-checked first fit over a fixed runtime arena. Recovery records per-resource states for cancel, reset, reinitialization, health, attempt count, and quarantine. The trace ring assigns monotonically increasing logical sequence numbers and exports event-level plan identity, including fallback identity after an accepted transition.

### 5.2 K230 Integration and Tested Plan

The physical evaluation uses one CanMV-K230-LP4 V3.0 board running RT-Smart. The fixed plan performs float32 Add+ReLU on shape `[1,8]` in a 64-byte arena, with a 100 us relative deadline and 100 us minimum interarrival time. The primary RVV segment registers a 4 us execution bound, 1 us coherency charge, and 50 us recovery charge. The CPU fallback registers 10, 1, and 50 us for the corresponding fields.

Physical ownership tests allocate cached MMZ buffers, obtain physical addresses, execute writeback and invalidation through the platform cache interface, and move data through GSDMA. The complete path is CPU pattern generation, source writeback, physical copy, destination invalidation, and byte comparison. The device lifecycle test deinitializes and reinitializes GSDMA and verifies a subsequent copy.

The implementation and evaluation concern CPU, RVV, and DMA paths used by this fixed workload. The AEG resource model includes an NPU identifier so plans can express one when a supported provider and evidence are present, but the reported physical experiment does not include a general NPU workload or NPU performance result.

## 6. Experimental Methodology

### 6.1 Preregistered Questions and Decision Rules

The evaluation is organized by claims rather than by executable names.

**Core 1 asks whether qualification and admission fail closed.** It exercises package structure, binding, input domain, evidence, providers, memory, coherency, scheduling, recovery state, provider-health races, trust-root rotation, and concurrent admission. Unsafe admission, active lease overlap, partial commit, or failure to roll back is a zero-tolerance endpoint.

**Core 2 asks whether schedule decisions match an independent oracle and whether the registered timing contract applies on the board.** The oracle does not call the production scheduler, queue, or lease code. It compares accept/reject status and predicted finish times for frozen DAG scenarios. Board timing reports percentiles and maxima separately; a percentile does not replace a registered worst-case bound.

**Core 3 asks whether lease and ownership invariants hold.** Allocation is checked against independent ownership state. Physical DMA output is compared byte for byte. Omitted-clean and omitted-invalidate controls must be observable; otherwise a passing complete path would not establish that the tested hardware path is sensitive to the ownership operations.

**Core 4 asks whether old-world events are isolated and recovery terminates at a governed state.** Stale and duplicate classes, bounded recovery, quarantine, fallback re-admission, trace classification, physical device lifecycle, and short-duration continuous operation are evaluated separately. State-safety endpoints have zero tolerance. Classification thresholds are macro-F1 at least 0.90, top-3 recall at least 0.95, and no verifier/admission bypass.

### 6.2 Platform and Measurement Discipline

The frozen protocol is `airtos-exp-v6`, executed on 2026-08-05. The loader and scheduling corpus is 49,085,520 bytes. Physical transfer sizes are 64, 256, 4,096, and 65,536 bytes, each receiving 250,000 complete-path transfers. The continuous run lasts 1,440 s and cycles the same four transfer sizes. It deinitializes and reinitializes the device every 100,000 iterations.

Safety counts are reported exactly, without combining distinct operation types into a common estimator. Schedule agreement concerns frozen simulator scenarios, not physical execution of 24,548 heterogeneous workloads. Stale-event and recovery cases execute production state-machine code on the board through controlled in-process callbacks; they are distinct from naturally late driver interrupts. Device reopen/reinitialize calls the physical library but is distinct from a chip hard reset.

Timing is audited against the values already registered in the plan. CPU and RVV paths each execute 30,000 numerical checks. The control-path criterion is a batch p99 below 5 us, corresponding to 5% of the 100 us plan deadline. A stricter criterion asks for steady-state control overhead below 5% of the shortest 4 us segment, or 0.2 us. Both criteria are reported.

The recomputed experimental summary is bound by SHA-256 `1a4ba42374048e5c2a9595ab14182672b621b4ea3e812ddcccc5321bb447656c`. Final HIL status is taken from the completed serial log and recomputed summary.

**[Figure 3 near here: Finite-domain validation coverage. The new figure will plot the four non-overlapping aggregate operation counts, annotate zero observed safety failures, and explicitly state that the bars are coverage counts rather than samples from one estimator.]**

## 7. Evaluation

### 7.1 Admission and Scheduling Consistency

Table 1 summarizes Core 1. The admission matrix completed 3,900 cases without an observed decision failure. Diagnostic classification completed 23,400 cases with macro-F1 1.0. Provider-health races and trust-root rotation added 300 and 1,500 decisions, respectively, without an unsafe commit or decision failure. Across 400,000 concurrent transactions, 112,091 were accepted and 287,909 rejected. The acceptance ratio is descriptive of a validation corpus, not a workload-capacity result. No active lease overlap or partial commit was observed.

**Table 1. Evidence-constrained and atomic admission.**

| Endpoint | Cases/operations | Observed failures | Result |
|---|---:|---:|---|
| Admission matrix | 3,900 | 0 | Joint predicate decisions |
| Diagnostic classification | 23,400 | 0 | Macro-F1 = 1.0 |
| Provider-health race | 300 | 0 | No unsafe commit |
| Trust-root rotation | 1,500 | 0 | No decision failure |
| Concurrent transactions | 400,000 | 0 | 112,091 accepted; 287,909 rejected |
| Active lease overlap | 400,000 transactions | 0 | No overlap observed |
| Partial commit | 400,000 transactions | 0 | No half-admitted job observed |

Core 2 executed 7,950 loader cases and 24,548 schedule-oracle comparisons. Production loader decisions matched frozen expectations, and simulator status and finish time matched the independent oracle in every compared scenario. These results support implementation consistency across the generated DAG, running-residual, recovery-charge, and reservation cases represented in the corpus. They do not depend on the physical timing values of the tested Add+ReLU plan.

The software-model ablation on 10,000 small scenarios demonstrates why admission must include all old and new jobs. With no admission test, 5,822 scenarios were falsely accepted. Checking only whether the candidate itself finished by its deadline still produced 3,932 false accepts because the candidate could delay an earlier commitment. FIFO and fixed-priority admission reduced false accepts to 27 and 29 but also introduced 355 and 380 false rejects. Complete all-job `SimEDF+` produced zero false accept and zero false reject against the independent oracle in this corpus.

**Table 1a. Software-model admission ablation over 10,000 small scenarios.**

| Admission condition | False accepts | False rejects |
|---|---:|---:|
| No admission check | 5,822 | 0 |
| Candidate-only finish check | 3,932 | 0 |
| FIFO baseline | 27 | 355 |
| Fixed-priority baseline | 29 | 380 |
| Complete all-job `SimEDF+` | 0 | 0 |

A separate sensitivity experiment held the admitted scenario set fixed at 4,178 cases per ratio. At actual/WCET ratios 0.50, 0.80, and 1.00, no deadline miss was observed. At ratios 1.05 and 1.20, the counts rose to 446 and 1,145. This controlled transition supports the role of the registered execution bound as a premise of admission rather than a descriptive performance target.

CPU and RVV Add+ReLU paths each completed 30,000 calls with zero numerical failure. This confirms numerical behavior for the fixed shape and operator in the tested environment. Timing applicability is evaluated separately in Section 7.4.

### 7.2 Memory Isolation and Physical Coherency

The allocator completed 1,000,000 attempts, of which 948,950 produced successful leases. The independent checks observed no overlap, corruption, generation error, or rollback failure counted by the frozen endpoint. Allocation failure under pressure is an availability outcome and is not counted as a safety failure.

The K230 physical path completed 1,000,000 DMA transfers with zero byte mismatch. Each of the four sizes contributed 250,000 transfers. Mean complete-path time increased from 29.949 us for 64 bytes to 713.355 us for 65,536 bytes, as shown in Table 2.

**Table 2. Physical K230 DMA and cache path.**

| Transfer size | Cases | Mean complete-path time |
|---:|---:|---:|
| 64 B | 250,000 | 29.949 us |
| 256 B | 250,000 | 34.490 us |
| 4,096 B | 250,000 | 86.502 us |
| 65,536 B | 250,000 | 713.355 us |

The negative controls establish sensitivity of this platform contract. Omitting source clean was detected in 400 of 400 controls, and omitting destination invalidate was detected in 400 of 400 controls. Thus, the complete-path result is not explained by an environment in which the tested ownership operations are observationally irrelevant. The evidence supports the aligned buffers, four sizes, cache interface, and GSDMA engine used on this K230 configuration.

### 7.3 Recovery, Feedback, and Short-Duration HIL

Seven stale-event classes contributed 700,000 controlled events. None was observed to mutate state through an invalid completion. Recovery completed 1,500 base episodes, while 4,800 recovery-budget episodes checked attempt accounting, closure, and quarantine. Another 1,200 fallback episodes exercised trust, evidence, active-lease, provider-health, and schedule gates; no re-admission bypass was observed.

The trace classifier completed 800 base cases with macro-F1 1.0 and top-3 recall 1.0. A robust corpus added 2,400 noise and ring-wrap cases and retained macro-F1 1.0 with no frozen-endpoint failure. These values establish behavior on the eight labeled synthetic classes used by the protocol and confirm that ring chronology and irrelevant events do not change the recorded decision in that domain.

Physical GSDMA reopen/reinitialize completed 300 episodes with zero lifecycle failure. The observed p99 was 53.148 us and the maximum was 69.222 us. This operation demonstrates that AIRTOS can close and re-establish the tested device-library lifecycle before a verification copy; it is not reported as a chip hard-reset latency.

The short HIL run completed 6,685,424 DMA lifecycle iterations in 1,440 s. Each iteration generated a deterministic pattern, selected one of four sizes, wrote back the source, invoked physical GSDMA, invalidated the destination, and compared bytes. Device deinitialization and reinitialization occurred every 100,000 iterations. The run recorded `data_failures=0`, `device_failures=0`, and `lifecycle_failures=0`, with terminal token `AIRTOS_K230_LONG_PASS`. Temperature ranged from 49.103 to 52.706 C, with a final reading of 52.406 C. These are physical DMA lifecycle iterations, not NPU executions or heterogeneous inference jobs.

**Table 3. Recovery, trace, and short physical run.**

| Endpoint | Cases/episodes | Observed failure/bypass | Additional result |
|---|---:|---:|---|
| Seven stale-event classes | 700,000 | 0 | No stale state mutation observed |
| Recovery episodes | 1,500 | 0 | State-machine checks |
| Recovery-budget episodes | 4,800 | 0 | Budget/quarantine closure |
| Fallback gate episodes | 1,200 | 0 | No re-admission bypass |
| Base trace classification | 800 | 0 | Macro-F1/top-3 = 1.0/1.0 |
| Robust trace classification | 2,400 | 0 | Macro-F1 = 1.0 under noise/wrap |
| Device reopen/reinitialize | 300 | 0 | p99/max = 53.148/69.222 us |
| Continuous HIL | 6,685,424 iterations | 0 | 1,440 s; final 52.406 C |

### 7.4 Timing Contract Audit

Figure 4 and Table 4 separate percentile behavior from contract validity. Both execution paths had a maximum batch p99 of 1.592 us. The RVV maximum, however, was 19.778 us against a registered 4 us bound, and the CPU maximum was 19.926 us against a registered 10 us bound. Both timing contracts therefore fail on maximum observation. This is the intended consequence of evidence-constrained governance: a plan can remain structurally valid and numerically correct while its timing evidence is rejected for the measured platform state.

**[Figure 4 near here: K230 WCET contract audit. The new figure will compare registered WCET, batch p99, and observed maximum for CPU fallback and RVV primary, making both maximum-based failures explicit.]**

**Table 4. Execution and control-path timing audit.**

| Path | Registered criterion | Batch p99 | Observed maximum | Outcome |
|---|---:|---:|---:|---|
| RVV Add+ReLU | WCET 4 us | 1.592 us | 19.778 us | Contract failed |
| CPU Add+ReLU | WCET 10 us | 1.592 us | 19.926 us | Contract failed |
| Clock read | p99 < 5 us | 1.518 us | 12.111 us | p99 criterion passed |
| ISR completion | p99 < 5 us | 3.445 us | 39.074 us | p99 criterion passed |
| Lease release | p99 < 5 us | 1.667 us | 2.629 us | p99 criterion passed |
| Plan load | p99 < 5 us | 3.741 us | 36.963 us | p99 criterion passed |
| Queue push/pop | p99 < 5 us | 1.555 us | 37.037 us | p99 criterion passed |
| SimEDF admission | p99 < 5 us | 2.223 us | 37.037 us | p99 criterion passed |
| Trace emission | p99 < 5 us | 1.704 us | 35.777 us | p99 criterion passed |

The maximum batch p99 among seven control operations was 3.741 us, so the preregistered deadline-relative 5 us criterion passed. The stricter 0.2 us criterion, equal to 5% of the shortest 4 us segment, did not pass. AIRTOS is therefore shown to fit the deadline-relative control budget used by the protocol, but the current implementation and plan combination does not support a claim of negligible overhead relative to its shortest segment.

The timing result does not contradict the conditional scheduling argument. The 24,548 oracle comparisons establish that the implementation evaluates its declared model consistently. Board measurement establishes that the declared 4 and 10 us bounds are not valid for the observed physical execution domain. Recalibration and generation of a new evidence-carrying plan are consequently required before a board-level deadline claim can be evaluated.

### 7.5 Aggregate Coverage

For visualization only, the protocol aggregates non-overlapping primary operations into four coverage counts: 429,100 for admission and transactions, 92,498 for loading, scheduling, and numerical runs, 2,000,800 for allocation, physical DMA, and omission controls, and 7,396,424 for stale events, recovery, fallback, trace, lifecycle, and short HIL. Each aggregate recorded zero observed safety failures under its defined endpoint. These totals do not share a common sampling distribution and are not combined into a single failure-rate estimate.

## 8. Discussion

### 8.1 What the Evidence Establishes

The combined results support three conclusions about the tested artifact. First, qualification is operational rather than documentary: package, evidence, domain, provider, memory, schedule, coherency, and recovery checks all participate in the decision that precedes dispatch. The concurrent transaction corpus supports the intended linearization of memory and schedule state within the tested interleavings.

Second, runtime ownership is explicit across both memory and device generations. Arena ranges are attached to sessions, cache transitions are attached to plan segments, and completions are attached to an epoch and cookie. The physical DMA result and omission controls connect the abstract ownership state to observable data behavior on the tested K230 configuration. The controlled stale-event corpus connects generation matching to the production recovery state machine.

Third, evidence remains capable of rejecting an otherwise functioning plan. The Add+ReLU paths were numerically correct in 60,000 measured calls, and their batch p99 values were favorable, yet their maxima exceeded the registered bounds. Withholding a deadline claim is not an incidental reporting choice; it demonstrates the distinction between functional success and timing applicability that motivates the joint predicate.

The trace interface preserves the same discipline. Classification results show that attributed events can select the intended experiment in the frozen labeled domain. Requiring a new plan identity, new evidence, and fresh admission prevents this feedback from becoming an implicit online certification channel.

### 8.2 Evidence Scope and Generalization

The physical scope is one CanMV-K230-LP4 V3.0 board, RT-Smart, a fixed float32 Add+ReLU plan, CPU and RVV execution, and GSDMA transfers over four aligned sizes. The physical coherency conclusion applies to that buffer, cache-interface, engine, and size contract. The reported corpus does not supply a general NPU performance result, board-to-board variability, or power data.

The controlled stale-event cases exercise production state-machine code but are distinct from naturally delayed interrupts emitted by a production driver. Likewise, device reopen/reinitialize is a physical library lifecycle operation rather than a hard reset. These distinctions preserve a clear correspondence between mechanism, stimulus, and supported statement.

The continuous run provides 24 minutes of short-duration evidence and 6,685,424 verified DMA lifecycle iterations. It establishes that no recorded data, device-call, or lifecycle counterexample occurred during that finite run. It is not used as a substitute for a 24-hour study.

The scheduling theorem remains conditional on registered execution, arrival, blocking, coherency, and recovery bounds. The negative WCET audit identifies exactly which premise does not apply to the current plan. A new plan with recalibrated bounds can pass through the same consumer-side machinery without changing the admission semantics.

## 9. Conclusion

AIRTOS treats an evidence-carrying heterogeneous execution plan as a first-class runtime object. Its joint predicate binds compiler evidence and applicability to live provider, memory, coherency, schedule, and recovery state. Generation-checked lease and schedule commit prevents half-admission, dependency-ready resource queues govern execution, plan-declared ownership actions connect buffers to physical DMA, and epoch-cookie matching separates current commands from stale completions. Bounded recovery ends in restored health or quarantine, while fallback and trace-generated candidates return through the complete gate.

Across the frozen corpus and one K230 board, these mechanisms produced no observed safety failure at the registered endpoints, including one million physical DMA transfers and 6.7 million short-run lifecycle iterations. At the same time, the measured maxima invalidated both registered execution bounds. This result illustrates the central role of evidence-constrained governance: the runtime does not infer eligibility from structural validity, numerical success, or favorable percentiles. It admits, rejects, recovers, and traces plans according to explicit, consumer-checkable conditions.

## References

The submission bibliography is maintained in `refs.bib` and contains the 22 project-verified sources cited above.

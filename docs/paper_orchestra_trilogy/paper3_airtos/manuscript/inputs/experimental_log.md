# AIRTOS Frozen Experimental Log

## 1. Experimental Setup

- Non-HIL protocol: `airtos-exp-v5`, executed twice from clean directories on
  2026-08-04 with recursive checksum verification.
- Physical protocol: `airtos-exp-v6`, executed 2026-08-05.
- Software and virtual platforms: x86_64 Linux, RV64GC QEMU user mode,
  RV64 QEMU `virt` with OpenSBI and RT-Thread Nano 5.3.0, and QEMU system
  machines `lm3s6965evb`, `mps2-an385`, `mps2-an386`, and `mps2-an500`.
- Physical platform: one CanMV-K230-LP4 V3.0 board running RT-Smart.
- Workload: fixed Add+ReLU plan; 100 us plan deadline; 4 us RVV primary WCET; 10 us CPU fallback WCET.
- Software paths: the production loader, evidence gate, coordinator, EDF simulator, lease allocator, coherency engine, recovery path, and trace exporter.
- Corpus: 49,085,520 bytes for loader/scheduling replay; physical DMA measurements use 64, 256, 4,096, and 65,536 byte transfers.
- Decision discipline: safety failures have zero tolerance. Timing claims are conditional on registered bounds. The final HIL truth is taken from the completed raw serial log and recomputed summary, not the stale in-progress prose in the initial v6 report.
- Final recomputed summary SHA-256: `1a4ba42374048e5c2a9595ab14182672b621b4ea3e812ddcccc5321bb447656c`.

## 2. Raw Numeric Data

### Cross-Architecture Software and Virtual-Platform Replay

The same frozen corpus was replayed in two independent runs. These repeated
executions test implementation consistency and portability; they are not
pooled as independent statistical samples.

| Environment | ISA / software layer | Primary workload per run | Two-run outcome |
|---|---|---|---|
| Native host | x86_64 Linux | Full four-core software suite | PASS / PASS; deterministic artifacts matched |
| QEMU user | RV64GC Linux user mode | Loader, admission, scheduling, recovery, trace, and coherency paths | PASS / PASS; Host/RV64 decision CSV hashes matched |
| QEMU `virt` | RV64 + OpenSBI + RT-Thread Nano 5.3.0 | 7,950 loader + 24,548 schedule + 1,000,000 coherency cases | PASS / PASS; zero decision mismatch or coherency failure |
| QEMU `lm3s6965evb` | Cortex-M3 / ARMv7-M | 7,950 loader + 24,548 schedule + 1,000,000 coherency cases | PASS / PASS; zero decision mismatch or coherency failure |
| QEMU `mps2-an385` | Cortex-M3 / ARMv7-M | 7,950 loader + 24,548 schedule + 1,000,000 coherency cases | PASS / PASS; zero decision mismatch or coherency failure |
| QEMU `mps2-an386` | Cortex-M4 / ARMv7E-M | 7,950 loader + 24,548 schedule + 1,000,000 coherency cases | PASS / PASS; zero decision mismatch or coherency failure |
| QEMU `mps2-an500` | Cortex-M7 / ARMv7E-M | 7,950 loader + 24,548 schedule + 1,000,000 coherency cases | PASS / PASS; zero decision mismatch or coherency failure |

Each coherency replay also evaluated 1,171,675 expected-rejection checks per
environment and run. The earlier system-mode smoke suite exercised legal and
truncated packages, two Add+ReLU executions, wrong-epoch rejection, cookie
wrap, normal completion, wait, and session destruction on all five QEMU system
models; every model produced PASS in both runs. The Cortex-M firmware occupied
approximately 25.8 KiB with 13,392 B of BSS; the RT-Thread+AIRTOS image occupied
79,272 B. These results do not measure physical DMA/cache behavior, interrupt
latency, reset timing, energy, or target-board WCET.

### Core 1: Evidence-Constrained and Atomic Admission

| Endpoint | Cases or operations | Failures | Additional result |
|---|---:|---:|---|
| Admission matrix | 3,900 | 0 | Structural, binding, domain, evidence, provider, memory, coherency, scheduling, and recovery decisions |
| Diagnostic classification | 23,400 | 0 | Macro-F1 = 1.0 |
| Evidence-material validation | 1,800 | 0 | Digest mismatch, missing artifact, path escape, and verifier faults rejected |
| Provider-health race | 300 | 0 | No unsafe commit |
| Trust-root rotation | 1,500 | 0 | No decision failure |
| Concurrent admission transactions | 400,000 | 0 | 112,091 accepted; 287,909 rejected |
| Lease overlaps | 400,000 transactions | 0 | No active overlap |
| Partial commits | 400,000 transactions | 0 | No half-admitted job |

### Core 2: Loader, Scheduling, and Board Timing

| Endpoint | Cases | Failures or mismatch | Result |
|---|---:|---:|---|
| Loader corpus | 7,950 | 0 | Production loader path |
| Schedule-oracle comparison | 24,548 | 0 | Status and finish-time agreement |
| CPU Add+ReLU numeric check | 30,000 | 0 | Maximum batch p99 = 1.592 us; maximum = 19.926 us |
| RVV Add+ReLU numeric check | 30,000 | 0 | Maximum batch p99 = 1.592 us; maximum = 19.778 us |

The following admission ablations and WCET-sensitivity results are frozen
software-model results from `airtos-exp-v5`. They use the same production
`SimEDF+` path but are reported separately from the v6 physical-board timing
audit. The admission ablation contains 10,000 small scenarios. The WCET
sensitivity contains 4,178 admitted scenarios per execution-time ratio.

| Scheduling admission condition | False accepts | False rejects |
|---|---:|---:|
| No admission check | 5,822 | 0 |
| Candidate-only finish check | 3,932 | 0 |
| FIFO admission baseline | 27 | 355 |
| Fixed-priority admission baseline | 29 | 380 |
| Complete all-job `SimEDF+` | 0 | 0 |

| Actual/WCET ratio | Admitted scenarios | Deadline misses |
|---:|---:|---:|
| 0.50 | 4,178 | 0 |
| 0.80 | 4,178 | 0 |
| 1.00 | 4,178 | 0 |
| 1.05 | 4,178 | 446 |
| 1.20 | 4,178 | 1,145 |

| Timing path | Registered threshold | Observed batch p99 | Observed maximum | Contract outcome |
|---|---:|---:|---:|---|
| RVV primary Add+ReLU | WCET 4 us | 1.592 us | 19.778 us | Failed because maximum exceeded WCET |
| CPU fallback Add+ReLU | WCET 10 us | 1.592 us | 19.926 us | Failed because maximum exceeded WCET |
| Clock read | p99 below 5 us | 1.518 us | 12.111 us | 5 us p99 threshold passed |
| ISR completion | p99 below 5 us | 3.445 us | 39.074 us | 5 us p99 threshold passed |
| Lease release | p99 below 5 us | 1.667 us | 2.629 us | 5 us p99 threshold passed |
| Plan load | p99 below 5 us | 3.741 us | 36.963 us | 5 us p99 threshold passed |
| Queue push/pop | p99 below 5 us | 1.555 us | 37.037 us | 5 us p99 threshold passed |
| SimEDF admission | p99 below 5 us | 2.223 us | 37.037 us | 5 us p99 threshold passed |
| Trace emission | p99 below 5 us | 1.704 us | 35.777 us | 5 us p99 threshold passed |

The maximum control-path batch p99 was 3.741 us, so the preregistered 5 us threshold passed. The stricter threshold requiring control overhead below 5% of the shortest segment did not pass.

### Core 3: Leases and Physical Coherency

| Endpoint | Cases or attempts | Failures | Result |
|---|---:|---:|---|
| Allocator | 1,000,000 | 0 | 948,950 successful leases |
| Software coherency state machine | 1,000,000 per environment/run | 0 | 1,171,675 expected rejection checks also passed |
| Physical DMA transfers | 1,000,000 | 0 | Zero data mismatch |
| Omitted clean negative control | 400 | 0 undetected | 400/400 omissions detected |
| Omitted invalidate negative control | 400 | 0 undetected | 400/400 omissions detected |

| Transfer size | Cases | Mean complete-path time |
|---:|---:|---:|
| 64 B | 250,000 | 29.949 us |
| 256 B | 250,000 | 34.490 us |
| 4,096 B | 250,000 | 86.502 us |
| 65,536 B | 250,000 | 713.355 us |

### Core 4: Stale Events, Recovery, Feedback, and Short HIL

| Endpoint | Cases or episodes | Failures or bypass | Additional result |
|---|---:|---:|---|
| Seven stale-event classes | 700,000 | 0 | No stale state mutation |
| Recovery episodes | 1,500 | 0 | Bounded state-machine checks |
| Recovery-budget episodes | 4,800 | 0 | Quarantine/budget closure |
| Fallback gate episodes | 1,200 | 0 | No re-admission bypass |
| Base trace classification | 800 | 0 | Macro-F1 = 1.0; top-3 recall = 1.0 |
| Robust trace classification | 2,400 | 0 | Macro-F1 = 1.0 under noise and ring wrap |
| Device reopen/reinitialize | 300 | 0 | p99 = 53.148 us; maximum = 69.222 us |
| Continuous HIL | 6,685,424 DMA iterations | 0 | 1,440 s; 52.406 C final temperature |

Each continuous-HIL iteration generated a deterministic pattern, cycled through 64, 256, 4,096, and 65,536 byte transfers, performed cache writeback, invoked the physical GSDMA copy, invalidated the destination, and compared bytes. The device was deinitialized and reinitialized every 100,000 iterations. These were DMA lifecycle iterations, not heterogeneous inference jobs or NPU executions. Failure counters were `data_failures=0`, `device_failures=0`, and `lifecycle_failures=0`. The terminal token was `AIRTOS_K230_LONG_PASS`; `completion_criteria_pass=true` and `short_experiments_pass=true`.

### Figure-3 Coverage Totals

These totals aggregate non-overlapping primary operations used to visualize coverage; they are not statistical sample sizes for a common estimator.

| Experimental core | Count represented in coverage plot | Observed safety failures |
|---|---:|---:|
| Core 1: admission and transactions | 429,100 | 0 |
| Core 2: loading, scheduling, and numeric runs | 92,498 | 0 |
| Core 3: allocation and DMA | 2,000,800 | 0 |
| Core 4: stale, recovery, fallback, trace, lifecycle, and HIL jobs | 7,396,424 | 0 |

## 3. Qualitative Observations

1. Joint admission produced no unsafe acceptance, lease overlap, or partial commit in the frozen finite corpus.
2. `SimEDF+` agreed with the independent oracle in 24,548 cases, supporting implementation consistency within that generated domain.
3. Physical data movement and both omission controls support plan-driven ownership transitions on the tested K230 configuration.
4. Epoch-cookie checks and recovery gates showed no state-safety failure under software-injected events, but those injections are not evidence of real late driver IRQ behavior.
5. The most important negative result is the WCET audit: both CPU and RVV observed maxima exceeded their registered bounds. AIRTOS therefore cannot claim hard-real-time execution on this configuration even though p99 values were below the bounds.
6. Reopen/reinitialize is a software lifecycle operation, not a device hard reset. The 24-minute HIL run is short-duration evidence only.

## 4. Permitted Conclusions

- Supported: finite-domain implementation consistency for admission, transaction atomicity, scheduling, leases, tested K230 coherency, stale-event state isolation, recovery-budget closure, fallback re-admission, and trace classification.
- Supported with narrow wording: no data, device-call, or lifecycle counterexample was observed over 6,685,424 DMA iterations in 24 minutes on one board.
- Not supported: unconditional hard real time, general NPU behavior, real late-IRQ isolation, hard-reset recovery, power efficiency, 24-hour stability, or cross-board generalization.

# AIRTOS 实验实施蓝图：联合准入、故障恢复与 HIL 素材

## 0. 文档定位

- 对应论文：[理论设计](./theoretical_design.md)
- 预注册规则：[实验协议](./experiment_protocol.md)
- 状态：`PARTIAL-RESULT / SHORT-PHYSICAL-HIL-SUPPORTED / 24H-HIL-IN-PROGRESS`
- 目标：把 AIRTOS 的数学谓词落实为可执行 runtime transaction，并把调度、内存、coherency、故障和物理长测素材细化到可直接制作。
- 纪律：正式实验禁用 mock/stub provider。Host 生产 runtime、QEMU 同源固件和物理 HIL 支持不同层次的结论；QEMU 可扩大模型与路径覆盖，但不能替代板级 timing、DMA/cache、reset/IRQ 和长期运行证据。

## 1. 实现设计目的与问题边界

AIRTOS 的目的不是重新实现完整 RTOS scheduler，而是在已有 RTOS 上治理异构 AI segment DAG：作业只有在计划绑定、证据、适用域、provider、WCET、调度、arena lease、coherency 和恢复预算同时满足时才能提交；提交时 schedule 与 memory 必须原子生效；取消、复位和迟到完成不能污染新作业。

核心因果链：

```text
CECAP package
 -> loader structural validation
 -> session plan binding
 -> lease probe + multi-job SimEDF/dbf + generation-guarded commit
 -> atomic commit/rollback
 -> per-resource EDF dispatch
 -> plan-driven coherency
 -> epoch/cookie completion isolation
 -> epoch-cookie + bounded reset/reinit + quarantine/fallback
 -> JSON/schema-validated attributable trace
```

边界条件：deadline safety 只在 `actual execution <= frozen WCET`、到达/预留模型成立、non-preemptive blocking 和 recovery overhead 已建模时讨论；有限 stress 不能证明无限时间可靠；Host/QEMU 不能证明非一致 cache/DMA 的物理正确性；没有真实 provider 的 cancel/reset 时界依据就只能报告测量，不能称有界恢复。

## 2. 当前代码基线与正式实验缺口

| 能力 | 当前实现 | 已完成的软件/QEMU验证 | 剩余正式实验缺口 |
|---|---|---|---|
| AEG/evidence | v2 全部 binding hash、逐义务 scope/artifact/verifier hash、verifier allowlist、fallback 和 policy；产品生成前现场验证材料 | 软件/QEMU 两轮；K230 实体 7,950 loader、3,900 admission、23,400 diagnosis、1,500 trust rotation 和 300 health race 均通过 | 实体 ISR fault point 与生产部署边界 |
| EDF/DAG | runtime stable EDF；生产 admission simulator 重建全部 job、按资源 EDF 推进 DAG并重验 deadline | 24,548 场景跨软件/QEMU 一致；K230 实体全量重放零 mismatch | 实测最大值超过原 WCET；须重新标定、生成新计划并构建 timing-confirmatory corpus |
| finish-time admission | active residual+三类 cost、reservation period/dbf、全部 snapshot deadlines | oracle 与单元边界 | 更长 sporadic horizon、理论临界点完备性、真实 WCET |
| 原子准入 | lock 内 lease probe/snapshot，锁外 simulate，双 generation 复核，锁内 lease+job commit | 软件两轮及 K230 实体 2/4/8/16 线程各 100,000 transaction；partial commit、overlap 与 rollback leak 均为 0 | 实体 ISR 并发和生产 driver 竞争 |
| stale 检查 | device/epoch/active job/cookie | 每平台七类各 `10^5`，共 700,000 stale event；cookie wrap 与新 epoch 隔离通过 | 物理迟到 IRQ、真实中断生存期与 cookie 复用时界 |
| arena | per-job generation lease；生产 allocator 与独立 byte-owner shadow | 软件两轮及 K230 实体各一百万 attempt；canary、跨 session differential、generation race、rollback leak 均为 0 | 更大 arena、多 session 和共享 cache-line 干扰 |
| coherency | range/cache-line/clean/invalidate/barrier、hook failure 与 ownership transition | 软件/QEMU 多环境 replay；K230 四档一百万次真实物理搬运零差分，遗漏 clean/invalidate 各 400/400 可观察 | 非对齐范围、其他 DMA engine、乱序/总线竞争和其他芯片 |
| recovery/fallback | cancel/reset/reinit poll、三个 timeout、\(K_r\)、quarantine、自动 fallback；切换前重验 evidence/provider/lease/`SimEDF+` | 板上 700,000 stale、1,500 legacy + 4,800 budget + 1,200 gate；真实设备重开/重初始化 300 次通过 | 当前 24 分钟持续运行；真实 driver late IRQ、硬复位、真实 fault seed及后续 24 h HIL |
| trace/反馈 | chronological ring、JSON exporter、event plan ID、Schema、扩展 taxonomy；反馈只生成 candidate | 800-case 基础 corpus macro-F1/top-3=1.0/1.0；2,400-case 噪声/ring-wrap corpus macro-F1/accuracy=1.0/1.0 | 真实工作负载标签外部效度和实体板端到端重新升证 |

恢复后 fallback 联合 schedule admission、artifact/verifier 现场校验、trust-root 轮换、扩展 trace taxonomy、噪声/ring-wrap 稳健性、pairwise diagnosis、并发 fault point、正式 coherency replay 与完整 corpus system replay 已闭合。v6 新增 K230 实体联合准入、全量调度重放、内存租约、真实 DMA/cache、板级开销、生成算子时序和设备生命周期证据。当前先完成 24 分钟持续运行，后续核心缺口仍为：用实体最大值重新生成计划后的期限复验、真实 driver late IRQ/硬复位 fault seed、真实标签、功耗和 24 h HIL；实体时序已经否定原计划 WCET 与严格 5% 低开销阈值，不能以 p99 掩盖最大值。

## 3. AEG/package v2 运行时合同

CECAP `plan.json/evidence.json/airtos_policy.json` 已携带完整合同；压缩 AEG v2 运行时包携带其 plan/evidence/policy 绑定摘要和运行必需字段：

```text
plan/evidence/policy/model/target/runtime_abi/provider_abi/fallback_plan hashes
segments(id, resource, dependencies, wcet, buffers, coherency actions)
domain(shape, dtype, layout, input/output bytes)
evidence records(obligation, scope, artifact, verifier, resource, verified) + fallback segments
arena_bytes + segment ranges
arrival/reservation model + end-to-end deadline
recovery policy(cancel/reset/reinit timeout, max_reset_attempts)
```

loader 验证结构、索引、非零摘要、verified flag 和数值范围；`rt_ai_session_create_v2` 将 AEG 与产品生成的 trust bundle 逐项比较，包括全部 binding hash、obligation/scope/artifact/verifier hash、resource 和 verifier allowlist。产品 `_trust` 在生成 trust bundle 前读取 evidence manifest，约束 artifact/verifier 路径位于 evidence root，检查文件存在并现场重算 SHA-256；v5 六类各 300 的材料 harness 已验证 mismatch/missing/path escape 均 fail closed。v2 submit 再核对 invocation plan/input domain 与动态 provider/health、到达、deadline、memory 和 schedule。

## 4. 联合准入 transaction

当前实现是乐观 validation transaction，而非长时间持锁或真正的 provisional lease：

```text
submit_v2(session, invocation, policy):
  validate plan hash, tensor domain, deployable/legacy, deadline/interarrival
  validate providers healthy and not pending/quarantined
  repeat max_retries:
    lock(runtime)
    choose free job slot
    lease = arena_probe(); capture lease_generation
    snapshot = schedule_snapshot(); capture schedule_generation
    unlock(runtime)
    finish = rt_ai_sim_edf(snapshot, candidate)
    if infeasible: reject DEADLINE
    lock(runtime)
    if schedule/slot/session/lease generation changed: unlock; retry
    arena_commit(lease)
    initialize and publish job; mark session busy; increment generation
    unlock(runtime); accept
  reject RETRY
```

该结构没有在仿真期间占住 lease，但 commit 前同时复核 schedule generation、lease generation、slot 和 session，并且 `arena_commit` 后没有可失败步骤。Core-1 已在 2/4/8/16 线程各 100,000 transaction、provider-health race 与 generation 竞争中检查该线性化点；两轮 partial commit、overlap 和 rollback leak 均为 0。该有限并发域不替代实体 ISR/driver 竞争。当前 admission 不写 `ADMISSION_COMMIT` trace；若论文需要逐 transaction admission event，仍须扩展 exporter，不能由 dispatch trace 代替。

### 4.1 `SimEDF+` 事件模型与当前覆盖

论文目标的事件至少包括：arrival、segment-ready、dispatch、non-preemptive-complete、DMA/coherency、cancel overhead、reset/reinit overhead、deadline。状态包括每资源 active residual、EDF queue、DAG predecessor、reservation supply 和 candidate lease。

当前 `rt_ai_sim_edf` 已把 snapshot jobs 与 candidate 合并，按 per-resource earliest-deadline ready segment 做非抢占离散事件推进；running cost 使用 WCET residual+coherency+recovery，结束时重验每个 job deadline，并在各 job deadline 检查 reservation/dbf。实现已达到 `SimEDF+` 的主结构。

独立 `oracle.py` 不调用 runtime queue/admission/lease，实现另一套事件循环。v5 已冻结 10,000 个一般 small DAG、5,000 stress、2,048 bounded Cartesian 和 30 seed x 250 multiseed，共 24,548 场景，覆盖 1-4 资源、running residual、reservation/dbf 与非抢占 blocking；Host/RV64 C 与独立 oracle 逐例一致，并在 RT-Thread/RV64 及四款 Cortex-M QEMU system machine 完整重放。该 corpus 的 cost 来自冻结 palette，因此只形成软件/QEMU模型结论；timing-confirmatory Core-2 仍必须从真实 CECAP plan DAG、CanMV-K230 measured WCET 和 arrival/provider trace 重新派生并在板上重放。

## 5. 恢复与 trace 接口

### 5.1 provider API 最小扩展

```text
cancel_begin(user, epoch, cookie) -> accepted/error
cancel_poll(user, epoch, cookie) -> pending/ack/error
reset_begin(user, new_epoch) -> accepted/error
reset_poll(user, new_epoch) -> pending/ack/error
reinit_poll(user, new_epoch) -> pending/healthy/error
health(user) -> healthy/degraded/quarantined
```

当前状态机：`running -> cancel_pending -> reset_pending -> reinit_pending -> healthy`；每次 reset 增加 epoch 和 attempt，任何 reset/reinit error/timeout 在 attempt<\(K_r\) 时重试，达到预算后 quarantine。故障 job 只有在 trust/evidence 重验通过、原 lease 仍活动且覆盖 fallback range、fallback provider 健康，并由当前 schedule snapshot 的 `rt_ai_sim_edf` 接纳后，才切换 fallback segments；失败会记录具体 status 并结束原故障 job。该实现仍需真实 provider、既有作业竞争和物理 fault seed 的正式验证。

### 5.2 trace 最小字段

```text
logical_sequence:uint64, timestamp:uint64, run_id, plan_hash,
job_id, segment_id, resource, epoch, cookie, event, status
```

当前 C ring 已按 logical sequence 重排并报告 dropped；JSON exporter 将 uint64 run ID 编码为 64-hex，并为每个 event 输出 primary/fallback plan ID。v5 以 `airtos_trace.schema.json` 校验实际输出，并在八类、每类 100 个冻结场景上完成根因分类与下一实验选择：macro-F1=1.0、top-3 recall=1.0、status-only macro-F1=0.416667、gate bypass=0。另在八类、每类 300 个场景中注入 65-128 个干扰事件并强制 ring wrap，2,400/2,400 wrap，macro-F1/accuracy=1.0/1.0。该结果支持冻结合成标签域，不支持真实工作负载标签外部效度；若论文需要逐 transaction admission/lease/coherency 事件，exporter 仍需补齐对应字段。

## 6. 实验素材总 manifest

```text
benchmarks/airtos/v1/
  manifest.json
  packages/valid/*.json
  packages/mutations/<class>/*.json
  oracle_scenarios/small/*.json
  stress_scenarios/*.json
  wcet_tables/*.json
  arrival_traces/*.jsonl
  lease_scenarios/*.json
  dma_buffers/*.bin
  coherency_scenarios/*.json
  fault_traces/<class>/*.jsonl
  feedback_scenarios/*.json
  hil_workload.json
  device_contracts/*.json
  seeds.txt
  exclusions.jsonl
```

### 6.1 10,000 个独立 oracle 小场景

| 维度 | 水平 | 覆盖方法 |
|---|---|---|
| resources | 1、2、3（CPU/RVV/NPU） | 分层均衡 |
| jobs | 1-8 | 边界值加权 |
| segments/job | 1-8 | chain/diamond/fan-in/fan-out |
| deadlines | distinct、equal、tight、infeasible | 每类至少 1,500 |
| WCET | CanMV-K230 measured ticks 的离散化值 | 保留原始 measurement ID |
| blocking | 0、short、near-deadline | 每资源覆盖 |
| arrivals | 板上 workload trace 中的 synchronous、periodic、sporadic burst | 保留 trace range，与 reservation 配对 |
| recovery cost | 0、cancel、reset | 至少 1,000 含故障场景 |

生成器只能对真实 plan DAG、measured WCET 和板上 arrival/provider trace 做确定性组合与边界 mutation，再由独立 oracle 标 `admit/reject`、期望 dispatch 序列集合、deadline outcome 和最大 resource demand。每例保存 source plan/measurement/trace hash；必须同时保留至少 30% 不可准入场景，防止只测正例。

### 6.2 5,000 个真实 trace 派生 stress 场景

- 30 个固定 seed；每 seed 至少 166 场景，剩余按 seed 轮转。
- jobs 8-64、segments 1-32、资源 1-3、arena 占用 40%-120%、deadline slack 覆盖观测区间及其预注册边界；所有 DAG/WCET/arrival 均能追溯到真实 plan 和板测 trace。
- 20% 含 cancel/reset，20% 含 arrival burst，20% 含同 deadline，20% 含高 fragmentation，20% 混合。
- stress 用于尾延迟、吞吐和反例搜索，不替代 10,000 小场景的逐例 oracle 一致性。

### 6.3 package mutation 素材

每类 300：magic/version、长度/offset、DAG cycle、resource/provider、plan/model/target hash、domain、evidence bits、WCET 缺失/负值/溢出、fallback 过期、coherency range 越界、recovery policy 无效。每个 case 保存 JSON Pointer diff、期望拒绝阶段和唯一主原因。

### 6.4 lease 与内存素材

- arena 大小和 alignment 由冻结 CECAP plan/Board-P2 合同中的实际值分层；协议边界值仅作为负例单列。
- lifetime 结构覆盖不重叠、部分重叠、完全嵌套、跨 session、cancel 中释放、reset 后回收。
- 至少 `10^6` 次 allocate/commit/rollback/free 操作；操作族来自真实 plan tensor lifetime 与板上 session trace，再通过冻结线程 interleaving 扩展；每 1,000 次保存位图和 canary hash。
- 数据 pattern 包括 walking bits、全 00/FF、address-derived、seeded random；跨 lease corruption 由 guard/canary 与最终 hash 双检。

### 6.5 DMA/cache 素材

| 因子 | 水平 |
|---|---|
| transfer | CPU->device、device->CPU、bidirectional、no-transfer |
| alignment | aligned、line-1、line+1、跨两 cache line |
| size | 1 B、line-1、line、line+1、4 KiB、arena boundary |
| ownership | CPU dirty、device dirty、shared-invalid、错误 owner |
| action mutation | omit clean、omit invalidate、wrong range、wrong order |

QEMU 使用板上捕获的 coherency command/IRQ trace，通过同源固件检查 parser、range 与调用顺序；数据一致性只由 CanMV-K230 上真实 buffer、真实 DMA descriptor 和 CPU/reference path 比较，至少 `10^6` 次物理 DMA/cache 操作。若平台无法产生可观测负对照，标为 `BLOCKED-HIL`，不得以行为模型补齐。

### 6.6 stale 与恢复素材

Board-P2 通过生产 driver/device fault injection 为每个可安全触发类别采集至少 30 个物理 seed：重复 IRQ、cancel 后迟到、reset 后迟到、错误 device/epoch/cookie、同 epoch 重复、cookie wrap 邻域；原始序列通过 QEMU 同源 ISR/completion 入口扩展到每类至少 `10^5` 次 replay。cancel failure、reset failure、reinit failure、连续超预算各 300 个物理 episode；无法安全触发者标为 `BLOCKED-HIL`。

事件 trace 在注入前冻结：原 job、注入时间、旧/新 epoch-cookie、预期返回、允许改变的状态、禁止改变的新 job 字段。cookie wrap 测试必须缩小测试位宽或可控地设置计数器，不能等待自然 32-bit wrap。

### 6.7 HIL 素材

- 唯一 device/probe serial、板卡 revision、firmware/image/plan/model hash。
- 频率、电压、温度、电源仪器和校准；串口/trace clock 对齐误差。
- 混合 workload 至少 24 小时且至少 `10^6` jobs，两条件同时满足。
- workload 覆盖 CPU/RVV、可用 NPU、DMA、多 session、deadline 分层、周期 cancel/reset 和受控 stale event。
- 每次启动先 readback image hash，再写 `run_id` 到设备与 host 日志；不匹配立即 `BLOCKED-HIL`。

## 7. 四个核心实验与实施卡

| 核心实验 | 内部实施卡 | 唯一主端点 |
|---|---|---|
| Core-1 package 与原子联合准入 | S1 loader；S2 联合准入 | unsafe admission 与 partial commit |
| Core-2 调度、WCET 与开销 | S3 oracle；S4 WCET；S8 overhead | model-valid oracle/deadline 一致性 |
| Core-3 内存与 coherency | S5 lease；S6 DMA/cache | overlap/corruption/reference diff |
| Core-4 恢复、反馈与 HIL | S7 stale；S9 feedback；S10 HIL | wrong completion/quarantine/bypass/HIL 安全端点 |

以下实施卡是四个核心实验内部的子测试，不单独扩张论文实验数量。

### 子测试 S1：AEG/package 结构安全

**目的**：在任何内存访问或 provider 调用前拒绝畸形/错绑 package。

**素材**：12 类 package mutation 各 300、合法 package 300、fuzz 补充集。

**执行**：loader 逐 case 解析；guard-page/ASan host harness 观察越界；记录首个拒绝原因；合法包 roundtrip 后 canonical hash 不变。

**输出**：parse decision、reason、bytes consumed、cycles、memory-safety log。

**结论锁**：关键非法包错误接受=0；合法误拒单列。崩溃后拒绝不算安全解析。

### 子测试 S2：联合准入与原子回滚

**目的**：验证 evidence/domain/provider/WCET/schedule/lease 的合取谓词和 transaction 原子性。

**素材**：单因子各 300；两两组合至少 1,000；10,000 并发 transaction schedule；arena 40%-120% 压力。

**执行**：在锁前后注入 yield；对每个失败点快照 queue/jobs/lease/cookie/session；与纯函数 admission oracle 比较；成功时检查 schedule 与 lease 同时可见。

**结论锁**：unsafe admission、部分 commit、失败后资源泄漏任一非零即 H2 失败；false rejection 只影响利用率。

### 子测试 S3：DAG、EDF、blocking 与 admission oracle

**目的**：扩展当前 `SimEDF+` 已验证域，并验证依赖顺序、per-resource EDF、dbf 和 admission 与独立模型一致。

**素材**：当前固定 seed 已冻结 10,000 个一般 small、5,000 个 5-8 job stress、2,048 bounded grid 和 30 seed x 250 multiseed，并在 Host/RV64 user-mode、RT-Thread/RV64 与四个 Cortex-M machine 完整重放。当前 cost 来自 palette，只作为软件模型结果。timing-confirmatory corpus 必须重新从真实 CECAP DAG、板测 WCET/arrival/provider trace 派生，覆盖同 deadline/tie、blocking、recovery cost 与 fallback；另保留导致 WCET 时间隔离修正的非抢占调度异常反例族。

**执行**：Host runtime 与 oracle 分别运行；QEMU 重放同源 RTOS 路径；比较 admit/reject、合法 dispatch 序列集合、dependency、每个新旧 job 的 predicted completion 和 deadline；逐资源检查非抢占区间。最后在 Board-P2 重放冻结 arrival trace 并比较实际完成。只返回候选 finish 的实现必须在最小反例族中被判为 false admission，而不是按候选自身是否按时计分。

**结论锁**：10,000 场景逐例一致且无 dependency/EDF 错误才支持 H2/H3 的实现一致性；平均准确率不能代替。

### 子测试 S4：WCET 与 deadline safety 条件

**目的**：区分 admission 算法错误与 WCET 模型失效。

**素材**：Board-P2 实测 actual/WCET 分布及预注册敏感性分层 0.5、0.8、1.0、1.05、1.2；板上 periodic/sporadic/burst 到达 trace；真实 blocking/recovery 开销；每格至少 300 jobs、30 个 trace block。

**执行**：冻结 WCET 后运行，不用同批 actual 反向调表；按 `actual<=WCET` 与超界分层；比较 miss、admission、pessimism 和利用率。

**结论锁**：模型有效层出现 deadline miss 或 oracle disagreement，H3 失败；只在 actual>WCET 层失败，结论是适用域失效而非 scheduler 定理失败。

### 子测试 S5：arena lease 与跨 session 隔离

**目的**：验证无重叠、无越权访问、rollback 无泄漏，并量化 fragmentation。

**素材**：第 6.4 节 `10^6` 操作、三种 arena、四种 alignment、并发/cancel/reset 序列。

**执行**：每次操作用参考 interval allocator 重算；写 canary/data pattern；随机 destroy/cancel/reset；周期性全 arena hash 与 active lease map 比对。

**结论锁**：任一 live lease overlap、跨 session corruption 或 rollback leak 为安全失败；分配失败率和 fragmentation 仅属可用性。

### 子测试 S6：cache/DMA coherency

**目的**：证明 plan action 与 buffer ownership/range 一致，并在可信平台上保持数据正确。

**素材**：第 6.5 节因子组合、action mutations、`10^6` 操作、uncached/reference 输出。

**执行**：比较完整、omit clean、omit invalidate、wrong range/order；记录 hook range、DMA descriptor、before/after hash；真实非一致平台重复测量。

**结论锁**：CanMV-K230 完整物理路径在声明域内差分为 0 才支持 H5；QEMU 通过只能写“同源固件的 coherency 命令路径一致”。硬件天然 coherent 或负对照不可观测时不支持非一致 cache 主张。

### 子测试 S7：timeout、cancel、reset、stale 与 quarantine

**目的**：验证旧世界事件不能修改新世界状态，并验证恢复预算的失败闭合。

**素材**：真实 driver/device fault injection 产生的物理 seed 与 QEMU 同源 ISR replay，每 stale 类 `10^5` 事件；恢复失败各 300 个物理 episode；冻结 cancel/reset/reinit bounds 与 \(K_r\in\{1,2,3,5\}\)；增加从真实 fallback plan 缩减得到的可行/不可行及会破坏既有 deadline 的反例。

**执行**：按 trace 注入；在 cancel ack 前后、epoch 增加前后和 cookie wrap 邻域检查；注入 cancel/reset/reinit timeout/error 和 health error；观察预算、quarantine、plan-ID trace 与 fallback。以保留的“直接 fallback”消融版本对照当前完整 gate，检查完整 gate 是否拒绝不可调度、失效 trust、无活动 lease 或不健康 provider 的恢复。

**结论锁**：任一 stale event 完成错误 job、达到预算未 quarantine、或 fallback 绕过 evidence/provider/schedule gate并破坏承诺即 H6 失败。无硬件依据的 bound 只能报告 stress latency。

### 子测试 S8：运行时开销

**目的**：量化安全机制的真实成本，并判断是否在 segment/deadline 预算内。

**素材**：load、admission、queue、lease、cache hook、ISR、trace、recovery 微测；每项 10 warm-up + 1,000 measurements；30 个端到端 batch。

**执行**：完整配置与逐项消融随机交错；记录 cycles、p50/p95/p99、代码/RAM、最大锁/关中断时间、吞吐和 deadline budget ratio。

**结论锁**：只有完整配置的 CI 满足冻结预算才支持 H7；host 绝对时间不能外推目标板。

### 子测试 S9：trace 到下一实验且不自证

**目的**：验证 trace 能选择正确的下一验证实验，同时新计划必须重新升证。

**素材**：contention、DMA dominant、kernel dominant、arena pressure、WCET miss、reset storm、coherency fault、无回归各 100 场景。

**执行**：比较无反馈、total-latency-only、人工规则、AIRTOS trace+ADAM selection；隐藏 root cause；候选新计划必须有新 hash、CECAP evidence、AIRTOS admission。

**结论锁**：root-cause macro-F1 和 top-k 达阈值且 bypass=0 才支持 H8；性能改善但绕过升证仍是失败。

### 子测试 S10：物理 HIL 长时稳定性

**目的**：在真实设备、DMA/cache、长时间故障和多 session 下寻找反例。

**素材**：第 6.7 节绑定记录；当前 24 分钟且 `10^6` jobs，后续 24 h 且 `10^6` jobs；混合 workload 与环境日志。

**执行**：先完成 device/image/run binding；随机交错 workload；周期注入 cancel/reset/stale；持续导出 trace、canary、output hash、温度/频率/功耗。

**结论锁**：错误 completion、stale acceptance、lease corruption、coherency diff、unsafe fallback、不可恢复死锁均零容忍。通过只能写“有限长测试未观察到反例”，不能写无限可靠。

## 8. 素材、指标与结论映射

| 核心实验 | 主素材 | 主端点 | 支持条件 | 一票否决 |
|---|---|---|---|---|
| Core-1 package 与原子联合准入 | structure/factor/concurrent tx | unsafe parse/admit、partial commit | 关键错误全零 | 越界/错绑、资源泄漏或部分提交 |
| Core-2 调度、WCET 与开销 | 10,000 oracle + WCET strata + microbench | 逐场景一致、valid miss、budget ratio | model-valid 层一致且开销达预算 | 任一 model-valid disagreement/miss |
| Core-3 内存与 coherency | `10^6` lease + `10^6` DMA ops | overlap/corruption/reference diff | 关键错误全零 | 跨 session 污染或可信平台差分 |
| Core-4 恢复、反馈与 HIL | stale events + labelled cases + 24h/`10^6` jobs | wrong completion、quarantine、F1/top-k/bypass、HIL 安全端点 | 安全端点全零且反馈达标 | 旧事件污染、绕过升证或任一 HIL 关键事件 |

## 9. 四类结论出口与预取方向

1. `SUPPORTED-WITHIN-MODEL`：实现齐全并在冻结模型、平台、WCET/arrival/recovery 前提内达标。
2. `NOT-SUPPORTED`：实验有效但调度、开销、反馈或稳定性阈值未满足。
3. `SAFE-ENDPOINT-FAILED`：unsafe admission、dependency error、污染、coherency diff 或 stale completion 非零。
4. `IMPLEMENTATION-NOT-READY`：必要代码对象缺失；当前 fallback gate 不再属于此类。扩域 corpus、并发/故障素材或 HIL 未完成时，分别标为 `EXPERIMENT-NOT-READY` 或 `BLOCKED-HIL`，不得再误写成代码机制不存在。

v5 软件/QEMU结果已观察到：联合准入阻止冻结域内的不合格作业；artifact/verifier 材料错误与 stale trust root 均 fail closed；`actual<=WCET` 层零 miss，而 `q=1.05/1.2` 分别出现 446/1,145 miss；每环境 1,000,000 coherency 命令 case 零失败；epoch+cookie+quarantine 在每平台 700,000 stale event 中未见状态污染；基础与噪声/ring-wrap trace 的 macro-F1 均为 1.0。目标板低开销、物理 deadline、DMA/cache 和 HIL 方向仍待实体实验，不能由这些结果代填。

## 10. 实施顺序与完成判据

| 阶段 | 工作 | 完成判据 |
|---|---|---|
| A（软件/QEMU已完成） | package v2 loader 与 plan/evidence/policy binding | 7,950 loader 与 23,400 diagnosis 两轮通过 |
| B（软件并发已完成） | 乐观 lease/schedule transaction | 2-16 线程与竞争历史无部分提交 |
| C（模型域已完成） | 多作业 `SimEDF+`/dbf 与独立 oracle | 24,548 场景逐例一致；timing-confirmatory 待板测数据 |
| D（软件状态机已完成） | recovery/quarantine/automatic fallback | 预算、隔离与联合 gate 通过；物理时界待实板 |
| E（冻结 corpus 已完成） | trace v2 JSON/Schema/metrics/classifier | 800-case 基础与 2,400-case 噪声/ring-wrap 阈值通过；真实标签待实板 |
| F（已冻结） | 10,000 oracle/5,000 stress 及扩展素材 | manifest/hash/逐场景结果两轮可重放 |
| G（软件 lease/coherency 命令已完成，物理待制作） | 并发 lease 与 DMA/cache | shadow/canary/differential 与七环境命令 replay 通过；真实 DMA/cache 待实板 |
| H（短时已完成，长时待补） | 目标板微测和 HIL | 当前 24 分钟且 `10^6` jobs 已通过；后续扩展为 24 h 且 `10^6` jobs |

## 11. readiness checklist

- [x] package v2 携带全部 binding、逐义务 evidence、input domain、WCET、fallback、coherency、arrival/reservation 和恢复预算
- [x] trust bundle 与 `rt_ai_session_create_v2` 实现 runtime evidence policy evaluator
- [x] 产品 trust 生成前现场重哈希 artifact/verifier 并限制 evidence-root 路径，trust-root old/dual/new 轮换已验证
- [x] session create 缓存计划，v2 submit 完成 probe->simulate->generation validate->lease/job commit
- [x] `SimEDF+` 重验全部 snapshot deadlines，包含 EDF/DAG、active residual、三类 cost 和 reservation/dbf
- [x] 独立 oracle 不调用 runtime scheduler/queue/lease，固定 seed 10,000 有限场景逐例一致
- [x] 一般 DAG/running/dbf/tie 的 10,000 small、5,000 stress、2,048 bounded 和 7,500 multiseed 场景已冻结并跨架构重放
- [x] cancel/reset/reinit poll、时界、\(K_r\) 预算、quarantine 和自动 fallback 已实现
- [x] 恢复后 fallback 重验 evidence/provider/active lease 并执行 `SimEDF+` 联合准入
- [x] C trace 有真实 completion timestamp、uint64 sequence、plan/job/resource/epoch/cookie、chronological wrap 和 dropped
- [x] C/JSON trace exporter、event plan ID、v2 schema 和基础 metrics 已验证
- [x] 扩展 trace taxonomy、800 根因场景与 2,400 噪声/ring-wrap 场景已冻结，macro-F1/top-3 和 gate 均达到阈值
- [x] 15 类 package mutation 各 300 及 105 类 pairwise 已冻结并逐例记录拒绝结果
- [x] 随机 lease `10^6` 操作具有 shadow map 与 generation 冲突检查
- [x] 生产 coherency 命令路径在七个软件/QEMU 环境各完成 1,000,000 正式 case，含缺 clean/invalidate/barrier 与错误 range/hook 负对照
- [x] 多线程 lease 每轮 `10^6` attempt 的 shadow/canary/differential checker 可自动运行
- [ ] 物理 DMA/cache `10^6` 操作的 reference/checker 待实体板
- [x] 软件 stale/duplicate 每类 `10^5`、legacy 恢复每类 300 episode 已完成
- [ ] WCET 在正式 actual 结果揭盲前冻结
- [ ] HIL 具备唯一设备、readback、run-ID、环境和仪器校准
- [x] 当前 24 分钟与 `10^6` jobs 两个停止条件同时满足
- [ ] 后续 24 h 与 `10^6` jobs 两个停止条件同时满足
- [x] 文档已禁用正式 mock，并规定 Host/QEMU/physical 分层，不跨层外推

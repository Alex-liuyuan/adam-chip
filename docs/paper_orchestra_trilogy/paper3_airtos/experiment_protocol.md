# AIRTOS 预注册实验协议

> 本文规定假设、阈值和统计纪律；10,000 个 oracle 场景、5,000 个 stress 场景、DMA/cache、故障与 HIL 素材的实施方法见 [实验实施蓝图](implementation_blueprint.md)。

## 0. 协议状态

- 论文：AIRTOS: Evidence-Bounded Admission, Resource Governance, and Recovery for Heterogeneous Edge AI
- 协议版本：`airtos-exp-v6`
- 状态：`PARTIAL-RESULT / SHORT-HIL-SUPPORTED`；二十四分钟持续运行实验已通过，二十四小时扩展长测、真实驱动迟到中断、硬复位和功耗仍为 `BLOCKED-HIL`
- 冻结对象：本文、AEG/package schema、场景生成器、独立调度 oracle、设备合同、WCET 表、故障清单和基线锁
- 结果纪律：正式实验禁用 mock/stub provider；Host 生产 runtime、QEMU 同源固件和物理板分层报告，虚拟覆盖不得替代板级物理证据

本协议不试图用有限次运行“证明永不 miss deadline”。hard deadline 结论始终相对于 WCET、到达模型、非抢占 blocking、恢复开销和运行时一致性成立。实验用于检查实现是否符合该模型，并测量前提在指定平台上是否被违反。

### 0.1 当前代码 readiness 与结果边界

截至 2026-08-04，`airtos-exp-v5-20260804-complete-nonhil` 已完成两次从头复验并冻结原始日志与 SHA-256。每轮覆盖 7,950 个 loader、23,400 个联合诊断、1,800 个 evidence-material case、Host/RV64 各 1,500 个 trust-root 轮换判定、24,548 个调度场景、400,000 次 submit transaction、1,000,000 次 allocator attempt，以及完整 coherency/stale/recovery/fallback/trace corpus。相同 49,085,520 B corpus 已在 Host、RV64 QEMU user-mode、`virt`/RV64 的 RT-Thread Nano 5.3.0，以及 `lm3s6965evb`、`mps2-an385`、`mps2-an386`、`mps2-an500` 四个 Cortex-M3/M4/M7 QEMU machine 上重放；RT-Thread 与每个 Cortex-M machine 另完整执行 1,000,000 个 coherency case；两轮均为零 mismatch/failure。完整报告见 [第五版非实体板实验报告](./results/airtos-exp-v5-20260804-complete-nonhil/EXPERIMENT_REPORT.md)，原始日志和二进制实验数据仍位于 `results/airtos/airtos-exp-v5-20260804-complete-nonhil/`。

这些结果只支持软件与 QEMU machine 模型内的实现符合性和跨架构可移植性。四个 ARM 结果仍是裸机 system machine，其中三个 MPS2 属于同一 FPGA 平台族；`virt` 也不是商品开发板。调度 cost 来自冻结 palette 而非 CanMV-K230 measured WCET，Host S8 不代表板级 cycles，cache hook 也不是真实 DMA/cache。真实 CECAP/板测 trace、物理 WCET/控制开销、生产 driver/device 恢复注入、功耗和 24 h HIL 仍未完成。

截至 2026-08-05，`airtos-exp-v6-20260805-k230-hil` 已在 CanMV-K230-LP4 V3.0 和 RT-Smart 上完成全部短周期实体实验。实体板执行 3,900 个准入案例、23,400 个联合诊断、400,000 次并发提交、7,950 个加载案例、24,548 个调度场景、一百万次内存租约和一百万次真实物理搬运；四档搬运完整路径零差分，遗漏写回和遗漏失效负对照分别 400/400 可观察。七类迟到状态机事件共 700,000 次、恢复/预算/回退门共 7,500 次均无安全失败，真实设备重开/重初始化 300 次零失败。完整报告见 [第六版实体板实验报告](./results/airtos-exp-v6-20260805-k230-hil/EXPERIMENT_REPORT.md)。

实体时序同时证伪了原计划的板级适用性：向量路径最大 19.778 微秒超过登记的 4 微秒，中央处理器回退路径最大 19.926 微秒超过登记的 10 微秒；严格“稳态控制开销小于最短执行段 5%”阈值也未达到。因此实体调度重放一致性已支持，但 K230 硬实时期限和低开销主张继续为 `UNSUPPORTED-BY-MEASURED-WCET`，必须重新标定并生成新计划后复验。迟到事件仍是板上生产状态机的软件注入，不等同于真实驱动迟到中断；当前先执行二十四分钟持续运行实验，二十四小时结果留作后续补测，不得由短时结果外推。

## 1. 行业背景与严格性的必要性

异构边缘推理同时占用 CPU/RVV、NPU、DMA、连续 SRAM、cache ownership 和中断状态。EDF、DAG runtime、NPU 多租户和 timeout API 均已有成熟先例 [@liu1973scheduling; @augonnet2011starpu; @rossbach2011ptask; @choi2020prema; @kim2023dream]。AIRTOS 的行业问题不是“如何再写一个队列”，而是编译计划在当前设备上是否有资格进入队列，以及超时、复位和迟到完成后是否仍保持资源归属。

严格性不可省略：

1. 平均 latency 不能说明 deadline safety，尤其是 NPU/DMA 非抢占 blocking 存在时。
2. 编译计划合法不代表当前 provider、arena、证据策略、输入 shape 或 device epoch 合法。
3. stale IRQ 一次错误接受就可能完成错误 job 并复用其内存，不能由 99.9% 成功率掩盖。
4. Host/QEMU 只能检查 coherency 规则和命令路径，真实 DMA/cache ownership 必须由物理板上的可观察负对照和 reference differential 验证 [@linux2026dmabuf; @linux2026dmaapi]。

## 2. 研究问题与预注册假设

| ID | 研究问题 | 预注册假设 | 主端点 | 支持阈值 |
|---|---|---|---|---|
| RQ1/H1 | 联合准入能否拒绝证据、域、资源、时限或健康状态不合格的计划？ | 完整 `Admit` 对关键 mismatch 零错误接纳 | unsafe admission rate, UAR | 每个关键类别 `UAR=0`；任何错误 hash/ABI/evidence/arena/WCET 接纳即失败 |
| RQ2/H2 | segment DAG 与 per-resource EDF 实现是否保持依赖和队列规则？ | 所有 dispatch 是 DAG 拓扑扩展，资源空闲时选择最早 deadline ready segment | dependency violation；EDF order violation | 10,000 个 oracle 场景中两者均为 0 |
| RQ3/H3 | `SimEDF+` 在明确前提下能否保持已接纳作业 deadline？ | 当 actual<=WCET 且到达/故障在模型内时，runtime 不比保守仿真慢 | oracle disagreement；model-valid deadline miss | 10,000 个小场景与独立 oracle 完全一致；所有 model-valid 场景 miss=0 |
| RQ4/H4 | lease 与 schedule 原子准入能否防止跨 session 污染？ | active leases 不重叠，失败 admission 完全回滚 | overlap/corruption；partial commit | 10^6 次分配操作和压力作业中均为 0 |
| RQ5/H5 | plan-driven coherency 能否防止 stale data？ | 完整 clean/barrier/invalidate 路径在 CanMV-K230 真实 DMA/cache 上与 reference 一致 | coherency reference failure | 每个已支持物理 cache/DMA 域零差分；Host/QEMU 不计入物理结论 |
| RQ6/H6 | epoch-cookie、预算恢复和 fallback 能否隔离迟到事件并终止故障占用？ | stale/duplicate completion 不改变新状态；达到 \(K_r\) 后 quarantine；fallback 重新准入后才执行 | stale acceptance；wrong completion；bound violation；unsafe fallback | 每种事件至少 (10^5) 次注入均为 0；模型内恢复满足时界；超预算正确 quarantine；fallback evidence/provider/schedule gate bypass=0 |
| RQ7/H7 | 安全机制开销是否可用于嵌入式 RTOS？ | admission/dispatch/trace 开销相对任务预算可控 | p99 control overhead；code/RAM | p99 admission 小于 `min(1 ms, 0.05*D_min)`，steady-state control overhead 小于最短 segment WCET 的 5%；未达标则撤回低开销主张 |
| RQ8/H8 | 可归属 trace 能否选择正确的下一实验而不自证？ | trace 分类优于 total-latency-only，且新计划重新验证 | root-cause macro-F1；experiment top-k；gate bypass | macro-F1>=0.90、top-3 recall>=0.95、gate bypass=0 |
| RQ9/H9 | 物理板持续运行是否暴露模型外故障？ | 当前阶段完成至少 24 分钟且至少 (10^6) jobs；后续扩展到 24 小时，不发生安全不变量错误 | safety violation；deadline/stale/reset distributions | 安全不变量错误为 0；24 分钟只支持短时结论，24 小时完成后才支持长时结论 |

## 3. 创新点的新颖性、必要性与证伪映射

| 创新主张 | 最接近已有工作 | 严格差异 | 为什么必要 | 可证伪观察 | 主实验 |
|---|---|---|---|---|---|
| 证据边界联合准入 | EDF/demand analysis、Simplex/runtime assurance [@baruah1990sporadic; @seto1998simplex; @hobbs2023runtimeassurance] | `PackageBind AND Domain AND Evidence AND Provider AND Memory AND Coherence AND Sched AND Recoverable` 同时成立 | 编译合法性和当前运行资格是不同命题 | 任一关键谓词为 false 仍被接纳 | Core-1 |
| segment DAG 多资源治理 | HEFT、StarPU、Legion、PTask、typed-DAG [@topcuoglu2002heft; @augonnet2011starpu; @bauer2012legion; @rossbach2011ptask; @lin2022typedag] | 计划证据/适用域约束下的 per-resource ready queue，并与 admission、lease、recovery 一体化 | 调度提交线程不能表达异步设备与 tensor 生命周期 | 前驱未完成 dispatch，或 EDF 选择错误 | Core-2 |
| 内存-时限原子准入 | TFLM/Salus/MoCA 的内存管理与多租户 [@david2021tflm; @yu2019salus; @kim2023moca] | 先暂占 lease，再在同一 transaction 仿真 schedule，失败统一回滚 | 分开检查会出现 memory 可行而 deadline 不可行的半提交 | active lease 重叠、拒绝后残留、并发 TOCTOU | Core-1、Core-3 |
| epoch-cookie 恢复语义 | 通用 timeout/cancel、DMA fence [@linux2026dmabuf] | `(device,epoch,cookie)` 精确归属迟到/重复完成；\(K_r\) 次 reset/reinit 后 quarantine 并选择独立 fallback | reset 后旧 IRQ 可命中新 job 指针 | stale event 改变新 job、失败资源继续接纳或 fallback 绕过 schedule gate | Core-4 |
| plan-driven coherency | Linux DMA mapping/ownership API [@linux2026dmaapi] | 编译计划绑定 buffer 范围和动作，provider 执行，evidence 记录适用域 | backend 隐式猜测在非一致 cache 下不可靠 | 缺/错 hook 未被拒绝，或正确路径仍 stale | Core-3 |
| 非自证 trace feedback | StarPU/系统 profiling 与 Clockwork 可预测 serving [@augonnet2011starpu; @gujarati2020clockwork] | trace 只生成下一实验，不能提高原计划证据；新计划重新走 CECAP/AIRTOS gate | 在线自适应容易用同一 trace 选策略并宣称策略正确 | trace 直接升证或新计划绕过 gate | Core-4 |

新颖性措辞限定为：AIRTOS 提出的是证据、适用域、资源、WCET、lease、coherency 和恢复的联合治理层，而不是 EDF、DAG runtime 或 NPU 多租户本身。

## 4. 调度模型、独立 oracle 与平台

### 4.1 作业生成域

冻结 `schedule_scenarios_v1.jsonl`：

- 10,000 个可完全枚举的小场景：1-4 jobs、每 job 1-8 segments、1-4 resources；
- DAG 形状：chain、diamond、fork-join、independent branches；
- deadline：tight/medium/loose，包含同 deadline FIFO；
- NPU/DMA 默认非抢占，CPU/RVV 是否可抢占由合同显式声明；
- 到达模型：一次性、周期、sporadic；包含 admission horizon 内 reservation；
- 故障模型：无故障、模型内 cancel/reset overhead、模型外执行超界。

另建 5,000 个中大型 stress 场景（5-64 jobs、每 job 2-64 segments）用于性能和尾延迟，不用于穷举完备性结论。

### 4.2 非抢占 blocking 和 demand

每个资源的 admission 输入显式包含：

\[
B_r(J_i)=\max\{C_s+O_s\mid res(s)=r,\ d(job(s))>d_i,\ s\ may\ be\ active\}.
\]

对周期/偶发 reservation，至少检查资源级需求上界：

\[
dbf_r(t)=\sum_i \max\left(0,
\left\lfloor\frac{t-D_{i,r}}{T_i}\right\rfloor+1\right)C_{i,r},
\]

并加入 blocking、DMA/coherency、scheduler 和恢复开销。若 DAG 映射不能由该上界安全分解，则使用完整 `SimEDF+` 离散事件仿真，不用简单 utilization 替代。

### 4.3 独立 oracle

oracle 与 runtime 不共享 queue、event loop 或 admission 代码。小场景枚举所有合法 dispatch 次序与完成上界；对每次 AIRTOS 接纳/拒绝，比较 oracle 的安全集合。两者可共享输入 schema，但 parser 后立即转换为不同内部表示。

### 4.4 平台层次

| 平台 | 验证对象 | 不能推出 |
|---|---|---|
| Host 生产 runtime/离散事件 admission | package、DAG、EDF、lease、epoch 的有限模型一致性 | 真实 ISR/DMA/cache/timing |
| QEMU user-mode/RV64 | v2 大样本的跨 ISA loader、admission、调度与恢复决策复核 | RTOS 集成、系统外设、物理时界 |
| QEMU system/Cortex-M | Cortex-M3/M4/M7 四个 machine 完整重放 7,950 loader + 24,548 调度 corpus | 四套 RTOS BSP、物理外设/时界 |
| QEMU system/virt64 + RT-Thread Nano | RTOS 启动并完整重放 7,950 loader + 24,548 调度 corpus | 商品开发板、生产固件安全加固、物理时界 |
| 物理 RVV/K230 类目标 | ISR、DMA、cache、reset、timing、energy | 未测设备/频率/温度域 |

## 5. 基线与公平性

| 类别 | 基线 |
|---|---|
| 调度 | FIFO、fixed priority、global EDF、per-resource EDF without admission、HEFT、typed-DAG/federated、DREAM 可运行子集 |
| 多租户 | PREMA、Planaria、V10、MoCA、NeuCloud；按硬件是否支持 preemption/fission 分层 |
| 运行时抽象 | PTask、StarPU、Legion 的可移植 task/data subset |
| 准入 | package-only、provider+memory-only、schedule-only、完整 AIRTOS |
| 恢复 | 无 epoch、cookie-only、epoch+cookie、bounded reset/reinit+quarantine、自动 fallback 无重新准入、自动 fallback+完整 gate |
| coherency | implicit backend hooks、plan hooks without range validation、完整 plan-driven coherency |

所有调度方法使用相同 job arrivals、segment WCET/actual time、preemptibility、资源和恢复模型。需要不同硬件能力的 PREMA/Planaria/V10 不进入同一 speedup 表，只报告其适用域内结果。

## 6. 四个核心实验与内部子测试

| 核心实验 | 主问题 | 内部子测试 |
|---|---|---|
| Core-1 package 与原子联合准入 | 畸形/不合格计划能否安全拒绝且完全回滚 | S1 package 结构；S2 联合准入/并发 transaction |
| Core-2 调度、WCET 与开销 | `SimEDF+` 是否正确、条件 deadline 是否成立且成本可接受 | S3 DAG/EDF/oracle；S4 WCET；S8 开销 |
| Core-3 内存与 coherency | lease 和 CPU/device ownership 是否保持隔离 | S5 arena lease；S6 cache/DMA |
| Core-4 恢复、反馈与 HIL | 旧事件是否隔离、恢复是否闭合、物理长测是否发现反例 | S7 stale/quarantine；S9 trace 反馈；S10 HIL |

以下 S1-S10 是四个核心实验的内部测试模块，不作为十个独立论文实验分别下结论。

### 6.1 当前实验条件与四个正式执行包

截至 2026-08-05，正式软件包和 CanMV-K230-LP4 V3.0 物理合同均已冻结；短周期实体实验完成，二十四分钟持续运行实验以 1,440 秒、6,685,424 作业和三类错误为零通过，二十四小时长测后续补充。实验器具在安全端点失败时输出明确失败标记，主机审计器对所有样本数和零容忍端点进行复算。

| 核心实验 | 当前可用条件 | 开始正式实验前必须补齐 | 当前状态 |
|---|---|---|---|
| Core-1 package 与原子联合准入 | 软件/QEMU 两轮；实体 3,900 admission、23,400 diagnosis、health race、trust rotation、400,000 transaction | 实体 ISR 与提交同时竞争 | 冻结实体测试域 `SUPPORTED`；真实 ISR 竞争 `BLOCKED-HIL` |
| Core-2 调度、WCET 与开销 | 24,548 场景跨平台；实体全量重放、60,000 次生成算子时序、7 类控制开销 | 重新标定 WCET 并生成新计划；真实到达/provider trace | 调度实现 `SUPPORTED`；原计划硬实时和严格低开销 `FAILED-APPLICABILITY` |
| Core-3 内存与 coherency | 实体一百万 allocator attempt、一百万真实物理搬运、800 个可观察负对照 | 非对齐范围、其他设备引擎和其他芯片 | 当前 K230 合同内 `SUPPORTED` |
| Core-4 恢复、反馈与 HIL | 板上 700,000 stale、7,500 recovery/budget/gate、3,200 trace、300 device lifecycle；24 分钟/6,685,424 作业通过 | 真实 driver late IRQ、硬复位、真实标签、后续 24 h、功耗 | 板上状态机、设备重初始化和短时持续运行 `SUPPORTED`；其余 `BLOCKED-HIL` |

#### Core-1：package 完整性与原子联合准入实验

- **研究目的**：验证畸形或证据/域/资源/时限不合格的计划在任何执行副作用前被拒绝，并验证并发提交不产生半提交或 lease 泄漏。
- **实验平台**：Host-P0（x86_64 Linux 6.8.0-136、Python 3.12.3、GCC 13.3）运行 native C runtime、Python mutation generator 和 2-16 线程并发 harness；RV64 user-mode、RT-Thread/RV64 和四款 Cortex-M3/M4/M7 machine 对同一字节流复核 loader 决策。非法 package 只进入 parser/rejection gate，dispatch counter 必须保持零，不执行非法 payload。
- **实验数据**：v5 两轮各含 300 个合法 package、15 类结构/字段 mutation 各 300、105 类 pairwise 各 30，共 7,950；12 类准入缺陷单因子与 66 类 pairwise 各 300，共 23,400；另含 health race 各 300 和 2/4/8/16 线程各 100,000 transaction。产品生成路径对 valid、artifact digest mismatch/missing/path escape、verifier digest mismatch/missing 六类各 300，共 1,800；Host/RV64 各执行 old/dual/new/stale-root 共 1,500 个轮换判定。实体 ISR fault point 留给实板分支。
- **实验单位与规模**：package 结构和每个关键 admission mismatch 类各 300；合法对照每类至少 300；pairwise covering array 单列；2、4、8、16 提交线程分别竞争最后一个 lease 与临界 deadline，每配置 100,000 轮。
- **独立变量**：package-only、provider+memory-only、schedule-only 和完整 AIRTOS；串行 transaction 与 generation-guarded 乐观 transaction。
- **主端点**：malformed/unsafe admission、partial commit、active lease overlap 和拒绝后 leak 均为 0；diagnostic macro-F1>=0.95。false rejection 和 admission p99 为次端点。
- **执行步骤**：冻结合法 package 与 trust bundle；生成单因子和组合 mutation；在 dispatch counter 为零时运行 loader/session/submit；对每个锁外 simulation 点注入 generation/provider-health 竞争；记录线性化历史；用独立 shadow state 检查 job、lease、session busy 和 schedule generation。
- **必须保存**：mutation diff、AEG/plan/evidence/policy/trust hash、逐谓词 decision、线程调度 seed、线性化 history、lease/job before-after、rejection reason 和 crash log。
- **统计**：安全类别逐类 exact interval；并发配置分别报告，不合并线程数；latency 用 median/p95/p99 和 bootstrap CI。
- **失败规则**：错误 binding/verifier/resource/domain 进入 session、任一 mismatch 被接纳、commit 后 job/lease 不一致或拒绝后资源残留，均为 `SAFE-ENDPOINT-FAILED`。
- **预取结论**：两轮软件结果支持冻结 mutation/admission 域内零错误接纳、artifact/verifier 材料 fail-closed、trust-root 轮换和 transaction 的 overlap/partial commit 为零；不能外推到未覆盖组合、物理 ISR 或吞吐性能。

#### Core-2：异构 DAG 调度、条件 deadline 与控制开销实验

- **研究目的**：验证 runtime 与独立 oracle 对一般 DAG、非抢占 blocking、running residual 和 reservation 的判断一致，并测量该安全检查的成本。
- **实验平台**：Board-P2 CanMV-K230 首先用生产 runner 生成 CPU/RVV/真实 provider 的 measured WCET、arrival 和控制开销；Host-P0 随后把这些只读实测表输入 native C `rt_ai_sim_edf` 与独立 Python oracle，验证有限模型一致性；QEMU-P1 运行同源 RT-Thread 固件并重放板上捕获的 arrival/IRQ 序列，扩大 tie、timeout 和队列路径覆盖；最后 Board-P2 按冻结到达 trace 实际执行并检验 deadline。Host、QEMU 和板测时间分表，只有 Board-P2 支撑 WCET/deadline/开销主张。
- **实验数据**：冻结 JSONL 包含 10,000 small、5,000 stress、2,048 bounded Cartesian 和 30 seed x 250 multiseed，共 24,548。固定 cost palette 标记为 `cecap_plan_cost_palette_model_domain`，不是板测 WCET；后续 timing corpus 必须由真实 CECAP DAG、Board-P2 WCET/arrival/provider trace 派生。
- **实验单位与规模**：24,548 个场景在 Host/RV64 C、独立 Python oracle、RT-Thread/RV64 和四款 Cortex-M machine 重放；S8 每个微操作 10 warm-up、每批 1,000 measurement、30 batch。
- **独立变量**：FIFO、fixed priority、global EDF、per-resource EDF without admission、完整 `SimEDF+`；actual/WCET 比率 `q={0.5,0.8,1.0,1.05,1.2}`；预留与未预留 sporadic arrivals。
- **主端点**：正式小场景的 oracle disagreement、dependency/EDF violation 和 model-valid deadline miss 均为 0；控制开销 p99 小于 `min(1 ms,0.05*D_min)` 且 steady-state control overhead 小于最短 segment WCET 的 5%。
- **执行步骤**：软件阶段以独立 oracle 逐场景比较 admit/reject 和所有 job finish，并在五个 system machine 重放同一 corpus；`q` 分层验证 WCET 时间隔离边界。物理阶段再以 Board-P2 实测 DAG/WCET/arrival/provider trace 生成 confirmatory corpus 并重放冻结 arrivals。
- **必须保存**：scenario、oracle/runtime trace、所有 tie order、WCET/source、reservation、predicted/actual finish、baseline decision、cycles/code/RAM 和失败最小化反例。
- **统计**：正确性逐场景判定；stress 报 admission ratio、miss、response p95/p99 和按 seed bootstrap CI；`q>1` 与未预留到达不得混入 model-valid 分母。
- **失败规则**：模型前提满足时任一 disagreement/miss 即 H2/H3 失败；仅候选按时但旧 job 超时算 false admission；开销超阈值只撤回低开销主张。
- **预取结论**：两轮 24,548 场景在 Host/RV64/RT-Thread/Cortex-M3/M4/M7 均零 mismatch，`q<=1` 零 miss且`q>1`暴露边界，可写“时间隔离实现与冻结软件模型一致”；没有 measured WCET、实际 arrivals 和板级 dispatch 时不能写 hard real-time 或低开销结论。

#### Core-3：arena lease 隔离与 CanMV-K230 coherency 实验

- **研究目的**：验证多 session 内存生命周期不交叉，并验证计划指定的 clean/barrier/invalidate 范围在真实非一致 DMA 路径上保持数据一致。
- **实验平台**：Host-P0 通过生产 allocator 路径运行 2-16 线程 lease transaction，并用独立 shadow/canary oracle 检查内存隔离；QEMU-P1 运行同源固件，验证 coherency action/range 的 parser、拒绝和调用顺序；Board-P2 CanMV-K230-LP4 V3.0 运行真实 DMA/cache ownership 并承担全部数据一致性主端点。P2 必须先确认 DMA engine、cache-line size、地址域和 clean/invalidate/barrier API；若负对照不能稳定产生 stale 差异，物理 coherency 分支标为 `BLOCKED-HIL`。
- **实验数据**：当前两轮各冻结 2/4/8/16 Host 线程、共 1,000,000 allocator attempt；run1 成功 878,058 次、run2 成功 908,918 次，并记录 overlap、canary、cross-session diff、generation race 和 rollback leak。生产 `coherency.c`/`plan_select.c` 在 Host、RV64 user、RT-Thread/RV64 和四个 Cortex-M machine 上各执行 1,000,000 case 与 1,171,675 个预期拒绝检查，全部 failure=0；仍没有真实 DMA descriptor/output reference。
- **实验单位与规模**：Host 至少 `10^6` 次 create/destroy/submit/fault 操作，覆盖 2-16 线程、碎片、rollback 和合法 alias；QEMU 至少 `10^6` 次同源 coherency command/path replay；CanMV-K230 至少 `10^6` 次真实 DMA transfer，当前持续运行至少 24 分钟，后续扩展到 24 小时。
- **物理平台合同**：CanMV-K230-LP4 V3.0；冻结 cache-line size、DMA engine/channel、buffer 地址域、alignment、CPU/RVV 频率、固件/image hash、device serial、温度和供电。若平台实际 coherent 或无法观测 cache ownership，则物理分支只能验证 hook/transfer，不支持非一致 coherency 主张。
- **独立变量**：无 lease、session-only arena、generation lease；缺 clean、缺 barrier、缺 invalidate、错误 range/对齐、DMA 完成前读取和完整 plan-driven path。
- **主端点**：active overlap、canary corruption、cross-session diff、rollback leak 和完整 coherency path reference diff 均为 0；错误 coherency 条件必须被拒绝或产生预期可观察负结果。
- **执行步骤**：以独立 shadow allocator 驱动生产 allocator 的同一冻结操作序列；在所有 lease 周围放置 canary；每个 transaction fault point 注入失败；QEMU 重放真实 coherency command 检查调用序列；板上先以缺 clean/invalidate、错误 range 和完成前读取等负对照验证观测灵敏度，再执行 CPU写->clean/barrier->真实 DMA->invalidate->CPU读，并分层覆盖真实 tensor size/range/alignment。
- **必须保存**：allocation/lease trace、shadow map、canary、输入/设备/输出 hash、cache action/range、DMA descriptor/completion、板卡合同、温度/频率和最小失败样例。
- **统计**：安全端点逐线程数、size/range 类别单列；fragmentation/utilization 和 cycles 报 ECDF/CI，不与零容忍端点合并。
- **失败规则**：任一跨 lease 污染或完整物理路径差分即 H4/H5 失败；Host/QEMU 通过但板测失败时必须报告外部效度失败，不能选择性采用虚拟结果。
- **预取结论**：两轮多线程 allocator 支持 Host 软件模型中的 lease 隔离，七个环境的正式 replay 支持 coherency action/range/hook/ownership 命令语义一致；CanMV-K230 是否能提供有效非一致 DMA 证据仍必须由平台合同和物理负对照灵敏度确认。

#### Core-4：预算恢复、fallback、可归属反馈与长时 HIL 实验

- **研究目的**：验证 cancel/reset 前的迟到事件不能完成新作业、恢复在预算内闭合、fallback 必须重新准入，并验证 trace 能选择下一实验但不能直接升证。
- **实验平台**：Board-P2 CanMV-K230 通过生产 driver/provider 路径执行真实 cancel/reset/reinit、迟到 IRQ、fallback 和持续运行实验；当前轮次为 24 分钟，24 小时轮次后续补充。QEMU-P1 运行同源 RTOS/driver，并把 Board-P2 捕获的 IRQ/reset trace 通过生产 ISR/completion 入口高次数重放，以扩大 epoch-cookie 状态空间覆盖；Host-P0 只运行 JSON Schema/metrics、独立 trace oracle 和 root-cause classifier。P2 的 reset 方法必须可恢复且有厂商/driver 时界依据，不允许用替身 provider 或未验证的电源/flash 操作代替。
- **实验数据**：每轮 Host/RV64 各有七类 stale 各 100,000；五类 legacy recovery 各 300；`K_r={1,2,3,5}` x 四类故障 x 300；四种 fallback gate 各 300；八类基础 trace 各 100；另有八类各 300 的噪声/ring-wrap 稳健性 corpus 和 cookie wrap。基础 corpus 的 macro-F1/top-3 为 1.0/1.0；稳健性 corpus 每例注入 65-128 个干扰事件并全部强制 wrap，macro-F1/accuracy=1.0/1.0。这些仍是生产状态机的受控 fault injection，不是物理 seed 或真实工作负载标签。
- **实验单位与规模**：Board-P2 对每种可安全触发的 cancel/reset/reinit/迟到 IRQ 类至少采集 30 个独立物理 seed episode，并完成各恢复 failure 类 300 episode；每个物理 seed 在 QEMU 同源 ISR 路径扩展到每种 stale/duplicate 类至少 `10^5` 次 replay；`K_r={1,2,3,5}`；八类 root-cause 各 100 个真实 fault episode，共 800；当前 CanMV-K230 持续运行同时满足 24 分钟和 `10^6` jobs，后续混合负载轮次同时满足 24 小时和 `10^6` jobs。无法安全触发的类别标 `BLOCKED-HIL`，不得生成替代数据。
- **前置实现硬门槛**：恢复切换 fallback 前重新执行 evidence/provider/active-lease/`rt_ai_sim_edf` 联合准入，并输出可审计 trace；该软件门槛已完成，实体 confirmatory Core-4 仍须先绑定真实 driver fault seed 与设备时界。
- **独立变量**：无 epoch、cookie-only、epoch+cookie、预算恢复+quarantine、fallback 不重新准入、fallback 完整 gate；反馈比较无反馈、total-latency-only、人工规则和 AIRTOS trace+ADAM。
- **主端点**：stale acceptance、wrong completion、超预算未 quarantine、unsafe fallback 和 new-plan gate bypass 均为 0；root-cause macro-F1>=0.90、top-3 recall>=0.95。HIL 的同类安全端点同样零容忍。
- **物理步骤**：冻结 CanMV-K230 cancel/reset/reinit 实现和时界依据；写前核对 serial/image/plan；受控注入 timeout/reset/迟到 IRQ；导出 JSON trace；运行 trace classifier 选择新实验；生成新 plan hash并重新经过 CECAP verifier/AIRTOS admission；完成长时混合负载和 readback。
- **必须保存**：device contract、fault schedule、epoch/cookie/plan trace、reset timing、quarantine/fallback decision、classifier labels/scores、新旧 plan/evidence、gate record、24 分钟及后续 24 小时环境和全部 serial logs。
- **统计**：stale/故障类别逐类 exact interval；恢复时间报告 bound violation 和分布；classifier 提供 confusion matrix、macro-F1/top-k bootstrap CI；HIL 按 model-valid/invalid deadline 分层。
- **失败规则**：任一旧事件改变新状态、达到 `K_r` 未闭合、fallback 未完整准入、trace 直接升证或长时安全端点非零，均优先于性能结果。
- **预取结论**：两轮软件实验支持七类 stale 状态不变性、`K_r` 恢复闭合、fallback gate，以及冻结 trace 在噪声/ring-wrap 下的分类稳健性；真实 driver/device fault seeds、恢复时间界、真实标签外部效度和单板 HIL 仍是决定性缺口。

### 6.2 全文声明覆盖矩阵

| 核心实验 | 唯一负责的 RQ/假设 | 覆盖的创新与理论 | 覆盖的实现对象 | 允许进入摘要/结论的主张 | 未通过时必须删除或降级的主张 |
|---|---|---|---|---|---|
| Core-1 | H1 | 证据/域/资源/WCET 联合准入与 lease-schedule 原子 transaction | AEG/evidence loader、trust bundle、submit transaction、rollback | 不合格计划被安全拒绝，接纳/拒绝不产生半提交 | “证据边界准入”“原子联合准入” |
| Core-2 | H2、H3、H7 | segment DAG 多资源治理、per-resource EDF、条件 deadline theorem | `SimEDF+`/dbf、runtime queues、独立 oracle、WCET/开销 measurement | DAG/EDF 实现与冻结模型一致；模型有效场景无 miss；开销达到阈值时可称可用 | “调度实现一致”“条件 deadline safety”“低开销”中失败的对应一项 |
| Core-3 | H4、H5 | lease 不相交和 plan-driven coherency 条件定理 | allocator/shadow/canary、QEMU command replay、CanMV-K230 真实 DMA/cache | 多 session 在测试域内隔离；物理条件满足时数据 ownership 路径一致 | “内存隔离”“物理 coherency”中的对应一项；Host/QEMU 结果不能保留物理措辞 |
| Core-4 | H6、H8、H9 | epoch-cookie、预算恢复/quarantine、非自证 trace feedback | recovery/fallback gate、JSON trace/classifier、CanMV-K230 reset/IRQ/HIL | stale event 被隔离、故障有界闭合、fallback 重新准入、反馈不自证、有限 HIL 未见反例 | “失败闭合”“schedule-safe fallback”“反馈有效”“长时稳定”中的对应一项 |

全文覆盖规则：联合准入、调度实现一致性、内存租约和当前 K230 合同内的真实缓存一致性已有实体直接证据；板上状态机迟到隔离、恢复预算、回退门和真实设备重初始化也已完成。平均延迟或接纳比例不能补偿任一安全失败。原计划硬实时期限与严格低开销阈值被实体数据否定；二十四分钟持续运行只能形成短时证据，真实驱动迟到中断、硬复位、真实故障标签、功耗和后续二十四小时长测继续标记为 `BLOCKED-HIL`。

### 子测试 S1：AEG/package 结构安全

**变体**：magic/version、截断、segment count、重复 ID、future/missing dependency、环、resource enum、arena overflow、整数 wrap、错误 hash、未知必需字段和 oversized length；每类 300 个。

**条件**：直接反序列化、AEG v1、扩展 evidence/domain loader。

**指标**：malformed acceptance、legal false rejection、parser cycles、peak stack/heap、拒绝原因。

**决策**：越界 segment、整数 wrap、错误 binding 或环进入 session 任一发生，结构安全实现声明失败。fuzz crash 即使未进入 session 也作为 parser robustness failure 单列。

### 子测试 S2：联合准入与原子回滚

#### S2-a：单因子与组合矩阵

对 target/model hash、shape/dtype/layout、ABI、每个 evidence obligation、provider、arena、WCET/deadline、coherency action、device health 分别构造 match/mismatch，每类 300 个；再以 pairwise covering array 生成组合错误。

#### S2-b：并发 transaction

使用 2-16 个提交线程竞争最后一个可用 lease 和相同 deadline slack，重复 100,000 轮。在线性化点记录 lease reservation、schedule snapshot 和 commit/rollback。

**指标**：unsafe admission、false rejection、diagnostic macro-F1、partial commit、active lease overlap、admission latency。

**决策**：H1 要求关键 mismatch unsafe admission=0；并发 partial commit/overlap=0。schedule-only 或 memory-only 通过不代表完整准入成功。

### 子测试 S3：DAG、EDF、blocking 与 admission oracle

对 10,000 个小场景运行所有调度基线与完整 AIRTOS，逐事件比较独立 oracle。明确加入两类最小反例：其一是“较晚 deadline 的长非抢占 NPU segment 已 active”，验证 blocking；其二是“已接纳较晚 deadline 作业尚在队列，新候选 deadline 更早且自身可按时、但插队后使旧作业超时”，验证 admission 必须重验全部已接纳 deadline，而非只判断候选 finish。

**指标**：dependency violation、EDF-order violation、admission confusion matrix、deadline miss、response time、p95/p99、utilization、queue wait、oracle finish-time error。

**决策**：H2 要求依赖/顺序错误为 0；H3 要求所有小场景 admission 与 oracle 一致。平均 miss ratio 更低不能补偿任一规则违反。

### 子测试 S4：WCET、到达模型与条件 deadline safety

#### S4-a：执行时间比例

对 actual/WCET 比率 (q\in\{0.5,0.8,1.0,1.05,1.2\}) 运行固定场景；前三组满足模型，后两组故意违反。另注入未预留 sporadic arrivals。

#### S4-b：分层解释

- `q<=1` 且 arrivals 已预留：任何 deadline miss 是 admission/runtime 实现反例；
- `q>1`：miss 说明该 WCET 不适用于测试域，不直接反驳条件定理；
- 未预留 arrival：用于证明“只看当前队列”的方法不足，不纳入 H3 支持样本。

报告 false admission、deadline miss、admission ratio、idle time、WCET pessimism 和预测-实际完成差。物理板 WCET 表必须绑定频率、温度、固件、cache 和 contention 状态。

### 子测试 S5：arena lease、碎片与跨 session 隔离

执行至少 (10^6) 次确定性随机 create/destroy/submit 操作，覆盖不同 arena size、最大 session 数、碎片化、串行复用、并发隔离、越界 offset、合法 alias 和 admission rollback。

每个 lease 前后放置 canary，并以独立 shadow allocator 检查区间。生产 provider 只允许访问声明 range；越界负例通过真实 package range mutation 触发 loader 拒绝，并用 Host guard page/QEMU MMU 检查错误接受后的内存保护，不编写替身 provider。

**指标**：active overlap、canary corruption、cross-session reference diff、accepted sessions、SRAM utilization、fragmentation、allocation cycles、false rejection。

**决策**：任一 active overlap、跨 session corruption 或拒绝后 lease 泄漏否决 H4。更高 utilization 不是安全端点。

### 子测试 S6：cache/DMA coherency

**场景**：缺 clean、缺 barrier、缺 invalidate、错误 range、非 cache-line 对齐、DMA 完成前读取、双向 ownership、正确动作；覆盖 1 B 到最大 tensor 的边界 size。

**层次**：Host 生产路径验证 action/range 规则；QEMU 同源固件重放板上捕获的 coherency command/IRQ trace；CanMV-K230 以真实 DMA、物理负对照和 reference path 运行至少 (10^6) 次 transfers 且至少 24 小时，两条件都满足才能停止。

**指标**：stale read/write、reference diff、hook sequence/range error、barrier cycles、latency、energy。

**决策**：错误动作应被 loader/admission 拒绝或在负面对照中产生可观察失败；完整路径在声明域内差分为 0 才支持 H5。若硬件天然 coherent，不能用该平台支持非一致 cache 主张。

### 子测试 S7：timeout、cancel、reset、stale event 与 quarantine

#### S7-a：注入类别

正常完成、重复 IRQ、cancel 后迟到、reset 后迟到、错误 device、错误 epoch、错误 cookie、同 epoch 重复、cookie 接近 wrap、cancel failure、reset failure、reinitialize failure、连续超预算故障。每个 stale/duplicate 类至少 (10^5) 次；恢复失败类各 300 episode。

#### S7-b：设备合同

每个 provider 在运行前冻结 `delta_cancel`、`delta_reset`、`delta_reinit`、最大中断生存期、cookie 位宽/复用隔离和 \(K_r\)。当前代码已经消费这三个 timeout 和 `max_reset_attempts`。若时界没有硬件/driver 依据，结果只能称 stress measurement，不能支持有界恢复。

**条件**：无 epoch、cookie-only、epoch+cookie、预算恢复/quarantine、自动 fallback 不重新准入、自动 fallback 通过 evidence/provider/`SimEDF+` gate。

**指标**：stale acceptance、wrong-job completion、post-reset contamination、cancel/reset latency、bound violation、reset count、quarantine precision/recall、后续 fallback。

**决策**：任一 stale event 改变新 job 状态即 H6 失败；模型内恢复超过冻结时界、达到 \(K_r\) 未 quarantine、或 fallback 未重新验证仍破坏任一 admitted deadline/evidence/provider 条件，也判 H6 失败。当前代码已实现并在软件正式规模验证预算、fallback dispatch 及 evidence/provider/lease/`SimEDF+` gate；尚缺生产 fault seed 与物理时界验证。

### 子测试 S8：运行时开销

分别微测 load/validation、admission simulation、queue push/pop、lease、cache hook、ISR completion、trace、cancel/reset transition。每配置 10 次 warm-up、至少 1,000 次微测和 30 个端到端 batch；报告 cycles、median、p95/p99、代码大小、RAM、最大锁/关中断时间、吞吐和尾延迟。

逐项关闭 evidence check、simulation、trace、epoch check 测归因，但危险消融不接物理关键负载。H7 使用完整配置的相对 deadline/segment 预算，不用桌面主机绝对时间支持嵌入式结论。

### 子测试 S9：trace 到下一实验且不自证

建立带标签场景：queue contention、DMA dominant、kernel dominant、arena pressure、WCET miss、reset storm、coherency fault 和无回归基线，每类至少 100 个。

**条件**：无反馈、total-latency-only、人工规则、AIRTOS trace + ADAM experiment selection。

**指标**：root-cause macro-F1、正确实验 top-1/top-3、time-to-validated-improvement、无效重编译、回归、new-plan verifier/admission bypass。

**决策**：达到 H8 分类阈值且 bypass=0 才支持闭环主张。即使下一计划性能改善，仍必须有新的 plan hash、CECAP evidence 和 AIRTOS admission 记录。

### 子测试 S10：物理 HIL 长时稳定性

**执行门槛**：唯一设备绑定、写前确认、image readback hash、plan hash、run ID、串口归属和环境记录均通过后开始。混合 workload 至少运行 24 小时且至少 (10^6) jobs；两个条件都满足才停止。

负载覆盖 CPU/RVV、可用 NPU、DMA、多个 session、不同 deadline、周期性 cancel/reset 和受控 stale event。记录频率、温度、电源、固件、设备 serial、镜像和仪器校准。

**主安全端点**：错误 job completion、stale acceptance、跨 lease corruption、coherency diff、错误 fallback、不可恢复死锁，均为零容忍。

**报告**：job 数、有效运行时长、deadline miss 按 model-valid/model-invalid 分层、p99、reset/quarantine、stale rejected、memory peak、温度、频率、功耗。有限长测只能发现反例，不能证明无限时间可靠性。

## 7. 样本量、统计与停止规则

- 准入/loader 关键负例每类 300 个，零事件报告单侧 95% Clopper-Pearson 上界。
- stale/duplicate event 每类至少 (10^5) 次，仍以事件类型逐类报告；零观察不替代状态机证明。
- 调度 exact/oracle corpus 固定 10,000 小场景；H2/H3 要求逐场景一致，不使用平均值放宽。
- 随机 stress 使用至少 30 seed；延迟和开销报告 median、IQR、p95/p99 及分层 bootstrap 95% CI。
- deadline miss、admission 和 recovery 比例报告 exact/binomial interval；多组探索比较使用 BH-FDR 0.05。
- 不因结果有利提前停止。关键安全失败可停止危险物理运行，但失败样本必须保留并计入主端点。
- 基础设施断电与协议无关的仪器失败标为 censored 之前，必须由独立日志证明；软件 hang、timeout 和 reset 不能排除。

## 8. Artifact 和 schema

```text
results/airtos/<protocol_hash>/<experiment>/<platform>/<scenario>/<condition>/<seed>/
  run.json
  package.aeg.sha256
  plan.json
  evidence.jsonl
  device_contract.json
  wcet_table.json
  arrivals.jsonl
  admission.jsonl
  schedule_trace.jsonl
  irq_trace.jsonl
  lease_trace.jsonl
  coherency_trace.jsonl
  outputs.sha256
  measurements.csv
  environment.json
```

每条 trace 至少含 monotonic logical sequence、timestamp、run ID、plan hash、job、segment、resource、epoch、cookie、event、status。ring wrap 后导出必须按逻辑 sequence 排序；`complete timestamp=0` 视为数据不合格。

## 9. 结果表与图占位

**表 1：联合准入和调度正确性**

| 条件 | n | unsafe admission | false rejection | dependency error | EDF error | oracle disagreement |
|---|---:|---:|---:|---:|---:|---:|
| v5 final_run1/2：x86_64/RV64 | loader 7,950/platform/run；diagnosis 23,400/platform/run | 0 | 0/300 legal | 0 | 0 | 0/24,548/platform/run |
| v5 final_run1/2：RT-Thread/RV64 + Cortex-M3/M4/M7 system machine | loader 7,950/machine/run；schedule 24,548/machine/run | 0 | 0/300 legal | 0 | 0 | 0/24,548/machine/run |

**表 2：资源和恢复安全**

| 条件 | lease overlap | corruption | coherency diff | stale accepted | wrong completion | bound violation | quarantine F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Host/RV64 software model | 0/878,058、908,918 successful leases | 0 canary/differential | 命令语义 0/1,000,000/environment/run；物理 diff `BLOCKED-HIL` | 0/700,000/platform/run | 0 | 0/4,800 budget episode；物理时界未测 | 基础 macro-F1/top-3=1.0/1.0；噪声/wrap macro-F1=1.0 |

**表 3：实时性与开销**

| platform/workload | WCET pessimism | admission ratio | valid miss | p99 response | admission p99 | control overhead | RAM/code |
|---|---:|---:|---:|---:|---:|---:|---:|
| Host x86_64 软件路径 | 固定 palette，非板测 | `SimEDF+` 依 scenario | 0/4,178，`q<=1` | 仅离散模型 | SimEDF+ 71-72 ns 批 p99 中位数 | 仅 Host，H7 不判定 | text/data/bss 30,855/992/16 B |
| CanMV-K230 实体板 | `BLOCKED-HIL` | `BLOCKED-HIL` | `BLOCKED-HIL` | `BLOCKED-HIL` | `BLOCKED-HIL` | `BLOCKED-HIL` | `BLOCKED-HIL` |

预注册图：Fig. 1 admission predicate confusion matrix；Fig. 2 actual/WCET sensitivity；Fig. 3 deadline miss-admission-pessimism tradeoff；Fig. 4 stale event survival/state transition；Fig. 5 lease fragmentation ECDF；Fig. 6 trace root-cause confusion matrix。

## 10. 条件化结论模板

**H1/H2/H4/H6 支持时**：

> 在预注册 package、联合准入、DAG、lease 和故障注入域内，AIRTOS 未出现关键错误接纳、依赖违规、跨 session 污染或 stale completion，并满足逐类零容忍门槛。结果支持对应实现不变量，但仍相对于 parser、oracle、provider 和故障模型成立。

**任一安全假设不支持时**：

> 观察到至少一个关键 unsafe admission、依赖错误、内存污染或 stale completion，因此对应安全实现声明不成立。该反例优先于所有平均 latency 或吞吐改善。

**H3 支持时**：

> 对所有满足 actual<=WCET、预留到达和模型内故障前提的冻结场景，AIRTOS 与独立 oracle 一致且未出现 deadline miss。这一结果支持 `SimEDF+` 的实现一致性和测试域内前提，不是对任意未来负载的无条件 hard real-time 证明。

**H3 不支持时**：

> 在定理前提被标记为满足的场景中仍出现 oracle disagreement 或 deadline miss，因此当前 admission 实现不能支持 deadline-safety 主张。若 only actual>WCET 组失败，则结论应是 WCET 模型适用域失效。

**H5 支持/不支持**：只有 CanMV-K230 真实 DMA/cache 路径和可观察负对照均有效、完整路径零差分时才写支持；仅 Host/QEMU 通过时只能写“规则和同源命令路径一致”，不写数据一致性已验证。

**H7-H9**：达到阈值时分别主张测试平台内的开销可接受、反馈选择有效和长时反例未观察到；未达到时直接撤回对应效率/闭环/稳定性主张，禁止写“接近显著”或由 QEMU 外推。

## 11. 执行前检查清单

已勾选项表示“代码对象已存在且对应定向验证可执行”，不是论文假设已经得到实验支持。

- [x] AEG/package v2 携带 evidence/domain hash、WCET、fallback、reservation、recovery 和 segment coherency range，并有结构 loader
- [x] `rt_ai_session_create_v2` 逐项核对 model/target/runtime/provider ABI、obligation/scope/artifact/verifier hash 和 verifier allowlist
- [x] 产品 trust 生成前现场验证 artifact/verifier 文件存在、SHA-256 一致且路径不逃逸 evidence root；Host/RV64 trust-root 轮换通过
- [x] `rt_ai_submit_async_v2` 实现 domain/provider/deadline 检查及 generation-guarded lease/job 原子提交
- [x] `rt_ai_sim_edf` 重验全部 snapshot job deadline，纳入 EDF/DAG、active residual、coherency/recovery cost 和 reservation/dbf
- [x] 独立 Python oracle 与 C simulator 对 10,000 个一般 small DAG 和 5,000 个 stress 场景逐例一致，并保存 JSONL/CSV/hash
- [ ] 用真实 CECAP DAG、CanMV-K230 measured WCET/arrival/provider trace 生成 timing-confirmatory corpus
- [x] 实现 cancel/reset/reinit poll、三个 timeout、`max_reset_attempts`、quarantine 和自动 fallback dispatch
- [x] fallback 在恢复后重新执行 evidence/provider/active-lease/`SimEDF+` 联合准入
- [x] trace completion 时间、uint64 sequence、ring-wrap chronological snapshot 和 dropped 计数已实现
- [x] C/JSON trace exporter、event-level plan ID、v2 Schema 验证和基础 latency/status metrics 已实现
- [x] CECAP trace feedback 只生成 candidate experiment，禁止直接升证或修改运行计划
- [x] 1,000,000 次随机 lease 状态序列具有 shadow map，并检查 generation 竞争
- [x] 非一致 cache 最小模型具有完整路径和缺 clean/invalidate 负对照
- [x] 生产 coherency 命令状态机已在 Host、RV64 user、RT-Thread/RV64 和 Cortex-M3/M4/M7 各完成 1,000,000 case 正式 replay
- [x] 完成 2-16 线程 transaction、15 类 package mutation 各 300、七类 stale 各 100,000 和五类恢复 fault 各 300 的软件实验
- [x] 完成 canary/跨 session reference differential、pairwise mutation 和软件逐 fault-point/generation 检查
- [ ] 采集生产 driver/device 的物理 fault seed
- [x] 完成 800 个基础反馈根因场景、2,400 个噪声/ring-wrap 场景、macro-F1/top-k 和端到端新计划 gate
- [ ] CanMV-K230 具有 PCB revision/device/probe serial 唯一绑定、readback、真实 WCET、DMA/cache 测试和仪器校准
- [x] 完成 24 分钟且 `10^6` jobs 的当前 HIL，生成协议哈希并登记时长变更，发布原始 trace 和失败样例
- [ ] 后续完成 24 h 且 `10^6` jobs 的扩展 HIL

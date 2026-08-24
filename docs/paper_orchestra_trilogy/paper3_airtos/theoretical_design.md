# Paper 3 理论设计：AIRTOS

> 工程实施、联合准入与恢复接口、实验素材生产、逐实验输入输出与结论判定见 [实验实施蓝图](implementation_blueprint.md)；冻结假设、样本量与统计规则见 [预注册实验协议](experiment_protocol.md)。

## 1. 论文题目

**英文题目**

> AIRTOS: Evidence-Bounded Admission, Resource Governance, and Recovery for Heterogeneous Edge AI

**中文题目**

> AIRTOS：面向异构边缘 AI 的证据边界准入、资源治理与故障恢复

题目强调 AIRTOS 不是一个通用新内核，也不是简单把推理函数放进 RTOS 线程。它研究的是编译计划进入实时运行环境之前和执行期间的三个系统问题：能否接纳、如何治理共享资源、发生超时和迟到事件后如何恢复。

### 1.1 论文研究设计摘要

| 必须体现的内容 | AIRTOS 的具体内容 |
|---|---|
| **真实行业难点** | EDF、异构 DAG runtime 和 NPU 多租户已经成熟，但边缘设备常含非抢占 NPU/DMA、有限连续 SRAM、非一致 cache 和 reset 后迟到 IRQ；这些运行状态通常没有与编译计划的 evidence/domain 联合进入 RTOS admission [@liu1973scheduling; @rossbach2011ptask; @choi2020prema; @kim2023dream; @linux2026dmaapi] |
| **核心创新** | 把 package binding、domain、evidence、provider、memory、coherency、schedule 和 recoverability 合成准入谓词；lease 与 schedule 原子提交；用 epoch-cookie 拒绝旧完成；trace 只产生下一实验而不自证 |
| **数学理论** | 定义 \(Admit\)、含非抢占 blocking/arrival reservation 的 \(SimEDF^+\)、per-resource EDF、lease 不相交、coherency ownership 状态机、epoch-cookie `Accept` 和有界恢复；结论全部绑定 WCET/到达/硬件前提 |
| **实验验证** | Core-1 验证 package 和原子联合准入；Core-2 用独立 oracle、WCET 失配和微测验证调度边界及开销；Core-3 验证 lease 与物理 coherency；Core-4 以 stale event、反馈任务和当前 24 分钟/\(10^6\) jobs HIL 验证短时恢复边界，后续用 24 h HIL 补充长时证据。完整方案见 [预注册协议](experiment_protocol.md) |
| **突出贡献** | 不是新 EDF 或新 NPU scheduler，而是一个让异构 AI 计划依据证据、适用域、内存、时限和设备代次被原子接纳、拒绝、恢复与追踪的 RTOS 治理层 |
| **成立边界** | hard deadline 只在 actual<=WCET、blocking/arrival/recovery 均被保守覆盖时成立；Host/QEMU 不证明真实 cache/DMA 或板级时界；有限 HIL 只能发现反例，不能证明无限时间可靠性 |

## 2. 当前行业难点

### 2.1 AI 作业不是一个独立 RTOS 线程

一次推理可能由 CPU、RVV、NPU 和 DMA 多个 segment 组成，segment 之间形成 DAG，并共享 arena、cache 和设备。只调度提交线程不能表达设备队列、异步完成、跨资源依赖和 tensor 生命周期。

### 2.2 deadline 与异构非抢占资源耦合

CPU 任务可能可抢占，而 NPU/DMA command 往往长时间非抢占。单一全局优先级不能直接约束每个资源的排队，也不能判断某个新作业是否会使已有作业 miss deadline。没有 WCET 或保守执行界时，“使用 EDF”本身不等于 deadline safety。

### 2.3 SRAM 紧张且内存错误跨模型传播

边缘 SoC 常由多个模型共享有限连续内存。模型单独能运行不代表并发能运行；静态总和又会拒绝可串行复用的组合。运行时需要同时管理 session lease、segment offset、生命周期、alignment 和并发隔离。

### 2.4 DMA、cache 与所有权转移难以靠 API 约定保证

CPU 与设备非一致 cache 下，clean/invalidate、barrier 和 DMA 完成顺序是正确性的一部分。如果这些动作没有随 plan segment 显式表达并由 runtime 执行，数值错误可能只在物理板或高负载时出现。

### 2.5 超时、取消和复位会产生迟到完成事件

设备 reset 后，旧中断可能晚到；取消失败后，旧 command 可能仍在执行；重复 IRQ 也可能发生。如果完成事件只用 job pointer 或 device ID 匹配，旧事件可能完成一个新作业，造成状态和内存污染。

### 2.6 编译计划可能合法，但不适合当前运行状态

计划可能 target hash 正确，却要求当前不可用的 backend、过大的 arena、更高证据策略，或者只适用于不同 shape/ABI。编译时正确不能替代运行时对当前状态的准入判断。

### 2.7 运行 trace 与编译优化脱节

queue wait、DMA wait、kernel time、arena pressure、reset 和 deadline miss 指向不同根因。传统 profiling 通常只展示数据，不能形成带 run ID 和环境绑定的后续编译实验，更不能防止在线 trace 自行提升计划证据。

### 2.8 行业真实性证据：文献与当前仓库的交叉核对

| 现实问题 | 外部行业证据 | 当前仓库直接观测 | 对论文主张的约束 |
|---|---|---|---|
| EDF/DAG/NPU 多租户不是新问题 | Liu-Layland/processor demand、PTask/StarPU/Legion、PREMA/Planaria/DREAM 已处理实时调度、异构任务和多模型资源共享 [@liu1973scheduling; @baruah1990sporadic; @rossbach2011ptask; @augonnet2011starpu; @choi2020prema; @ghodrati2020planaria; @kim2023dream] | `resource_queue.c:3-24` 已按 deadline 稳定排序；`coordinator.c:21-36` 只在 predecessor done 后入队 | AIRTOS 不能把 per-resource EDF 或 DAG dependency 单列为创新；必须验证联合准入与恢复增量 |
| 多作业 finish-time admission 已实现，证明域仍有限 | 实时理论要求 WCET、blocking 和到达模型进入可调度性判断 [@baruah1990sporadic; @vestal2007mixed; @burns2017mixed] | `admission.c` 快照全部非恢复 job，含 running residual 与三类 cost；`sim_edf.c` 按资源非抢占 EDF 推进全部 DAG、逐 job 重验 deadline，并执行 reservation/dbf 检查 | 10,000 small + 5,000 stress 已覆盖一般小 DAG、1-4 资源、running state 和 reservation/dbf，但仍是固定 cost palette 的有限随机域；真实 WCET/arrival/provider trace 和更大 job 域待验证 |
| lease 与 schedule 已采用乐观原子提交 | 多租户系统表明内存与执行共享共同决定 QoS [@yu2019salus; @kim2023moca] | v2 submit 在锁内 probe lease/取 snapshot，锁外仿真，再以 `schedule_generation` 与 `lease_generation` 校验并在锁内提交 lease+job；竞争变化会重试 | v5 已完成 2-16 线程 transaction、provider-health/generation race 与 rollback 检查；软件域端点为零，实体 ISR/driver 并发仍待验证 |
| coherency 命令语义已正式跨架构验证，物理一致性仍未验证 | Linux DMA API 明确 clean/invalidate、ownership 和同步语义 [@linux2026dmaapi; @linux2026dmabuf] | `coherency.c` 检查 lease 范围、cache line、clean/invalidate/barrier；正式 harness 直接调用生产 `coherency.c`/`plan_select.c` | Host、RV64 user、RT-Thread/RV64 与四款 Cortex-M QEMU machine 各完成 1,000,000 case 和 1,171,675 个预期拒绝检查；这只支持命令状态机，不支持物理 DMA/cache 数据一致性 |
| 有预算 reset 与自动 fallback 路径已实现 | DMA fence 与 NPU 多租户工作处理完成同步/抢占，但不自动解决本项目 reset 归属 [@linux2026dmabuf; @choi2020prema] | `recovery.c` 已消费 `reset_timeout_us`、轮询 reset/reinit、按 `max_reset_attempts` 重试、quarantine；fallback 切换前重验 trust/evidence、active lease/range、provider health 和当前 snapshot 的 `SimEDF+`，trace 记录 accept/reject status | gate 的实现支撑已闭合，但固定替代 provider 回归不支撑物理时限安全；仍需真实 fault seed、竞争作业、provider bounds 与 HIL |
| trace v2 JSON、扩展 taxonomy 与分类器已实现 | profiling/serving 系统要求可归属 timing 才能分析瓶颈 [@augonnet2011starpu; @gujarati2020clockwork] | C exporter 输出 event-level plan ID，JSON Schema 验证通过；八类各 100 个冻结场景取得 macro-F1/top-3=1.0/1.0，另有八类各 300 个噪声/ring-wrap case 达 macro-F1/accuracy=1.0/1.0 | 支持冻结合成标签域及 ring-wrap 噪声稳健性，不等于真实 workload 的分类外部效度；实体板反馈仍须重新升证 |
| 物理硬件仍是必要证据层 | RTOS 文档只能证明 API 存在，不能证明本项目 deadline/cache/reset [@zephyr2026deadline; @rtthread2026docs] | v5 已在 Cortex-M3/M4/M7 四个 QEMU system machine 和 `virt`/RV64 RT-Thread Nano 5.3.0 完整重放 7,950 loader + 24,548 调度 + 1,000,000 coherency corpus；全部 `physical_hil=false`，provider fault injection 不等于生产 driver seed | QEMU 系统模型只增加跨架构实现符合性与 RTOS 集成证据；HIL 未完成前不得写物理板功能/压力证据、真实 WCET、功耗或长期稳定性结果 |

## 3. 主要核心思想

AIRTOS 将 CECAP 计划视为 RTOS 一等对象，并把作业生命周期建模为：

\[
\text{load}\rightarrow\text{validate}\rightarrow\text{select plan}
\rightarrow\text{admit}\rightarrow\text{lease}\rightarrow\text{dispatch}
\rightarrow\text{complete/cancel/reset}\rightarrow\text{trace}.
\]

计划只有同时满足以下条件才可接纳：

1. package 结构与哈希有效；
2. 当前 target、模型输入和 ABI 位于计划适用域；
3. 证据覆盖满足部署策略；
4. 所需 CPU/RVV/NPU/DMA provider 可用；
5. arena lease、buffer 边界和 coherency 动作可满足；
6. 在保守执行界下，加入该作业后所有已接纳作业仍可满足 deadline；
7. backend 处于可恢复状态且剩余恢复预算足够。

执行时采用 per-resource EDF 管理各资源 ready segment，用 DAG 依赖控制 release，用不重叠 lease 隔离 session，用 cache ownership action 维护一致性，用 `(device, epoch, cookie)` 隔离旧完成事件。trace 只作为 ADAM 下一轮实验输入，不在运行时自发改变证据等级。

## 4. 文章创新点

### 4.1 证据和适用域成为 RTOS 准入维度

传统 admission control 主要检查 CPU utilization、priority 或 memory。AIRTOS 将 plan evidence、target/model hash、shape/dtype、ABI 和 runtime prerequisites 与资源/时限联合检查，使“是否被证明可用于这里”成为接纳条件。

### 4.2 面向 segment DAG 的多资源治理

每个异构资源拥有独立 EDF queue，只有依赖完成的 segment 才进入对应队列。该模型允许同一作业的无依赖 CPU/DMA segment 并发，同时保持有依赖 segment 的拓扑顺序。

### 4.3 内存 lease 与 schedule 的原子联合准入

内存不是模型加载后的被动错误。AIRTOS 在 admission transaction 中先暂占 lease，再进行保守调度仿真；任一条件失败即回滚，从而避免“调度可行但内存不可行”或反之。

### 4.4 epoch-cookie 隔离的故障恢复语义

每个设备具有单调 epoch，每次 reset 使 epoch 变化；每次 dispatch 具有 cookie。完成事件只有同时匹配当前 epoch、active job 和 cookie 才被接受。该机制把迟到 IRQ、重复完成和 reset 后旧 command 明确定义为 stale event。

### 4.5 plan-driven coherency

cache clean/invalidate 不由 backend 隐式猜测，而由编译计划的 segment flag 和 buffer 范围驱动；运行时在 submit 前和完成后执行对应 provider hook，并将其纳入计划正确性前提。

### 4.6 可归属的 trace-to-experiment 反馈

AIRTOS 输出绑定 plan hash、target hash、run ID、epoch 和 segment 的 trace。ADAM 根据瓶颈分类选择后续 CECAP 实验，但新计划仍需重新验证和准入，从而形成无自证的闭环。

## 5. 数学理论

### 5.1 作业与 segment 模型

作业定义为：

\[
J_i=(id_i,P_i,r_i,d_i,\kappa_i,\chi_i),
\]

其中 \(P_i\) 是 CECAP 计划，\(r_i\) 是 release time，\(d_i\) 是绝对 deadline，\(\kappa_i\) 是最低证据策略，\(\chi_i\) 是 criticality/recovery policy。

计划 segment 为：

\[
s=(id,res,C,Pred,off,size,flags),
\]

其中 \(res\in\{CPU,RVV,NPU,DMA\}\)，\(C\) 是在适用域内的保守执行时间界，\(Pred\) 是前驱集合，`off/size` 是 session arena 内区域，`flags` 声明 coherency 动作。

作业 segment DAG 为 \(G_i=(V_i,E_i)\)，仅当所有前驱完成时 segment ready：

\[
Ready(s,t)\iff released(J_i,t)\land\forall u\in Pred(s),state(u)=done.
\]

### 5.2 运行时状态

定义：

\[
R_t=(\{Q_r\},\{A_r\},\mathcal{L},\mathcal{C},\{epoch_r\},\{cookie_r\},D_t,Z_t),
\]

其中：

- \(Q_r\)：资源 \(r\) 的 EDF ready queue；
- \(A_r\)：资源当前 active segment；
- \(\mathcal{L}\)：arena lease 集合；
- \(\mathcal{C}\)：cache/数据所有权状态；
- \(epoch_r,cookie_r\)：设备代次和当前 dispatch 标识；
- \(D_t\)：设备健康、reset 次数和 quarantine 状态；
- \(Z_t\)：带归属的 trace。

### 5.3 证据边界准入谓词

对候选作业定义：

\[
Admit(J_i,R_t)\iff
Parse\land Bind\land Domain\land Evidence\land Provider\land
Memory\land Coherence\land Sched\land Recoverable.
\]

各项含义为：

\[
Bind\iff h_{package}=P_i.E.output\_hash\land h_H=P_i.\Omega.target\_hash,
\]

\[
Domain\iff CurrentInput\times R_t\subseteq\Omega(P_i),
\]

\[
Evidence\iff \forall o\in Policy(\kappa_i),Cov(P_i.E,o)=1,
\]

\[
Provider\iff \forall s\in V_i,Available(res(s),R_t),
\]

\[
Memory\iff \exists l=[a,a+Arena(P_i)):\ l\subseteq Arena_{global}
\land\forall l'\in\mathcal{L},l\cap l'=\emptyset,
\]

且每个 segment 的 `[off, off+size)` 位于该 lease 内。

`Coherence` 要求所有跨 ownership domain 的边都有 runtime 支持的 clean、invalidate 和 barrier 动作。

### 5.4 保守可调度性检查

异构 DAG 和非抢占资源使简单 CPU utilization test 不足。AIRTOS 采用与运行时相同规则的保守离散事件仿真：

\[
\widehat{S}=SimEDF^+(R_t,\mathcal{J}_{admitted}\cup\{J_i\},\{C_s\}),
\]

仿真包含：

- 各资源当前 active segment 的剩余 WCET；
- 每个资源的非抢占 per-resource EDF；
- segment 前驱完成后的 release；
- coherency、DMA 和恢复的保守开销；
- 已知 release 或 admission horizon 内的保留负载。

可调度谓词为：

\[
Sched(J_i,R_t)\iff\forall J_j\in\widehat{S},\ \widehat{F}_j\le d_j.
\]

在线系统每次只原子加入通过该测试的作业。未来未知作业没有预留时不得影响已接纳承诺；周期/偶发任务需以 reservation 或 demand bound 纳入仿真。

当前 `rt_ai_admission_snapshot` 将所有非恢复 job 转换为 simulation job；对 running segment 使用：

\[
C_s^{rem}=\max(0,C_s-(t-t_s^{start}))+O_s^{coh}+O_s^{rec}.
\]

`rt_ai_sim_edf` 将候选加入快照后，对每个资源选择 ready 集中 deadline 最早的 segment，非抢占运行到完成，更新 dependency release，最后检查：

\[
Sched_{impl}(J_i,R_t)\iff
\left(\forall J_j\in\mathcal J_{snapshot}\cup\{J_i\},
\widehat F_j\le d_j\right)
\land
\left(\forall r,h\in H,dbf_r(h)\le h-t\right),
\]

其中当前临界点集合 \(H\) 是快照中各 job 的 deadline，future reservation demand 由 period、relative deadline 和 budget 估计。相较上一版，`Sched_impl` 已重验全部已接纳 job，而不再只判断候选。

在当前冻结软件域中，\(Sched_{impl}=Sched_+\) 已由两轮 Host/QEMU 逐例比较支持：每轮 10,000 个 small 场景覆盖 1-8 segment、1-4 resource、chain/diamond/fork-join/branches、running residual 和 reservation/dbf，另有 5,000 个 5-8 job stress 场景，status 与 finish 均零 mismatch。该有限随机域不是穷举，也未使用 CanMV-K230 measured WCET/arrival/provider trace，因此只支持实现一致性，不支持物理 deadline 定理的前提已经满足。

### 5.5 per-resource EDF

对资源 \(r\)，ready queue 顺序为：

\[
s_i<_{Q_r}s_j\iff d(job(s_i))<d(job(s_j)),
\]

deadline 相同则保持稳定 FIFO。资源空闲时弹出队首，运行中 segment 默认非抢占。EDF 只决定 ready segment 顺序，不绕过 DAG dependency。

### 5.6 内存 lease 与生命周期

session lease 为：

\[
l_i=(base_i,size_i,owner_i,used_i).
\]

跨 session 隔离条件：

\[
\forall i\ne j,used_i\land used_j\Rightarrow
[base_i,base_i+size_i)\cap[base_j,base_j+size_j)=\emptyset.
\]

同一 lease 内 buffer 可否重叠由 CECAP 生命周期/alias 证明决定，AIRTOS 只检查 plan 给出的 segment 范围不越过 lease。

### 5.7 coherency 状态机

对非一致 buffer 使用抽象状态：

\[
Owner(b)\in\{CPU\_dirty,CPU\_clean,Device,CPU\_valid\}.
\]

典型转移为：

```text
CPU_dirty --clean+barrier--> CPU_clean --device submit--> Device
Device --complete+invalidate--> CPU_valid
```

只有 plan 声明范围、provider hook 和硬件 cache line/alignment 均正确时，该抽象才能支持数据一致性结论。

### 5.8 timeout、cancel、reset 和 stale event

设备状态为：

\[
Idle(e)\rightarrow Busy(e,c,J,s)\rightarrow
\{Idle(e),Cancelling(e,c),Resetting(e+1),Quarantined\}.
\]

完成事件 \(irq=(r,e',c',status)\) 的接收条件：

\[
Accept(irq,R_t)\iff e'=epoch_r\land c'=cookie_r
\land A_r\ne\varnothing.
\]

timeout 后先发起 cancel；若在 \(\Delta_c\) 内不能确认静止，则增加 epoch 并进入 `reset_begin/reset_poll`；reset 完成后在 \(\Delta_i\) 内执行 reinit/health poll。每次 reset 或 reinit 失败增加尝试次数，达到 AEG v2 的 \(K_r=\texttt{max\_reset\_attempts}\) 后进入 `Quarantined`。被隔离资源不得再通过 provider admission。

当前实现已具有上述预算状态机和自动 fallback 路径。若故障作业失败且预算耗尽，恢复代码先重验 session trust/evidence、原 lease 的活动性与 fallback range、fallback provider health，再以当前 snapshot 调用 `rt_ai_sim_edf` 重验 fallback 与其他已接纳 job；只有全部通过才切换 fallback plan hash 并重新进入 pending。不可调度与 evidence 失效分别留下 admission/evidence status。schedule-safe fallback 仍是待真实 fault corpus 证伪的实验命题，而不再是缺失的代码路径。

### 5.9 trace 与反馈

运行 trace 汇总为：

\[
Z_i=(L_{queue},L_{dma},L_{kernel},M_{peak},N_{miss},N_{cancel},N_{reset},N_{stale},Env,run\_id).
\]

反馈策略不直接修改已加载计划，而输出新的验证任务：

\[
Feedback(Z_i)=
\begin{cases}
\text{mapping/scheduling experiment}, & L_{queue}\text{ dominates},\\
\text{layout/fusion/DMA experiment}, & L_{dma}\text{ dominates},\\
\text{kernel/backend experiment}, & L_{kernel}\text{ dominates},\\
\text{memory-plan experiment}, & M_{peak}\text{ near limit},\\
\text{WCET/fallback/recovery experiment}, & N_{miss}+N_{reset}>0.
\end{cases}
\]

### 5.10 核心定理与证明路线

**定理 1：跨 session 内存隔离。** 若 lease allocator 保持两两不相交，AEG loader 保证每个 segment 范围位于 plan arena 内，provider 只访问声明范围，则一个 session 的 segment 不会访问另一个 session 的 lease。

*证明路线*：segment 物理范围是 `lease.base + [off,off+size)`，它是本 lease 子集；不同 lease 不相交，故范围不相交。该定理不证明同一 session 内 alias 正确。

**定理 2：DAG 依赖安全。** 若 segment 仅在所有 predecessor 为 `done` 时入队，且只有队中 segment 可 dispatch，则任何执行序列都是 segment DAG 的拓扑序扩展。

*证明路线*：每次 dispatch 的 segment 前驱均已完成，按执行位置归纳。

**命题 1：per-resource EDF 顺序。** 在资源空闲、队列未被并发破坏时，dispatch 的 ready segment 具有该资源队列中的最早 deadline。该命题不等价于全系统 deadline guarantee。

**定理 3：epoch 隔离。** reset 后 `epoch_r` 增加。任何携带旧 epoch 的迟到完成事件都不满足 `Accept`，因而不能改变新 active job 的 segment 状态。

*证明路线*：旧事件 \(e'<epoch_r\)，与接收条件的相等式矛盾。对同 epoch 重复事件，第一次完成后 active/cookie 被清除，第二次也被拒绝。还需假设 cookie 在中断最大生存期内不复用；32-bit wrap 必须通过这一工程约束或扩大 cookie 位宽处理。

**定理 4：条件数据一致性。** 假设 cache hook 对声明地址范围正确实现 clean/invalidate 与必要 barrier，设备遵守 DMA 完成语义，计划 coherency flag 完整，则设备读取的是 submit 前 CPU 最新输入，CPU 在完成后读取的是设备最新输出。

该结论不能由 Host 或 QEMU 单独证明，必须由目标硬件上的真实 DMA/cache 路径、可观察负对照和 reference differential 支撑。

**定理 5：带 WCET 时间隔离的在线准入 deadline safety。** 令 segment \(s\) 的 dispatch 时刻为 \(a_s\)，包含 coherency/recovery 开销的认证预算为 \(C_s\)，设备实际完成时刻为 \(h_s\)。AIRTOS 只在逻辑完成时刻

\[
\ell_s=\max(h_s,a_s+C_s)
\]

释放资源并使 successor 可见。假设 `SimEDF+` 使用同一 \(C_s\)、确定性 tie-break 和非抢占规则精确模拟 runtime，所有执行作业都经过原子 admission，未来负载被拒绝或已预留，且设备不发生模型外故障。若 \(h_s\le a_s+C_s\) 且每次 `Sched` 均成立，则所有已接纳作业在 deadline 前逻辑完成。

*证明路线*：当实际执行不超过预算时，每个 segment 都在 \(a_s+C_s\) 产生逻辑完成，故 runtime 的资源释放、successor ready 与 EDF 选择轨迹和 WCET 仿真一致；按离散事件归纳得到相同 finish。新作业只在包含旧集合的仿真仍可行时原子加入，因此保持 deadline 不变量。若 \(h_s>a_s+C_s\)，该 segment 按实际较晚时刻释放并被标为模型失效，定理不适用。

该时间隔离条件不可省略。开发实验曾发现反例：在多资源非抢占 EDF 中，较早完成的前驱会让低优先级 successor 提前占用另一设备，反而阻塞随后释放的高优先级作业；因此“actual≤WCET”本身不蕴含调度可预测性。生产 runtime 现将提前硬件完成保持到认证预算边界，正式敏感性实验同时验证 \(q\le1\) 与 \(q>1\) 两侧。

**定理 6：预算恢复的失败闭合。** 若 `cancel_poll`、每次 `reset_poll` 和 `reinit_poll+health` 分别受 \(\Delta_c,\Delta_r,\Delta_i\) 约束，且最多尝试 \(K_r\) 次，则故障资源在至多

\[
T_{close}\le \Delta_c+K_r(\Delta_r+\Delta_i)+O(K_r)
\]

内进入 `Healthy` 或 `Quarantined`，不会无限占用 admission control。故障 job 的 lease 在恢复结束或 fallback 完成前不释放。

正式软件模型实验已在 Host/QEMU 各完成七类 stale/duplicate 各 \(10^5\) 次、五类恢复故障各 300 episode，并验证 cookie wrap 推进 epoch；两轮状态污染与恢复失败均为零。provider 实际执行 Add+ReLU，故障仅注入 cancel/reset/reinit API，但这些事件不是生产 driver 的物理 seed。定理仍要求真实 provider 时界、预算边界值、物理 IRQ/reset 和 HIL，不能把软件闭合外推为硬件有界恢复。

## 6. 四个核心实验如何验证

AIRTOS 的验证收敛为四个论文级核心实验。原 loader、联合准入、调度、WCET、lease、coherency、恢复、开销、反馈和 HIL 验证保留为内部子测试。

### 核心实验 1：package 完整性与原子联合准入

**研究问题**：畸形、错绑或不满足证据/资源条件的计划能否在任何 dispatch 前被拒绝，失败准入是否完全回滚？

**子测试**：package 结构 mutation；target/model/domain/evidence/provider/arena/deadline/device-health 单因子和组合 mismatch；并发提交争用最后 lease。

**对照组**：直接反序列化、AEG v1、package-only、provider+memory-only、schedule-only、完整 AIRTOS。

**主端点**：关键 malformed/unsafe admission、partial commit、active lease overlap 和 rollback leak 均为 0；拒绝原因 macro-F1 不低于 0.95。

**理论对应**：共同验证 loader 安全、完整 `Admit` 谓词和 lease/schedule 原子 transaction。

### 核心实验 2：异构 DAG 调度、WCET 边界与运行时开销

**研究问题**：`SimEDF+` 是否与独立 oracle 一致，并在模型前提成立时满足 deadline，代价是否可接受？

**素材**：从真实 CECAP plan DAG、CanMV-K230 measured WCET、arrival/provider trace 派生的 10,000 个小型 oracle 场景和 5,000 个 stress 场景；actual/WCET={0.5,0.8,1.0,1.05,1.2} 只作分层敏感性；每项机制 1,000 次板级微测和 30 个端到端 batch。

**对照组**：FIFO、fixed priority、global EDF、per-resource EDF without admission、完整 AIRTOS 及安全机制消融。

**主端点**：小场景逐例 dependency/EDF/admission 与 oracle 一致；`actual<=WCET` 且 arrivals 已预留层 deadline miss=0；完整配置 p99、锁时间、代码/RAM 满足冻结预算。

**理论对应**：同时检查 DAG 因果性、条件 deadline safety 和机制成本；超 WCET 层失败只说明模型域失效。

### 核心实验 3：arena lease 隔离与 plan-driven coherency

**研究问题**：多 session 共享 SRAM 和 CPU/device ownership 转移能否保持内存与数据一致性？

**子测试**：至少 `10^6` 次 allocate/commit/rollback/free；碎片、alignment、cancel/reset 回收；至少 `10^6` 次 DMA/cache 操作；缺 clean/invalidate/barrier、错误范围/顺序和非对齐边界。

**对照组**：静态独占、全局 bump allocator、AIRTOS lease；implicit hooks、无 range validation hooks、完整 plan-driven coherency。

**主端点**：active overlap、跨 session corruption、rollback leak 和可信平台 reference diff 均为 0。

**理论对应**：Host 生产 allocator 验证 lease 不相交，QEMU 同源固件验证命令路径，CanMV-K230 真实 DMA/cache differential 验证条件 coherency 定理；任何虚拟平台结果都不能支持物理数据一致性。

### 核心实验 4：失败闭合恢复、可归属反馈与物理 HIL

**研究问题**：cancel/reset 前的旧事件能否被隔离，恢复失败能否闭合，trace 与物理长测能否在不自证条件下发现反例？

**子测试**：每 stale/duplicate 类至少 `10^5` 次；恢复失败各 300 episode；八类带标签根因场景各 100；唯一设备绑定、当前 24 分钟且 `10^6` jobs 的持续运行 HIL；后续补 24 h 混合 HIL。

**对照组**：无 epoch、cookie-only、epoch+cookie、bounded reset/reinit+quarantine、自动 fallback 不重新准入、自动 fallback 重新 `SimEDF+` 准入；无反馈、total-latency-only、人工规则、AIRTOS trace+ADAM。

**主端点**：stale acceptance、wrong completion、post-reset contamination、超预算未 quarantine、new-plan verifier bypass、跨 lease/coherency/unsafe fallback/deadlock 均为 0；反馈分类达到预注册 F1/top-k 阈值。

**理论对应**：验证 stale isolation、有界失败闭合和无自证反馈。有限 HIL 只能写“未观察到反例”，不能证明无限可靠。

### 6.1 统计与复现

- 调度场景报告完整到达序列、WCET、实际执行时间和随机种子；
- deadline miss 用比例及置信区间，尾延迟用分位数 bootstrap；
- 故障注入逐类报告，不用平均值隐藏 stale-event failure；
- 物理实验固定或记录频率、温度、固件、设备 serial、镜像 hash 和 run ID；
- 正确性和性能分表，性能提升不能覆盖任何 correctness failure。

## 7. 每篇文章的突出贡献

AIRTOS 的突出贡献应归纳为以下四点：

1. **提出证据边界的 AI 计划准入。** 将 CECAP 适用域和多维证据与 provider、memory、deadline 和 device health 一起纳入 RTOS admission predicate。
2. **提出异构 segment DAG 的多资源治理模型。** 通过 per-resource EDF、依赖 release、session lease 和 plan-driven coherency 统一 CPU/RVV/NPU/DMA 执行。
3. **提出 epoch-cookie 隔离和预算恢复理论。** 为 timeout、cancel、reset、重复/迟到 IRQ、\(K_r\) 次恢复、quarantine 和 fallback 给出精确状态语义及条件安全定理。
4. **提出无自证的运行反馈闭环。** 将可归属 trace 转换为下一轮编译实验，同时保持新计划重新验证和重新准入。

论文最突出的主张是：

> AIRTOS 使异构 AI 计划不再以普通函数调用进入 RTOS，而成为能够依据证据、适用域、内存、时限和设备代次被接纳、拒绝、恢复与追踪的一等系统对象。

## 8. 当前项目支撑与缺口

2026-08-05 最新代码在 `airtos-exp-v5-20260804-complete-nonhil` 的软件/多架构证据之外，新增 `airtos-exp-v6-20260805-k230-hil` 单块 CanMV-K230-LP4 V3.0 实体证据：

- AEG v2 八类 section 现携带 plan/evidence/policy/model/target/runtime ABI/provider ABI/fallback plan hash、逐义务 scope/artifact/verifier hash、WCET、reservation 和恢复预算；`rt_ai_session_create_v2` 通过产品生成的 trust bundle 执行逐义务 evidence policy evaluation；
- `rt_ai_submit_async_v2` 检查 input domain、deadline/interarrival、primary/fallback provider health，并用 schedule/lease generation 乐观提交；commit 前再次检查选中 provider，失败会释放已提交 lease；
- `rt_ai_sim_edf` 重建全部 snapshot job，以 per-resource 非抢占 EDF 推进 DAG，纳入 running residual、coherency/recovery cost、reservation/dbf，并逐 job 检查 finish<=deadline；两轮 Host/RV64 对 24,548 个 small/stress/bounded/multiseed 场景与独立 oracle 逐例一致；
- 产品 trust 生成前现场验证 evidence artifact/verifier 的存在性、SHA-256 和 evidence-root 路径；六类各 300、共 1,800 case 零失败；Host/RV64 的 old/dual/new trust-root 轮换各 1,500 判定零失败；
- arena stress 为两轮 2/4/8/16 线程、每轮 1,000,000 次 attempt；成功 lease 分别为 878,058 和 908,918，overlap/canary/differential/generation/rollback 均为零；
- 生产 `coherency.c`/`plan_select.c` 正式矩阵在 Host、RV64 user、RT-Thread/RV64 和四款 Cortex-M machine 各执行 1,000,000 case，动作顺序、range/cache-line、缺失/失败/legacy hook、越界与 ownership transition 零失败；
- recovery 已实现 cancel/reset/reinit poll、`reset_timeout_us`、`max_reset_attempts`、quarantine、自动 fallback 和 fallback plan identity trace；
- trace 已有 JSON exporter、event-level plan ID、Schema 验证、latency/status 基础指标；反馈合同继续保证 trace 只产生 candidate experiment，不直接升证；
- 15 类 loader mutation及105类 pairwise、23,400-case admission diagnosis、health race、并发 transaction、七类 stale、`K_r` 恢复矩阵、四种 fallback gate、800-case trace classifier、2,400-case 噪声/ring-wrap trace 与 cookie wrap 均有冻结日志；完整回归在 Host、ASan/UBSan 和 QEMU user-mode 通过；
- v5 在 `lm3s6965evb`、`mps2-an385`、`mps2-an386`、`mps2-an500` 四个 Cortex-M3/M4/M7 QEMU system machine，以及 `virt`/RV64 的 OpenSBI + RT-Thread Nano 5.3.0 上完整重放同一 7,950 loader + 24,548 调度 + 1,000,000 coherency corpus；两轮零 mismatch/failure，确定性日志和 RT-Thread ELF 哈希一致。该证据支持软件模型内的跨架构实现符合性，但不等于五块实体开发板。
- v6 在真实 K230/RT-Smart 上完成 3,900 个准入案例、23,400 个联合诊断、400,000 次并发提交、7,950 个加载案例、24,548 个调度场景和一百万次内存租约；所有零容忍端点为零。
- v6 使用真实连续物理内存、物理地址、缓存写回/失效接口和通用直接存储器访问引擎完成四档共一百万次搬运，完整路径零差分；遗漏写回和遗漏失效各 400/400 产生可观察旧数据，故当前 K230 合同内的条件 coherency 定理已有物理证据。
- v6 的中央处理器/向量生成算子各测量 30,000 次，数值零失败；但最大值 19.926/19.778 微秒分别超过计划 10/4 微秒，实体数据否定了原 WCET 表在当前板上的适用性。7 类控制操作的 p99 低于期限 5% 的 5 微秒阈值，但没有低于最短执行段的 5%。
- v6 在板上完成 700,000 个 stale event、7,500 个 recovery/budget/gate episode、3,200 个 trace case，并使用真实设备接口完成 300 次重开/重初始化；状态机和设备生命周期端点均通过。二十四分钟持续运行正式轮次完成 6,685,424 个作业，三类错误为零并通过机器审计；二十四小时长测后续补充。

剩余缺口分为物理适配缺口与正式实验缺口：

- **物理适配缺口**：fallback 联合 gate、扩展 trace taxonomy、真实缓存路径和设备重初始化已验证；尚缺真实 driver late IRQ、硬复位和生产 provider 的可恢复 fault seed；
- **调度验证缺口**：24,548 场景已在 K230 完整重放，但仍是有限合成域；原 WCET 被实体最大值否定，必须重新标定并生成新计划，仍没有真实 arrival/provider trace 的期限复验；
- **证据验证缺口**：单因子/pairwise diagnosis、provider-health race、rollback、artifact/verifier 现场重哈希和 trust-root 轮换已完成；仅实体 ISR fault point 与生产构建部署边界仍待物理验证；
- **并发与内存缺口**：实体 2-16 线程 submit/allocator 和真实 DMA/cache ownership 已完成；仍缺更大 arena、更多 session、非对齐共享 cache line 和其他 DMA 引擎；
- **coherency 外部效度缺口**：K230 四档 reference differential 已完成；仍缺乱序、共享 cache line、总线竞争、非对齐范围和其他芯片；
- **恢复/反馈缺口**：板上状态机和真实设备重初始化已完成；仍缺生产 driver late IRQ、硬复位、真实 fault seed 和真实工作负载标签外部效度；
- **物理证据缺口**：已有生成算子时序、目标板 p99 控制开销和真实非一致 cache/DMA；原计划 WCET/低开销合同未通过，功耗、IRQ/reset 时界和后续 24 h 且 `10^6` jobs HIL 仍未完成。当前 24 分钟轮次不能替代这些长时证据。

因此当前正确状态是：联合准入、调度实现一致性、内存租约和当前 K230 合同内的物理 coherency 为 `SUPPORTED-WITHIN-SHORT-PHYSICAL-HIL`；板上 stale/recovery/fallback 状态机和真实设备重初始化也已支持。原计划 hard deadline 与严格低开销主张为 `FAILED-APPLICABILITY`；真实 driver late IRQ、硬复位、真实标签、功耗与二十四小时 HIL 为 `BLOCKED-HIL/IN-PROGRESS`。AIRTOS 消费 CECAP 计划并向 ADAM 返回 trace；它不执行编译搜索，也不替代 ADAM 的工件晋升。

## 9. 文献基础、创新边界与实验基线

完整检索、来源等级、矛盾分析和三篇接口边界见 `../literature_review.md`，引用数据见 `../references.bib`。

### 9.1 相关工作分层

**实时调度。** Liu-Layland 与 Baruah 等给出单处理器 EDF、周期/偶发任务和 demand 分析基础；Vestal 与 Burns-Davis 说明 WCET assurance 和 criticality 必须进入可调度性分析 [@liu1973scheduling; @baruah1990sporadic; @vestal2007mixed; @burns2017mixed]。这些结果不能无条件推广到非抢占 CPU/RVV/NPU/DMA segment DAG。

**异构 DAG 运行时。** HEFT、StarPU、Legion、PTask 和 typed-DAG 调度已覆盖异构任务图、数据 locality、加速器 OS 对象和异构实时 DAG [@topcuoglu2002heft; @augonnet2011starpu; @bauer2012legion; @rossbach2011ptask; @lin2022typedag]。因此“per-resource queue + DAG dependency”不是单独足够的新意。

**NPU/GPU 多租户。** PREMA、Planaria、V10、MoCA、DREAM、NeuCloud、Salus 和 Clockwork 已覆盖抢占、空间切分、细粒度共享、memory-centric QoS、实时多模型、虚拟化和可预测 serving [@choi2020prema; @ghodrati2020planaria; @xue2023v10; @kim2023moca; @kim2023dream; @xue2023npuvirt; @yu2019salus; @gujarati2020clockwork]。DREAM 是最接近的 edge real-time scheduler；PREMA/V10 依赖的硬件环境不同，必须按能力分层比较。

**Runtime assurance 与 OS 保证。** Simplex/runtime assurance 强调复杂控制器与可信安全边界分离，seL4 表明强 OS 正确性必须有清晰证明范围 [@seto1998simplex; @hobbs2023runtimeassurance; @klein2009sel4]。AIRTOS 可以借鉴其准入思想，但当前主机测试绝不等价于形式验证。

### 9.2 文献约束后的创新边界

AIRTOS 的可辩护创新是一个联合 predicate，而不是一个新 EDF 名称：

\[
PackageBind\land Domain\land Evidence\land Provider\land Memory
\land Coherence\land Sched\land Recoverable.
\]

具体贡献为：

1. 编译证据和适用域成为 RTOS admission 的必要维度；
2. arena lease 暂占和保守 schedule simulation 原子提交/回滚；
3. `(device,epoch,cookie)` 对 cancel/reset 后迟到或重复完成进行归属隔离，并以预算进入 quarantine；
4. plan 指定 cache/DMA 范围和动作，provider 执行并记录；
5. trace 只触发下一轮 CECAP/ADAM 实验，不提高原计划证据。

Linux DMA fence/API 文档已定义同步和 ownership 规则 [@linux2026dmabuf; @linux2026dmaapi]，所以创新不是重新发明 fence，而是把这些动作绑定到计划、准入、恢复和证据语义。

### 9.3 数学模型补强

当前非抢占资源必须在 `SimEDF+` 中加入 blocking：

\[
B_r(J_i)=\max\{C_s+O_s\mid res(s)=r,\ d(job(s))>d_i,
\ s\text{ may already be active}\}.
\]

周期/偶发任务还需将 reservation 或 demand-bound 纳入 admission horizon。定理 5 的结论只有在到达模型、WCET、blocking、DMA/coherency 和恢复开销均保守时成立；一旦 `actual > C_s`，实验结论应写成 WCET 模型失效，而不是掩盖为随机抖动。

对 NPU 必须在 \(\Omega(P)\) 中声明 `preemptible`。若为 false，使用上述 blocking；若为 true 且硬件/driver 证据成立，才可与 PREMA 类抢占模型直接比较 [@choi2020prema]。

### 9.4 对照组与新增实验要求

- **调度基线**：FIFO、fixed priority、global EDF、per-resource EDF、HEFT、typed-DAG/federated scheduler、DREAM。
- **多租户基线**：PREMA、Planaria、V10、MoCA、NeuCloud；按是否要求硬件 preemption/fission 分层，不把数据中心 NPU 结果直接外推到 MCU。
- **运行时抽象基线**：PTask、StarPU、Legion 中可移植的 task/data 管理子集；无法运行的系统只做机制对照，不填性能表。
- **安全主端点**：unsafe admission、stale completion acceptance、跨 lease corruption、coherency reference diff、quarantine bound 和 unsafe fallback，均必须逐例为零或解释反例。
- **时限主端点**：deadline miss、p95/p99、admission ratio 与 WCET pessimism 同时报告；只优化平均 latency 不足以验证 AIRTOS。
- **平台层次**：正式实验不用 mock；Host 运行生产 runtime 验证软件不变量，QEMU 运行同源固件并重放真实板 trace，物理 HIL 验证真实 DMA/cache/reset/IRQ 与时界。Zephyr 和 RT-Thread 文档只作为现有 API/RTOS 能力对照 [@zephyr2026deadline; @rtthread2026docs]。

### 9.5 文献修订后的突出贡献

Paper 3 最强贡献应写成：**一个让异构 AI 计划依据证据、适用域、内存、时限和设备代次被原子接纳、拒绝、恢复与追踪的 RTOS 治理层。** 它不宣称发明 EDF、DAG runtime 或 NPU 多租户；论文成败取决于联合准入、stale-event 隔离、物理 coherency 和失败闭合恢复是否经反例驱动实验成立。

## 10. 逐项创新性证明义务与实验锁

完整执行方案见 [AIRTOS 预注册实验协议](experiment_protocol.md)。AIRTOS 的贡献是联合治理不变量；平均 latency 或利用率不能替代错误接纳、stale completion、跨 lease 和 coherency 端点。

| ID | 创新点 | 最近先例与已解决内容 | AIRTOS 必须证明的新差异 | 严谨性的必要性 | 直接证伪条件 | 协议实验 |
|---|---|---|---|---|---|---|
| N1 | 证据/域/资源/WCET 联合准入 | EDF/demand、Simplex/runtime assurance 已有时限和安全过滤 [@baruah1990sporadic; @seto1998simplex; @hobbs2023runtimeassurance] | 编译 evidence/domain 与 provider、lease、coherency、schedule、health 同时进入一个 predicate | 编译正确不等于当前状态可执行 | 任一关键谓词为 false 仍接纳 | Core-1 |
| N2 | segment DAG 多资源治理 | HEFT、StarPU、Legion、PTask、typed-DAG 已有异构 DAG [@topcuoglu2002heft; @augonnet2011starpu; @bauer2012legion; @rossbach2011ptask; @lin2022typedag] | 计划资格约束下的 per-resource ready queue 与 admission/recovery 一体化 | submit-thread 调度看不到设备队列和 tensor lifetime | 前驱未完成 dispatch 或最早 deadline 规则违反 | Core-2 |
| N3 | lease 与 schedule 原子联合准入 | TFLM、Salus、MoCA 已有 arena/多租户内存治理 [@david2021tflm; @yu2019salus; @kim2023moca] | lease probe、保守 simulation 与双 generation 校验形成乐观 transaction，最终 lease/job 同锁提交 | 分开检查会产生 TOCTOU 和半提交 | active lease 重叠、拒绝后残留或 schedule snapshot 失配 | Core-1、Core-3 |
| N4 | epoch-cookie 与预算恢复/quarantine | timeout/cancel 和 DMA fence 已有 API/同步语义 [@linux2026dmabuf] | 以 device/epoch/cookie 归属迟到/重复完成；以 \(K_r\) 次有界 reset/reinit、quarantine 和独立 fallback 终止失败恢复 | reset 后旧 IRQ 可能完成新 job | stale event 改变新状态、超预算未隔离，或 fallback 未重新准入即破坏承诺 | Core-4 |
| N5 | plan-driven coherency | Linux DMA mapping 已定义 ownership 和 cache API [@linux2026dmaapi] | plan 绑定 buffer range/action，provider 实施并把结果作为证据 | 隐式 hook 难以审计且对错范围不敏感 | 完整路径仍 stale，或错误 range/action 未被拒绝 | Core-3 |
| N6 | 非自证 trace-to-experiment | StarPU profiling、Clockwork 可预测 serving 已有 trace/性能治理 [@augonnet2011starpu; @gujarati2020clockwork] | trace 只选择下一实验，新计划重新通过 CECAP verifier 和 AIRTOS admission | 在线反馈同时选策略和证明策略会形成循环 | trace 直接升证或新 plan 绕过 gate | Core-4 |

### 10.1 deadline 理论的额外证明义务

定理 5必须同时满足：actual execution/overhead 不超过绑定的 WCET、非抢占 active segment 的 blocking 已计入、周期/偶发负载以 reservation 或 demand bound 纳入 horizon、lease/schedule admission 原子、所有 model-valid job 均走相同 dispatch 规则。协议用 10,000 个小场景和独立 oracle 检查实现一致性，并用 `actual/WCET` 敏感性显式展示前提破坏。

有限实验中的 `deadline miss=0` 不是 hard real-time 证明。允许的论文措辞是：“在前提 A、冻结模型和测试域内，实现与保守仿真一致且未发现 miss。”一旦 `actual>C_s`，结论必须写成 WCET 模型对该域失效；若在全部前提满足时仍 miss，则 admission 实现声明失败。

### 10.2 论文级验收规则

- N1、N2、N3、N4 的关键安全端点必须为零；N4 的每个 stale/duplicate 类至少注入 (10^5) 次。
- N5 只有 CanMV-K230 真实 DMA/cache 路径和可观察负对照能支持物理数据一致性；Host/QEMU 只支持规则与命令路径一致性。
- N6 必须达到 trace 分类阈值且 gate bypass=0；性能改善本身不能充当反馈正确性证据。
- 长时 HIL 至少同时满足 24 小时和 (10^6) jobs，并逐例报告 reset、deadline、stale、memory 和 coherency 事件；未完成时保持 `physical_hil=false`。

当前实现已提供逐义务 evidence evaluation、artifact/verifier 现场重哈希、trust-root 轮换、多作业 `SimEDF+`/dbf、乐观原子 lease/job 提交、预算恢复/quarantine、fallback evidence/provider/active-lease/`SimEDF+` 重新准入、正式 coherency command replay、扩展 trace taxonomy/classifier 与噪声/ring-wrap 验证，并在两轮 24,548 调度场景、每环境 1,000,000 coherency case 和 x86_64/RV64/Cortex-M3/M4/M7 环境中形成软件/QEMU模型证据。仍未闭合的是真实 CECAP DAG/板测 trace 派生 timing corpus、生产 driver/device fault seeds、物理 DMA/cache、真实 WCET、板级开销、真实标签外部效度和 HIL。物理主张仍必须由板测支撑。

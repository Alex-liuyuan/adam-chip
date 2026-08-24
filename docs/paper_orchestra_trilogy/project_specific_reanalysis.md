# 基于当前项目真实能力的三篇论文重新分析

## 0. 分析依据与结论纪律

本文不是从三个预设题目反向寻找项目材料，而是从当前生产链的三个决策边界重新推导论文：

```text
硬件材料 -> ADAM：谁有权产生和晋升工程工件？
已验证合同 -> CECAP：什么异构加速计划合法且具有部署资格？
可部署计划 -> AIRTOS：在当前资源、时限和设备状态下能否接纳和安全执行？
```

分析依据包括当前仓库的材料锁、Hardware IR、能力任务图、隔离 worktree、来源闭包、TVM/RVV 编译原型、AEG v2、联合准入、EDF、arena lease、coherency、epoch-cookie、恢复/quarantine、trace v2 和反馈合同，以及已经核验的行业文献。当前实现与理论目标严格分开：AIRTOS 已在两次冻结软件运行中完成 package/admission、一般小 DAG/stress、2-16 线程 transaction/allocator、stale/recovery/cookie-wrap 验证；该证据只支撑软件模型，真实 CECAP/板测数据、物理 DMA/cache、生产 driver 时界、H8 和 HIL 仍未完成。

所有实验结论均为预注册式条件结论，不是已获得结果。详细素材与执行步骤分别见三篇的实验实施蓝图。

## 1. 为什么必须拆成三篇

| 层次 | 决策对象 | 主要失败后果 | 独立数学对象 | 对应论文 |
|---|---|---|---|---|
| 工程协同层 | task、patch、source closure、evidence、promotion | 错误事实授权、污染集成树、非法来源、错误晋升 | 任务图、事实状态、证据债务、晋升谓词 | ADAM |
| 编译计划层 | partition、schedule、mapping、memory、fallback、domain | 非法 backend、越界内存、域外执行、错误升证 | 合法计划空间、多目标支配、证据产品 | CECAP |
| 运行时治理层 | admission、queue、lease、DMA/cache、epoch、recovery | deadline miss、跨模型污染、stale completion、死锁 | 可调度性、原子资源事务、恢复状态机 | AIRTOS |

三篇共享“候选权不等于验收权”，但不能共享同一个主端点。ADAM 的 `false promotion=0` 不能证明 CECAP 的 Pareto 前沿正确；CECAP 的数值通过不能证明 AIRTOS deadline；AIRTOS 一次成功运行也不能反向证明计划在其他适用域正确。

# 2. 论文一：ADAM

## 2.1 建议题目

**英文**

> ADAM: Evidence-Governed Agentic Co-Design for Hardware-Derived SoC Software Stacks

**中文**

> ADAM：面向硬件材料驱动 SoC 软件栈的证据治理型智能体协同设计

题目保留 `Hardware-Derived`、`Agentic Co-Design` 和 `Evidence-Governed` 三个限定。论文不是普通多 Agent 编程，而是研究在不完全信任 Agent 和硬件材料的前提下如何控制工程效力。

## 2.2 主要核心思想

把 SoC 软件生产建模为“事实授权、候选生成、独立验证、证据闭合和原子晋升”的任务图。Agent 可以搜索、生成和修复，但没有权力把自己的输出写成发布事实。只有来源安全的硬件事实、允许的路径、完整来源闭包和与声明匹配的证据同时满足时，候选才能进入集成树。

中心命题为：

> 在材料解析、路径检查、来源求解和 verifier 满足明确前提时，ADAM 能阻止由非安全事实、越权修改、非法来源或证据债务支撑的候选获得工程效力，同时通过风险激活减少不必要的协作成本。

## 2.3 当前行业的真实难点

1. **硬件输入不是干净 target**：真实输入来自 PDF、原理图、DTS、SVD、板级观察和旧镜像，字段会缺失、冲突或版本漂移。通用代码 Agent 通常假定仓库和任务描述已给定 [@yang2024sweagent; @jimenez2024swebench]。
2. **跨层因果链长**：Boot、BSP、driver、compiler、runtime、image 和 HIL 相互依赖，局部代码通过不能说明整体可用。
3. **Agent 容易自证**：生成器自行选择测试、解释结果和晋升时，候选权与验收权混合；两个 verifier 还可能共享工具链和 oracle [@barr2015oracle; @avizienis1985nversion]。
4. **源码可发现不等于可组合**：许可证、OS ABI、media ABI、submodule、manifest 和 revision 必须形成传递闭包，顶层 commit 锁并不充分 [@torresarias2019intoto; @samuel2010tuf]。
5. **失败与阻塞语义不同**：网络失败、工具失败、材料不足和设备缺失需要不同恢复策略；简单重试会掩盖稳定 blocker。
6. **安全指标不能只看平均成功率**：少量错误 flash、错误 ABI 或 false promotion 的后果远高于一般任务失败，因此需要逐类零容忍端点。

## 2.4 文章创新点及新颖性边界

### 创新 1：硬件事实状态驱动的能力图

将 `authoritative/standard-derived/board-observed/candidate/unknown/conflict` 作为能力启用语义，而不是标量置信度。新颖点在于事实状态直接约束 SoC 工程动作，而非仅作为检索元数据。当前 `material_selectors` 仍可能绕过这一原则，因此它也是必须被实验证伪的实现缺口。

### 创新 2：候选权与工程验收权分离

在沙箱之外加入 owned-path、symlink/rename 防绕过、候选验证、集成后验证、证据闭合和 promotion commit。新颖性不是“用了 worktree”，而是把这些机制组合为工程效力状态机。

### 创新 3：声明索引的证据债务

证据按 claim、obligation、input/output hash 和适用域绑定；build、numeric、physical 和 timing 不能由一个 `verified=true` 互相代替。它借鉴 PCC、runtime verification 和 assurance case，但研究对象是 Agent 生成的 SoC 工件 [@necula1997pcc; @leucker2009runtimeverification]。

### 创新 4：来源锚点与传递闭包共同求解

把许可证、ABI、被选路径和传递依赖闭包纳入任务规划，不仅记录 provenance。区别在于 provenance 记录“做了什么”，闭包求解还决定“是否允许这样组合”。

### 创新 5：由证据债务和后果风险激活 verifier

不是固定启动所有角色，也不是为了省调用任意裁剪；系统选择能覆盖高权重未满足义务的 verifier。新颖性必须由“证据非劣且 false promotion 不增加”证明。

### 创新 6：面向恢复的可审计状态机

把 `failed/blocked/interrupted/obsolete/passed`、输入 hash、失败签名、尝试预算和 artifact 完整性统一持久化。新颖点是恢复与证据有效性和晋升状态联动，而不只是任务重跑。

新颖性措辞应限定为：在检索覆盖的多 Agent 软件工程、供应链 provenance 与 runtime assurance 工作中，尚未发现这些机制被统一用于硬件材料驱动的 SoC 工件晋升。不能无条件声称“首次”。

## 2.5 数学理论

### 基本对象

材料锁为 `lambda`，Hardware IR 为 `H`，事实为：

\[
f=(v,q,Pi,C),\qquad SafeFact(f)\iff q\in\{authoritative,standard\_derived,board\_observed\}.
\]

任务图定义为：

\[
G=(V_T,E_D,E_R,E_V),
\]

其中 `E_D` 是依赖边，`E_R` 是资源/权限边，`E_V` 是验证义务边。声明 `c` 的证据债务为：

\[
Debt(c,E)=\sum_{o\in O_c}w_o\left(1-Cov(E,c)[o]\right).
\]

晋升谓词为：

\[
Promote(a)\iff SafeBasis(a)\land PathOK(a)\land ClosureOK(a)
\land CandidatePass(a)\land IntegrationPass(a)\land Debt(a)=0.
\]

### 需要证明或检验的核心命题

1. **非安全事实不激活**：若 capability 的必要 basis 中存在非 `SafeFact`，该 capability 不进入 production roots。
2. **路径不越权**：在 changed-tree 检查完整且文件系统假设成立时，晋升工件的修改集合属于 owned paths。
3. **依赖因果性**：任务只有在所有前驱处于有效 passed 状态时才能晋升。
4. **相对 verifier 可靠性**：若 candidate 和 integration verifier 对声明域 sound，false candidate 不能晋升；实验必须单列共同漏检以检查前提。
5. **债务单调性**：普通候选变换不能无授权 verifier 地降低 evidence debt；输入或适用域变化会使相关证据失效。
6. **有限恢复终止**：有限任务图、有限尝试预算和稳定 blocker 条件下，调度最终进入 passed、failed 或 blocked 终态。

理论的关键严谨性在于所有命题都带解析器、文件系统、oracle、verifier 和故障模型假设，不把工程测试写成无条件形式证明。

## 2.6 四个核心实验如何验证

| 实验 | 要验证的创新/命题 | 核心素材与对照 | 主指标与判据 | 能支持的结论 |
|---|---|---|---|---|
| Core-1 事实、来源与任务图安全 | 创新 1/4 | 160 任务、fact/closure 各类 300、60 个合法栈、多平台合同 | unsafe activation=0；invalid closure acceptance=0；graph F1>=0.95 | 测试域内事实授权、来源闭包和平台区分有效 |
| Core-2 候选与晋升安全 | 创新 2/3 | 路径攻击与 oracle blind spot 各类 300；两阶段验证 | 路径逃逸/关键 false promotion=0；claim-evidence recall=1 | 工程效力隔离在 verifier 前提内成立 |
| Core-3 风险协作有效性 | 创新 5 | 96 个分层任务 x 5 seed；静态全角色、单 Agent、简化流程 | evidence 非劣下界>=-3pp 后 calls 中位数下降>=20%；FPR 不增 | 同等证据下减少协作成本 |
| Core-4 恢复与跨平台边界 | 创新 6 及端到端组合 | 六类故障各 300；QEMU/RVV/NPU/K230 合同和 HIL gate | 状态违反=0；重做下降>=50%；错误物理效力=0 | 正确恢复并对材料/设备不足稳定阻塞 |

素材生成、文件 schema、统计方法和结论出口见 [ADAM 实施蓝图](paper1_adam/implementation_blueprint.md)与[预注册协议](paper1_adam/experiment_protocol.md)。

## 2.7 突出贡献

ADAM 最突出的贡献不是提高 Agent 数量或单纯提高代码生成成功率，而是提出并实现一个**不需要信任 Agent 正确性的 SoC 工程效力控制面**。它把硬件来源、能力授权、路径权限、来源闭包、证据义务和恢复状态统一到同一晋升决策中。若实验成立，论文贡献是“如何安全使用不可靠 Agent”，而不是“Agent 自动完成了整个芯片软件栈”。

# 3. 论文二：CECAP

## 3.1 建议题目

**英文**

> CECAP: Contract- and Evidence-Carrying Acceleration Plans for Hardware-Bounded Heterogeneous Edge AI

**中文**

> CECAP：面向硬件约束异构边缘 AI 的契约与证据携带加速计划

题目强调输出对象是 `acceleration plan`，不是又一个 kernel tuner。

## 3.2 主要核心思想

将编译器输出从代码/二进制扩展为运行时可检查的完整计划：图分段、backend、layout、quantization、schedule、mapping、memory、domain、fallback、obligation 和 evidence 全部被 hash 绑定。搜索器可保留 candidate，但只有合法、域内且证据完整的计划才能成为 deployable。

中心命题为：

> 在来源受限的硬件合同和有限搜索空间内，CECAP 能先过滤非法计划，再产生带独立适用域和证据的主计划/fallback；exact 算法在明确前提下保持 Pareto 前沿，而 bounded beam 只提供可测的近似质量。

## 3.3 当前行业的真实难点

1. **编译器通常假设 target 已正确给出**：TVM、MLIR、Ansor、TensorIR 已解决大量 lowering/tuning 问题，但新 SoC 的 NPU ABI、DMA、cache 和 arena 合同可能未知或冲突 [@chen2018tvm; @lattner2021mlir; @zheng2020ansor; @feng2023tensorir]。
2. **异构优化是跨层组合**：partition、layout、precision、schedule、mapping、memory 和 coherency 互相影响，局部最快不一定形成合法全局计划。
3. **编译成功不等于可运行**：code artifact 通常不足以表示 model/shape/target/toolchain/runtime 适用域和最低 evidence policy。
4. **exact 与 heuristic 容易混写**：固定 beam 会丢失 Pareto 计划，不能用经验性能宣称完备。
5. **证据是多维产品而非等级**：build、numeric、resource、physical、timing 和 supply-chain 不能互相替代。
6. **fallback 最容易发生资格降级**：主后端失败时，系统常转向未经独立验证的 CPU/RVV 路径。

## 3.4 文章创新点及新颖性边界

### 创新 1：消费者可检查的完整计划对象

以 `P=(G,B,L,Q,S,M,D,F,Omega,E)` 同时表达 graph、backend、layout、quantization、schedule、memory/mapping、domain、fallback、obligation 和 evidence。区别于普通 metadata 的关键是 runtime 可以依据这些字段拒绝计划。

### 创新 2：由事实来源状态约束合法空间

backend 资格必须有 SafeFact basis；检测到 NPU 名称不等于具有 command ABI。unknown/conflict 产生 blocker 或调查任务，不能生成 deployable blob。

### 创新 3：exact Pareto 保持与 beam 近似分离

exact 层通过完整有限扩展和非支配归并给出可检查定理；beam 明确携带 K、预算和丢弃 trace，只做经验近似。

### 创新 4：适用域索引正确性

正确性绑定 model、shape、layout、precision、target、ABI、toolchain 和 runtime hash；消费者在 dispatch 前拒绝域外计划。

### 创新 5：编译变换的证据不增信

普通 transform 只能保持或失效 evidence coordinate，不能新增 pass；所有升证都必须由授权 verifier 产生。

### 创新 6：candidate-preserving deployment

不删除证据不足但可能有价值的候选，而是将 candidate storage 与 deployable set 分离，既保留搜索投资又不放松执行 gate。

### 创新 7：独立证据 fallback

每个 fallback 是完整计划，有自己的 domain、memory、evidence 和 policy，不继承主计划资格。

新颖性不应写成“比 TVM 更先进的编译器”，而应写成：CECAP 把来源受限合法性、完整异构计划、适用域、证据失效和独立 fallback 统一为消费者可拒绝的部署合同。

## 3.5 数学理论

硬件合同 `H`、工作负载 `W` 与计划 `P` 的合法性定义为：

\[
Legal(P\mid H,W)=TypeOK\land BackendOK\land DAGOK\land MemoryOK
\land ABIOK\land CoherencyOK\land BindingOK\land FallbackOK.
\]

多目标成本向量为：

\[
J(P)=(latency,energy,peak\_memory,compile\_cost,evidence\_debt,risk).
\]

支配关系：

\[
P_1\prec P_2\iff \forall k:J_k(P_1)\le J_k(P_2)
\land \exists k:J_k(P_1)<J_k(P_2).
\]

证据状态使用产品空间：

\[
E(P)=\prod_{o\in O_P}E_o,
\]

普通变换 `T` 的不增信性质为：

\[
E_o(T(P))\preceq E_o(P)
\]

除非 `T` 同时调用该坐标的授权 verifier。

核心理论包括：

1. **合法空间安全**：所有 deployable plan 都属于 `Legal(P|H,W)`。
2. **exact Pareto 保持**：若扩展完备、lower bound 可采纳、dominance relation 正确，则分层 exact frontier 等于穷举前沿。
3. **适用域正确性**：plan 只对 `Omega_request subseteq Omega_plan` 且所有 binding hash 相等的请求可执行。
4. **证据不增信**：未运行授权 verifier 的 transform 不会增加覆盖坐标。
5. **fallback safety**：runtime 只选择第一个独立满足 Legal、domain 和 evidence policy 的计划，否则拒绝。

beam 不属于 Pareto 保持定理，只评价 recall、hypervolume 和 epsilon indicator。

## 3.6 四个核心实验如何验证

| 实验 | 要验证的创新/命题 | 核心素材与对照 | 主指标与判据 | 能支持的结论 |
|---|---|---|---|---|
| Core-1 合同与完整计划合法性 | 创新 1/2/4 | 八类合同/域外 mutation 各 300；code-only、metadata、plan v2 | illegal/unsafe pre-dispatch acceptance=0；diagnostic F1>=0.95 | 来源约束和完整计划可提前拒绝非法/域外部署 |
| Core-2 搜索正确性与质量 | 创新 3 | 200 小图、10,000 lower-bound cases、30-seed 大图 | exact recall=1/false=0；K=8 beam recall/HV 达阈值 | exact 符合定理，beam 只在预算内有用 |
| Core-3 证据与 fallback 安全 | 创新 5/6/7 | transform、NPU ABI、六类环境故障各 300 | false evidence/NPU emission/unsafe fallback=0 | 不错误升证，未知 ABI 阻塞，fallback 不降级 |
| Core-4 多模型执行与真实性能 | 可执行性与外部有效性 | 多模型/shape 每配置 100 输入；CPU/RVV/NPU；真实板 | 数值超容差=0；负例全拒绝；speedup CI 完全>1 | 超出 Add+ReLU，正确性与性能分别有证据 |

详细素材和运行卡见 [CECAP 实施蓝图](paper2_cecap/implementation_blueprint.md)与[预注册协议](paper2_cecap/experiment_protocol.md)。

## 3.7 突出贡献

CECAP 最突出的贡献是把异构编译结果从“选择了哪段代码”提升为**可由运行时检查和拒绝的部署资格对象**。它让合法性、适用域、证据和 fallback 不再是日志或隐含假设，而成为计划本身的一部分。论文价值主要是可信部署边界，而不是预设性能一定超过现有 tuner。

# 4. 论文三：AIRTOS

## 4.1 建议题目

**英文**

> AIRTOS: Evidence-Bounded Admission, Resource Governance, and Recovery for Heterogeneous Edge AI

**中文**

> AIRTOS：面向异构边缘 AI 的证据边界准入、资源治理与故障恢复

题目明确它是 RTOS 上的 AI 治理层，不是一个全新通用内核。

## 4.2 主要核心思想

把 CECAP 计划作为只读合同，在作业提交时联合检查 binding、domain、evidence、provider health、WCET、调度、arena lease、coherency 和恢复状态；lease 与 schedule 必须在同一 transaction 中提交或回滚。执行期间使用 per-resource EDF、epoch-cookie、预算恢复和 quarantine 隔离迟到事件；trace 只能触发下一实验，不能自证。当前代码已实现 \(K_r=\texttt{max\_reset\_attempts}\) 次 reset/reinit 尝试，且 fallback 切换前重验 trust/evidence、active lease/range、provider health 与 `rt_ai_sim_edf`；“schedule-safe”仍须由真实竞争与故障素材验证，不能由替代 provider 回归直接宣称。

中心命题为：

> 在 WCET、到达模型、非抢占 blocking、coherency 和恢复时界前提成立时，AIRTOS 能拒绝不可安全接纳的异构 AI 作业，保持 segment 依赖与内存隔离，并阻止 cancel/reset 前的迟到完成污染新作业。

## 4.3 当前行业的真实难点

1. **AI 作业不是单一 RTOS 线程**：一个推理图会跨 CPU、RVV、NPU、DMA 和中断，传统单任务 WCET/priority 表达不足。
2. **异构资源常非抢占**：NPU/DMA blocking 会破坏只看平均 latency 或简单 EDF queue 的安全判断 [@liu1973scheduling; @rossbach2011ptask]。
3. **连续 SRAM 是跨 session 风险**：arena 紧张、碎片化、取消和 reset 时错误回收会造成跨模型污染。
4. **cache/DMA 是所有权协议**：clean/invalidate 的范围和顺序依赖数据所有权；API 被调用不等于数据一致 [@linux2026dmaapi]。
5. **取消不是瞬间完成**：cancel/reset 后旧 IRQ 仍可能到达；只有 cookie 而无设备代次和恢复闭合仍可能污染新作业。
6. **编译计划合法不等于当前可接纳**：provider offline、arena 不足、evidence policy 提高或 deadline 变紧都必须在运行时判断。
7. **trace 容易形成自证闭环**：若同一 trace 同时选择优化和验证优化，结论不独立。

## 4.4 文章创新点及新颖性边界

### 创新 1：证据和适用域进入运行时准入

`Admit` 不只检查 deadline/provider，而是同时检查 plan/model/target hash、domain、evidence policy、WCET、resource、memory 和 recovery。

### 创新 2：面向 segment DAG 的多资源治理

以 segment dependency 和 per-resource EDF 治理 CPU/RVV/NPU/DMA，显式包含 active residual、非抢占 blocking、reservation 和 recovery overhead。

### 创新 3：lease 与 schedule 原子联合准入

先 tentative allocate 和 schedule simulation，再统一 commit/rollback，消除“调度可行但内存失败”或“内存已占用但调度拒绝”的部分提交。

### 创新 4：epoch-cookie 与有界恢复/quarantine

epoch 隔离设备代次，cookie 区分同代作业；cancel ack、`reset_poll`、reset/reinit timeout、最多 \(K_r\) 次尝试和 quarantine 使失败状态闭合。自动 fallback 已形成可执行功能路径，并在切换前重验 trust/evidence、active lease/range、provider health 与 `rt_ai_sim_edf`；真实竞争作业和故障 seed 仍是该创新的直接证伪素材缺口。

### 创新 5：plan-driven coherency

由计划中 buffer ownership、range 和 transfer edge 驱动 clean/invalidate，而不是由调用者凭约定操作 cache。

### 创新 6：可归属且不自证的 trace 反馈

trace 带 logical sequence、真实 timestamp、run/plan/job/resource/epoch/cookie，能够选择下一实验；新计划仍必须重新经过 CECAP evidence 和 AIRTOS admission。

新颖性应限定为：AIRTOS 不是新 EDF 算法，而是将编译计划证据、适用域、异构资源、内存、coherency 和恢复状态统一进 RTOS 准入与执行生命周期。

## 4.5 数学理论

作业 `j` 由 segment DAG 表示：

\[
J_j=(V_j,E_j,r_j,d_j,Omega_j),
\]

每个 segment `s` 有资源 `k(s)`、WCET `C_s`、内存区间和 coherency action。运行时状态为：

\[
R_t=(Q_t,A_t,L_t,H_t,Epoch_t,Cookie_t,Trace_t).
\]

联合准入谓词：

\[
Admit(j,R_t)\iff BindOK\land DomainOK\land EvidenceOK\land ProviderOK
\land LeaseFeasible\land SimEDF^+(j,R_t)\land RecoveryFeasible.
\]

内存不相交不变量：

\[
\forall l_i,l_j\in L_t,i\ne j:\ interval(l_i)\cap interval(l_j)=\varnothing.
\]

完成事件接收谓词：

\[
Accept(e)\iff device(e)=r\land epoch(e)=Epoch_r
\land cookie(e)=ActiveCookie_r\land job(e)=ActiveJob_r.
\]

预算恢复的理论闭合界为：

\[
T_{close}\le \Delta_c+K_r(\Delta_r+\Delta_i)+O(K_r),
\]

其中 \(\Delta_c\)、\(\Delta_r\)、\(\Delta_i\) 分别约束 cancel acknowledgement、每次 reset poll 和 reinit/health；达到 `max_reset_attempts` 后必须进入 `Quarantined`。当前实现具备该预算状态机，但 provider 时界依据、错误组合和边界值仍需 Core-4 验证。若切换 fallback，还必须满足：

\[
FallbackSafe(J_f,R_t)\iff Evidence_f\land Provider_f\land
SimEDF^+(R_t,J_f).
\]

当前恢复路径已实现上述三项 gate，并额外重验 active lease/range 和绝对 deadline；因尚无真实竞争作业、生产 provider bound 与物理故障 seed，当前只支撑 gate 的实现 readiness，不支撑 fallback 实时安全的正式结论。

核心理论包括：

1. **联合准入安全**：任何被接纳作业满足全部合取条件，失败 transaction 不改变资源状态。
2. **条件 deadline safety**：若 actual<=WCET、arrival/reservation、blocking 和 recovery cost 模型成立，`SimEDF+` 接纳集合无 deadline miss。
3. **DAG 因果性**：segment 只在全部 predecessor 完成后入队。
4. **lease 隔离**：所有 live lease 区间不相交，rollback 后无资源泄漏。
5. **coherency 所有权安全**：每次 CPU/device ownership 转移执行计划要求的 range action。
6. **stale isolation**：不满足 Accept 的旧事件不能改变任何新 job 状态。
7. **预算失败闭合**：cancel 超时转 reset，最多 \(K_r\) 次 reset/reinit 后进入 Healthy 或 Quarantined；该命题不自动保证 fallback 可调度。

## 4.6 四个核心实验如何验证

| 实验 | 要验证的创新/命题 | 核心素材与对照 | 主指标与判据 | 能支持的结论 |
|---|---|---|---|---|
| Core-1 package 与原子联合准入 | 创新 1/3 | package mutation 各 300；组合 1,000；并发 transaction 10,000 | unsafe parse/admission/partial commit/leak=0 | loader、合取准入和原子提交正确 |
| Core-2 调度、WCET 与开销 | 创新 2 与条件 deadline | 10,000 oracle、5,000 stress、WCET 分层、微测 | 逐场景一致；model-valid miss=0；开销达冻结预算 | `SimEDF+` 在模型内一致且成本可接受 |
| Core-3 内存与 coherency | 创新 3/5 | `10^6` lease + `10^6` DMA/cache 操作；可信平台 | overlap/corruption/rollback leak/reference diff=0 | 多 session 隔离和 plan-driven coherency 有效 |
| Core-4 恢复、反馈与 HIL | 创新 4/6 与外部有效性 | `10^5` stale/类、恢复失败、800 根因、24 h/`10^6` jobs | wrong completion/quarantine/bypass/HIL 安全端点=0；F1/top-k 达标 | 旧事件隔离、恢复闭合、反馈不自证、有限 HIL 无反例 |

详细素材、状态机和 HIL 入口见 [AIRTOS 实施蓝图](paper3_airtos/implementation_blueprint.md)与[预注册协议](paper3_airtos/experiment_protocol.md)。

## 4.7 突出贡献

AIRTOS 最突出的贡献是提出一个**证据边界内的异构 AI 运行时治理层**：运行时不盲信编译器，也不重新做编译搜索，而是根据当前资源、时限、设备代次和证据策略原子接纳或拒绝计划；出现故障时以 epoch-cookie、时界和 quarantine 保持状态隔离。

## 4.8 更新后代码支撑与论文缺口

截至 2026-08-04，当前代码已形成以下软件模型与 QEMU 系统机型支撑：

- **合同与证据**：AEG v2 携带 plan/evidence/policy/model/target/runtime ABI/provider ABI hash、逐义务 scope/artifact/verifier hash、verifier allowlist 及 primary/fallback evidence-resource 绑定；产品生成 trust bundle，并由 `rt_ai_session_create_v2` 调用 runtime evaluator；
- **联合准入与调度**：两轮 Host/QEMU user-mode 各完成 4,800 loader、3,900 admission、10,000 small 和 5,000 stress；固定 corpus/CSV 哈希一致且零 mismatch。Host 每轮另完成 400,000 次 2-16 线程 transaction，overlap/partial commit 为零；
- **内存与 coherency**：Host 每轮完成 1,000,000 次 2-16 线程 allocator attempt，成功 lease 为 995,267/996,095 且 overlap 为零；软件 cache model 回归通过，但不进入物理 coherency 结论；
- **恢复与 trace**：Host/QEMU user-mode 每轮每平台完成七类 stale 各 100,000、五类恢复故障各 300 和 cookie wrap，全部零污染/失败；trace exporter、fallback 和完整回归同步通过；
- **系统机型与 RTOS 集成**：`airtos-exp-v3-20260804-qemu-system` 在 `lm3s6965evb`、`mps2-an385`、`mps2-an386`、`mps2-an500` 四个 Cortex-M QEMU system machine 上完成裸机同源 AIRTOS smoke，并在 `virt`/RV64 上实际启动 OpenSBI + RT-Thread Nano 5.3.0，完成 loader、Add+ReLU、wrong-epoch 拒绝和 cookie-wrap 路径；两轮 ELF/日志哈希逐项一致；
- **结果纪律**：v2 `final_run4/5` 记录环境、原始 CSV/log、异常链、统计上界和 SHA-256，结论标为 `SUPPORTED-WITHIN-SOFTWARE-MODEL`；v3 标为 `SUPPORTED-WITHIN-QEMU-SYSTEM-MODELS`。v2 大样本仍是 QEMU user-mode，v3 四个 ARM 结果是裸机 machine smoke，三个 MPS2 同属一个 FPGA 平台族，`virt` 不是商品板，完整 corpus 尚未在 RT-Thread 固件中重放；任何一项均不能标为实体板结果。

剩余缺口按论文声明分层如下：

- **实现与验证边界**：自动 fallback 的 evidence/provider/active-lease/`rt_ai_sim_edf` gate 和软件故障路径已有直接证据；`fallback schedule-safe` 仍为 `EXPERIMENT-NOT-READY`，因为尚无真实竞争作业、生产 provider bound 与物理 fault seed；
- **调度正式验证**：当前 10,000 small 已覆盖一般小 DAG、1-4 资源、running residual 和 reservation/dbf，另有 5,000 个 5-8 job stress；但它们来自固定 cost palette，不是 CECAP/CanMV-K230 measured WCET、arrival/provider trace，也不支撑实际 deadline/开销；
- **证据与 transaction**：单因子 mutation/admission 和 2-16 线程 transaction 已完成；仍缺组合 covering array、artifact 文件重哈希、provider-health race、canary/跨 session 差分、诊断 F1 及全部 rollback fault point；
- **恢复与反馈**：软件逐 stale 类各 `10^5`、恢复失败类各 300 和 wrap 已完成；仍缺生产 driver/device fault seed、物理时界/预算边界、fallback 真实竞争、800 个真实根因、macro-F1/top-k；
- **物理外部效度**：Host/QEMU 不能外推真实 DMA/cache；真实 WCET、目标板 p99 开销、能耗、IRQ/reset 时界以及 24 h 且 `10^6` jobs HIL 均未完成。

四个核心实验的软件子域已经形成冻结结果，可标为 `SUPPORTED-WITHIN-SOFTWARE-MODEL`；它不能冒充物理 confirmatory 结果。真实 WCET/arrival/provider 数据未具备时标为 `BLOCKED-HIL-DATA`，实体 DMA/cache/reset/HIL 未执行时标为 `BLOCKED-HIL`，H8 未实现时标为 `EXPERIMENT-NOT-READY`。

# 5. 三篇文章的独立贡献与组合价值

| 论文 | 唯一研究对象 | 最重要安全端点 | 最突出贡献 | 不能声称的内容 |
|---|---|---|---|---|
| ADAM | Agent 候选及其工程晋升 | unsafe activation/false promotion=0 | 不信任 Agent 前提下的工程效力控制 | 编译 Pareto、运行时 deadline |
| CECAP | 异构加速计划及部署资格 | illegal/domain/evidence/fallback acceptance=0 | 可由消费者拒绝的完整部署合同 | Agent 协作安全、任意 beam 完备 |
| AIRTOS | 当前运行状态中的作业接纳与恢复 | unsafe admission/stale/corruption=0 | 证据、资源、时限和代次联合治理 | 编译全域正确、无限时间可靠 |

三篇组合形成闭环：ADAM 产生并治理合同和实验，CECAP 产生可检查计划，AIRTOS 在运行环境中接纳和执行，trace 再返回 ADAM 选择下一实验。闭环不能形成证明循环：每一轮新计划都需要新的 hash、证据和准入记录。

# 6. 投稿叙事上的最终取舍

1. ADAM 的摘要首先写“阻止未经证实候选获得工程效力”，其次才写自动化效率。
2. CECAP 的摘要首先写“完整计划可被消费者拒绝”，不能以“比 TVM 更快”作为必然卖点。
3. AIRTOS 的摘要首先写“条件准入和 stale isolation”，不能把平均 latency 当作实时安全。
4. 三篇的安全结论均采用逐类零容忍；效率、覆盖率和性能采用效果量与置信区间，不能互相代偿。
5. 未实现机制标记 `IMPLEMENTATION-NOT-READY`；实验代码或语料未冻结时标记 `EXPERIMENT-NOT-READY`；无物理设备时标记 `BLOCKED-HIL`。
6. 任何预期结论只有在协议冻结、独立 oracle 和原始 artifact 完整后才能改写为结果陈述。

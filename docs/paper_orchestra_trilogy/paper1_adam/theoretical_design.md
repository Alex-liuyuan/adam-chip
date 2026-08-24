# Paper 1 理论设计：ADAM

> 工程实施、实验素材生产、逐实验输入输出与结论判定见 [实验实施蓝图](implementation_blueprint.md)；冻结假设、样本量与统计规则见 [预注册实验协议](experiment_protocol.md)。

## 1. 论文题目

**英文题目**

> ADAM: Evidence-Governed Agentic Co-Design for Hardware-Derived SoC Software Stacks

**中文题目**

> ADAM：面向硬件材料驱动 SoC 软件栈的证据治理型多智能体协同设计

题目中的三个限定不可删除：

- `Hardware-Derived` 表示软件需求和能力必须从材料锁与 Hardware IR 推导，而不是由用户预选 SDK 或目标配置；
- `Agentic Co-Design` 表示多个专业 Agent 围绕跨层依赖图协作，而不是一个代码生成模型独立完成任务；
- `Evidence-Governed` 表示 Agent 只拥有候选权，工件晋升由来源、权限和确定性验证共同决定。

### 1.1 论文研究设计摘要

| 必须体现的内容 | ADAM 的具体内容 |
|---|---|
| **真实行业难点** | 当前软件 Agent 已能在仓库中调用工具、修复 issue 和执行测试，但 SoC 开发起点是来源强度不同且可能冲突的材料；沙箱、provenance、测试和多 Agent SOP 各自存在，却不能共同决定一个硬件相关候选是否可进入集成树 [@hong2024metagpt; @yang2024sweagent; @wang2025openhands; @torresarias2019intoto] |
| **核心创新** | 将硬件事实状态、capability/task DAG、owned-path、传递来源闭包、claim-indexed evidence 和 `failed/blocked/obsolete` 恢复统一为工程效力控制面；Agent 生成候选，但无权自行晋升 |
| **数学理论** | 以材料锁 \(\lambda\)、任务图 \(G=(V_T,E_D,E_R,E_V)\)、风险 \(\rho(\tau)\)、证据债务 \(Debt\) 和晋升谓词 \(Promote\) 为核心，给出不安全事实不激活、路径权限、依赖因果、相对验证器可靠性、债务单调性和有限调度终止的条件结论 |
| **实验验证** | Core-1 检查事实 gate、来源闭包和跨目标任务图；Core-2 以路径攻击和 hidden oracle 检查 false promotion；Core-3 检查风险激活的成本/证据非劣效；Core-4 检查 kill/resume、blocker、obsolete 与物理边界。正式样本、阈值和统计见 [预注册协议](experiment_protocol.md) |
| **突出贡献** | 不是“更多 Agent”，而是一个在不信任 Agent 正确性的前提下，阻止缺少安全事实、路径权限、来源闭包或必要证据的 SoC 候选获得工程效力的控制面 |
| **成立边界** | 结论相对于材料解析器、Git/文件系统、工具链、verifier soundness 和预注册故障模型；物理板、未知错误和验证器共同盲区不由理论自动消除 |

## 2. 当前行业难点

### 2.1 硬件信息不是一个干净的 target JSON

芯片软件团队面对的是数据手册、原理图、SVD、DTS、参考 SDK、板级观测和口头信息的混合体。它们具有不同权威性，常见问题包括字段缺失、版本不一致、地址或 IRQ 冲突、图片/PDF 难以机器执行，以及“参考板信息被误当成目标板事实”。传统 Agent 容易补全未知字段，从而把语言合理性误写成硬件真实性。

### 2.2 跨层任务不能靠固定流水线完整表达

Boot、BSP、驱动、RTOS、编译器、运行时、产品 API、镜像和 HIL 之间既有数据依赖，也有风险依赖。固定串行流水线会执行大量无关步骤；纯对话式多 Agent 又缺少可检查的依赖、输出、权限和停止条件。行业缺少一种能从硬件能力动态形成最小任务闭包，同时保持工程可审计性的协作模型。

### 2.3 Agent 容易自证与越权

同一个 Agent 生成代码、解释日志并宣布成功，会形成自证闭环。若没有 owned-path、隔离工作区、独立 verifier 和哈希快照，一个局部修复还可能污染其他层，成功日志也可能属于旧镜像或错误设备。

### 2.4 软件来源“能找到”不等于“能组合”

候选仓库可能架构匹配但许可证不可构建，可能覆盖驱动却与主 BSP 的 OS ABI 或媒体 ABI 不兼容，也可能依赖未锁定的 submodule 或 repo manifest。单仓库检索分数无法保证整个软件栈的一致性与可复现性。

### 2.5 失败是正常状态，但工程状态难以恢复

外部网络、工具链、构建容器、设备和 Agent 都可能中断。若任务没有稳定输入哈希、失败签名、阻塞原因和重试预算，恢复只能从头执行；若无区分 `failed` 与 `blocked`，系统还会对缺少物理板之类的外部条件进行无意义修复。

### 2.6 局部通过不蕴含端到端正确

schema、自测试、编译、QEMU、物理板和长期压力验证覆盖不同声明。项目中的真实经验表明，即使局部解析器测试通过，完整材料仍可能因标识符、schema 或跨阶段约束而失败。行业常见的“测试通过率”无法说明具体声明是否具备足够证据。

### 2.7 行业真实性证据：文献与当前仓库的交叉核对

| 现实问题 | 外部行业证据 | 当前仓库直接观测 | 对论文主张的约束 |
|---|---|---|---|
| Agent 已能完成仓库任务，但角色数量不等于可靠性 | MetaGPT/ChatDev 已有固定角色流程；SWE-agent/OpenHands 已有仓库工具与沙箱；Agentless 表明简化流程也可竞争 [@hong2024metagpt; @qian2024chatdev; @yang2024sweagent; @wang2025openhands; @xia2025agentless] | `engine/control.py:350-460` 已有隔离 worktree、owned-path、symlink 检查、候选验证、集成后再验证和 promotion commit | ADAM 不能把多 Agent、工具或沙箱单列为创新；必须用 false promotion 证明组合 gate 的增量价值 |
| 硬件材料缺失/冲突必须形成 blocker | 现有通用 Agent benchmark 以 issue/repository 为输入，没有提供硬件事实授权语义 [@jimenez2024swebench; @yang2024sweagent] | `socimage/hardware.py:376-510` 已将未解析字段、NPU command ABI、冲突和安全 basis 映射为 enabled/blocked capability | “硬件材料驱动”有真实代码基础，但只能在所有授权入口都检查 `SafeFact` 时成立 |
| 当前仍存在候选文本绕过事实 gate 的路径 | 这是项目特有实现事实，不由外部文献替代 | `engine/control.py:103-115` 同时接受 `enabled_capabilities` 和 observation `material_selectors`；后者可把候选文本加入 roots | 该路径在修复或降级为 investigation-only 前，定理 1必须保留唯一入口前提，Core-1 必须把它作为反例 |
| provenance 不等于软件栈可组合 | in-toto、TUF、SLSA 和可复现构建已解决步骤/身份/来源的一部分 [@torresarias2019intoto; @samuel2010tuf; @slsa2026spec; @lamb2022reproducible] | `engine/source_discovery_tools.py:380-507` 实际检查 license decision、architecture、锚点角色、OS/media ABI 和 adapter；后续还锁 selected paths 与 revision | 创新只能是将来源/ABI 闭包并入 Agent 任务和晋升，不能声称发明 hash 或 provenance |
| verifier 可能共同漏检 | N-version 与 oracle problem 明确指出多实现和测试 oracle 都可能相关失效或不完备 [@avizienis1985nversion; @barr2015oracle] | 当前候选/集成验证主要复用同一个 `verify_tool`；部分工具的所谓 independent verification仍共享模板、工具链和 oracle | 定理 4只能是 relative soundness；Core-2 必须测 \(F_{joint}\)，不能假定双验证漏检率是 \(p^2\) |
| 中断、blocker 和输入变化是正常工程状态 | 构建系统和 dynamic assurance 强调依赖与环境变化 [@mokhov2018buildsystems; @calinescu2018assurance] | `engine/control.py:175-305` 持久化 task/attempt/artifact/failure，恢复 running、重试 failed/blocked，并在输入变化时重置/obsolete | 恢复贡献是真实存在的系统问题，但全局终止仍依赖有限重试预算 |

## 3. 主要核心思想

ADAM 把 SoC 软件开发建模为一个**由硬件事实激活、由风险调节、由证据晋升的异构任务图**。

核心闭环为：

\[
\text{材料锁定}\rightarrow\text{事实推导}\rightarrow\text{能力激活}
\rightarrow\text{候选生成}\rightarrow\text{独立验证}\rightarrow\text{受控晋升}
\rightarrow\text{失败/运行反馈}\rightarrow\text{下一实验}.
\]

ADAM 不要求 Agent 本身可信。系统只要求：

1. 输入材料、工具、策略和任务均由哈希绑定；
2. 不安全硬件事实不能激活可执行能力；
3. 每个任务有明确依赖、所有者、owned paths、输出和 verifier；
4. Agent 在隔离 worktree 中产生候选，候选通过验证后才进入 run-local integration；
5. 证据按声明义务组合，而不是用一个模糊“置信度”代替；
6. 高风险或高证据债任务才激活额外验证和实验；
7. 失败、阻塞、恢复和过期任务是状态机中的一等状态。

因此，ADAM 的研究对象不是“多个 Agent 会不会讨论出好代码”，而是：**在 Agent 可能出错的前提下，控制面能否阻止未经证实的内容获得工程效力。**

## 4. 文章创新点

### 4.1 硬件材料驱动的 Agentic Co-Design Graph

现有多 Agent 软件工程通常从需求文本或现有代码库开始。ADAM 从不可变材料集合开始，将来源状态、未知项和冲突直接映射为能力图的启用或阻塞条件。它将“硬件事实是否足以支持软件动作”纳入多 Agent 调度语义。

### 4.2 候选权与验收权的系统性分离

Agent 可以提出补丁、源码候选、编译映射和修复方案，但不能凭自然语言输出晋升工件。验收由路径权限、schema、确定性工具、重复 verifier、哈希快照和发布/HIL gate 完成。该设计把 Agent 不可靠性从系统可信基中移出。

### 4.3 事实状态与证据义务的双层语义

ADAM 区分：

- `authoritative/standard_derived/board_observed/...`：描述输入事实能否用于激活能力；
- E0-E6 及义务覆盖向量：描述某个输出声明经过了哪些验证。

这避免把“来源权威”和“软件已验证”混为同一个置信度。

### 4.4 一致性锚点与传递来源闭包

源码选择不是逐组件贪心，而是先选择覆盖 boot、BSP、driver framework 和 image tool 的锚点，再检查其他角色与锚点的 OS/media ABI，最后锁定许可证证据、被选路径和传递依赖。该机制把供应链可构建性纳入 Agent 计划。

### 4.5 证据债务与风险激活

为每个声明显式计算未覆盖义务的证据债务，并将硬件不确定性、跨层耦合、失效严重性和外部暴露组合成风险。系统只激活能够降低当前债务的最小验证子图，而不是让所有 Agent 无条件参与。

### 4.6 面向恢复的可审计状态机

任务状态、输入哈希、尝试、失败签名、工件哈希、阻塞原因和晋升提交写入持久化状态。输入变化使旧任务 `obsolete`，中断任务可恢复为 `pending`，稳定失败可路由给明确责任域。

## 5. 数学理论

### 5.1 基本对象

材料集合及其锁为：

\[
M=\{m_1,\ldots,m_n\},\qquad
\lambda=\operatorname{Sort}\{(Hash(m_i),|m_i|,kind(m_i))\}_{i=1}^{n}.
\]

Hardware IR 为事实集合 \(H=\{f_j\}\)，事实安全谓词沿用统一框架：

\[
SafeFact(f_j)\iff q(f_j)\in\{authoritative,standard\_derived,board\_observed\}.
\]

Agent 定义为：

\[
a_i=(K_i,O_i,U_i,V_i),
\]

其中 \(K_i\) 是能力集合，\(O_i\) 是可修改路径集合，\(U_i\) 是可调用工具集合，\(V_i\) 是其输出所需 verifier 集合。

任务定义为：

\[
\tau=(id,c,a,D,h,O,Y,v,s,n,b),
\]

其中 \(c\) 是目标能力，\(a\) 是所有者，\(D\) 是依赖，\(h\) 是输入哈希，\(O\) 是 owned paths，\(Y\) 是预期输出，\(v\) 是 verifier，\(s\) 是状态，\(n\) 是尝试次数，\(b\) 是 blocker。

任务状态空间为：

\[
\mathbb{S}_\tau=\{pending,running,passed,failed,blocked,obsolete\}.
\]

Agentic Co-Design Graph 定义为：

\[
G=(V_T,E_D,E_R,E_V),
\]

其中 \(E_D\) 是硬依赖边，\(E_R\) 是风险触发边，\(E_V\) 是候选到 verifier 的证据边。

### 5.2 能力激活与最小依赖闭包

能力 \(c\) 的硬件前提集合为 \(Req(c)\)。基础激活规则：

\[
Enabled_H(c)\iff \forall f\in Req(c),\ SafeFact(f)\land Predicate_c(value(f)).
\]

给定请求能力集合 \(C_0\)，需要执行的基础任务集合为：

\[
T_0=DepClosure(C_0\cup\{c\mid Enabled_H(c)\}).
\]

材料文本选择器只能触发候选调查，不得替代 `Enabled_H` 对可执行能力的事实检查。

### 5.3 风险模型

对任务 \(\tau\) 定义四个归一化分量：失效严重性 \(S_\tau\)、事实/证据不确定性 \(U_\tau\)、跨层耦合度 \(C_\tau\)、物理或供应链暴露 \(X_\tau\)。

\[
\rho(\tau)=\operatorname{clip}(w_sS_\tau+w_uU_\tau+w_cC_\tau+w_xX_\tau,0,1),
\quad \sum w_*=1.
\]

风险激活子图为：

\[
G_\tau^*=DepClosure(\{owner(\tau)\}\cup Trigger(\rho(\tau),type(\tau),Debt(\tau))).
\]

其中 `Trigger` 是策略函数。例如涉及物理写入时必须加入 VerificationAgent，涉及许可证/签名时加入 SecurityAgent，超过高风险阈值时加入 verifier diversity。当前项目已经实现基于硬件事实的能力激活；上述风险激活是论文需要新增并消融验证的理论层。

### 5.4 证据债务和实验选择

令未满足义务集合为 \(U_t\)，候选实验 \(x\) 的结果随机变量为 \(Y_x\)。实验价值定义为：

\[
J(x\mid X_t)=
\frac{
\alpha\,\mathbb{E}[Debt_t-Debt_{t+1}\mid x]
+\beta I(\Theta;Y_x\mid X_t)
+\gamma Reuse(x)
}{Cost(x)+\epsilon}
-\delta Irreversibility(x).
\]

选择规则为：

\[
x_t^*=\arg\max_{x\in Feasible(X_t,B_t)}J(x\mid X_t).
\]

其中物理刷写、设备复位等不可逆或高风险动作只有在唯一设备绑定和写前策略满足时才属于 `Feasible`。

### 5.5 候选执行与晋升规则

设候选补丁为 \(p\)，任务 owned paths 为 \(O_\tau\)，两次验证分别为候选工作区验证 \(V_c\) 和集成树验证 \(V_i\)。晋升谓词为：

\[
Promote(p,\tau)\iff
Changed(p)\subseteq O_\tau
\land NoSymlink(p)
\land Outputs(p)=Y_\tau
\land V_c(p)=pass
\land ApplyCheck(p,I_t)=pass
\land V_i(I_t\oplus p)=pass.
\]

晋升后的工件按内容寻址：

\[
Artifact(y)=(Hash(y),path(y),|y|,\tau,attempt,kind).
\]

### 5.6 核心定理与证明路线

**定理 1：不安全事实不激活。** 若 `Enabled_H` 是能力激活的唯一入口，且每个 `Req(c)` 的 basis 路径经过 `SafeFact` 检查，则任何仅由 `candidate`、`unknown` 或 `conflict` 支撑的能力均不会被激活。

*证明路线*：对 `Enabled_H` 合取项直接反证。若能力被激活，则所有 basis 均满足 `SafeFact`，与存在唯一不安全 basis 矛盾。需要额外验证所有 registry capability 都完整声明 `Req(c)`。

**定理 2：路径权限保持。** 假设 Git diff 完整枚举候选的所有文件变化，路径归一化和 symlink 检查可靠。若 `Promote(p,τ)` 成立，则晋升造成的文件变化均位于 \(O_\tau\)。

*证明路线*：由 `Changed(p) subset O_tau` 和 `NoSymlink(p)` 得到候选作用域；`git apply --check` 保证实际应用与补丁一致，因此集成变化不越界。

**定理 3：依赖因果保持。** 若 `ready(τ)` 仅在 \(D_\tau\subseteq Passed\) 时返回任务，则任一 `passed` 任务的所有传递依赖在它开始执行前均已 `passed`。

*证明路线*：对 DAG 拓扑深度归纳。深度 0 显然成立；深度 \(k\) 任务 ready 时直接依赖已通过，由归纳假设其传递依赖也已通过。

**定理 4：相对验证器的晋升可靠性。** 假设 \(V_c,V_i\) 对声明 \(c\) 在适用域 \(\Omega_c\) 内是 sound 的，输入和输出哈希未被破坏，且 `Promote(p,τ)` 成立，则晋升工件满足 \(c\)。

*证明路线*：候选验证排除候选内错误；应用后验证排除 patch 上下文变化；哈希绑定确定验证对象即晋升对象。该结论是 relative soundness，不声称验证器之外的全功能正确。

**命题 1：证据债务单调性。** 在固定输入哈希、有效证据只追加且已验证工件不被破坏时，\(Debt_{t+1}\le Debt_t\)。输入变化、证据撤销或工件完整性失败会开启新状态版本，不属于该单调区间。

**定理 5：单次调度终止。** 若任务图有限且无环、每个 ready task 在有限时间内返回 `passed/failed/blocked`，一次 `run_tasks` 不在内部无限重试，则该次调度在有限步内终止。

*证明路线*：每次 wave 至少把一个 `pending` 任务转为终态；任务数有限。跨 `resume` 的全局终止还要求有限重试预算，当前可重试 blocker 需要在完整理论实现中加入显式预算。

### 5.7 理论不保证的内容

- 两次运行相同材料必然产生相同网络搜索候选；可复现性从 source lock 形成后开始。
- 同一模块中的 generator/verifier 是组织意义上的独立实现。当前实现是独立重跑，强独立性需要 verifier diversity。
- 所有冲突都能自动解决。ADAM 的安全行为可以是稳定 `blocked`。
- Agent 能找到全局最优修复。ADAM 只约束候选的工程效力。

## 6. 四个核心实验如何验证

所有验证收敛为四个论文级核心实验。原来的事实变异、来源闭包、路径攻击、局部测试反例、故障恢复和平台测试保留为核心实验内部的预注册子测试，不再作为同级实验。随机 Agent/LLM 条件报告多次独立运行、效果量、置信区间和失败分布，不预填虚构结果。

### 核心实验 1：硬件事实、来源闭包与任务图安全

**研究问题**：非安全事实、冲突材料或非法来源组合能否被阻止进入 production capability 和 build closure？

**子测试**：事实状态/冲突传播、材料篡改、许可证与 OS/media ABI、submodule/manifest/revision 闭包、跨 QEMU/RVV/K230 合同的任务图差异。

**对照组**：文本直接生成 target、来源多数投票、逐组件最高分、只锁顶层 commit、去掉 `SafeFact` gate。

**主端点**：逐类 unsafe capability activation 和 invalid closure acceptance 均为 0；安全 blocker 无漏报；task-graph macro-F1 不低于 0.95。

**理论对应**：共同验证定理 1、来源闭包和材料驱动图。任何候选文本直接授权生产能力、禁用许可证或 ABI 冲突进入闭包，均否定安全主张。

### 核心实验 2：候选隔离、证据对齐与安全晋升

**研究问题**：越权修改或仅在候选环境通过的错误工件能否被阻止晋升？

**子测试**：absolute/`..`/symlink/rename/submodule/binary patch 路径攻击；candidate-pass/integration-fail 反例；claim-obligation-evidence 对齐；两个 verifier 的共同盲区。

**对照组**：共享工作区、只做事后 diff、单次 candidate verifier、仅 integration verifier、完整两阶段晋升。

**主端点**：关键/高严重度 false promotion、路径逃逸和晋升污染半径均为 0；claim-evidence recall=1；共同漏检单独报告。

**理论对应**：验证路径权限、债务闭合和相对 verifier 晋升定理。若 `F_joint>0`，必须撤回实现满足 soundness 前提的声明。

### 核心实验 3：风险驱动的多 Agent 协作有效性

**研究问题**：按风险和未满足义务激活 Agent，能否在不降低证据完整性的前提下降低成本？

**任务集**：从真实 commit、失败签名、review 或集成事件锚定的 160 项中分层抽取 96 项，每条件 5 个 seed；覆盖 boot、driver、source、compiler、runtime、image 和 HIL，使用独立隐藏 oracle，不使用 toy repository、stub tool 或凭空合成任务。

**对照组**：单 Agent、固定全角色图、静态 DAG、Agentless 类简化流程、去掉 evidence debt/risk activation、完整 ADAM。

**主端点**：先检验 evidence completion 非劣，下界不低于 -3 个百分点；再检验 calls 中位数至少下降 20%；false promotion 不得增加。

**理论对应**：只在“证据非劣 + 成本优效 + 安全不退化”同时成立时支持风险激活创新。

### 核心实验 4：可恢复端到端执行与跨平台边界

**研究问题**：系统能否在中断、工件失效、设备缺失和目标变化后保持正确状态，并给出可解释终态？

**子测试**：kill/timeout/network/build failure、artifact 篡改、输入 hash 变化、稳定 blocker、尝试预算、resume；QEMU、RVV、NPU-ABI-unknown/known 与 K230/CanMV HIL gate。

**对照组**：无状态脚本、只保存日志、state.db 恢复；无设备绑定和完整绑定的 HIL 流程。

**主端点**：状态不变量违反为 0；重复工作中位数下降至少 50%；未知 NPU ABI 只产生 blocker；物理写入归属错误为 0。

**理论对应**：验证有限恢复终止、跨平台区分和物理边界。没有绑定设备时正确结果必须是 `blocked`。

### 6.1 统计与报告

- 二元安全指标报告 Wilson 区间，并单列每个 false acceptance；
- 连续成本/时延报告中位数、IQR 和 bootstrap 置信区间；
- 配对任务采用配对置换检验或 Wilcoxon 检验；
- 多目标、多缺陷类型分别报告，不只给总体平均；
- 所有失败样例、材料哈希、source lock、工具版本和 run ID 随 artifact 发布。

## 7. 每篇文章的突出贡献

ADAM 的突出贡献应浓缩为以下四点：

1. **提出硬件材料驱动的 Agentic Co-Design Graph。** 在本文检索覆盖的相关工作范围内，把硬件事实状态、能力激活、跨层任务依赖和专业 Agent 权限统一为可执行图模型。
2. **提出候选权/验收权分离的证据治理机制。** 在不假设 Agent 可靠的前提下，通过隔离、owned paths、确定性 verifier、哈希工件和晋升状态机限制 Agent 输出的工程效力。
3. **提出证据债务与风险激活理论。** 用声明义务覆盖而非单一置信度决定下一实验，并以最小风险子图降低验证成本。
4. **把来源闭包和可恢复执行纳入多 Agent 协同设计。** 将许可证、ABI、传递依赖、失败签名、阻塞和恢复视为芯片软件协同的核心理论对象，而不是外围工程脚本。

论文最强且最可信的主张不是“ADAM 自动完成所有芯片软件”，而是：

> 在明确的工具可信基和故障模型下，ADAM 使不可靠 Agent 能够参与 SoC 软件候选生成，同时阻止缺少安全硬件事实、路径权限或必要证据的候选被晋升。

## 8. 与另外两篇的边界

ADAM 向 CECAP 提供 Hardware IR、source lock、任务输入哈希和验证执行环境；它不证明编译计划最优。ADAM 接收 AIRTOS trace 并选择后续实验；它不证明运行时 deadline。CECAP 和 AIRTOS 产生的证据必须作为新的账本条目进入下一状态，不能形成同轮自证循环。

当前项目中 `soc_image.py`、`socimage/`、`engine/control.py`、`engine/source_discovery_tools.py`、`engine/capabilities.json` 和 HIL 工具构成该理论的实现基础；旧的 `chip_agents.py` 八角色链仅作为历史对照，不应被描述为当前生产入口。

当前实现还有一个与定理 1直接相关的缺口：`engine/control.py` 除了读取 `reference_profile.enabled_capabilities`，也会根据原始材料 observation 的 `material_selectors` 激活 capability；注册表中的 `source_stack_image` 可由 `k230` 文本触发。这条路径适合启动源码调查，但尚不满足“可执行能力只能由安全事实激活”的唯一入口假设。正式实现应将它拆成候选调查能力，或要求 material selector 结果再次通过安全身份事实和板级配置验证；Core-1 必须包含这一反例。

## 9. 文献基础、创新边界与实验基线

完整检索方法、78 个来源的核验矩阵和跨论文矛盾分析见 `../literature_review.md`，共享 BibTeX 见 `../references.bib`。

### 9.1 相关工作分层

**多 Agent 软件工程。** AutoGen、MetaGPT、AgentVerse 和 ChatDev 已经覆盖可编程对话、SOP、角色分工和动态组合；SWE-agent、OpenHands 与 SWE-bench 已经覆盖终端/仓库交互、沙箱和真实 issue benchmark [@wu2023autogen; @hong2024metagpt; @chen2024agentverse; @qian2024chatdev; @yang2024sweagent; @wang2025openhands; @jimenez2024swebench]。因此，“多个 Agent 协作写代码”“使用工具”“在沙箱中运行”均不能作为 ADAM 的独立创新。Agentless 还表明复杂 agent loop 并非获得强结果的必要条件 [@xia2025agentless]。

**供应链与构建 provenance。** in-toto、TUF、Sigstore、SLSA、SSDF 和可复现构建已分别处理供应链步骤证明、密钥失陷、签名透明度、构建来源分级与安全开发流程 [@torresarias2019intoto; @samuel2010tuf; @newman2022sigstore; @slsa2026spec; @nist2022ssdf; @lamb2022reproducible]。ADAM 使用这些机制，但贡献不能退化为“给产物加 hash”。

**验证与 assurance。** Runtime verification、dynamic assurance case、N-version 和 oracle problem 表明：监测只覆盖已声明性质，验证实现可能共同失效，测试 oracle 也可能不完备 [@leucker2009runtimeverification; @calinescu2018assurance; @avizienis1985nversion; @barr2015oracle]。因此定理 4 必须保持 `relative to verifier`，双重验证也不能假定统计独立。

### 9.2 文献约束后的创新边界

ADAM 的可辩护贡献是以下四项的统一，而不是任一单项：

1. 从异构硬件材料和非线性事实状态推导 capability，而不是从 issue 文本或预写 target 直接启动代码生成；
2. 用 isolated worktree、owned-path、symlink/rename 防绕过、候选/集成双验证和内容寻址晋升控制 Agent 输出的工程效力；
3. 把来源闭包、ABI coherence 和声明索引 evidence debt 纳入同一个任务图；
4. 用风险和未覆盖义务激活 verifier 子图，并把 `failed/blocked/obsolete` 作为可恢复状态。

建议新颖性措辞为：

> 在本研究覆盖的多 Agent 软件工程、软件供应链和 runtime assurance 文献中，尚未发现一个系统将硬件材料事实状态、路径级 Agent 权限、传递来源闭包和声明证据债务统一用于 SoC 软件工件晋升。

该措辞不等于无条件“首次”，正式投稿前仍需更新 2025-2026 文献。

### 9.3 数学模型补强

证据账本可进一步写为 claim-evidence 二部图：

\[
G_{CE}=(\mathcal C,\mathcal E,R),\qquad
(c,e)\in R\iff Valid(e,c,X)\land \Omega_c\subseteq\Omega_e.
\]

只有 `Promotable(c,E,X)` 对该声明成立，工件才可晋升。Proof-carrying code 提供“生产者携带、消费者检查”的理论先例 [@necula1997pcc]，但 ADAM 中的 schema/build/diff/HIL 多数是经验验证证据，不能统一称为 formal proof。

为验证 verifier diversity，实验应估计共同漏检率：

\[
F_{joint}=\Pr[V_c=pass\land V_i=pass\mid c=false],
\]

而不是默认两个 verifier 独立并写成单次漏检率的平方。

### 9.4 对照组与新增实验要求

- **Agent 基线**：单 tool-agent、MetaGPT/ChatDev 类固定角色、SWE-agent/OpenHands 类仓库代理、Agentless 类简化流程；使用相同模型、工具、token/时间预算。
- **治理基线**：无 gate、test-only gate、in-toto/SLSA provenance-only、静态全角色图、ADAM 完整方法。
- **任务来源**：以 SWE-bench 的真实 issue 设计原则构建 SoC 专属 benchmark，但 hidden oracle 必须覆盖 boot/BSP/driver/compiler/runtime/image 的跨层声明，而非直接搬用 Python issue [@jimenez2024swebench]。
- **新增指标**：claim-evidence precision/recall、共同漏检率、false promotion severity、候选污染半径、blocker calibration、恢复后重复工作量。
- **否定性报告**：逐个列出 false promotion、越权变更和错误 capability activation；平均成功率不能抵消任何安全接纳失败。

### 9.5 文献修订后的突出贡献

Paper 1 最强贡献应聚焦为：**一个允许不可靠 Agent 参与候选生成、但把工程效力保留给来源安全、权限检查和声明级证据的 SoC 软件控制面。** 它不是通用软件 Agent 排行榜论文，也不是供应链签名协议论文；ADAM-CoDesignBench 必须验证这套组合机制在 SoC 跨层任务上的必要性。

## 10. 逐项创新性证明义务与实验锁

完整执行方案见 [ADAM 预注册实验协议](experiment_protocol.md)。下表不是宣传性比较，而是每个创新点必须独立完成的证明义务；任一行未通过，只撤回该行主张，不能用其他实验的成功补偿。

| ID | 创新点 | 最近先例与已解决内容 | ADAM 必须证明的新差异 | 严谨性的必要性 | 直接证伪条件 | 协议实验 |
|---|---|---|---|---|---|---|
| N1 | 硬件材料驱动 capability graph | AutoGen/MetaGPT/AgentVerse 已有角色与拓扑 [@wu2023autogen; @hong2024metagpt; @chen2024agentverse] | capability 的授权 basis 来自带状态和 provenance 的 Hardware IR，而非需求文本或 Agent 推断 | 错误字段可能触发寄存器、镜像或 NPU 动作 | candidate/unknown/conflict 单独启用可执行 capability | Core-1 |
| N2 | 候选权/验收权分离 | SWE-agent/OpenHands 已有沙箱和仓库工具 [@yang2024sweagent; @wang2025openhands] | owned-path、防路径绕过、候选/集成双检查与内容寻址晋升共同限制工程效力 | 沙箱成功不保证合入后或共享树正确 | 越权/hidden-oracle 错误候选被 promoted | Core-2 |
| N3 | 事实状态与 claim-indexed evidence product | PCC、runtime verification、assurance case 已区分生产者与检查者 [@necula1997pcc; @leucker2009runtimeverification; @calinescu2018assurance] | 来源授权和输出验证分成两套语义；证据按义务、hash、domain 绑定 | 标量置信度会使 build、numeric、physical 相互替代 | 缺义务、冲突证据或错误域仍可晋升 | Core-2、Core-3 |
| N4 | 一致性锚点与传递来源闭包 | in-toto/SLSA/TUF 已有 provenance 与供应链角色 [@torresarias2019intoto; @slsa2026spec; @samuel2010tuf] | 将许可证、OS/media ABI、选中路径与传递依赖共同纳入 source solver | 顶层 commit 已锁不代表整个栈可构建、可分发 | 漏锁依赖、禁用许可证或 ABI 冲突进入 build closure | Core-1 |
| N5 | 风险激活 verifier graph | 动态角色组合与 Agentless 已说明复杂协作不总是必要 [@chen2024agentverse; @xia2025agentless] | 按失效严重性和未覆盖义务选择 verifier 子图，并保持必要证据 | 全角色成本高，静态简化又可能漏验 | 调用下降伴随 evidence completion 越界下降或 FPR 上升 | Core-3 |
| N6 | 持久失败/阻塞/过期恢复 | 构建系统和供应链记录已有依赖/步骤状态 [@mokhov2018buildsystems; @hassanshahi2023macaron] | 输入哈希、失败签名、blocker、尝试预算、artifact 与晋升提交统一进状态机 | 网络、工具和板卡中断不可避免，错误复用会污染证据 | interrupted 当 passed，输入变化后旧 passed 仍有效，或无限重试 | Core-4 |

### 10.1 论文级验收规则

ADAM 的核心安全结论要求 N1、N2、N3 和 N4 的关键 false acceptance 全部为零；N5 和 N6 分别支撑效率与恢复贡献。协议规定每个关键负例类别 300 个，并逐类报告单侧 exact 区间。零观察只支持测试域内实现证据，不证明 verifier 对所有未知错误 sound。

当前 `material_selectors` 可从候选文本触发 `source_stack_image` 是 N1 的已知实现反例入口。在该路径被收紧为 investigation-only 并通过 Core-1 前，定理 1只能保持为“若 `Enabled_H` 是唯一授权入口”的条件定理，摘要和贡献不得写成已实现的无条件能力。

### 10.2 预注册结论边界

- N1-N4 全部通过：可写“在预注册 SoC 材料、路径、来源和 hidden-oracle 缺陷域内阻止关键错误晋升”。
- 任一 N1-N4 失败：必须写“当前实现存在反例”，并撤回安全晋升主张；任务成功率不能抵消。
- N5 通过：只可写风险激活在证据非劣前提下降低调用；未通过时保留治理结果，撤回效率主张。
- N6 通过：只可写冻结故障模型内恢复一致且减少重做；不能外推到任意进程、文件系统或硬件故障。

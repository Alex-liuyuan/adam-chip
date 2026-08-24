# ADAM-CECAP-AIRTOS 文献综述、证据矩阵与创新边界

## 0. 结论先行

本综述纳入 78 个可追溯来源。材料包括同行评审论文、已被正式会议接收且可由 arXiv 核验的版本、标准/官方技术文档，以及一个截至 2026-08-03 的新近预印本。完整 BibTeX 见 `references.bib`。

文献支持把项目拆成三篇论文，但也要求收紧主张：

1. **ADAM 的创新不应写成“多 Agent 自动开发芯片软件”。** AutoGen、MetaGPT、AgentVerse、ChatDev、SWE-agent 和 OpenHands 已覆盖角色协作、工具使用、沙箱与仓库任务。ADAM 可成立的差异是：从硬件材料状态推导能力，以 owned-path 和来源闭包限制候选，以声明义务和独立 verifier 决定晋升，并把失败/阻塞纳入持久状态机。
2. **CECAP 的创新不应写成“异构 AI 编译或自动调优”。** TVM、AutoTVM、Ansor、TensorIR、TASO、Collage、DORY、Deeploy 等已覆盖 IR、搜索、后端放置和极端内存部署。CECAP 可成立的差异是：把适用域、fallback、多维证据和硬件事实来源状态合并进运行时可拒绝的计划对象。
3. **AIRTOS 的创新不应写成“首次调度异构 AI/NPU”。** PTask、StarPU、Legion、PREMA、Planaria、V10、MoCA、DREAM 等已覆盖异构任务、NPU 多租户、QoS 和动态调度。AIRTOS 可成立的差异是：将编译计划证据和适用域与 WCET、DAG、内存 lease、coherency、epoch 恢复做联合准入，并保持 trace 不自证。

三篇共享的真正理论主线不是一个更大的“置信度”，而是一个**声明索引的证据产品空间**：来源真实性、静态合法性、编译/链接、数值一致性、虚拟执行、物理执行、时限、长期压力和供应链证据互不替代。

## 1. 检索与筛选方法

### 1.1 研究问题

- **RQ1 / ADAM**：已有 LLM 多 Agent 软件工程、软件供应链和 assurance 工作中，哪些机制已经覆盖协作、隔离、来源和验证？还缺少什么硬件材料驱动的工程效力控制？
- **RQ2 / CECAP**：已有 ML 编译器、TinyML 部署、自动调优和编译验证工作中，哪些机制已经覆盖合法空间、搜索、内存和语义验证？还缺少什么可被运行时拒绝的计划合同？
- **RQ3 / AIRTOS**：已有实时调度、异构运行时、NPU 多租户和 runtime assurance 工作中，哪些机制已经覆盖 deadline、DAG、内存和恢复？还缺少什么证据边界联合准入？

### 1.2 数据源与日期

- 检索日期：2026-08-03。
- 学术索引：OpenAlex、Crossref、Semantic Scholar、arXiv export API。
- 一手技术资料：USENIX/ACM/IEEE/ACL 元数据链接；NIST、SLSA、Linux、Apache TVM、Zephyr、RT-Thread 官方资料。
- 本地原始工程资产：`third_party/tvm`、`third_party/tflite-micro`、`third_party/executorch`、`third_party/llvm-project`、`third_party/rt-thread` 和 `third_party/zephyr`，用于确认项目实际依赖的接口与实现方向。
- 早期代理故障：默认代理对 OpenAlex、Crossref、Semantic Scholar、DOI、arXiv 和 USENIX 返回 TLS/502；绕过该代理后恢复访问。失败过程不计为核验。

### 1.3 检索式

Broad search 使用以下 15 个英文检索簇，每簇读取 OpenAlex 前 8 项，形成 120 个初始候选槽位；随后以精确题名、DOI 和 arXiv ID 解析正式版本并去重。

```text
"LLM multi-agent software engineering"
"software engineering agents repository issue resolution benchmark"
"software supply chain provenance in-toto reproducible builds"
"runtime verification assurance cases software systems"
"proof carrying code translation validation"
"machine learning compiler autotuning heterogeneous edge"
"tensor program auto scheduling Ansor TensorIR"
"neural network deployment microcontrollers memory compiler"
"heterogeneous deep learning compiler backend integration"
"compiler translation validation Alive2 CompCert"
"real-time scheduling neural processing unit multi tenancy"
"real-time DAG scheduling heterogeneous resources"
"predictable machine learning model serving Clockwork"
"mixed criticality runtime assurance learning enabled systems"
"operating system abstractions GPU heterogeneous task runtime"
```

精确补检覆盖 SWE-bench/SWE-agent/OpenHands、in-toto/TUF/SLSA、TVM/MLIR/Ansor/TensorIR/Collage、MCUNet/DORY/Deeploy、Liu-Layland/processor demand、PTask/StarPU/Legion、PREMA/Planaria/V10/MoCA/DREAM 等题名。

### 1.4 纳入与排除

**纳入条件**：

- 直接支撑三篇论文的问题、方法、定理前提、对照组或实验指标；
- 正式同行评审版本优先；只有快速变化且无更合适正式版本时保留预印本；
- 基础理论不限年份，Agent/编译/NPU 系统状态以 2023-2026 为重点；
- 官方文档只支撑规范语义、接口和本项目技术上下文，不支撑性能优势。

**排除条件**：

- 只因关键词命中但与研究问题无关的论文；
- 无法由 DOI、arXiv、权威索引或官方项目定位确认存在的条目；
- 二手博客、厂商营销页和没有方法细节的新闻；
- 同一论文的预印本与正式版重复时，优先保留正式版；
- OpenAlex 搜索中明显异常的高引元数据或题名/DOI错配。

本工作是面向理论设计的 scoping review，不是声称穷尽所有文献的 PRISMA 系统综述。API 使用 top-k 检索和精确解析混合方式，因此除“120 个初始候选槽位”和“78 个最终来源”外，不伪造不可复算的 PRISMA hit 数。

### 1.5 核验等级

- **A**：同行评审、权威 venue、元数据匹配，且方法与当前声明直接相关。
- **B**：可信正式论文或高相关预印本，但适用环境与本项目有明显差异，或只核对了摘要/元数据。
- **C**：官方规范/项目文档，或尚未同行评审的新近材料；仅用于规范事实和背景。
- **Level III**：有系统实现与受控实验的技术研究；不是随机试验，但属于系统领域的主要实证形式。
- **Level V**：系统综述/综合性 survey。
- **Level VI**：单系统描述、预印本或案例性研究。
- **Level VII**：标准、规范、项目文档或专家材料。

等级是“对当前声明的适配度”，不是把系统论文错误套入医学证据金字塔。所有系统论文都存在作者评估自己系统的 intellectual COI；官方规范存在机构 COI。未从元数据发现需要排除的未披露财务冲突，也未发现可疑/掠夺性 venue。

## 2. 来源质量与用途矩阵

表中 `M/A/O` 分别表示元数据核验、原始摘要/论文入口核验、官方规范或本地原始项目资料核验。COI 的 `I` 表示作者评价自己的方法，`Inst` 表示机构维护自己的规范；这两类是常见且需在实验复现中控制的利益关系，不等同于学术不端。

### 2.1 ADAM 文献簇

| Key | Level/Grade | 核验 | 主要用途 | COI |
|---|---|---|---|---|
| `he2025llmmas` | V/A | M+A | 多 Agent SE 综述与未解决问题 | I |
| `wu2023autogen` | VI/B | A | 可编程多 Agent 对话基础设施 | I |
| `hong2024metagpt` | III/A | A | SOP/角色流水线与级联幻觉动机 | I |
| `chen2024agentverse` | III/B | A | 动态角色组合与涌现行为 | I |
| `qian2024chatdev` | III/A | A | 设计-编码-测试多 Agent 基线 | I |
| `jimenez2024swebench` | III/A | A | 真实仓库问题 benchmark | I |
| `yang2024sweagent` | III/A | A | Agent-computer interface 与工具基线 | I |
| `xia2025agentless` | III/A | M | 复杂 agent loop 的反证/简化基线 | I |
| `wang2025openhands` | III/A | A | 沙箱、终端、仓库交互平台基线 | I |
| `ronanki2025trustworthy` | VI/B | M | 人-Agent trust 边界 | I |
| `torresarias2019intoto` | III/A | M | 供应链步骤证明与布局约束 | I |
| `newman2022sigstore` | III/A | M | 工件签名、透明日志与身份 | I |
| `samuel2010tuf` | III/A | M | 更新链路密钥失陷与角色分离 | I |
| `lamb2022reproducible` | VI/A | M | 可复现构建与供应链完整性 | I |
| `mokhov2018buildsystems` | VI/A | M | 构建依赖语义与可组合模型 | I |
| `avizienis1985nversion` | III/A | M | verifier diversity 与相关失效 | I |
| `leucker2009runtimeverification` | V/A | M | 运行监测不是全功能证明 | I |
| `calinescu2018assurance` | III/A | M | 动态 assurance case 与运行时变化 | I |
| `barr2015oracle` | V/A | M | 测试 oracle 不完备性 | I |
| `okafor2022sok` | V/A | M | 供应链安全属性体系 | I |
| `ladisa2023sok` | V/A | M | 开源供应链攻击分类 | I |
| `hassanshahi2023macaron` | III/A | M | 逻辑化供应链 assurance | I |
| `necula1997pcc` | III/A | M | 生产者携带、消费者检查的理论先例 | I |
| `nist2022ssdf` | VII/A | O | 安全开发流程规范 | Inst |
| `slsa2026spec` | VII/A | O | 构建 provenance 分级规范 | Inst |

### 2.2 CECAP 文献簇

| Key | Level/Grade | 核验 | 主要用途 | COI |
|---|---|---|---|---|
| `chen2018tvm` | III/A | A+O | 图/算子优化与跨后端编译基线 | I |
| `lattner2021mlir` | III/A | M+O | 多层 IR 与 progressive lowering | I |
| `rotem2019glow` | III/A | A | 强类型 IR、静态内存和异构 lowering | I |
| `chen2018autotvm` | III/A | A | 学习型 cost model 与 schedule search | I |
| `zheng2020ansor` | III/A | A | 大搜索空间自动生成与搜索策略 | I |
| `feng2023tensorir` | III/A | A+O | tensorized primitive 的可调度抽象 | I |
| `jia2019taso` | III/A | M | 图级等价替换与全局优化 | I |
| `jeon2023collage` | III/A | A | 多后端自动放置和集成 | I |
| `zheng2020flextensor` | III/A | M | 异构 schedule 探索 | I |
| `ansel2014opentuner` | III/A | M | 通用 ensemble autotuning 基线 | I |
| `deb2002nsgaii` | III/A | M | 多目标 Pareto 搜索基线 | I |
| `knowles2006parego` | III/A | M | 昂贵多目标优化基线 | I |
| `lin2020mcunet` | III/A | A | TinyNAS/TinyEngine 的设备约束联合设计 | I |
| `david2021tflm` | III/A | A+O | 静态 arena 和碎片化嵌入式运行时 | I |
| `burrello2021dory` | III/A | A | scratchpad、tiling、DMA 与极端内存 | I |
| `scherer2024deeploy` | III/A | A | 异构 MCU/NPU 上端到端部署 | I |
| `liu2024tinyts` | III/A | M | TinyML 内存编译基线 | I |
| `garofalo2020pulpnn` | III/A | A | RISC-V 量化 kernel 与实测基线 | I |
| `garofalo2020xpulpnn` | III/A | M | ISA extension 与量化执行 | I |
| `moreau2019vta` | III/A | A | task-ISA、memory/compute orchestration | I |
| `banbury2021mlperftiny` | III/A | A | latency/energy/accuracy 评测规范 | Inst |
| `leroy2009compcert` | III/A | M | 形式验证编译器的高保证参照 | I |
| `pnueli1998translation` | III/A | M | 编译后 translation validation | I |
| `lopes2021alive2` | III/A | M | 有界 LLVM 变换验证基线 | I |
| `li2021dlcompiler` | V/A | A | DL compiler 设计空间综述 | I |
| `bringmann2021codesign` | III/B | M | edge AI 自动 HW/SW co-design | I |
| `vandelm2023htvm` | III/A | M | heterogeneous TinyML 放置/部署 | I |
| `nachin2026executorch` | VI/B | A+O | 最新 PyTorch-native on-device 部署 | Inst |
| `apachetvm2026byoc` | VII/A | O | BYOC 接口规范；不支撑性能结论 | Inst |

### 2.3 AIRTOS 文献簇

| Key | Level/Grade | 核验 | 主要用途 | COI |
|---|---|---|---|---|
| `liu1973scheduling` | III/A | A | RM/EDF 基础定理与假设 | I |
| `baruah1990sporadic` | III/A | A | sporadic task 可行性/processor demand | I |
| `vestal2007mixed` | III/A | A | 多 criticality 执行时间保证 | I |
| `burns2017mixed` | V/A | A | mixed-criticality 研究综述 | I |
| `topcuoglu2002heft` | III/A | A | 异构 DAG 启发式基线 | I |
| `augonnet2011starpu` | III/A | A | 异构任务与数据管理运行时 | I |
| `bauer2012legion` | III/A | A | logical region、依赖与 locality | I |
| `rossbach2011ptask` | III/A | A | 加速器作为 OS 一等对象 | I |
| `choi2020prema` | III/A | A | 可抢占 NPU 多任务/SLA 基线 | I |
| `ghodrati2020planaria` | III/A | A | 空间多租户 accelerator 分割 | I |
| `xue2023v10` | III/A | A | NPU 细粒度共享与公平性 | I |
| `kim2023moca` | III/A | A | memory-centric 多租户 QoS | I |
| `kim2023dream` | III/A | A | 动态实时多模型 edge scheduler | I |
| `xue2023npuvirt` | III/A | A | vNPU、隔离与利用率 | I |
| `yu2019salus` | III/A | M | GPU memory sharing primitive | I |
| `gujarati2020clockwork` | III/A | M | 可预测 DNN serving | I |
| `hobbs2023runtimeassurance` | V/A | A | runtime assurance/safety filter | I |
| `seto1998simplex` | III/A | M | 复杂控制器与安全基线分离 | I |
| `klein2009sel4` | III/A | M | OS 形式验证的可信基参照 | I |
| `lin2022typedag` | III/A | A | 异构 typed DAG 实时调度 | I |
| `linux2026dmabuf` | VII/A | O | DMA fence 和异步完成语义 | Inst |
| `linux2026dmaapi` | VII/A | O | DMA mapping/cache ownership 规范 | Inst |
| `zephyr2026deadline` | VII/A | O | 现有 RTOS EDF 能力对照 | Inst |
| `rtthread2026docs` | VII/A | O | 本项目 RTOS substrate；不支撑性能优势 | Inst |

## 3. Paper 1: ADAM 文献综合

### 3.1 已有工作已经解决什么

AutoGen 提供可编程对话拓扑，MetaGPT 和 ChatDev 把软件角色/SOP 编码进多 Agent 流程，AgentVerse 研究动态组合，OpenHands 和 SWE-agent 提供沙箱、终端与仓库接口 [@wu2023autogen; @hong2024metagpt; @qian2024chatdev; @chen2024agentverse; @wang2025openhands; @yang2024sweagent]。SWE-bench 则把真实 issue 修复变成可复现 benchmark [@jimenez2024swebench]。这些工作充分说明“角色 + 工具 + 执行环境”不是 ADAM 的新意。

另一条文献链已经解决工件来源和供应链证明。in-toto 描述供应链步骤与布局，TUF 处理更新密钥失陷，Sigstore 提供签名/透明记录，可复现构建、SLSA 和 NIST SSDF 约束构建来源与安全流程 [@torresarias2019intoto; @samuel2010tuf; @newman2022sigstore; @lamb2022reproducible; @slsa2026spec; @nist2022ssdf]。因此 ADAM 不能把“hash、签名、provenance”单独声明为创新。

第三条链由 runtime verification、dynamic assurance case、N-version 与测试 oracle 构成 [@leucker2009runtimeverification; @calinescu2018assurance; @avizienis1985nversion; @barr2015oracle]。它们说明：运行监测只覆盖被监测性质，多个实现可能相关失效，测试 oracle 本身可能不完整。ADAM 的双 verifier 只能给出相对可靠性，不能写成绝对正确。

### 3.2 文献留下的缺口

当前语料中没有工作同时给出以下闭环：


```text
heterogeneous hardware materials
  -> fact-state-gated capabilities
  -> path-scoped agent candidates
  -> transitive source/ABI closure
  -> claim-indexed evidence obligations
  -> independent promotion
  -> persistent blocked/failed/obsolete recovery
```

多 Agent 工作的成功端点通常是任务完成或测试通过；供应链工作关注构建步骤和工件来源；assurance 工作关注声明和运行监测。ADAM 的合理研究空位是把三者用于**材料不完备且跨 Boot/BSP/driver/compiler/runtime 的 SoC 软件候选治理**。

### 3.3 收紧后的创新点

1. `Hardware-derived activation`：不是从 issue 文本直接生成任务，而是先以非线性事实状态阻止 candidate/unknown/conflict 获得执行授权。
2. `Engineering-effect isolation`：沙箱不够，必须再有 owned-path、symlink/rename 防绕过、候选/集成双验证与内容寻址晋升。
3. `Claim-indexed evidence debt`：借鉴 PCC 的生产者/消费者分离 [@necula1997pcc]，但明确这里多数 evidence 是测试证据，不是假装成形式 proof。
4. `Risk-activated verifier graph`：动态选择能减少特定义务债务的验证子图，而不是以 Agent 数量或讨论轮数作为协作质量。

不宜使用未经系统检索证明的“首次”措辞。建议写成：**在本综述覆盖的多 Agent SE、供应链 assurance 和 runtime verification 工作中，尚未发现把上述四项统一到硬件材料驱动 SoC 软件晋升中的方法。**

### 3.4 对数学理论的补强

将原证据账本进一步解释为 claim-evidence 二部图：

\[
G_{CE}=(\mathcal C,\mathcal E,R),\qquad
(c,e)\in R\iff Valid(e,c,X)\land \Omega_c\subseteq\Omega_e.
\]

测试 oracle 文献要求把 verifier 的 soundness 作为显式假设，而不是结论。若两个 verifier 的相关失效率为 \(\rho_v\)，则“双 verifier”实验必须估计共同漏检，而不能默认独立。N-version 只提供设计启发，不提供 \(p^2\) 式独立概率保证 [@avizienis1985nversion]。

### 3.5 实验设计修订

- 任务基线加入 SWE-bench 风格的真实仓库 issue，但必须构建 SoC 专属的 hidden oracle；不能直接以通用 Python issue 代表跨层芯片任务 [@jimenez2024swebench]。
- Agent 基线至少包含单 tool-agent、SWE-agent/OpenHands 类仓库代理、MetaGPT/ChatDev 类固定角色流程，以及 Agentless 类简化搜索 [@yang2024sweagent; @wang2025openhands; @hong2024metagpt; @qian2024chatdev; @xia2025agentless]。
- 治理基线加入 `in-toto/SLSA provenance only`，用于证明 ADAM 的增益不是只有 hash 和签名。
- 新增 `claim-evidence precision/recall`、共同漏检率、false promotion severity、候选污染半径、恢复后重复工作量和 blocker calibration。
- 预注册故障类型与任务难度，报告每个 false promotion，不允许用平均完成率掩盖安全失败。

## 4. Paper 2: CECAP 文献综合

### 4.1 已有工作已经解决什么

TVM、MLIR 和 Glow 建立图级/算子级优化、多层 IR、lowering 与静态内存基础 [@chen2018tvm; @lattner2021mlir; @rotem2019glow]。AutoTVM、Ansor、TensorIR、FlexTensor 和 OpenTuner 已覆盖学习型 cost model、大搜索空间生成、tensorized primitive 和自动调优 [@chen2018autotvm; @zheng2020ansor; @feng2023tensorir; @zheng2020flextensor; @ansel2014opentuner]。TASO 与 Collage 分别覆盖图级等价变换和多后端自动放置 [@jia2019taso; @jeon2023collage]。

TinyML 文献已把内存约束置于编译核心。MCUNet/TinyEngine 联合搜索网络与运行时，TFLM 使用静态 arena，DORY 处理 scratchpad、tiling 和显式 DMA，Deeploy/HTVM 处理异构 MCU/NPU，TinyTS 研究内存高效编译 [@lin2020mcunet; @david2021tflm; @burrello2021dory; @scherer2024deeploy; @vandelm2023htvm; @liu2024tinyts]。因此 CECAP 不能把“考虑 SRAM/DMA/异构”单独声明为创新。

形式方法链也很成熟：CompCert 在证明范围内给出 verified compiler，translation validation 验证具体编译结果，Alive2 对 LLVM 优化做有界验证 [@leroy2009compcert; @pnueli1998translation; @lopes2021alive2]。CECAP 当前以 schema、编译和差分测试为主，证据强度显著低于这些工作，必须使用 `evidence-carrying`，避免把全部实验材料称为 formal proof。

### 4.2 文献留下的缺口

已有编译器主要输出 IR、代码、调度记录或 runtime module；已有 edge 部署系统主要追求给定硬件上的可执行性与效率。文献中较少把以下内容作为一个不可分割、由消费者检查的对象：

- 硬件事实的来源状态，而不只是 target flag；
- 主计划与每个 fallback 的独立适用域；
- segment、boundary 和 global obligation 的证据向量；
- candidate plan 与 deployable plan 的效力区分；
- 证据债务作为搜索目标，而不是编译后的布尔 `verified`。

Collage/BYOC 是最近的后端集成参照，但“后端可调用”不等于 ABI、数值、内存、coherency 和物理适用域都已证明 [@jeon2023collage; @apachetvm2026byoc]。

### 4.3 收紧后的创新点

1. `Plan as a consumer-checkable contract`：核心创新是十元组 \(P=(G,B,L,Q,S,M,D,F,\Omega,E)\)，不是新 IR 名称。
2. `Source-state-bounded legality`：unknown/conflict ABI 不属于 codegen 合法空间；这比普通 feature detection 更强。
3. `Non-amplifying evidence product`：变换产生新义务，不能复制旧证据冒充覆盖；fallback 单独验收。
4. `Candidate-preserving compilation`：允许保留待升证候选，但 deployable set 由策略和证据决定。
5. `Conditional Pareto result`：exact frontier 在明确假设下保持 Pareto；当前 beam 只能测 approximate recall，不能引用定理包装成完备性。

### 4.4 对数学理论的补强

把 evidence 从总等级改成产品格：

\[
\mathbb E=E_{source}\times E_{schema}\times E_{build}\times E_{numeric}
\times E_{resource}\times E_{virtual}\times E_{physical}\times E_{timing}.
\]

组合操作只在相同 hash/version binding 和兼容适用域内逐维取 meet；任何 pass 若改变相关语义或适用域，必须把对应维重置为未覆盖。PCC、CompCert 与 Alive2 只能作为高保证参照，不直接推出 CECAP 的 empirical evidence sound [@necula1997pcc; @leroy2009compcert; @lopes2021alive2]。

多目标搜索至少同时报告 latency、energy、peak memory、compile time、evidence debt 和 risk。NSGA-II/ParEGO 是搜索基线，不是 correctness baseline [@deb2002nsgaii; @knowles2006parego]。

### 4.5 实验设计修订

- 编译/搜索基线：TVM default、AutoTVM、Ansor、TensorIR/MetaSchedule、FlexTensor、OpenTuner、NSGA-II/ParEGO [@chen2018tvm; @chen2018autotvm; @zheng2020ansor; @feng2023tensorir; @zheng2020flextensor; @ansel2014opentuner; @deb2002nsgaii; @knowles2006parego]。
- 后端/部署基线：Collage/BYOC、MCUNet/TinyEngine、TFLM、DORY、Deeploy、HTVM [@jeon2023collage; @apachetvm2026byoc; @lin2020mcunet; @david2021tflm; @burrello2021dory; @scherer2024deeploy; @vandelm2023htvm]。
- 正确性参照：reference execution + differential testing 是主实验；Alive2/CompCert 只在确实接入其适用 IR 时才能成为执行基线。
- 平台指标按 MLPerf Tiny 的 accuracy/latency/energy 纪律报告，并额外报告 evidence completion、invalid-plan rejection、diagnostic precision 和 package/admission overhead [@banbury2021mlperftiny]。
- RISC-V 路径至少与 PULP-NN/XpulpNN 或同级优化库比较；QEMU 指令出现不能替代真实板 latency/energy [@garofalo2020pulpnn; @garofalo2020xpulpnn]。
- ExecuTorch 2026 条目已由 arXiv 原始记录核验，但仍是新近预印本，只作为现代 on-device deployment 对照，不承载“行业已证明”的强结论 [@nachin2026executorch]。

## 5. Paper 3: AIRTOS 文献综合

### 5.1 已有工作已经解决什么

Liu-Layland 与 Baruah 等奠定单处理器 EDF、周期/偶发任务和 demand 分析 [@liu1973scheduling; @baruah1990sporadic]；Vestal 及 Burns-Davis 说明 criticality 与 WCET assurance 必须联合考虑 [@vestal2007mixed; @burns2017mixed]。这些结论不能直接搬到非抢占 CPU/RVV/NPU/DMA segment DAG；AIRTOS 的 `SimEDF+` 必须显式建模 blocking、precedence 和 reservation。

HEFT、StarPU、Legion、PTask 与 typed-DAG 调度已经覆盖异构任务图、数据 locality、加速器 OS 对象和异构实时 DAG [@topcuoglu2002heft; @augonnet2011starpu; @bauer2012legion; @rossbach2011ptask; @lin2022typedag]。因此“segment DAG + resource queue”本身不是足够的新意。

PREMA、Planaria、V10、MoCA、DREAM 和 NPU virtualization 已覆盖 NPU 抢占、空间分割、细粒度共享、memory-centric QoS、动态实时多模型和 vNPU 隔离 [@choi2020prema; @ghodrati2020planaria; @xue2023v10; @kim2023moca; @kim2023dream; @xue2023npuvirt]。其中 DREAM 是 AIRTOS 最近的 edge real-time scheduler 基线；PREMA/V10 更偏数据中心或硬件支持，不能作为完全同域对照。

Runtime assurance/Simplex 将高性能复杂控制与可信安全边界分开，seL4 展示强 OS 保证需要明确的验证范围 [@hobbs2023runtimeassurance; @seto1998simplex; @klein2009sel4]。AIRTOS 应把这些工作作为“安全准入”理论来源，但不能暗示当前 C 主机测试达到形式验证等级。

### 5.2 文献留下的缺口

现有 NPU 多租户工作主要以 latency、throughput、SLA、公平性和利用率为端点；经典实时工作以 task/WCET/priority 为核心；runtime assurance 主要检查控制输出安全。当前语料中尚未发现一个 RTOS admission predicate 同时检查：

\[
PackageBind\land ApplicabilityDomain\land EvidenceCoverage\land Provider
\land Lease\land Coherence\land Schedulability\land Recoverability.
\]

此外，Linux DMA 文档定义 fence、mapping 和 cache ownership 规则，但这些机制不会自动生成计划级 proof，也不解决 reset 后迟到完成对新作业的归属 [@linux2026dmabuf; @linux2026dmaapi]。

### 5.3 收紧后的创新点

1. `Evidence-bounded admission`：证据/适用域与资源、时限和健康状态联合，而不是加载后只检查 backend 是否存在。
2. `Atomic memory-time admission`：lease reservation 与 schedule simulation 在同一 transaction 中成功或回滚。
3. `Epoch-cookie recovery semantics`：贡献是迟到/重复完成的精确归属和 quarantine 上界，不是一般 timeout API。
4. `Plan-driven coherency`：编译计划声明 buffer 范围和动作，runtime provider 实施；正确性仍相对于硬件 DMA/cache 模型。
5. `Non-self-certifying feedback`：trace 触发下一实验，新计划仍重新验证和准入。

### 5.4 对数学理论的补强

当前 per-resource EDF 必须加入非抢占 blocking 上界：

\[
B_r(J_i)=\max\{C_s+O_s\mid res(s)=r,\ d(job(s))>d_i,\ s\text{ may be active}\}.
\]

周期/偶发任务不能只仿真当前队列，还需将 demand/reservation 纳入 horizon。`SimEDF+` 定理的真正前提是：到达模型、WCET、blocking、DMA/coherency 和恢复开销都被保守覆盖；否则只能报告经验 miss ratio，不能声称 hard deadline safety [@liu1973scheduling; @baruah1990sporadic; @vestal2007mixed]。

对抢占能力应区分两种计划域：`preemptible=true` 时可与 PREMA 类基线比较；当前非抢占 NPU 则必须把长 segment blocking 显式纳入 admission，不能借用 PREMA 的效果 [@choi2020prema]。

### 5.5 实验设计修订

- 调度基线：FIFO、fixed priority、全局 EDF、per-resource EDF、HEFT、typed-DAG/federated scheduler、DREAM [@liu1973scheduling; @topcuoglu2002heft; @lin2022typedag; @kim2023dream]。
- 多租户基线：PREMA、Planaria、V10、MoCA、NeuCloud；按是否需要硬件 fission/preemption 分层，不做不公平的一表式 speedup [@choi2020prema; @ghodrati2020planaria; @xue2023v10; @kim2023moca; @xue2023npuvirt]。
- 运行时抽象基线：PTask、StarPU/Legion 思想对应的 DAG/data management；实现比较需选择可运行子集 [@rossbach2011ptask; @augonnet2011starpu; @bauer2012legion]。
- 最强安全实验不是平均 latency，而是 `unsafe admission=0`、stale completion acceptance、跨 lease corruption、WCET underestimation sensitivity、quarantine bound 和 false fallback。
- 物理 HIL 必须验证 DMA/cache 和 reset/IRQ；Zephyr/RT-Thread 文档只能证明 API/实现存在，不能证明本项目 deadline 或 coherency [@zephyr2026deadline; @rtthread2026docs]。
- serving 工作如 Salus/Clockwork 用于尾延迟与可预测性比较，但其 datacenter GPU 环境不是 MCU/RTOS 直接证据 [@yu2019salus; @gujarati2020clockwork]。

## 6. 跨论文矛盾与边界条件

| 文献张力 | 表面冲突 | 综合结论 | 对三篇的约束 |
|---|---|---|---|
| Agent 灵活性 vs. 固定 SOP | AutoGen/AgentVerse 强调灵活组合，MetaGPT/ChatDev 强调流程结构 | 属于适用场景差异，不是二选一 | ADAM 用风险图动态选角色，但 verifier/权限规则保持确定 |
| 多 Agent vs. Agentless | 多 Agent 声称协作增益，Agentless 显示简单流程可竞争 | 协作数量不是有效性来源 | 实验必须比较相同预算和工具，不以角色数当贡献 |
| 性能编译 vs. 高保证编译 | Ansor/TVM 优化经验性能，CompCert/Alive2强调证明范围 | 目标不同，可在 artifact 级组合 | CECAP 把 empirical evidence 与 formal proof 分栏 |
| exact Pareto vs. bounded beam | 多目标理论要求保留非支配候选，工程 beam 截断候选 | 条件差异可解释 | exact 小图验证定理，大图只报告 recall/hypervolume |
| NPU 抢占 vs. 非抢占设备 | PREMA 假设/设计抢占支持，当前 AIRTOS 默认 segment 非抢占 | 不是算法矛盾，是硬件域差异 | 计划适用域必须声明 preemptibility；非抢占加入 blocking |
| Runtime assurance vs. evidence admission | Simplex 检查在线动作，AIRTOS 检查计划/证据/资源 | 两者可组合但证明对象不同 | AIRTOS 不把 safety filter 文献当作编译正确性证明 |
| PCC proof vs. 测试 evidence | PCC 携带可机器检查证明，当前项目主要携带 schema/build/diff/trace | 证据强度不同 | 术语采用 evidence-carrying，只有形式对象才称 proof |

该 inventory 是按共享主题构造的范围性张力扫描，不声称完成 78 个来源的全 pairwise contradiction detection。

## 7. 三篇文章的最终创新边界

| 论文 | 已有工作最接近部分 | 不能再声称 | 可主张的组合贡献 | 必须用实验守住的边界 |
|---|---|---|---|---|
| ADAM | MetaGPT/ChatDev + OpenHands/SWE-agent + in-toto/SLSA + assurance case | 角色协作、沙箱、hash、测试本身是新贡献 | 硬件事实激活、工程效力隔离、声明证据债务、风险验证图、来源闭包与恢复统一 | 不安全事实激活率、false promotion、共同漏检、恢复一致性 |
| CECAP | TVM/Ansor/TensorIR/Collage + DORY/Deeploy + PCC/translation validation | 异构编译、自动调优、SRAM/DMA、BYOC 本身是新贡献 | 来源状态约束的合法空间 + 完整计划合同 + 适用域/fallback + 不增信证据产品 | illegal plan acceptance、Pareto recall、域外拒绝、每项 evidence obligation |
| AIRTOS | EDF/demand + PTask/StarPU/Legion + PREMA/DREAM/MoCA + Simplex | EDF、DAG、NPU 多租户、timeout 本身是新贡献 | 证据/适用域/资源/WCET/lease/recovery 的原子联合准入 | WCET 违反敏感性、stale IRQ、跨 lease、cache/DMA、恢复时界和 HIL |

## 8. 综合后的论文顺序与依赖

更合理的投稿/实现顺序是：

1. **先完成 CECAP schema 与小图 exact oracle。** 它定义 AIRTOS 消费的对象，也给 ADAM 提供明确的验证义务。
2. **再完成 AIRTOS 联合准入与物理故障实验。** 它能产生最硬的运行时反例和 trace。
3. **最后完成 ADAM-CoDesignBench。** 此时 ADAM 可以在真实 compiler/runtime 义务上比较实验选择，而不是只在模拟任务上展示多 Agent 讨论。

该顺序不改变三篇理论依赖，但降低了 Paper 1 因缺少真实下游证据而沦为 workflow paper 的风险。

## 9. 分布偏差与局限

`DISTRIBUTIONAL_SKEW_ADVISORY`：

- Dimension: methodological distribution
- Concentration: 系统构建/受控 benchmark/规范分析约 70/78，超过 70%
- Advisory: 这是由研究问题决定的覆盖分布，不等于来源缺陷；它意味着本文不能外推到组织行为、人因或大规模工业部署效果。
- Search response: 已加入综述、assurance、供应链和形式验证来源，但不为追求分布均衡纳入与 RQ 无关的经验研究。

其他局限：

- 没有订阅型 Scopus/WoS/Cabell 数据，predatory/venue 检查以公认出版社、会议、DOI 和官方索引为主。
- 对 78 个来源完成了存在性和元数据核验，但只对核心论文批量读取了原始摘要；不能声称逐页通读全部全文。
- Semantic Scholar 在批量核验后返回 429；未把缺失响应错误记为“不匹配”，改用 OpenAlex/Crossref/arXiv 继续核验。
- 2025-2026 Agent 和 on-device 文献变化快；`nachin2026executorch` 为已核验存在的预印本，仍需在投稿前检查是否出现正式版本。
- 系统论文通常由作者评估自己的系统。最终三篇必须发布原始 trace、失败样例、配置/hash 和可执行基线，降低 intellectual COI 对结论的影响。

## 10. 研究诚信说明

本综述由 AI 辅助执行检索、元数据核验、聚类和综合。所有 DOI、arXiv ID 和官方链接均保存在 `references.bib`，但作者仍需在正式投稿前人工阅读将被用于关键新颖性或定理前提的原文，并逐条确认引用是否真正支持对应声明。

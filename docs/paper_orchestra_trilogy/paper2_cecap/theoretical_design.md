# Paper 2 理论设计：CECAP

> 工程实施、计划 schema、实验素材生产、逐实验输入输出与结论判定见 [实验实施蓝图](implementation_blueprint.md)；冻结假设、样本量与统计规则见 [预注册实验协议](experiment_protocol.md)。

## 1. 论文题目

**英文题目**

> CECAP: Contract- and Evidence-Carrying Acceleration Plans for Hardware-Bounded Heterogeneous Edge AI

**中文题目**

> CECAP：面向硬件约束异构边缘 AI 的契约与证据携带加速计划

CECAP 的核心不是再提出一个局部算子优化器，而是改变编译器输出对象：从“代码或二进制”扩展为“可由运行时检查、拒绝、回退和继续升证的计划”。

### 1.1 论文研究设计摘要

| 必须体现的内容 | CECAP 的具体内容 |
|---|---|
| **真实行业难点** | ML 编译器已经成熟处理 IR、lowering、自动 schedule 和多后端放置，TinyML 也已处理静态 arena、tiling 和 DMA；尚缺的是在硬件合同本身不完备时，把主计划/fallback、适用域和逐义务证据交给运行时检查 [@chen2018tvm; @zheng2020ansor; @feng2023tensorir; @jeon2023collage; @burrello2021dory] |
| **核心创新** | 以十元组 \(P=(G,B,L,Q,S,M,D,F,\Omega,E)\) 改变编译器输出对象；由来源状态限定合法空间，区分 candidate/deployable，保证普通 transform 不增信，每个 fallback 独立合法和有证据 |
| **数学理论** | 定义 \(Legal(P\mid H,W)\) 的类型、backend、DAG、内存、ABI、coherency、numeric、binding 和 fallback 合取；给出 exact 分层 Pareto 保持条件、证据产品组合、条件可执行性与 fallback safety |
| **实验验证** | Core-1 验证合同过滤、完整计划和域外拒绝；Core-2 用 200 个可穷举小图验证 exact frontier 并将 beam 限定为近似；Core-3 验证证据不增信、NPU ABI blocker 和 fallback；Core-4 做多模型、真实板数值和性能。完整方案见 [预注册协议](experiment_protocol.md) |
| **突出贡献** | 不是新的 kernel tuner，而是把异构编译结果提升为带硬件来源边界、适用域、内存/依赖、证据和独立 fallback、可由运行时拒绝的部署合同 |
| **成立边界** | exact 定理不适用于有限 beam；QEMU 不支持物理 timing/energy；差分测试不等于形式证明；未知 NPU ABI 的正确结果可以是稳定 blocker |

## 2. 当前行业难点

### 2.1 编译器通常假定 target 正确，但嵌入式硬件合同可能不完整

通用 ML 编译器擅长图变换、算子融合和 kernel 调度，却通常假定 ISA、内存层次、DMA、cache、加速器 ABI 和工具链 target 已经可信。新 SoC 或板级项目中，这些信息往往来自多源材料，并包含未知项和冲突。若编译器把“检测到 NPU 名称”当成“拥有可用 command ABI”，就可能生成根本无法安全执行的 blob。

### 2.2 异构优化是跨层组合问题

CPU、RVV、NPU 和 DMA 的选择与图切分、layout、量化、TensorIR schedule、arena、数据搬运、cache fence、依赖和 fallback 相互耦合。单独优化 kernel latency 可能增加 layout conversion、DMA 或内存峰值，最终使系统更慢或无法部署。

### 2.3 “编译成功”不能回答“何时可以运行”

普通编译产物缺少适用域、资源需求、验证范围和版本绑定。运行时无法知道该产物是否只验证了某个 shape/dtype，是否只在 QEMU 上执行，是否要求某个 ABI revision，或者预测性能来自 seed 而非实测。

### 2.4 异构搜索空间巨大，剪枝又容易丢失全局好解

图分区、算法、schedule 和硬件映射形成乘法搜索空间。固定 beam 能控制成本，但不能无条件保证保留 Pareto 最优计划；仅凭单一延迟估计排序还会系统性忽略内存、能耗、证据债务和转换成本。

### 2.5 验证证据不能用一个等级替代

schema、编译、数值差分、虚拟 RTOS、物理板和压力性能验证覆盖不同义务。物理启动并不证明数值正确，主机差分也不证明真实 DMA/cache 行为。行业需要能随计划传播的多维证据，而不是一个模糊 `verified=true`。

### 2.6 回退常被写成异常路径，而不是编译计划的一部分

NPU 不可用、资源不足或适用域不匹配时，系统需要可验证的 RVV/CPU 回退。若 fallback 没有自己的适用域、内存计划和证据，运行时回退只是从一个未知计划跳到另一个未知计划。

### 2.7 行业真实性证据：文献与当前仓库的交叉核对

| 现实问题 | 外部行业证据 | 当前仓库直接观测 | 对论文主张的约束 |
|---|---|---|---|
| IR、autotuning 和异构 mapping 已是成熟领域 | TVM/MLIR/Glow、AutoTVM/Ansor/TensorIR、TASO/Collage 已分别覆盖多层 IR、schedule search、图优化和多后端放置 [@chen2018tvm; @lattner2021mlir; @rotem2019glow; @chen2018autotvm; @zheng2020ansor; @feng2023tensorir; @jia2019taso; @jeon2023collage] | `engine/tvm_templates/compiler.py` 已能构建 CPU/RVV AOT、QEMU 执行和简单 backend 选择 | CECAP 不能把编译、RVV codegen、BYOC 或分层搜索本身作为创新 |
| SRAM、DMA 和 edge deployment 已有强基线 | TFLM、DORY、Deeploy、HTVM 已处理静态 arena、scratchpad tiling、DMA 和异构 MCU/NPU [@david2021tflm; @burrello2021dory; @scherer2024deeploy; @vandelm2023htvm] | 当前 AEG v2 已有八类 section、arena/range/coherency、domain、evidence、fallback、reservation 和 recovery，但生成实例仍是一段、64 B、固定 Add+ReLU | 创新必须是完整计划合同和消费者拒绝，不是“考虑内存/DMA”；当前实例不能代表一般图覆盖 |
| 当前性能成本不是实测 | MLPerf Tiny 要求同时报告 accuracy、latency 和 energy，并明确测量环境 [@banbury2021mlperftiny] | `engine/tvm_templates/compiler.py:148-182` 把 10/4 us 标为 `compiler_seed`，只对固定 `add_relu_f32_8` 做 `beam_width=4` 排序 | 这些数只能测通搜索路径；不得进入 speedup、能耗、WCET 或 Pareto 质量结论 |
| 当前计划对象已形成可检查子集，但覆盖仍窄 | 编译验证/PCC 文献要求明确证明对象和检查边界 [@necula1997pcc; @pnueli1998translation; @lopes2021alive2] | `plan_v2.py` 已生成绑定 model/target/runtime/provider ABI、domain、primary/fallback、memory、evidence/policy 和 arrival/recovery 的 plan/evidence/AEG v2；runtime trust bundle 可逐义务核对 | N1/N4/N5 已有固定工作负载接口实例；仍需一般 segment DAG、变换失效传播、正式 mutation 和多模型消费者实验 |
| NPU 名称或 BYOC API 不等于可执行 ABI | BYOC 规定后端接入接口，但不证明厂商 command ABI、DMA 和数值正确 [@apachetvm2026byoc] | `engine/tvm_ai_tools.py:35-47,124-151` 只有安全 `command_abi` 才确认 NPU，manifest 固定 `npu_blob_emitted=false`，缺 ABI 时要求 blocker/fallback | 未知 ABI 不生成 NPU blob 是现有可验证贡献；真实 NPU 性能和正确性仍 blocked |
| 虚拟执行不能外推物理性能 | 编译与部署文献分别报告 correctness、平台和测量域 [@leroy2009compcert; @banbury2021mlperftiny] | 当前 RVV 路径由 `qemu-riscv64` 与 objdump 指令检查验证，未产生真实板 latency/energy | QEMU 只支撑 codegen/execution-path 证据，Core-4 必须在真实板重测 |

## 3. 主要核心思想

CECAP 将一次异构编译结果定义为：

\[
P=(G,B,L,Q,S,M,D,F,\Omega,E),
\]

其中计划不仅描述“执行什么代码”，还描述：

- 模型图如何分段 \(G\)；
- 每段映射到哪个 backend \(B\)；
- layout 和 precision/quantization \(L,Q\)；
- kernel 与 TensorIR schedule \(S\)；
- arena、buffer 生命周期和对齐 \(M\)；
- 段依赖、DMA 和 coherency 动作 \(D\)；
- 有序 fallback 计划 \(F\)；
- target、模型、shape、dtype、ABI 和运行前提的适用域 \(\Omega\)；
- 每项声明的证据集合 \(E\)。

编译过程由硬件契约先定义合法空间，再在合法空间内做分层 Pareto 搜索。候选计划可以保留，但只有满足当前声明义务的计划才能被标为可交付；未知 NPU ABI 直接从合法 codegen 空间删除，同时保留已验证的 RVV/CPU 回退。

因此，CECAP 的核心研究问题是：

> 编译器能否生成一种自描述计划，使运行时无需信任编译器的自然语言结论，也能判定该计划在当前硬件和状态下是否属于已验证适用域？

## 4. 文章创新点

### 4.1 契约与证据携带计划对象

CECAP 把异构图映射、内存、依赖、fallback、适用域和验证证据合并为同一个编译中间对象。代码只是计划的一部分，运行时可检查的声明边界也是输出。

### 4.2 由来源状态约束的编译合法空间

硬件能力并非布尔 target flag。只有 `SafeFact` 支撑的 ISA extension、内存和 ABI 才能进入合法计划空间；`candidate/unknown/conflict` 对应显式 blocker，而不是使用默认值继续 codegen。

### 4.3 分层 Pareto 传播与有条件剪枝保证

搜索按 graph partition、algorithm、S-TIR/TensorIR schedule、hardware mapping 四层展开。每层先做约束过滤，再传播非支配候选。论文明确区分 exact frontier 和 bounded beam：只有在下界可采纳且不截断必要候选时才给出 Pareto 保持定理。

### 4.4 适用域索引的正确性

CECAP 不声称 plan 全局正确，而将正确性绑定到 \(\Omega\)。模型哈希、shape、dtype、layout、target hash、ABI、工具链和 runtime prerequisites 任一不匹配，运行时必须拒绝或选择另一 fallback。

### 4.5 不增信的证据传播

编译变换可以组合已有证据和产生新证明义务，但不能自行提升证据。每个 segment、edge 和全局 plan 的证据按义务种类组合；整计划等级不能高于最弱的必要义务覆盖。

### 4.6 candidate-preserving compilation

未完成板级验证的 RVV/NPU 候选可保留用于下一轮实验，但必须与可执行 verified plan 分开。该机制支持 ADAM 后续选择升证实验，同时避免候选伪装成生产计划。

## 5. 数学理论

### 5.1 硬件契约与工作负载

硬件契约定义为：

\[
H=(I,R,A,\mathcal{M},X,C,V),
\]

其中 \(I\) 是 ISA/extension，\(R\) 是可执行资源，\(A\) 是加速器及其 ABI，\(\mathcal{M}\) 是内存区域和约束，\(X\) 是 DMA/cache/coherency 能力，\(C\) 是时钟/容量约束，\(V\) 是版本和来源哈希。

工作负载为带张量类型的 DAG：

\[
W=(V_W,E_W,\sigma,\delta,h_W),
\]

其中 \(\sigma(v)=(shape,dtype,layout)\)，\(\delta(v)\) 是算子语义，\(h_W\) 是模型哈希。

### 5.2 CECAP 计划

计划十元组各字段定义如下：

\[
P=(G,B,L,Q,S,M,D,F,\Omega,E).
\]

- \(G=\{g_1,\ldots,g_k\}\)：保持 \(W\) 语义边界的 segment DAG；
- \(B:g_i\mapsto\{CPU,RVV,NPU,DMA\}\)：backend 映射；
- \(L\)：每条张量边的 layout 和必要转换；
- \(Q\)：精度、量化参数和允许误差；
- \(S\)：每段算法、lowering 和 schedule；
- \(M\)：buffer、地址空间、对齐、生命周期和 arena 峰值；
- \(D\)：段依赖、传输、barrier、clean/invalidate 动作；
- \(F=(P_1,\ldots,P_m)\)：有序回退链；
- \(\Omega\)：计划适用域及版本/hash 绑定；
- \(E\)：按声明义务索引的证据对象集合。

### 5.3 计划合法性

CECAP 定义以下合取谓词：

\[
Legal(P\mid H,W)=
Type\land Target\land Backend\land DAG\land Memory\land ABI\land
Coherence\land Numeric\land Bind\land Fallback.
\]

主要约束为：

**类型与图语义**

\[
\forall (u,v)\in E_G,\ OutType(u,L,Q)=InType(v,L,Q),
\]

且 \(G\) 无环、覆盖所有必要算子，分区边上的转换显式存在。

**backend 能力**

\[
B(g)=r\Rightarrow Supported(r,op(g),\sigma(g),H)\land SafeFact(Basis(r)).
\]

**内存边界**

对每个 buffer \(b\)：

\[
0\le offset_b,\quad offset_b+size_b\le Arena(P),\quad
offset_b\equiv0\pmod{align_b}.
\]

若两个 buffer 地址区间重叠，则它们必须显式 alias 或生命周期不相交：

\[
Addr(b_i)\cap Addr(b_j)\ne\emptyset
\Rightarrow AliasAllowed(b_i,b_j)\lor Life(b_i)\cap Life(b_j)=\emptyset.
\]

**ABI 与 coherency**

\[
B(g)=NPU\Rightarrow SafeFact(command\_abi)\land VersionMatch(ABI_g,H),
\]

跨 coherent domain 的边必须包含对应 DMA、barrier 和 cache 动作。

**绑定**

\[
\Omega(P).target\_hash=Hash(H),\qquad \Omega(P).model\_hash=h_W.
\]

**回退**

\(F\) 中每个计划独立满足 `Legal`；不能以主计划证据代替 fallback 证据。

### 5.4 多目标函数

对合法计划定义成本向量：

\[
\mathbf{f}(P)=(\widehat{L},\widehat{Energy},M_{peak},T_{compile},Debt(P),Risk(P)).
\]

估计值与实测值必须带来源标签。当前原型 `cost.db` 的 `compiler_seed` 只能用于测试搜索路径，不得作为 \(\widehat{L}\) 的实验测量。

计划 \(P_1\) 支配 \(P_2\) 当且仅当：

\[
P_1\prec P_2\iff \forall j,f_j(P_1)\le f_j(P_2)
\land\exists j,f_j(P_1)<f_j(P_2).
\]

### 5.5 分层搜索

搜索层次为：

\[
\mathcal{N}_0\xrightarrow{partition}\mathcal{N}_1
\xrightarrow{algorithm}\mathcal{N}_2
\xrightarrow{schedule}\mathcal{N}_3
\xrightarrow{mapping}\mathcal{P}.
\]

每个 partial node \(n\) 具有约束集合 \(C(n)\)、成本下界 \(\ell(n)\) 和所有合法完成集合 \(Ext(n)\)。理论算法为：

```text
frontier <- {empty plan}
for level in [partition, algorithm, schedule, mapping]:
    candidates <- expand(frontier, level)
    feasible <- {n in candidates | contract_filter(n, H, W)}
    frontier <- nondominated(feasible, admissible_lower_bounds)
return complete legal plans in frontier
```

工程实现可设置 beam width \(K\)，但必须把结果称为近似前沿；只有 exact frontier 或满足明确 \(\epsilon\)-coverage 的截断策略才能声称保持性。

### 5.6 证据生成与组合

计划证据分为：

\[
E(P)=\bigcup_iE(g_i)\cup\bigcup_{(i,j)}E(i,j)\cup E_{global}(P).
\]

组合有效需要：

1. 每个 segment 的输入输出类型和适用域与相邻 edge 证据一致；
2. 版本/hash 绑定相同；
3. 全局内存、依赖和 fallback 义务被覆盖；
4. 数值证据覆盖最终输出，而非只覆盖局部 kernel；
5. 新变换引入的新义务不能沿用变换前证据。

计划可交付谓词为：

\[
Deliverable(P,k)\iff Legal(P\mid H,W)\land Debt_k(P,E)=0,
\]

其中 \(k\) 是部署策略要求的义务集合，而不是只比较一个 E-level 数字。

### 5.7 核心定理与证明路线

**定理 1：约束过滤可靠性。** 若 `contract_filter` 对 `Legal` 的每个合取项都是 sound 的，则所有被保留的 complete plan 均属于合法计划空间。

*证明路线*：过滤器对每个合取约束返回真；有限合取闭包直接得到 `Legal`。该定理不保证过滤器 complete，保守过滤可能拒绝合法计划。

**推论 1：未知 NPU ABI 不生成 NPU 计划。** 若 `SafeFact(command_abi)=false` 且 ABI 过滤器 sound，则任何保留计划都不含 NPU segment。

这与当前 `npu_blocker.json` 和 `npu_blob_emitted=false` 的实现行为一致。

**定理 2：分层 Pareto 保持。** 假设每个合法完整计划都可由层次展开到达；约束具有 extension-monotonicity；\(\ell(n)\) 是所有 \(P\in Ext(n)\) 的分量下界；只剪除被某个可行完整计划支配的节点；不使用额外 beam 截断。则最终 frontier 包含所有 Pareto 最优完整计划。

*证明路线*：反证。若最优计划 \(P^*\) 的某个前缀被剪除，则存在可行计划支配其可采纳下界，从而支配 \(P^*\)，与 \(P^*\) 最优矛盾。

**注意**：当前 `beam_width=4` 不满足“不额外截断”条件，因此只能作为搜索原型，不能引用该定理声称完备。

**命题 1：证据不放大。** 若编译 pass 只能复制输入证据或通过授权 verifier 新增证据，则任一 pass 不能把未覆盖义务从 0 改为 1。

*证明路线*：对 pass 序列归纳；普通 transform 不改变覆盖向量，verifier 只对其实际验证义务置位。

**定理 3：计划证据组合。** 若所有 segment、boundary 和全局义务在同一版本绑定和兼容适用域内有效，则组合计划满足这些义务的合取。

*证明路线*：按 segment DAG 拓扑序归纳，boundary 证据保证相邻段接口保持，最终加入全局内存和输出义务。

**定理 4：条件可执行性。** 假设 `Legal(P|H,W)`、运行状态 \(R\in\Omega(P)\)、所有必要证据有效、AIRTOS 遵守 \(M,D\) 且 backend 实现满足 ABI，则执行不会违反已声明的类型、内存、依赖和数值误差义务。

该定理不自动证明 deadline；只有 CECAP 提供保守执行界且 AIRTOS 的 admission theorem 前提成立时，才能得到时限结论。

**定理 5：回退安全。** 若 runtime 只从 \((P,F_1,\ldots,F_m)\) 中选择首个同时满足 `Legal`、适用域和部署证据策略的计划，则回退不会降低规定的安全义务覆盖。

回退可能牺牲性能，但不能牺牲最低证据策略。

## 6. 四个核心实验如何验证

CECAP 的验证收敛为四个论文级核心实验。合同 mutation、域外加载、证据失效、NPU blocker、fallback 和多模型覆盖作为核心实验内部子测试保留。

### 核心实验 1：合同约束、完整计划与域外拒绝

**研究问题**：完整 plan 是否能在搜索和 dispatch 前阻止非法或域外部署？

**子测试**：ISA/RVV/NPU ABI、shape/dtype/layout、arena/alignment、DMA/cache、target/model/toolchain hash、DAG cycle 与 plan 字段 mutation；code-only、ordinary metadata 和 CECAP plan v2 加载对比。

**对照组**：target-string-only、metadata-only、code-only AOT、完整 CECAP filter/loader。

**主端点**：每个关键类别 illegal-plan acceptance 和 unsafe pre-dispatch acceptance 均为 0；diagnostic macro-F1 不低于 0.95。

**理论对应**：共同验证合法空间定理、完整计划对象和适用域索引。未知 ABI NPU blob、越界 arena 或域外 dispatch 任一发生即否定安全主张。

### 核心实验 2：exact Pareto 保持与 bounded beam 质量

**研究问题**：exact 分层搜索是否保持前沿，bounded beam 在给定预算下损失多少？

**素材**：从公开真实模型确定性抽取且保留原节点 provenance 的 200 个 2-8 节点可穷举 typed sub-DAG、CanMV-K230 覆盖全部候选的实测 cost table、至少 10,000 个 lower-bound property case，以及真实多模型大图和 30 个固定搜索 seed。

**对照组**：穷举 oracle、flat random、单目标 beam、CECAP beam `K={1,2,4,8,16,32}`、exact hierarchical frontier、epsilon-frontier、NSGA-II、ParEGO。

**主端点**：exact 每图 Pareto recall=1 且 false-frontier=0；K=8 的 median recall 不低于 0.90，normalized hypervolume 差的 95% CI 下界不低于 -0.05。

**理论对应**：exact 任一集合差异否定定理实现；beam 未达标只否定近似策略，不反推 exact 定理。

### 核心实验 3：证据不增信、NPU 升证与安全 fallback

**研究问题**：编译变换和环境退化是否会错误提高或继承部署资格？

**子测试**：shape/layout/precision/memory/ABI/toolchain/artifact transform；分层缺失 evidence；无/冲突/权威 NPU ABI；NPU offline、RVV 不可用、arena 缩小、policy 提高和 hash 变化。

**对照组**：标量 verified、无独立证据 fallback、fastest-only、CECAP evidence product 与独立 fallback。

**主端点**：false evidence promotion、stale evidence reuse、错误 NPU emission 和 unsafe fallback 均为 0。

**理论对应**：共同验证证据不增信、candidate/deployable 分离和 fallback safety。无权威 ABI 时 NPU 正分支保持 `blocked`。

### 核心实验 4：多模型后端正确性与真实性能

**研究问题**：CECAP 是否超出 Add+ReLU，并在声明域内数值正确、性能结论可由真实测量支持？

**素材**：公开发布真实权重的 MLPerf Tiny 类、MobileNet/ResNet、attention+MLP 及其真实融合子图；主输入来自 CIFAR-10、MS COCO/VWW、Speech Commands v2、ToyADMOS 和 WikiText-2 官方 test/validation split [@krizhevsky2009cifar; @lin2014coco; @chowdhery2019vww; @warden2018speechcommands; @koizumi2019toyadmos; @merity2017wikitext]，每 model/shape 至少 100 个带 sample ID/hash 的真实输入；unsupported/dynamic/quant/arena 与数值边界单列为 robustness 负例。

**对照组**：reference runtime、TVM CPU AOT、TVM default RVV、CECAP tensorized RVV；权威 ABI 和 provider 可用时增加 NPU。

**主端点**：支持域内数值超容差为 0；所有负例正确拒绝；Core-4a 原子实测组合成本在 Core-4b held-out complete plans 上达到 latency MAPE<=10%、p95 APE<=20% 才外推真实硬件 Pareto；每配置 10 warm-up+30 测量，speedup 95% CI 完全高于 1 才声称更快。

**理论对应**：分别验证可执行性、真实数据覆盖和板级性能。QEMU 只支持 execution path/指令证据，CanMV-K230 measured cost 才能进入真实性能与 confirmatory Pareto 结论。

### 6.1 消融与统计

关键消融包括：去掉硬件 contract filter、去掉 \(\Omega\)、去掉 evidence vector、去掉 fallback、flat search、单目标 latency、固定 beam 宽度变化。小图用 exact oracle；大图用重复搜索和 bootstrap 置信区间。性能比较同时报告测量环境、热身、频率、温度、运行次数和原始 trace。

## 7. 每篇文章的突出贡献

CECAP 的突出贡献应写成以下四点：

1. **提出契约与证据携带的异构编译计划。** 将代码、图映射、内存、依赖、fallback、适用域和验证证据统一为运行时可检查对象。
2. **建立来源安全硬件事实到编译合法空间的形式映射。** 未知或冲突 ABI 不再由启发式补全，而成为可解释 blocker。
3. **提出具有明确保证边界的分层 Pareto 搜索。** 给出 exact frontier 的保持条件，并明确有限 beam 只能提供近似结果，避免过度理论声明。
4. **提出适用域索引和不增信的证据组合理论。** 使候选计划可以被保留和升证，同时防止编译成功、虚拟执行或物理启动越权替代其他证明义务。

论文最突出的主张是：

> CECAP 使异构编译产物从“不可审计的代码选择”变成“可验证、可拒绝、可回退且适用域明确的系统计划”。

## 8. 当前项目支撑与缺口

当前 `engine/tvm_ai_tools.py`、`engine/tvm_templates/compiler.py` 和 `plan_v2.py` 已实现 TVM Relax/S-TIR、CPU/RVV AOT、QEMU 数值差分、RVV 指令检查、简单 beam plan、NPU ABI blocker，以及 plan/evidence/policy v2、AEG v2、逐义务证据、独立 CPU/RVV fallback 和 AIRTOS trust-bundle/runtime evaluation。这些对象构成 CECAP-AIRTOS 合同的固定工作负载实例。

当前覆盖仍固定为 `add_relu_f32_8`、单 segment 和 64 B arena；beam 仍为 width=4 的单成本选择，`cost.db` 的 10/4 微秒仍是 `compiler_seed`。尚无 exact frontier、200 图独立 oracle、证据变换失效 corpus、多模型输入集、CanMV-K230 measured cost 或真实 NPU command ABI/provider。因此“合同接口已实现”与“完整论文主张已验证”必须分开；现有 selftest 不得写成 Core-1 至 Core-4 的正式结果。

CECAP 消费 ADAM 产生的 Hardware IR 和来源闭包，向 AIRTOS 输出计划及证明义务；它不负责 Agent 晋升，也不负责当前队列和 deadline 的运行时保证。

## 9. 文献基础、创新边界与实验基线

完整检索方法、来源核验和三篇的共享边界见 `../literature_review.md`；引用元数据见 `../references.bib`。

### 9.1 相关工作分层

**IR 与性能可移植性。** TVM、MLIR 和 Glow 已经覆盖图/算子优化、多层 IR、progressive lowering、静态内存和多 target codegen [@chen2018tvm; @lattner2021mlir; @rotem2019glow]。这些能力是 CECAP 的基础，不是 CECAP 的新贡献。

**自动搜索与多后端放置。** AutoTVM、Ansor、TensorIR、FlexTensor、OpenTuner、TASO 和 Collage 已经覆盖 cost model、自动 schedule、tensorized primitive、图等价变换和后端自动放置 [@chen2018autotvm; @zheng2020ansor; @feng2023tensorir; @zheng2020flextensor; @ansel2014opentuner; @jia2019taso; @jeon2023collage]。CECAP 不能把“分层搜索”“BYOC”或“异构 mapping”单独写成首次。

**TinyML 与内存约束部署。** MCUNet/TinyEngine、TFLM、DORY、Deeploy、TinyTS 和 HTVM 已经把静态 arena、scratchpad tiling、DMA、量化与异构 MCU/NPU 部署放到系统核心 [@lin2020mcunet; @david2021tflm; @burrello2021dory; @scherer2024deeploy; @liu2024tinyts; @vandelm2023htvm]。因此“考虑 SRAM/DMA”本身不是论文空白。

**编译验证。** PCC、CompCert、translation validation 和 Alive2 提供比当前差分测试更强的证明/验证参照 [@necula1997pcc; @leroy2009compcert; @pnueli1998translation; @lopes2021alive2]。CECAP 当前应称 `evidence-carrying`，只有真实形式对象才称 `proof`。

### 9.2 文献约束后的创新边界

CECAP 的新意必须落在运行时消费者可检查的计划合同：

1. 将硬件事实的来源状态映射为编译合法空间，未知/冲突 ABI 不能被默认 target flag 覆盖；
2. 将主计划与 fallback 的 \(G,B,L,Q,S,M,D,F,\Omega,E\) 统一绑定，并要求每个 fallback 独立满足合法性和证据策略；
3. 证据按 segment、boundary 和 global obligation 组合，编译 pass 不得自行增信；
4. 待物理升证的 candidate 可以保留，但不能进入 deployable set；
5. exact frontier 与 bounded beam 使用不同结论，当前 `beam_width=4` 只报告近似质量。

建议新颖性措辞为：

> CECAP 不是新的局部 kernel 调优器，而是把来源受限的硬件合法性、异构执行计划、fallback、适用域和声明证据统一为运行时可以拒绝的部署对象。

### 9.3 数学模型补强

证据空间应明确为产品而非标量等级：

\[
\mathbb E=E_{source}\times E_{schema}\times E_{build}\times E_{numeric}
\times E_{resource}\times E_{virtual}\times E_{physical}\times E_{timing}.
\]

计划组合只在相同 hash/version binding 和兼容适用域内逐维取 meet。任一变换若改变 shape、layout、precision、memory 或 ABI，必须把受影响维度重置为未覆盖。这样可以形式化解释为什么物理启动不能替代 numerical diff，也不能替代 timing/stress。

多目标搜索以 NSGA-II、ParEGO 等作为 search baseline [@deb2002nsgaii; @knowles2006parego]。它们只比较优化质量，不承担 `Legal` 或 evidence soundness。

### 9.4 对照组与新增实验要求

- **编译/搜索基线**：TVM default、AutoTVM、Ansor、TensorIR/MetaSchedule、FlexTensor、OpenTuner、NSGA-II/ParEGO。
- **放置/部署基线**：Collage/BYOC、MCUNet/TinyEngine、TFLM、DORY、Deeploy、HTVM；对无法在同一硬件运行的系统分层比较，避免不公平 speedup。
- **正确性参照**：reference execution + differential testing 是当前可执行基线；只有实际接入相容 IR 时，Alive2/CompCert 才能成为执行对照。
- **评测纪律**：按 MLPerf Tiny 同时记录 accuracy、latency 和 energy，并增加 invalid-plan acceptance、evidence completion、domain-mismatch rejection、package size 和 admission overhead [@banbury2021mlperftiny]。
- **RISC-V 基线**：真实板 RVV/量化路径与 PULP-NN、XpulpNN 或同级库比较；QEMU 指令存在性不得写成 speedup [@garofalo2020pulpnn; @garofalo2020xpulpnn]。
- **新近工作**：ExecuTorch 2026 已由 arXiv 原始记录核验，但仍是预印本，只作为现代 on-device deployment 方向，不承载强新颖性结论 [@nachin2026executorch]。

### 9.5 文献修订后的突出贡献

Paper 2 的突出贡献应写成：**把 ML compiler 的结果从代码/调度选择提升为证据边界明确、适用域索引、可回退且可被运行时拒绝的异构部署计划。** 性能优化必须与错误拒绝和证据不放大共同成立，否则只是一套不完整的 autotuning 包装。

## 10. 逐项创新性证明义务与实验锁

完整执行方案见 [CECAP 预注册实验协议](experiment_protocol.md)。CECAP 的创新必须由计划安全、搜索质量和真实执行三类证据分别支撑，不能用 speedup 替代 illegal-plan rejection。

| ID | 创新点 | 最近先例与已解决内容 | CECAP 必须证明的新差异 | 严谨性的必要性 | 直接证伪条件 | 协议实验 |
|---|---|---|---|---|---|---|
| N1 | 契约与证据携带计划 | TVM/MLIR/Glow 和 Collage 已输出 IR、module、mapping [@chen2018tvm; @lattner2021mlir; @rotem2019glow; @jeon2023collage] | (G,B,L,Q,S,M,D,F,\Omega,E) 作为一个消费者可检查、可拒绝对象 | code-only 无法判断 domain、fallback 和 evidence policy | 关键 mismatch 只能执行后发现，或字段不全仍可加载 | Core-1 |
| N2 | 来源状态约束合法空间 | target flag、BYOC 已描述 backend 能力接口 [@apachetvm2026byoc] | backend basis 必须是安全硬件事实，unknown/conflict 成为 blocker | NPU 名称/API 存在不代表 command ABI 可执行 | 未知/冲突 ABI 产生 deployable NPU blob | Core-1、Core-3 |
| N3 | exact/approx 分界的分层 Pareto 搜索 | AutoTVM、Ansor、TensorIR、OpenTuner、多目标算法已有搜索 [@chen2018autotvm; @zheng2020ansor; @feng2023tensorir; @ansel2014opentuner; @deb2002nsgaii] | 约束过滤先于优化；exact 给条件保持，beam 只给经验近似 | 固定 beam 截断不能获得无条件前沿保证 | exact 在满足假设的小图丢失或错误保留 Pareto plan | Core-2 |
| N4 | 适用域索引正确性 | Glow/TFLM/TinyML 系统已有类型、内存和 target 部署 [@rotem2019glow; @david2021tflm; @lin2020mcunet] | model/shape/layout/precision/target/ABI/toolchain/runtime 共同绑定声明 | 一次执行不能外推到其他 shape、版本或硬件 | 域外 plan 被当作域内执行 | Core-1 |
| N5 | 不增信证据产品 | PCC、CompCert、translation validation、Alive2 提供更强形式参照 [@necula1997pcc; @leroy2009compcert; @pnueli1998translation; @lopes2021alive2] | empirical/formal evidence 分栏；transform 使受影响坐标失效，只有授权 verifier 可新增 pass | compile/boot/numeric 覆盖不同命题 | 未调用 verifier 却新增 evidence，或跨 hash/domain 复用 | Core-3 |
| N6 | candidate-preserving compilation 与独立 fallback | autotuning/多后端系统已保留候选和后端路径 | candidate 与 deployable 具有不同工程效力；每个 fallback 独立合法、适用且有证据 | 删除候选浪费升证机会，直接部署又越权 | candidate 绕过 gate，或 fallback 继承主计划证据 | Core-3 |

### 10.1 论文级验收规则

- N1、N2、N4、N5、N6 的关键错误接受必须逐类为零；任一反例优先于所有 latency/energy 优势。
- N3 的 exact 实现必须在冻结的 200 个可穷举小图上 `Pareto recall=1` 且 false-frontier=0。bounded beam 只报告 recall、hypervolume 和成本，不论数值多高都不能写“完备”。
- RVV/NPU 正确性必须有 reference differential；性能必须来自真实板、10 次 warm-up 和至少 30 次测量。QEMU 和 `compiler_seed` 永不进入板级 speedup 表。

### 10.2 预注册结论边界

若计划安全假设通过，可写“在测试合同与 mutation 域内，CECAP 使 runtime 在执行前拒绝关键非法、域外和证据不足计划”。若 exact search 通过，只能写“在所枚举有限空间及定理假设下与 oracle 一致”。若真实后端数值失败，撤回对应适用域；若性能 CI 不支持优势，写“未观察到可靠加速”，不改变计划合同贡献。

当前固定 Add+ReLU 的 plan/evidence/AEG v2、seed cost 和无真实 NPU 执行只能支撑合同原型路径。N1/N4/N5 已从纯设计缺口升级为固定域代码支撑，但 N1-N6 的论文结论仍以协议 readiness checklist、冻结 corpus 和生成 artifact 为准，不能由理论设计文字替代。

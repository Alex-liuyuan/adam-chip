# CECAP 预注册实验协议

> 本文规定假设、阈值和统计纪律；plan v2、200 个 exact 小图、模型/合同素材和逐实验执行卡见 [实验实施蓝图](implementation_blueprint.md)。

## 0. 协议状态

- 论文：CECAP: Contract- and Evidence-Carrying Acceleration Plans for Hardware-Bounded Heterogeneous Edge AI
- 协议版本：`cecap-exp-v1`
- 状态：`PRE-RESULT / UNVERIFIED`
- 冻结对象：本文、workload manifest、hardware contracts、合法性 oracle、搜索空间、成本测量和基线锁
- 结果纪律：`cost.db` 的 `compiler_seed` 只用于冒烟测试；任何 latency、energy、speedup、WCET 或 Pareto 结果在真实运行前均为 TBD

CECAP 的主贡献不依赖“比 TVM 更快”这一单一结果。论文分别检验计划是否合法、消费者能否拒绝域外计划、搜索是否保留前沿、证据是否被错误放大，以及可执行后端是否正确和有效。

## 1. 行业背景与严格性的必要性

ML 编译器已经提供多层 IR、图变换、自动调优、后端放置和内存规划 [@chen2018tvm; @lattner2021mlir; @zheng2020ansor; @feng2023tensorir; @jeon2023collage]。TinyML 系统也已把 arena、DMA、tiling 和异构部署置于核心 [@lin2020mcunet; @burrello2021dory; @scherer2024deeploy]。新 SoC 的困难是 target contract 本身可能缺字段或冲突，而代码产物通常没有把适用域、fallback 和逐项验证义务作为运行时可检查对象。

严格性在这里有三层必要性：

1. 搜索到低成本候选不代表候选合法；非法计划必须先于优化被过滤。
2. 编译、数值差分、QEMU、物理执行和 timing 是不同证据坐标，不能用最高 E-level 覆盖其余义务。
3. exact search 与有限 beam 的数学结论不同。若不建立穷举 oracle，任何“保持 Pareto 最优”都不可证伪。

## 2. 研究问题与预注册假设

| ID | 研究问题 | 预注册假设 | 主端点 | 支持阈值 |
|---|---|---|---|---|
| RQ1/H1 | 来源状态约束能否阻止非法计划进入可交付集合？ | 完整 `Legal` filter 对预注册非法变体零接受 | illegal-plan acceptance rate, IPAR | 每个关键类别 `IPAR=0`；任一越界内存或未知 ABI NPU plan 通过即失败 |
| RQ2/H2 | exact 分层搜索是否保持完整 Pareto 前沿？ | 在定理假设成立的小图上 exact frontier 与穷举 oracle 相同 | Pareto recall；false-frontier rate | 每个图 `recall=1` 且 false-frontier=0 |
| RQ3/H3 | 有限 beam 在等预算下能否给出有用近似？ | bounded beam 达到预注册近似质量，但不声称完备 | Pareto recall；normalized hypervolume | 跨图 median recall 不低于 0.90，且 HV 差的 bootstrap 95% CI 下界不低于 -0.05；否则只报告失败曲线 |
| RQ4/H4 | 完整计划能否在执行前拒绝适用域和环境不匹配？ | (P=(G,B,L,Q,S,M,D,F,\Omega,E)) 比 code-only/metadata-only 检出更多域外部署 | unsafe pre-execution acceptance；diagnostic recall | 每个关键 mismatch 类错误执行为 0，拒绝原因 macro-F1 不低于 0.95 |
| RQ5/H5 | 编译 pass 是否保持证据不增信？ | 未调用授权 verifier 的 transform 不会把未覆盖义务变为 covered | false evidence promotion | 300 个变体/受影响证据坐标中错误升证为 0 |
| RQ6/H6 | fallback 是否独立满足合法性、适用域和证据策略？ | runtime 只选择首个满足策略的主计划或 fallback | unsafe fallback rate | 每个故障类别错误 fallback 为 0 |
| RQ7/H7 | RVV/NPU 候选是否数值正确且性能主张来自实测？ | 可用后端在声明容差内等价；原子实测组合成本对完整计划具有冻结误差界；性能效果由真实测量决定 | numerical failure；plan cost error；latency/energy ratio | 数值失败为 0；held-out plan latency MAPE<=10% 且 p95 APE<=20% 才外推真实硬件 Pareto；性能仅在 95% CI 支持时声明 |
| RQ8/H8 | 方法能否覆盖超出 Add+ReLU 的模型和负例？ | 多模型计划可正确接受或拒绝 | semantic acceptance accuracy | 所有 unsupported-op/域外模型正确拒绝；支持模型的合法计划完成率单独报告，无最低覆盖率替代安全性 |

## 3. 创新点的新颖性、必要性与证伪映射

| 创新主张 | 最接近已有工作 | 严格差异 | 为什么必要 | 可证伪观察 | 主实验 |
|---|---|---|---|---|---|
| 消费者可检查的完整计划 | TVM/MLIR/Glow IR 与 Collage/BYOC 后端集成 [@chen2018tvm; @lattner2021mlir; @rotem2019glow; @jeon2023collage] | 将 (G,B,L,Q,S,M,D,F,\Omega,E) 作为一个绑定对象交给 runtime，主计划和 fallback 均可被拒绝 | code/module 无法表达“在哪个 target、shape、ABI 和证据政策下可运行” | mismatch 只能在崩溃后发现，或计划字段不完整仍被加载 | Core-1 |
| 来源状态约束的合法空间 | 通用 target flags、BYOC 接口 [@apachetvm2026byoc] | backend 能力必须由 `SafeFact` basis 支撑，unknown/conflict 产生 blocker | 检测到 NPU 名称不等于拥有 command ABI | 未知/冲突 ABI 生成 deployable NPU blob | Core-1、Core-3 |
| 有边界的分层 Pareto 搜索 | AutoTVM、Ansor、TensorIR、FlexTensor、OpenTuner、NSGA-II、ParEGO [@chen2018autotvm; @zheng2020ansor; @feng2023tensorir; @zheng2020flextensor; @ansel2014opentuner; @deb2002nsgaii; @knowles2006parego] | 合法性先过滤；exact 算法给保持条件，beam 明确只给近似 | 固定 beam 会丢前沿，单目标 latency 会忽略 memory/evidence/risk | exact 在满足假设的小图丢失任一 oracle Pareto plan | Core-2 |
| 适用域索引正确性 | 静态类型/内存编译与 edge deployment [@rotem2019glow; @david2021tflm; @vandelm2023htvm] | 正确性绑定 model/shape/layout/precision/target/ABI/toolchain/runtime hash | 一次编译或板级运行不能推广到其他输入和版本 | 域外 plan 被当作域内执行 | Core-1 |
| 不增信证据产品 | PCC、CompCert、translation validation、Alive2 [@necula1997pcc; @leroy2009compcert; @pnueli1998translation; @lopes2021alive2] | 明确大多数对象是 evidence 而非 formal proof；每次变换重置受影响坐标 | physical boot 不证明 numerical，compile 不证明 memory/coherency | pass 在未运行 verifier 时新增覆盖或跨 hash 复用 | Core-3 |
| candidate-preserving deployment | autotuning 候选缓存与部署模块 | candidate 可保留供升证，但 deployable set 受义务和适用域硬约束 | 删除所有未升证候选浪费搜索，直接部署又不安全 | candidate 绕过 gate 进入可执行集合 | Core-3 |
| 独立证据 fallback | 通用异常回退和多后端放置 | 每个 fallback 有自己的完整计划、适用域和证据，不继承主计划资格 | 主后端失效时最容易发生证据降级 | fallback 使用旧 target、缺义务或越界 arena | Core-3 |

新颖性措辞限定为：CECAP 不是新 kernel tuner，而是将来源受限合法性、异构计划、fallback、适用域和声明证据统一为消费者可拒绝的部署对象。

## 4. 工作负载、合同与搜索空间冻结

### 4.1 小图 exact corpus

从第 4.2 节公开模型的真实 ONNX/TFLite 图中确定性抽取 200 个可穷举 typed sub-DAG：节点数 2-8，覆盖链、diamond、残差、fan-in/fan-out 和包含真实 unsupported op 的边界。每个子图保存原模型 URL、版本、许可证、模型 SHA-256、原节点 ID、抽取规则和真实 tensor type；不得手工拼接 toy graph。算子覆盖 Conv2D、DepthwiseConv2D、MatMul、Add、Mul、ReLU、Pool、Reshape、Transpose、Quantize/Dequantize；backend 支持表和来自 Board-P2 的实测候选成本在 `exact_space_v1.json` 中冻结。

每个图枚举 partition、algorithm、schedule 和 mapping 的完整有限空间。独立 oracle 不调用 CECAP pruning 代码，先过滤 `Legal`，再直接计算非支配集合。若完整空间超过预注册上限 (10^7) 个 complete plans，该图在冻结前缩小参数，不允许在看到结果后排除。

### 4.2 模型 corpus

| 类别 | 模型/子图 | 形状配置 | 目的 |
|---|---|---:|---|
| MLPerf Tiny 类 | image classification、visual wake words、keyword spotting、anomaly detection | 每类至少 3 | latency/energy/accuracy 可比性 [@banbury2021mlperftiny] |
| 轻量网络 | MobileNetV2/同级分类、ResNet-8/同级残差 | 各至少 3 | fusion、layout、memory |
| Transformer | attention + MLP 基础块 | 至少 5 sequence/hidden 组合 | MatMul、softmax 和 arena 压力 |
| 融合子图 | Conv-BN-ReLU、MatMul-Add-ReLU、residual block | 各至少 10 | RVV 与边界证据 |
| 负例 | unsupported op、dynamic shape、错误量化、超 arena | 每类 30 | 正确拒绝 |

模型只使用公开发布的真实权重，记录下载 URL、release/version、许可证、原始 SHA-256、ONNX/opset、预处理和 reference runtime 版本。正式输入来自官方 test/validation split：CIFAR-10（image classification）、MS COCO/VWW（visual wake words）、Speech Commands v2（keyword spotting）、ToyADMOS（anomaly detection）和 WikiText-2 的冻结 token traces（attention+MLP）[@krizhevsky2009cifar; @lin2014coco; @chowdhery2019vww; @warden2018speechcommands; @koizumi2019toyadmos; @merity2017wikitext]；每个 model/shape 分层抽取 100 个真实样本并保存原始 sample ID。零值、dtype 极值、非对齐尾部和量化边界只作为独立 robustness supplement，不计入真实性能主样本。

### 4.3 硬件合同

冻结四类合同：CPU-only、RVV-enabled、NPU-ABI-unknown/conflict、NPU-ABI-known。每类生成 ISA、ABI、shape、dtype、layout、arena、alignment、DMA/cache、hash、toolchain、DAG cycle 和 fallback evidence 等关键错误类别，每类 300 个独立 mutation。

`NPU-ABI-known` 只有在获得权威且版本绑定的 command ABI、生产 driver/provider 和物理设备执行时才属于正例；QEMU 或厂商模拟器可扩大命令流与异常路径覆盖，但不能单独把该分支升级为可部署正例。否则该分支保持 `BLOCKED-HIL`，不得用 BYOC API 或替身 provider 可调用替代。

## 5. 基线与公平性

| 组 | 基线 | 用途 |
|---|---|---|
| 编译 | TVM default AOT、TensorIR/MetaSchedule、AutoTVM、Ansor、FlexTensor | kernel/schedule 质量 |
| 图/放置 | TASO、Collage/BYOC | 图变换和后端放置 |
| 多目标 | random search、NSGA-II、ParEGO、单目标 beam | 搜索质量 |
| TinyML | TFLM、DORY、Deeploy、HTVM；硬件可行时加入 PULP-NN/XpulpNN | memory、DMA、RISC-V 执行 |
| 正确性 | reference runtime differential、code-only AOT、code + ordinary metadata | 数值和消费者拒绝 |
| 保证参照 | Alive2/translation validation 仅在 IR 兼容时执行 | 不把不兼容形式系统伪装成基线 |

所有可运行基线固定相同模型、精度、线程、CPU affinity、频率策略、内存上限和测量仪器。无法运行在同一硬件的系统只做机制或分层对照，不进入 speedup 排名。

## 6. 四个核心实验与内部子测试

| 核心实验 | 主问题 | 内部子测试 |
|---|---|---|
| Core-1 合同与完整计划合法性 | 非法/域外计划能否在 dispatch 前拒绝 | S1 合法性与 blocker；S3 完整计划与域外拒绝 |
| Core-2 搜索正确性与质量 | exact 是否保持前沿，beam 损失多少 | S2 exact/beam/多目标搜索 |
| Core-3 证据与 fallback 安全 | 是否错误升证、发射 NPU 或降级 fallback | S4 证据不增信；S6 NPU 升证；S7 fallback |
| Core-4 多模型执行与真实性能 | 是否超出 Add+ReLU 且结论来自真实测量 | S5 RVV 数值/性能；S8 端到端覆盖 |

以下 S1-S8 是四个核心实验的内部测试模块，不作为八个独立论文实验分别下结论。

### 6.1 当前实验条件与四个正式执行包

截至 2026-08-04，当前代码已经生成 plan/evidence/policy v2、AEG v2、CPU/RVV primary/fallback、逐义务 hash 和 QEMU 数值/指令冒烟结果；但 workload 仍固定为 `add_relu_f32_8`，搜索仍是 `beam_width=4` 和 `compiler_seed` cost，尚无 exact frontier、200 图 oracle、冻结模型 corpus 或实测 cost。环境具备 RISC-V 交叉编译器和 QEMU；物理验证统一预留一块 **CanMV-K230-LP4 V3.0**，在设备 serial、板卡 revision、固件、频率和仪器未登记前仍视为 `BLOCKED-HIL`。

| 核心实验 | 当前可用条件 | 开始正式实验前必须补齐 | 当前状态 |
|---|---|---|---|
| Core-1 合同与完整计划合法性 | v2 schema、hash binding、runtime trust bundle、NPU ABI blocker | 八类 mutation、合法对照、独立 legality oracle | `EXPERIMENT-NOT-READY` |
| Core-2 搜索正确性与质量 | 固定工作负载 beam smoke | exact search、200 小图、穷举 oracle、lower-bound cases、多目标 cost | `IMPLEMENTATION-NOT-READY` |
| Core-3 证据与 fallback 安全 | 逐义务 evidence、独立 CPU/RVV fallback、runtime evaluator | transform/failure corpus、失效传播 oracle；NPU 正分支需权威 ABI | Host 为 `EXPERIMENT-NOT-READY`；NPU 正分支为 `BLOCKED-HIL` |
| Core-4 多模型执行与真实性能 | Add+ReLU CPU/RVV QEMU differential 和 RVV 指令检查 | 多模型/输入 corpus、真实板 runner、measured cost 和功耗协议 | QEMU 为 `EXPERIMENT-NOT-READY`；板测为 `BLOCKED-HIL` |

执行顺序固定为 `Core-4a 板级原子标定 -> 冻结 measured cost table -> Core-2 搜索 -> Core-4b 端到端盲测`。Core-4a 在不知道搜索结果时测量每个唯一 kernel/shape/precision/mapping 以及 layout/DMA 转换原语，按预注册组合规则形成 plan cost vector；Core-4b 再对搜索前沿和基线完整执行，检验组合成本与端到端实测的偏差。两阶段同属 Core-4，不新增第五个实验；若组合模型误差超过冻结界限，Core-2 只能声称相对于该成本表的算法前沿，不能声称真实硬件 Pareto 前沿。

#### Core-1：合同合法性、完整计划与执行前拒绝实验

- **研究目的**：验证完整 plan 是否在 dispatch 前拒绝非法 backend、域外输入、错误绑定或不合格 fallback，并量化相对 code-only/ordinary metadata 的增益。
- **实验平台**：Host-P0（x86_64 Linux 6.8.0-136、Python 3.12.3、GCC 13.3）运行生产 plan generator、JSON Schema、独立 legality oracle 和真实 AIRTOS loader/evaluator；QEMU-P1 重放同一 CPU/RVV package，确认 RISC-V loader/dispatch gate 与 Host 决策一致。危险 package 只验证 pre-dispatch 拒绝，拒绝后立即终止，不执行非法 payload；本实验不需要物理板。正式运行需冻结 CPU/RAM、container、Git commit、QEMU image 与 parser/runtime ABI hash。
- **实验数据**：当前可生成的数据仅为 selftest 中固定 `add_relu_f32_8` 的 plan/evidence/policy/AEG v2，且未持久冻结。正式 base contract 全部由 Core-4 的公开模型、真实 CPU/RVV artifact 和 Board-P2 合同生成，位于 `benchmarks/cecap/v1/contracts/`；其受控 mutations 位于 `mutations/<8-classes>/`（八类各 300，共 2,400），另有 `legal_controls/` 300 项、`pairwise/` 和 `legality_oracle/`。每项保存 origin model/artifact/board-contract hash、JSON Pointer/字节 diff、expected accept/reason 和 family ID。该目录当前不存在。
- **实验单位与规模**：ISA/capability、ABI/toolchain、shape/dtype/layout、memory、graph、binding/hash、fallback、evidence-policy 八类 mutation 各 300 例，另设 300 个合法对照；同一 base contract 的变体按 family 聚类。
- **独立变量**：code-only AOT、ordinary metadata、完整 CECAP v2；对照条件除合同表达外使用同一 code artifact 和输入。
- **主端点**：关键非法计划和域外计划的 pre-dispatch acceptance 均为 0；diagnostic macro-F1>=0.95。合法 false rejection、package bytes、parse cycles 和 peak RAM 为次端点。
- **执行步骤**：冻结真实 base contract 与独立规则 oracle；按 JSON Pointer 生成单因子 mutation 和单独的 pairwise stress；构建三类 package；分别通过 Host 和 QEMU 的生产 loader/runtime 入口，在 kernel dispatch 前记录接受/拒绝、reason 和 dispatch counter；危险计划一经错误接受即记安全失败并停止，不以继续执行制造“后果证据”。
- **必须保存**：原始/变异合同、字节 diff、plan/evidence/policy/AEG hash、oracle/system decision、loader trace、dispatch counter、package size 和环境锁。
- **统计**：安全类别逐类 exact interval；diagnostic F1 给分层 bootstrap 95% CI；开销只作描述性配对比较，不与安全端点代偿。
- **失败规则**：未知/冲突 ABI 发射 deployable NPU blob、arena 越界、环、错误 hash、域外 shape 或未验证 fallback 任一进入 dispatch，均为 `SAFE-ENDPOINT-FAILED`。
- **预取结论**：当前 v2 机制预期优于 code-only 的执行前拒绝，但正式 mutation/oracle 未冻结前只能称代码支撑；通过后也只支持冻结 schema/合同域，不等于编译器形式正确。

#### Core-2：exact Pareto 保持与 bounded-beam 近似质量实验

- **研究目的**：分别回答 exact 实现是否与有限穷举集合一致，以及 beam 在固定预算下损失多少；两类结论不得合并。
- **实验平台**：Board-P2 在 Core-4a 对所有进入冻结搜索空间的唯一真实 CPU/RVV kernel/shape/precision/mapping 与 layout/DMA 转换原语采集 latency/cycles/energy-if-available/peak-memory，按预注册规则组合为 plan cost；Host-P0 随后只读该 `measured-component` cost table，运行 exact、独立 oracle 和搜索基线，并统一 process/thread、RAM 与 wall-clock 预算。QEMU-P1 复核各候选确实执行目标 ISA，但 QEMU 时间不进入 cost vector。板测缺失的原语对应候选从 confirmatory 搜索空间删除并报告覆盖率，不能以估计值补齐。
- **实验数据**：`benchmarks/cecap/v1/exact_graphs/` 为从公开真实模型确定性抽取的 200 个 2-8 节点 typed sub-DAG，逐图保留 origin model/node/tensor provenance；`exact_space_v1.json` 冻结 backend/algorithm/schedule/mapping 与 Board-P2 `measured` cost vector，`exhaustive_oracle/<graph_id>.json` 保存完整 Legal/Pareto 集，`lower_bound_cases.jsonl` 至少 10,000 项，`seeds/core2.txt` 30 个 seed。近似大图来自同一 `models/model_manifest.jsonl` 的真实 segment DAG。当前仓库只有单 workload、width=4 beam，没有这些数据、实测 cost 或 oracle。
- **实验单位与规模**：200 个 2-8 节点 typed DAG；至少 10,000 个 partial-node lower-bound cases；近似搜索使用 30 个固定 seed。完整空间大于 `10^7` 的图在冻结前缩小。
- **独立变量**：独立 exhaustive oracle、CECAP exact、random、single-objective beam、CECAP beam `K={1,2,4,8,16,32}`、epsilon-frontier、NSGA-II 和 ParEGO；合法计划评价次数与 wall time 双重匹配。
- **成本分层**：confirmatory exact/beam、HV 和 Pareto 表只读取 Core-4a/Board-P2 产生的 `measured-component` cost；`compiler_seed`、解析模型、QEMU timing 和模拟 cost 仅用于开发调试，不进入正式 n。Core-4b 单列报告 plan cost prediction error，并以冻结界限判断能否外推到真实硬件前沿；若某 objective 无仪器（如 energy），预注册时删除该维度并重冻搜索空间，不允许插补。
- **主端点**：每图 exact Pareto recall=1 且 false-frontier=0；预注册 K=8 的跨图 median recall>=0.90，normalized-HV 差的 bootstrap 95% CI 下界>=-0.05。
- **执行步骤**：由不 import CECAP pruning/dominance 的 oracle 枚举 Legal complete plans；独立 canonical serializer 生成 plan ID；运行 exact 并比较集合；穷举 partial extensions 验证 lower bound；最后在相同预算运行各近似方法。
- **必须保存**：graph/search-space hash、完整 oracle/frontier 集、所有 pruned nodes/reasons、预算、seed、peak RAM、cost-source 标签和集合 diff。
- **统计**：exact 是逐图集合判定，不以 p-value 放宽；beam 指标按图分层 bootstrap，并报告所有 K 的敏感性曲线。
- **失败规则**：exact 丢失或错误加入任一 plan 即 H2 失败；beam 不达阈值只撤回近似质量主张，不能反推 exact 失败。
- **预取结论**：当前代码没有 exact 路径，因此本实验首先是必要实现门；若只运行现有 width=4 smoke，不得出现“Pareto 保持”措辞。

#### Core-3：证据失效、NPU blocker 与独立 fallback 实验

- **研究目的**：验证普通编译变换不会自动增信，环境变化不会复用 stale evidence，fallback 不会继承 primary 的部署资格。
- **实验平台**：Host-P0 通过生产 evidence/plan transform 和真实 AIRTOS evaluator 执行失效传播；QEMU-P1（RISC-V GCC 13.3、QEMU 8.2.2）通过生产 RISC-V loader/provider 路径执行 CPU/RVV fallback reference differential；Board-P2 对同一 fallback artifact 做实板复核。NPU 正分支仅在权威 ABI、生产 driver/provider 和 Board-P2 物理执行均可用时加入，否则保持 `BLOCKED-HIL`。
- **实验数据**：`benchmarks/cecap/v1/evidence_mutations/` 保存七类各 300（2,100）transform 与组合反例，`fallback_scenarios/` 保存六类各 300（1,800）环境变化，`mutations/npu_abi/` 保存无 ABI 和冲突 ABI 各 300，`oracles/evidence_invalidation.json` 定义变换-失效坐标矩阵；每例绑定 primary/fallback plan、evidence、policy、artifact 和 verifier hash。当前只有固定 Add+ReLU 的 CPU/RVV obligation/fallback 正例，正式 mutation 数据不存在。
- **实验单位与规模**：shape/layout/precision/memory/ABI/toolchain/artifact 七类 transform 各 300；segment-pass/boundary-fail 等组合反例各 100；NPU busy/offline、RVV unavailable、arena 缩小、policy 提高、evidence 过期、target/toolchain 改变六类 fallback 场景各 300；无 ABI/冲突 ABI 各 300。
- **独立变量**：无失效传播、仅 hash binding、完整 coordinate invalidation；fastest-only、共享 primary evidence fallback、独立证据 fallback。
- **主端点**：false evidence promotion、stale reuse、无 ABI NPU emission 和 unsafe fallback 均为 0；completion 和 switch cycles 只作可用性指标。
- **执行步骤**：先绑定完整 evidence vector；施加单一 transform 但不运行 verifier；由独立 obligation oracle计算应失效坐标；尝试 candidate->deployable；再注入 provider/环境变化并比较三种 fallback；新 fallback 必须有独立 plan/evidence hash 并通过 AIRTOS gate。
- **必须保存**：变换前后 plan、坐标失效矩阵、verifier allowlist、primary/fallback identity、选择原因、runtime decision 和失败 artifact。
- **统计**：逐安全类别 exact interval；选择原因 macro-F1、completion 和 switch cost 单独报告。
- **失败规则**：未运行 verifier 而 pass 坐标增加、跨 hash 复用证据、无权威 ABI 生成 NPU blob或 fallback 绕过最低 policy，任一即安全失败。
- **预取结论**：当前固定 Add+ReLU 已提供机制实例，预计可支撑负分支；K230 NPU 正分支必须等权威 command ABI、driver/provider 和板级 reference diff，缺失时正确结论是 blocked。

#### Core-4：多模型数值正确性与 CanMV-K230 真实性能实验

- **研究目的**：把“生成目标指令”“数值正确”“实板更快/更省能”拆成三个独立结论，并验证方法超出 Add+ReLU。
- **实验平台**：Reference-P0 在 Host-P0 上运行冻结的 ONNX Runtime/reference implementation；QEMU-P1 验证 RVV execution path 与 objdump；Board-P2 为单块 CanMV-K230-LP4 V3.0，执行 CPU/RVV 数值复核、latency/cycles/peak-memory 和可选功耗测量。三层结果分表，QEMU 时间不进入板级性能。
- **实验数据**：`benchmarks/cecap/v1/models/model_manifest.jsonl` 覆盖 MLPerf Tiny 四任务类、MobileNetV2/轻量分类、ResNet-8、attention+MLP 和从这些模型抽取的三类融合子图；`models/files/` 保存公开发布的真实权重与许可证。主输入为 CIFAR-10 test、MS COCO/VWW validation、Speech Commands v2 test、ToyADMOS evaluation 和 WikiText-2 test 的冻结 sample IDs，每 model/shape 分层抽取 100 个真实样本；`inputs/.../provenance.json` 保存 dataset/version/split/sample/hash/preprocess，`reference_outputs/` 保存输出 hash 与容差。零值/极值/非对齐/量化边界以及 unsupported/dynamic/quant/arena 各 30 仅作为 robustness/拒绝补充集，单列且不计入真实性能分母。当前仓库正式范围内没有该 corpus，`third_party/mlperf-tiny` 只能作为候选来源，不能直接算作已冻结数据。
- **实验单位与规模**：使用第 4.2 节冻结模型/子图；每 model/shape/backend 100 个真实 test/validation 样本；Host/QEMU 每输入逐例 differential；CanMV-K230 每配置 10 次 warm-up+30 次随机交错测量，性能统计以 model/shape 为独立单位。
- **物理平台合同**：一块 CanMV-K230-LP4 V3.0，记录 PCB revision、SoC/内存配置、device serial、固件/image hash、toolchain、CPU/RVV 频率、温度、散热、电源和仪器校准；板卡更换或 revision 改变必须成为新实验 block。
- **独立变量**：reference runtime、TVM CPU AOT、TVM default RVV、CECAP RVV；NPU 仅在权威 ABI/provider 完成后加入，不因板上存在 NPU 名称自动加入。
- **主端点**：冻结域内 numerical failure=0；unsupported/dynamic/quant/arena 负例错误接受=0。Core-4b 从 frontier、near-frontier 和 dominated baseline 分层抽取至少 20% complete plans 作为 held-out end-to-end 校准集，要求 latency MAPE<=10% 且 p95 APE<=20% 才允许把 Core-2 前沿称为真实硬件 Pareto；性能比率只在 95% CI 完全支持时声明；energy 无同步仪器时记 NA。
- **执行步骤**：冻结公开模型许可、权重 hash、预处理和容差；Core-4a 在不知道搜索输出时测量唯一 kernel/转换原语并冻结 `measured-component` DB；运行 Core-2 后，Core-4b 生成 reference，在 QEMU 跑 CPU/RVV differential 和 objdump，在板上 readback 镜像并验证 run ID，随机交错执行搜索前沿与基线；采集 latency/cycles/peak memory/temperature/energy，并计算组合成本对端到端实测的误差。
- **必须保存**：模型/输入/output hash、build/objdump log、板卡合同、原始串口/计时/功耗数据、warm-up 标记、运行顺序、异常和全部失败样例。
- **统计**：数值按输入逐例判断；性能以 model/shape 为配对单位，报告 median、p95、ratio 和分层 bootstrap 95% CI，不把 30 次重复当成 30 个独立模型。
- **失败规则**：任一超容差输出撤回对应 domain；QEMU latency、`compiler_seed` 或单板未校准读数不能支持 speedup/energy；组合成本误差超过预注册界限时撤回“真实硬件 Pareto”措辞，但不影响 Core-2 相对于冻结 cost table 的集合正确性；没有实板时只允许形成 execution-path 结论。
- **预取结论**：预期 CPU/RVV 可在部分静态子图保持数值一致，但是否加速必须由 CanMV-K230 实测决定；即使没有加速，Core-1/3 的部署资格贡献仍可独立成立。

### 6.2 全文声明覆盖矩阵

| 核心实验 | 唯一负责的 RQ/假设 | 覆盖的创新与理论 | 覆盖的实现对象 | 允许进入摘要/结论的主张 | 未通过时必须删除或降级的主张 |
|---|---|---|---|---|---|
| Core-1 | H1、H4 | 完整计划、来源约束合法空间、适用域索引；`Legal(P|H,W)` 与消费者拒绝 | plan/evidence/policy v2、AEG v2、loader/runtime evaluator | 关键非法、域外和错误绑定计划在 dispatch 前被拒绝 | “消费者可检查完整计划”“来源约束合法空间”“域外拒绝” |
| Core-2 | H2、H3 | exact/approx 分界的分层 Pareto 搜索；exact frontier 保持与 beam 近似边界 | exact/beam、独立 exhaustive oracle、cost-source 分层 | exact 在冻结有限空间与 oracle 集合一致；K=8 仅有测试域近似质量 | “Pareto 保持”或“beam 有用近似”中失败的对应一项 |
| Core-3 | H5、H6，H1 的 NPU 负分支 | 不增信证据产品、candidate/deployable 分离、独立 evidence fallback | obligation/evidence、trust bundle、NPU blocker、primary/fallback | transform 不凭空升证；无 ABI 不发射 NPU；fallback 不继承 primary 资格 | “证据不增信”“安全 NPU blocker”“独立 fallback” |
| Core-4 | H7、H8 | 条件可执行性、数值等价与实验外部效度 | 多模型 CPU/RVV、QEMU、CanMV-K230 measured cost；可选 NPU 正分支 | 所测模型/shape 数值正确；只有实测 CI 支持的后端才声明性能差异 | “超出 Add+ReLU”“数值正确”“板级加速/能耗”中的对应一项 |

全文覆盖规则：CECAP 的中心贡献由 Core-1 和 Core-3 共同支撑；Core-2 支撑搜索理论，Core-4 支撑执行与外部效度。Core-4 未观察到加速不否定合同贡献，但没有多模型数值结果时不得把固定 Add+ReLU 外推；没有权威 NPU ABI 时所有 NPU 正向措辞保持 `BLOCKED-HIL`。

### 子测试 S1：合法性、错误拒绝和 blocker

**步骤**：对每个合同 mutation 生成计划候选；分别运行 target-string-only、metadata-only 和完整 CECAP filter。独立 oracle 根据冻结约束重新判定。

**主指标**：

\[
IPAR=\frac{|\{P:OracleLegal(P)=0\land Filter(P)=accept\}|}{|\{P:OracleLegal(P)=0\}|},
\]

以及 legal false rejection、blocker macro-F1、constraint-check latency。

**决策**：每个关键类别 IPAR=0。unknown/conflict NPU ABI 产生 deployable blob、arena 越界、错误 hash、环或未验证 fallback 任一通过，H1 失败。合法误拒只影响可用性，不抵消错误接受。

### 子测试 S2：exact frontier、beam 与多目标搜索

#### S2-a：exact 验证

对 200 个小图分别运行穷举 oracle 与 exact hierarchical frontier。比较 canonical plan ID 集合：

\[
Recall_P=\frac{|F_{CECAP}\cap F^*|}{|F^*|},\qquad
FalseFrontier=\frac{|F_{CECAP}\setminus F^*|}{|F_{CECAP}|}.
\]

同时对 partial-node lower bound 做随机性质检验：对至少 10,000 个节点穷举 `Ext(n)`，验证每个成本维度 ℓ(n) 不大于所有完成计划成本。任一反例必须保留。

#### S2-b：近似搜索

在大图上比较 random、single-objective beam、CECAP beam (K\in\{1,2,4,8,16,32\})、epsilon-frontier、NSGA-II 和 ParEGO。随机方法使用 30 个固定 seed，预算以合法计划评价次数和 wall-clock 双重匹配。

报告 Pareto recall（有 oracle 时）、normalized hypervolume、epsilon indicator、best latency/memory/debt、合法候选比例、搜索时间和 peak RAM。H3 只评价预注册 `K=8`；其余宽度为敏感性分析。

**决策**：exact 任一图 recall<1 或 false-frontier>0 否决 H2。beam 未达 H3 只说明近似策略不足，不能反推 exact 定理失败。

### 子测试 S3：完整计划对象与域外拒绝

**条件**：code-only AOT、code+ordinary metadata、完整 CECAP plan。

**变异**：错误 target/model hash、shape、dtype、layout、ABI/toolchain revision、provider 缺失、arena 不足、evidence policy 提高和 fallback 过期；每类 300 个。

**步骤**：在任何 kernel dispatch 前通过 Host/QEMU 的生产消费者 loader/admission 运行并记录拒绝阶段和原因。危险样本一经错误接受即停止；主端点只依赖 pre-dispatch decision 和 dispatch counter，不执行非法 payload。

**指标**：unsafe pre-execution acceptance、pre-dispatch detection recall、diagnostic macro-F1、package bytes、parse cycles、peak RAM。

**决策**：完整计划对关键 mismatch 的错误执行为 0 且诊断达标支持 H4。若错误仅在执行崩溃后发现，则 H4 不支持。

### 子测试 S4：证据产品、不增信与组合

#### S4-a：证据坐标

使用 `source/schema/build/numeric/resource/virtual/physical/timing/supply-chain` 产品空间。对 shape、layout、precision、memory、ABI、toolchain 和 artifact hash 变换分别标记应失效的坐标。

#### S4-b：变体

每种变换生成 300 个计划；仅运行普通 transform，不调用 verifier，随后尝试晋升。另构造 segment pass 但 boundary fail、physical boot pass 但 numeric fail、fallback 缺证据、hash/version 不一致等组合反例。

**指标**：false evidence promotion、stale evidence reuse、错误组合接受、obligation attribution accuracy。

**决策**：任一受影响坐标保持 pass 并用于 deployable 决策，H5 失败。物理启动不能覆盖 numerical/timing；compile 不能覆盖 resource/coherency。

### 子测试 S5：RVV 执行、数值和实测性能

**条件**：reference runtime、TVM CPU AOT、TVM default RVV、CECAP tensorized RVV；硬件匹配时加入厂商库/PULP-NN 类实现。

**正确性**：对每个模型/shape 使用至少 100 个来自官方 test/validation split 且带 sample ID/hash 的真实输入；零值、极值、非对齐尾部和量化边界放入独立 robustness supplement，不替代真实数据分母。浮点判定：

\[
|y-\hat y|\le atol+rtol|y|,
\]

`atol/rtol` 在每个 dtype/模型 manifest 中按 reference runtime 先验规范冻结。量化模型同时报告 exact match、top-1 agreement 和任务 accuracy 差。

**性能**：每个配置 10 次 warm-up、至少 30 次独立测量；顺序随机交错。固定/记录频率、温度、线程、固件和输入。报告 median、p95、bootstrap 95% CI、cycles、peak memory、编译时间；能耗使用同一仪器窗口并报告测量误差。

**决策**：任一超容差输出是该适用域的数值失败。仅当 speedup ratio 的 95% CI 完全高于 1 才写“更快”；否则写“未观察到可靠加速”。QEMU 只用于 execution path 和指令检查，不进入真实板 speedup。

### 子测试 S6：NPU ABI blocker 与候选升证

对无 ABI、冲突 ABI、权威 ABI 三类合同运行相同模型子集。

- 无/冲突 ABI：NPU blob emission 必须为 0，且生成可解释 blocker 或选择已验证 CPU/RVV fallback。
- 权威 ABI：依次验证 command encoding、buffer/DMA 范围、barrier、生产 driver acceptance、QEMU/厂商模拟路径、reference diff 和真实设备执行。模拟结果只覆盖命令流与异常路径，不能代替物理正分支；每项证据独立记录。

只有后一类所有必要坐标为 pass，才能从 candidate 移入 deployable。若没有权威 ABI/provider，协议结果只包含前两类并明确第三类 blocked。

### 子测试 S7：fallback 与环境变化

**故障类别**：NPU busy/offline、RVV 不可用、arena 不足、deadline policy 收紧、evidence 过期、target/toolchain hash 改变，每类 300 个场景。

**条件**：fastest-only、无独立证据 fallback、CECAP evidence-bounded fallback。

**指标**：unsafe fallback、completion、选择原因准确率、switch cycles、latency degradation。

**决策**：CECAP 错误 fallback 为 0 支持 H6。任务被拒绝是允许结果；为了完成率绕过最低证据策略即失败。

### 子测试 S8：端到端模型与平台覆盖

在 CPU-only、RVV、NPU-unknown 和可用时的 NPU-known 合同上运行第 4.2 节完整 corpus。输出每个模型的 accepted/rejected、segment mapping、layout conversion、peak arena、evidence completion 和真实 latency。

unsupported op、dynamic shape 域外输入、量化不一致和超 arena 必须保持可解释拒绝。不得静默替换算子、改变模型精度或删除负例以提高 coverage。

## 7. 统计、样本量与多重比较

- 安全负例每类 300 个，零事件时报告单侧 95% exact upper bound；类别单列。
- exact corpus 固定 200 图；H2 是集合相等判定，不用 p-value 替代。
- 随机搜索 30 seed；报告中位数、IQR 和按图分层 bootstrap 95% CI。
- 性能每配置 10 warm-up + 30 measurement；模型为配对单位，原始运行不是虚增的独立样本。
- confirmatory 假设按 H1-H7 顺序分别报告；同一假设下多个次指标用 Holm 校正，探索图用 BH-FDR 0.05。
- 不因结果有利提前停止。OOM、编译失败、unsupported 和 timeout 按预定义结果类别保留。

## 8. Artifact 和 schema

```text
results/cecap/<protocol_hash>/<experiment>/<workload>/<target>/<condition>/<seed>/
  run.json
  hardware_contract.json
  workload.json
  model.sha256
  plan.json
  plan.canonical.sha256
  legality_oracle.json
  evidence.jsonl
  search_trace.jsonl
  build.log
  reference_outputs.npz.sha256
  outputs.npz.sha256
  measurements.csv
  environment.json
```

`measurements.csv` 最少字段：run_id、warmup、iteration、backend、latency_ns、cycles、energy_uj、peak_bytes、temperature、frequency、status。缺失能耗不得填 0，应为 NA 并附原因。

## 9. 结果表与图占位

**表 1：合法性与域外拒绝**

| 条件 | mutation class | n | illegal accepted | legal rejected | diagnostic F1 | check cycles |
|---|---:|---:|---:|---:|---:|---:|
| TBD | TBD | TBD | TBD | TBD | TBD | TBD |

**表 2：搜索质量**

| 方法 | budget | Pareto recall | hypervolume | epsilon | search time | peak RAM |
|---|---:|---:|---:|---:|---:|---:|
| TBD | TBD | TBD | TBD | TBD | TBD | TBD |

**表 3：执行与证据**

| model/shape | backend | max error | task accuracy | median latency | energy | evidence vector |
|---|---|---:|---:|---:|---:|---|
| TBD | TBD | TBD | TBD | TBD | TBD | TBD |

预注册图：Fig. 1 exact 与 beam 前沿叠图；Fig. 2 beam width-recall-cost 曲线；Fig. 3 各 mismatch 的拒绝混淆矩阵；Fig. 4 latency-memory-evidence-debt Pareto 图；Fig. 5 证据坐标变换失效矩阵。

## 10. 条件化结论模板

**H1/H4/H5/H6 支持时**：

> 在预注册合同 mutation、适用域变化和证据/fallback 反例中，CECAP 未接受任何关键非法或证据不足计划，并在执行前给出达到阈值的拒绝原因。结果支持“消费者可检查计划合同”在所测域内有效，但不等于编译器形式验证。

**任一安全假设不支持时**：

> 观察到至少一个非法计划、域外执行、错误升证或不安全 fallback。相应安全主张不成立；该反例必须完整报告，性能结果不能抵消该失败。

**H2 支持时**：

> 对 200 个冻结小图，exact 分层算法与穷举 Pareto oracle 集合一致，支持定理在所检查有限空间及其前提下的实现一致性。

**H2 不支持时**：

> exact 搜索丢失或错误保留至少一个 Pareto 计划，说明 lower bound、扩展或支配实现与定理前提不一致，不能声称 Pareto 保持。

**H3 支持/不支持**：达到阈值时只写“bounded beam 在测试预算下获得所述近似质量”；未达到时写“固定 beam 未提供稳定近似保证”。两种结果都不得使用“Pareto 完备”。

**H7 支持时**：

> 所测 backend 在冻结容差和模型域内通过数值比较；对置信区间完全支持的指标，报告对应实测性能差异。

**H7 不支持时**：

> 至少一个模型/shape 超出数值容差，或性能区间不支持预期优势；因此撤回该适用域的正确性或加速主张，不将 QEMU/seed 结果替代为板级性能。

## 11. 执行前检查清单

- [x] plan/evidence/policy v2 与 AEG v2 已携带固定域的 domain、primary/fallback、memory、evidence、arrival/recovery 和 ABI binding
- [ ] 将该对象扩展并冻结到一般 segment DAG、模型/shape/backend corpus
- [ ] 冻结 200 个 exact 图、独立穷举 oracle 和搜索空间
- [ ] 冻结模型/shape、reference runtime、数值容差和公开权重哈希
- [ ] 用实测 cost 替换正式实验中的 `compiler_seed`
- [ ] 冻结基线 commit、编译 flags、容器和目标频率策略
- [ ] NPU positive branch 具备权威 ABI 与真实 provider，否则保持 blocked
- [ ] 生成协议哈希；任何排除和 deviation 在分析前登记
- [ ] 发布计划、搜索 trace、输出 hash、原始测量和全部失败样例

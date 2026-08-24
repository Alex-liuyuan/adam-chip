# CECAP 实验实施蓝图：计划对象、素材与结论判定

## 0. 文档定位

- 对应论文：[理论设计](./theoretical_design.md)
- 预注册规则：[实验协议](./experiment_protocol.md)
- 状态：`PRE-RESULT / UNVERIFIED`
- 目标：把“契约与证据携带的加速计划”实现为消费者可检查对象，并给出可以直接制作、运行和审计的实验素材规范。
- 结果纪律：`compiler_seed` 中的 10/4 us 不是测量；QEMU 结果不是板级性能；未获得权威 NPU ABI 时，NPU 正分支只能是 `BLOCKED-HIL`。

## 1. 实现设计目的与边界

CECAP 要解决的不是普通 kernel tuning，而是异构边缘 AI 中“一个候选何时具有部署资格”的问题。实现必须把目标合同、图划分、算法、调度、映射、内存、适用域、fallback 和逐坐标证据放进同一个可哈希、可验证、可拒绝的计划对象。

设计必须分开回答：

1. 候选是否合法：未知/冲突硬件能力、越界 arena、错误 ABI 或环不能进入合法空间。
2. 搜索是否正确：exact 模式与独立穷举前沿集合相同；beam 只报告近似质量。
3. 计划是否可部署：消费者在 dispatch 前检查域、证据和环境。
4. 执行是否正确：reference differential、真实延迟和能耗各自提供不同证据。
5. 环境变化后如何退化：fallback 必须独立合法且独立有证据。

本文不保证任意图上的 beam 完备，不把编译成功等价为数值/资源/物理/timing 正确，不在未知 ABI 上推断 NPU command encoding，也不把单个 Add+ReLU 的 smoke test 推广为模型覆盖。

## 2. 当前代码基线与 readiness 缺口

| 项目 | 当前代码事实 | 当前可验证 | 正式实验所需 |
|---|---|---|---|
| workload | `compiler.py` 固定 `add_relu_f32_8` | CPU/RVV AOT smoke | 接入冻结模型/小图 corpus |
| cost | `cost.db` 写入 10/4 us `compiler_seed` | 搜索流程 smoke | 正式搜索单独读取 CanMV-K230 `measured` 表，缺项不插补 |
| search | beam width=4、单工作负载、单 latency | 基本选择路径 | exact frontier、独立穷举 oracle、多目标和 K 敏感性 |
| plan/AEG | plan/evidence/policy v2 与八类 section 的 AEG v2；固定单 segment、64 B arena | canonical hash、Schema、loader/runtime roundtrip | 一般 segment DAG、完整模型/shape/backend corpus 和正式 schema freeze |
| CPU/RVV | QEMU 执行、reference diff、objdump | execution path/数值 smoke | 真实板时延/能耗、完整 dtype/shape/tail corpus |
| NPU | `npu_blob_emitted=false`，无 ABI 时 blocker/fallback | 负分支 | 权威 ABI、生产 driver/provider 与物理执行后才有正分支；QEMU/模拟器只扩展路径覆盖 |
| evidence | CPU/RVV 逐义务 scope/artifact/verifier hash、primary/fallback 独立 obligation、产品 trust bundle | 固定域逐义务 runtime evaluation | transform 失效传播、artifact 重哈希、policy 变化和大规模 mutation oracle |

任何正式性能表若仍读取 `source=compiler_seed`，该表自动判为 `INVALID-MEASUREMENT`。

## 3. `soc-image.cecap-plan.v2` 最小 schema

```json
{
  "schema": "soc-image.cecap-plan.v2",
  "plan_id": "sha256:...",
  "bindings": {
    "model": "sha256:...", "target": "sha256:...",
    "toolchain": "sha256:...", "runtime": "sha256:..."
  },
  "graph": {"segments": [], "edges": []},
  "layout": [],
  "quantization": [],
  "schedules": [],
  "mapping": [],
  "memory": {"arena_bytes": 0, "alignment": 0, "buffers": []},
  "coherency": {"transfers": [], "cache_ranges": []},
  "domain": {"shapes": [], "dtypes": [], "layouts": [], "abi": "..."},
  "fallbacks": [{"plan_id": "sha256:...", "activation": "..."}],
  "obligations": [],
  "evidence": [],
  "status": "candidate"
}
```

### 3.1 不可省略的不变量

- `plan_id` 是除签名外 canonical JSON 的 SHA-256；数组排序和数值规范化规则必须固定。
- `bindings` 任一 hash 改变，旧证据不可静默复用。
- 每个 segment 的 backend 必须有 `SafeFact` capability basis。
- 每条跨 backend edge 必须有 layout/precision 转换、buffer、coherency 和成本。
- 主计划与每个 fallback 分别满足 `Legal`、domain 和 evidence policy。
- `candidate` 可以保存和继续升证，但 runtime 只能加载 `deployable`。

### 3.2 证据坐标

```text
source, schema, build, numeric, resource, virtual,
physical, timing, supply_chain, coherency
```

每条证据包含 `verifier_id`、输入/输出 hash、domain hash、toolchain hash、outcome、时间和失效依赖。普通 transform 只能保持或失效证据，不得把 `unknown/fail` 提升为 `pass`。

## 4. 编译管线与接口

```text
contract normalize
  -> legal backend space
  -> graph partition candidates
  -> algorithm candidates
  -> schedule candidates
  -> resource mapping
  -> memory/coherency construction
  -> exact frontier | bounded beam
  -> evidence binding
  -> candidate/deployable decision
  -> package + AEG v2
```

### 4.1 阶段 I/O 与完成判据

| 阶段 | 输入 | 输出 | 完成判据 | 失败处理 |
|---|---|---|---|---|
| normalize | Hardware IR、模型 manifest | canonical contract/workload | schema 与 hash 可重现 | invalid/blocked，不猜默认值 |
| legal space | contract、op support table | legal backend per op | 与独立规则 oracle 一致 | 输出 blocker |
| partition | typed DAG、backend set | segment DAG candidates | 保持依赖和类型 | 丢弃非法候选并记原因 |
| algorithm/schedule | segment | implementations | 每项有适用 shape/dtype | candidate |
| mapping/memory | candidates、arena | complete plans | 无越界、alignment/DMA 合法 | illegal |
| search | complete/partial plans | frontier/beam | exact 集合或预算记录完整 | 保留 trace |
| evidence | plan、verifier outputs | evidence vector | hash/domain 对齐 | evidence debt |
| package | deployable plan | plan.json、AEG、code | loader 可在 dispatch 前拒绝域外输入 | 不允许 code-only fallback |

### 4.2 exact 与 beam 分离

```text
ExactFrontier(node):
  if complete(node): return {node} if Legal(node) else empty
  children = all legal one-step extensions(node)
  union = merge(ExactFrontier(child) for child in children)
  return nondominated(union)

BeamFrontier(node, K):
  expand legal children
  remove dominated candidates under registered objectives
  rank by frozen tie-breaker
  keep K
```

只有 ExactFrontier 在有限空间和定理前提下测试 Pareto 保持；BeamFrontier 必须在输出中写入 `approximate=true`、K、预算和丢弃 trace。

## 5. 实验素材总 manifest

```text
benchmarks/cecap/v1/
  manifest.json
  exact_graphs/*.json
  exact_space_v1.json
  exhaustive_oracle/<graph_id>.json
  models/model_manifest.jsonl
  models/files/...
  inputs/<model_id>/<input_id>.npz
  reference_outputs/<model_id>/<input_id>.npz.sha256
  contracts/*.json
  mutations/<class>/<case_id>.json
  evidence_mutations/*.json
  fallback_scenarios/*.json
  measurement_protocol.json
  seeds.txt
  exclusions.jsonl
```

### 5.1 200 个小图素材

| 结构 | 数量 | 节点范围 | 必含特征 |
|---|---:|---:|---|
| chain | 40 | 2-8 | fusion、layout conversion |
| diamond | 35 | 4-8 | 分支汇合、buffer lifetime |
| residual | 35 | 4-8 | Add 与 shape 对齐 |
| fan-out | 30 | 3-8 | 多消费者、共享 tensor |
| fan-in | 30 | 3-8 | 多生产者同步 |
| unsupported/mixed | 30 | 2-8 | 孤立 unsupported op 或 CPU fallback |

200 图必须由第 5.2 节公开模型的真实 ONNX/TFLite 图按冻结规则抽取，不得手工拼装。每图记录 origin URL/release/license/model SHA-256、原节点 ID、tensor type 和抽取脚本 hash。算子至少覆盖 Conv2D、DepthwiseConv2D、MatMul、Add、Mul、ReLU、Pool、Reshape、Transpose、Quantize/Dequantize；shape、dtype、layout 来自原图，backend support、algorithm、schedule、mapping 和 Board-P2 实测 cost vector 另行冻结。完整空间超过 `10^7` complete plans 的图必须在冻结前缩小，不得在看到 CECAP 结果后排除。

独立穷举 oracle 使用单独模块，不 import CECAP pruning、dominance 或 canonical-ID 实现。两者只共享冻结 JSON schema和原始成本表；集合比较使用独立 canonical serializer 交叉确认。

### 5.2 模型与输入素材

| 组 | 最低配置 | 每配置输入 | 用途 |
|---|---:|---:|---|
| MLPerf Tiny 四任务类 | 每类 3 shape/precision | 100 | 可比较 workload |
| MobileNetV2/轻量分类 | 3 | 100 | depthwise、layout、arena |
| ResNet-8/残差网络 | 3 | 100 | residual/fan-in |
| attention+MLP block | 5 seq/hidden | 100 | MatMul、softmax、内存压力 |
| Conv-BN-ReLU | 10 子图 | 100 | fusion/RVV |
| MatMul-Add-ReLU | 10 子图 | 100 | tensorize/tail |
| residual block | 10 子图 | 100 | 多 segment 边界 |
| 负例 | unsupported/dynamic/quant/arena 各 30 | 1 最小复现 | 拒绝准确性 |

正式模型只接受公开发布的真实权重。每组 100 个主输入从官方 test/validation split 分层抽取：CIFAR-10、MS COCO/VWW、Speech Commands v2、ToyADMOS 或 WikiText-2 [@krizhevsky2009cifar; @lin2014coco; @chowdhery2019vww; @warden2018speechcommands; @koizumi2019toyadmos; @merity2017wikitext]；保存 dataset URL/version/license、split、sample ID、原始 hash 和预处理 hash。零值/常量、dtype 极值、非对齐尾部和量化边界各自形成补充 robustness corpus，不计入真实任务性能分母。模型保存 URL、release、许可证、原始 SHA-256、ONNX opset 和 reference runtime，禁止用随机权重替代公开 checkpoint。

### 5.3 合同 mutation 素材

每个关键类别 300 个，按基础合同 family 分层：

| 类别 | 主要变异 | oracle 标签 |
|---|---|---|
| ISA/capability | RVV 缺失、NPU unknown/conflict、扩展拼写漂移 | legal backend set |
| ABI/toolchain | command ABI、calling convention、driver/runtime/tool revision | accept/block + reason |
| shape/dtype/layout | 域外 shape、错误 precision、遗漏转换 | legal/illegal |
| memory | arena、alignment、lifetime overlap、DMA range | legal/illegal |
| graph | cycle、missing edge、错误 dependency | legal/illegal |
| binding/hash | model/target/artifact/evidence hash mismatch | pre-dispatch reject |
| fallback | 过期、缺证据、域外、资源不可用 | selected/reject |
| evidence policy | policy 提高、坐标失效、verifier 未运行 | deployable/candidate |

每个 mutation 只计入一个主类别；组合 stress set 另列。mutation 必须记录改变前后 JSON Pointer 和字节级 diff。

### 5.4 真实测量素材

- 测量分两阶段：Core-4a 盲于搜索结果地采集唯一 kernel/shape/precision/mapping 与 layout/DMA 转换原语；Core-2 只读冻结表；Core-4b 再对前沿与基线做端到端盲测。
- 每个 model/shape/backend 先做 10 次 warm-up，再做 30 次独立 measurement；运行顺序随机交错。
- `measurements.csv` 记录 latency_ns、cycles、energy_uj 或 NA、peak_bytes、temperature、frequency、firmware、device serial、仪器与校准日期。
- 开发库可保留 `seed/qemu/model` 标签供冒烟与诊断；冻结的 confirmatory cost table 只含 `source=measured-component`，并保存组合规则与原始 measurement IDs。QEMU 仅支持执行路径与指令证据，缺失物理原语的候选删除并报告覆盖率，不得填充模拟值。
- 能耗窗口必须覆盖同一工作单元并扣除/报告 idle baseline；无法同步时填 NA，不得填 0。
- Core-4b 对每个入选完整计划保存 predicted/actual ratio 和绝对误差；误差超过预注册界限时，Pareto 结论限定为“相对于冻结 measured-component cost table”。

## 6. 四个核心实验与实施卡

| 核心实验 | 内部实施卡 | 唯一主端点 |
|---|---|---|
| Core-1 合同与完整计划合法性 | S1 合法性/blocker；S3 域外拒绝 | illegal/unsafe pre-dispatch acceptance |
| Core-2 搜索正确性与质量 | S2 exact/beam | exact 集合相等；K=8 recall/HV |
| Core-3 证据与 fallback 安全 | S4 证据；S6 NPU；S7 fallback | false evidence/NPU/fallback promotion |
| Core-4 多模型执行与真实性能 | S5 RVV；S8 端到端覆盖 | numerical failure 与真实性能 CI |

以下实施卡是四个核心实验内部的子测试，不单独扩张论文实验数量。

### 子测试 S1：合法性、错误拒绝与 blocker

**目的**：验证优化前的合法空间是否由权威合同约束。

**素材**：八类 mutation 各 300；对应未变异合法合同至少 50；独立规则 oracle。

**执行**：用 target-string-only、metadata-only 和完整 filter 生成候选；对每个候选保存逐约束判定；oracle 独立重判；测 constraint-check cycles。

**输出**：`candidate.json`、`filter_trace.jsonl`、`oracle.json`、`diff.json`。

**结论锁**：逐关键类别 IPAR=0 才支持 H1；任何 unknown/conflict NPU blob、arena 越界、环或错误 hash 被接受均为安全端点失败。合法误拒只影响可用性。

### 子测试 S2：exact frontier 与 bounded beam

**目的**：分别验证 exact 实现一致性和 beam 工程近似质量。

**素材**：从公开模型抽取并保留 provenance 的 200 个真实小图；Board-P2 覆盖全部候选的实测 cost table；至少 10,000 partial nodes 的 lower-bound property cases；真实大图模型 corpus；30 个固定搜索 seed。

**执行**：穷举 oracle 与 exact CECAP 分别产生 plan-ID 集；逐图比较；对 partial node 穷举全部 extensions；大图按相同合法评价次数和 wall time 运行 random、single-objective beam、CECAP K={1,2,4,8,16,32}、epsilon-frontier、NSGA-II、ParEGO。

**输出**：frontier 集、search trace、pruned reason、budget、peak RAM、HV/epsilon。

**结论锁**：exact 任一 recall<1 或 false-frontier>0 即 H2 不支持；K=8 达预注册 recall/HV 门槛才支持 H3。其他 K 只能作敏感性分析。

### 子测试 S3：完整计划与域外拒绝

**目的**：证明完整计划能在 kernel dispatch 前发现 code-only 无法表达的环境不匹配。

**素材**：target/model hash、shape、dtype、layout、ABI、toolchain、provider、arena、policy、fallback 十类各 300；合法对照 300。

**执行**：分别打包 code-only、ordinary metadata、CECAP v2；同一 package 经 Host 与 QEMU 的生产 loader 在 dispatch 前验证。危险样本一经错误接受即停止并计为安全失败，不继续执行非法 payload。

**输出**：loader decision、拒绝阶段/原因、parse cycles、package bytes、peak RAM。

**结论锁**：关键 mismatch 错误执行为 0、diagnostic macro-F1>=0.95 才支持 H4；执行后崩溃才发现不算 pre-execution detection。

### 子测试 S4：证据不增信与失效传播

**目的**：检验 transform、hash 变化和证据组合不会凭空提高可信度。

**素材**：shape/layout/precision/memory/ABI/toolchain/artifact 七类 transform 各 300；segment-pass/boundary-fail、physical-pass/numeric-fail、fallback 缺证据等组合反例各 100。

**执行**：先绑定完整 evidence vector；仅执行普通 transform，不调用 verifier；计算预期失效矩阵；尝试 candidate->deployable；比较系统与独立 obligation oracle。

**输出**：before/after evidence、invalidated coordinates、promotion decision。

**结论锁**：任何受影响坐标仍为 pass 并参与部署，即 H5 失败。高层 physical pass 不能覆盖 numeric/timing/resource。

### 子测试 S5：RVV 数值与真实性能

**目的**：把“生成了 RVV 指令”“输出数值正确”“板上更快”分成三个可独立证伪的主张。

**素材**：第 5.2 节全部支持模型/shape，每配置 100 输入；reference runtime；CPU AOT、default RVV、CECAP RVV；真实 RVV 板和校准仪器。

**执行**：先 reference 输出；CPU/RVV differential；objdump 确认目标 kernel 的 RVV path；真实板随机交错测量；量化模型额外计算 exact match、top-1 agreement 和任务 accuracy 差。

**结论锁**：任一超冻结容差输出使该 domain 数值失败；speedup 95% CI 完全高于 1 才写“更快”。无真实板只报告 QEMU execution path，不产生性能结论。

### 子测试 S6：NPU ABI blocker 与候选升证

**目的**：验证“识别到 NPU”与“拥有可部署 NPU 计划”之间的证据边界。

**素材**：无 ABI、冲突 ABI 各 300 mutation；权威 ABI 分支需 command spec、版本 hash、生产 driver/provider、QEMU/厂商模拟路径证据和真实设备；至少 10 个支持子图。模拟平台不能替代物理正分支。

**执行**：负分支检查 blob emission=0 和 blocker/fallback；正分支逐项验证 encoding、buffer/DMA、barrier、driver acceptance、reference diff、物理执行。

**结论锁**：无权威材料时正分支为 `IMPLEMENTATION-NOT-READY`，不是失败也不是支持。负分支任一 deployable NPU blob 是安全失败。

### 子测试 S7：fallback 与环境变化

**目的**：验证主后端失效时不会发生隐式证据降级。

**素材**：NPU busy/offline、RVV unavailable、arena 缩小、deadline policy 提高、evidence 过期、target/toolchain hash 变化各 300 场景。

**执行**：比较 fastest-only、共享主计划证据 fallback、CECAP 独立证据 fallback；记录选择顺序、拒绝原因、switch cycles 和完成状态。

**结论锁**：错误 fallback=0 才支持 H6；安全拒绝允许降低 completion。绕过最低 policy 以完成任务是失败。

### 子测试 S8：端到端模型与平台覆盖

**目的**：检验方法是否超出 Add+ReLU，并展示可解释接受/拒绝边界。

**素材**：完整模型、负例、CPU-only、RVV、NPU-unknown 和可用时 NPU-known 合同。

**执行**：对每个 model/shape 输出 accepted/rejected、mapping、conversion、peak arena、evidence completion、latency 或 NA；所有失败保留。

**结论锁**：unsupported、dynamic、quant mismatch 和超 arena 必须拒绝；支持模型完成率单列，不能替代关键安全零容忍。

## 7. 素材、指标与结论映射

| 核心实验 | 主素材 | 主端点 | 支持出口 | 否决条件 |
|---|---|---|---|---|
| Core-1 合同与完整计划合法性 | contract/domain mutations | IPAR、unsafe pre-dispatch acceptance | 关键非法和域外计划零执行 | 任一关键非法接受或 dispatch 后才发现 |
| Core-2 搜索正确性与质量 | 200 小图 + 大图/30 seeds | exact 集合相等、K=8 recall/HV | exact 完整且 beam 达预注册质量 | exact 集合差异；beam 失败单独撤回 |
| Core-3 证据与 fallback 安全 | transform/NPU/failure scenarios | false evidence/NPU emission/unsafe fallback | 零错误升证和零错误 fallback | 任一 stale/false pass 或无 ABI blob |
| Core-4 多模型执行与真实性能 | 100 inputs/config + board runs | numeric error、negative acceptance、speedup CI | 分域正确且性能由实测支持 | 超容差、负例错误接受或 CI 不支持 |

## 8. 四类结论出口

1. `SUPPORTED-WITHIN-MODEL`：实现与素材完成，达到主阈值，只对冻结 model/shape/target/toolchain/domain 有效。
2. `NOT-SUPPORTED`：实验有效但阈值失败，例如 beam 质量不足或板上无可靠加速。
3. `SAFE-ENDPOINT-FAILED`：非法计划、域外 dispatch、错误升证或 unsafe fallback 非零；性能不能抵消。
4. `IMPLEMENTATION-NOT-READY`：必要代码对象（如 exact search）缺失；corpus/测量未冻结标 `EXPERIMENT-NOT-READY`，单板或权威 NPU ABI 未具备标 `BLOCKED-HIL`，不得借用 smoke 结果。

预取的合理结论方向是：合同/证据机制可能提高拒绝正确性但带来 package 和 parse 开销；exact 应与穷举一致，beam 质量随 K 改变；RVV 是否加速必须由板测决定；NPU 在当前无权威 ABI 条件下应保持 blocked。以上均为待验证预期。

## 9. 实施顺序与完成判据

| 阶段 | 实现 | 完成判据 |
|---|---|---|
| A | plan/package v2、canonical hash、loader | 正/负 schema cases 全部判定一致 |
| B | candidate/deployable 与 evidence invalidation | transform 不调用 verifier 时无升证 |
| C | 200 小图生成器和独立 oracle | 可重复产生相同集合/hash |
| D | exact/beam 多目标搜索 | exact smoke 与 oracle 相同；beam trace 可审计 |
| E | 模型/输入/reference corpus | 所有文件 hash、许可证和容差冻结 |
| F | RVV 板测管线与 measured cost DB | seed cost 无法进入正式分析 |
| G | fallback/环境模拟 | 六类故障可重放且理由稳定 |
| H | 可选 NPU 正分支 | 权威 ABI/provider/设备齐全；否则 blocked |

## 10. readiness checklist

- [x] `soc-image.cecap-plan.v2`、evidence/policy v2 和 AEG/package v2 代码对象已存在并通过仓库 selftest
- [ ] 上述 schema、协议版本和兼容策略已正式冻结
- [x] loader/runtime 在 dispatch 前验证 binding、domain、evidence、provider 和 fallback resource/evidence 一致性
- [ ] cost DB 区分 seed/QEMU/measured，正式分析拒绝非 measured 性能
- [ ] 200 小图及独立穷举 oracle 已冻结
- [ ] lower-bound 10,000 property cases 可重放
- [ ] 模型、权重、输入、reference 输出、容差和许可证已锁定
- [ ] 八类合同 mutation 各 300，组合集另列
- [ ] exact 与 beam 代码路径和结论措辞明确分离
- [ ] CanMV-K230 PCB revision、频率、温度、固件/image hash、device/probe serial 和仪器校准已记录
- [ ] NPU 正分支具有权威 ABI；否则只执行 blocker 负分支
- [ ] 所有 baseline 预算、flags、线程、频率和输入一致
- [ ] 结果脚本按模型/图为统计单位，不把重复测量虚增为样本

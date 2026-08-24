# ADAM 实验实施蓝图：从材料、实现到可判定结论

## 0. 文档定位

- 对应论文：[理论设计](./theoretical_design.md)
- 预注册规则：[实验协议](./experiment_protocol.md)
- 状态：`PRE-RESULT / UNVERIFIED`
- 用途：把论文主张转换为可实现模块、冻结素材、执行步骤和逐项结论判据。
- 纪律：本文的“预期”均指机制成立时应出现的方向，不是已获得结果；正式结果只能从冻结后的原始 artifact 计算。

## 1. 实现设计目的与问题边界

ADAM 的实现目的不是让 Agent 生成更多代码，而是回答一个更严格的问题：当 SoC 材料不完整、互相冲突或只提供候选线索时，系统能否保证这些信息只触发调查，不会直接获得修改集成树、选择软件栈、生成镜像或操作设备的工程效力；当候选确实通过与其声明匹配的证据义务后，系统又能否以可恢复、可审计的方式晋升。

论文要验证四个因果环节：

1. `材料字节 -> Hardware IR/SafeFact`：事实状态和来源是否保真。
2. `SafeFact -> capability/task graph`：只有安全 basis 才能授权生产 capability。
3. `candidate -> verifier -> integration -> promotion`：候选生成权与工程验收权是否隔离。
4. `claim -> obligation -> evidence -> decision`：每个晋升决定是否能回溯到适用域一致的证据。

不在本文保证范围内：自然语言材料解析器绝对正确、两个共享工具链 verifier 的统计独立、任意未来 SoC 的通用性、形式验证意义上的程序正确性、无权威 ABI 时的 NPU 执行。

## 2. 当前实现基线与正式实验缺口

| 能力 | 当前代码基础 | 可直接用于 | 正式实验前缺口 |
|---|---|---|---|
| Hardware IR 与安全 basis | `socimage/hardware.py` 的 unresolved、conflict、command ABI blocker、enabled/blocked capability | Core-1 smoke、材料追踪 | 冻结 mutation generator；统一 fact ID 与 claim ID |
| 任务规划 | `engine/control.py` 的 capability DAG 与 input hash | Core-1/Core-4 基线 | `material_selectors` 当前可由 observation 文本加入 root，必须改为 `investigation_only` |
| 候选隔离 | `engine/control.py` 的独立 worktree、owned-path、symlink 检查 | Core-2 path 基线 | 补 rename/submodule/binary patch oracle 和污染审计 |
| 两阶段验证与晋升 | candidate verifier、integration verifier、promotion commit | Core-2 smoke | 显式记录两个 verifier 的 failure domain；增加 promotion decision record |
| 状态恢复 | SQLite task/attempt/artifact/failure、recover、obsolete | Core-4 基线 | 增加 claim/evidence/obligation 表和证据失效传播 |
| 来源闭包 | `engine/source_discovery_tools.py` 的 license、architecture、anchor、OS/media ABI、adapter | Core-1 基线 | 冻结传递依赖图、合法栈正例和独立 closure oracle |
| 风险激活 | 理论模型已有 | 无正式能力 | 实现 obligation-driven scheduler，并保留静态全角色基线 |

若上述“正式实验前缺口”未完成，对应实验只能标为 `IMPLEMENTATION-NOT-READY`，不能把 selftest 通过写成论文主张得到支持。

## 3. 最小实现架构与数据流

```text
materials + material.lock
  -> parser/normalizer
  -> facts(state, value, source, locator, hash)
  -> capability gate(required_facts, risk_policy)
  -> investigation tasks | production task DAG
  -> isolated candidate generation
  -> candidate verification
  -> integration apply + integration verification
  -> claim/obligation/evidence closure check
  -> promotion commit | blocked | failed | obsolete
  -> immutable run artifacts
```

### 3.1 必需持久对象

在现有 SQLite 状态库中至少增加以下逻辑表；字段可以合并到现有 schema，但语义不可省略。

```text
claims(claim_id, subject_hash, predicate, expected, domain_hash, severity, status)
evidence(evidence_id, verifier_id, artifact_hash, input_hash, domain_hash,
         outcome, created_at, failure_domain_id)
claim_evidence(claim_id, evidence_id, relation, valid)
obligations(obligation_id, claim_id, verifier_class, required_domain,
            required_outcome, status)
failure_domains(failure_domain_id, implementation_hash, toolchain_hash,
                oracle_hash, shared_dependencies)
promotion_decisions(decision_id, task_id, candidate_hash, integration_hash,
                    obligation_set_hash, outcome, reason, commit_hash)
```

### 3.2 capability registry 最小扩展

每个 production capability 必须携带：

```json
{
  "id": "source_stack_image",
  "required_facts": ["cpu.isa", "boot.rom_contract"],
  "required_obligations": ["source_closure", "license", "abi", "integration"],
  "risk_class": "high",
  "unknown_policy": "investigation_only",
  "conflict_policy": "blocked"
}
```

`material_selectors` 只能生成调查任务，其输出需要重新进入材料解析与 `SafeFact` gate；不得直接把 production capability 加入 roots。

### 3.3 晋升状态机

```text
planned -> running -> candidate
candidate -> candidate_failed | integration_pending
integration_pending -> integration_failed | evidence_pending
evidence_pending -> blocked | promoted
任何状态 --input/artifact/domain hash 变化--> obsolete
任何执行中状态 --中断--> interrupted，恢复后不得自动视为 passed
```

晋升伪代码：

```text
facts = resolve_required_facts(capability)
if any fact is unknown/candidate: return investigation_only
if any fact is conflict: return blocked("unsafe fact basis")
candidate = run_in_isolated_worktree(task)
if changed(candidate) outside owned_paths: return failed("path escape")
if not candidate_verifier(candidate): return failed("candidate verifier")
integration = apply_to_current_integration(candidate.patch)
if not integration_verifier(integration): rollback; return failed("integration verifier")
obligations = obligations_for(claims(candidate), risk_policy)
if not all evidence_matches_hash_and_domain(obligations): rollback; return blocked("evidence debt")
return atomic_promote(integration, decision_record)
```

## 4. 实验素材总 manifest

### 4.1 目录与冻结文件

```text
benchmarks/adam_codesignbench/v1/
  manifest.json
  tasks.jsonl
  materials/<task_id>/...
  material_locks/<task_id>.json
  oracles/<task_id>.json
  mutations/<class>/<case_id>.json
  legal_stacks.jsonl
  source_graphs/<stack_id>.json
  fault_schedule.jsonl
  seeds.txt
  exclusions.jsonl
  baseline_lock.json
  environment.lock
```

`manifest.json` 记录文件 SHA-256、生成器 commit、生成时间、协议版本和父素材来源。首次正式运行后只允许新增带原因的 deviation，不得原位改写。

### 4.2 160 个基础任务的组成

| 责任域 | 真实单事件重建 | 真实跨层事件重建 | 真实事件表示变体 | 合计 | 最低 oracle |
|---|---:|---:|---:|---:|---|
| Boot | 10 | 5 | 5 | 20 | build + image layout + boot log |
| BSP | 10 | 5 | 5 | 20 | schema + compile + symbol/ABI |
| Driver | 10 | 5 | 5 | 20 | register/compatible + build + negative probe |
| Source | 10 | 5 | 5 | 20 | license + revision + closure + ABI |
| Compiler | 10 | 5 | 5 | 20 | build + numeric + target binding |
| Runtime | 10 | 5 | 5 | 20 | unit/state trace + integration |
| Image | 10 | 5 | 5 | 20 | component hash + layout + readback where available |
| HIL | 10 | 5 | 5 | 20 | device binding + run attribution + expected terminal state |

全部 160 项都必须锚定仓库 commit、失败签名、review 记录或真实集成事件，并保存 `origin_commit`、原始 artifact hash 和最小复现补丁；跨层任务至少重放两个真实责任域事件；表示变体只能对同一真实事件改变命名、排序或等价表示，不能凭空生成需求，也不能改变 oracle 答案。

两名不参与候选生成的标注者分别填写 `required_capabilities`、`allowed_paths`、`forbidden_effects`、`required_obligations` 和 `expected_terminal_state`。分歧由第三人裁决，报告原始一致率和裁决记录。

### 4.3 每类 300 个负例的生成方法

| 类别 | 因子与配额 | 标签 | 独立 oracle | 排除条件 |
|---|---|---|---|---|
| fact_state | unknown/candidate/conflict 各 75；同名异值、版本漂移、locator 错配各 25 | allowed capability set | 只读取冻结 fact policy 的规则解释器 | mutation 未改变目标字段 |
| path_escape | absolute、`..`、symlink、rename、submodule、binary patch 各 50 | forbidden changed paths | Git tree diff + inode/link 审计 | 攻击未被实际注入 |
| oracle_blind_spot | schema、link、symbol、dependency、identifier、integration context 各 50 | candidate pass/integration fail | hidden integration tests | candidate 本身不能构建 |
| source_closure | license、OS ABI、media ABI、submodule、manifest、revision drift 各 50 | legal/illegal closure | 独立图遍历与 policy evaluator | closure 图不连通且与任务无关 |
| state_recovery | kill、timeout、artifact tamper、input change、stable blocker、budget exhaustion 各 50 | expected state transition | 状态机参考模型 | 故障未发生在指定边界 |
| device_binding | wrong device、old log、readback mismatch、run-ID mix、image hash、serial missing 各 50 | allow/block | 独立绑定检查器 | 无设备的场景错误标成物理正例 |

每个 case 的 `mutation.json` 包含 `base_id`、`seed`、`changed_bytes`、`expected_label`、`severity`、`oracle_version`。同一基础样例衍生的多个变体在统计中按 family 聚类，不能假装完全独立。

### 4.4 合法栈、故障和物理素材

- 合法软件栈不少于 60 个，每个 target/RTOS/media ABI 组合不少于 10 个；保存 repo URL、commit、submodule、manifest、许可证 SPDX、toolchain 和构建哈希。
- Core-4 的恢复子测试每类故障至少 300 次，`fault_schedule.jsonl` 预先指定 task、DAG 边界、注入时间、期望状态和恢复后允许复用的 artifact。
- 物理记录统一使用一块 CanMV-K230-LP4 V3.0，必须包含 PCB revision、device serial、probe serial、image hash、readback hash、run ID、固件 hash、串口起止 sequence 和 UTC 时间。缺任一项时结果自动归类为 `BLOCKED-HIL`。

## 5. 四个核心实验与实施卡

| 核心实验 | 内部实施卡 | 唯一主端点 |
|---|---|---|
| Core-1 事实、来源与任务图安全 | S1 事实/冲突/任务图；S4 来源闭包 | unsafe activation 与 invalid closure acceptance |
| Core-2 候选与晋升安全 | S2 路径/证据/两阶段晋升 | false promotion 与污染半径 |
| Core-3 风险协作有效性 | S3 多 Agent 对照 | evidence 非劣后 calls 优效 |
| Core-4 恢复与跨平台边界 | S5 恢复；S6 平台/HIL | 状态不变量与错误物理效力 |

以下实施卡是四个核心实验内部的子测试，不单独扩张论文实验数量。

### 子测试 S1：事实状态、冲突传播与任务图

**设计目的**：隔离验证“危险事实是否被授权”这一根因，不让后续 build 成败掩盖 gate 错误。

**素材**：160 个基础任务的材料；fact_state 六个子类各 300 例；QEMU、RVV、K230 三类合同；对应的冻结 allowed-capability oracle。

**执行**：对原始和 mutation 材料分别派生 IR；保存逐字段状态、来源定位和 hash；生成 capability graph；比较 enabled/blocked/investigation-only；再改变一个材料字节确认锁和所有依赖输入 hash 失效。

**主输出**：`facts.jsonl`、`profile.json`、`plan.json`、`oracle_diff.json`、`hash_propagation.json`。

**判定**：逐子类 `UAR=0` 且 provenance locator 完整；安全正例的 FBR 和 graph macro-F1 单独报告。任何 observation 文本绕过 SafeFact 直接启用 production capability 即为 H1 安全失败。

**可形成结论**：只有零危险激活时，才能写“在冻结 mutation 域内实现了事实授权隔离”；否则写“当前 gate 存在具体反例”，不能用总体准确率稀释。

### 子测试 S2：路径隔离、证据对齐与晋升

**设计目的**：证明候选测试通过不等于可晋升，并测出两个 verifier 的共同盲区。

**素材**：六类 path_escape 各 300 例；六类 oracle_blind_spot 各 300 例；160 个合法/非法候选；冻结 claim-obligation oracle。

**执行**：在独立 worktree 注入候选；运行 candidate verifier；施加 integration context mutation；执行 apply-check、integration verifier 和 obligation closure；记录候选与集成 verifier 的 implementation/toolchain/oracle hash。

**主输出**：`patch.diff`、`tree_before/after`、两个 verifier JSON、`claims.jsonl`、`evidence.jsonl`、`promotion_decision.json`。

**判定**：关键/高严重度 FPR、path escape 和污染半径均为 0；claim-evidence recall=1；共同漏检 `F_joint` 单列。只要共同漏检非零，就不得把双 verifier 描述为满足 soundness 前提。

**可形成结论**：结果支持的是“工程效力隔离实现”，不是“生成代码一定正确”。

### 子测试 S3：风险激活与协作有效性

**设计目的**：检验 obligation-driven 激活是否真正减少无效协作，而不是通过少做验证换取成本下降。

**素材**：从 160 个真实任务分层抽取 96 个，每域 12 个；单事件/跨层事件/真实事件表示变体、难度和风险均衡；5 个 Agent seed；固定模型和预算；20 个不进入正式数据的 pilot。

**执行**：Latin-square 平衡任务顺序；运行 B0、B1、B2、B3、B6、M；cache 策略一致；运行期间隐藏 oracle；保存每次激活原因、未覆盖 obligation、calls、tokens、wall time 和人工介入。

**判定**：先验证 evidence completion 相对 B2 非劣，下界不低于 -3pp；再验证 calls 中位数至少下降 20%；任一新增 FPR 直接否定 H3。

**可形成结论**：同时通过两阶段门控才能称“更有效率”；仅 calls 少只能说明执行更少。

### 子测试 S4：来源锚点、ABI 与传递闭包

**设计目的**：验证软件来源选择是全栈约束求解，而不是逐组件最高分拼接。

**素材**：source_closure 六类各 300 负例；60 个合法栈；每栈的完整依赖图、SPDX、OS/media ABI、adapter 和可重建 hash。

**执行**：比较逐组件最高分、顶层 commit 锁、provenance-only 和完整 ADAM；独立 oracle 遍历传递依赖并检查 policy；在干净容器重建两次。

**判定**：禁用许可证、未锁依赖和 ABI mismatch 错误接受均为 0；合法栈 false rejection 与构建成功率单列；两次重建 hash 不同必须解释非确定来源。

**可形成结论**：安全端点通过支持“错误闭包拒绝”；可构建率只支持可用性，不能抵消非法闭包。

### 子测试 S5：失败、阻塞、过期与恢复

**设计目的**：验证恢复语义保持过去的有效工作，同时不会复用已失效工件。

**素材**：六类故障各 300 次；每个 DAG wave 边界至少 30 次；故障前后 state.db 快照；稳定 blocker 与临时 failure 的标注集。

**执行**：按冻结计划 kill、timeout、断网、移除设备、篡改 artifact、改变 input hash；调用 resume；逐条对照参考状态机；检查预算和重复工作。

**判定**：interrupted->passed、blocked 被当 failed、hash 变化后旧 passed 未 obsolete、篡改 artifact 被复用、超预算重试，任一出现即正确恢复主张失败。效率使用重复 CPU 时间和任务数中位数衡量。

**可形成结论**：不变量为零且重复工作下降达阈值，才分别支持“正确恢复”和“减少重做”；两者不得合并。

### 子测试 S6：端到端平台差异与物理边界

**设计目的**：验证系统会因硬件证据差异产生不同任务闭包，并把“正确阻塞”视为可接受终态。

**素材**：同一请求在 CPU/QEMU、RVV、NPU-ABI-unknown、NPU-ABI-known（仅权威 ABI 可用时）和真实 K230 绑定设备上的合同；每平台至少 20 个覆盖八域的请求。

**执行**：比较 task graph、blocker、source lock、CECAP handoff、HIL gate；物理分支执行写前绑定、flash、readback、run attribution；未知 ABI 分支确认不产生 NPU 可部署 blob。

**判定**：graph-oracle macro-F1>=0.95，安全 blocker 无漏报/误报；无设备时必须 blocked；任何缺 serial/hash/run-ID 的物理结果不纳入通过样本。

**可形成结论**：只能声称“对所测合同有区分能力”；未知材料的正确拒绝不是任务失败。

## 6. 素材到指标再到论文结论的锁定映射

| 核心实验 | 唯一主素材 | 主指标 | 支持结论 | 一票否决 |
|---|---|---|---|---|
| Core-1 事实、来源与任务图安全 | fact/closure mutations + legal stacks | UAR、invalid closure acceptance | 测试域内事实授权与来源闭包有效 | 任一危险激活或关键非法闭包 |
| Core-2 候选与晋升安全 | path/blind-spot cases | FPR、污染半径、evidence recall | 错误候选未晋升 | 路径逃逸或关键 false promotion |
| Core-3 风险协作有效性 | 96 tasks x 5 seeds | evidence 非劣 + calls 优效 | 同等证据下成本更低 | 新增 FPR 或非劣失败 |
| Core-4 恢复与跨平台边界 | fault schedule + platform contracts | invariant violation、rework、blocker error | 正确恢复并区分平台边界 | 状态不变量或错误物理效力 |

## 7. 四类结论出口

每个实验只能进入以下一个出口：

1. `SUPPORTED-WITHIN-MODEL`：实现完成、素材冻结、主端点达到阈值，结论必须附合同、平台和 oracle 边界。
2. `NOT-SUPPORTED`：实现已完成且实验有效，但主端点未达阈值；完整保留反例，不得改写为趋势。
3. `SAFE-ENDPOINT-FAILED`：出现关键错误激活、false promotion、非法闭包或状态不变量违反；立即停止相关危险物理分支，失败仍计入主结果。
4. `IMPLEMENTATION-NOT-READY`：claim/evidence schema 或 risk activation 等必要代码缺失；独立 oracle/corpus 未冻结标 `EXPERIMENT-NOT-READY`，CanMV-K230 未绑定标 `BLOCKED-HIL`；只能报告对应 readiness，不能评价假设。

论文总主张只有在 H1/H2 对应安全出口均为第一类时成立。H3 效率、H5 重做成本或 H6 通用性失败，必须分别撤回，不能由其他实验代偿。

## 8. 实施顺序与完成判据

| 阶段 | 工作 | 输入 | 完成判据 |
|---|---|---|---|
| A | 修正授权入口并增加持久 schema | 当前代码 | selector 只能 investigation；schema migration/selftest 通过 |
| B | 构建独立 oracle 与素材生成器 | 任务/变体规范 | 双标注完成；manifest hash 冻结；抽查可重放 |
| C | 完成 candidate/integration/evidence 决策记录 | A | 每次晋升可重建完整 CER 链 |
| D | 实现 risk activation 与静态基线 | obligation graph | 同一任务可切换 B6/M，预算一致 |
| E | 运行 host/QEMU smoke | A-D | 每类至少 5 个公开样例端到端生成 artifact |
| F | 冻结协议并运行隐藏正式集 | E | 无临时改代码；原始失败完整保存 |
| G | 有条件运行物理分支 | 设备与 ABI | serial/readback/run-ID 全绑定，否则 blocked |

## 9. 执行前 readiness checklist

- [ ] `material_selectors` 不再直接授权 production capability
- [ ] claims、evidence、obligations、failure_domains 和 promotion decision 可持久重建
- [ ] candidate 与 integration verifier 的共享依赖已标注
- [ ] 160 个任务完成双标注与隐藏 oracle
- [ ] 每类 300 个 mutation 已去重、冻结且可重放
- [ ] 60 个合法栈及传递依赖图可在干净容器重建
- [ ] 六类故障计划能命中指定状态边界
- [ ] baseline adapter、模型服务版本、容器和工具链已锁定
- [ ] 危险消融与真实设备物理隔离
- [ ] 结果分析脚本只读取不可变 artifact，不读取手工结论栏
- [ ] 协议 hash、manifest hash、代码 commit 和环境 digest 已登记

只有全部非物理项完成，Core-1 至 Core-4 的 host 子测试才能进入正式运行；CanMV-K230 未绑定或物理项未完成时 Core-4 的 HIL 子测试保持 `BLOCKED-HIL`，不能产生 HIL 结论。

---
experiment_id: AIRTOS-FORMAL-260804-005
system: AIRTOS
type: confirmatory-non-hil
date_utc: 2026-08-04
status: SUPPORTED-WITHIN-SOFTWARE-AND-QEMU-MODELS
final_runs: [final_run1, final_run2]
physical_hardware_status: BLOCKED-HIL
mock_results: false
---

# AIRTOS 四个核心实验非 HIL 正式报告

## Material Passport

- Evidence root: `results/airtos/airtos-exp-v5-20260804-complete-nonhil`
- Runs: `final_run1`, `final_run2`
- AEG SHA-256: `e823492eb9abe21d150a26355c28b1ca9242ec923cca9bc04d7ca4a08d3ef106`
- Corpus SHA-256: `c818ff4428b417d870e8d7b62b5696ee25e94deb4c2be8158441129bbc450906`
- Verification status: `VERIFIED` for the stated software/QEMU model; `BLOCKED-HIL` for physical claims

## 1. 总结论与边界

`final_run1` 和 `final_run2` 均从独立空目录由失败即停 runner 完整执行并写入 `RUN_PASS`；两轮递归 `SHA256SUMS` 校验通过。实验直接链接当前生产 loader、admission、allocator、coherency、scheduler、recovery 和 trace 源码，不使用 mock、stub 或抽样替代正式 corpus。

非实体板分支现已闭合：联合准入、材料现场重哈希、verifier trust-root 轮换、`SimEDF+`、WCET 时间隔离、并发 lease、coherency 命令状态机、epoch-cookie、预算恢复、fallback gate、trace 分类与 ring-wrap 噪声稳健性均完成两轮复验。相同 49,085,520 B corpus 在 x86_64、RV64、Cortex-M3/M4/M7 上给出一致决策。

本报告不支持实体开发板上的 hard deadline、物理 DMA/cache 数据一致性、IRQ/reset 时界、板级开销/功耗、真实工作负载标签外部效度或 24 h 且 `10^6` jobs HIL。这些结论仍为 `BLOCKED-HIL`。

## 2. 平台与正式负载

| 平台 | 架构/系统 | 每轮正式负载 | 结果 |
|---|---|---:|---|
| Host | x86_64 Linux 6.8.0-136 | 四实验全部软件子测试 | PASS/PASS |
| QEMU user | RV64GC, QEMU 8.2.2 | loader/admission/schedule/recovery/coherency | PASS/PASS |
| QEMU `virt` | RV64 + OpenSBI + RT-Thread Nano 5.3.0 | 7,950 loader + 24,548 schedule + 1,000,000 coherency | PASS/PASS |
| QEMU `lm3s6965evb` | Cortex-M3 | 7,950 + 24,548 + 1,000,000 | PASS/PASS |
| QEMU `mps2-an385` | Cortex-M3 | 7,950 + 24,548 + 1,000,000 | PASS/PASS |
| QEMU `mps2-an386` | Cortex-M4 | 7,950 + 24,548 + 1,000,000 | PASS/PASS |
| QEMU `mps2-an500` | Cortex-M7 | 7,950 + 24,548 + 1,000,000 | PASS/PASS |
| CanMV-K230-LP4 V3.0 | 实体 RV64/RVV/KPU | 物理分支 | `BLOCKED-HIL / NOT RUN` |

四个 Cortex-M machine 与 `virt` 是 QEMU 系统模型，不是五块实体开发板。它们验证跨 ISA、字长、ABI、启动环境和 RTOS 集成下的同源实现符合性，不验证物理外设或时界。

## 3. Core-1：package、证据材料与原子联合准入

**目的。** 验证畸形/错绑 package、失效 evidence、错误 provider/memory/deadline 条件在 dispatch 前被拒绝，trust-root 能安全轮换，并发失败不会留下半提交。

**输入与结果。** 每轮每个 corpus 平台运行 300 个合法 package、15 类单因子各 300、105 类 pairwise 各 30，共 7,950 case，全部零 mismatch。Host/RV64 联合诊断各含 23,400 case，macro-F1=1.0；provider-health race 各 300 case，failure 与 rollback leak 均为 0。

产品 trust 生成前对 evidence artifact/verifier 做现场存在性、SHA-256 与 evidence-root 路径约束检查。每轮运行 valid、artifact digest mismatch、artifact missing、artifact path escape、verifier digest mismatch、verifier missing 六类各 300，共 1,800 case，failure=0。随后在 Host 与 RV64 各执行 1,500 次 old-only、dual-root grace、new-only rejection、重新签署 acceptance 与 stale-root rejection，failure=0。

Host 并发提交每轮为 2/4/8/16 线程各 100,000 transaction。run1 接纳 16,047，run2 接纳 23,649；overlap 与 partial commit 均为 0。零失败并不证明所有攻击组合，但 1,800 个材料 case 的单轮一侧 95% exact 失败率上界为 0.166292%，1,500 个轮换判定对应 0.199516%。

**结论。** 支持冻结材料/变异/并发域内的 evidence material fail-closed、信任根轮换、联合拒绝与事务回滚；不外推到实体 ISR/生产 driver 竞争。

## 4. Core-2：异构 DAG 调度、WCET 边界与开销

**目的。** 验证一般 DAG、running residual、reservation/dbf 和非抢占多资源 EDF，并明确条件 deadline 定理的有效侧与失效侧。

**数据与结果。** 每轮包含 10,000 small、5,000 stress、2,048 bounded Cartesian、30 seed x 250 multiseed，共 24,548 场景。Host/RV64 C simulator 与独立 Python oracle 的 status/finish 逐例一致，RT-Thread/RV64 和四个 Cortex-M system machine 对相同 corpus 也全部零 mismatch。

在 10,000 small 场景中，无准入有 5,822 false accept，candidate-only 有 3,932，FIFO 为 27 false accept/355 false reject，fixed-priority 为 29/380，完整 `SimEDF+` 为 0/0。4,178 个 WCET 下接纳场景在 `actual/WCET=0.5/0.8/1.0` 时 deadline miss 均为 0；越界 `1.05/1.2` 分别出现 446/1,145 次 miss。

Host S8 每项 10 次预热、30 批 x 1,000 次。下表为“批 median 的中位数 / 批 p99 的中位数”，单位 ns，未扣除 14/15 ns clock baseline。

| 操作 | run1 | run2 |
|---|---:|---:|
| load | 89 / 91 | 90 / 91 |
| SimEDF+ | 70 / 72 | 70 / 71 |
| queue push+pop | 19 / 20 | 19 / 20 |
| lease+release | 25 / 26 | 25 / 26 |
| trace | 23 / 25 | 23 / 30 |
| completion ISR path | 54 / 56 | 54 / 56 |

基准 ELF 为 text 30,855 B、data 992 B、bss 16 B。绝对时间只描述当前 Host 软件路径，不支持目标板低开销或 WCET 主张。

## 5. Core-3：lease 隔离与 coherency 命令状态机

**目的。** 验证并发 session lease 不重叠、不越权，coherency command 对 range、cache-line、clean/invalidate/barrier、hook failure 和 ownership transition 执行 fail-closed 检查。

**数据与结果。** 每轮 2/4/8/16 线程各 250,000 allocator attempt，共 1,000,000；run1 成功 lease 878,058，run2 为 908,918。所有 overlap、canary corruption、cross-session differential、generation-race failure 与 rollback leak 均为 0。

生产 `coherency.c` 与 `plan_select.c` 在 Host、RV64 user、RV64/RT-Thread 和四个 Cortex-M machine 上，每环境每轮执行 1,000,000 case，并进行 1,171,675 个预期拒绝检查；所有环境 `failures=0`。覆盖动作顺序、范围/cache-line 对齐、缺失/失败/legacy hook、越界和 ownership transition。单环境单轮 1,000,000 case 零失败的一侧 95% exact 上界为 0.000300%。

**结论。** 支持软件/QEMU 域内的 lease 隔离和 coherency 命令语义符合性。由于 QEMU 不提供本项目目标 SoC 的真实非一致 cache、DMA descriptor、共享 cache line 与总线竞争，该结果不能支持条件数据一致性定理的物理前提；物理 reference differential 仍为 `BLOCKED-HIL`。

## 6. Core-4：stale、恢复、fallback 与 trace 稳健性

**目的。** 验证旧完成事件不污染新状态，恢复尝试有界闭合，fallback 不绕过重新准入，trace 在噪声和 ring wrap 下仍能归因且不自证。

**数据与结果。** 每轮每平台注入 wrong-device、wrong-epoch、wrong-cookie、cancel-late、reset-late、same-epoch-old-cookie、duplicate 各 100,000，共 700,000，状态污染为 0。五类恢复各 300 episode；`K_r={1,2,3,5}` x 四类故障 x 300，共 4,800 episode；四类 fallback gate 各 300，全部 failure/bypass=0。Host/RV64 cookie wrap 均观察到 `(epoch=1,cookie=UINT32_MAX)->(epoch=2,cookie=1)`。

原 8 类 x 100 冻结 trace corpus 在 Host/RV64 上均为 macro-F1=1.0、top-3 recall=1.0、status-only macro-F1=0.416667、gate bypass=0。新增稳健性实验为 8 类 x 300，共 2,400 case/平台/run；每例注入 65-128 个干扰事件并强制 ring wrap，wrapped=2,400、macro-F1=1.0、accuracy=1.0、failure=0。2,400 case 零失败的一侧 95% exact 上界为 0.124744%。

**结论。** 支持软件状态机内的事件归属、预算闭合、fallback 重验和冻结标签域的 trace 稳健性；不支持生产 driver 的物理 cancel/reset/IRQ 时界或真实 workload 标签外部效度。

## 7. 论文主张判定

可写：在冻结软件/QEMU 模型和两轮独立执行中，未观察到 unsafe admission、evidence material bypass、stale trust acceptance、oracle mismatch、model-valid deadline miss、lease/data corruption、coherency command violation、stale-state mutation、恢复预算违例、fallback gate bypass 或 trace ring-wrap 分类错误；完整 corpus 在 x86_64、RV64、Cortex-M3/M4/M7 上得到一致决策。

不可写：QEMU machine 等同实体开发板；已证明 CanMV-K230 hard real-time、物理 DMA/cache 一致性、IRQ/reset bound、板级功耗/开销、真实 workload 外部效度或 24 h 稳定性。非 HIL 验证已经完整，Paper 3 的物理论证仍需实体板实验。

## 8. 文章作用与片上系统问题解释

### 8.1 文章在项目中的作用

这篇文章研究的不是怎样把人工智能模型编译出来，而是模型编译完成以后，怎样让执行计划安全、可控、按时地进入片上系统运行。它位于编译计划和真实硬件之间，承担运行治理作用。

传统做法通常是“模型编译完成后直接调用推理函数”。本文把这一过程改为：先检查软件包、输入适用范围、证明材料、计算设备、内存和截止时间；只有全部条件满足，才同时提交任务与内存。执行期间继续管理数据同步、超时、取消、设备复位、迟到完成信号和备用方案。运行记录只用于提出下一轮优化实验，不能直接把新方案宣布为可信。

因此，本文把人工智能执行计划从“一个可以调用的函数”提升为“操作系统中能够被接纳、拒绝、调度、隔离、恢复和追踪的一等对象”。它回答的核心问题不是“模型能不能运行”，而是“模型是否有资格在当前芯片、当前输入和当前系统状态下运行，并且不会破坏已经作出的资源与时间承诺”。

### 8.2 解决的片上系统问题与实验证据

| 片上系统实际问题 | 传统方法为什么不足 | 本文的解决方法 | 本轮直接实验数据 | 数据说明 |
|---|---|---|---|---|
| 编译正确不等于当前可以运行 | 文件结构正确仍可能存在输入不适用、证明失效、设备故障、内存不足或截止时间不可满足 | 把软件包绑定、输入范围、证明材料、设备健康、内存、调度和恢复条件合并成统一准入条件 | 每轮7,950个软件包、23,400个联合诊断，错误接纳和错误诊断均为0 | 不合格计划能够在任何执行副作用前被拒绝，拒绝原因可追踪 |
| 证明材料可能被替换、删除或引用目录外文件 | 只相信清单中登记的数字摘要，无法发现材料文件已经变化 | 生成可信运行包前检查文件存在、限制材料目录并现场重算数字摘要 | 六类材料情况各300，共1,800个用例，失败为0 | 材料被修改、缺失或路径越界时能够停止生成可信运行包 |
| 验证程序需要升级但不能留下信任空窗 | 永久写死一个验证程序不便升级，直接替换又可能错误接受旧结果 | 支持旧验证程序、新旧并存过渡、新验证程序以及过期结果拒绝 | 主机和六十四位精简指令集环境各1,500个轮换判定，失败为0 | 信任关系能够按明确阶段升级，旧结果不会在切换完成后继续生效 |
| 多种计算资源共同执行一个人工智能任务 | 只调度提交线程，看不到中央处理器、向量单元、神经网络加速器和数据搬运设备之间的任务依赖 | 把推理拆成有依赖关系的任务段，为每种资源建立独立的最早截止时间队列，并在准入前仿真全部任务 | 每轮24,548个场景与独立参考程序逐例一致，不同处理器环境均为0处不一致 | 多资源任务依赖、非抢占阻塞、正在运行任务和未来预留任务已进入同一个调度判断 |
| 新任务自己能按时完成，但可能使旧任务超时 | 只检查候选任务会忽略它对已接纳任务的阻塞 | 新任务加入前重新计算新旧全部任务的完成时间 | 不做准入有5,822次错误接纳，只检查候选任务有3,932次，完整方法为0 | 联合完成时间检查是保护既有截止时间承诺的必要机制 |
| 平均运行时间不能支撑严格截止时间 | 神经网络加速器和数据搬运通常不能随时抢占，执行超界会长期占用资源 | 每个任务段绑定保守的最坏情况执行时间，并按该时间控制逻辑完成与后继释放 | 4,178个接纳场景中，实际时间不超过上界时违例为0；超过百分之五和百分之二十时分别出现446和1,145次违例 | 截止时间结论只在实际执行不超过登记上界时成立，执行上界是必要前提而不是性能参考 |
| 多个模型共享有限片内存，容易产生重叠、污染和失败残留 | 永久独占浪费内存，简单顺序分配又不能保护并发任务 | 为每个活动任务分配有生命周期和版本的内存租约，并让内存与调度同时提交或同时回滚 | 每轮1,000,000次并发分配尝试；内存重叠、边界损坏、跨任务污染、版本竞争错误和回滚泄漏均为0 | 在当前并发测试域内，不同任务的活动内存保持隔离，失败准入不留下半提交资源 |
| 处理器与计算设备可能看到不同版本的数据 | 处理器写入可能仍停留在高速缓存，设备写回后处理器也可能继续读取旧副本 | 由执行计划明确声明数据写回、高速缓存失效、内存屏障、操作范围和所有权转换 | 七个软件和虚拟处理器环境每环境每轮1,000,000个用例，并含1,171,675个预期拒绝检查，失败为0 | 数据一致性命令、范围和顺序的执行语义正确；真实物理数据一致性仍需开发板验证 |
| 设备复位后，旧任务的迟到中断可能误完成新任务 | 只检查设备编号或任务指针，无法区分复位前后的执行世界 | 每次设备复位增加设备代次，每次派发分配执行序号；完成信号必须同时匹配设备、代次、序号和活动任务 | 每平台每轮七类迟到或重复事件共700,000次，状态污染为0 | 复位前旧事件不能修改复位后的新任务状态，也不能错误释放新任务资源 |
| 故障设备可能无限取消、复位和重新初始化 | 没有最大尝试次数会永久占用任务、设备、内存和调度资源 | 为取消、复位和重新初始化设置等待上限和最大尝试次数，超过预算后隔离设备 | 五类基础恢复共1,500个过程；四种最大次数与四类故障共4,800个过程，预算违例为0 | 软件状态机能够在有限尝试后进入健康或隔离状态，不会无限恢复 |
| 主设备失败后直接切换备用方案可能破坏原有安全承诺 | 备用方案可能证明失效、设备不健康、内存无效或使其他任务超时 | 备用方案执行前重新检查证明材料、设备、活动内存和全部任务截止时间 | 四类备用方案关口各300，共1,200个过程，绕过次数为0 | 备用方案不是绕过准入的后门，而是必须重新接纳的新执行计划 |
| 总耗时日志无法区分排队、搬运、计算、内存和复位问题 | 只有总时间和最终错误码，难以定位根因，也容易让在线优化形成自我证明 | 记录计划、任务段、资源、设备代次、执行序号、事件和状态，并要求新方案重新经过验证与准入 | 800个基础场景的完整记录分类全部正确；2,400个带65至128个干扰事件并强制缓冲区覆盖的场景仍全部正确 | 可归属运行记录能够在冻结标签域中稳定识别问题，同时没有绕过新方案验证 |

### 8.3 数据揭示的总体工程意义

第一，这些数据说明片上系统上的人工智能运行问题不能被缩减为“调用一个推理函数”或“增加一个最早截止时间队列”。真正的问题是计划资格、异构设备、内存、时间、数据和故障状态彼此耦合，任何一项单独检查都可能留下错误接纳或半提交。

第二，这些数据说明实时性是有条件的。系统能够保护截止时间的前提是实际执行时间不超过登记的最坏情况执行时间、未来到达已经预留、非抢占阻塞和恢复开销已经计入。执行时间一旦超界，截止时间违例明显增加，因此论文不能把有限实验写成无条件实时保证。

第三，这些数据把空间隔离、时间隔离和故障隔离区分开来。内存租约防止不同任务访问重叠区域；保守调度防止新任务破坏旧任务的截止时间；设备代次和执行序号防止旧完成信号污染新状态。三类隔离共同组成片上系统运行安全边界，不能用其中一种替代另外两种。

第四，跨普通电脑、六十四位精简指令集处理器和三类嵌入式处理器的相同结果，说明实现没有表现出明显的数据宽度、对齐、编译方式或启动环境依赖。它支持软件规则的跨架构可复现性，但不等于这些虚拟环境就是实体开发板。

### 8.4 本段允许形成的论文结论

根据现有数据，可以写：在冻结的软件和虚拟处理器模型、指定输入范围以及两轮独立复验中，系统实现了证据边界联合准入、多资源任务调度、内存与时间原子提交、数据一致性命令治理、旧完成事件隔离、预算恢复、备用方案重新准入和可归属运行反馈；没有观察到错误接纳、参考程序不一致、模型有效范围内的截止时间违例、跨任务内存污染、旧事件污染、恢复预算违例或关口绕过。

不能写：已经证明真实开发板上的严格截止时间、物理高速缓存和直接存储器访问一致性、真实中断与复位时间上界、板级功耗、真实任务标签分类能力或长期稳定性。实体开发板实验仍需验证这些软件规则依赖的物理前提是否成立。

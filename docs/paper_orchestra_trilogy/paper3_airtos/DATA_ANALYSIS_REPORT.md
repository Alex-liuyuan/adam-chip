# AIRTOS 实验数据目录分析报告

分析日期：2026-08-06  
数据目录：`/root/myproject/adam/chip/docs/paper_orchestra_trilogy/paper3_airtos`

## 1. 执行摘要

清理前该目录共 1,438,743,487 B，包含 2,256 个文件和 519 个目录。历史过程轮次
移入回收站后，当前为 347,182,354 B、539 个文件和 103 个目录。原约 1.4 GB
空间主要由 v2、v4、v5 的重复语料、构建树和历史尝试占用，不等于独立实验样本量。

论文结论应以两组规范证据为准：

- 非 HIL：`results/airtos-exp-v5-20260804-complete-nonhil/`，两次干净运行均 PASS。
- K230 HIL：`results/airtos-exp-v6-20260805-k230-hil/`，短实验和 24 分钟连续运行完成。
- 冻结汇总：`manuscript/inputs/experimental_log.md`，与 v5/v6 原始证据及最终稿一致。

目录数据支持有限测试域内的准入、调度实现一致性、事务原子性、内存租约、
K230 DMA 数据一致性、旧事件隔离、恢复预算和 trace 分类。最重要的负结果是：
CPU 与 RVV 的观测最大时延都超过注册 WCET，因此当前板卡配置不支持硬实时保证。
v7-v10 虽增加了真实摄像头/KPU 和较长运行证据，但完整 24 小时三负载联合实验仍未完成。

## 2. 数据选择与统计口径

| 层级 | 采用的数据 | 用途 |
|---|---|---|
| 论文规范非 HIL | v5 `final_run1`、`final_run2` | 软件、QEMU、跨架构一致性和四个核心实验 |
| 论文规范 HIL | v6 原始日志、`summary.json` | 单块 K230 的物理 DMA、时序和 24 分钟运行 |
| 失败与后续开发 | v7-v10 | 失败分析、预检和未完成长测；不回填为论文规范结果 |
| 历史与修复轨迹 | v1-v4 | 说明装置演进、缺陷修复和最终协议形成过程 |

统计时遵循以下规则：

1. v5 两轮复验用于确认可重复性，不把相同冻结语料合并成独立随机样本。
2. Host、QEMU user 和各 QEMU system machine 是不同执行环境，不是多块实体板。
3. 不同端点的分母不相加计算统一“成功率”；覆盖图总数只表示非重叠操作量。
4. “0 失败”只表示给定有限测试域内未观察到反例，不表示总体失败概率为 0。
5. v6 的 6,685,424 次是 DMA lifecycle iteration，不是 NPU inference job。

## 3. v1-v10 实验谱系

| 版本 | 角色与范围 | 最终状态 | 是否进入论文规范数据 |
|---|---|---|---|
| v1 | Host/RISC-V QEMU pilot；修复调度拒绝分支输出和 fallback 实现门槛 | `UNVERIFIED`，仅 pilot 域支持 | 否 |
| v2 | 正式软件模型；记录并修复并发锁、DBF、cookie wrap、器具初始化等问题 | `SUPPORTED-WITHIN-SOFTWARE-MODEL` | 历史依据，不作为最终冻结版本 |
| v3 | RV64 RT-Thread 与 Cortex-M3/M4/M7 QEMU system portability smoke | `SUPPORTED-WITHIN-QEMU-SYSTEM-MODELS` | 历史依据 |
| v4 | 完整软件/QEMU 协议；保留失败尝试并形成两轮 PASS | `SUPPORTED-WITHIN-SOFTWARE-AND-QEMU-MODELS` | v5 的直接前身 |
| v5 | 两个空目录中的完整非 HIL 复验；补齐材料、信任根、coherency 和 trace 稳健性 | 两轮 PASS，规范非 HIL | 是 |
| v6 | 单块 CanMV-K230-LP4 V3.0；短实验和 24 分钟 HIL | `SHORT_EXPERIMENTS_AND_24MIN_RUN_COMPLETE` | 是 |
| v7 | 24 小时三负载尝试；摄像头管线重复重建耗尽视频池 | 3,108 s 时 FAILED | 否，保留为负结果 |
| v8 | DMA 与四会话计算各 420 s 预检 | 预检 PASS；MicroPython transport 阻塞混合测试 | 否 |
| v9 | 启动 DMA/计算 24 小时任务，缺混合负载且未取得完整终态 | 部分启动记录 | 否 |
| v10 | 新镜像上 DMA/计算运行超过 200 min；另做 420 s 混合预检 | 部分长测 + 混合预检 PASS；完整 24 h 未完成 | 否 |

v7 的失败不是数据搬运或四会话计算错误。混合脚本每 3,600 帧销毁并重建摄像头，
视频缓冲池未完全回收，最终出现 `too many pools` 和 `vicap init failed(-1)`。
后续把摄像头管线重建限制为一次，仍保留一次真实生命周期恢复验证。

## 4. 规范非 HIL 数据：v5

### 4.1 平台和语料

同一 49,085,520 B 冻结语料在两轮中重复执行。两轮的 Host/RV64 决策 CSV
逐字节一致，status 与 finish-time 比较均无 mismatch。

| 环境 | 每轮主要负载 | 两轮结果 |
|---|---|---|
| x86_64 Linux Host | 完整四核心软件套件 | PASS / PASS |
| RV64GC QEMU user | loader、admission、schedule、recovery、trace、coherency | PASS / PASS |
| RV64 QEMU `virt` + OpenSBI + RT-Thread Nano 5.3.0 | 7,950 loader + 24,548 schedule + 1,000,000 coherency | PASS / PASS |
| `lm3s6965evb` Cortex-M3 | 同上 | PASS / PASS |
| `mps2-an385` Cortex-M3 | 同上 | PASS / PASS |
| `mps2-an386` Cortex-M4 | 同上 | PASS / PASS |
| `mps2-an500` Cortex-M7 | 同上 | PASS / PASS |

每环境、每轮的 coherency replay 还包含 1,171,675 个预期拒绝检查，均通过。
Cortex-M 固件约 25.8 KiB、BSS 13,392 B；RT-Thread+AIRTOS image 为 79,272 B。
这些结果不测量物理 DMA/cache、IRQ、reset、能耗或目标板 WCET。

### 4.2 Loader 与调度语料结构

| 数据集 | 数量 | 质量结果 |
|---|---:|---|
| loader manifest | 7,950 | 300 legal；7,650 expected reject |
| small schedule | 10,000 | 全部解析 |
| stress schedule | 5,000 | 全部解析 |
| bounded grid | 2,048 | 全部解析 |
| multiseed stress | 7,500 | 全部解析 |
| schedule 合计 | 24,548 | Host/QEMU status 和 finish 均零 mismatch |

所有规范 JSONL 均可解析；未发现重复 ID、完全重复行、schema 漂移、非法
release/deadline 关系。规范 CSV 未发现缺失值或完全重复行。

### 4.3 两轮非 HIL 复验中的关键并发计数

| 端点 | final_run1 | final_run2 | 安全端点 |
|---|---:|---:|---|
| Admission transactions | 400,000 | 400,000 | overlap 0；partial commit 0 |
| Accepted transactions | 16,047 | 23,649 | 接纳率不是容量估计 |
| Rejected transactions | 383,953 | 376,351 | 均为无半提交的拒绝 |
| Allocator attempts | 1,000,000 | 1,000,000 | overlap/corruption/generation/rollback failure 0 |
| Successful leases | 878,058 | 908,918 | 线程调度差异导致数量不同，不要求确定性相等 |

每轮还在 Host/RV64 上完成材料校验、信任根轮换、provider-health race、stale、
recovery、fallback 和 trace 端点；所有预注册安全计数均为 0。物理板上的对应汇总
另见第 5 节，不能与这两轮合并为一个分母。

### 4.4 调度和 WCET 敏感性

| Admission 策略，10,000 个相同场景 | False accept | False reject |
|---|---:|---:|
| 无 admission check | 5,822 | 0 |
| Candidate-only finish check | 3,932 | 0 |
| FIFO baseline | 27 | 355 |
| Fixed-priority baseline | 29 | 380 |
| 全作业 `SimEDF+` | 0 | 0 |

| Actual/WCET | 已准入场景 | Deadline miss | 派生 miss rate |
|---:|---:|---:|---:|
| 0.50 | 4,178 | 0 | 0% |
| 0.80 | 4,178 | 0 | 0% |
| 1.00 | 4,178 | 0 | 0% |
| 1.05 | 4,178 | 446 | 10.675% |
| 1.20 | 4,178 | 1,145 | 27.405% |

## 5. 规范 K230 HIL 数据：v6

### 5.1 实验条件

| 项目 | 值 |
|---|---|
| 开发板 | 1 块 CanMV-K230-LP4 V3.0 |
| 系统 | RT-Smart |
| 固定算子 | float32 Add+ReLU，输入 `[1,8]` |
| Plan deadline | 100 us |
| RVV 注册 WCET | 4 us |
| CPU fallback 注册 WCET | 10 us |
| DMA 大小 | 64、256、4,096、65,536 B |

### 5.2 板端准入、租约和治理端点

| 端点 | 数量 | 失败或绕过 | 结果 |
|---|---:|---:|---|
| Admission matrix | 3,900 | 0 | 结构、绑定、domain、evidence、provider、memory、coherency、schedule、recovery |
| Diagnostic classification | 23,400 | 0 | Macro-F1 = 1.0 |
| Provider-health race | 300 | 0 | 无 unsafe commit |
| Trust-root rotation | 1,500 | 0 | 无判定失败 |
| Admission transactions | 400,000 | 0 | 112,091 accepted；287,909 rejected；无 overlap/partial commit |
| Allocator attempts | 1,000,000 | 0 | 948,950 successful leases |
| 7 类 stale event | 700,000 | 0 | 无 stale state mutation |
| Recovery episode | 1,500 | 0 | 状态机端点满足 |
| Recovery-budget episode | 4,800 | 0 | quarantine/budget 闭合 |
| Fallback gate | 1,200 | 0 | 无重新准入绕过 |
| Base trace classification | 800 | 0 | Macro-F1 = 1.0；top-3 recall = 1.0 |
| Noise + ring-wrap trace | 2,400 | 0 | Macro-F1 = 1.0 |

### 5.3 板端执行和控制路径时序

CPU 和 RVV 各执行 30 个 batch，每批 1,000 次，共各 30,000 次；数值失败均为 0。
七个控制操作也都是 30 batch x 1,000 次。

| 路径/操作 | 最大 batch p99 | 最大单次时延 | 注册条件 | 判定 |
|---|---:|---:|---:|---|
| RVV Add+ReLU | 1.592 us | 19.778 us | maximum <= 4 us | 失败 |
| CPU Add+ReLU | 1.592 us | 19.926 us | maximum <= 10 us | 失败 |
| Clock read | 1.518 us | 12.111 us | batch p99 < 5 us | 通过 |
| ISR completion | 3.445 us | 39.074 us | batch p99 < 5 us | 通过 |
| Lease release | 1.667 us | 2.629 us | batch p99 < 5 us | 通过 |
| Plan load | 3.741 us | 36.963 us | batch p99 < 5 us | 通过 |
| Queue push/pop | 1.555 us | 37.037 us | batch p99 < 5 us | 通过 |
| `SimEDF+` admission | 2.223 us | 37.037 us | batch p99 < 5 us | 通过 |
| Trace emission | 1.704 us | 35.777 us | batch p99 < 5 us | 通过 |

控制路径 7/7 通过 5 us 标准，但 0/7 通过“低于最短 segment 的 5%”，即 0.2 us，
这一更严格标准。CPU/RVV 的 batch p99 较低不能覆盖 maximum 超界；两条 WCET 合同必须判失败。

### 5.4 物理 DMA 与 cache 负对照

| 传输大小 | 次数 | 平均完整路径时延 |
|---:|---:|---:|
| 64 B | 250,000 | 29.949 us |
| 256 B | 250,000 | 34.490 us |
| 4,096 B | 250,000 | 86.502 us |
| 65,536 B | 250,000 | 713.355 us |

1,000,000 次完整 DMA 路径均逐字节一致。省略 source clean 与 destination invalidate
的负对照各 400 次，800/800 次遗漏均被检出，未检出数为 0。

### 5.5 设备生命周期和连续 HIL

| 端点 | 数量 | 结果 |
|---|---:|---|
| Device reopen/reinitialize | 300 | failure 0；p99 53.148 us；max 69.222 us |
| 连续 HIL | 1,440 s | 6,685,424 DMA lifecycle iterations |
| HIL failure counters | 3 类 | data/device/lifecycle 均为 0 |
| Heartbeat | 66 | elapsed 和 iterations 单调递增 |
| 温度 | 起始/最终/最高 | 49.103 / 52.406 / 52.706 deg C |
| 终态 token | 1 | `AIRTOS_K230_LONG_PASS` |

Reopen/reinitialize 是 device-library lifecycle 操作，不是硬复位。24 分钟运行也不是
24 小时稳定性实验。

## 6. 后续真实板实验：v7-v10

| 版本 | 时长/规模 | 结果 | 可用结论 |
|---|---|---|---|
| v7 | mixed elapsed 3,108 s | lifecycle failure 1，整轮 FAILED | 反复 camera pipeline recreation 会耗尽视频池 |
| v8 DMA preflight | 420 s；1,097,424 jobs | 三类 failure 0 | 短时 DMA 预检通过 |
| v8 compute preflight | 420 s；70,500 batches；282,000 jobs | 五类 failure 0；max batch 233.733 ms | 300 ms 预算下短时预检通过 |
| v9 | 两个 24 h 任务启动 | 缺可读取终态，混合负载未启动 | 仅启动/存活证据 |
| v10 DMA/compute | >200 min；32,000,000 DMA；2,000,000 batches/8,000,000 jobs | error 0；max batch 237.517 ms < 300 ms | 中间检查点，开发板随后为 mixed preflight 重启 |
| v10 mixed preflight | 420 s | 12,365 frames/object、1,237 face、1 camera restart、14 KPU restarts；三类 error 0 | 摄像头加双模型短时协同通过 |

v10 混合预检最大单帧 60 ms，另记录 1 次外部 IDE 中断，不计为摄像头或模型错误。
原始 recovered log 含 85 个 NUL 字节，去除 NUL 后记录可解析。`status.env` 仍标
`RUNNING_PARTIAL_HARDWARE_24H`，但开发板已为 mixed preflight 重启，且没有对应长测进程，
因此该状态是过期状态，不能当作仍在运行或已经完成的依据。

## 7. 数据完整性与可复现性审计

### 7.1 通过项

- v5 规范 JSONL 全部可解析，未见重复 ID、重复行、schema 漂移或非法时间关系。
- v5 Host/QEMU 对应决策 CSV 字节一致，status/finish mismatch 均为 0。
- v5/v6 规范 CSV 的数据行无缺失值、无重复 batch key。
- v6 `summary.json` SHA-256 为
  `1a4ba42374048e5c2a9595ab14182672b621b4ea3e812ddcccc5321bb447656c`。
- v6 24 分钟原始日志 SHA-256 为
  `e7c701c360893fec2a9270151ed20e6f033fa707366dfc4ff765cf8a3180e302`。
- v6 `SHA256SUMS.short` 的 83 项在路径前缀重映射后全部验证通过。

### 7.2 归档缺陷

1. v5 顶层和每轮 `SHA256SUMS` 使用归档前的 `results/airtos/...` 路径，直接
   `sha256sum -c` 不可移植。路径重映射后，保留文件均匹配，但每轮还引用一个已不存在的
   `core2/rtthread_virt/staging/rtthread/__pycache__/rtconfig.cpython-312.pyc`。
   这是生成态字节码，不影响实验数值，但说明 checksum manifest 没有完全清理。
2. v6 `SHA256SUMS.short` 同样保存归档前路径；内容可验证，直接检查会因路径失败。
3. v6 三个名为 `.csv` 的板端文件含一行 shell 命令前导和尾部 PASS/prompt 行，
   不是严格的纯 CSV。数据行完整，但复用时应只读取 header 到最后一个数据行。
4. v10 recovered log 含 NUL 字节；应保留原文件及散列，解析时显式去 NUL，不能静默覆盖原件。
5. v9/v10 状态文件是检查点记录，不是事务性终态；应以原始日志、终态 token 和进程事实交叉判断。

## 8. 可支持与不可支持的结论

### 可支持

- 冻结有限域内，AIRTOS 的联合准入、材料校验、事务回滚、`SimEDF+` 实现、lease、
  coherency 命令状态机、stale-event gate、恢复预算和 trace 分类未观察到定义内安全失败。
- 同一软件语料在 x86_64、RV64 和 Cortex-M3/M4/M7 QEMU 环境得到一致决策。
- 单块 K230、给定 RT-Smart 和四种 DMA 大小下，1,000,000 次完整物理传输无字节差异，
  两类 cache 操作遗漏负对照均被检出。
- 单块板上 24 分钟、6,685,424 次 DMA lifecycle iteration 未记录 data、device 或
  lifecycle counterexample。
- v10 的摄像头、目标检测、人脸检测及有限次数生命周期重建在 420 秒预检中协同通过。

### 不可支持

- 当前 CPU/RVV 配置的硬实时或无条件 deadline 保证。
- 通用 NPU/KPU 性能、任意 AI 模型或异构工作负载性能。
- 真实迟到 IRQ 行为、芯片硬复位时延或生产驱动故障分布。
- 功耗、能效、跨板差异或跨芯片泛化。
- 24 小时稳定性、长期失效率或完整三负载联合长测通过。

## 9. 最终判断

论文的证据链已经形成“v5 软件/QEMU 规范复验 + v6 单板短时物理验证”的闭环，
但它是一组条件化、有限域的工程证据，不是无条件可靠性证明。目录中最应保留在摘要和结论里的
负结果是 CPU/RVV WCET 失败；最需要防止误用的是把 v7-v10 的失败、预检或部分长测写成
完整 24 小时通过。后续若要升级主张，最低要求是重新完成带终态审计的 24 小时三负载联合实验，
并对 CPU/RVV WCET 重新标定后生成新证据。

# Paper 3 AIRTOS 文件组织说明

本文档只覆盖 AIRTOS 论文目录：

`/root/myproject/adam/chip/docs/paper_orchestra_trilogy/paper3_airtos`

## 一、当前有效入口

| 文件 | 用途 |
|---|---|
| `theoretical_design.md` | 论文题目、核心思想、行业难点、创新点、数学理论和贡献边界 |
| `experiment_protocol.md` | 四个核心实验设计、实验平台、实验数据、指标和结论规则 |
| `implementation_blueprint.md` | 实验如何对应到项目代码和板端脚本 |
| `DATA_ANALYSIS_REPORT.md` | 已完成实验数据的解释和论文可用结论 |
| `EXPERIMENT_RESULTS_INDEX.md` | 当前最重要的实验结果总索引 |
| `DATA_RETENTION_MANIFEST.md` | 数据保留、清理和不可使用数据说明 |

## 二、目录职责

| 目录 | 内容 | 维护规则 |
|---|---|---|
| `figures/` | 论文机制图和图注 | 只放可解释理论机制的图 |
| `inputs/` | 早期输入和写作素材 | 不作为最终实验结论来源 |
| `manuscript/` | 论文正文、模板、草稿、最终稿 | 最终论文看 `manuscript/final/` |
| `manuscript/inputs/` | 冻结写作输入和实验日志 | 论文正文引用数据优先看这里 |
| `results/` | 所有实验结果包 | 原始日志、环境、摘要和校验文件必须保留 |

## 三、实验结果目录

| 目录 | 定位 | 论文使用方式 |
|---|---|---|
| `results/airtos-exp-v5-20260804-complete-nonhil/` | 软件、QEMU 和跨架构复验 | 可支撑软件模型、跨架构一致性和形式化用例结论 |
| `results/airtos-exp-v6-20260805-k230-hil/` | K230 实体板短时硬件在环实验 | 可支撑真实板端准入、数据搬运和生命周期结论 |
| `results/airtos-exp-v7-20260805-k230-24h/` | 24 小时实验失败轮次 | 只能作为失败分析和边界说明 |
| `results/airtos-exp-v8-20260805-k230-24h/` | 24 小时前预检轮次 | 只能作为预检证据 |
| `results/airtos-exp-v10-20260806-k230-new-image/` | 新镜像板端实验 | 可作为 200 分钟硬件中间证据和 420 秒混合负载预检证据 |

## 四、当前不能写成论文结论的内容

- 不能写“24 小时实验已经通过”。当前没有完整 24 小时三负载联合通过结果。
- 不能把 420 秒摄像头加双模型混合预检写成长时间稳定性结论。
- 不能把外部开发环境中断写成摄像头或模型内部错误。
- 不能写功耗结论；当前没有功率计数据。
- 不能写绝对可靠，只能写“在当前测试窗口内未观察到反例”。

## 五、与工程代码的对应关系

| 工程文件 | 对应实验 |
|---|---|
| `experiments/airtos/formal_suite.py` | 软件形式化用例和调度语料 |
| `experiments/airtos/run_qemu_system_matrix.sh` | QEMU 多架构系统实验 |
| `experiments/airtos/k230_hil_transport.py` | K230 串口/板端交互和实验调度 |
| `experiments/airtos/k230_compute_long_hil.c` | K230 长时间计算负载 |
| `experiments/airtos/k230_mixed_24h.py` | 摄像头加双模型混合负载实验 |
| `experiments/airtos/run_k230_full_24h.sh` | 24 小时联合实验启动脚本 |
| `experiments/airtos/summarize_k230_full_24h.py` | 24 小时联合实验结果汇总 |

## 六、后续整理规则

新增 AIRTOS 实验时，按以下格式建立目录：

`results/airtos-exp-v<编号>-<日期>-<实验名>/`

每个正式实验目录至少包含：

- `README.md`：本轮实验说明。
- `status.env` 或 `summary.json`：机器可读结果。
- `logs/` 或 `raw/`：原始日志。
- `source_sha256.txt` 或 `SHA256SUMS`：代码和工件校验。
- 失败时必须增加 `failure_analysis.md` 或 `ANOMALY_LOG.md`。


# 项目文件组织说明

本文档用于说明 `/root/myproject/adam/chip` 当前文件应该如何阅读、维护和归档。它不替代根目录 `README.md`；根目录 `README.md` 说明工程入口，本文档说明文件分区。

## 一、工程主目录

| 目录 | 内容 | 整理原则 |
|---|---|---|
| `boot/` | 启动链、引导相关材料 | 保留工程代码，不放论文实验结果 |
| `bsp/` | 板级支持包 | 只放板级适配，不放论文草稿 |
| `compiler/` | 编译、模型打包、后端适配 | 论文二 CECAP 可引用这里的能力，但实验结果仍放 `docs/` |
| `engine/` | 镜像生成、产品模板、运行时模板 | 作为工程实现主体维护 |
| `experiments/` | 可执行实验程序和脚本 | 只放实验代码，不放最终论文结论 |
| `products/` | 具体产品配置和板端应用 | 只放可烧录/可运行产品材料 |
| `tools/` | 通用工具脚本 | 能复用的工程工具放这里 |
| `third_party/` | 第三方源码、工具链和外部依赖 | 不手工混入论文文件；按 manifest/lock 管理 |
| `docs/` | 论文、实验报告、行业分析、图表和数据索引 | 所有论文材料统一归档入口 |

## 二、论文材料主目录

三篇论文材料统一放在：

`/root/myproject/adam/chip/docs/paper_orchestra_trilogy/`

| 子目录 | 论文 | 当前定位 |
|---|---|---|
| `paper1_adam/` | 论文一 ADAM | 硬件材料驱动的软件栈协同生成 |
| `paper2_cecap/` | 论文二 CECAP | 面向边缘异构人工智能的带证据加速计划 |
| `paper3_airtos/` | 论文三 AIRTOS | 面向边缘异构人工智能的准入、资源治理和恢复机制 |

共享文献与理论放在 `paper_orchestra_trilogy/` 根部：

- `project_specific_reanalysis.md`：三篇论文按项目特点重新拆分后的总分析。
- `theoretical_framework.md`：三篇论文共享的理论框架。
- `literature_review.md`：文献综述。
- `references.bib`：统一文献库。

## 三、每篇论文内部约定

每篇论文目录建议保持同一结构：

| 文件或目录 | 用途 |
|---|---|
| `theoretical_design.md` | 题目、核心思想、行业难点、创新点、数学理论和贡献边界 |
| `experiment_protocol.md` | 四个核心实验的目的、平台、数据、指标和结论规则 |
| `implementation_blueprint.md` | 如何从项目代码落地实验 |
| `initial_research_plan.md` | 早期方案，只作追溯，不覆盖当前设计 |
| `figures/` | 论文概念图、机制图和图注 |
| `inputs/` | 写作输入、素材和中间说明 |
| `results/` | 实验结果包、原始日志、环境记录和校验信息 |
| `manuscript/` | 论文正文、模板、最终稿和写作过程 |

## 四、AIRTOS 实验结果归档规则

AIRTOS 的所有实验结果必须放在：

`/root/myproject/adam/chip/docs/paper_orchestra_trilogy/paper3_airtos/results/`

不要再把 Paper 3 实验结果散放到项目根部 `results/`、`output/` 或工程代码目录。

Paper 3 当前总索引为：

`/root/myproject/adam/chip/docs/paper_orchestra_trilogy/paper3_airtos/EXPERIMENT_RESULTS_INDEX.md`

该索引是判断哪些数据可用于论文结论的第一入口。

## 五、哪些文件不能随意移动或删除

以下文件属于实验可追溯性材料，即使失败也要保留：

- 原始板端日志。
- 主机控制日志。
- `status.env`、`environment.env`、`summary.json`。
- `SHA256SUMS` 或 `source_sha256.txt`。
- 失败分析和异常记录。

失败实验不是垃圾文件。它用于证明实验边界、修复过程和最终结论没有被选择性报告。

## 六、当前清理边界

本次整理只建立索引和归档规则，不执行以下操作：

- 不移动原始实验目录。
- 不删除失败日志。
- 不恢复或提交工作树中已有的无关删除。
- 不把仓库外的未跟踪文档纳入本项目。
- 不把 420 秒预检写成 24 小时通过。
- 不把没有功率计的数据写成功耗结论。


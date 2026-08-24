# 三篇论文材料索引

本目录的论文材料以 `paper_orchestra_trilogy/` 为唯一主目录，分别对应 ADAM、CECAP 和 AIRTOS。三篇论文共享理论与文献，但研究问题、实验结论和证据边界彼此独立。

## 建议阅读顺序

0. [项目文件组织说明](PROJECT_FILE_ORGANIZATION.md)：先确认工程代码、论文材料和实验结果分别放在哪里。
1. [项目特征重分析](paper_orchestra_trilogy/project_specific_reanalysis.md)：三篇论文为何拆分、各自题目和贡献边界。
2. [统一理论框架](paper_orchestra_trilogy/theoretical_framework.md)：共同术语、证据语义和论文间接口。
3. 对应论文目录中的 `theoretical_design.md`、`experiment_protocol.md`、`implementation_blueprint.md`。
4. [文献综述](paper_orchestra_trilogy/literature_review.md)与 [BibTeX 文献库](paper_orchestra_trilogy/references.bib)。
5. 已完成实验的 `results/`；`initial_research_plan.md` 仅作为早期研究记录，不覆盖当前设计和实验协议。

## 论文一：ADAM

**题目：** *ADAM: Evidence-Governed Agentic Co-Design for Hardware-Derived SoC Software Stacks*

**当前状态：** `PRE-RESULT / UNVERIFIED`，尚无正式结果包。

| 材料 | 用途 |
|---|---|
| [理论设计](paper_orchestra_trilogy/paper1_adam/theoretical_design.md) | 当前题目、创新、数学模型、声明边界 |
| [预注册实验协议](paper_orchestra_trilogy/paper1_adam/experiment_protocol.md) | 样本、基线、指标、阈值和结论规则 |
| [实施蓝图](paper_orchestra_trilogy/paper1_adam/implementation_blueprint.md) | 代码对象、素材生产和执行步骤 |
| [早期研究方案](paper_orchestra_trilogy/paper1_adam/initial_research_plan.md) | 早期“多 Agent SoC 软件生态构建”方案，仅供追溯 |
| [图表目录](paper_orchestra_trilogy/paper1_adam/figures/) | 3 张概念图及 `captions.json` |

## 论文二：CECAP

**题目：** *CECAP: Contract- and Evidence-Carrying Acceleration Plans for Hardware-Bounded Heterogeneous Edge AI*

**当前状态：** `PRE-RESULT / UNVERIFIED`，尚无正式结果包。

| 材料 | 用途 |
|---|---|
| [理论设计](paper_orchestra_trilogy/paper2_cecap/theoretical_design.md) | 当前题目、计划对象、搜索理论和声明边界 |
| [预注册实验协议](paper_orchestra_trilogy/paper2_cecap/experiment_protocol.md) | corpus、基线、oracle、板测和统计规则 |
| [实施蓝图](paper_orchestra_trilogy/paper2_cecap/implementation_blueprint.md) | schema、编译流水线和实验执行步骤 |
| [早期研究方案](paper_orchestra_trilogy/paper2_cecap/initial_research_plan.md) | 早期“TVM 原生 AI 编译器”方案，仅供追溯 |
| [图表目录](paper_orchestra_trilogy/paper2_cecap/figures/) | 3 张概念图及 `captions.json` |

## 论文三：AIRTOS

**题目：** *AIRTOS: Evidence-Bounded Admission, Resource Governance, and Recovery for Heterogeneous Edge AI*

**当前状态：** `PARTIAL-RESULT / SHORT-HIL-SUPPORTED`；24 小时长测、真实驱动迟到中断、硬复位和功耗仍未完成。

| 材料 | 用途 |
|---|---|
| [理论设计](paper_orchestra_trilogy/paper3_airtos/theoretical_design.md) | 当前题目、准入/治理/恢复模型和声明边界 |
| [预注册实验协议](paper_orchestra_trilogy/paper3_airtos/experiment_protocol.md) | 软件、QEMU、实体板实验与最新状态 |
| [实施蓝图](paper_orchestra_trilogy/paper3_airtos/implementation_blueprint.md) | 接口、实验装置、HIL 和结果判定 |
| [文件组织说明](paper_orchestra_trilogy/paper3_airtos/FILE_ORGANIZATION.md) | Paper 3 文档、实验结果和工程代码对应关系 |
| [早期研究方案](paper_orchestra_trilogy/paper3_airtos/initial_research_plan.md) | 早期“RT-Thread 原生 AI OS”方案，仅供追溯 |
| [图表目录](paper_orchestra_trilogy/paper3_airtos/figures/) | 3 张概念图及 `captions.json` |
| [v1 Host/QEMU 试验](paper_orchestra_trilogy/paper3_airtos/results/airtos-exp-v1-20260804-hostqemu/) | 首轮试验、失败端点、修复过程和生产运行快照 |
| [v2 正式软件模型结果](paper_orchestra_trilogy/paper3_airtos/results/airtos-exp-v2-20260804-formal-software/) | 软件模型确认实验、五轮复验和异常记录 |
| [v3 QEMU 系统结果](paper_orchestra_trilogy/paper3_airtos/results/airtos-exp-v3-20260804-qemu-system/) | RV64 RT-Thread 与 Cortex-M3/M4/M7 跨系统模型验证 |
| [v4 完整软件/QEMU 结果](paper_orchestra_trilogy/paper3_airtos/results/airtos-exp-v4-20260804-complete-software/) | 全量 corpus、两轮正式结果和校验和 |
| [v5 非 HIL 结果](paper_orchestra_trilogy/paper3_airtos/results/airtos-exp-v5-20260804-complete-nonhil/) | 软件/QEMU 模型的冻结报告、异常、复现表和校验和 |
| [v6 K230 HIL 结果](paper_orchestra_trilogy/paper3_airtos/results/airtos-exp-v6-20260805-k230-hil/) | 最新实体板短时实验、摘要、环境和工件校验信息 |

## 共享与板级材料

| 材料 | 主要用途 |
|---|---|
| [CanMV 兼容参考产品计划](canmv_compatible_reference_product_plan.md) | ADAM 工程对象与三篇论文的共同产品背景 |
| [K230 官方镜像严格对比](k230_official_image_strict_comparison.md) | 镜像验收边界和板级基线 |
| [K230-LP4 V3.0 原理图](product/SCH_CanMV-K230-LP4-V3.0_20240509_2024-07-15(1).pdf) | 硬件事实来源 |
| [K230-LP4 V3.0 引脚图](product/k230%20%203.0%E5%BC%95%E8%84%9A%E5%9B%BE.jpg) | 板级连接与 HIL 参考 |

## 目录约定

- `theoretical_design.md`、`experiment_protocol.md` 和 `implementation_blueprint.md` 是每篇论文的当前主材料。
- `initial_research_plan.md` 是早期方案，出现冲突时以上述三份当前主材料为准。
- `figures/` 保存可直接用于论文的图和图注；`inputs/` 是后续 PaperOrchestra 输入预留目录。
- `results/<run-id>/` 必须保留报告、异常记录、复现信息、环境和校验和，不把运行结果混入理论文档。
- AIRTOS 的 v1-v6 完整实验历史均在 `paper3_airtos/results/`；本工作区原路径 `results/airtos/` 仅保留兼容入口。
- 三篇论文共同引用根目录的 `references.bib`，不维护三份重复文献库。

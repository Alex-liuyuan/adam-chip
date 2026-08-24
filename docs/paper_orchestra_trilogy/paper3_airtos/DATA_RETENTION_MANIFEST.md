# AIRTOS 实验数据保留与清理记录

清理日期：2026-08-06

## 保留

| 内容 | 原因 |
|---|---|
| `DATA_ANALYSIS_REPORT.md` | 最终完整数据整理、质量审计和结论边界 |
| `manuscript/inputs/experimental_log.md` | 论文冻结数值的权威汇总 |
| `results/airtos-exp-v5-20260804-complete-nonhil/` | 论文规范非 HIL 原始证据及两轮复验 |
| `results/airtos-exp-v6-20260805-k230-hil/` | 论文规范 K230 原始日志、summary 和校验清单 |
| v7 的失败摘要、分析、状态和日志 | 摄像头视频池耗尽的必要负结果 |
| v8 的预检状态及 DMA/compute 日志 | 420 秒预检的原始证据 |
| v10 的状态、checkpoint 和 mixed 日志 | 超过 200 分钟检查点与 420 秒 mixed 预检证据 |
| 稿件、图、协议和设计文档 | 论文及实验解释材料，不属于可删除实验过程轮次 |

## 删除

| 内容 | 删除原因 | 原占用约值 |
|---|---|---:|
| `results/airtos-exp-v1-20260804-hostqemu/` | pilot 与修复过程，已被 v5 完整取代 | 14 MB |
| `results/airtos-exp-v2-20260804-formal-software/` | 软件模型尝试与修复历史，已被 v5 取代 | 383 MB |
| `results/airtos-exp-v3-20260804-qemu-system/` | QEMU smoke 过程，最终矩阵已在 v5 保留 | 5.7 MB |
| `results/airtos-exp-v4-20260804-complete-software/` | v5 的前序失败/修复轮次 | 644 MB |
| `results/airtos-exp-v9-20260806-k230-hardware/` | 只有启动/存活记录，无可用终态，v10 已取代 | 428 KB |
| v7/v8 的 `k230_compute_long_hil` 可执行副本 | 可重建过程产物，不是实验数据 | 约 609 KB |
| v8 的空 preclean/autorun/未完成 mixed 日志 | 无有效实验终态 | 约 3 KB |

工作目录释放约 1.05 GB。上述内容已移动到系统回收站，没有执行永久删除；在回收站
清空前仍可恢复。

## 未删除的已知冗余

v5 两轮各保留一份 49,085,520 B 冻结 corpus 和相应构建证据，v6 也保留板端
corpus。它们占用较多空间，但属于最终结果的可审计输入，不能按普通过程数据处理。

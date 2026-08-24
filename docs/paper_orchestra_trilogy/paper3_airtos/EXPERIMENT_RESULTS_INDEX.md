# Paper 3 AIRTOS 最终实验索引

数据根目录：`/root/myproject/adam/chip/docs/paper_orchestra_trilogy/paper3_airtos`

## 最终文档

- 完整数据分析：`DATA_ANALYSIS_REPORT.md`
- 冻结论文实验日志：`manuscript/inputs/experimental_log.md`
- 数据保留与清理记录：`DATA_RETENTION_MANIFEST.md`
- 最终论文：`manuscript/final/paper.pdf`

## 论文规范实验

| 目录 | 定位 | 最终状态 |
|---|---|---|
| `results/airtos-exp-v5-20260804-complete-nonhil/` | 软件、QEMU 和跨架构复验 | 两轮完整 PASS |
| `results/airtos-exp-v6-20260805-k230-hil/` | 单块 K230 物理实验 | 短实验和 24 分钟 HIL 完成 |

论文中所有定量结论以 v5、v6 和冻结实验日志为准。v5 两轮是相同语料的复验，
不能合并成独立统计样本。

## 后续硬件证据

| 目录 | 结果 | 使用边界 |
|---|---|---|
| `results/airtos-exp-v7-20260805-k230-24h/` | 3,108 s 时摄像头 lifecycle failure，整轮 FAILED | 保留失败摘要、分析和原始日志 |
| `results/airtos-exp-v8-20260805-k230-24h/` | DMA/compute 各 420 s 预检通过 | mixed 因 transport 阻塞，未形成完整实验 |
| `results/airtos-exp-v10-20260806-k230-new-image/` | DMA/compute 超过 200 min；mixed 420 s 预检通过 | 开发板随后重启，不是 24 h 通过 |

完整 24 小时三负载联合实验仍未完成。v10 的
`RUNNING_PARTIAL_HARDWARE_24H` 是历史检查点状态，不代表任务仍在运行。

## 关键最终结论

- 7,950 个 loader case 和 24,548 个 schedule scenario 均无 mismatch。
- 400,000 个板端 admission transaction 无 overlap 或 partial commit。
- 1,000,000 次 K230 DMA 传输无字节差异；800/800 次 cache 操作遗漏被检出。
- 24 分钟 HIL 完成 6,685,424 次 DMA lifecycle iteration，三类 failure 均为 0。
- RVV 最大 19.778 us 超过 4 us WCET；CPU 最大 19.926 us 超过 10 us WCET。
  因此当前配置不支持硬实时保证。

## 已清理的过程轮次

v1-v4 已被 v5/v6 完整取代；v9 只有启动记录且没有可用终态。这些目录已按
`DATA_RETENTION_MANIFEST.md` 移至系统回收站，不再作为数据源。

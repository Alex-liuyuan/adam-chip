# AIRTOS CanMV-K230 24 小时实验失败轮次分析

实验编号：AIRTOS-K230-260805-002

状态：FAILED

失败确认时间：2026-08-05T12:48:28Z

原始日志：logs/core4/full_24h_formal.log

原始日志 SHA-256：9001a6b3c5c1988632c4d6436808460f3909d670a22a9ce155e5d38a92326e1d

## 失败现象

- 数据搬运和四会话计算在失败前仍继续推进，正式错误字段为 0。
- 混合摄像头和加速器负载在 elapsed_seconds=3108 时输出：
  - AIRTOS_K230_MIXED_LIFECYCLE_ERROR kind=camera_kpu detail=sensor(0) run error, vicap init failed(-1)
  - AIRTOS_K230_MIXED_RESULT ... lifecycle_failures=1
  - AIRTOS_K230_MIXED_FAIL
- 因出现 AIRTOS_K230_MIXED_FAIL，本轮不能作为 24 小时通过证据。

## 根因判断

混合负载脚本每 3600 帧销毁并重建一次摄像头管线。真实开发板日志显示，每次销毁后仍出现视频缓冲块占用告警：

- someone is using vb now, please make sure to release vb block first

随后视频池编号持续增长。到第 14 个视频池附近，驱动返回：

- too many pools
- kd_mpi_vicap_init Create pool for vicap dev0 chn2 failed

这说明真实硬件的视频缓冲池没有在高频摄像头重建后完全回收。问题不是数据搬运或计算负载错误，而是混合负载中的摄像头生命周期压力设计过强，触发了开发板媒体驱动的视频池数量上限。

## 修复动作

已将混合负载中的摄像头管线重建限制为一次。这样仍保留一次真实摄像头销毁、释放、重建验证，用于支撑论文中的资源恢复路径；同时避免在 24 小时长测中反复创建视频池导致硬件资源耗尽。

KPU 模型会话重建仍按周期执行，用于持续验证加速器模型资源的释放和重新加载。

## 后续要求

- 第七版失败日志必须保留，不能覆盖。
- 修复后使用新实验编号 AIRTOS-K230-260805-003 和新结果目录 airtos-exp-v8-20260805-k230-24h 重新开始完整 24 小时。
- 新轮次必须重新生成环境散列、原始日志、最终审计和论文实验记录。

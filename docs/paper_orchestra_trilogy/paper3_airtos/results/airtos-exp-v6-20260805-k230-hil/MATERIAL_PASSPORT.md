# 实验素材护照

## 物理素材

- 开发板：CanMV-K230-LP4 V3.0，序列号 `001000000`。
- 实时系统控制台：`/dev/serial/by-id/usb-1a86_USB_Dual_Serial_5C78109061-if00`。
- 开发板调试接口：`/dev/serial/by-id/usb-Kendryte_CanMV_001000000-if00`。
- 系统镜像：`output/k230_canmv_v3p0_flash_20260730/sdk.img`。
- 镜像散列：`1389e00ab29d95cb2592f61c0ead503adbb97f08999f8175f1decf8b41361baf`。
- 实体外设：通用直接存储器访问设备、连续物理内存设备、神经网络加速器设备、OV5647 摄像头和芯片温度传感器。

## 输入数据

- 模型计划：`results/airtos/airtos-exp-v1-20260804-hostqemu/apparatus/compiler_corrected/model.aeg`。
- 模型计划散列：`e823492eb9abe21d150a26355c28b1ca9242ec923cca9bc04d7ca4a08d3ef106`。
- 调度计划说明：`results/airtos/airtos-exp-v1-20260804-hostqemu/apparatus/compiler_corrected/plan.json`。
- 全量语料：`results/airtos/airtos-exp-v5-20260804-complete-nonhil/final_run1/core12/rtthread_formal_corpus.bin`。
- 全量语料大小：49,085,520 字节。
- 全量语料散列：`c818ff4428b417d870e8d7b62b5696ee25e94deb4c2be8158441129bbc450906`。

## 实验程序

- 上传和板端散列：`experiments/airtos/k230_hil_transport.py`。
- 全量加载/调度重放：`experiments/airtos/k230_formal_runner.c`。
- 真实缓存和物理搬运：`experiments/airtos/k230_dma_hil.c`。
- 真实设备生命周期：`experiments/airtos/k230_gsdma_lifecycle.c`。
- 编译器生成算子时序：`experiments/airtos/k230_aot_timing.c`。
- 二十四分钟持续运行及后续二十四小时长测：`experiments/airtos/k230_long_hil.c`。
- 机器审计：`experiments/airtos/summarize_k230_hil.py`。
- 联合准入、并发租约、迟到事件和恢复实验复用 `experiments/airtos/` 下既有正式测试器。

编译后的实体程序和主机散列位于 `results/airtos/airtos-exp-v6-20260805-k230-hil/artifacts/` 和 `artifact_sha256.txt`。每个上传程序均由开发板重新计算散列，读回记录位于 `logs/preflight/upload.log`。

## 数据真实性边界

- 没有使用替身、模拟提供器或随机生成的“硬件结果”。
- 虚拟机历史结果只用于跨体系结构软件重放，不进入本轮物理缓存、物理时序或温度结果。
- 迟到事件通过真实板上的生产状态机入口注入，但不是驱动自然产生的迟到中断。
- 设备重开/重初始化调用真实设备库和 `/dev/gsdma_device`，但不等同于芯片硬复位。
- 没有外接功率计，因此没有功耗数据。
- 二十四分钟正式轮次连续运行 1,440 秒并完成 6,685,424 个作业；原始日志散列为 `e7c701c360893fec2a9270151ed20e6f033fa707366dfc4ff765cf8a3180e302`。
- 二十四分钟结果不替代后续二十四小时异构混合负载实验。
- 摄像头已在产品级实体报告中采集，但未并入本轮 AIRTOS 混合长测。

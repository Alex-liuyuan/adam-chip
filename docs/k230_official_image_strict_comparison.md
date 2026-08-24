# K230 候选镜像与官方镜像严格对比

对比日期：2026-07-30

## 对比对象

- 官方镜像：`third_party/canmv-v1.8-editable/output/k230_canmv_v3p0_defconfig/CanMV_K230_V3P0_micropython_v1.8-0-gc2d1f5c_nncase_v2.11.0.img`
- 项目候选镜像：`/tmp/adam_k230_replacement_20260730/run/13_ReleaseAgent/01_firmware/sdk.img`
- 候选镜像来源：`chip_agents.py run-project projects/k230_sdk_project.json`

比较过程只读，没有修改两份镜像。

## 最终判定

| 检查项 | 结果 | 判定 |
| --- | ---: | --- |
| 镜像大小 | 均为 650,117,120 字节 | 一致 |
| 整盘 SHA-256 | 不同 | 不一致 |
| MBR 前 512 字节 | 逐字节相同 | 一致 |
| 分区类型、起点和大小 | 完全相同 | 一致 |
| 启动组件放置偏移 | 完全相同 | 一致 |
| A/B 槽位冗余关系 | 各镜像内部 A/B 完全相同 | 一致 |
| 官方 FAT 文件是否丢失 | 0 个丢失 | 一致 |
| 共有普通文件 | 491 个，490 个逐字节相同 | 仅 `revision.txt` 不同 |
| 产品扩展 | 候选增加 1 个目录和 5 个文件 | 预期差异 |
| 物理板全功能等价 | 尚无完整 HIL 证据 | 未通过验收 |
| 性能优于官方镜像 | 尚无同板基准数据 | 未证明 |

结论：候选镜像不是官方镜像的逐字节复现，但磁盘布局、启动组件位置、A/B 结构和官方文件集均被保留。它可以进入物理板验收，当前不能宣称已经覆盖官方全功能，也不能宣称性能更优。

## 整盘与分区

整盘哈希：

```text
official  47b57bba1532b04add5199b0f16c104d796d08ba26cf02a6da3c6428796cda2c
candidate 1389e00ab29d95cb2592f61c0ead503adbb97f08999f8175f1decf8b41361baf
```

两份镜像均使用 DOS/MBR 分区表，磁盘标识均为 `0x00000000`：

| 分区 | 起始 LBA | 字节偏移 | 扇区数 | 大小 | 类型 |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 | 225,280 | 115,343,360 | 20,480 | 10 MiB | `0x0c` FAT |
| 2 | 245,760 | 125,829,120 | 1,024,000 | 500 MiB | `0x0c` FAT |

整盘共有 15,334,419 个字节不同，占 2.358716%。首个差异位于零基偏移 `2,097,164`，即 U-Boot 封装头内部。

| 区域 | 大小 | 不同字节 | 差异比例 | 首个差异 | 最后差异 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 启动区 | 115,343,360 | 15,326,539 | 13.287751% | 2,097,164 | 90,573,737 |
| FAT 分区 1 | 10,485,760 | 207 | 0.001974% | 115,343,399 | 115,368,792 |
| FAT 分区 2 | 524,288,000 | 7,673 | 0.001464% | 125,829,159 | 532,775,415 |

## 启动组件

组件边界来自 `boards/k230_canmv_v3p0/genimage-sdcard.cfg`。0 至 2 MiB 完全相同，因此 TOC、OTA 元数据、SPL 和 U-Boot 环境没有字节差异。

| 组件 | 偏移 | 官方封装大小 | 候选封装大小 | 严格结果 |
| --- | ---: | ---: | ---: | --- |
| U-Boot | 2 MiB | 301,380 | 301,380 | 39 字节不同，差异集中在封装头前 544 字节内 |
| OpenSBI/RT-Smart A | 10 MiB | 1,891,808 | 1,891,813 | 候选大 5 字节，内容哈希不同 |
| rtapp/MicroPython A | 30 MiB | 6,687,659 | 6,686,054 | 候选小 1,605 字节，压缩内容不同 |
| OpenSBI/RT-Smart B | 60 MiB | 1,891,808 | 1,891,813 | 与各自 A 槽完全相同 |
| rtapp/MicroPython B | 80 MiB | 6,687,659 | 6,686,054 | 与各自 A 槽完全相同 |

候选输出目录中的 `fn_ug_u-boot.bin`、`opensbi_rtt_system.bin` 和 `rtapp.elf.gz` 与候选镜像对应区域逐字节相同，证明镜像没有在组装时错写组件。关键启动字符串（包括 `U-Boot SPL`、`lpddr4`、`k230_load_img`、`k230_run_system`、`mmc_init`、`sdhci_init`、`board=k230_canmv_v3p0` 和 `MicroPython`）仍存在于相同偏移。

U-Boot 的 39 字节差异符合 K230 封装头中的摘要/签名元数据变化；OpenSBI/RT-Smart 和 rtapp 是重新生成的二进制/压缩产物，因此不能仅凭结构相同推断运行行为完全相同。

## FAT 文件系统

分区 1 两边均有 28 个路径，路径集合完全相同。分区 2 官方有 502 个路径，候选有 508 个路径，官方路径没有任何缺失。

候选新增：

```text
adam_product.json
apps/
apps/adam_hil_camera.py
apps/adam_hil_display.py
apps/adam_hil_kpu.py
apps/adam_product_smoke.py
```

两边共有 491 个普通文件，其中 490 个 SHA-256 完全相同。唯一不同的共有文件是 `revision.txt`：官方只记录 2026-07-03 构建时间，候选记录 20 个锁定仓库版本以及 2026-07-30 构建时间。FAT 分区自身的少量字节差异还包含目录项和时间戳等文件系统元数据。

## 项目产出边界

ReleaseAgent 清单显示：

```text
backend: canmv-editable
build.skipped: true
build.reason: verified existing artifact requested
self_hosted_boot_chain: true
sdk_candidate_ready: true
physical_release_ready: false
```

这表示候选镜像由项目工作流组装、注入产品文件、验证、签署和发布，但本次 ReleaseAgent 使用的是项目先前生成并验证的本地基底，没有在 Release 阶段重新编译固件组件。来源锁定文件为 `products/k230_canmv_v3p0/manifest.lock.xml`。构建溯源使用 `local-development` HMAC-SHA256 密钥，不是生产发布签名。

## 尚未通过的严格验收

在同一块 CanMV-K230 V3.0 板上完成以下测试前，状态保持为“候选镜像”，不能升级为“官方镜像替代品”：

1. 冷启动、热重启、A/B 槽位启动和异常掉电恢复。
2. USB 串口 REPL、脚本上传、异常回溯和软复位。
3. 摄像头采集、显示输出及长时间并发稳定性。
4. KPU 模型加载、推理正确性、内存峰值和吞吐量。
5. 网络、SD/FAT 读写、USB、GPIO、I2C、SPI、UART、PWM 和音频。
6. 与官方镜像使用同一测试输入，比较启动时间、帧率、推理延迟、功耗、内存和稳定性。

原始逐字节统计与文件清单保存在 `/tmp/adam_k230_strict_compare/`；项目发布门报告位于 `/tmp/adam_k230_replacement_20260730/run/13_ReleaseAgent/03_gate/release_gate_report.json`。

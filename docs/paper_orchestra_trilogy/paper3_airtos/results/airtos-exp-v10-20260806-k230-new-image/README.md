# AIRTOS-K230-260806-002 新镜像硬件实验

本轮在用户重新烧录镜像后启动，开始时间为 2026-08-06T07:33:00Z。

已启动：

- 数据搬运 24 小时任务：`/sdcard/airtos/long_hil_24h_v10_new_image.log`
- 四会话计算 24 小时任务：`/sdcard/airtos/compute_24h_v10_new_image.log`

第一次进程检查确认 `long_hil` 与 `compute_long_hil` 均在运行。启动日志中存在 `AIRTOS_K230_LONG_START` 与 `AIRTOS_K230_COMPUTE_START`。

新镜像仍只枚举出 `1a86:55d2 USB Dual_Serial`，未枚举出 CanMV IDE 脚本设备。`if02` 脚本探针未能创建 `/sdcard/airtos/new_image_ide_probe.txt`，因此摄像头加双模型混合实验仍阻塞。

运行中读取板端日志暂时返回打开失败，保留原始 checkpoint 日志；完整结果需等 24 小时任务结束后抓取。

## 摄像头加双模型混合预检

按用户要求重启后，主机短暂枚举出 `1209:abd1 Generic OpenMV Cam`，脚本设备为 `/dev/serial/by-id/usb-Kendryte_CanMV_001000000-if00`。随后执行 420 秒摄像头加双模型混合预检。

结果：`AIRTOS_K230_MIXED_PASS`。

- 运行时长：420 秒
- 摄像头帧：12,365
- 目标检测：12,365 次
- 人脸检测：1,237 次
- 摄像头管线重建：1 次
- 模型会话重建：14 次
- 帧错误：0
- 推理错误：0
- 生命周期错误：0
- 最大单帧耗时：60 毫秒
- IDE 外部中断：1 次，已单独计数，未计入摄像头或模型失败

原始日志：

- `logs/core4/mixed_preflight_420s_after_ide_interrupt_fix.log`
- `logs/core4/mixed_preflight_420s_board_log_recovered.log`

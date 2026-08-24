# AIRTOS-K230-260805-003 预检状态

更新时间：2026-08-06T07:06:37Z

## 已完成

真实 CanMV-K230 开发板已重新连接，控制台为 `/dev/serial/by-id/usb-1a86_USB_Dual_Serial_5C78109061-if00`，第二串口为 `/dev/serial/by-id/usb-1a86_USB_Dual_Serial_5C78109061-if02`。重启日志显示系统识别到 `ov5647_csi2` 摄像头。

420 秒数据搬运预检通过：

- 日志：`logs/core4/long_hil_preflight_v8.log`
- 结果：`elapsed_seconds=420 jobs=1097424 data_failures=0 device_failures=0 lifecycle_failures=0`
- 温度范围观察：约 52 到 55 摄氏度
- 日志散列：`5853d84b14f02ab34e3aa1de33b746bc64239215e8f36986fd68abceae12c464`

420 秒四会话计算预检通过：

- 日志：`logs/core4/compute_preflight_v8.log`
- 结果：`elapsed_seconds=420 batches=70500 jobs=282000 runtime_failures=0 numeric_failures=0 lease_failures=0 stale_failures=0 deadline_failures=0`
- 本轮真实板预算：`deadline_us=300000`
- 最大批次耗时：`maximum_batch_us=233733`
- 日志散列：`292c55e1f9fc44b977661bef38237665b0777338c89674c8a1939164f3b8034c`

## 参数修正

前一轮使用 `deadline_us=100000`，真实板上曾观察到约 231 到 234 毫秒的批次峰值，因此 100 毫秒预算会产生截止时间失败。第八版预检改用 300 毫秒预算，并且 420 秒内未观察到计算错误或截止时间失败。论文中只能写 300 毫秒真实板预算，不能写成 100 毫秒。

## 当前阻塞

摄像头和双模型混合实验尚未启动。原因不是摄像头本身，而是当前主机没有可用的 MicroPython 脚本注入通道：

- `if02` 写入脚本协议时发生写超时；
- `if02` 或 `if00` 均不能返回 `[mpy] enter repl` 完成标记；
- RT-Thread shell 没有 `python` 命令；
- `/sdcard/main.py` 在当前固件上不会自动运行，已删除临时测试文件。

因此当前不能启动完整 24 小时正式实验。下一步必须恢复 CanMV IDE/脚本注入设备，或提供可在 shell 中运行 Python 脚本的固件入口，然后重新运行混合预检和完整 24 小时实验。

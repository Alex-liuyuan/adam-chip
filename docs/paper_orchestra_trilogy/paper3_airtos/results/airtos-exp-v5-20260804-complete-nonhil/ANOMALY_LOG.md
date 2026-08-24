# AIRTOS v5 异常与复验记录

## Material Passport

- Experiment: `AIRTOS-FORMAL-260804-005`
- Scope: non-HIL extension over the retained v4 anomaly history
- Verification status: `VERIFIED`

| 阶段 | 真实观察 | 处理 | 最终状态 |
|---|---|---|---|
| v5 `final_run1` | 无安全主端点失败；所有 runner 写入 `RUN_PASS` | 不重试、不缩小 corpus | PASS |
| v5 `final_run2` | 无安全主端点失败；所有 runner 写入 `RUN_PASS` | 不重试、不缩小 corpus | PASS |
| artifact/verifier 现场校验 | 六类 1,800 case，预期 accept/reject 全部一致 | 无阈值调整 | PASS |
| trust-root 轮换 | old/dual/new 与 stale-root 判定各平台 1,500 case，failure=0 | 无阈值调整 | PASS |
| coherency 正式矩阵 | 七个执行环境各 1,000,000 case，failure=0 | 无 case 排除 | PASS |
| trace 噪声/ring-wrap | 每例 65-128 干扰事件，2,400/2,400 强制 wrap，failure=0 | 无标签或阈值调整 | PASS |
| 事后完整 `product_tools.selftest()` | 触发整条 K230 工程构建，命令会话到达外层时限后以 143 终止；无被测断言或 stderr | 不计为 PASS；改以真实 `plan.json/evidence.json` 直接执行生产 `_trust`，生成 2-obligation/1-root bundle | TARGETED PASS；完整 Engine 自检未完成 |

v4 中发现并修复的 `SimEDF+` 可预测性、RT-Thread 栈溢出、ARM freestanding `memcmp` 和 S8 active-lease 问题均保留在 v4 `ANOMALY_LOG.md`，没有在 v5 删除或重写。v5 没有失败 attempt 目录，因为两轮均首次完整通过。

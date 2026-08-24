# AIRTOS v5 材料护照

## Material Passport

- Experiment: `AIRTOS-FORMAL-260804-005`
- Data access: raw logs, CSV, binaries and recursive checksums retained locally
- Verification status: `VERIFIED` for non-HIL evidence

| 材料 | SHA-256 |
|---|---|
| `model.aeg` | `e823492eb9abe21d150a26355c28b1ca9242ec923cca9bc04d7ca4a08d3ef106` |
| `rt_ai_target.h` | `cc7fec3059d47c999b55bbb8171f2a1471eddcdf968c1ef13b4273af56be1e77` |
| `rtthread_formal_corpus.bin` | `c818ff4428b417d870e8d7b62b5696ee25e94deb4c2be8158441129bbc450906` |
| `formal_suite.py` | `a02132483d36b7e9678463199f6827583d18531db9278f7075f92e3dc8899675` |
| `admission_harness.c` | `5450aee3bcd496d980e63b1bacf5c8a37c12539f366fe47f260f2e1c2c41e37e` |
| `concurrency_probe.c` | `4cf917a0082e0247357bc8823e84f6a5a4a32532842f72ba6ef03a027a57c63d` |
| `recovery_harness.c` | `f5a67ef4b7097b7f22109423c5051b681f5463734935cfff968c3fe88397110c` |
| `coherency_formal.c` | `9fc52df7db2b0a4ff2858dc969944b0f17d84e461227c3450575a04cd61449ac` |
| `trust_material_harness.py` | `1a27b729ace36af57c3a9273d5f28a3ee8a237cdd64420bf464cb760be70ab8d` |
| `rtthread_formal_main.c` | `92183eb25f15d18cefcceffeaeffbcd0242a910dc5f6dba0da8c354852164713` |
| `qemu_arm_formal.c` | `7801c65eb2a47e039c986bfbe576cd0f226ea90fde58f0e7fc88ef9aca2c9917` |
| `run_software_experiments.sh` | `ef093661d807b542ba6450781176afce22b69dae559b840bae45e7fb981016be` |
| `run_rtthread_formal_qemu.sh` | `b5b0e71002d970d8238e3e0cad20127bd02a667d32ce1ccba0252fd78867a2fd` |
| `run_qemu_system_matrix.sh` | `320320e3c59016837b8b86a559c788f3939233cb499af88a4ddf76aaa51448b9` |
| production `product_tools.py` | `aea57e1c10238bf325cbea4616185b855db733d1337e23a65df636820c914655` |
| production `coherency.c` | `b641a72b0cbd4088c7090c046f47753df6f287d125e867a6a6133b32940dbe83` |
| production `plan_select.c` | `c764905dfeb6f3d108b3b32f7487498cf221f39f9c8e59d7593a953575543660` |
| production `coordinator.c` | `d31b42a170ea40aa040cde877f6a7b1dc4d8bb67665455b246066a64033bb17e` |
| production `sim_edf.c` | `49405710d38980aad02c7aeaeb79048a853e103d25f1aec717b572559e8c5d05` |

环境为 Linux 6.8.0-136 x86_64，GCC/RISC-V GCC 13.3.0，ARM GCC 13.2.1，QEMU 8.2.2，Python 3.12.3；Git 基线为 `232a0f7c0de4c8120bd31a2467b4298510d1e713` 加表中逐哈希记录的工作树实现。

每个 `final_run*` 含独立 `environment.env`、原始 CSV/log/binary、递归 `SHA256SUMS` 和最后写入的 `RUN_PASS`。RT-Thread ELF 两轮 SHA-256 均为 `430e5547434eeac828515d74e490b7af42ff45f2f664edbec0f1ee908879a43d`。

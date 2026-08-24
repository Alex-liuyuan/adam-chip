"""K230 RT-Thread BSP backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

SOURCE_SPEC = {
    "source_repo": "third_party/k230-sdk",
    "source_revision": "7e302f733311d284be255f0d81d3463b6ae6ee6d",
    "bsp_path": "src/big/rt-smart/kernel/bsp/maix3",
    "rtthread_path": "src/big/rt-smart/kernel/rt-thread",
    "required_symbols": [
        "rt_hw_interrupt_init", "rt_hw_mmu_map_init", "rt_hw_cpu_dcache_ops", "rt_hw_tick_init",
        "rt_hw_uart_init", "rt_hw_timer_init", "ipcm_module_init", "sharefs_module_init",
    ],
    "required_objects": [
        "c908/cache.o", "c908/clint.o", "c908/mmu.o", "c908/plic.o", "c908/tick.o",
        "board/interdrv/uart/drv_uart.o",
        "board/ipcm/ipcm_init.o", "board/ipcm/sharefs_init.o", "board/ipcm/virt_tty_init.o",
    ],
    "required_sources": ["board/interdrv/sdio/drv_sdhci.c"],
}


def build_source(out: Path, toolchain_bin: Path | None = None, jobs: int = 1) -> dict[str, Any]:
    from bsp import rtthread_source

    root = Path(__file__).resolve().parents[2]
    toolchain = toolchain_bin or root / "third_party/k230-toolchain/riscv64-linux-musleabi_for_x86_64-pc-linux-gnu/bin"
    return rtthread_source.build(root, out, SOURCE_SPEC, toolchain, root / ".venv/bin/scons", jobs)

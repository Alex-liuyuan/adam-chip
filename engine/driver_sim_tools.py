"""Contract-bound DriverAgent and SimulationAgent tools."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from engine.boot_bsp_tools import _run_qemu
from engine.source_discovery_tools import selected_anchor
from socimage.facts import is_safe, sha256


SUPPORTED = {
    "uart": "ns16550",
    "plic": "riscv,plic",
    "clint": "riscv,clint",
    "dma": "soc-image,descriptor-dma-v1",
    "clock": "soc-image,fixed-clock-mmio-v1",
    "reset": "soc-image,reset-v1",
    "pinmux": "soc-image,pinmux-v1",
}


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content) if isinstance(content, bytes) else path.write_text(content, encoding="utf-8")


def _fact(item: dict[str, Any], name: str) -> Any:
    value = item.get(name)
    return value.get("value") if is_safe(value) else None


def _compatible(item: dict[str, Any]) -> list[str]:
    value = _fact(item, "compatible")
    return [str(entry).lower() for entry in (value if isinstance(value, list) else [value]) if value is not None]


def _devices(hardware_ir: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    selected: dict[str, dict[str, Any]] = {}
    blocked = []
    for item in hardware_ir.get("peripherals", []):
        base = _fact(item, "base")
        if not isinstance(base, int):
            continue
        kind = item.get("kind", "peripheral")
        token = SUPPORTED.get(kind)
        if token and any(token in value for value in _compatible(item)):
            selected.setdefault(kind, item)
        elif kind not in {"peripheral"} or _compatible(item):
            blocked.append(f"peripherals.{item['id']}.register_contract")
    missing = sorted({"uart", "plic", "clint", "dma"} - selected.keys())
    if missing:
        raise ValueError("required standard IP contracts are missing: " + ", ".join(missing))
    return selected, sorted(blocked)


def _macro(kind: str, item: dict[str, Any]) -> str:
    prefix = f"SOC_{kind.upper()}"
    lines = [
        f"#define {prefix}_BASE ((uintptr_t)UINT64_C(0x{_fact(item, 'base'):x}))",
        f"#define {prefix}_SIZE UINT32_C(0x{int(_fact(item, 'size') or 0):x})",
    ]
    irq = _fact(item, "interrupts")
    if isinstance(irq, int):
        lines.append(f"#define {prefix}_IRQ UINT32_C({irq})")
    return "\n".join(lines)


def _register_header(devices: dict[str, dict[str, Any]]) -> str:
    blocks = "\n\n".join(_macro(kind, item) for kind, item in sorted(devices.items()))
    return f"""#ifndef SOC_REGS_H
#define SOC_REGS_H
#include <stdint.h>

{blocks}

#define SOC_UART_THR_OFFSET UINT32_C(0x0)
#define SOC_UART_LSR_OFFSET UINT32_C(0x5)
#define SOC_UART_LSR_TX_READY UINT8_C(0x20)
#define SOC_PLIC_CLAIM_OFFSET UINT32_C(0x201004)
#define SOC_CLINT_MTIME_OFFSET UINT32_C(0xbff8)
#define SOC_DMA_SRC_OFFSET UINT32_C(0x0)
#define SOC_DMA_DST_OFFSET UINT32_C(0x4)
#define SOC_DMA_LEN_OFFSET UINT32_C(0x8)
#define SOC_DMA_CTRL_OFFSET UINT32_C(0xc)
#define SOC_DMA_STATUS_OFFSET UINT32_C(0x10)
#define SOC_DMA_CTRL_START UINT32_C(0x1)
#define SOC_DMA_STATUS_DONE UINT32_C(0x1)
#define SOC_DMA_STATUS_ERROR UINT32_C(0x2)
#endif
"""


def _driver_header() -> str:
    return """#ifndef SOC_DRIVER_H
#define SOC_DRIVER_H
#include <stdint.h>
int soc_uart_putc(char value, uint32_t spin_limit);
uint64_t soc_timer_now(void);
uint32_t soc_irq_claim(void);
void soc_irq_complete(uint32_t irq);
void soc_dma_start(uint32_t source, uint32_t destination, uint32_t length);
int soc_dma_wait(uint32_t spin_limit);
#endif
"""


def _driver_source() -> str:
    return """#include <stdint.h>
#include "soc_regs.h"
#include "soc_driver.h"

extern uint8_t soc_mmio_read8(uintptr_t address);
extern void soc_mmio_write8(uintptr_t address, uint8_t value);
extern uint32_t soc_mmio_read32(uintptr_t address);
extern void soc_mmio_write32(uintptr_t address, uint32_t value);
extern uint64_t soc_mmio_read64(uintptr_t address);

int soc_uart_putc(char value, uint32_t spin_limit)
{
    while (spin_limit-- != 0U) {
        if ((soc_mmio_read8(SOC_UART_BASE + SOC_UART_LSR_OFFSET) & SOC_UART_LSR_TX_READY) != 0U) {
            soc_mmio_write8(SOC_UART_BASE + SOC_UART_THR_OFFSET, (uint8_t)value);
            return 0;
        }
    }
    return -1;
}

uint64_t soc_timer_now(void)
{
    return soc_mmio_read64(SOC_CLINT_BASE + SOC_CLINT_MTIME_OFFSET);
}

uint32_t soc_irq_claim(void)
{
    return soc_mmio_read32(SOC_PLIC_BASE + SOC_PLIC_CLAIM_OFFSET);
}

void soc_irq_complete(uint32_t irq)
{
    soc_mmio_write32(SOC_PLIC_BASE + SOC_PLIC_CLAIM_OFFSET, irq);
}

void soc_dma_start(uint32_t source, uint32_t destination, uint32_t length)
{
    soc_mmio_write32(SOC_DMA_BASE + SOC_DMA_SRC_OFFSET, source);
    soc_mmio_write32(SOC_DMA_BASE + SOC_DMA_DST_OFFSET, destination);
    soc_mmio_write32(SOC_DMA_BASE + SOC_DMA_LEN_OFFSET, length);
    soc_mmio_write32(SOC_DMA_BASE + SOC_DMA_CTRL_OFFSET, SOC_DMA_CTRL_START);
}

int soc_dma_wait(uint32_t spin_limit)
{
    while (spin_limit-- != 0U) {
        uint32_t status = soc_mmio_read32(SOC_DMA_BASE + SOC_DMA_STATUS_OFFSET);
        if ((status & SOC_DMA_STATUS_ERROR) != 0U) return -2;
        if ((status & SOC_DMA_STATUS_DONE) != 0U) return 0;
    }
    return -1;
}
"""


def _target_mmio() -> str:
    return """#include <stdint.h>
uint8_t soc_mmio_read8(uintptr_t address) { return *(volatile uint8_t *)address; }
void soc_mmio_write8(uintptr_t address, uint8_t value) { *(volatile uint8_t *)address = value; }
uint32_t soc_mmio_read32(uintptr_t address) { return *(volatile uint32_t *)address; }
void soc_mmio_write32(uintptr_t address, uint32_t value) { *(volatile uint32_t *)address = value; }
uint64_t soc_mmio_read64(uintptr_t address) { return *(volatile uint64_t *)address; }
"""


def _manifest(context: Any, devices: dict[str, dict[str, Any]], blocked: list[str], source: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "soc-image.driver-manifest.v1",
        "task_id": context.task_id,
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "source_lock_sha256": source["source_lock_sha256"],
        "generator": "DriverAgent",
        "selected_source": {"id": source["id"], "revision": source["revision"]},
        "reuse_mode": "contract-derived adaptation; no source file copied",
        "devices": [
            {
                "id": item["id"],
                "kind": kind,
                "base": _fact(item, "base"),
                "compatible": _compatible(item),
                "sources": item["base"]["sources"],
            }
            for kind, item in sorted(devices.items())
        ],
        "blocked_complex_ip": blocked,
    }


def _cross_compile(drivers: Path) -> None:
    compiler = shutil.which("riscv64-linux-gnu-gcc")
    if not compiler:
        raise RuntimeError("RISC-V cross compiler is unavailable")
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("soc_driver.c", "mmio_target.c"):
            proc = subprocess.run(
                [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-ffreestanding", "-I", str(drivers / "include"), "-c", str(drivers / "src" / name), "-o", str(Path(tmp) / f"{name}.o")],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            if proc.returncode:
                raise RuntimeError(f"driver cross compile failed for {name}:\n{proc.stdout}")


def generate_contract_drivers(context: Any) -> dict[str, Any]:
    devices, blocked = _devices(context.hardware_ir)
    source = selected_anchor(context)
    root = context.worktree / "generated/drivers"
    _write(root / "include/soc_regs.h", _register_header(devices))
    _write(root / "include/soc_driver.h", _driver_header())
    _write(root / "src/soc_driver.c", _driver_source())
    _write(root / "src/mmio_target.c", _target_mmio())
    _write(root / "manifest.json", json.dumps(_manifest(context, devices, blocked, source), indent=2, sort_keys=True) + "\n")
    _cross_compile(root)
    return {"status": "passed", "outputs": list(context.outputs), "blocked_complex_ip": blocked, "cross_compile_pass": True}


def verify_contract_drivers(context: Any) -> list[str]:
    errors = [f"missing driver output: {path}" for path in context.outputs if not (context.worktree / path).is_file()]
    if errors:
        return errors
    root = context.worktree / "generated/drivers"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("task_id") != context.task_id or manifest.get("hardware_ir_sha256") != context.hardware_ir_sha256:
        errors.append("driver manifest is not bound to the task and Hardware IR")
    source = selected_anchor(context)
    if manifest.get("source_lock_sha256") != source["source_lock_sha256"] or manifest.get("selected_source", {}).get("revision") != source["revision"]:
        errors.append("driver manifest is not bound to the promoted source lock")
    try:
        devices, blocked = _devices(context.hardware_ir)
        if manifest.get("blocked_complex_ip") != blocked:
            errors.append("complex IP blocker list does not match Hardware IR")
        if {item["kind"] for item in manifest.get("devices", [])} != set(devices):
            errors.append("driver manifest device set does not match Hardware IR")
        _cross_compile(root)
    except (RuntimeError, ValueError) as exc:
        errors.append(str(exc))
    return errors


def _mmio_model() -> str:
    return """#include <stdint.h>
#include "soc_regs.h"

static uint8_t uart_ready;
static uint8_t uart_value;
static uint32_t pending_irq;
static uint32_t completed_irq;
static uint64_t timer_value;
static uint32_t dma_mode;
static uint32_t dma_source;
static uint32_t dma_destination;
static uint32_t dma_length;

void host_uart_ready(uint8_t value) { uart_ready = value; }
uint8_t host_uart_value(void) { return uart_value; }
void host_raise_irq(uint32_t value) { pending_irq = value; }
uint32_t host_completed_irq(void) { return completed_irq; }
void host_timer_value(uint64_t value) { timer_value = value; }
void host_dma_mode(uint32_t value) { dma_mode = value; }
uint32_t host_dma_source(void) { return dma_source; }
uint32_t host_dma_destination(void) { return dma_destination; }
uint32_t host_dma_length(void) { return dma_length; }

uint8_t soc_mmio_read8(uintptr_t address)
{
    if (address == SOC_UART_BASE + SOC_UART_LSR_OFFSET) return uart_ready ? SOC_UART_LSR_TX_READY : 0U;
    return 0U;
}

void soc_mmio_write8(uintptr_t address, uint8_t value)
{
    if (address == SOC_UART_BASE + SOC_UART_THR_OFFSET) uart_value = value;
}

uint32_t soc_mmio_read32(uintptr_t address)
{
    if (address == SOC_PLIC_BASE + SOC_PLIC_CLAIM_OFFSET) return pending_irq;
    if (address == SOC_DMA_BASE + SOC_DMA_STATUS_OFFSET) {
        if (dma_mode == 1U) return SOC_DMA_STATUS_DONE;
        if (dma_mode == 2U) return SOC_DMA_STATUS_ERROR;
    }
    return 0U;
}

void soc_mmio_write32(uintptr_t address, uint32_t value)
{
    if (address == SOC_PLIC_BASE + SOC_PLIC_CLAIM_OFFSET) completed_irq = value;
    if (address == SOC_DMA_BASE + SOC_DMA_SRC_OFFSET) dma_source = value;
    if (address == SOC_DMA_BASE + SOC_DMA_DST_OFFSET) dma_destination = value;
    if (address == SOC_DMA_BASE + SOC_DMA_LEN_OFFSET) dma_length = value;
}

uint64_t soc_mmio_read64(uintptr_t address)
{
    return address == SOC_CLINT_BASE + SOC_CLINT_MTIME_OFFSET ? timer_value : 0U;
}
"""


def _host_test() -> str:
    return """#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "soc_driver.h"

void host_uart_ready(uint8_t value);
uint8_t host_uart_value(void);
void host_raise_irq(uint32_t value);
uint32_t host_completed_irq(void);
void host_timer_value(uint64_t value);
void host_dma_mode(uint32_t value);
uint32_t host_dma_source(void);
uint32_t host_dma_destination(void);
uint32_t host_dma_length(void);

int main(void)
{
    host_uart_ready(0U);
    assert(soc_uart_putc('X', 2U) == -1);
    host_uart_ready(1U);
    assert(soc_uart_putc('A', 2U) == 0 && host_uart_value() == 'A');
    host_timer_value(UINT64_C(0x123456789));
    assert(soc_timer_now() == UINT64_C(0x123456789));
    host_raise_irq(10U);
    assert(soc_irq_claim() == 10U);
    soc_irq_complete(10U);
    assert(host_completed_irq() == 10U);
    soc_dma_start(0x1000U, 0x2000U, 64U);
    assert(host_dma_source() == 0x1000U && host_dma_destination() == 0x2000U && host_dma_length() == 64U);
    host_dma_mode(1U);
    assert(soc_dma_wait(2U) == 0);
    host_dma_mode(0U);
    assert(soc_dma_wait(2U) == -1);
    host_dma_mode(2U);
    assert(soc_dma_wait(2U) == -2);
    puts("MMIO_PASS IRQ_PASS DMA_SUCCESS_PASS DMA_TIMEOUT_PASS DMA_ERROR_PASS");
    return 0;
}
"""


def _repl(devices: dict[str, dict[str, Any]]) -> str:
    return f"""// Generated from authoritative standard-compatible nodes.
cpu: CPU.RiscV64 @ sysbus
    cpuType: "rv64imafdc"
uart: UART.NS16550 @ sysbus 0x{_fact(devices['uart'], 'base'):x}
plic: IRQControllers.PlatformLevelInterruptController @ sysbus 0x{_fact(devices['plic'], 'base'):x}
clint: IRQControllers.CoreLevelInterruptor @ sysbus 0x{_fact(devices['clint'], 'base'):x}
"""


def _build_host(worktree: Path, destination: Path) -> tuple[str, str]:
    compiler = shutil.which("gcc")
    if not compiler:
        raise RuntimeError("host C compiler is unavailable")
    drivers = worktree / "generated/drivers"
    simulation = worktree / "generated/simulation"
    destination.mkdir(parents=True, exist_ok=True)
    binary = destination / "driver_tests"
    proc = subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(drivers / "include"), str(drivers / "src/soc_driver.c"), str(simulation / "host/mmio_model.c"), str(simulation / "host/test_drivers.c"), "-o", str(binary)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError("host driver test build failed:\n" + proc.stdout)
    run = subprocess.run([str(binary)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if run.returncode or not all(token in run.stdout for token in ("MMIO_PASS", "IRQ_PASS", "DMA_TIMEOUT_PASS", "DMA_ERROR_PASS")):
        raise RuntimeError("host driver tests failed:\n" + run.stdout)
    return run.stdout, sha256(binary)


def _simulation_report(context: Any, destination: Path) -> dict[str, Any]:
    host_log, binary_hash = _build_host(context.worktree, destination)
    qemu_log, qemu_pass = _run_qemu(context.worktree / "generated/platform/build/rtthread.elf")
    if not qemu_pass:
        raise RuntimeError("QEMU boot regression failed")
    _write(destination / "host.log", host_log)
    _write(destination / "qemu.log", qemu_log)
    return {
        "schema": "soc-image.driver-simulation-verification.v1",
        "host_mmio_pass": True,
        "irq_injection_pass": True,
        "dma_success_pass": True,
        "dma_timeout_injection_pass": True,
        "dma_error_injection_pass": True,
        "qemu_rtthread_shell_pass": True,
        "renode_model_generated": True,
        "driver_tests_sha256": binary_hash,
    }


def generate_simulation_models(context: Any) -> dict[str, Any]:
    devices, blocked = _devices(context.hardware_ir)
    root = context.worktree / "generated/simulation"
    _write(root / "platform.repl", _repl(devices))
    _write(root / "host/mmio_model.c", _mmio_model())
    _write(root / "host/test_drivers.c", _host_test())
    manifest = {
        "schema": "soc-image.simulation-manifest.v1",
        "task_id": context.task_id,
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "generator": "SimulationAgent",
        "driver_manifest_sha256": sha256(context.worktree / "generated/drivers/manifest.json"),
        "blocked_complex_ip": blocked,
    }
    _write(root / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    report = _simulation_report(context, root / "build")
    _write(root / "build/verification.json", json.dumps(report, indent=2, sort_keys=True) + "\n")
    return {"status": "passed", "outputs": list(context.outputs), "verification": report}


def verify_simulation_models(context: Any) -> list[str]:
    errors = [f"missing simulation output: {path}" for path in context.outputs if not (context.worktree / path).is_file()]
    if errors:
        return errors
    root = context.worktree / "generated/simulation"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("task_id") != context.task_id or manifest.get("hardware_ir_sha256") != context.hardware_ir_sha256:
        errors.append("simulation manifest is not bound to the task and Hardware IR")
    if manifest.get("driver_manifest_sha256") != sha256(context.worktree / "generated/drivers/manifest.json"):
        errors.append("simulation is not bound to the promoted driver manifest")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            report = _simulation_report(context, Path(tmp))
        if not all(value is True for name, value in report.items() if name.endswith("_pass")):
            errors.append("independent simulation verification did not pass")
    except RuntimeError as exc:
        errors.append(str(exc))
    return errors


def selftest() -> None:
    if not shutil.which("qemu-system-riscv64"):
        return
    from engine.control import Engine
    from socimage.hardware import derive
    from socimage.intake import create_run

    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp) / "run"
        create_run([root / "verification/materials/qemu_virt64_drivers.dts"], run)
        assert derive(run)["ok"]
        result = Engine(run).run_tasks(max_workers=1)
        assert result["ok"], result
        assert result["task_status"]["task:simulation_models"] == "passed"
        report = json.loads((run / "integration/generated/simulation/build/verification.json").read_text(encoding="utf-8"))
        assert report["dma_timeout_injection_pass"] and report["qemu_rtthread_shell_pass"]

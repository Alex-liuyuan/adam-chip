"""BootBspAgent tools for a contract-bound upstream RT-Thread QEMU target."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from engine.source_discovery_tools import selected_anchor
from engine.source_export import export_locked_build_source
from socimage.facts import is_safe, sha256


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_ANCESTRY = ("canmv", "k230_sdk", "sdk.img", "defconfig")
UPSTREAM_SOURCES = (
    "libcpu/risc-v/common64/cpuport.c",
    "libcpu/risc-v/common64/cpuport_gcc.S",
    "libcpu/risc-v/common64/context_gcc.S",
    "libcpu/risc-v/common64/sbi.c",
    "libcpu/risc-v/common64/tick.c",
    "libcpu/risc-v/common64/trap.c",
    "libcpu/risc-v/common/atomic_riscv.c",
    "libcpu/risc-v/virt64/start.c",
    "libcpu/risc-v/virt64/interrupt.c",
    "libcpu/risc-v/virt64/plic.c",
    "libcpu/risc-v/virt64/cache.c",
)


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _fact_value(value: Any) -> Any:
    return value["value"] if is_safe(value) else None


def _parameters(hardware_ir: dict[str, Any]) -> dict[str, Any]:
    isa = str(_fact_value(hardware_ir.get("cpu", {}).get("isa")) or "").lower()
    platform = str(_fact_value(hardware_ir.get("cpu", {}).get("platform_compatible")) or "").lower()
    if not isa.startswith("rv64"):
        raise ValueError("BootBspAgent currently requires an authoritative RV64 ISA")
    if "qemu" not in platform and "riscv-virtio" not in platform:
        raise ValueError("BootBspAgent has no verified platform provider for this hardware contract")
    region = next(
        (
            item for item in hardware_ir.get("memory_regions", [])
            if isinstance(_fact_value(item.get("base")), int) and isinstance(_fact_value(item.get("size")), int)
        ),
        None,
    )
    if region is None:
        raise ValueError("no safe memory region is available for the linker")
    memory_base = _fact_value(region["base"])
    memory_size = _fact_value(region["size"])
    sbi_reserve = 0x200000
    if memory_size <= sbi_reserve + 0x400000:
        raise ValueError("memory region is too small for OpenSBI and RT-Thread")
    march_match = re.match(r"^(rv64[a-z]+)", isa)
    if not march_match:
        raise ValueError(f"unsupported RISC-V ISA spelling: {isa}")
    march = march_match.group(1)
    if "zicsr" not in march:
        march += "_zicsr_zifencei"
    base_extensions = march_match.group(1)[4:]
    mabi = "lp64d" if "d" in base_extensions or "g" in base_extensions else "lp64"
    return {
        "isa": isa,
        "march": march,
        "mabi": mabi,
        "memory_base": memory_base,
        "memory_size": memory_size,
        "load_base": memory_base + sbi_reserve,
        "load_size": memory_size - sbi_reserve,
        "timebase_hz": 10_000_000,
    }


def _source_bytes(source: dict[str, Any], relative: str) -> bytes:
    proc = subprocess.run(["git", "show", f"{source['revision']}:{relative}"], cwd=source["path"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode:
        raise RuntimeError(f"locked source file is unavailable: {source['id']}:{relative}")
    return proc.stdout


def _linker(parameters: dict[str, Any]) -> str:
    return f"""OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY {{ RAM (rwx) : ORIGIN = 0x{parameters['load_base']:x}, LENGTH = 0x{parameters['load_size']:x} }}
__STACKSIZE__ = 16384;
SECTIONS
{{
  . = ORIGIN(RAM);
  __text_start = .;
  .start : {{ KEEP(*(.start)) }} > RAM
  .text :
  {{
    *(.text .text.*) *(.rodata .rodata.*)
    . = ALIGN(8); __fsymtab_start = .; KEEP(*(FSymTab)) __fsymtab_end = .;
    . = ALIGN(8); __vsymtab_start = .; KEEP(*(VSymTab)) __vsymtab_end = .;
    . = ALIGN(8); __rt_init_start = .; KEEP(*(SORT(.rti_fn*))) __rt_init_end = .;
  }} > RAM
  .eh_frame : {{ *(.eh_frame*) }} > RAM
  .data :
  {{
    *(.data .data.*) . = ALIGN(8); PROVIDE(__global_pointer$ = . + 0x800);
    *(.sdata .sdata.*)
  }} > RAM
  .ctors : {{ KEEP(*(SORT(.init_array.*))) KEEP(*(.init_array)) }} > RAM
  .dtors : {{ KEEP(*(SORT(.fini_array.*))) KEEP(*(.fini_array)) }} > RAM
  .stack (NOLOAD) : {{ . = ALIGN(64); __stack_start__ = .; . += __STACKSIZE__; __stack_end__ = .; }} > RAM
  .bss (NOLOAD) :
  {{
    . = ALIGN(8); __bss_start = .; *(.sbss .sbss.*) *(.bss .bss.*) *(COMMON)
    . = ALIGN(8); __bss_end = .;
  }} > RAM
  _end = .;
}}
"""


def _rtconfig_h(parameters: dict[str, Any]) -> str:
    fpu = "#define ARCH_RISCV_FPU\n" if parameters["mabi"] == "lp64d" else ""
    return """#ifndef RT_CONFIG_H__
#define RT_CONFIG_H__
#define RT_NAME_MAX 16
#define RT_USING_NANO
#define RT_ALIGN_SIZE 8
#define RT_CPUS_NR 1
#define RT_THREAD_PRIORITY_32
#define RT_THREAD_PRIORITY_MAX 32
#define RT_TICK_PER_SECOND 100
#define CLOCK_TIMER_FREQ 10000000
#define RT_USING_OVERFLOW_CHECK
#define IDLE_THREAD_STACK_SIZE 2048
#define __STACKSIZE__ 16384
#define RT_USING_SEMAPHORE
#define RT_USING_MUTEX
#define RT_USING_CONSOLE
#define RT_USING_CONSOLE_OUTPUT_CTL
#define RT_CONSOLEBUF_SIZE 128
#define RT_VER_NUM 0x50300
#define RT_KLIBC_USING_VSNPRINTF_LONGLONG
#define RT_KLIBC_USING_VSNPRINTF_STANDARD
#define RT_KLIBC_USING_LIBC_VSSCANF
#define RT_BACKTRACE_LEVEL_MAX_NR 16
#define ARCH_CPU_64BIT
#define ARCH_RISCV
#define ARCH_RISCV64
#define ARCH_USING_RISCV_COMMON64
#define ARCH_USING_NEW_CTX_SWITCH
#define RT_USING_CACHE
""" + fpu + """#define RT_USING_COMPONENTS_INIT
#define RT_USING_USER_MAIN
#define RT_MAIN_THREAD_STACK_SIZE 4096
#define RT_MAIN_THREAD_PRIORITY 10
#define RT_USING_FINSH
#define RT_USING_MSH
#define FINSH_USING_MSH
#define FINSH_THREAD_NAME "msh"
#define FINSH_THREAD_PRIORITY 20
#define FINSH_THREAD_STACK_SIZE 4096
#define FINSH_USING_SYMTAB
#define FINSH_CMD_SIZE 80
#define MSH_USING_BUILT_IN_COMMANDS
#define FINSH_ARG_MAX 10
#endif
"""


def _board_h() -> str:
    return """#ifndef GENERATED_BOARD_H
#define GENERATED_BOARD_H
#include <rtconfig.h>
extern unsigned int __bss_start;
extern unsigned int __bss_end;
void rt_hw_board_init(void);
#endif
"""


def _board_c(parameters: dict[str, Any]) -> str:
    return f"""#include <rthw.h>
#include <rtthread.h>
#include <sbi.h>
#include <tick.h>
#include <interrupt.h>
#include "board.h"

extern int entry(void);

void primary_cpu_entry(void)
{{
    rt_hw_interrupt_disable();
    entry();
}}

rt_uint64_t rt_hw_get_clock_timer_freq(void)
{{
    return {parameters['timebase_hz']}ULL;
}}

void rt_hw_board_init(void)
{{
    rt_hw_interrupt_init();
    rt_hw_tick_init();
    rt_components_board_init();
}}

signed char rt_hw_console_getchar(void)
{{
    return (signed char)sbi_console_getchar();
}}

void rt_hw_cpu_reset(void)
{{
    sbi_shutdown();
    for (;;) {{ }}
}}
"""


def _main_c(context: Any) -> str:
    return f"""#include <rtthread.h>

int main(void)
{{
    rt_kprintf("SOC_IMAGE_RUN {context.project_id}\\n");
    rt_kprintf("BOOT_BSP_TASK {context.task_id}\\n");
    return 0;
}}
"""


def _sconstruct() -> str:
    return """import os
import sys
import rtconfig
from rtconfig import RTT_ROOT
sys.path += [os.path.join(RTT_ROOT, 'tools')]
from building import *

TARGET = 'rtthread.elf'
DefaultEnvironment(tools=[])
env = Environment(tools=['mingw'], AS=rtconfig.AS, ASFLAGS=rtconfig.AFLAGS,
    CC=rtconfig.CC, CCFLAGS=rtconfig.CFLAGS, AR=rtconfig.AR, ARFLAGS='-rc',
    LINK=rtconfig.LINK, LINKFLAGS=rtconfig.LFLAGS)
env['ENV']['SOURCE_DATE_EPOCH'] = os.environ.get('SOURCE_DATE_EPOCH', '0')
env['ASCOM'] = env['ASPPCOM']
Export('RTT_ROOT')
Export('rtconfig')
rtconfig.CPU = 'virt64'
rtconfig.ARCH = 'risc-v'
objs = PrepareBuilding(env, RTT_ROOT, has_libcpu=True)
DoBuilding(TARGET, objs)
"""


def _sconscript() -> str:
    return """import os
from building import *
Import('RTT_ROOT')
cwd = GetCurrentDir()
upstream = os.path.join(cwd, 'upstream')
common64 = os.path.join(RTT_ROOT, 'libcpu', 'risc-v', 'common64')
common = os.path.join(RTT_ROOT, 'libcpu', 'risc-v', 'common')
virt64 = os.path.join(RTT_ROOT, 'libcpu', 'risc-v', 'virt64')
mm = os.path.join(RTT_ROOT, 'components', 'mm')
avl = os.path.join(RTT_ROOT, 'components', 'utilities', 'libadt', 'avl')
src = Glob('*.c') + [
    os.path.join(cwd, '..', 'boot', 'startup.S'),
    os.path.join(cwd, '..', 'boot', 'trap.S'),
    os.path.join(upstream, 'libcpu/risc-v/common64/cpuport.c'),
    os.path.join(upstream, 'libcpu/risc-v/common64/cpuport_gcc.S'),
    os.path.join(upstream, 'libcpu/risc-v/common64/context_gcc.S'),
    os.path.join(upstream, 'libcpu/risc-v/common64/sbi.c'),
    os.path.join(upstream, 'libcpu/risc-v/common64/tick.c'),
    os.path.join(upstream, 'libcpu/risc-v/common64/trap.c'),
    os.path.join(upstream, 'libcpu/risc-v/common/atomic_riscv.c'),
    os.path.join(upstream, 'libcpu/risc-v/virt64/start.c'),
    os.path.join(upstream, 'libcpu/risc-v/virt64/interrupt.c'),
    os.path.join(upstream, 'libcpu/risc-v/virt64/plic.c'),
    os.path.join(upstream, 'libcpu/risc-v/virt64/cache.c'),
]
group = DefineGroup('GeneratedBsp', src, depend=[''], CPPPATH=[
    cwd,
    os.path.join(upstream, 'libcpu/risc-v/common64'),
    os.path.join(upstream, 'libcpu/risc-v/common'),
    os.path.join(upstream, 'libcpu/risc-v/virt64'),
    common64, common, virt64, mm, avl,
])
Return('group')
"""


def _rtconfig_py(parameters: dict[str, Any]) -> str:
    march = parameters["march"]
    mabi = parameters["mabi"]
    return f"""import os
ARCH = 'risc-v'
CPU = 'virt64'
CROSS_TOOL = 'gcc'
RTT_ROOT = os.getenv('RTT_ROOT')
PLATFORM = 'gcc'
EXEC_PATH = os.getenv('RTT_EXEC_PATH') or '/usr/bin'
PREFIX = os.getenv('RTT_CC_PREFIX') or 'riscv64-linux-gnu-'
CC = PREFIX + 'gcc'
AS = PREFIX + 'gcc'
AR = PREFIX + 'ar'
LINK = PREFIX + 'gcc'
DEVICE = ' -mcmodel=medany -march={march} -mabi={mabi} '
BUILD_ROOT = os.path.dirname(os.getcwd())
REPRO = ' -ffile-prefix-map=' + BUILD_ROOT + '=/generated/platform -fmacro-prefix-map=' + BUILD_ROOT + '=/generated/platform '
CFLAGS = DEVICE + REPRO + '-Os -ffreestanding -fno-builtin -fno-common -ffunction-sections -fdata-sections -Wall'
AFLAGS = ' -c' + DEVICE + REPRO + ' -x assembler-with-cpp -D__ASSEMBLY__'
LFLAGS = DEVICE + ' -nostdlib -static -Wl,--gc-sections,--build-id=none,-Map=rtthread.map,-u,_start -T ../boot/link.lds -lgcc'
POST_ACTION = ''
"""


def _makefile() -> str:
    return """RTT_ROOT ?= ../../../third_party/rt-thread
.PHONY: all clean
all:
	RTT_ROOT=$(RTT_ROOT) scons -j2
	riscv64-linux-gnu-objcopy -O binary rtthread.elf rtthread.bin
clean:
	scons -c
"""


def _generate_sources(context: Any, parameters: dict[str, Any], source: dict[str, Any]) -> Path:
    platform = context.worktree / "generated/platform"
    if source["id"] != "rt-thread":
        raise RuntimeError(f"BootBspAgent has no QEMU adapter for selected BSP source: {source['id']}")
    startup_source = _source_bytes(source, "libcpu/risc-v/common64/startup_gcc.S")
    trap_source = _source_bytes(source, "libcpu/risc-v/common64/interrupt_gcc.S")
    files: dict[str, str | bytes] = {
        "boot/startup.S": startup_source,
        "boot/trap.S": trap_source,
        "boot/link.lds": _linker(parameters),
        "boot/opensbi/build.conf": f"PLATFORM=generic\nFW_TEXT_START=0x{parameters['memory_base']:x}\nFW_PAYLOAD_OFFSET=0x200000\n",
        "boot/u-boot/fragment.config": "CONFIG_RISCV=y\nCONFIG_64BIT=y\nCONFIG_TARGET_QEMU_VIRT=y\n",
        "rtthread/SConstruct": _sconstruct(),
        "rtthread/SConscript": _sconscript(),
        "rtthread/rtconfig.py": _rtconfig_py(parameters),
        "rtthread/rtconfig.h": _rtconfig_h(parameters),
        "rtthread/board.h": _board_h(),
        "rtthread/board.c": _board_c(parameters),
        "rtthread/main.c": _main_c(context),
        "rtthread/Makefile": _makefile(),
    }
    for relative, content in files.items():
        _write(platform / relative, content)
    upstream_files = []
    for relative in UPSTREAM_SOURCES:
        content = _source_bytes(source, relative)
        destination = platform / "rtthread/upstream" / relative
        _write(destination, content)
        upstream_files.append({"path": relative, "sha256": hashlib.sha256(content).hexdigest()})
    manifest = {
        "schema": "soc-image.boot-bsp-manifest.v1",
        "task_id": context.task_id,
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "source_lock_sha256": source["source_lock_sha256"],
        "generator": "BootBspAgent",
        "target": {"isa": parameters["isa"], "load_base": parameters["load_base"], "load_size": parameters["load_size"]},
        "upstream": [{
            "name": "RT-Thread",
            "revision": source["revision"],
            "source_files": [
                {"path": "libcpu/risc-v/common64/startup_gcc.S", "sha256": hashlib.sha256(startup_source).hexdigest()},
                {"path": "libcpu/risc-v/common64/interrupt_gcc.S", "sha256": hashlib.sha256(trap_source).hexdigest()},
                *upstream_files,
            ],
        }],
        "prohibited_ancestry": ["official firmware", "CanMV source", "K230 SDK", "existing defconfig"],
    }
    _write(platform / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return platform


def _run_qemu(elf: Path) -> tuple[str, bool]:
    qemu = shutil.which("qemu-system-riscv64")
    if not qemu:
        raise RuntimeError("qemu-system-riscv64 is unavailable")
    process = subprocess.Popen(
        [qemu, "-M", "virt", "-m", "128M", "-nographic", "-no-reboot", "-bios", "default", "-kernel", str(elf)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        output, _ = process.communicate(timeout=6)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            output, _ = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()
    passed = "RT-Thread" in output and "SOC_IMAGE_RUN" in output and "msh" in output
    return output, passed


def _build(context: Any, source_platform: Path, destination: Path, parameters: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    scons = shutil.which("scons")
    objcopy = shutil.which("riscv64-linux-gnu-objcopy")
    readelf = shutil.which("riscv64-linux-gnu-readelf")
    if not scons or not objcopy or not readelf:
        raise RuntimeError("RT-Thread, SCons, or the RISC-V cross tools are unavailable")
    with tempfile.TemporaryDirectory() as tmp:
        platform = Path(tmp) / "platform"
        rtthread = Path(tmp) / "rt-thread"
        export_locked_build_source(context, source["id"], rtthread)
        shutil.copytree(source_platform, platform, ignore=shutil.ignore_patterns("build", "*.elf", "*.bin", "*.map"))
        bsp = platform / "rtthread"
        env = {**os.environ, "RTT_ROOT": str(rtthread), "SOURCE_DATE_EPOCH": "0"}
        proc = subprocess.run([scons, "-C", str(bsp), "-j2"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        if proc.returncode:
            raise RuntimeError("RT-Thread build failed:\n" + "\n".join(proc.stdout.splitlines()[-30:]))
        elf = bsp / "rtthread.elf"
        binary = bsp / "rtthread.bin"
        subprocess.run([objcopy, "-O", "binary", str(elf), str(binary)], check=True)
        header = subprocess.run([readelf, "-h", str(elf)], text=True, stdout=subprocess.PIPE, check=True).stdout
        sections = subprocess.run([readelf, "-S", str(elf)], text=True, stdout=subprocess.PIPE, check=True).stdout
        entry_match = re.search(r"Entry point address:\s*(0x[0-9a-fA-F]+)", header)
        errors = []
        if "ELF64" not in header or "RISC-V" not in header:
            errors.append("ELF class or machine is not RV64")
        if not entry_match or int(entry_match.group(1), 16) != parameters["load_base"]:
            errors.append("ELF entry does not match the generated linker contract")
        for name in (".start", ".text", ".data", ".bss"):
            if name not in sections:
                errors.append(f"ELF section is missing: {name}")
        qemu_log, qemu_pass = _run_qemu(elf)
        if not qemu_pass:
            errors.append("QEMU did not reach the RT-Thread msh shell")
        if errors:
            raise RuntimeError("; ".join(errors) + "\n" + qemu_log[-4000:])
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(elf, destination / "rtthread.elf")
        shutil.copyfile(binary, destination / "rtthread.bin")
        _write(destination / "qemu.log", qemu_log)
        compiler = subprocess.run(["riscv64-linux-gnu-gcc", "--version"], text=True, stdout=subprocess.PIPE, check=True).stdout.splitlines()[0]
        report = {
            "schema": "soc-image.boot-bsp-verification.v1",
            "cross_compile_pass": True,
            "elf_entry_pass": True,
            "elf_sections_pass": True,
            "elf_abi": "ELF64 RISC-V lp64",
            "qemu_rtthread_shell_pass": True,
            "load_base": parameters["load_base"],
            "compiler": compiler,
            "rtthread_revision": source["revision"],
            "source_lock_sha256": source["source_lock_sha256"],
            "artifacts": {
                "rtthread.elf": sha256(destination / "rtthread.elf"),
                "rtthread.bin": sha256(destination / "rtthread.bin"),
            },
        }
        _write(destination / "verification.json", json.dumps(report, indent=2, sort_keys=True) + "\n")
        return report


def generate_boot_bsp(context: Any) -> dict[str, Any]:
    parameters = _parameters(context.hardware_ir)
    source = selected_anchor(context)
    platform = _generate_sources(context, parameters, source)
    report = _build(context, platform, platform / "build", parameters, source)
    return {"status": "passed", "outputs": list(context.outputs), "verification": report}


def verify_boot_bsp(context: Any) -> list[str]:
    errors = []
    platform = context.worktree / "generated/platform"
    for relative in context.outputs:
        if not (context.worktree / relative).is_file():
            errors.append(f"missing Boot/BSP output: {relative}")
    if errors:
        return errors
    manifest = json.loads((platform / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("task_id") != context.task_id or manifest.get("hardware_ir_sha256") != context.hardware_ir_sha256:
        errors.append("Boot/BSP manifest is not bound to the Agent task and Hardware IR")
    source = selected_anchor(context)
    if manifest.get("source_lock_sha256") != source["source_lock_sha256"]:
        errors.append("Boot/BSP manifest is not bound to the promoted source lock")
    for path in platform.rglob("*"):
        if path.is_file() and path.suffix not in {".elf", ".bin"}:
            lowered = path.read_text(encoding="utf-8", errors="ignore").lower()
            if any(token in lowered for token in FORBIDDEN_ANCESTRY):
                if path.name != "manifest.json":
                    errors.append(f"prohibited build ancestry token in {path.relative_to(platform)}")
    if errors:
        return errors
    parameters = _parameters(context.hardware_ir)
    with tempfile.TemporaryDirectory() as tmp:
        verification = Path(tmp) / "build"
        try:
            _build(context, platform, verification, parameters, source)
        except RuntimeError as exc:
            return [f"independent Boot/BSP verification failed: {exc}"]
        for name in ("rtthread.elf", "rtthread.bin"):
            if sha256(verification / name) != sha256(platform / "build" / name):
                errors.append(f"independent rebuild differs: {name}")
    return errors


def selftest() -> None:
    if not shutil.which("qemu-system-riscv64"):
        return
    from engine.control import Engine
    from socimage.hardware import derive
    from socimage.intake import create_run

    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp) / "run"
        create_run([ROOT / "verification/materials/qemu_virt64.dts"], run)
        assert derive(run)["ok"]
        result = Engine(run).run_tasks(max_workers=1)
        assert result["ok"], result
        assert result["task_status"]["task:boot_bsp"] == "passed"
        report = json.loads((run / "integration/generated/platform/build/verification.json").read_text(encoding="utf-8"))
        assert report["qemu_rtthread_shell_pass"]

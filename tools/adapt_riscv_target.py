#!/usr/bin/env python3
"""Generate compiler, RT-Thread, RVAIC and MicroPython files for a RISC-V target."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from compiler.backends.rvv_microkernel import catalog as rvv_catalog


IDENT = re.compile(r"[^A-Za-z0-9_]")
CPU_AOT_OPS = ["add", "conv2d", "matmul", "relu", "reshape"]
RVV_CANDIDATE_OPS = ["add", "conv2d", "layernorm", "matmul", "mul", "softmax"]


def safe_name(value: str) -> str:
    name = IDENT.sub("_", value).strip("_")
    if not name:
        raise ValueError("target name is empty after sanitizing")
    if name[0].isdigit():
        name = "target_" + name
    return name


def macro(value: str) -> str:
    return safe_name(value).upper()


def load_target(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("name", "isa", "abi", "toolchain_prefix"):
        if not data.get(key):
            raise ValueError(f"target missing {key}")
    data["_target_file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return data


def target_hash(target: dict) -> str:
    if target.get("_target_file_sha256"):
        return str(target["_target_file_sha256"])
    encoded = json.dumps({key: value for key, value in target.items() if not key.startswith("_")}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def rvv_execution_cores(target: dict) -> list[dict]:
    cores = []
    for core in target.get("cores", []):
        if core.get("rvv"):
            cores.append(
                {
                    "id": core.get("id", ""),
                    "role": core.get("role", ""),
                    "vlen_bits": int(core.get("vlen", target.get("rvv", {}).get("vlen", 0))),
                }
            )
    if cores:
        return cores
    rvv = target.get("rvv", {})
    if rvv.get("enabled"):
        return [{"id": "default", "role": "compute", "vlen_bits": int(rvv.get("vlen", 0))}]
    return []


def bootrom_core_has_rvv(target: dict) -> bool:
    bootrom_core = str(target.get("boot", {}).get("bootrom_core", ""))
    if not bootrom_core:
        return bool(target.get("rvv", {}).get("enabled"))
    for core in target.get("cores", []):
        if core.get("id") == bootrom_core:
            return bool(core.get("rvv"))
    return bool(target.get("rvv", {}).get("enabled"))


def rvv_inline_kernel_files(target: dict, target_sha: str, name: str, m: str) -> dict[str, str]:
    rvv = target.get("rvv", {})
    if not rvv.get("enabled"):
        return {}

    files = {}
    for rel, text in rvv_catalog.generate_files(name, target_sha, target).items():
        files[f"kernels/rvv_microkernels/{rel}"] = text
    files["kernels/rvv_core_guard.h"] = files["kernels/rvv_microkernels/rvv_core_guard.h"]
    files["kernels/rvv_kernel_abi.h"] = files["kernels/rvv_microkernels/rvv_kernel_abi.h"]
    files["kernels/rvv_inline_kernel_manifest.json"] = files["kernels/rvv_microkernels/rvv_kernel_manifest.json"]
    files["kernels/rvv_inline_add_f32.c"] = files["kernels/rvv_microkernels/add_f32.c"]
    return files


def memory_bytes(memory: dict, key: str, fallback_kb_key: str) -> int:
    if key in memory:
        return int(memory[key])
    return int(memory.get(fallback_kb_key, 0)) * 1024


def system_memory_bytes(memory: dict) -> int:
    for key, kb_key in (
        ("system_memory_bytes", "system_memory_kb"),
        ("ddr_bytes", "ddr_kb"),
        ("system_sram_bytes", "sram_kb"),
    ):
        value = memory_bytes(memory, key, kb_key)
        if value:
            return value
    return 0


def target_memory_regions(target: dict) -> list[dict]:
    memory = target.get("memory", {})
    dma = target.get("dma", {})
    npu = target.get("npu", {})
    cache = target.get("cache", {})
    cache_line = int(cache.get("line_size", 32))
    dma_align = int(dma.get("alignment", cache_line))
    regions = [
        {
            "name": "flash",
            "scope": "flash",
            "size_bytes": memory_bytes(memory, "flash_bytes", "flash_kb"),
            "alignment_bytes": cache_line,
            "executable": True,
            "dma_safe": False,
        },
        {
            "name": "system_sram",
            "scope": "system_sram",
            "size_bytes": system_memory_bytes(memory),
            "alignment_bytes": cache_line,
            "executable": False,
            "dma_safe": False,
            "kind": memory.get("memory_kind", "sram"),
        },
        {
            "name": "dma_safe",
            "scope": "dma_safe",
            "size_bytes": memory_bytes(memory, "dma_safe_bytes", "dma_safe_kb"),
            "alignment_bytes": dma_align,
            "executable": False,
            "dma_safe": True,
        },
    ]
    if npu.get("enabled"):
        regions.append(
            {
                "name": "npu_sram",
                "scope": "npu_sram",
                "size_bytes": memory_bytes(memory, "npu_sram_bytes", "npu_sram_kb"),
                "alignment_bytes": max(dma_align, int(npu.get("alignment", dma_align))),
                "executable": False,
                "dma_safe": True,
            }
        )
    return regions


def backend_capability(target: dict) -> dict:
    rvv = target.get("rvv", {})
    npu = target.get("npu", {})
    backends = [
        {
            "name": "cpu",
            "mask": 1,
            "status": "verified_safe_baseline",
            "ops": CPU_AOT_OPS,
            "dtypes": ["float32"],
            "evidence_required": ["generated_c_diff"],
        }
    ]
    if rvv.get("enabled"):
        backends.append(
            {
                "name": "rvv",
                "mask": 2,
                "status": "candidate_requires_board_evidence",
                "ops": RVV_CANDIDATE_OPS,
                "dtypes": ["float32", "float16", "int8"],
                "vlen_bits": int(rvv.get("vlen", 0)),
                "evidence_required": ["rvv_board_diff", "rvv_benchmark"],
            }
        )
    if npu.get("enabled"):
        backends.append(
            {
                "name": "npu",
                "mask": 4,
                "status": "candidate_requires_driver_or_simulator_evidence",
                "ops": sorted(npu.get("ops", [])),
                "dtypes": npu.get("dtypes", ["int8", "float16"]),
                "evidence_required": ["npu_nir_diff", "npu_driver_run"],
            }
        )
    return {
        "target": target.get("name"),
        "target_hash": target_hash(target),
        "backends": backends,
        "not_claimed": [
            "RVV runtime speedup without board evidence",
            "real NPU execution without driver/HIL evidence",
        ],
    }


def operator_capabilities(target: dict) -> dict:
    backend = backend_capability(target)
    ops: dict[str, dict] = {}
    for item in backend["backends"]:
        for op in item.get("ops", []):
            entry = ops.setdefault(op, {"op": op, "legal_backends": [], "verified_backends": [], "candidate_backends": []})
            entry["legal_backends"].append(item["name"])
            if item["status"].startswith("verified"):
                entry["verified_backends"].append(item["name"])
            else:
                entry["candidate_backends"].append(item["name"])
    return {
        "target": target.get("name"),
        "target_hash": target_hash(target),
        "ops": [ops[name] for name in sorted(ops)],
    }


def runtime_abi_contract(target: dict) -> dict:
    return {
        "name": "rvaic-runtime-abi",
        "version": 1,
        "target": target.get("name"),
        "target_hash": target_hash(target),
        "rtos": target.get("rtos", "rt-thread"),
        "objects": ["model", "tensor", "session", "job", "plan", "fence", "device"],
        "entrypoints": ["rvaic_model_admit", "rvaic_plan_select", "rvaic_plan_execute", "rvaic_service_submit"],
        "evidence_levels": ["E0", "E1", "E2", "E3", "E4", "E5", "E6"],
    }


def metaschedule_constraints(target: dict) -> dict:
    memory = target.get("memory", {})
    dma = target.get("dma", {})
    rvv = target.get("rvv", {})
    npu = target.get("npu", {})
    return {
        "target": target.get("name"),
        "target_hash": target_hash(target),
        "memory": {
            "max_system_sram_bytes": system_memory_bytes(memory),
            "max_dma_safe_bytes": memory_bytes(memory, "dma_safe_bytes", "dma_safe_kb"),
            "max_npu_sram_bytes": memory_bytes(memory, "npu_sram_bytes", "npu_sram_kb"),
        },
        "dma": {
            "alignment_bytes": int(dma.get("alignment", target.get("cache", {}).get("line_size", 32))),
            "channels": int(dma.get("channels", 1)),
            "max_transfer_bytes": int(dma.get("max_transfer_bytes", 0)),
        },
        "rvv": {
            "enabled": bool(rvv.get("enabled")),
            "vlen_bits": int(rvv.get("vlen", 0)),
        },
        "npu": {
            "enabled": bool(npu.get("enabled")),
            "ops": sorted(npu.get("ops", [])),
            "matrix_tile": npu.get("matrix_tile", []),
        },
    }


def shell_path(path: str) -> str:
    if Path(path).is_absolute():
        return path
    return "$ADAM_CHIP_ROOT/" + path


def render_files(target: dict, root: Path) -> dict[str, str]:
    name = safe_name(target["name"])
    m = macro(name)
    memory = target.get("memory", {})
    cache = target.get("cache", {})
    dma = target.get("dma", {})
    rvv = target.get("rvv", {})
    npu = target.get("npu", {})
    uart = target.get("uart", {})
    app = target.get("python_app", {})
    micropython = target.get("micropython", {})
    firmware = target.get("firmware", {})
    download = firmware.get("download", {})
    cc = target["toolchain_prefix"]
    isa = target["isa"]
    abi = target["abi"]
    cache_line = int(cache.get("line_size", 32))
    dma_align = int(dma.get("alignment", cache_line))
    mp_enabled = bool(micropython.get("enabled"))
    mp_package = micropython.get("package", "rtthread-micropython")
    mp_bsp = micropython.get("bsp", f"bsp/{name}")
    base_heap_kb = system_memory_bytes(memory) // 1024 or int(memory.get("sram_kb", 256))
    mp_heap_kb = int(micropython.get("heap_kb", max(base_heap_kb // 4, 64)))
    mp_stack_kb = int(micropython.get("stack_kb", 16))
    python_files = micropython.get("python_files", ["main.py", "modules"])
    firmware_image = firmware.get("image", f"build/micropython/{name}/firmware.bin")
    download_command = download.get("command", "printf 'set firmware.download.command in target json\\n'; exit 2")
    serial = firmware.get("serial", "/dev/ttyUSB0")
    baudrate = int(firmware.get("baudrate", 115200))
    uart_base = uart.get("base", "0x10000000UL")
    target_sha = target_hash(target)
    memory_regions = target_memory_regions(target)
    backend_caps = backend_capability(target)
    op_caps = operator_capabilities(target)
    runtime_abi = runtime_abi_contract(target)
    metaschedule = metaschedule_constraints(target)
    target_contract = {
        "name": name,
        "target_hash": target_sha,
        "isa": isa,
        "abi": abi,
        "rtos": target.get("rtos", "rt-thread"),
        "memory": memory,
        "memory_regions": memory_regions,
        "dma": dma,
        "rvv": rvv,
        "npu": npu,
    }

    kernel_strategy = {
        "target": name,
        "isa": isa,
        "abi": abi,
        "rvv": rvv,
        "npu": npu,
        "acceptance": ["kernel_build_pass", "operator_diff_pass", "fastcorrect_pass"],
    }
    generated_paths = [
        "compiler/toolchain.mk",
        "compiler/tvm_target.json",
        "compiler/operator_capabilities.json",
        "compiler/memory_regions.json",
        "compiler/metaschedule_constraints.json",
        "contracts/target_contract.json",
        "contracts/operator_capabilities.json",
        "contracts/memory_regions.json",
        "contracts/runtime_abi.json",
        "rtthread/Kconfig.fragment",
        "rtthread/rtconfig.py.fragment",
        "rtthread/applications/rvaic_conv_smoke.c",
        "rtthread/applications/SConscript",
        "rvaic/target_config.h",
        "rvaic/backend_capability.json",
        "rvaic/runtime_abi.json",
        "rvaic/admission_defaults.json",
        "kernels/kernel_strategy.json",
        "python/app.py",
        "examples/rtthread_session_template.c",
        "docs/application_development.md",
        "sdk_manifest.json",
    ]
    if rvv.get("enabled"):
        generated_paths.extend(
            [
                "kernels/rvv_core_guard.h",
                "kernels/rvv_inline_add_f32.c",
                "kernels/rvv_inline_kernel_manifest.json",
            ]
        )
    if mp_enabled:
        generated_paths.extend(
            [
                "micropython/package_config.json",
                "micropython/rtconfig_micropython.h",
                "micropython/adam_micropython_main.c",
                "micropython/main.py",
                "micropython/modules/.keep",
                "micropython/build_firmware.sh",
                "micropython/download_firmware.sh",
                "micropython/dev_shell.sh",
                "micropython/README.md",
            ]
        )

    developer_manifest = {
        "schema": "rvaic.application_sdk.v1",
        "target": name,
        "target_hash": target_sha,
        "generated_by": "tools/adapt_riscv_target.py",
        "runtime_package": "sdk/packages/rvaic",
        "contracts": {
            "target": "contracts/target_contract.json",
            "runtime_abi": "contracts/runtime_abi.json",
            "operator_capabilities": "compiler/operator_capabilities.json",
            "memory_regions": "compiler/memory_regions.json",
        },
        "application_surface": {
            "rtthread": {
                "kconfig_fragment": "rtthread/Kconfig.fragment",
                "applications_sconscript": "rtthread/applications/SConscript",
                "smoke_application": "rtthread/applications/rvaic_conv_smoke.c",
                "template": "examples/rtthread_session_template.c",
                "required_package_symbol": "PKG_USING_RVAIC",
            },
            "host_python": {
                "entrypoint": "python/app.py",
                "flow": ["import_onnx", "tvm_aot", "emit_rvaic_package", "build_rtthread_firmware"],
            },
            "micropython": {
                "enabled": mp_enabled,
                "package_config": "micropython/package_config.json" if mp_enabled else "",
            },
        },
        "public_api": {
            "model": ["rvaic_model_register", "rvaic_model_find", "rvaic_session_create", "rvaic_run"],
            "plan": ["rvaic_plan_admit", "rvaic_plan_select_with_evidence", "rvaic_plan_execute"],
            "service": ["rvaic_service_submit", "rvaic_job_wait", "rvaic_cancel", "rvaic_fence_wait"],
            "rt_ai": ["rt_ai_model_find", "rt_ai_model_admit", "rt_ai_submit", "rt_ai_cancel"],
        },
        "backend_policy": backend_caps,
        "operator_capabilities": op_caps,
        "memory_regions": memory_regions,
        "required_environment": ["ADAM_CHIP_ROOT", "RTTHREAD_BSP", "CROSS_COMPILE"],
        "developer_ready_evidence": [
            "target contract generated",
            "runtime ABI generated",
            "operator capability table generated",
            "RT-Thread application entry generated",
            "RVAIC target config generated",
            "host Python flow generated",
        ],
        "product_ready_blockers": [
            "project RT-Thread BSP",
            "project media flashing protocol",
            "physical RT-Thread RVAIC output diff",
            "CPU1 RVV board benchmark if RVV is enabled",
            "KPU/NPU HIL evidence if NPU is enabled",
        ],
        "not_claimed": [
            "arbitrary ONNX coverage",
            "RVV speedup without same-frequency board benchmark",
            "real NPU execution without KPU command ABI and HIL evidence",
            "burnable production SDK until board evidence reaches the configured release gate",
        ],
        "generated_paths": sorted(generated_paths),
    }

    files = {
        "sdk_manifest.json": json.dumps(developer_manifest, indent=2, sort_keys=True) + "\n",
        "docs/application_development.md": f"""# {name} Application SDK

This SDK directory is generated from `targets/{name}.json` by
`tools/adapt_riscv_target.py`.

## Stable application surface

- RT-Thread package: `sdk/packages/rvaic`
- Target config: `rvaic/target_config.h`
- Runtime ABI: `contracts/runtime_abi.json`
- Plan admission defaults: `rvaic/admission_defaults.json`
- Example RT-Thread application: `rtthread/applications/rvaic_conv_smoke.c`
- Non-compiled integration template: `examples/rtthread_session_template.c`
- Host app flow: `python/app.py`

## Evidence boundary

The generated SDK is application-development ready when
the generated manifest and RT-Thread smoke application pass their consumer checks. Production board
release still requires RT-Thread BSP integration, project-owned flashing,
RT-Thread output diff, and board evidence for RVV/NPU plans.
""",
        "examples/rtthread_session_template.c": f"""#include "rvaic.h"

int app_run_registered_model(const char *model_name, const rvaic_tensor_t *input, rvaic_tensor_t *output)
{{
    const rvaic_model_t *model = rvaic_model_find(model_name);
    rvaic_session_t *session;
    int status;

    if (!model || !input || !output)
    {{
        return -1;
    }}

    session = rvaic_session_create(model, sizeof(*model));
    if (!session)
    {{
        return -1;
    }}

    status = rvaic_set_input(session, 0, input);
    if (status == 0)
    {{
        status = rvaic_run(session);
    }}
    if (status == 0)
    {{
        status = rvaic_get_output(session, 0, output);
    }}

    rvaic_session_destroy(session);
    return status;
}}
""",
        "compiler/toolchain.mk": f"""RISCV_PREFIX ?= {cc}
RISCV_ARCH ?= {isa}
RISCV_ABI ?= {abi}
CC := $(RISCV_PREFIX)gcc
AR := $(RISCV_PREFIX)ar
OBJCOPY := $(RISCV_PREFIX)objcopy
CFLAGS += -march=$(RISCV_ARCH) -mabi=$(RISCV_ABI) -ffunction-sections -fdata-sections
LDFLAGS += -Wl,--gc-sections
""",
        "compiler/tvm_target.json": json.dumps(
            {
                "kind": "llvm",
                "mtriple": "riscv64-unknown-elf" if "64" in isa else "riscv32-unknown-elf",
                "mattr": "+" + isa,
                "mabi": abi,
                "target_hash": target_sha,
            },
            indent=2,
        )
        + "\n",
        "compiler/operator_capabilities.json": json.dumps(op_caps, indent=2, sort_keys=True) + "\n",
        "compiler/memory_regions.json": json.dumps({"target": name, "target_hash": target_sha, "regions": memory_regions}, indent=2, sort_keys=True) + "\n",
        "compiler/metaschedule_constraints.json": json.dumps(metaschedule, indent=2, sort_keys=True) + "\n",
        "contracts/target_contract.json": json.dumps(target_contract, indent=2, sort_keys=True) + "\n",
        "contracts/operator_capabilities.json": json.dumps(op_caps, indent=2, sort_keys=True) + "\n",
        "contracts/memory_regions.json": json.dumps({"target": name, "target_hash": target_sha, "regions": memory_regions}, indent=2, sort_keys=True) + "\n",
        "contracts/runtime_abi.json": json.dumps(runtime_abi, indent=2, sort_keys=True) + "\n",
        "rtthread/Kconfig.fragment": f"""config BSP_USING_{m}
    bool "Enable {name} board support"
    default y

config RVAIC_TARGET_{m}
    bool "Enable RVAIC target config for {name}"
    default y
""",
        "rtthread/rtconfig.py.fragment": f"""ARCH = 'risc-v'
CPU = '{target.get("cpu", "generic-riscv")}'
CROSS_TOOL = 'gcc'
EXEC_PATH = ''
PREFIX = '{cc}'
DEVICE = '{name}'
""",
        "rtthread/applications/rvaic_conv_smoke.c": f"""#include <rtthread.h>
#include "rvaic.h"

typedef signed char i8;

static int tiny_conv_run(void *user, const rvaic_tensor_t *inputs, rvaic_tensor_t *outputs)
{{
    (void)user;
    const i8 *input = (const i8 *)inputs[0].data;
    static const i8 kernel[9] = {{1, 1, 1, 1, 1, 1, 1, 1, 1}};
    static int output[4];

    for (int oh = 0; oh < 2; ++oh)
    {{
        for (int ow = 0; ow < 2; ++ow)
        {{
            int acc = 0;
            for (int kh = 0; kh < 3; ++kh)
            {{
                for (int kw = 0; kw < 3; ++kw)
                {{
                    acc += (int)input[(oh + kh) * 4 + (ow + kw)] * (int)kernel[kh * 3 + kw];
                }}
            }}
            output[oh * 2 + ow] = acc;
        }}
    }}

    outputs[0].data = output;
    outputs[0].ndim = 1;
    outputs[0].shape[0] = 4;
    return 0;
}}

static const rvaic_model_t tiny_conv_model = {{
    .magic = RVAIC_MODEL_MAGIC,
    .version = RVAIC_MODEL_VERSION,
    .input_count = 1,
    .output_count = 1,
    .run = tiny_conv_run,
}};

static int rvaic_conv_smoke(void)
{{
    static const i8 input[16] = {{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16}};
    static const int expected[4] = {{54, 63, 90, 99}};
    rvaic_tensor_t in = {{0}};
    rvaic_tensor_t out = {{0}};
    rvaic_session_t *session;
    int *values;

    in.data = (void *)input;
    in.ndim = 2;
    in.shape[0] = 4;
    in.shape[1] = 4;

    if (rvaic_init() != 0)
    {{
        rt_kprintf("RVAIC smoke init failed\\n");
        return -RT_ERROR;
    }}
    session = rvaic_session_create(&tiny_conv_model, sizeof(tiny_conv_model));
    if (!session || rvaic_set_input(session, 0, &in) != 0 || rvaic_run(session) != 0 || rvaic_get_output(session, 0, &out) != 0)
    {{
        rt_kprintf("RVAIC smoke run failed\\n");
        return -RT_ERROR;
    }}

    values = (int *)out.data;
    for (int i = 0; i < 4; ++i)
    {{
        if (values[i] != expected[i])
        {{
            rt_kprintf("RVAIC smoke mismatch %d got %d expected %d\\n", i, values[i], expected[i]);
            return -RT_ERROR;
        }}
    }}

    rt_kprintf("RVAIC_CONV_SMOKE_PASS target={name}\\n");
    rvaic_session_destroy(session);
    return RT_EOK;
}}
INIT_APP_EXPORT(rvaic_conv_smoke);
""",
        "rtthread/applications/SConscript": """from building import *

cwd = GetCurrentDir()
src = Glob('*.c')
CPPPATH = [cwd, cwd + '/../../rvaic', cwd + '/../../../sdk/packages/rvaic/include']

group = DefineGroup('Applications', src, depend=['PKG_USING_RVAIC'], CPPPATH=CPPPATH)
Return('group')
""",
        "rvaic/target_config.h": f"""#ifndef RVAIC_TARGET_CONFIG_H
#define RVAIC_TARGET_CONFIG_H

#define RVAIC_TARGET_NAME "{name}"
#define RVAIC_TARGET_ISA "{isa}"
#define RVAIC_TARGET_ABI "{abi}"
#define RVAIC_SRAM_KB {int(memory.get("sram_kb", 0))}
#define RVAIC_SYSTEM_MEMORY_KB {system_memory_bytes(memory) // 1024}
#define RVAIC_FLASH_KB {int(memory.get("flash_kb", 0))}
#define RVAIC_CACHE_LINE_SIZE {cache_line}
#define RVAIC_DMA_ALIGNMENT {dma_align}
#define RVAIC_HAS_RVV {1 if rvv.get("enabled") else 0}
#define RVAIC_RVV_VLEN {int(rvv.get("vlen", 0))}
#define RVAIC_HAS_NPU {1 if npu.get("enabled") else 0}
#define RVAIC_TARGET_HASH "{target_sha}"

#endif
""",
        "rvaic/backend_capability.json": json.dumps(backend_caps, indent=2, sort_keys=True) + "\n",
        "rvaic/runtime_abi.json": json.dumps(runtime_abi, indent=2, sort_keys=True) + "\n",
        "rvaic/admission_defaults.json": json.dumps(
            {
                "target": name,
                "target_hash": target_sha,
                "arena_free_bytes": memory_bytes(memory, "ai_arena_bytes", "ai_arena_kb") or system_memory_bytes(memory),
                "available_backends": [item["name"] for item in backend_caps["backends"]],
                "min_evidence_level": "E3",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "kernels/kernel_strategy.json": json.dumps(kernel_strategy, indent=2) + "\n",
        "python/app.py": f"""#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Host-side Python app flow for {name}")
    parser.add_argument("--model", default="{app.get("model", "model.onnx")}")
    parser.add_argument("--target", default="{name}")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    adam_chip_root = Path(os.environ.get("ADAM_CHIP_ROOT", {json.dumps(str(root))}))

    package = {{
        "target": args.target,
        "model": args.model,
        "steps": ["import_onnx", "tvm_aot", "emit_rvaic_package", "build_rtthread_firmware"],
    }}
    print(json.dumps(package, indent=2))
    if not args.dry_run:
        subprocess.run(
            ["python3", str(adam_chip_root / "chip_agents.py"), "strategy", "Build Python app model package", "--kind", "framework"],
            cwd=str(adam_chip_root),
            check=True,
        )


if __name__ == "__main__":
    main()
""",
    }
    files.update(rvv_inline_kernel_files(target, target_sha, name, m))
    if mp_enabled:
        package_config = {
            "target": name,
            "package": mp_package,
            "bsp": mp_bsp,
            "isa": isa,
            "abi": abi,
            "cpu": target.get("cpu", "generic-riscv"),
            "toolchain_prefix": cc,
            "heap_kb": mp_heap_kb,
            "stack_kb": mp_stack_kb,
            "python_files": python_files,
            "memory": memory,
            "uart": uart,
            "firmware_image": firmware_image,
        }
        files.update(
            {
                "micropython/package_config.json": json.dumps(package_config, indent=2) + "\n",
                "micropython/rtconfig_micropython.h": f"""#ifndef ADAM_MICROPYTHON_RTCONFIG_{m}_H
#define ADAM_MICROPYTHON_RTCONFIG_{m}_H

#define PKG_USING_MICROPYTHON
#define PKG_MICROPYTHON_HEAP_SIZE ({mp_heap_kb} * 1024)
#define ADAM_MICROPYTHON_STACK_SIZE ({mp_stack_kb} * 1024)
#define ADAM_MICROPYTHON_UART0_BASE {uart_base}
#define MICROPYTHON_USING_MACHINE_UART

#endif
""",
                "micropython/adam_micropython_main.c": f"""#include <rtthread.h>

extern void mpy_main(const char *filename);

static void adam_micropython_entry(void *parameter)
{{
    (void)parameter;
    for (;;)
    {{
        mpy_main(RT_NULL);
        rt_thread_mdelay(100);
    }}
}}

int adam_micropython_start(void)
{{
    rt_thread_t tid = rt_thread_create(
        "mpy",
        adam_micropython_entry,
        RT_NULL,
        ADAM_MICROPYTHON_STACK_SIZE,
        20,
        10);

    if (tid == RT_NULL)
    {{
        rt_kprintf("failed to create MicroPython thread\\n");
        return -RT_ERROR;
    }}

    rt_thread_startup(tid);
    return RT_EOK;
}}
INIT_APP_EXPORT(adam_micropython_start);
""",
                "micropython/main.py": f"""print("MicroPython ready on {name}")
""",
                "micropython/modules/.keep": "",
                "micropython/build_firmware.sh": f"""#!/bin/sh
set -eu

SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ADAM_CHIP_ROOT=${{ADAM_CHIP_ROOT:-{shlex.quote(str(root))}}}
RTTHREAD=${{RTTHREAD:-$ADAM_CHIP_ROOT/third_party/rt-thread}}
MICROPYTHON_PACKAGE=${{MICROPYTHON_PACKAGE:-$ADAM_CHIP_ROOT/third_party/{shlex.quote(mp_package)}}}
RTTHREAD_BSP=${{RTTHREAD_BSP:-$RTTHREAD/{shlex.quote(mp_bsp)}}}
MICROPYTHON_PKG_DIR=${{MICROPYTHON_PKG_DIR:-$RTTHREAD_BSP/packages/micropython-latest}}
BUILD_DIR=${{BUILD_DIR:-$ADAM_CHIP_ROOT/build/micropython/{name}}}
CROSS_COMPILE=${{CROSS_COMPILE:-{shlex.quote(cc)}}}

if [ ! -d "$RTTHREAD" ]; then
    echo "missing $RTTHREAD; run: sh scripts/fetch_third_party.sh" >&2
    exit 1
fi
if [ ! -d "$MICROPYTHON_PACKAGE" ]; then
    echo "missing $MICROPYTHON_PACKAGE; run: sh scripts/fetch_third_party.sh" >&2
    exit 1
fi
if [ ! -d "$RTTHREAD_BSP" ]; then
    echo "missing RT-Thread BSP: $RTTHREAD_BSP" >&2
    echo "set RTTHREAD_BSP to your board directory after BSP bring-up" >&2
    exit 2
fi
if ! command -v "${{CROSS_COMPILE}}gcc" >/dev/null 2>&1; then
    echo "missing toolchain: ${{CROSS_COMPILE}}gcc" >&2
    exit 1
fi
if ! printf '#include <stdint.h>\\n#include <stdio.h>\\n' | "${{CROSS_COMPILE}}gcc" -E - >/dev/null 2>&1; then
    echo "toolchain ${{CROSS_COMPILE}}gcc lacks C library headers; install a RISC-V bare-metal toolchain with newlib or picolibc" >&2
    exit 3
fi

mkdir -p "$RTTHREAD_BSP/packages" "$RTTHREAD_BSP/applications" "$BUILD_DIR"
ln -sfn "$MICROPYTHON_PACKAGE" "$MICROPYTHON_PKG_DIR"
cp "$SELF_DIR/adam_micropython_main.c" "$RTTHREAD_BSP/applications/adam_micropython_main.c"
cp "$SELF_DIR/rtconfig_micropython.h" "$BUILD_DIR/rtconfig_micropython.h"

if [ -f "$RTTHREAD_BSP/rtconfig.h" ] && ! grep -q '^#define PKG_USING_MICROPYTHON' "$RTTHREAD_BSP/rtconfig.h"; then
    cat "$SELF_DIR/rtconfig_micropython.h" >> "$RTTHREAD_BSP/rtconfig.h"
fi

if [ ! -f "$RTTHREAD_BSP/packages/SConscript" ]; then
    cat > "$RTTHREAD_BSP/packages/SConscript" <<'SCONS'
from building import *

objs = []
objs += SConscript('micropython-latest/SConscript')

Return('objs')
SCONS
fi

echo "RT-Thread MicroPython package: $MICROPYTHON_PACKAGE"
echo "BSP: $RTTHREAD_BSP"
if [ -f "$RTTHREAD_BSP/SConscript" ] && ! grep -q 'packages/SConscript' "$RTTHREAD_BSP/SConscript"; then
    echo "note: ensure $RTTHREAD_BSP/SConscript includes packages/SConscript"
fi
if [ "${{ADAM_PREPARE_ONLY:-0}}" = "1" ]; then
    exit 0
fi

if [ -z "${{RTT_EXEC_PATH:-}}" ]; then
    TOOLCHAIN_CC=$(command -v "${{CROSS_COMPILE}}gcc")
    export RTT_EXEC_PATH=$(dirname "$TOOLCHAIN_CC")
fi
cd "$RTTHREAD_BSP"
scons
""",
                "micropython/download_firmware.sh": f"""#!/bin/sh
set -eu

ADAM_CHIP_ROOT=${{ADAM_CHIP_ROOT:-{shlex.quote(str(root))}}}
FIRMWARE=${{FIRMWARE:-{shell_path(firmware_image)}}}
DOWNLOAD_COMMAND=${{DOWNLOAD_COMMAND:-{shlex.quote(download_command)}}}

if [ ! -f "$FIRMWARE" ]; then
    echo "missing firmware: $FIRMWARE" >&2
    echo "run: sh build_firmware.sh" >&2
    exit 1
fi

export FIRMWARE
sh -c "$DOWNLOAD_COMMAND"
""",
                "micropython/dev_shell.sh": f"""#!/bin/sh
set -eu

SERIAL=${{SERIAL:-{shlex.quote(serial)}}}
BAUDRATE=${{BAUDRATE:-{baudrate}}}

python3 -m mpremote connect "$SERIAL:$BAUDRATE" "$@"
""",
                "micropython/README.md": f"""# {name} MicroPython Firmware

```sh
sh build_firmware.sh
sh download_firmware.sh
sh dev_shell.sh
```

`package_config.json` is generated from `targets/{name}.json`. This flow reuses
the RT-Thread MicroPython package at `third_party/{mp_package}`; it does not
install or maintain a custom MicroPython port.
Use `RTTHREAD`, `RTTHREAD_BSP`, `MICROPYTHON_PACKAGE`, `CROSS_COMPILE`,
`FIRMWARE`, `SERIAL` and `BAUDRATE` to override the generated defaults.
""",
            }
        )
    return files


def write_files(files: dict[str, str], out: Path) -> list[str]:
    written = []
    for rel, content in files.items():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(str(path))
    return written


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = {
            "name": "demo",
            "isa": "rv64gcv",
            "abi": "lp64d",
            "toolchain_prefix": "riscv64-unknown-elf-",
            "rvv": {"enabled": True, "vlen": 128},
            "micropython": {"enabled": True, "package": "rtthread-micropython", "bsp": "bsp/demo", "heap_kb": 128},
            "firmware": {"download": {"command": "printf ok"}},
            "uart": {"base": "0x10000000UL"},
        }
        files = render_files(target, root)
        assert "compiler/toolchain.mk" in files
        assert "sdk_manifest.json" in files
        assert "examples/rtthread_session_template.c" in files
        assert "docs/application_development.md" in files
        manifest = json.loads(files["sdk_manifest.json"])
        assert manifest["schema"] == "rvaic.application_sdk.v1"
        assert manifest["application_surface"]["rtthread"]["required_package_symbol"] == "PKG_USING_RVAIC"
        assert "rvaic_plan_execute" in manifest["public_api"]["plan"]
        assert "physical RT-Thread RVAIC output diff" in manifest["product_ready_blockers"]
        assert "compiler/operator_capabilities.json" in files
        assert "compiler/metaschedule_constraints.json" in files
        assert "contracts/runtime_abi.json" in files
        assert "rvaic/backend_capability.json" in files
        assert "rvaic/admission_defaults.json" in files
        assert "RVAIC_HAS_RVV 1" in files["rvaic/target_config.h"]
        assert "RVAIC_TARGET_HASH" in files["rvaic/target_config.h"]
        assert json.loads(files["compiler/operator_capabilities.json"])["ops"]
        assert json.loads(files["rvaic/backend_capability.json"])["backends"][0]["status"] == "verified_safe_baseline"
        assert "QiMeng-GEMM" in files["kernels/kernel_strategy.json"]
        assert "kernels/rvv_inline_add_f32.c" in files
        assert "vsetvli" in files["kernels/rvv_inline_add_f32.c"]
        assert "vfadd.vv" in files["kernels/rvv_inline_add_f32.c"]
        assert "kernels/rvv_core_guard.h" in files
        assert "RVAIC_RVV_EXECUTION_CORE" in files["kernels/rvv_core_guard.h"]
        assert json.loads(files["kernels/rvv_inline_kernel_manifest.json"])["implementation"] == "riscv_vector_inline_asm"
        assert "micropython/build_firmware.sh" in files
        assert "RTTHREAD_BSP" in files["micropython/build_firmware.sh"]
        assert "rtthread/applications/rvaic_conv_smoke.c" in files
        assert "RVAIC_CONV_SMOKE_PASS" in files["rtthread/applications/rvaic_conv_smoke.c"]
        assert "rvaic_session_create" in files["rtthread/applications/rvaic_conv_smoke.c"]
        assert "rtthread/applications/SConscript" in files
        assert "PKG_USING_MICROPYTHON" in files["micropython/rtconfig_micropython.h"]
        assert "PKG_MICROPYTHON_HEAP_SIZE" in files["micropython/rtconfig_micropython.h"]
        assert "mpy_main" in files["micropython/adam_micropython_main.c"]
        assert "ADAM_MICROPYTHON_UART0_BASE 0x10000000UL" in files["micropython/rtconfig_micropython.h"]
        assert "printf ok" in files["micropython/download_firmware.sh"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?")
    parser.add_argument("--out", default="generated/targets")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        selftest()
        print("ok")
        return 0
    if not args.target:
        parser.error("target json is required unless --selftest is used")

    root = Path.cwd()
    target = load_target(Path(args.target))
    out = Path(args.out) / safe_name(target["name"])
    written = write_files(render_files(target, root), out)
    print(json.dumps({"target": target["name"], "out": str(out), "written": written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

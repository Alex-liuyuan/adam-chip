#!/usr/bin/env python3
"""Contract-driven RVV microkernel catalog and inline-asm generator."""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class KernelSpec:
    name: str
    op: str
    dtype: str
    prototype: str
    instructions: tuple[str, ...]
    source: str
    scalar_fallback: str


def rvv_contract(target: dict[str, Any]) -> dict[str, Any]:
    rvv = target.get("rvv", {}) if isinstance(target.get("rvv"), dict) else {}
    return {
        "version": str(rvv.get("version", "1.0")),
        "vlen_bits": int(rvv.get("vlen_bits", rvv.get("vlen", 0)) or 0),
        "legal_sew_bits": list(rvv.get("legal_sew_bits", [32])),
        "legal_lmul": list(rvv.get("legal_lmul", ["m1"])),
        "tail_policy": list(rvv.get("tail_policy", ["ta"])),
        "mask_policy": list(rvv.get("mask_policy", ["ma"])),
        "min_alignment_bytes": int(rvv.get("min_alignment_bytes", 4) or 4),
        "execution_cores": list(rvv.get("execution_cores", [])),
        "forbidden_cores": list(rvv.get("forbidden_cores", [])),
        "default_c_api": str(rvv.get("default_c_api", "inline_asm")),
        "required_static_evidence": list(rvv.get("required_static_evidence", ["rvv_contract_pass", "rvv_static_compile_pass", "rvv_objdump_signature_pass"])),
        "required_board_evidence": list(rvv.get("required_board_evidence", ["rvv_cpu1_board_diff_pass", "rvv_cpu1_benchmark_pass"])),
    }


def abi_h(target_name: str) -> str:
    guard = target_name.upper()
    return f"""#ifndef RVAIC_RVV_KERNEL_ABI_{guard}_H
#define RVAIC_RVV_KERNEL_ABI_{guard}_H

#include <stddef.h>

#define RVAIC_RVV_OK 0
#define RVAIC_RVV_EINVAL (-1)

void rvaic_rvv_add_f32(const float *a, const float *b, float *c, size_t n);
void rvaic_rvv_mul_f32(const float *a, const float *b, float *c, size_t n);
void rvaic_rvv_axpy_f32(float alpha, const float *x, const float *y, float *out, size_t n);
void rvaic_rvv_relu_f32(const float *x, float *out, size_t n);
float rvaic_rvv_dot_f32(const float *a, const float *b, size_t n);
float rvaic_rvv_reduce_sum_f32(const float *x, size_t n);

#endif
"""


def core_guard_h(target_name: str, target_hash: str, contract: dict[str, Any]) -> str:
    guard = target_name.upper()
    execution_core = str(contract["execution_cores"][0]) if contract["execution_cores"] else "default"
    forbidden = ",".join(map(str, contract["forbidden_cores"]))
    return f"""#ifndef RVAIC_RVV_CORE_GUARD_{guard}_H
#define RVAIC_RVV_CORE_GUARD_{guard}_H

#define RVAIC_RVV_TARGET_HASH "{target_hash}"
#define RVAIC_RVV_EXECUTION_CORE "{execution_core}"
#define RVAIC_RVV_FORBIDDEN_CORES "{forbidden}"
#define RVAIC_RVV_VLEN_BITS {int(contract["vlen_bits"])}
#define RVAIC_RVV_SEW_BITS 32
#define RVAIC_RVV_LMUL m1
#define RVAIC_RVV_MIN_ALIGNMENT_BYTES {int(contract["min_alignment_bytes"])}
#define RVAIC_RVV_MAX_VL_F32 ((RVAIC_RVV_VLEN_BITS / 32) ? (RVAIC_RVV_VLEN_BITS / 32) : 1)

#endif
"""


def include_headers() -> str:
    return """#include <stddef.h>

#include "rvv_kernel_abi.h"
#include "rvv_core_guard.h"
"""


def binary_source(fname: str, asm_op: str) -> str:
    return include_headers() + f"""
void {fname}(const float *a, const float *b, float *c, size_t n)
{{
    for (size_t i = 0; i < n;)
    {{
        size_t vl;
        __asm__ volatile ("vsetvli %0, %1, e32, m1, ta, ma" : "=r"(vl) : "r"(n - i));
        __asm__ volatile ("vle32.v v8, (%0)" :: "r"(a + i) : "memory");
        __asm__ volatile ("vle32.v v9, (%0)" :: "r"(b + i) : "memory");
        __asm__ volatile ("{asm_op} v10, v8, v9" ::: "memory");
        __asm__ volatile ("vse32.v v10, (%0)" :: "r"(c + i) : "memory");
        i += vl;
    }}
}}
"""


def axpy_source() -> str:
    return include_headers() + """
void rvaic_rvv_axpy_f32(float alpha, const float *x, const float *y, float *out, size_t n)
{
    for (size_t i = 0; i < n;)
    {
        size_t vl;
        __asm__ volatile ("vsetvli %0, %1, e32, m1, ta, ma" : "=r"(vl) : "r"(n - i));
        __asm__ volatile ("vle32.v v8, (%0)" :: "r"(x + i) : "memory");
        __asm__ volatile ("vle32.v v9, (%0)" :: "r"(y + i) : "memory");
        __asm__ volatile ("vfmul.vf v10, v8, %0" :: "f"(alpha) : "memory");
        __asm__ volatile ("vfadd.vv v10, v10, v9" ::: "memory");
        __asm__ volatile ("vse32.v v10, (%0)" :: "r"(out + i) : "memory");
        i += vl;
    }
}
"""


def relu_source() -> str:
    return include_headers() + """
void rvaic_rvv_relu_f32(const float *x, float *out, size_t n)
{
    const float zero = 0.0f;
    for (size_t i = 0; i < n;)
    {
        size_t vl;
        __asm__ volatile ("vsetvli %0, %1, e32, m1, ta, ma" : "=r"(vl) : "r"(n - i));
        __asm__ volatile ("vle32.v v8, (%0)" :: "r"(x + i) : "memory");
        __asm__ volatile ("vfmax.vf v10, v8, %0" :: "f"(zero) : "memory");
        __asm__ volatile ("vse32.v v10, (%0)" :: "r"(out + i) : "memory");
        i += vl;
    }
}
"""


def dot_source() -> str:
    return include_headers() + """
float rvaic_rvv_dot_f32(const float *a, const float *b, size_t n)
{
    float sum = 0.0f;
    float tmp[RVAIC_RVV_MAX_VL_F32];
    for (size_t i = 0; i < n;)
    {
        size_t vl;
        __asm__ volatile ("vsetvli %0, %1, e32, m1, ta, ma" : "=r"(vl) : "r"(n - i));
        __asm__ volatile ("vle32.v v8, (%0)" :: "r"(a + i) : "memory");
        __asm__ volatile ("vle32.v v9, (%0)" :: "r"(b + i) : "memory");
        __asm__ volatile ("vfmul.vv v10, v8, v9" ::: "memory");
        __asm__ volatile ("vse32.v v10, (%0)" :: "r"(tmp) : "memory");
        for (size_t j = 0; j < vl; ++j)
        {
            sum += tmp[j];
        }
        i += vl;
    }
    return sum;
}
"""


def reduce_source() -> str:
    return include_headers() + """
float rvaic_rvv_reduce_sum_f32(const float *x, size_t n)
{
    float sum = 0.0f;
    float tmp[RVAIC_RVV_MAX_VL_F32];
    for (size_t i = 0; i < n;)
    {
        size_t vl;
        __asm__ volatile ("vsetvli %0, %1, e32, m1, ta, ma" : "=r"(vl) : "r"(n - i));
        __asm__ volatile ("vle32.v v8, (%0)" :: "r"(x + i) : "memory");
        __asm__ volatile ("vse32.v v8, (%0)" :: "r"(tmp) : "memory");
        for (size_t j = 0; j < vl; ++j)
        {
            sum += tmp[j];
        }
        i += vl;
    }
    return sum;
}
"""


def kernels() -> list[KernelSpec]:
    return [
        KernelSpec("add_f32", "add", "float32", "void rvaic_rvv_add_f32(const float *a, const float *b, float *c, size_t n)", ("vsetvli", "vle32.v", "vfadd.vv", "vse32.v"), binary_source("rvaic_rvv_add_f32", "vfadd.vv"), "scalar_add_f32"),
        KernelSpec("mul_f32", "mul", "float32", "void rvaic_rvv_mul_f32(const float *a, const float *b, float *c, size_t n)", ("vsetvli", "vle32.v", "vfmul.vv", "vse32.v"), binary_source("rvaic_rvv_mul_f32", "vfmul.vv"), "scalar_mul_f32"),
        KernelSpec("axpy_f32", "axpy", "float32", "void rvaic_rvv_axpy_f32(float alpha, const float *x, const float *y, float *out, size_t n)", ("vsetvli", "vle32.v", "vfmul.vf", "vfadd.vv", "vse32.v"), axpy_source(), "scalar_axpy_f32"),
        KernelSpec("dot_f32", "dot", "float32", "float rvaic_rvv_dot_f32(const float *a, const float *b, size_t n)", ("vsetvli", "vle32.v", "vfmul.vv", "vse32.v"), dot_source(), "scalar_dot_f32"),
        KernelSpec("reduce_sum_f32", "reduce_sum", "float32", "float rvaic_rvv_reduce_sum_f32(const float *x, size_t n)", ("vsetvli", "vle32.v", "vse32.v"), reduce_source(), "scalar_reduce_sum_f32"),
        KernelSpec("relu_f32", "relu", "float32", "void rvaic_rvv_relu_f32(const float *x, float *out, size_t n)", ("vsetvli", "vle32.v", "vfmax.vf", "vse32.v"), relu_source(), "scalar_relu_f32"),
    ]


def manifest(target_name: str, target_hash: str, target: dict[str, Any]) -> dict[str, Any]:
    contract = rvv_contract(target)
    return {
        "schema": "adam.rvv.microkernel_catalog.v1",
        "target": target_name,
        "target_hash": target_hash,
        "kernel": "rvv_microkernel_catalog",
        "implementation": "riscv_vector_inline_asm",
        "status": "static_compile_candidate_requires_board_benchmark",
        "contract": contract,
        "required_evidence": contract["required_static_evidence"] + contract["required_board_evidence"],
        "kernels": [
            {
                "name": spec.name,
                "op": spec.op,
                "dtype": spec.dtype,
                "prototype": spec.prototype,
                "source": f"{spec.name}.c",
                "instruction_signature": list(spec.instructions),
                "scalar_fallback": spec.scalar_fallback,
                "evidence_level": "E3_static_objdump_required",
            }
            for spec in kernels()
        ],
        "not_claimed": [
            "RVV runtime execution",
            "RVV performance improvement over scalar CPU",
            "TVM TensorIR RVV lowering",
        ],
    }


def generate_files(target_name: str, target_hash: str, target: dict[str, Any]) -> dict[str, str]:
    contract = rvv_contract(target)
    files = {
        "rvv_kernel_abi.h": abi_h(target_name),
        "rvv_core_guard.h": core_guard_h(target_name, target_hash, contract),
        "rvv_kernel_manifest.json": json.dumps(manifest(target_name, target_hash, target), indent=2, sort_keys=True) + "\n",
    }
    for spec in kernels():
        files[f"{spec.name}.c"] = spec.source
    return files


def write_catalog(out: Path, target_name: str, target_hash: str, target: dict[str, Any]) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    files = generate_files(target_name, target_hash, target)
    for rel, text in files.items():
        (out / rel).write_text(text, encoding="utf-8")
    report = {
        "ok": True,
        "schema": "adam.rvv.microkernel_codegen.v1",
        "out": str(out),
        "files": sorted(files),
        "manifest": str(out / "rvv_kernel_manifest.json"),
        "kernel_count": len(kernels()),
    }
    (out / "rvv_microkernel_codegen_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def selftest() -> None:
    target = {
        "rvv": {
            "enabled": True,
            "version": "1.0",
            "vlen_bits": 128,
            "legal_sew_bits": [32],
            "legal_lmul": ["m1"],
            "tail_policy": ["ta"],
            "mask_policy": ["ma"],
            "min_alignment_bytes": 4,
            "execution_cores": ["cpu1"],
            "forbidden_cores": ["cpu0"],
            "default_c_api": "inline_asm",
        }
    }
    with tempfile.TemporaryDirectory() as tmp:
        report = write_catalog(Path(tmp), "demo", "hash", target)
        assert report["kernel_count"] == 6, report
        data = json.loads((Path(tmp) / "rvv_kernel_manifest.json").read_text(encoding="utf-8"))
        assert data["contract"]["vlen_bits"] == 128, data
        assert {item["name"] for item in data["kernels"]} >= {"add_f32", "dot_f32", "relu_f32"}, data
        assert "vfmax.vf" in (Path(tmp) / "relu_f32.c").read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=False)
    parser.add_argument("--target-name", default="demo")
    parser.add_argument("--target-hash", default="unknown")
    parser.add_argument("--out", default="/tmp/adam_rvv_microkernel")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    target = json.loads(Path(args.target).read_text(encoding="utf-8")) if args.target else {"rvv": {"enabled": True, "vlen_bits": 128}}
    report = write_catalog(Path(args.out), args.target_name, args.target_hash, target)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

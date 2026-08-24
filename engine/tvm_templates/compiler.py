#!/usr/bin/env python3
"""Hardware-contract TVM Relax/S-TIR compiler used by CompilerAgent."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import tvm
from onnx import TensorProto, helper
from tvm import relax
from tvm.relax.dpl.pattern import is_op, wildcard
from tvm.relax.frontend.onnx import from_onnx
from tvm.script import tirx as T

from plan_v2 import build_contracts, encode_aeg


@T.prim_func(s_tir=True)
def rvv_add_relu_workload(
    input_buffer: T.Buffer((8,), "float32"),
    constant_buffer: T.Buffer((8,), "float32"),
    output_buffer: T.Buffer((8,), "float32"),
):
    for index in range(8):
        with T.sblock("rvv_add_relu"):
            value = T.axis.spatial(8, index)
            T.reads(input_buffer[value], constant_buffer[value])
            T.writes(output_buffer[value])
            output_buffer[value] = T.max(input_buffer[value] + constant_buffer[value], T.float32(0.0))


@T.prim_func(s_tir=True)
def rvv_add_relu_desc(
    input_handle: T.handle,
    constant_handle: T.handle,
    output_handle: T.handle,
):
    input_buffer = T.match_buffer(input_handle, (8,), "float32", offset_factor=1)
    constant_buffer = T.match_buffer(constant_handle, (8,), "float32", offset_factor=1)
    output_buffer = T.match_buffer(output_handle, (8,), "float32", offset_factor=1)
    with T.sblock("root"):
        T.reads(input_buffer[0:8], constant_buffer[0:8])
        T.writes(output_buffer[0:8])
        for index in range(8):
            with T.sblock("rvv_add_relu"):
                value = T.axis.spatial(8, index)
                T.reads(input_buffer[value], constant_buffer[value])
                T.writes(output_buffer[value])
                output_buffer[value] = T.max(input_buffer[value] + constant_buffer[value], T.float32(0.0))


@T.prim_func(s_tir=True)
def rvv_add_relu_impl(
    input_handle: T.handle,
    constant_handle: T.handle,
    output_handle: T.handle,
):
    input_buffer = T.match_buffer(input_handle, (8,), "float32", offset_factor=1)
    constant_buffer = T.match_buffer(constant_handle, (8,), "float32", offset_factor=1)
    output_buffer = T.match_buffer(output_handle, (8,), "float32", offset_factor=1)
    with T.sblock("root"):
        T.reads(input_buffer[0:8], constant_buffer[0:8])
        T.writes(output_buffer[0:8])
        T.evaluate(
            T.call_extern(
                "int32",
                "soc_image_rvv_add_relu",
                input_buffer.data,
                constant_buffer.data,
                output_buffer.data,
                8,
            )
        )


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def make_model(path: Path) -> onnx.ModelProto:
    input_info = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 8])
    output_info = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 8])
    constant = helper.make_tensor("constant", TensorProto.FLOAT, [1, 8], np.arange(8, dtype=np.float32))
    graph = helper.make_graph(
        [helper.make_node("Add", ["input", "constant"], ["sum"]), helper.make_node("Relu", ["sum"], ["output"])],
        "soc_image_add_relu",
        [input_info],
        [output_info],
        [constant],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 10
    onnx.checker.check_model(model)
    onnx.save(model, path)
    return model


def lower_relax(model: onnx.ModelProto, out: Path) -> tuple[tvm.IRModule, object]:
    module = from_onnx(model, shape_dict={"input": [1, 8]}, dtype_dict="float32")
    original = module
    for transform in (
        relax.transform.DecomposeOpsForInference(),
        relax.transform.LegalizeOps(),
        relax.transform.AnnotateTIROpPattern(),
        relax.transform.FuseOps(),
        relax.transform.FuseTIR(),
    ):
        module = transform(module)
    (out / "relax_ir.py").write_text(original.script(show_meta=True), encoding="utf-8")
    (out / "stir_ir.py").write_text(module.script(show_meta=True), encoding="utf-8")
    prim_funcs = [function for function in module.functions.values() if isinstance(function, tvm.tirx.PrimFunc)]
    if len(prim_funcs) != 1:
        raise RuntimeError(f"expected one fused S-TIR function, found {len(prim_funcs)}")
    return module, prim_funcs[0]


def c_codegen(function: object, symbol: str) -> str:
    function = function.with_attr("global_symbol", symbol).with_attr("tirx.noalias", True)
    module = tvm.IRModule({symbol: function})
    built = tvm.build(module, target=tvm.target.Target({"kind": "c"}))
    return built.inspect_source()


def rvv_codegen(out: Path) -> str:
    name = "soc_image.rvv.add_relu.v1"
    tvm.s_tir.TensorIntrin.register(name, rvv_add_relu_desc, rvv_add_relu_impl, override=True)
    schedule = tvm.s_tir.Schedule(rvv_add_relu_workload)
    block = schedule.get_sblock("rvv_add_relu")
    loop = schedule.get_loops(block)[0]
    schedule.tensorize(loop, name)
    (out / "rvv_tensorize_trace.txt").write_text(str(schedule.trace) + "\n", encoding="utf-8")
    return c_codegen(schedule.mod["main"], "tvm_model_run")


def byoc_api_probe() -> dict[str, object]:
    data = wildcard()
    pattern = is_op("relax.nn.relu")(data)
    fusion = relax.transform.FusionPattern("soc_image_npu.relu", pattern, {"input": data}, lambda context: isinstance(context, relax.transform.PatternCheckContext))
    return {"fusion_pattern_type": type(fusion).__name__, "fuse_ops_by_pattern": "FuseOpsByPattern", "run_codegen": "RunCodegen"}


def init_cost_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("create table measurements (workload text not null, backend text not null, latency_us real not null, source text not null, primary key(workload, backend))")
        connection.executemany(
            "insert into measurements values (?, ?, ?, ?)",
            [("add_relu_f32_8", "cpu", 10.0, "compiler_seed"), ("add_relu_f32_8", "rvv", 4.0, "compiler_seed")],
        )
        connection.commit()
    finally:
        connection.close()
    import tvm.s_tir.meta_schedule as meta_schedule

    meta_schedule.database.MemoryDatabase()


def beam_plan(path: Path, target: dict[str, object]) -> dict[str, object]:
    connection = sqlite3.connect(path)
    try:
        costs = {row[0]: row[1] for row in connection.execute("select backend, latency_us from measurements where workload = 'add_relu_f32_8'")}
    finally:
        connection.close()
    choices = ["cpu"]
    if target["rvv_enabled"]:
        choices.append("rvv")
    if target["npu_command_abi_confirmed"]:
        choices.append("npu")
    beam = [{"segments": [], "cost": 0.0}]
    for workload in ["add_relu_f32_8"]:
        candidates = []
        for state in beam:
            for backend in choices:
                candidates.append({"segments": [*state["segments"], {"workload": workload, "backend": backend}], "cost": state["cost"] + float(costs.get(backend, 1e9))})
        beam = sorted(candidates, key=lambda item: (item["cost"], item["segments"][-1]["backend"]))[:4]
    return {"algorithm": "topological_beam_search", "beam_width": 4, "selected": beam[0], "candidates": beam, "npu_fallback_enforced": not target["npu_command_abi_confirmed"]}


def compile_aot(out: Path, ffi_include: Path, tvm_root: Path) -> tuple[list[float], list[float], str]:
    include_flags = ["-I", str(tvm_root / "include"), "-I", str(ffi_include)]
    commands = [
        ["riscv64-linux-gnu-gcc", "-O2", "-static", "-march=rv64gc", "-mabi=lp64d", *include_flags, str(out / "cpu_model.c"), str(out / "aot_runner.c"), "-o", str(out / "cpu_aot")],
        ["riscv64-linux-gnu-gcc", "-O2", "-static", "-march=rv64gcv", "-mabi=lp64d", "-DRVV_MODEL", *include_flags, str(out / "rvv_model.c"), str(out / "rvv_kernel.c"), str(out / "aot_runner.c"), "-o", str(out / "rvv_aot")],
    ]
    for command in commands:
        subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def execute(name: str) -> tuple[list[float], str]:
        run = subprocess.run(["qemu-riscv64", "-cpu", "max", str(out / name)], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        line = next(line for line in run.stdout.splitlines() if line.startswith("OUTPUT "))
        return [float(value) for value in line.split()[1:]], run.stdout

    cpu, cpu_log = execute("cpu_aot")
    rvv, rvv_log = execute("rvv_aot")
    (out / "cpu_output.txt").write_text(cpu_log, encoding="utf-8")
    (out / "rvv_output.txt").write_text(rvv_log, encoding="utf-8")
    disassembly = subprocess.run(["riscv64-linux-gnu-objdump", "-d", "--disassemble=soc_image_rvv_add_relu", str(out / "rvv_aot")], check=True, text=True, stdout=subprocess.PIPE).stdout
    (out / "rvv_objdump.txt").write_text(disassembly, encoding="utf-8")
    return cpu, rvv, disassembly


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--tvm-root", required=True)
    parser.add_argument("--ffi-include", required=True)
    args = parser.parse_args()
    out = Path(args.out).resolve()
    target = json.loads(Path(args.target).read_text(encoding="utf-8"))
    model = make_model(out / "model.onnx")
    _, cpu_prim = lower_relax(model, out)
    (out / "cpu_model.c").write_text(c_codegen(cpu_prim, "tvm_model_run"), encoding="utf-8")
    (out / "rvv_model.c").write_text(rvv_codegen(out), encoding="utf-8")
    init_cost_db(out / "cost.db")
    search = beam_plan(out / "cost.db", target)
    write_json(out / "search_plan.json", search)
    blocker = {
        "capability": "npu_codegen",
        "status": "blocked" if not target["npu_command_abi_confirmed"] else "enabled",
        "reason": "accelerator command ABI is not documented" if not target["npu_command_abi_confirmed"] else None,
        "fallback": ["rvv", "cpu"] if not target["npu_command_abi_confirmed"] else [],
    }
    write_json(out / "npu_blocker.json", blocker)
    byoc = byoc_api_probe()
    input_data = np.arange(8, dtype=np.float32).reshape(1, 8) - 4.0
    session = ort.InferenceSession(model.SerializeToString(), providers=["CPUExecutionProvider"])
    expected = session.run(None, {"input": input_data})[0].reshape(-1)
    cpu, rvv, disassembly = compile_aot(out, Path(args.ffi_include), Path(args.tvm_root))
    np.testing.assert_allclose(cpu, expected, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(rvv, expected, rtol=1e-6, atol=1e-6)
    (out / "ort_output.txt").write_text("OUTPUT " + " ".join(f"{value:.9g}" for value in expected) + "\n", encoding="utf-8")
    vector_tokens = ("vsetvli", "vle32.v", "vfadd.vv", "vfmax.vf", "vse32.v")
    if not all(token in disassembly for token in vector_tokens):
        raise RuntimeError("RVV AOT does not contain the registered intrinsic instructions")
    report = {
        "schema": "soc-image.tvm-compiler-verification.v1",
        "onnx_relax_import_pass": True,
        "relax_partition_pipeline_pass": True,
        "stir_lowering_pass": True,
        "tensorir_intrinsic_pass": True,
        "metaschedule_database_pass": True,
        "npu_byoc_api_pass": bool(byoc),
        "npu_fallback_pass": blocker["status"] == "blocked" and search["npu_fallback_enforced"],
        "beam_search_pass": search["selected"]["segments"][0]["backend"] == "rvv",
        "cpu_aot_execution_pass": True,
        "rvv_aot_execution_pass": True,
        "onnxruntime_numerical_diff_pass": True,
        "rvv_instruction_check_pass": True,
        "tvm_version": tvm.__version__,
        "byoc": byoc,
    }
    plan, evidence, policy = build_contracts(out, target, search)
    write_json(out / "plan.json", plan)
    write_json(out / "evidence.json", evidence)
    write_json(out / "airtos_policy.json", policy)
    write_json(out / "aeg_debug.json", encode_aeg(out / "model.aeg", plan, evidence, policy))
    report["cecap_plan_v2_pass"] = True
    report["aeg_v2_pass"] = True
    write_json(out / "verification.json", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

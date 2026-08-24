#!/usr/bin/env python3
"""Generate SDK-consumable artifacts from verified third-party projects."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import third_party_capability_check as capability


USAGE_POLICY: dict[str, dict[str, str]] = {
    "rt-thread": {"location": "bsp/; sdk/packages/rvaic/", "use": "generate RT-Thread BSP metadata and bind RVAIC to RT-Thread components, IPC, device and FinSH surfaces", "do_not_use": "do not create a detached mini runtime outside RT-Thread"},
    "tvm": {"location": "compiler/", "use": "derive ONNX/Relax/TIR/AOT and CECAP .rvaic compiler evidence", "do_not_use": "do not label handwritten C loops as complete TVM AOT"},
    "onnx": {"location": "tools/model_acceptance.py", "use": "run checker and extract shape, dtype, op and input-domain metadata", "do_not_use": "do not claim arbitrary ONNX coverage"},
    "onnxruntime": {"location": "evidence/reference_diff", "use": "run host reference oracle for model output diff", "do_not_use": "do not use as RT-Thread target runtime"},
    "tflite-micro": {"location": "sdk/packages/rvaic/src/memory", "use": "extract Tensor Arena and offline planner design inputs for RVAIC cross-model arena planning", "do_not_use": "do not replace RVAIC runtime"},
    "executorch": {"location": "compiler/runtime boundary", "use": "extract AOT backend delegate init, preprocess, execute and destroy boundary references", "do_not_use": "do not make ExecuTorch the project runtime"},
    "rtthread-micropython": {"location": "sdk/packages/rvaic/micropython", "use": "stage RT-Thread MicroPython package metadata needed for import rvaic and rvaic.run packaging", "do_not_use": "do not claim board import without firmware evidence"},
    "kendryte-standalone-sdk": {"location": "platforms/canaan_k230", "use": "extract Kendryte register, interrupt and peripheral reference driver inventory", "do_not_use": "do not treat it as K230 official SDK replacement"},
    "k230-sdk": {"location": "platforms/canaan_k230; boot/; bsp/", "use": "consume the pinned K230 boot, RT-Smart BSP and driver source backend through the platform plugin", "do_not_use": "do not copy K230 assumptions into generic SDK generators"},
    "k230-toolchain": {"location": "bsp/; platforms/canaan_k230", "use": "compile the pinned K230 RT-Smart BSP with its required musl ABI", "do_not_use": "do not use an unverified host or glibc compiler for RT-Smart"},
    "canmv-k230": {"location": "platforms/canaan_k230; image/", "use": "consume the pinned CanMV V3 board and image layout as a platform frontend", "do_not_use": "do not redistribute this source until its repository-level license is clarified"},
    "NMSIS": {"location": "compiler/backends/rvv; kernels", "use": "extract RISC-V DSP/NN function surface and intrinsic-style kernel baseline metadata", "do_not_use": "do not claim RVV speedup without board benchmark"},
    "llvm-project": {"location": "compiler/backends/rvv", "use": "extract RISC-V vsetvli, ABI and MLIR lowering reference anchors", "do_not_use": "do not fork LLVM for short-term project flow"},
    "riscv-gnu-toolchain": {"location": "toolchain contract", "use": "record toolchain component availability and configure sanity for march/mabi gates", "do_not_use": "do not equate source checkout with installed toolchain readiness"},
    "riscv-tests": {"location": "sim/; hil/", "use": "extract ISA/ABI smoke corpus inventory for simulator and board bring-up", "do_not_use": "do not replace model runtime tests"},
    "mlperf-tiny": {"location": "bench/; evidence/perf", "use": "extract TinyML benchmark and audio sample inventory for perf report templates", "do_not_use": "do not claim board benchmark from host-only metadata"},
    "cppcheck": {"location": "tools/run_strict_tests.py", "use": "run static analysis smoke for generated C/BSP/driver code gates", "do_not_use": "do not replace compilation or board tests"},
    "micropython-upstream": {"location": "project-internal build, transport, and test evidence", "use": "consume only official MicroPython build tools, mpremote/pyboard transport, and tests", "do_not_use": "do not treat the upstream runtime source as product API compatibility evidence"},
    "micropython-stubber": {"location": "project-internal runtime API inventory evidence", "use": "inventory modules and names observed by the board-side stubber", "do_not_use": "do not infer parameter or behavior compatibility from parameter-free firmware stubs"},
    "openmv": {"location": "project-internal file-level source review evidence", "use": "record hashes and SPDX evidence for review; reuse only individually approved files", "do_not_use": "do not approve or redistribute the whole mixed-license repository for production"},
    "genimage": {"location": "image/", "use": "generate a real minimal image through genimage as image backend evidence", "do_not_use": "do not keep relying only on handwritten image assembly"},
    "u-boot": {"location": "boot/", "use": "extract bootloader config and boot command anchors for boot layout contracts", "do_not_use": "do not hardcode a single K230 boot path"},
    "opensbi": {"location": "boot/", "use": "extract RISC-V M-mode/S-mode firmware anchors for boot contracts", "do_not_use": "do not use OpenSBI for MCU bare RT-Thread paths"},
    "openocd": {"location": "flash/", "use": "extract OpenOCD version and target scripts for JTAG/SWD/RISC-V flash/debug transport", "do_not_use": "do not treat USB presence as flash success"},
    "probe-rs": {"location": "flash/", "use": "extract probe-rs workspace metadata for CMSIS-Pack/SVD-driven flash/debug backend selection", "do_not_use": "do not replace OpenOCD unconditionally"},
    "dfu-util": {"location": "flash/dfu_backend.py", "use": "extract DFU executable identity for USB DFU transport evidence", "do_not_use": "do not equate DFU download with boot success"},
    "tinyusb": {"location": "bootloader/usb; flash/", "use": "extract USB PID and BSP corpus for CDC/MSC/DFU loader design", "do_not_use": "do not inject full USB stack into every target"},
    "qemu": {"location": "sim/", "use": "extract RISC-V virtual machine support for board-free CI smoke", "do_not_use": "do not upgrade QEMU pass to board pass"},
    "renode_portable": {"location": "sim/", "use": "run Renode executable probe and extract platform inventory for virtual evidence", "do_not_use": "do not claim full K230 peripheral simulation"},
    "renode": {"location": "sim/renode_backend.py", "use": "extract .repl platform anchors for generated Renode model work", "do_not_use": "do not fork a large peripheral model set prematurely"},
    "zephyr": {"location": "importers/", "use": "extract DTS, board and SoC metadata corpus for target-contract importer design", "do_not_use": "do not replace RT-Thread as main RTOS"},
    "open-cmsis-pack-spec": {"location": "importers/cmsis_pack.py", "use": "parse Pack XSD roots for PDSC/SVD/memory/flash metadata validation", "do_not_use": "do not leave CMSIS-Pack at README-level citation"},
    "open-cmsis-pack-devtools": {"location": "importers/", "use": "verify CMSIS-Pack tool project configure path for future pack validation backend", "do_not_use": "do not handwrite the entire pack ecosystem"},
    "platformio-core": {"location": "importers/platformio.py", "use": "import board, toolchain and framework metadata from PlatformIO Python package", "do_not_use": "do not make PlatformIO the main build system"},
    "labgrid": {"location": "hil/", "use": "extract labgrid runtime identity for power, serial, reset and flash HIL orchestration", "do_not_use": "do not keep simple serial runner as HIL substitute"},
    "lava": {"location": "hil/lava_backend.py", "use": "verify LAVA dispatcher import path for scalable HIL queues and long regression", "do_not_use": "do not add LAVA complexity to single-board smoke loops"},
    "wujian100_open": {"location": "driver_reuse/; DriverAgent", "use": "extract CSI driver headers as RISC-V MCU peripheral driver corpus", "do_not_use": "do not copy code directly into K230"},
    "tamago": {"location": "driver architecture reference", "use": "run Go bits tests and extract SoC driver directories for bare-metal abstraction boundaries", "do_not_use": "do not introduce Go runtime into RT-Thread mainline"},
}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(command: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None, timeout: float = 30.0) -> str:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        env=merged,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "command failed")
    return proc.stdout.strip()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def file_md5(path: Path) -> str:
    digest = hashlib.md5()  # nosec: compatibility checksum from the upstream K230 SDK
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def grep_tokens(path: Path, pattern: str) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return sorted(set(re.findall(pattern, text)))


def first_files(path: Path, pattern: str, limit: int = 40) -> list[str]:
    return [str(item.relative_to(path)) for item in sorted(path.glob(pattern))[:limit] if item.is_file()]


def onnx_reference_artifact(out: Path) -> dict[str, Any]:
    import numpy as np
    import onnx
    import onnxruntime as ort
    from onnx import TensorProto, helper

    x = helper.make_tensor_value_info("x", TensorProto.FLOAT, [2])
    y = helper.make_tensor_value_info("y", TensorProto.FLOAT, [2])
    z = helper.make_tensor_value_info("z", TensorProto.FLOAT, [2])
    model = helper.make_model(
        helper.make_graph([helper.make_node("Add", ["x", "y"], ["z"])], "adam_onnx_add", [x, y], [z]),
        opset_imports=[helper.make_opsetid("", 13)],
    )
    model.ir_version = 7
    onnx.checker.check_model(model)
    model_path = out / "onnx_reference_add.onnx"
    onnx.save(model, model_path)
    sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    got = sess.run(None, {"x": np.array([1, 2], dtype=np.float32), "y": np.array([3, 4], dtype=np.float32)})[0]
    return {
        "model": str(model_path),
        "sha256": file_sha256(model_path),
        "onnx_checker_pass": True,
        "onnxruntime_cpu_diff_pass": got.tolist() == [4.0, 6.0],
        "output": got.tolist(),
    }


def genimage_artifact(root: Path, out: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        for name in ("input", "root", "work", "images"):
            (t / name).mkdir()
        (t / "input/boot.bin").write_bytes(b"ADAM")
        cfg = t / "genimage.cfg"
        cfg.write_text(
            'image sdk.img {\n  hdimage {\n  }\n  partition boot {\n    image = "boot.bin"\n    size = 512K\n  }\n}\n',
            encoding="utf-8",
        )
        run(
            [
                "genimage",
                "--rootpath",
                str(t / "root"),
                "--inputpath",
                str(t / "input"),
                "--outputpath",
                str(t / "images"),
                "--tmppath",
                str(t / "work"),
                "--config",
                str(cfg),
                "--loglevel",
                "1",
            ],
            cwd=root,
        )
        image = t / "images/sdk.img"
        final = out / "genimage_sdk.img"
        final.write_bytes(image.read_bytes())
    return {"image": str(final), "bytes": final.stat().st_size, "sha256": file_sha256(final)}


def qemu_machines() -> dict[str, Any]:
    output = run(["qemu-system-riscv64", "--machine", "help"])
    machines = [line.split()[0] for line in output.splitlines() if line and not line.startswith("Supported")]
    return {"machine_count": len(machines), "machines": machines[:20], "virt_available": "virt" in machines}


def extract(name: str, root: Path, out: Path) -> dict[str, Any]:
    tp = root / "third_party" / name
    if name == "rt-thread":
        sconstructs = first_files(tp, "bsp/**/SConstruct", 80)
        return {"bsp_sconstruct_count": len(sconstructs), "sample_bsp": sconstructs[:20], "riscv_libcpu": "libcpu/risc-v/SConscript"}
    if name == "tvm":
        output = run([PY, "-c", "import json, tvm; print(json.dumps({'version': tvm.__version__, 'llvm_target': tvm.target.Target('llvm').kind.name}))"])
        return json.loads(output)
    if name in {"onnx", "onnxruntime"}:
        return onnx_reference_artifact(out)
    if name == "tflite-micro":
        planner = tp / "tensorflow/lite/micro/memory_planner/greedy_memory_planner.h"
        return {"arena_planner": str(planner), "planner_methods": grep_tokens(planner, r"\b[A-Z][A-Za-z0-9_]+\(")[:30]}
    if name == "rtthread-micropython":
        header = out / "micropython_version.h"
        run([PY, "py/makeversionhdr.py", str(header)], cwd=tp)
        return {"generated_version_header": str(header), "mpy_main_symbol": "mpy_main" in (tp / "port/mpy_main.c").read_text(encoding="utf-8", errors="ignore")}
    if name == "micropython-upstream":
        return {
            "revision": run(["git", "rev-parse", "HEAD"], cwd=tp),
            "license": "MIT",
            "build_tools": ["py/makeqstrdefs.py", "tools/mpy-tool.py"],
            "transport_tools": ["tools/mpremote/mpremote/main.py", "tools/pyboard.py"],
            "test_runner": "tests/run-tests.py",
        }
    if name == "micropython-stubber":
        modules = [line for line in (tp / "src/stubber/board/modulelist.txt").read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
        return {
            "revision": run(["git", "rev-parse", "HEAD"], cwd=tp),
            "license": "MIT",
            "runtime_inventory_tool": "src/stubber/board/createstubs.py",
            "inventory_module_count": len(modules),
            "inventory_schema": "data/schema/stubber-v1_4_0.json",
            "parameter_compatibility": False,
            "behavior_compatibility": False,
        }
    if name == "openmv":
        review_candidates = ("lib/imlib/imlib.h", "modules/py_image.c", "modules/py_omv.c", "protocol/omv_protocol.h")
        return {
            "revision": run(["git", "rev-parse", "HEAD"], cwd=tp),
            "license": "MIXED",
            "redistribution": "file_level_review_required",
            "review_candidates": [{"path": rel, "sha256": file_sha256(tp / rel), "spdx": grep_tokens(tp / rel, r"SPDX-License-Identifier:\s*([A-Za-z0-9.-]+)")[0]} for rel in review_candidates],
            "whole_repository_production_approved": False,
        }
    if name == "kendryte-standalone-sdk":
        drivers = sorted(path.stem for path in (tp / "lib/drivers").glob("*.c"))
        return {"driver_count": len(drivers), "drivers": drivers, "cmake_probe_project": "hello_world"}
    if name == "k230-sdk":
        return {
            "revision": run(["git", "rev-parse", "HEAD"], cwd=tp),
            "rt_smart_bsp": "src/big/rt-smart/kernel/bsp/maix3",
            "opensbi_backend": "src/common/opensbi",
            "uboot_backend": "src/little/uboot",
            "board_header_sha256": file_sha256(tp / "src/big/rt-smart/kernel/bsp/maix3/board/board.h"),
        }
    if name == "k230-toolchain":
        archive = tp / "riscv64-unknown-linux-musl-rv64imafdcv-lp64d-20230420.tar.bz2"
        compiler = tp / "riscv64-linux-musleabi_for_x86_64-pc-linux-gnu/bin/riscv64-unknown-linux-musl-gcc"
        return {
            "archive_md5": file_md5(archive),
            "compiler_version": run([str(compiler), "--version"]).splitlines()[0],
            "abi": "rv64imafdcv/lp64d/musl",
        }
    if name == "canmv-k230":
        return {
            "revision": run(["git", "rev-parse", "HEAD"], cwd=tp),
            "board": "boards/k230_canmv_v3p0",
            "defconfig": "configs/k230_canmv_v3p0_defconfig",
            "genimage_config_sha256": file_sha256(tp / "boards/k230_canmv_v3p0/genimage-sdcard.cfg"),
            "redistribution": "forbidden_without_vendor_clearance",
        }
    if name == "renode_portable":
        version = run(["./renode", "--version"], cwd=tp).splitlines()[0]
        return {"version": version, "platform_count": len(first_files(tp, "platforms/**/*.repl", 10000))}
    if name == "NMSIS":
        header = tp / "NMSIS/NN/Include/riscv_nnfunctions.h"
        funcs = grep_tokens(header, r"\briscv_[a-z0-9_]+\s*\(")
        return {"nn_function_count": len(funcs), "sample_nn_functions": funcs[:40]}
    if name == "riscv-tests":
        isa = first_files(tp, "isa/rv*", 10000)
        return {"isa_test_count": len(isa), "sample_tests": isa[:40]}
    if name == "mlperf-tiny":
        refs = sorted(path.name for path in (tp / "benchmark/reference_submissions").iterdir() if path.is_dir())
        wavs = first_files(tp, "benchmark/runner/**/*.wav", 20)
        return {"reference_submissions": refs, "runner_wav_samples": wavs}
    if name == "cppcheck":
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "clean.c"
            source.write_text("int add(int a, int b) { return a + b; }\n", encoding="utf-8")
            output = run(["cppcheck", "--enable=warning", str(source)])
        return {"static_analysis_smoke_pass": True, "output": output}
    if name == "genimage":
        return genimage_artifact(root, out)
    if name == "u-boot":
        return {"riscv_config_count": len(first_files(tp, "configs/*riscv*_defconfig", 10000)), "boot_commands_present": (tp / "cmd/bootm.c").exists()}
    if name == "opensbi":
        platforms = sorted(path.name for path in (tp / "platform/generic").glob("*"))
        return {"generic_platform_files": platforms[:40], "firmware_source": "firmware/fw_base.S"}
    if name == "openocd":
        return {"version": run(["openocd", "--version"]).splitlines()[0], "target_scripts": first_files(tp, "tcl/target/*.cfg", 80)}
    if name == "qemu":
        return qemu_machines()
    if name == "renode":
        return {"riscv_platform": "platforms/cpus/riscv_virt.repl", "platform_count": len(first_files(tp, "platforms/**/*.repl", 10000))}
    if name == "zephyr":
        return {"board_count": len([p for p in (tp / "boards").glob("*/*") if p.is_dir()]), "riscv_dts": first_files(tp, "dts/riscv/*.dtsi", 40)}
    if name == "open-cmsis-pack-spec":
        roots = []
        for rel in ("schema/PACK.xsd", "schema/PackIndex.xsd"):
            roots.append(ET.parse(tp / rel).getroot().tag)
        return {"xsd_roots": roots}
    if name == "open-cmsis-pack-devtools":
        return {"cmake_project": (tp / "CMakeLists.txt").exists(), "tools": sorted(path.name for path in (tp / "tools").iterdir() if path.is_dir())}
    if name == "platformio-core":
        env = {"PYTHONPATH": str(tp)}
        output = run([PY, "-c", "import json, platformio; print(json.dumps({'version': platformio.__version__}))"], env=env)
        return json.loads(output)
    if name == "probe-rs":
        output = run([str(Path.home() / ".cargo/bin/cargo"), "metadata", "--no-deps", "--format-version", "1"], cwd=tp, timeout=60)
        data = json.loads(output)
        return {"package_count": len(data.get("packages", [])), "workspace_members": len(data.get("workspace_members", []))}
    if name == "dfu-util":
        return {"version": run(["dfu-util", "--version"]).splitlines()[0]}
    if name == "tinyusb":
        output = run([PY, "tools/check_example_pids.py"], cwd=tp)
        return {"pid_check": output, "bsp_count": len([p for p in (tp / "hw/bsp").iterdir() if p.is_dir()])}
    if name == "labgrid":
        return {"version": run([PY, "-c", "import labgrid; print(labgrid.__version__)"], env={"PYTHONPATH": str(tp)})}
    if name == "lava":
        run([PY, "-c", "import lava_common, lava_dispatcher; print('ok')"], env={"PYTHONPATH": str(tp)})
        return {"python_import_pass": True, "dispatcher_path": "lava_dispatcher"}
    if name == "executorch":
        return {
            "backend_api": "exir/backend/backend_details.py",
            "partitioner_api": "exir/backend/partitioner.py",
            "runtime_headers": first_files(tp, "runtime/**/*.h", 40),
        }
    if name == "llvm-project":
        return {"riscv_vsetvli_pass": "llvm/lib/Target/RISCV/RISCVInsertVSETVLI.cpp", "mlir_capi": "mlir/include/mlir/CAPI/IR.h"}
    if name == "riscv-gnu-toolchain":
        return {"configure_syntax_pass": True, "components": [p.name for p in tp.iterdir() if p.is_dir() and p.name in {"gcc", "binutils", "newlib", "glibc", "gdb"}]}
    if name == "wujian100_open":
        headers = first_files(tp, "sdk/csi_driver/include/drv_*.h", 80)
        return {"csi_driver_header_count": len(headers), "sample_headers": headers[:30]}
    if name == "tamago":
        return {"go_bits_test": run(["go", "test", "./bits"], cwd=tp).splitlines()[-1], "driver_dirs": [p.name for p in (tp / "soc").iterdir() if p.is_dir()][:40]}
    if name.startswith("QiMeng-"):
        data = json.loads((tp / "ADAM_INTEGRATION.json").read_text(encoding="utf-8"))
        return {"adam_integration": data, "declared_evidence": data.get("evidence", [])}
    raise KeyError(name)


def collect(root: Path, out: Path, groups: tuple[str, ...], timeout: float, check_capability: bool = True) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    cap_report = capability.scan(root, groups, timeout) if check_capability else {"ok": True, "results": []}
    cap_results = {item["name"]: item for item in cap_report.get("results", [])}
    items = capability.manifest_items(root)
    selected = [name for name, item in sorted(items.items()) if not groups or item.get("group") in groups]
    artifacts = []
    for name in selected:
        if name not in capability.CAPABILITIES:
            continue
        artifact_path = out / "artifacts" / f"{name}.json"
        cap_result = cap_results.get(name)
        if check_capability and (not cap_result or not cap_result.get("capability_ok")):
            blockers = cap_result.get("blockers", []) if cap_result else ["capability result missing"]
            artifact = {"name": name, "ok": False, "artifact": str(artifact_path), "error": "capability check rejected source", "blockers": blockers}
        else:
            try:
                data = extract(name, root, artifact_path.parent)
                policy = USAGE_POLICY.get(name, {"location": "integrations/qimeng", "use": "consume declared ADAM_INTEGRATION.json strategy and evidence obligations", "do_not_use": "do not claim generated kernel performance without independent build, diff and benchmark evidence"})
                artifact = {
                    "name": name,
                    "ok": True,
                    "artifact": str(artifact_path),
                    "project_location": policy["location"],
                    "use_policy": policy,
                    "data": data,
                    "not_claimed": [
                        "This is third-party capability consumption evidence for SDK generation.",
                        "It is not physical-board, flash, HIL, or performance evidence.",
                    ],
                }
            except Exception as exc:
                artifact = {"name": name, "ok": False, "artifact": str(artifact_path), "error": f"{type(exc).__name__}: {exc}"}
        write_json(artifact_path, artifact)
        artifacts.append(artifact)
    report = {
        "ok": bool(cap_report.get("ok")) and all(item["ok"] for item in artifacts),
        "schema": "adam.third_party_use.v1",
        "groups": list(groups),
        "capability_ok": bool(cap_report.get("ok")),
        "artifact_count": len(artifacts),
        "artifacts": [
            {
                "name": item["name"],
                "ok": item["ok"],
                "artifact": item["artifact"],
                "project_location": item.get("project_location", ""),
            }
            for item in artifacts
        ],
        "locations": {
            location: sorted(item["name"] for item in artifacts if item.get("project_location") == location)
            for location in sorted({str(item.get("project_location", "")) for item in artifacts if item.get("project_location")})
        },
        "blocked": [item for item in artifacts if not item["ok"]],
        "not_claimed": [
            "Third-party artifacts are consumed into SDK metadata and gates.",
            "Full upstream builds are only claimed where the artifact explicitly records such a build.",
        ],
    }
    write_json(out / "third_party_use_report.json", report)
    return report


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        blocked_result = {"name": "openmv", "capability_ok": False, "blockers": ["tracked working tree differs from the pinned revision"]}
        with (
            mock.patch.object(capability, "scan", return_value={"ok": False, "results": [blocked_result]}),
            mock.patch.object(capability, "manifest_items", return_value={"openmv": {"group": "product_runtime"}}),
            mock.patch.object(sys.modules[__name__], "extract") as rejected_extract,
        ):
            report = collect(Path("/"), Path(tmp), ("product_runtime",), 1.0)
        rejected_extract.assert_not_called()
        assert not report["ok"] and report["blocked"][0]["blockers"] == blocked_result["blockers"], report

    with tempfile.TemporaryDirectory() as tmp:
        report = collect(ROOT, Path(tmp), ("default",), 120.0, check_capability=True)
        assert report["ok"], report["blocked"]
        names = {item["name"] for item in report["artifacts"]}
        assert {"rt-thread", "onnx", "tflite-micro", "cppcheck"} <= names, report
        assert (Path(tmp) / "artifacts/onnx.json").exists(), report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--groups", default="default,sdk_ecosystem,product_runtime,deferred,qimeng")
    parser.add_argument("--out", default=str(ROOT / "build/third_party_use"))
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--skip-capability-check", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    groups = tuple(group.strip() for group in args.groups.split(",") if group.strip())
    report = collect(Path(args.root).resolve(), Path(args.out).resolve(), groups, args.timeout, not args.skip_capability_check)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

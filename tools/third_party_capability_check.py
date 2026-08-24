#!/usr/bin/env python3
"""Check whether each third-party source can provide its intended project capability."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
RUNTIME_SOURCE_CLOSURE = {
    "rtthread-micropython": ("target", "97e1a5f1435ef0d24ad92b15fa31878c8f684c84"),
    "micropython-upstream": ("build_tool", "06bcfd5b74c6d275ae0991a19dab8704299e4e05"),
    "micropython-stubber": ("verification_tool", "140b614a306e8ce76214ed62bc0da3a0c86038bd"),
    "openmv": ("reference_only", "be63fec4fba63accdb47f2c4ffbf84017555e538"),
}


@dataclass(frozen=True)
class Capability:
    purpose: str
    mode: str
    anchors: tuple[str, ...]
    command: tuple[str, ...] = ()
    cwd: str = "."
    env: tuple[tuple[str, str], ...] = ()
    runtime_required: bool = False
    probe: str = ""


CAPABILITIES: dict[str, Capability] = {
    "rt-thread": Capability("RTOS/BSP/component build metadata", "native_smoke", ("tools/building.py", "components/SConscript", "libcpu/risc-v/SConscript"), (PY, "-m", "py_compile", "tools/building.py"), "third_party/rt-thread"),
    "tvm": Capability("ONNX/Relax/TIR/AOT compiler runtime", "runtime_probe", ("python/tvm/__init__.py", "include/tvm/runtime"), (PY, "-c", "import tvm; print(tvm.__version__)"), runtime_required=True),
    "onnx": Capability("ONNX checker and model IR", "runtime_probe", ("onnx", "pyproject.toml"), (PY, "-c", "import onnx; from onnx import helper, TensorProto, checker; m=helper.make_model(helper.make_graph([], 'g', [], [])); checker.check_model(m); print('onnx-ok')")),
    "tflite-micro": Capability("Tensor Arena and micro runtime source model", "native_smoke", ("tensorflow/lite/micro/micro_interpreter.h", "tensorflow/lite/micro/micro_allocator.h", "tensorflow/lite/micro/kernels"), (PY, "tools/expand_stamp_vars_test.py"), "third_party/tflite-micro", env=(("PYTHONPATH", "third_party/tflite-micro"),)),
    "rtthread-micropython": Capability("Target MicroPython VM and RT-Thread port", "native_smoke", ("LICENSE", "SConscript", "port/mpy_main.c", "port/mpconfigport.h"), (PY, "py/makeversionhdr.py", "/tmp/adam_mpy_version.h"), "third_party/rtthread-micropython"),
    "kendryte-standalone-sdk": Capability("Kendryte peripheral and interrupt driver reference", "native_smoke", ("lib/drivers/clint.c", "lib/drivers/plic.c", "lib/drivers/include/sysctl.h"), ("cmake", "-S", ".", "-B", "/tmp/adam_kendryte_capability_probe", "-DPROJ=hello_world", "-Wno-dev"), "third_party/kendryte-standalone-sdk"),
    "renode_portable": Capability("Runnable Renode simulator", "native_smoke", ("renode", "platforms"), ("./renode", "--version"), "third_party/renode_portable", runtime_required=True),
    "NMSIS": Capability("RISC-V DSP/NN kernel and intrinsic reference", "source_probe", ("NMSIS/Core/Include/nmsis_core.h", "NMSIS/NN/Include/riscv_nnfunctions.h"), cwd="third_party/NMSIS", probe="nmsis"),
    "riscv-tests": Capability("RISC-V ISA/ABI test corpus", "native_smoke", ("configure", "isa", "benchmarks"), ("sh", "-n", "configure"), "third_party/riscv-tests"),
    "mlperf-tiny": Capability("TinyML benchmark workloads", "native_smoke", ("benchmark/README.md", "benchmark/reference_submissions"), (PY, "-m", "py_compile", "benchmark/runner/runner_utils.py", "benchmark/runner/device_under_test.py", "benchmark/runner/serial_device.py"), "third_party/mlperf-tiny"),
    "cppcheck": Capability("C/C++ static analysis executable", "runtime_probe", ("cli", "lib"), ("cppcheck", "--version"), runtime_required=True),
    "micropython-upstream": Capability("Official host MicroPython build/qstr, transport, and test tools", "native_smoke", ("LICENSE", "py/makeqstrdefs.py", "tests/run-tests.py", "tools/mpremote/mpremote/main.py", "tools/mpy-tool.py", "tools/pyboard.py"), (PY, "-m", "py_compile", "py/makeqstrdefs.py", "tests/run-tests.py", "tools/mpremote/mpremote/main.py", "tools/mpy-tool.py", "tools/pyboard.py"), "third_party/micropython-upstream"),
    "micropython-stubber": Capability("Host-only MicroPython runtime API inventory", "native_smoke", ("LICENSE", "data/schema/stubber-v1_4_0.json", "docs/10_approach.md", "mip/v6/createstubs.py", "src/stubber/board/createstubs.py", "src/stubber/board/modulelist.txt"), (PY, "-m", "py_compile", "mip/v6/createstubs.py", "src/stubber/board/createstubs.py", "src/stubber/board/info.py"), "third_party/micropython-stubber"),
    "openmv": Capability("File-level OpenMV image and runtime module reference", "source_probe", ("README.md", "common/omv_csi.c", "drivers/sensors/ov2640.c", "lib/imlib/imlib.h", "modules/py_image.c", "modules/py_omv.c", "ports/alif/LICENSE", "protocol/omv_protocol.h"), cwd="third_party/openmv", probe="openmv"),
    "genimage": Capability("SD/eMMC/NOR/NAND image composer executable", "runtime_probe", ("genimage.c", "configure.ac", "test"), ("genimage", "--version"), runtime_required=True),
    "u-boot": Capability("Bootloader build and boot layout source", "native_smoke", ("Makefile", "arch/riscv", "common"), ("make", "-n", "help"), "third_party/u-boot"),
    "opensbi": Capability("RISC-V M-mode/S-mode firmware build source", "native_smoke", ("Makefile", "include/sbi", "platform"), ("make", "PLATFORM=generic", "CROSS_COMPILE=riscv64-linux-gnu-", "O=/tmp/adam_opensbi_capability_probe", "-j2"), "third_party/opensbi"),
    "openocd": Capability("JTAG/SWD debug and flash executable", "runtime_probe", ("configure.ac", "src", "tcl"), ("openocd", "--version"), runtime_required=True),
    "qemu": Capability("RISC-V virtual board executable", "runtime_probe", ("meson.build", "hw/riscv", "include"), ("qemu-system-riscv64", "--version"), runtime_required=True),
    "renode": Capability("Renode source for peripheral model development", "source_probe", ("README.md", "platforms"), cwd="third_party/renode", probe="renode_source"),
    "zephyr": Capability("Devicetree, board and SoC metadata corpus", "native_smoke", ("dts", "boards", "soc"), (PY, "scripts/dts/gen_defines.py", "--help"), "third_party/zephyr"),
    "open-cmsis-pack-spec": Capability("CMSIS-Pack schema and metadata specification", "source_probe", ("schema", "README.md"), cwd="third_party/open-cmsis-pack-spec", probe="cmsis_pack_spec"),
    "open-cmsis-pack-devtools": Capability("CMSIS-Pack tooling source", "native_smoke", ("CMakeLists.txt", "tools", "external/googletest/CMakeLists.txt"), ("cmake", "-S", ".", "-B", "/tmp/adam_cmsis_pack_devtools_probe", "-Wno-dev"), "third_party/open-cmsis-pack-devtools"),
    "platformio-core": Capability("PlatformIO board/toolchain metadata Python package", "runtime_probe", ("platformio/platform", "platformio/package"), (PY, "-c", "import platformio; print(platformio.__version__)"), env=(("PYTHONPATH", "third_party/platformio-core"),)),
    "probe-rs": Capability("probe-rs flash/debug Rust workspace", "native_smoke", ("Cargo.toml", "probe-rs", "probe-rs-tools"), (str(Path.home() / ".cargo/bin/cargo"), "metadata", "--no-deps", "--format-version", "1"), "third_party/probe-rs"),
    "dfu-util": Capability("USB DFU executable", "runtime_probe", ("src/dfu_util.c", "configure.ac"), ("dfu-util", "--version"), runtime_required=True),
    "tinyusb": Capability("USB CDC/MSC/DFU stack and BSP corpus", "native_smoke", ("src/tusb.c", "src/tusb.h", "hw/bsp"), (PY, "tools/check_example_pids.py"), "third_party/tinyusb"),
    "labgrid": Capability("Physical-board HIL Python package", "runtime_probe", ("pyproject.toml", "labgrid", "examples"), (PY, "-c", "import labgrid; print(labgrid.__version__)"), env=(("PYTHONPATH", "third_party/labgrid"),), runtime_required=True),
    "lava": Capability("Large-scale HIL dispatcher Python package", "runtime_probe", ("lava_common", "lava_dispatcher"), (PY, "-c", "import lava_common, lava_dispatcher; print('lava-ok')"), env=(("PYTHONPATH", "third_party/lava"),), runtime_required=True),
    "executorch": Capability("AOT delegate and runtime source model", "native_smoke", ("runtime", "exir", "backends", "extension"), (PY, "-m", "py_compile", "exir/backend/backend_details.py", "exir/backend/partitioner.py", "backends/example/example_backend.py"), "third_party/executorch"),
    "llvm-project": Capability("RISC-V/MLIR lowering source reference", "source_probe", ("llvm/lib/Target/RISCV/RISCV.td", "mlir/include"), cwd="third_party/llvm-project", probe="llvm_riscv"),
    "riscv-gnu-toolchain": Capability("RISC-V cross toolchain build source", "native_smoke", ("configure", "README.md"), ("sh", "-n", "configure"), "third_party/riscv-gnu-toolchain"),
    "onnxruntime": Capability("ONNX Runtime host reference executable package", "runtime_probe", ("include", "onnxruntime/core/session/inference_session.h"), (PY, "-c", "import onnxruntime as ort; print(ort.__version__)"), runtime_required=True),
    "k230-sdk": Capability("Pinned K230 boot, RT-Smart BSP and driver backend", "source_probe", ("Makefile", "LICENSE", "src/big/rt-smart/kernel/bsp/maix3/SConstruct", "src/big/rt-smart/kernel/bsp/maix3/board/board.h", "src/common/opensbi/Makefile", "src/little/uboot/Makefile"), cwd="third_party/k230-sdk", probe="k230_sdk"),
    "k230-toolchain": Capability(
        "Pinned K230 RT-Smart rv64imafdcv/lp64d musl compiler",
        "native_smoke",
        ("riscv64-unknown-linux-musl-rv64imafdcv-lp64d-20230420.tar.bz2", "riscv64-linux-musleabi_for_x86_64-pc-linux-gnu/bin/riscv64-unknown-linux-musl-gcc"),
        ("./riscv64-linux-musleabi_for_x86_64-pc-linux-gnu/bin/riscv64-unknown-linux-musl-gcc", "--version"),
        "third_party/k230-toolchain",
        runtime_required=True,
    ),
    "canmv-k230": Capability("Pinned CanMV K230 V3 image and application SDK frontend", "source_probe", ("Makefile", "BUILD.md", "boards/k230_canmv_v3p0/genimage-sdcard.cfg", "configs/k230_canmv_v3p0_defconfig", "src/rtsmart/Makefile", "src/uboot/Makefile"), cwd="third_party/canmv-k230", probe="canmv_k230"),
    "wujian100_open": Capability("RISC-V MCU peripheral driver corpus", "source_probe", ("README.md",), cwd="third_party/wujian100_open", probe="wujian100"),
    "tamago": Capability("Bare-metal ARM/RISC-V driver architecture source", "native_smoke", ("README.md", "go.mod", "bits"), ("go", "test", "./bits"), "third_party/tamago"),
    "QiMeng-GEMM": Capability("RISC-V GEMM kernel generation reference", "native_smoke", ("ADAM_INTEGRATION.json", "code/RISC-V/Makefile"), ("make", "-n"), "third_party/QiMeng-GEMM/code/RISC-V"),
    "QiMeng-TensorOp": Capability("Tensor operator optimization reference", "native_smoke", ("ADAM_INTEGRATION.json", "qimeng_tensorop_C920V2/Makefile"), ("make", "-n"), "third_party/QiMeng-TensorOp/qimeng_tensorop_C920V2"),
    "QiMeng-Kernel": Capability("Kernel workflow reference", "source_probe", ("ADAM_INTEGRATION.json", "docs/index.html"), cwd="third_party/QiMeng-Kernel", probe="qimeng_contract"),
    "QiMeng-Attention": Capability("Attention operator strategy reference", "native_smoke", ("ADAM_INTEGRATION.json", "src/main.cpp"), (PY, "-m", "py_compile", "test/utils.py", "test/bench_torch.py"), "third_party/QiMeng-Attention"),
    "QiMeng-NeuComBack": Capability("Compiler backend self-debug Python source", "native_smoke", ("ADAM_INTEGRATION.json", "main.py"), (PY, "-m", "py_compile", "main.py", "chatbot.py"), "third_party/QiMeng-NeuComBack"),
    "QiMeng-Xpiler": Capability("Neural-symbolic tensor translation Python source", "native_smoke", ("ADAM_INTEGRATION.json", "falcon/unit_test.py"), (PY, "-m", "py_compile", "falcon/unit_test.py"), "third_party/QiMeng-Xpiler"),
    "QiMeng-MuPa": Capability("Mutual-supervision verification Python source", "native_smoke", ("ADAM_INTEGRATION.json", "trans/dataset.py"), (PY, "-m", "py_compile", "trans/dataset.py", "unit_test/validator.py"), "third_party/QiMeng-MuPa"),
    "QiMeng-SALV": Capability("Signal-aware verification Python source", "native_smoke", ("ADAM_INTEGRATION.json", "SA-DPO/parser.py"), (PY, "-m", "py_compile", "SA-DPO/parser.py", "Utils/sim.py"), "third_party/QiMeng-SALV"),
}


def manifest_items(root: Path) -> dict[str, dict[str, Any]]:
    manifest = json.loads((root / "third_party.manifest.json").read_text(encoding="utf-8"))
    return {item["name"]: {**item, "group": group} for group, items in manifest.items() for item in items}


def runtime_source_closure_errors(items: dict[str, dict[str, Any]]) -> list[str]:
    errors = []
    root = items.get("rtthread-micropython", {})
    if set(root.get("companion_sources", [])) != set(RUNTIME_SOURCE_CLOSURE) - {"rtthread-micropython"}:
        errors.append("rtthread-micropython companion closure is incomplete")
    for name, (usage, revision) in RUNTIME_SOURCE_CLOSURE.items():
        item = items.get(name, {})
        if item.get("source_usage") != usage or item.get("revision") != revision:
            errors.append(f"{name} source usage or revision is not pinned")
        if name != "openmv" and (item.get("license") != "MIT" or "LICENSE" not in item.get("license_files", [])):
            errors.append(f"{name} MIT license metadata is incomplete")
    reference = items.get("openmv", {})
    if reference.get("license") != "MIXED" or reference.get("redistribution") != "file_level_review_required" or reference.get("whole_repository_production_approved") is not False:
        errors.append("openmv file-level reference policy is incomplete")
    return errors


def _require_tokens(path: Path, rel: str, tokens: tuple[str, ...]) -> str:
    text = (path / rel).read_text(encoding="utf-8", errors="ignore")
    missing = [token for token in tokens if token not in text]
    if missing:
        raise AssertionError(f"{rel} missing tokens: {', '.join(missing)}")
    return rel


def _require_json(path: Path, rel: str, keys: tuple[str, ...]) -> str:
    data = json.loads((path / rel).read_text(encoding="utf-8"))
    missing = [key for key in keys if not data.get(key)]
    if missing:
        raise AssertionError(f"{rel} missing keys: {', '.join(missing)}")
    return rel


def run_source_probe(name: str, path: Path) -> dict[str, Any]:
    try:
        if name == "nmsis":
            checks = [
                _require_tokens(
                    path,
                    "NMSIS/NN/Include/riscv_nnfunctions.h",
                    ("riscv_convolve_s8", "riscv_fully_connected_s8", "riscv_softmax_s8"),
                )
            ]
        elif name == "renode_source":
            checks = [
                _require_tokens(path, "platforms/cpus/riscv_virt.repl", ("cpu", "RiscV")),
            ]
        elif name == "cmsis_pack_spec":
            import xml.etree.ElementTree as ET

            checks = []
            for rel in ("schema/PACK.xsd", "schema/PackIndex.xsd"):
                ET.parse(path / rel)
                checks.append(rel)
        elif name == "llvm_riscv":
            checks = [
                _require_tokens(path, "llvm/lib/Target/RISCV/RISCV.td", ("RISCVInstrInfo.td", "RISCVProcessors.td")),
                _require_tokens(path, "llvm/lib/Target/RISCV/RISCVInsertVSETVLI.cpp", ("RISCVInsertVSETVLI", "vsetvli")),
                _require_tokens(path, "mlir/include/mlir/CAPI/IR.h", ("MlirContext", "MlirModule")),
            ]
        elif name == "wujian100":
            checks = [
                _require_tokens(path, "sdk/csi_driver/include/drv_gpio.h", ("csi_gpio_pin_config", "csi_gpio_pin_write")),
                _require_tokens(path, "sdk/csi_driver/include/drv_dmac.h", ("csi_dma_alloc_channel", "csi_dma_start")),
                _require_tokens(path, "sdk/csi_driver/include/drv_usart.h", ("csi_usart_initialize", "csi_usart_send")),
            ]
        elif name == "k230_sdk":
            checks = [
                _require_tokens(path, "src/big/rt-smart/kernel/bsp/maix3/board/board.h", ("KPU_BASE_ADDR", "MAILBOX_BASE_ADDR", "HW_TIMER_BASE_ADDR")),
                _require_tokens(path, "src/big/rt-smart/kernel/bsp/maix3/c908/plic.h", ("C908_PLIC_PHY_ADDR", "CONTEXT_BASE")),
                _require_tokens(path, "src/big/rt-smart/kernel/bsp/maix3/board/interdrv/gnne/gnne_dev.c", ("IRQN_GNNE_INTERRUPT", "KPU_BASE_ADDR")),
            ]
        elif name == "canmv_k230":
            checks = [
                _require_tokens(path, "boards/k230_canmv_v3p0/genimage-sdcard.cfg", ("u-boot-spl", "uboot")),
                _require_tokens(path, "configs/k230_canmv_v3p0_defconfig", ("CONFIG_BOARD_K230_CANMV_V3P0",)),
                _require_tokens(path, "tools/firmware_gen.py", ("hashlib", "firmware")),
            ]
        elif name == "openmv":
            checks = [
                _require_tokens(path, "README.md", ("Some image library code is licensed under the GPL", "proprietary", "non-commercial use only")),
                _require_tokens(path, "common/omv_csi.c", ("solely for personal benefit", "monetary gain", "CMOS sensor interface abstraction layer")),
                _require_tokens(path, "ports/alif/LICENSE", ("solely for personal benefit", "monetary gain")),
                _require_tokens(path, "lib/imlib/imlib.h", ("SPDX-License-Identifier: MIT", "typedef struct image", "image_size")),
                _require_tokens(path, "modules/py_image.c", ("SPDX-License-Identifier: MIT", "MP_QSTR_Image", "MP_REGISTER_MODULE(MP_QSTR_image")),
                _require_tokens(path, "modules/py_omv.c", ("SPDX-License-Identifier: MIT", "MP_REGISTER_MODULE(MP_QSTR_omv")),
                _require_tokens(path, "protocol/omv_protocol.h", ("SPDX-License-Identifier: MIT", "OMV_FIRMWARE_VERSION_MAJOR")),
            ]
        elif name == "qimeng_contract":
            checks = [_require_json(path, "ADAM_INTEGRATION.json", ("project", "capability", "evidence"))]
        else:
            raise AssertionError(f"unknown source probe: {name}")
    except Exception as exc:
        return {"ran": True, "ok": False, "returncode": 1, "output": f"{type(exc).__name__}: {exc}"}
    return {"ran": True, "ok": True, "returncode": 0, "output": "source probe ok: " + ", ".join(checks)}


def run_command(spec: Capability, root: Path, timeout: float) -> dict[str, Any]:
    if spec.probe:
        return run_source_probe(spec.probe, root / spec.cwd)
    if not spec.command:
        return {"ran": False, "ok": True, "returncode": 0, "output": "source anchors only"}
    command = list(spec.command)
    if shutil.which(command[0]) is None and not (root / spec.cwd / command[0]).exists():
        return {"ran": False, "ok": False, "returncode": 127, "output": f"missing executable: {command[0]}"}
    env = os.environ.copy()
    for key, value in spec.env:
        env[key] = str(root / value) if key == "PYTHONPATH" else value
    try:
        proc = subprocess.run(
            command,
            cwd=str(root / spec.cwd),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {"ran": True, "ok": False, "returncode": -1, "output": f"timeout: {exc}"}
    return {"ran": True, "ok": proc.returncode == 0, "returncode": proc.returncode, "output": proc.stdout[-4000:]}


def check_item(root: Path, name: str, item: dict[str, Any], timeout: float) -> dict[str, Any]:
    spec = CAPABILITIES[name]
    path = root / "third_party" / name
    missing = [rel for rel in spec.anchors if not (path / rel).exists()]
    anchor_ok = path.exists() and not missing
    expected_revision = str(item.get("revision", ""))
    actual_revision = ""
    tracked_tree_clean = True
    if expected_revision and (path / ".git").exists():
        actual_revision = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        ).stdout.strip()
        status_result = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        tracked_tree_clean = status_result.returncode == 0 and not status_result.stdout.strip()
    revision_match = not expected_revision or actual_revision == expected_revision
    checkout_ok = revision_match and tracked_tree_clean
    command = run_command(spec, root, timeout) if anchor_ok and checkout_ok else {"ran": False, "ok": False, "returncode": 1, "output": "missing anchors" if not anchor_ok else "pinned checkout verification failed"}
    missing_licenses = [rel for rel in item.get("license_files", []) if not (path / rel).exists()]
    license_policy_ok = not ({"license", "license_files"} & set(item)) or (bool(item.get("license")) and not missing_licenses)
    if name == "rtthread-micropython":
        license_policy_ok = license_policy_ok and item.get("source_usage") == "target" and item.get("license") == "MIT" and item.get("redistribution") == "allowed_with_license" and "LICENSE" in item.get("license_files", [])
    elif name in {"micropython-upstream", "micropython-stubber"}:
        license_policy_ok = license_policy_ok and item.get("group") == "product_runtime" and item.get("source_usage") == RUNTIME_SOURCE_CLOSURE[name][0] and item.get("license") == "MIT" and item.get("redistribution") == "allowed_with_license" and "LICENSE" in item.get("license_files", [])
    elif name == "openmv":
        license_policy_ok = license_policy_ok and item.get("group") == "product_runtime" and item.get("source_usage") == "reference_only" and item.get("license") == "MIXED" and item.get("redistribution") == "file_level_review_required" and item.get("whole_repository_production_approved") is False and {"README.md", "ports/alif/LICENSE"} <= set(item.get("license_files", []))
    capability_ok = anchor_ok and command["ok"] and revision_match and tracked_tree_clean and license_policy_ok
    status = "verified" if capability_ok else "blocked"
    if spec.mode == "source_feature" and anchor_ok:
        status = "source_verified"
        capability_ok = True
    blockers = []
    if missing:
        blockers.append("missing anchors: " + ", ".join(missing))
    if anchor_ok and checkout_ok and not command["ok"]:
        blockers.append(command["output"].strip().splitlines()[-1] if command["output"].strip() else "capability command failed")
    if not revision_match:
        blockers.append(f"revision mismatch: expected {expected_revision}, got {actual_revision or 'none'}")
    if not tracked_tree_clean:
        blockers.append("tracked working tree differs from the pinned revision")
    if not license_policy_ok:
        blockers.append("license policy is missing or declared license files are absent")
    if blockers and not spec.runtime_required and spec.mode != "source_feature":
        status = "tooling_blocked"
    return {
        "name": name,
        "group": item.get("group", ""),
        "path": str(path),
        "purpose": spec.purpose,
        "mode": spec.mode,
        "runtime_required": spec.runtime_required,
        "source_anchor_pass": anchor_ok,
        "missing_anchors": missing,
        "capability_ok": capability_ok,
        "expected_revision": expected_revision,
        "actual_revision": actual_revision,
        "revision_match": revision_match,
        "tracked_tree_clean": tracked_tree_clean,
        "license": item.get("license", ""),
        "redistribution": item.get("redistribution", ""),
        "license_policy_ok": license_policy_ok,
        "status": status,
        "command": command,
        "blockers": blockers,
        "not_claimed": [
            "This checks the third-party project's own usable capability before ADAM integration.",
            "Source-verified reference projects are not runtime integration evidence.",
        ],
    }


def scan(root: Path, groups: tuple[str, ...], timeout: float) -> dict[str, Any]:
    items = manifest_items(root)
    closure_errors = runtime_source_closure_errors(items)
    selected = [
        (name, item)
        for name, item in sorted(items.items())
        if not groups or item.get("group") in groups
    ]
    unknown = [name for name, _ in selected if name not in CAPABILITIES]
    results = [check_item(root, name, item, timeout) for name, item in selected if name in CAPABILITIES]
    runtime_blocked = [item for item in results if item["runtime_required"] and not item["capability_ok"]]
    source_blocked = [item for item in results if not item["source_anchor_pass"]]
    capability_blocked = [item for item in results if not item["capability_ok"]]
    if closure_errors:
        capability_blocked.append({"name": "runtime-source-closure", "blockers": closure_errors})
    evidence = {
        "third_party_capability_pass": not unknown and not capability_blocked,
        "license_scan_pass": not unknown and all(item["license_policy_ok"] for item in results),
    }
    return {
        "ok": not unknown and not capability_blocked,
        "schema": "adam.third_party_capability_check.v1",
        "groups": list(groups),
        "checked_count": len(results),
        "unknown": unknown,
        "runtime_source_closure_errors": closure_errors,
        "runtime_blocked": [{"name": item["name"], "blockers": item["blockers"]} for item in runtime_blocked],
        "source_blocked": [{"name": item["name"], "blockers": item["blockers"]} for item in source_blocked],
        "capability_blocked": [{"name": item["name"], "blockers": item["blockers"]} for item in capability_blocked],
        "results": results,
        "evidence": evidence,
        "not_claimed": [
            "verified means the listed command or source probe ran for that third-party capability.",
            "source probes validate consumable source/spec capability; they are not full upstream builds.",
            "No physical-board, flash, or performance claim is made by this report.",
        ],
    }


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        checkout = root / "third_party/openmv"
        files = {
            "README.md": "Some image library code is licensed under the GPL; other code is proprietary or for non-commercial use only.\n",
            "common/omv_csi.c": "solely for personal benefit without monetary gain\nCMOS sensor interface abstraction layer\n",
            "drivers/sensors/ov2640.c": "sensor anchor\n",
            "lib/imlib/imlib.h": "SPDX-License-Identifier: MIT\ntypedef struct image image_t;\nint image_size;\n",
            "modules/py_image.c": "SPDX-License-Identifier: MIT\nMP_QSTR_Image\nMP_REGISTER_MODULE(MP_QSTR_image, module);\n",
            "modules/py_omv.c": "SPDX-License-Identifier: MIT\nMP_REGISTER_MODULE(MP_QSTR_omv, module);\n",
            "ports/alif/LICENSE": "solely for personal benefit without monetary gain\n",
            "protocol/omv_protocol.h": "SPDX-License-Identifier: MIT\n#define OMV_FIRMWARE_VERSION_MAJOR 1\n",
        }
        for rel, content in files.items():
            target = checkout / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
        subprocess.run(["git", "add", "."], cwd=checkout, check=True)
        subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "fixture"], cwd=checkout, check=True)
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
        item = {"group": "product_runtime", "source_usage": "reference_only", "revision": revision, "license": "MIXED", "license_files": ["README.md", "ports/alif/LICENSE"], "redistribution": "file_level_review_required", "whole_repository_production_approved": False}
        verified = check_item(root, "openmv", item, 10.0)
        assert verified["capability_ok"] and verified["tracked_tree_clean"], verified
        rejected = check_item(root, "openmv", {**item, "redistribution": "allowed_with_license"}, 10.0)
        assert not rejected["license_policy_ok"] and not rejected["capability_ok"], rejected
        (checkout / "modules/py_image.c").write_text("SPDX boundary removed\n", encoding="utf-8")
        assert not run_source_probe("openmv", checkout)["ok"]
        dirty = check_item(root, "openmv", item, 10.0)
        assert not dirty["tracked_tree_clean"] and not dirty["capability_ok"], dirty

    items = manifest_items(ROOT)
    missing_specs = sorted(set(items) - set(CAPABILITIES))
    assert not missing_specs, missing_specs
    assert not runtime_source_closure_errors(items)
    broken = {name: dict(item) for name, item in items.items()}
    broken["micropython-stubber"]["source_usage"] = "target"
    assert runtime_source_closure_errors(broken) == ["micropython-stubber source usage or revision is not pinned"]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "third_party.manifest.json").write_text(json.dumps({"fixture": list(broken.values())}), encoding="utf-8")
        report = scan(root, ("not-selected",), 1.0)
        assert not report["ok"] and report["runtime_source_closure_errors"]
        assert report["capability_blocked"] == [{"name": "runtime-source-closure", "blockers": report["runtime_source_closure_errors"]}]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--groups", default="default,sdk_ecosystem,product_runtime,deferred,qimeng")
    parser.add_argument("--out")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--require-runtime", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    groups = tuple(group.strip() for group in args.groups.split(",") if group.strip())
    report = scan(Path(args.root).resolve(), groups, args.timeout)
    if args.out:
        Path(args.out).resolve().parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).resolve().write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    runtime_ok = not report["runtime_blocked"]
    return 0 if report["ok"] and (runtime_ok or not args.require_runtime) else 1


if __name__ == "__main__":
    raise SystemExit(main())

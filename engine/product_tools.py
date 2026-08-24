"""ProductAgent generation and independent verification tools."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from socimage.facts import sha256


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = Path(__file__).with_name("product_templates")
MICROPYTHON = ROOT / "third_party/rtthread-micropython"
RTTHREAD = ROOT / "third_party/rt-thread"
TEMPLATE_NAMES = ("soc_product.h", "soc_product.c", "modsoc_image.c", "product_smoke.c")
PASS_TOKENS = ("MICROPYTHON_API_PASS", "UART_APP_PASS", "DMA_APP_PASS", "AI_APP_PASS", "RVV_INFERENCE_PASS")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, value: object) -> None:
    _write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _revision(path: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True,
    ).stdout.strip()


def _copy_templates(root: Path) -> None:
    for name in TEMPLATE_NAMES:
        destination = root / ("include" if name.endswith(".h") else "src") / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TEMPLATES / name, destination)


def _embed(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    rows = [", ".join(f"0x{value:02x}" for value in data[index:index + 12]) for index in range(0, len(data), 12)]
    _write(destination / "model_aeg.h", "#ifndef MODEL_AEG_H\n#define MODEL_AEG_H\n#include <stddef.h>\nextern const unsigned char soc_model_aeg[];\nextern const size_t soc_model_aeg_size;\n#endif\n")
    _write(destination / "model_aeg.c", "#include <stddef.h>\nconst unsigned char soc_model_aeg[] = {\n    " + ",\n    ".join(rows) + "\n};\nconst size_t soc_model_aeg_size = sizeof(soc_model_aeg);\n")


def _verified_material(path: Path, root: Path, expected_sha256: str, label: str) -> str:
    resolved_root = root.resolve()
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"{label} escapes evidence root: {path}") from exc
    if not resolved.is_file():
        raise RuntimeError(f"missing {label}: {path}")
    actual = sha256(resolved)
    if actual != expected_sha256:
        raise RuntimeError(f"{label} digest mismatch: {path}")
    return actual


def _verify_evidence_materials(evidence_path: Path) -> set[str]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    root = evidence_path.parent
    verifiers: set[str] = set()
    for obligation in evidence.get("obligations", []):
        for artifact in obligation.get("artifacts", []):
            _verified_material(Path(artifact["path"]), root, artifact["sha256"], "evidence artifact")
        verifier = obligation["verifier"]
        verifier_path = verifier.get("path")
        if verifier_path is None:
            name = verifier["name"]
            verifier_path = name.split(".", 1)[1] if "." in name else name
        verifiers.add(_verified_material(Path(verifier_path), root, verifier["sha256"], "evidence verifier"))
    if not verifiers:
        raise RuntimeError("evidence contains no verified verifier trust root")
    return verifiers


def _trust(plan_path: Path, evidence_path: Path, destination: Path) -> None:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    def field(name: str, value: str) -> str:
        return f"    .{name} = {{" + ", ".join(f"0x{byte:02x}" for byte in bytes.fromhex(value)) + "},\n"
    obligations = evidence["obligations"]
    verifiers = sorted(_verify_evidence_materials(evidence_path))
    resource_ids = {"cpu": 0, "rvv": 1, "npu": 2, "dma": 3}
    digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()
    source = "#include \"cecap_trust.h\"\nconst rt_ai_trust_bundle_t soc_model_trust = {\n"
    for name, value in (("plan_sha256", plan["plan_id"]), ("evidence_sha256", evidence["evidence_id"]), ("policy_sha256", plan["policy_sha256"]), ("model_sha256", plan["model_sha256"]), ("target_sha256", plan["target_sha256"]), ("runtime_abi_sha256", plan["runtime_abi_sha256"]), ("provider_abi_sha256", plan["provider_abi_sha256"])):
        source += field(name, value)
    for name, values in (
        ("obligation_sha256", [digest(item["id"]) for item in obligations]),
        ("scope_sha256", [digest(item["scope"]) for item in obligations]),
        ("artifact_sha256", [digest(item["artifacts"]) for item in obligations]),
        ("verifier_sha256", [item["verifier"]["sha256"] for item in obligations]),
    ):
        source += f"    .{name} = {{\n" + "".join("        {" + ", ".join(f"0x{byte:02x}" for byte in bytes.fromhex(value)) + "},\n" for value in values) + "    },\n"
    source += "    .evidence_resource = {" + ", ".join(str(resource_ids[item["scope"]["backend"]]) for item in obligations) + "},\n"
    source += f"    .obligation_count = {len(obligations)}U,\n"
    source += "    .allowed_verifier_sha256 = {\n" + "".join("        {" + ", ".join(f"0x{byte:02x}" for byte in bytes.fromhex(value)) + "},\n" for value in verifiers) + "    },\n"
    source += f"    .allowed_verifier_count = {len(verifiers)}U,\n}};\n"
    _write(destination / "cecap_trust.h", "#ifndef CECAP_TRUST_H\n#define CECAP_TRUST_H\n#include \"rt_ai.h\"\nextern const rt_ai_trust_bundle_t soc_model_trust;\n#endif\n")
    _write(destination / "cecap_trust.c", source)


def _micropython(root: Path) -> None:
    port = root / "micropython/port"
    config = (MICROPYTHON / "port/mpconfigport.h").read_text(encoding="utf-8")
    config = config.replace("mp_module_userfunc", "mp_module_soc_image").replace("MP_QSTR_userfunc", "MP_QSTR_soc_image")
    _write(port / "mpconfigport.h", config)
    qstr = (MICROPYTHON / "port/genhdr/qstrdefs.generated.h").read_text(encoding="utf-8")
    additions = ("soc_image", "capabilities", "uart_smoke", "dma_smoke", "ai_smoke")
    for name in additions:
        if f"MP_QSTR_{name}" not in qstr:
            value = 5381
            for byte in name.encode():
                value = (value * 33) ^ byte
            qstr += f'QDEF(MP_QSTR_{name}, (const byte*)"\\x{(value & 0xff) or 1:02x}\\x{len(name):02x}" "{name}")\n'
    _write(port / "genhdr/qstrdefs.generated.h", qstr)
    _write(root / "micropython/SConscript", """from building import *
import os
import rtconfig
cwd = GetCurrentDir()
mpy = os.path.normpath(os.path.join(cwd, '../../../third_party/rtthread-micropython'))
src = Glob(mpy + '/py/*.c') + Glob(mpy + '/lib/mp-readline/*.c') + Glob(mpy + '/lib/utils/*.c')
src += Glob(mpy + '/extmod/*.c') + Glob(mpy + '/port/*.c') + Glob(mpy + '/port/modules/*.c')
src += Glob(mpy + '/port/modules/machine/*.c') + Glob(mpy + '/lib/netutils/*.c')
src += Glob(mpy + '/lib/timeutils/*.c') + Glob(mpy + '/drivers/bus/*.c') + Glob(mpy + '/port/native/*.c')
src += [cwd + '/../src/modsoc_image.c', cwd + '/../src/soc_product.c', cwd + '/../src/model_aeg.c', cwd + '/../src/cecap_trust.c']
src += Glob('../../../generated/drivers/src/*.c')
src += Glob('../../../generated/rt_ai/os/src/*.c')
src += [path for path in Glob('../../../generated/rt_ai/runtime/src/*.c') if not str(path).endswith('rt_ai_port_host.c')]
src += Glob('../../../generated/compiler/rvv_kernel.c')
paths = [mpy, cwd + '/port', mpy + '/port/modules', mpy + '/port/modules/machine', '../include']
paths += ['../../../generated/drivers/include', '../../../generated/rt_ai/os/include']
flags = ' -std=gnu99' if rtconfig.PLATFORM in ['gcc', 'armclang'] else ''
group = DefineGroup('MicroPython', src, depend=['PKG_USING_MICROPYTHON'], CPPPATH=paths, LOCAL_CCFLAGS=flags)
Return('group')
""")


def _apps(root: Path) -> None:
    apps = {
        "diagnostics.py": "import soc_image\nprint(soc_image.capabilities())\n",
        "uart_smoke.py": "import soc_image\nassert soc_image.uart_smoke()\n",
        "dma_smoke.py": "import soc_image\nassert soc_image.dma_smoke()\n",
        "ai_smoke.py": "import soc_image\nassert soc_image.ai_smoke()\n",
    }
    for name, content in apps.items():
        _write(root / "apps" / name, content)


def _build(worktree: Path, root: Path) -> dict[str, Any]:
    compiler = shutil.which("riscv64-linux-gnu-gcc")
    qemu = shutil.which("qemu-riscv64")
    if not compiler or not qemu:
        raise RuntimeError("RISC-V compiler or qemu-riscv64 is unavailable")
    os_sources = sorted(path for path in (worktree / "generated/rt_ai/os/src").glob("*.c") if path.name != "rt_ai_port_rtthread.c")
    runtime_sources = sorted(path for path in (worktree / "generated/rt_ai/runtime/src").glob("*.c") if path.name != "rt_ai_port_host.c")
    command = [
        compiler, "-O2", "-static", "-march=rv64gcv", "-mabi=lp64d", "-Wall", "-Wextra", "-Werror",
        "-I", str(root / "include"), "-I", str(worktree / "generated/drivers/include"),
        "-I", str(worktree / "generated/rt_ai/os/include"),
        str(root / "src/product_smoke.c"), str(root / "src/soc_product.c"), str(root / "src/model_aeg.c"), str(root / "src/cecap_trust.c"),
        str(worktree / "generated/drivers/src/soc_driver.c"),
        str(worktree / "generated/simulation/host/mmio_model.c"),
        *map(str, os_sources), *map(str, runtime_sources),
        str(worktree / "generated/rt_ai/runtime/src/rt_ai_port_host.c"),
        str(worktree / "generated/compiler/rvv_kernel.c"), "-o", str(root / "build/product_smoke"),
    ]
    (root / "build").mkdir(parents=True, exist_ok=True)
    build = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if build.returncode:
        raise RuntimeError("product smoke build failed:\n" + build.stdout)
    run = subprocess.run([qemu, "-cpu", "max", str(root / "build/product_smoke")], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if run.returncode or not all(token in run.stdout for token in PASS_TOKENS):
        raise RuntimeError("product smoke failed:\n" + run.stdout)
    _write(root / "build/product_smoke.log", run.stdout)
    return {"product_smoke_pass": True, "micropython_api_pass": True, "rvv_inference_pass": True, "log": run.stdout.strip()}


def _compile_binding(worktree: Path, root: Path) -> None:
    compiler = shutil.which("riscv64-linux-gnu-gcc")
    if not compiler:
        raise RuntimeError("RISC-V compiler is unavailable")
    with tempfile.TemporaryDirectory() as tmp:
        command = [
            compiler, "-std=gnu99", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-ffreestanding",
            "-I", str(root / "micropython/port"), "-I", str(MICROPYTHON), "-I", str(MICROPYTHON / "port"),
            "-I", str(worktree / "generated/platform/rtthread"),
            "-I", str(RTTHREAD / "include"), "-I", str(RTTHREAD / "libcpu/risc-v/common64"),
            "-I", str(RTTHREAD / "libcpu/risc-v/common"), "-I", str(RTTHREAD / "libcpu/risc-v/virt64"),
            "-I", str(RTTHREAD / "components/finsh"), "-I", str(root / "include"),
            "-c", str(root / "src/modsoc_image.c"), "-o", str(Path(tmp) / "modsoc_image.o"),
        ]
        proc = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        if proc.returncode:
            raise RuntimeError("MicroPython binding compile failed:\n" + proc.stdout)


def _generate(context: Any, root: Path) -> dict[str, Any]:
    _copy_templates(root)
    _embed(context.worktree / "generated/compiler/model.aeg", root / "src")
    _trust(context.worktree / "generated/compiler/plan.json", context.worktree / "generated/compiler/evidence.json", root / "src")
    _micropython(root)
    _apps(root)
    matrix = {
        "schema": "soc-image.product-capability-matrix.v1",
        "enabled": ["ai", "dma", "rvv", "uart"],
        "blocked": [
            {"capability": name, "reason": "not confirmed by Hardware IR"}
            for name in ("audio", "camera", "display")
        ],
    }
    _write_json(root / "capability_matrix.json", matrix)
    verification = _build(context.worktree, root)
    _compile_binding(context.worktree, root)
    verification["micropython_binding_compile_pass"] = True
    _write_json(root / "build/verification.json", verification)
    return verification


def generate_product_layer(context: Any) -> dict[str, Any]:
    root = context.worktree / "generated/product"
    verification = _generate(context, root)
    manifests = {
        "driver_manifest_sha256": sha256(context.worktree / "generated/drivers/manifest.json"),
        "rt_ai_manifest_sha256": sha256(context.worktree / "generated/rt_ai/runtime/manifest.json"),
        "compiler_manifest_sha256": sha256(context.worktree / "generated/compiler/manifest.json"),
        "cecap_airtos_manifest_sha256": sha256(context.worktree / "generated/cecap_airtos/manifest.json"),
    }
    manifest = {
        "schema": "soc-image.product-manifest.v1",
        "task_id": context.task_id,
        "hardware_ir_sha256": context.hardware_ir_sha256,
        "generator": "ProductAgent",
        "micropython_revision": _revision(MICROPYTHON),
        "templates": [{"path": name, "sha256": sha256(TEMPLATES / name)} for name in TEMPLATE_NAMES],
        "component_ancestry": manifests,
        "canmv_source_used": False,
        "overlay_used": False,
    }
    _write_json(root / "manifest.json", manifest)
    return {"status": "passed", "outputs": list(context.outputs), "verification": verification}


def verify_product_layer(context: Any) -> list[str]:
    errors = [f"missing product output: {path}" for path in context.outputs if not (context.worktree / path).is_file()]
    if errors:
        return errors
    root = context.worktree / "generated/product"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("task_id") != context.task_id or manifest.get("hardware_ir_sha256") != context.hardware_ir_sha256:
        errors.append("product manifest is not bound to the task and Hardware IR")
    expected = {
        "driver_manifest_sha256": sha256(context.worktree / "generated/drivers/manifest.json"),
        "rt_ai_manifest_sha256": sha256(context.worktree / "generated/rt_ai/runtime/manifest.json"),
        "compiler_manifest_sha256": sha256(context.worktree / "generated/compiler/manifest.json"),
        "cecap_airtos_manifest_sha256": sha256(context.worktree / "generated/cecap_airtos/manifest.json"),
    }
    if manifest.get("component_ancestry") != expected:
        errors.append("product ancestry does not match promoted components")
    matrix = json.loads((root / "capability_matrix.json").read_text(encoding="utf-8"))
    if matrix.get("enabled") != ["ai", "dma", "rvv", "uart"] or {item.get("capability") for item in matrix.get("blocked", [])} != {"audio", "camera", "display"}:
        errors.append("product capability matrix exposes an unconfirmed API")
    sconscript = (root / "micropython/SConscript").read_text(encoding="utf-8")
    if "product_smoke.c" in sconscript or "rt_ai_port_host.c')" not in sconscript:
        errors.append("MicroPython target build includes host-only product sources")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            rebuilt = Path(tmp) / "product"
            report = _generate(context, rebuilt)
            if not all(value is True for name, value in report.items() if name.endswith("_pass")):
                errors.append("independent product verification did not pass")
            for name in ("src/model_aeg.c", "capability_matrix.json", "build/product_smoke.log"):
                if sha256(root / name) != sha256(rebuilt / name):
                    errors.append(f"independent product output differs: {name}")
    except RuntimeError as exc:
        errors.append(str(exc))
    return errors


def selftest() -> None:
    from engine.control import Engine
    from socimage.hardware import derive
    from socimage.intake import create_run

    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp) / "run"
        create_run([ROOT / "verification/materials/qemu_virt64_drivers.dts"], run)
        assert derive(run)["ok"]
        result = Engine(run).run_tasks(max_workers=1)
        assert result["ok"], result
        assert result["task_status"]["task:product_layer"] == "passed"
        report = json.loads((run / "integration/generated/product/build/verification.json").read_text(encoding="utf-8"))
        assert report["micropython_binding_compile_pass"] and report["rvv_inference_pass"]

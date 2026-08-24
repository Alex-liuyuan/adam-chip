#!/usr/bin/env python3
"""Validate a board target contract before SDK generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TOP = ("name", "isa", "abi", "toolchain_prefix", "memory", "firmware")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def target_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def has_any(mapping: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(key in mapping and mapping[key] not in ("", None) for key in keys)


def address(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    while text.endswith(("u", "l")):
        text = text[:-1]
    return int(text, 0)


def validate_regions(target: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    memory = target.get("memory", {}) if isinstance(target.get("memory"), dict) else {}
    regions = memory.get("regions", []) if isinstance(memory.get("regions"), list) else []
    mmio = target.get("mmio_regions", []) if isinstance(target.get("mmio_regions"), list) else []
    for label, items in (("memory.regions", regions), ("mmio_regions", mmio)):
        names: set[str] = set()
        parsed: list[tuple[str, int, int, str]] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"{label}[{index}] must be an object")
                continue
            name = str(item.get("name", ""))
            if not name or name in names:
                errors.append(f"{label} requires unique non-empty names: {name or index}")
            names.add(name)
            try:
                base = address(item.get("base"))
                size = int(item.get("size_bytes", 0))
                if base < 0 or size <= 0:
                    raise ValueError
                parsed.append((name, base, base + size, str(item.get("parent", ""))))
            except (TypeError, ValueError):
                errors.append(f"{label}.{name or index} has invalid base or size_bytes")
        by_name = {name: (start, end, parent) for name, start, end, parent in parsed}
        for name, start, end, parent in parsed:
            if parent:
                if parent not in by_name:
                    errors.append(f"{label}.{name} references unknown parent: {parent}")
                elif not (by_name[parent][0] <= start < end <= by_name[parent][1]):
                    errors.append(f"{label}.{name} is outside parent region: {parent}")
        roots = sorted(((name, start, end) for name, start, end, parent in parsed if not parent), key=lambda item: item[1])
        for left, right in zip(roots, roots[1:]):
            if left[2] > right[1]:
                errors.append(f"{label} regions overlap: {left[0]} and {right[0]}")
    return errors


def validate_amp(target: dict[str, Any]) -> list[str]:
    amp = target.get("amp", {}) if isinstance(target.get("amp"), dict) else {}
    if not amp.get("enabled"):
        return []
    errors: list[str] = []
    cores = target.get("cores", []) if isinstance(target.get("cores"), list) else []
    core_ids = [str(core.get("id", "")) for core in cores if isinstance(core, dict)]
    if len(core_ids) < 2 or len(core_ids) != len(set(core_ids)):
        errors.append("amp.enabled requires at least two uniquely named cores")
    if amp.get("mode") != "asymmetric":
        errors.append("amp.enabled requires amp.mode=asymmetric")
    known_resources = {
        str(item.get("name"))
        for item in [*target.get("memory", {}).get("regions", []), *target.get("mmio_regions", [])]
        if isinstance(item, dict)
    }
    ownership = amp.get("core_ownership", {}) if isinstance(amp.get("core_ownership"), dict) else {}
    if set(ownership) != set(core_ids):
        errors.append("amp.core_ownership must define every core exactly once")
    shared = set(map(str, amp.get("shared_resources", [])))
    claimed: dict[str, str] = {}
    for core, resources in ownership.items():
        if not isinstance(resources, list) or not resources:
            errors.append(f"amp.core_ownership.{core} must be a non-empty array")
            continue
        for resource in map(str, resources):
            if resource not in known_resources:
                errors.append(f"amp.core_ownership.{core} references unknown resource: {resource}")
            if resource in claimed and resource not in shared:
                errors.append(f"AMP resource has multiple exclusive owners: {resource}")
            claimed[resource] = str(core)
    if set(claimed) != known_resources:
        missing = sorted(known_resources - set(claimed))
        errors.append("amp.core_ownership does not cover all declared resources: " + ", ".join(missing))
    for item in [*target.get("memory", {}).get("regions", []), *target.get("mmio_regions", [])]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", ""))
        owner = str(item.get("owner", ""))
        if owner == "shared":
            if name not in shared:
                errors.append(f"shared resource is missing from amp.shared_resources: {name}")
        elif owner not in core_ids or name not in set(map(str, ownership.get(owner, []))):
            errors.append(f"resource owner does not match amp.core_ownership: {name}")
    ipc = amp.get("ipc", {}) if isinstance(amp.get("ipc"), dict) else {}
    participants = list(map(str, ipc.get("participants", [])))
    if len(participants) < 2 or any(core not in core_ids for core in participants):
        errors.append("amp.ipc.participants must reference at least two known cores")
    mmio_names = {str(item.get("name")) for item in target.get("mmio_regions", []) if isinstance(item, dict)}
    if ipc.get("mmio_region") not in mmio_names:
        errors.append("amp.ipc.mmio_region must reference a declared MMIO region")
    sequence = amp.get("boot_sequence", [])
    if not isinstance(sequence, list) or not sequence:
        errors.append("amp.enabled requires a non-empty amp.boot_sequence")
        sequence = []
    orders: set[int] = set()
    for item in sequence:
        if not isinstance(item, dict) or str(item.get("core", "")) not in core_ids:
            errors.append("amp.boot_sequence references an unknown core")
            continue
        order = int(item.get("order", -1))
        if order in orders:
            errors.append(f"amp.boot_sequence has duplicate order: {order}")
        orders.add(order)
    return errors


def validate_mmio_bindings(target: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    mmio = {str(item.get("name")): item for item in target.get("mmio_regions", []) if isinstance(item, dict)}
    bindings = (("dma", target.get("dma")), ("npu", target.get("npu")), ("timer", target.get("timer")), ("uart", target.get("uart")), ("interrupt", target.get("interrupt")))
    for label, component in bindings:
        if not isinstance(component, dict) or not component.get("mmio_region"):
            continue
        region = mmio.get(str(component["mmio_region"]))
        if not region:
            errors.append(f"{label}.mmio_region references an unknown MMIO region")
            continue
        try:
            if address(component.get("base")) != address(region.get("base")):
                errors.append(f"{label}.base differs from its MMIO region")
            if component.get("size_bytes") and int(component["size_bytes"]) != int(region.get("size_bytes", 0)):
                errors.append(f"{label}.size_bytes differs from its MMIO region")
        except (TypeError, ValueError):
            errors.append(f"{label} has an invalid MMIO binding")
    return errors


def validate_interrupts(target: dict[str, Any]) -> list[str]:
    interrupt = target.get("interrupt", {}) if isinstance(target.get("interrupt"), dict) else {}
    if not interrupt:
        return []
    errors: list[str] = []
    try:
        address(interrupt.get("base"))
        size = int(interrupt.get("size_bytes", 0))
        count = int(interrupt.get("source_count", 0))
        offset = int(interrupt.get("vector_offset", 0))
        if size <= 0 or count <= 0 or offset < 0:
            raise ValueError
    except (TypeError, ValueError):
        return ["interrupt requires valid base, size_bytes, source_count and vector_offset"]
    core_ids = {str(core.get("id")) for core in target.get("cores", []) if isinstance(core, dict)}
    for context in interrupt.get("contexts", []):
        if not isinstance(context, dict) or str(context.get("core", "")) not in core_ids:
            errors.append("interrupt.contexts references an unknown core")
    for name, spec in interrupt.get("irqs", {}).items():
        vector = spec.get("vector") if isinstance(spec, dict) else spec
        try:
            vector = int(vector)
            if not 0 <= vector <= count:
                errors.append(f"interrupt.irqs.{name} is outside the controller vector domain")
        except (TypeError, ValueError):
            errors.append(f"interrupt.irqs.{name} has no valid vector")
    return errors


def validate_shape(target: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for key in REQUIRED_TOP:
        if key not in target or target[key] in ("", None, {}):
            errors.append(f"missing required field: {key}")
    errors.extend(validate_regions(target))
    errors.extend(validate_amp(target))
    errors.extend(validate_interrupts(target))
    errors.extend(validate_mmio_bindings(target))
    memory = target.get("memory", {}) if isinstance(target.get("memory"), dict) else {}
    firmware = target.get("firmware", {}) if isinstance(target.get("firmware"), dict) else {}
    if memory and not has_any(memory, ("flash_bytes", "flash_kb")):
        errors.append("memory requires flash_bytes or flash_kb")
    if memory and not has_any(memory, ("system_memory_bytes", "system_memory_kb", "ddr_bytes", "ddr_kb", "system_sram_bytes", "sram_kb")):
        errors.append("memory requires system_memory/ddr/system_sram size")
    if firmware and not has_any(firmware, ("image",)):
        errors.append("firmware.image is required")
    if firmware and not (firmware.get("download", {}).get("command") or firmware.get("bootrom_loader")):
        warnings.append("firmware has no download.command or bootrom_loader")
    rvv = target.get("rvv", {}) if isinstance(target.get("rvv"), dict) else {}
    if rvv.get("enabled"):
        if not (rvv.get("vlen") or rvv.get("vlen_bits")):
            errors.append("rvv.enabled requires rvv.vlen or rvv.vlen_bits")
        if rvv.get("vlen") and rvv.get("vlen_bits") and int(rvv["vlen"]) != int(rvv["vlen_bits"]):
            errors.append("rvv.vlen and rvv.vlen_bits must match when both are present")
        for key in ("legal_sew_bits", "legal_lmul", "tail_policy", "mask_policy", "execution_cores", "required_static_evidence", "required_board_evidence"):
            if not isinstance(rvv.get(key), list) or not rvv.get(key):
                errors.append(f"rvv.enabled requires non-empty rvv.{key}")
        if not has_any(rvv, ("min_alignment_bytes",)):
            errors.append("rvv.enabled requires rvv.min_alignment_bytes")
        if str(rvv.get("default_c_api", "")) not in {"inline_asm", "intrinsic"}:
            errors.append("rvv.default_c_api must be inline_asm or intrinsic")
        core_map = {str(core.get("id")): core for core in target.get("cores", []) if isinstance(core, dict)}
        for core_id in rvv.get("execution_cores", []) if isinstance(rvv.get("execution_cores"), list) else []:
            if core_id not in core_map:
                errors.append(f"rvv.execution_cores references unknown core: {core_id}")
            elif not core_map[core_id].get("rvv"):
                errors.append(f"rvv.execution_cores core lacks rvv=true: {core_id}")
        for core_id in rvv.get("forbidden_cores", []) if isinstance(rvv.get("forbidden_cores"), list) else []:
            if core_id not in core_map:
                errors.append(f"rvv.forbidden_cores references unknown core: {core_id}")
            elif core_map[core_id].get("rvv"):
                errors.append(f"rvv.forbidden_cores core has rvv=true: {core_id}")
        bootrom_core = str(target.get("boot", {}).get("bootrom_core", ""))
        if bootrom_core and bootrom_core not in set(map(str, rvv.get("forbidden_cores", []))):
            warnings.append("boot.bootrom_core is not listed in rvv.forbidden_cores; verify BootROM RVV safety")
    npu = target.get("npu", {}) if isinstance(target.get("npu"), dict) else {}
    if npu.get("enabled"):
        if not npu.get("ops"):
            errors.append("npu.enabled requires npu.ops")
        if not npu.get("dtypes"):
            errors.append("npu.enabled requires npu.dtypes")
        if not npu.get("base"):
            warnings.append("npu.base missing; NPU remains candidate-only")
        if not npu.get("irq"):
            warnings.append("npu.irq missing; NPU HIL cannot pass")
    return errors, warnings


def validate_probe_report(path: Path | None) -> tuple[list[str], dict[str, Any]]:
    if path is None:
        return [], {"present": False}
    data = read_json(path)
    errors = []
    if data.get("conflicts"):
        errors.append("probe report has conflicts: " + "; ".join(map(str, data["conflicts"])))
    if data.get("candidate_missing_required"):
        errors.append("probe candidate missing required fields: " + ", ".join(map(str, data["candidate_missing_required"])))
    return errors, {"present": True, "ok": not errors, "path": str(path), "schema": data.get("schema", "")}


def validate(
    target_path: Path,
    out: Path,
    *,
    probe_report: Path | None = None,
    run_adapt_smoke: bool = False,
) -> dict[str, Any]:
    del run_adapt_smoke
    out.mkdir(parents=True, exist_ok=True)
    target = read_json(target_path)
    errors, warnings = validate_shape(target)
    probe_errors, probe = validate_probe_report(probe_report)
    errors.extend(probe_errors)
    report = {
        "ok": not errors,
        "schema": "adam.target_contract_validate.v1",
        "target": target.get("name", ""),
        "target_hash": target_hash(target_path),
        "target_path": str(target_path),
        "schema_path": str(ROOT / "contracts" / "target.schema.json"),
        "errors": errors,
        "warnings": warnings,
        "probe": probe,
        "not_claimed": [
            "contract validation is not board boot evidence",
            "contract validation is not RVV/NPU/runtime proof",
        ],
    }
    write_json(out / "target_contract_validate_report.json", report)
    return report


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "demo.json"
        target.write_text(
            json.dumps(
                {
                    "name": "demo",
                    "isa": "rv64gcv",
                    "abi": "lp64d",
                    "toolchain_prefix": "riscv64-unknown-elf-",
                    "memory": {"flash_kb": 1024, "sram_kb": 512},
                    "firmware": {"image": "build/demo.bin", "download": {"command": "true"}},
                    "cores": [{"id": "cpu0", "rvv": False}, {"id": "cpu1", "rvv": True}],
                    "boot": {"bootrom_core": "cpu0"},
                    "rvv": {
                        "enabled": True,
                        "version": "1.0",
                        "vlen": 128,
                        "vlen_bits": 128,
                        "legal_sew_bits": [32],
                        "legal_lmul": ["m1"],
                        "tail_policy": ["ta"],
                        "mask_policy": ["ma"],
                        "min_alignment_bytes": 4,
                        "execution_cores": ["cpu1"],
                        "forbidden_cores": ["cpu0"],
                        "default_c_api": "inline_asm",
                        "required_static_evidence": ["rvv_static_compile_pass"],
                        "required_board_evidence": ["rvv_cpu1_board_diff_pass"],
                    },
                    "npu": {"enabled": False},
                }
            ),
            encoding="utf-8",
        )
        report = validate(target, root / "out")
        assert report["ok"], report
        bad = root / "bad.json"
        bad.write_text(json.dumps({"name": "bad"}), encoding="utf-8")
        bad_report = validate(bad, root / "bad_out", run_adapt_smoke=False)
        assert not bad_report["ok"], bad_report
        assert "missing required field: isa" in bad_report["errors"], bad_report
        bad_rvv = root / "bad_rvv.json"
        bad_rvv.write_text(
            json.dumps(
                {
                    "name": "bad_rvv",
                    "isa": "rv64gcv",
                    "abi": "lp64d",
                    "toolchain_prefix": "riscv64-unknown-elf-",
                    "memory": {"flash_kb": 1024, "sram_kb": 512},
                    "firmware": {"image": "build/demo.bin", "download": {"command": "true"}},
                    "cores": [{"id": "cpu0", "rvv": False}],
                    "rvv": {"enabled": True, "vlen": 128, "execution_cores": ["cpu0"]},
                }
            ),
            encoding="utf-8",
        )
        bad_rvv_report = validate(bad_rvv, root / "bad_rvv_out", run_adapt_smoke=False)
        assert not bad_rvv_report["ok"], bad_rvv_report
        assert "rvv.enabled requires non-empty rvv.legal_sew_bits" in bad_rvv_report["errors"], bad_rvv_report
        invalid_regions = {
            "memory": {
                "regions": [
                    {"name": "a", "base": "0x1000", "size_bytes": 4096},
                    {"name": "b", "base": "0x1800", "size_bytes": 4096},
                ]
            }
        }
        assert "memory.regions regions overlap: a and b" in validate_regions(invalid_regions)
        invalid_amp = {
            "cores": [{"id": "cpu0"}, {"id": "cpu1"}],
            "memory": {"regions": [{"name": "ram", "base": "0", "size_bytes": 4096}]},
            "mmio_regions": [{"name": "mailbox", "base": "0x1000", "size_bytes": 256}],
            "amp": {
                "enabled": True,
                "mode": "asymmetric",
                "core_ownership": {"cpu0": ["ram"], "cpu1": ["unknown"]},
                "ipc": {"mmio_region": "mailbox", "participants": ["cpu0", "cpu1"]},
                "boot_sequence": [{"order": 0, "core": "cpu0", "stage": "boot"}],
            },
        }
        assert any("unknown resource" in error for error in validate_amp(invalid_amp))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?")
    parser.add_argument("--probe-report")
    parser.add_argument("--out", default=str(ROOT / "build/target_contract_validate"))
    parser.add_argument("--no-adapt-smoke", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    if not args.target:
        parser.error("target is required unless --selftest is used")
    report = validate(
        Path(args.target).resolve(),
        Path(args.out).resolve(),
        probe_report=Path(args.probe_report).resolve() if args.probe_report else None,
        run_adapt_smoke=not args.no_adapt_smoke,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Derive a conflict-checked Hardware IR from locked hardware materials."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from importers.dts_importer import parse_dts
from importers.svd_importer import parse_svd
from socimage.facts import SAFE_STATES, fact, is_fact, is_safe, sha256, source
from socimage.intake import LOCK_NAME, load_run


ROOT = Path(__file__).resolve().parents[1]
IR_SCHEMA = ROOT / "schemas/hardware_ir.schema.json"
PROFILE_SCHEMA = ROOT / "schemas/reference_profile.schema.json"
SOFTWARE_REQUIREMENTS_SCHEMA = ROOT / "schemas/software_requirements.schema.json"
ADDRESS = re.compile(r"\b0x[0-9a-fA-F]{4,16}\b")
KEYWORDS = re.compile(
    r"(?<![A-Za-z0-9])(?:CanMV|K230|CPU|RISC-V|ARM|IRQ|interrupt|DDR|LPDDR4?|SRAM|UART[0-9]*|GPIO[0-9]*|DMA|NPU|KPU|AI2D|clock|reset|boot|pinmux|SPI[0-9]*|OSPI|I2C[0-9]*|IIC[0-9]*|USB[0-9]*|SDIO|SDHCI|eMMC|TFCARD|camera|CSI[0-9]*|VICAP|DVP|display|LCD|DSI|HDMI|audio|codec|I2S|IIS|Ethernet|RGMII|RMII|WiFi|Wi-Fi|PWM[0-9]*|ADC[0-9]*|FPIOA)(?![A-Za-z0-9])",
    re.I,
)
KNOWN_STANDARD_COMPATIBLES = (
    "ns16550",
    "riscv,plic",
    "riscv,clint",
    "arm,gic",
    "snps,dw-apb-uart",
    "snps,dw-apb-timer",
    "snps,dwcmshc",
    "soc-image,descriptor-dma-v1",
    "soc-image,fixed-clock-mmio-v1",
    "soc-image,reset-v1",
    "soc-image,pinmux-v1",
)
SOFTWARE_ROLES = ("boot", "bsp", "driver", "os", "toolchain", "compiler", "runtime", "product", "image_tool")
IDENTITY_PATTERNS = (
    ("vendor", "canmv", re.compile(r"(?:^|[^a-z0-9])canmv(?:$|[^a-z0-9])", re.I)),
    ("board", "canmv-k230-v3", re.compile(r"canmv[-_ ]?k230.*(?:v3(?:\.0)?|lp4)", re.I)),
    ("soc", "k230", re.compile(r"\bk230(?:d|_lp4)?\b", re.I)),
    ("memory", "lpddr4", re.compile(r"\b(?:lpddr4|lp4)\b", re.I)),
)
COMPONENT_PATTERNS = {
    "uart": re.compile(r"(?<![a-z0-9])uart[0-9]*(?![a-z0-9])", re.I),
    "gpio": re.compile(r"(?<![a-z0-9])gpio[0-9]*(?![a-z0-9])", re.I),
    "i2c": re.compile(r"(?<![a-z0-9])(?:i2c|iic)[0-9]*(?![a-z0-9])", re.I),
    "spi": re.compile(r"(?<![a-z0-9])(?:spi[0-9]*|ospi)(?![a-z0-9])", re.I),
    "pwm": re.compile(r"(?<![a-z0-9])pwm[0-9]*(?![a-z0-9])", re.I),
    "adc": re.compile(r"(?<![a-z0-9])adc[0-9]*(?![a-z0-9])", re.I),
    "usb": re.compile(r"(?<![a-z0-9])usb[0-9]*(?![a-z0-9])", re.I),
    "storage": re.compile(r"(?<![a-z0-9])(?:sd|sdio|sdhci|emmc|tfcard|tf card|mmc[0-9]?)(?![a-z0-9])", re.I),
    "network": re.compile(r"(?<![a-z0-9])(?:ethernet|wifi|wi-fi|rgmii|rmii)(?![a-z0-9])", re.I),
    "camera": re.compile(r"(?<![a-z0-9])(?:camera|csi[0-9]*|vicap|dvp|mipi_rx)(?![a-z0-9])", re.I),
    "display": re.compile(r"(?<![a-z0-9])(?:display|lcd|dsi|hdmi)(?![a-z0-9])", re.I),
    "audio": re.compile(r"(?<![a-z0-9])(?:audio|codec|i2s|iis)(?![a-z0-9])", re.I),
    "accelerator": re.compile(r"(?<![a-z0-9])(?:kpu|npu|ai2d|gnne)(?![a-z0-9])", re.I),
}
INTERFACES_BY_CLASS = {
    "uart": ("clock", "irq", "pinmux"),
    "gpio": ("clock", "irq", "pinmux"),
    "i2c": ("clock", "irq", "pinmux"),
    "spi": ("clock", "irq", "pinmux"),
    "pwm": ("clock", "pinmux"),
    "adc": ("clock", "pinmux"),
    "usb": ("clock", "irq", "reset"),
    "storage": ("clock", "dma", "irq", "pinmux", "reset"),
    "network": ("clock", "dma", "irq", "pinmux", "reset"),
    "camera": ("clock", "dma", "irq", "pinmux", "reset"),
    "display": ("clock", "dma", "irq", "pinmux", "reset"),
    "audio": ("clock", "dma", "irq", "pinmux", "reset"),
    "accelerator": ("clock", "dma", "irq", "reset"),
}


def _read_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(data: dict[str, Any], schema_path: Path) -> list[str]:
    errors = sorted(Draft202012Validator(_read_schema(schema_path)).iter_errors(data), key=lambda item: list(item.path))
    return [error.message for error in errors]


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _document_pages(path: Path) -> tuple[list[str], str]:
    if path.suffix.lower() == ".pdf":
        tool = shutil.which("pdftotext")
        if not tool:
            return [], "pdftotext_unavailable"
        proc = subprocess.run(
            [tool, "-layout", str(path), "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode:
            return [], f"pdftotext_failed:{proc.stderr.decode(errors='ignore').strip()}"
        return proc.stdout.decode("utf-8", errors="ignore").split("\f"), "pdftotext"
    if path.suffix.lower() in {".txt", ".md", ".csv", ".html", ".htm"}:
        return [path.read_text(encoding="utf-8", errors="ignore")], "text"
    return [], "extractor_unavailable"


def extract_document(path: Path) -> dict[str, Any]:
    pages, extractor = _document_pages(path)
    observations = []
    seen = set()
    if KEYWORDS.search(path.name):
        observations.append({"text": path.name, "state": "candidate", "sources": [source(path, "filename")]})
    for page_number, page_text in enumerate(pages, 1):
        for line_number, line in enumerate(page_text.splitlines(), 1):
            normalized = " ".join(line.split())
            if not normalized or not (ADDRESS.search(normalized) or KEYWORDS.search(normalized)):
                continue
            key = (page_number, normalized)
            if key in seen:
                continue
            seen.add(key)
            observations.append(
                {
                    "text": normalized[:1000],
                    "state": "candidate",
                    "sources": [source(path, f"page:{page_number}:line:{line_number}", page=page_number)],
                }
            )
            if len(observations) >= 2000:
                break
        if len(observations) >= 2000:
            break
    return {
        "kind": "document",
        "extractor": extractor,
        "page_count": len([page for page in pages if page.strip()]),
        "observations": observations,
        "facts_promoted": 0,
    }


def _merge_fact(left: dict[str, Any], right: dict[str, Any], path: str, conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    if left["value"] == right["value"]:
        merged = copy.deepcopy(left)
        known = {(item["sha256"], item["locator"]) for item in merged["sources"]}
        merged["sources"].extend(item for item in right["sources"] if (item["sha256"], item["locator"]) not in known)
        if left["state"] not in SAFE_STATES or right["state"] not in SAFE_STATES:
            merged["state"] = left["state"] if left["state"] == right["state"] else "candidate"
        return merged
    conflicts.append({"kind": "fact_value", "paths": [path, path], "message": f"conflicting values: {left['value']!r} != {right['value']!r}"})
    return {
        "value": [left["value"], right["value"]],
        "state": "conflict",
        "sources": [*left["sources"], *right["sources"]],
        "constraints": sorted(set([*left.get("constraints", []), *right.get("constraints", [])])),
        **({"unit": left["unit"]} if left.get("unit") == right.get("unit") and left.get("unit") else {}),
    }


def _merge_registers(left: list[dict[str, Any]], right: list[dict[str, Any]], prefix: str, conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {item["id"].lower(): copy.deepcopy(item) for item in left}
    for register in right:
        key = register["id"].lower()
        if key not in merged:
            merged[key] = copy.deepcopy(register)
            continue
        current = merged[key]
        for field_name in ("offset", "size", "access", "reset_value"):
            incoming = register.get(field_name)
            if incoming is None:
                continue
            if field_name not in current:
                current[field_name] = copy.deepcopy(incoming)
            else:
                current[field_name] = _merge_fact(current[field_name], incoming, f"{prefix}.registers.{register['id']}.{field_name}", conflicts)
        fields = {item["id"].lower(): copy.deepcopy(item) for item in current["fields"]}
        for incoming_field in register["fields"]:
            field_key = incoming_field["id"].lower()
            if field_key not in fields:
                fields[field_key] = copy.deepcopy(incoming_field)
                continue
            for fact_name in ("bit_offset", "bit_width", "access"):
                incoming = incoming_field.get(fact_name)
                if incoming is None:
                    continue
                if fact_name not in fields[field_key]:
                    fields[field_key][fact_name] = copy.deepcopy(incoming)
                else:
                    fields[field_key][fact_name] = _merge_fact(fields[field_key][fact_name], incoming, f"{prefix}.registers.{register['id']}.fields.{incoming_field['id']}.{fact_name}", conflicts)
        current["fields"] = sorted(fields.values(), key=lambda item: item["id"].lower())
    return sorted(merged.values(), key=lambda item: item["id"].lower())


def _merge_peripherals(groups: list[list[dict[str, Any]]], conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for peripheral in group:
            key = peripheral["id"].lower()
            if key not in merged:
                merged[key] = copy.deepcopy(peripheral)
                continue
            current = merged[key]
            for fact_name in ("compatible", "base", "size", "interrupts", "clock_refs", "reset_refs", "pin_refs"):
                incoming = peripheral.get(fact_name)
                if incoming is None:
                    continue
                if fact_name not in current:
                    current[fact_name] = copy.deepcopy(incoming)
                else:
                    current[fact_name] = _merge_fact(current[fact_name], incoming, f"peripherals.{current['id']}.{fact_name}", conflicts)
            current["registers"] = _merge_registers(current["registers"], peripheral["registers"], f"peripherals.{current['id']}", conflicts)
            if current.get("kind") == "peripheral" and peripheral.get("kind") != "peripheral":
                current["kind"] = peripheral["kind"]
    return sorted(merged.values(), key=lambda item: item["id"].lower())


def _merge_regions(groups: list[list[dict[str, Any]]], conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for region in group:
            key = region["id"].lower()
            if key not in merged:
                merged[key] = copy.deepcopy(region)
                continue
            current = merged[key]
            for fact_name in ("kind", "base", "size", "attributes"):
                incoming = region.get(fact_name)
                if incoming is None:
                    continue
                if fact_name not in current:
                    current[fact_name] = copy.deepcopy(incoming)
                else:
                    current[fact_name] = _merge_fact(current[fact_name], incoming, f"memory_regions.{current['id']}.{fact_name}", conflicts)
    return sorted(merged.values(), key=lambda item: item["id"].lower())


def _mark_conflict(value: dict[str, Any]) -> None:
    value["state"] = "conflict"


def _address_and_irq_conflicts(ir: dict[str, Any]) -> None:
    peripherals = ir["peripherals"]
    for index, left in enumerate(peripherals):
        if not is_safe(left.get("base")) or not is_safe(left.get("size")):
            continue
        left_base, left_size = left["base"]["value"], left["size"]["value"]
        if not isinstance(left_base, int) or not isinstance(left_size, int) or left_size <= 0:
            continue
        for right in peripherals[index + 1:]:
            if not is_safe(right.get("base")) or not is_safe(right.get("size")):
                continue
            right_base, right_size = right["base"]["value"], right["size"]["value"]
            if not isinstance(right_base, int) or not isinstance(right_size, int) or right_size <= 0:
                continue
            if left_base < right_base + right_size and right_base < left_base + left_size:
                ir["conflicts"].append(
                    {
                        "kind": "address_overlap",
                        "paths": [f"peripherals.{left['id']}.base", f"peripherals.{right['id']}.base"],
                        "message": f"MMIO ranges for {left['id']} and {right['id']} overlap",
                    }
                )
                _mark_conflict(left["base"])
                _mark_conflict(right["base"])
    for region in ir["memory_regions"]:
        if not is_safe(region.get("base")) or not is_safe(region.get("size")):
            continue
        region_base, region_size = region["base"]["value"], region["size"]["value"]
        if not isinstance(region_base, int) or not isinstance(region_size, int) or region_size <= 0:
            continue
        for peripheral in peripherals:
            if not is_safe(peripheral.get("base")) or not is_safe(peripheral.get("size")):
                continue
            peripheral_base, peripheral_size = peripheral["base"]["value"], peripheral["size"]["value"]
            if not isinstance(peripheral_base, int) or not isinstance(peripheral_size, int) or peripheral_size <= 0:
                continue
            if region_base < peripheral_base + peripheral_size and peripheral_base < region_base + region_size:
                ir["conflicts"].append(
                    {
                        "kind": "memory_mmio_overlap",
                        "paths": [f"memory_regions.{region['id']}.base", f"peripherals.{peripheral['id']}.base"],
                        "message": f"memory region {region['id']} overlaps MMIO for {peripheral['id']}",
                    }
                )
                _mark_conflict(region["base"])
                _mark_conflict(peripheral["base"])
    irq_owner: dict[int, dict[str, Any]] = {}
    for peripheral in peripherals:
        interrupts = peripheral.get("interrupts")
        if not is_safe(interrupts) or not isinstance(interrupts["value"], int):
            continue
        irq = interrupts["value"]
        previous = irq_owner.get(irq)
        if previous is None:
            irq_owner[irq] = peripheral
            continue
        ir["conflicts"].append(
            {
                "kind": "irq_collision",
                "paths": [f"peripherals.{previous['id']}.interrupts", f"peripherals.{peripheral['id']}.interrupts"],
                "message": f"IRQ {irq} is assigned to multiple peripherals without a shared-IRQ contract",
            }
        )
        _mark_conflict(previous["interrupts"])
        _mark_conflict(interrupts)
    regions = ir["memory_regions"]
    for index, left in enumerate(regions):
        if not is_safe(left.get("base")) or not is_safe(left.get("size")):
            continue
        left_base, left_size = left["base"]["value"], left["size"]["value"]
        for right in regions[index + 1:]:
            if not is_safe(right.get("base")) or not is_safe(right.get("size")):
                continue
            right_base, right_size = right["base"]["value"], right["size"]["value"]
            if all(isinstance(value, int) and value >= 0 for value in (left_base, left_size, right_base, right_size)) and left_base < right_base + right_size and right_base < left_base + left_size:
                ir["conflicts"].append(
                    {
                        "kind": "memory_overlap",
                        "paths": [f"memory_regions.{left['id']}.base", f"memory_regions.{right['id']}.base"],
                        "message": f"memory regions {left['id']} and {right['id']} overlap",
                    }
                )
                _mark_conflict(left["base"])
                _mark_conflict(right["base"])


def _safe_peripheral(ir: dict[str, Any], kinds: set[str]) -> list[dict[str, Any]]:
    return [item for item in ir["peripherals"] if item.get("kind") in kinds and is_safe(item.get("base"))]


def _known_standard(peripheral: dict[str, Any]) -> bool:
    compatible = peripheral.get("compatible")
    if not is_safe(compatible):
        return False
    values = compatible["value"] if isinstance(compatible["value"], list) else [compatible["value"]]
    return any(token in str(value).lower() for token in KNOWN_STANDARD_COMPATIBLES for value in values)


def _register_contract(peripheral: dict[str, Any]) -> bool:
    registers = peripheral["registers"]
    fields = [field for register in registers for field in register["fields"]]
    return (
        bool(fields)
        and all(is_safe(register.get("offset")) and is_safe(register.get("access")) for register in registers)
        and all(
            is_safe(field.get("bit_offset"))
            and is_safe(field.get("bit_width"))
            and is_safe(field.get("access"))
            for field in fields
        )
    )


def _driver_ready(peripheral: dict[str, Any]) -> bool:
    return is_safe(peripheral.get("base")) and (_known_standard(peripheral) or _register_contract(peripheral))


def _controllers_ready(ir: dict[str, Any], kinds: set[str]) -> bool:
    return any(_driver_ready(item) for item in _safe_peripheral(ir, kinds))


def _explicit_contract(items: list[dict[str, Any]], field_name: str) -> bool:
    return any(is_safe(item.get(field_name)) for item in items)


def _unresolved(ir: dict[str, Any]) -> list[dict[str, Any]]:
    checks = [
        ("cpu.isa", is_safe(ir["cpu"].get("isa")), ["boot", "bsp", "cpu_execution"], True),
        ("memory_regions", any(is_safe(item.get("base")) and is_safe(item.get("size")) for item in ir["memory_regions"]), ["linker", "bsp", "runtime_memory"], True),
        ("clocks", _controllers_ready(ir, {"clock"}), ["boot", "bsp", "drivers"], True),
        ("resets", _controllers_ready(ir, {"reset"}), ["boot", "drivers", "recovery"], True),
        ("pinmux", _controllers_ready(ir, {"pinmux"}), ["board_io", "drivers"], True),
        ("interrupt_controller", _controllers_ready(ir, {"plic", "gic"}), ["bsp", "interrupts"], True),
        ("dma", any(_driver_ready(item) for item in _safe_peripheral(ir, {"dma"})), ["dma", "ai_runtime"], True),
        ("ddr.training", _explicit_contract(ir["ddr"], "training_contract"), ["ddr_boot", "high_memory"], False),
        ("boot.rom_and_media", _explicit_contract(ir["boot"], "rom_contract"), ["boot", "image_layout"], False),
        ("cache.coherency", is_safe(ir["cpu"].get("cache_line_bytes")), ["dma", "ai_runtime"], True),
        ("accelerator.inventory", any(is_safe(item.get("base")) for item in ir["accelerators"]), ["accelerator_execution"], True),
    ]
    result = []
    for path, ready, capabilities, probe_allowed in checks:
        if not ready:
            result.append(
                {
                    "path": path,
                    "reason": "no authoritative, standard-derived, or board-observed value is available",
                    "blocking_capabilities": capabilities,
                    "probe_allowed": probe_allowed,
                }
            )
    for accelerator in ir["accelerators"]:
        if not is_safe(accelerator.get("command_abi")):
            result.append(
                {
                    "path": f"accelerators.{accelerator['id']}.command_abi",
                    "reason": "accelerator command ABI is not documented",
                    "blocking_capabilities": ["accelerator_codegen", "accelerator_execution"],
                    "probe_allowed": False,
                }
            )
    for peripheral in ir["peripherals"]:
        if is_safe(peripheral.get("base")) and not _driver_ready(peripheral):
            result.append(
                {
                    "path": f"peripherals.{peripheral['id']}.register_contract",
                    "reason": "neither field-level registers nor a recognized standard compatible are available",
                    "blocking_capabilities": [f"driver_{peripheral.get('kind', 'peripheral')}"],
                    "probe_allowed": True,
                }
            )
    return result


def _reference_profile(ir: dict[str, Any], ir_hash: str) -> dict[str, Any]:
    enabled: list[dict[str, Any]] = []
    isa = ir["cpu"].get("isa")
    if is_safe(isa):
        enabled.append({"id": "cpu_execution", "basis": ["cpu.isa"]})
        isa_match = re.match(r"^rv(?:32|64|128)([a-z]+)", str(isa["value"]).lower())
        if isa_match and "v" in isa_match.group(1):
            enabled.append({"id": "rvv", "basis": ["cpu.isa"]})
    if is_safe(ir["cpu"].get("cache_line_bytes")):
        enabled.append({"id": "cache_coherency", "basis": ["cpu.cache_line_bytes"]})
    for region in ir["memory_regions"]:
        if is_safe(region.get("base")) and is_safe(region.get("size")):
            enabled.append({"id": "runtime_memory", "basis": [f"memory_regions.{region['id']}.base", f"memory_regions.{region['id']}.size"]})
            break
    kind_capabilities = {
        "uart": "console_uart",
        "timer": "timer",
        "gpio": "gpio",
        "spi": "spi",
        "i2c": "i2c",
        "usb": "usb",
        "storage": "storage",
        "ethernet": "network",
        "camera": "camera",
        "display": "display",
        "audio": "audio",
        "dma": "dma",
        "plic": "interrupt_controller",
        "gic": "interrupt_controller",
    }
    for peripheral in ir["peripherals"]:
        capability = kind_capabilities.get(peripheral.get("kind"))
        if capability and _driver_ready(peripheral):
            basis = [f"peripherals.{peripheral['id']}.base"]
            if _known_standard(peripheral):
                basis.append(f"peripherals.{peripheral['id']}.compatible")
            else:
                basis.append(f"peripherals.{peripheral['id']}.registers.{peripheral['registers'][0]['id']}.offset")
            enabled.append({"id": capability, "basis": basis})
    unique_enabled = {item["id"]: item for item in enabled}
    blocked: dict[str, dict[str, Any]] = {}
    for item in ir["unresolved"]:
        for capability in item["blocking_capabilities"]:
            entry = blocked.setdefault(capability, {"id": capability, "reason": "required hardware fields are unresolved", "fields": []})
            entry["fields"].append(item["path"])
    for conflict in ir["conflicts"]:
        entry = blocked.setdefault("contract_conflict", {"id": "contract_conflict", "reason": "hardware facts conflict", "fields": []})
        entry["fields"].extend(conflict["paths"])
    return {
        "schema": "soc-image.reference-profile.v1",
        "project_id": ir["project_id"],
        "hardware_ir_sha256": ir_hash,
        "product_class": "hardware_capability_coverage",
        "os_policy": "rt-thread",
        "enabled_capabilities": sorted(unique_enabled.values(), key=lambda item: item["id"]),
        "blocked_capabilities": sorted(
            ({**item, "fields": sorted(set(item["fields"]))} for item in blocked.values()),
            key=lambda item: item["id"],
        ),
    }


def _resolve_basis(ir: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    current: Any = ir
    index = 0
    while index < len(parts):
        part = parts[index]
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            current = next((item for item in current if isinstance(item, dict) and item.get("id") == part), None)
        else:
            return None
        if current is None:
            return None
        index += 1
    return current


def profile_safety_errors(ir: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    errors = []
    for capability in profile.get("enabled_capabilities", []):
        for basis in capability.get("basis", []):
            value = _resolve_basis(ir, basis)
            if not is_fact(value) or not is_safe(value):
                errors.append(f"enabled capability {capability['id']} has unsafe basis: {basis}")
    return errors


def _basis_from_observation(observation: dict[str, Any]) -> str:
    source_item = observation["sources"][0]
    return f"observations:{source_item['sha256']}:{source_item['locator']}"


def _identity(ir: dict[str, Any]) -> list[dict[str, Any]]:
    values: dict[tuple[str, str], dict[str, Any]] = {}
    for observation in ir["observations"]:
        text = observation["text"]
        for kind, normalized, pattern in IDENTITY_PATTERNS:
            if pattern.search(text):
                key = (kind, normalized)
                item = values.setdefault(key, {"kind": kind, "value": normalized, "state": "candidate", "basis": []})
                item["basis"].append(_basis_from_observation(observation))
    platform = ir["cpu"].get("platform_compatible")
    if is_safe(platform):
        compatibles = platform["value"] if isinstance(platform["value"], list) else [platform["value"]]
        for compatible in compatibles:
            value = str(compatible)
            if value:
                values[("board", value)] = {
                    "kind": "board", "value": value, "state": platform["state"], "basis": ["cpu.platform_compatible"]
                }
    isa = ir["cpu"].get("isa")
    if is_safe(isa):
        architecture = "riscv" if str(isa["value"]).lower().startswith("rv") else str(isa["value"]).lower()
        values[("architecture", architecture)] = {
            "kind": "architecture", "value": architecture, "state": isa["state"], "basis": ["cpu.isa"]
        }
    return [
        {**item, "basis": sorted(set(item["basis"]))}
        for _, item in sorted(values.items())
    ]


def _compatible_values(peripheral: dict[str, Any]) -> list[str]:
    compatible = peripheral.get("compatible")
    if not is_fact(compatible):
        return []
    values = compatible["value"] if isinstance(compatible["value"], list) else [compatible["value"]]
    return sorted({str(value) for value in values if str(value)})


def _search_terms(identity: list[dict[str, Any]], component_class: str, compatible: list[str]) -> list[str]:
    identity_text = " ".join(item["value"] for item in identity if item["kind"] in {"board", "soc"})
    terms = [f"{identity_text} {component_class} driver".strip(), *(f"{value} driver" for value in compatible)]
    return sorted(set(terms))


def _software_requirements(ir: dict[str, Any], ir_hash: str) -> dict[str, Any]:
    identity = _identity(ir)
    components: list[dict[str, Any]] = []
    existing_classes: set[str] = set()
    for peripheral in ir["peripherals"]:
        component_class = re.sub(r"[^a-z0-9_]+", "_", peripheral.get("kind", "peripheral").lower()).strip("_") or "peripheral"
        compatible = _compatible_values(peripheral)
        states = [item["state"] for item in (peripheral.get("base"), peripheral.get("compatible")) if is_fact(item)]
        evidence_state = next((state for state in states if state in SAFE_STATES), "candidate")
        components.append({
            "id": peripheral["id"],
            "class": component_class,
            "compatible": compatible,
            "required_interfaces": sorted(INTERFACES_BY_CLASS.get(component_class, ("clock", "irq", "reset"))),
            "hardware_basis": [f"peripherals.{peripheral['id']}"],
            "evidence_state": evidence_state,
            "search_terms": _search_terms(identity, component_class, compatible),
            "reuse_allowed": True,
            "generated_mmio_allowed": _driver_ready(peripheral),
        })
        existing_classes.add(component_class)
    for component_class, pattern in COMPONENT_PATTERNS.items():
        if component_class in existing_classes:
            continue
        matched = [item for item in ir["observations"] if pattern.search(item["text"])]
        if not matched:
            continue
        components.append({
            "id": f"observed-{component_class}",
            "class": component_class,
            "compatible": [],
            "required_interfaces": sorted(INTERFACES_BY_CLASS.get(component_class, ("clock", "irq", "reset"))),
            "hardware_basis": sorted({_basis_from_observation(item) for item in matched}),
            "evidence_state": "candidate",
            "search_terms": _search_terms(identity, component_class, []),
            "reuse_allowed": True,
            "generated_mmio_allowed": False,
        })
    return {
        "schema": "soc-image.software-requirements.v1",
        "project_id": ir["project_id"],
        "hardware_ir_sha256": ir_hash,
        "board_identity": identity,
        "software_roles": list(SOFTWARE_ROLES),
        "components": sorted(components, key=lambda item: item["id"].lower()),
    }


def software_requirement_safety_errors(ir: dict[str, Any], requirements: dict[str, Any]) -> list[str]:
    peripherals = {item["id"]: item for item in ir["peripherals"]}
    errors = []
    for component in requirements.get("components", []):
        if not component.get("generated_mmio_allowed"):
            continue
        peripheral = peripherals.get(component.get("id"))
        if peripheral is None or not _driver_ready(peripheral):
            errors.append(f"software requirement permits unsafe MMIO generation: {component.get('id')}")
    return errors


def _extraction(path: Path, kind: str) -> dict[str, Any]:
    if kind == "svd":
        parsed = parse_svd(path)
        return {"kind": kind, "extractor": "cmsis-svd-xml", "facts": parsed, "observations": []}
    if kind == "dts":
        parsed = parse_dts(path)
        return {"kind": kind, "extractor": "dtc-yaml", "facts": parsed, "observations": []}
    if kind in {"document", "image", "unknown", "cmsis_pack"}:
        return extract_document(path)
    return {"kind": kind, "extractor": "unavailable", "observations": [], "facts_promoted": 0}


def derive(run: Path, *, force: bool = False) -> dict[str, Any]:
    run = run.resolve()
    intake = load_run(run)
    if not intake["ok"]:
        return {"ok": False, "status": "blocked", "run": str(run), "errors": intake["errors"]}
    outputs = [run / name for name in ("hardware_ir.json", "unknowns.json", "conflicts.json", "reference_profile.json", "software_requirements.json")]
    if not force and all(path.is_file() for path in outputs):
        return load_outputs(run)

    lock_path = run / LOCK_NAME
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    staging = Path(tempfile.mkdtemp(prefix=".hardware-ir-", dir=run))
    try:
        extraction_dir = staging / "material_extractions"
        extraction_dir.mkdir()
        parsed_groups: list[list[dict[str, Any]]] = []
        memory_groups: list[list[dict[str, Any]]] = []
        cpu: dict[str, Any] = {}
        observations: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        for item in lock["materials"]:
            path = run / item["stored_path"]
            extracted = _extraction(path, item["kind"])
            _write_json(extraction_dir / f"{item['sha256']}.json", extracted)
            observations.extend(extracted.get("observations", []))
            facts = extracted.get("facts", {})
            if facts:
                parsed_groups.append(facts.get("peripherals", []))
                memory_groups.append(facts.get("memory_regions", []))
                for name, value in facts.get("cpu", {}).items():
                    cpu[name] = _merge_fact(cpu[name], value, f"cpu.{name}", conflicts) if name in cpu else copy.deepcopy(value)
        peripherals = _merge_peripherals(parsed_groups, conflicts)
        memory_regions = _merge_regions(memory_groups, conflicts)
        ir: dict[str, Any] = {
            "schema": "soc-image.hardware-ir.v1",
            "project_id": lock["project_id"],
            "materials_lock_sha256": sha256(lock_path),
            "cpu": cpu,
            "memory_regions": sorted(memory_regions, key=lambda item: item["id"]),
            "peripherals": peripherals,
            "clocks": [{"id": item["id"], "peripheral_id": item["id"]} for item in peripherals if item.get("kind") == "clock"],
            "resets": [{"id": item["id"], "peripheral_id": item["id"]} for item in peripherals if item.get("kind") == "reset"],
            "pinmux": [{"id": item["id"], "peripheral_id": item["id"]} for item in peripherals if item.get("kind") == "pinmux"],
            "dma": [{"id": item["id"], "peripheral_id": item["id"]} for item in peripherals if item.get("kind") == "dma"],
            "ddr": [{"id": item["id"], "peripheral_id": item["id"]} for item in peripherals if item.get("kind") == "ddr"],
            "boot": [],
            "accelerators": [
                {"id": item["id"], "peripheral_id": item["id"], **({"base": copy.deepcopy(item["base"])} if "base" in item else {})}
                for item in peripherals if item.get("kind") in {"npu", "kpu"}
            ],
            "board_components": [],
            "observations": observations,
            "unresolved": [],
            "conflicts": conflicts,
        }
        _address_and_irq_conflicts(ir)
        ir["unresolved"] = _unresolved(ir)
        errors = _validate(ir, IR_SCHEMA)
        if errors:
            raise ValueError("Hardware IR schema validation failed: " + "; ".join(errors))
        ir_path = staging / "hardware_ir.json"
        _write_json(ir_path, ir)
        ir_hash = sha256(ir_path)
        profile = _reference_profile(ir, ir_hash)
        safety_errors = profile_safety_errors(ir, profile)
        if safety_errors:
            raise ValueError("reference profile safety validation failed: " + "; ".join(safety_errors))
        profile_errors = _validate(profile, PROFILE_SCHEMA)
        if profile_errors:
            raise ValueError("reference profile schema validation failed: " + "; ".join(profile_errors))
        _write_json(staging / "reference_profile.json", profile)
        requirements = _software_requirements(ir, ir_hash)
        requirement_errors = _validate(requirements, SOFTWARE_REQUIREMENTS_SCHEMA)
        requirement_errors.extend(software_requirement_safety_errors(ir, requirements))
        if requirement_errors:
            raise ValueError("software requirements validation failed: " + "; ".join(requirement_errors))
        _write_json(staging / "software_requirements.json", requirements)
        _write_json(staging / "unknowns.json", {"schema": "soc-image.unknowns.v1", "hardware_ir_sha256": ir_hash, "items": ir["unresolved"]})
        _write_json(staging / "conflicts.json", {"schema": "soc-image.conflicts.v1", "hardware_ir_sha256": ir_hash, "items": ir["conflicts"]})
        destination_extractions = run / "artifacts/material_extractions"
        if destination_extractions.exists():
            shutil.rmtree(destination_extractions)
        destination_extractions.parent.mkdir(exist_ok=True)
        os.replace(extraction_dir, destination_extractions)
        for name in ("hardware_ir.json", "unknowns.json", "conflicts.json", "reference_profile.json", "software_requirements.json"):
            os.replace(staging / name, run / name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return load_outputs(run)


def load_outputs(run: Path) -> dict[str, Any]:
    run = run.resolve()
    paths = {name: run / f"{name}.json" for name in ("hardware_ir", "unknowns", "conflicts", "reference_profile", "software_requirements")}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        return {"ok": False, "status": "hardware_ir_missing", "run": str(run), "errors": [f"missing output: {path}" for path in missing]}
    intake = load_run(run)
    if not intake["ok"]:
        return {"ok": False, "status": "hardware_ir_invalid", "run": str(run), "errors": intake["errors"]}
    lock_path = run / LOCK_NAME
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    try:
        ir = json.loads(paths["hardware_ir"].read_text(encoding="utf-8"))
        profile = json.loads(paths["reference_profile"].read_text(encoding="utf-8"))
        unknowns = json.loads(paths["unknowns"].read_text(encoding="utf-8"))
        conflicts = json.loads(paths["conflicts"].read_text(encoding="utf-8"))
        requirements = json.loads(paths["software_requirements"].read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"ok": False, "status": "hardware_ir_invalid", "run": str(run), "errors": [str(exc)]}
    if not all(isinstance(value, dict) for value in (ir, profile, unknowns, conflicts, requirements)):
        return {"ok": False, "status": "hardware_ir_invalid", "run": str(run), "errors": ["Hardware IR outputs must be JSON objects"]}
    errors = _validate(ir, IR_SCHEMA)
    errors.extend(_validate(profile, PROFILE_SCHEMA))
    errors.extend(_validate(requirements, SOFTWARE_REQUIREMENTS_SCHEMA))
    errors.extend(profile_safety_errors(ir, profile))
    errors.extend(software_requirement_safety_errors(ir, requirements))
    ir_hash = sha256(paths["hardware_ir"])
    if ir.get("materials_lock_sha256") != sha256(lock_path):
        errors.append("hardware_ir.json does not match materials.lock.json")
    if profile.get("hardware_ir_sha256") != ir_hash:
        errors.append("reference profile does not match hardware_ir.json")
    if profile.get("project_id") != ir.get("project_id"):
        errors.append("reference profile project_id does not match hardware_ir.json")
    if requirements.get("hardware_ir_sha256") != ir_hash or requirements.get("project_id") != ir.get("project_id"):
        errors.append("software requirements do not match hardware_ir.json")
    for name, payload, expected in (
        ("unknowns", unknowns, ir.get("unresolved")),
        ("conflicts", conflicts, ir.get("conflicts")),
    ):
        if payload.get("schema") != f"soc-image.{name}.v1":
            errors.append(f"{name}.json has an invalid schema")
        if payload.get("hardware_ir_sha256") != ir_hash:
            errors.append(f"{name}.json does not match hardware_ir.json")
        if payload.get("items") != expected:
            errors.append(f"{name}.json items do not match hardware_ir.json")
    allowed_hashes = {item["sha256"] for item in lock["materials"]}
    stack: list[Any] = [ir]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if "sources" in value:
                sources = value["sources"]
                if isinstance(sources, list):
                    for item in sources:
                        digest = item.get("sha256") if isinstance(item, dict) else None
                        if digest not in allowed_hashes:
                            errors.append(f"hardware fact source is not in materials.lock.json: {digest}")
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return {
        "ok": not errors,
        "status": "hardware_ir_complete" if not errors else "hardware_ir_invalid",
        "run": str(run),
        "hardware_ir": str(paths["hardware_ir"]),
        "unknowns": str(paths["unknowns"]),
        "conflicts": str(paths["conflicts"]),
        "reference_profile": str(paths["reference_profile"]),
        "software_requirements": str(paths["software_requirements"]),
        "enabled_capabilities": [item["id"] for item in profile.get("enabled_capabilities", [])],
        "blocked_capabilities": [item["id"] for item in profile.get("blocked_capabilities", [])],
        "generation_safety_pass": not profile_safety_errors(ir, profile),
        "next_stage": "dynamic_planning" if not errors else None,
        "errors": errors,
    }


def selftest() -> None:
    from socimage.intake import create_run

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        svd = root / "soc.svd"
        svd.write_text(
            """<device><name>demo</name><size>32</size><peripherals><peripheral><name>UART0</name>
            <baseAddress>0x10000000</baseAddress><registers><register><name>DATA</name>
            <addressOffset>0</addressOffset><access>read-write</access><fields><field><name>VALUE</name><bitOffset>0</bitOffset>
            <bitWidth>8</bitWidth></field></fields></register></registers></peripheral></peripherals></device>""",
            encoding="utf-8",
        )
        document = root / "SCH_CanMV-K230-LP4-V3.0.txt"
        document.write_text("Candidate UART base 0x20000000 and camera CSI must not override SVD.\n", encoding="utf-8")
        run = root / "run"
        create_run([svd, document], run)
        result = derive(run)
        assert result["ok"], result
        ir = json.loads((run / "hardware_ir.json").read_text(encoding="utf-8"))
        assert ir["peripherals"][0]["base"]["value"] == 0x10000000
        assert ir["observations"] and ir["observations"][0]["state"] == "candidate"
        profile = json.loads((run / "reference_profile.json").read_text(encoding="utf-8"))
        assert "console_uart" in {item["id"] for item in profile["enabled_capabilities"]}
        assert "cpu_execution" in {item["id"] for item in profile["blocked_capabilities"]}
        assert "ddr_boot" in {item["id"] for item in profile["blocked_capabilities"]}
        requirements = json.loads((run / "software_requirements.json").read_text(encoding="utf-8"))
        identity = {(item["kind"], item["value"]) for item in requirements["board_identity"]}
        assert {("vendor", "canmv"), ("board", "canmv-k230-v3"), ("soc", "k230"), ("memory", "lpddr4")} <= identity
        components = {item["id"]: item for item in requirements["components"]}
        assert components["UART0"]["generated_mmio_allowed"] is True
        assert components["observed-camera"]["evidence_state"] == "candidate"
        assert components["observed-camera"]["generated_mmio_allowed"] is False
        dts_requirements = copy.deepcopy(requirements)
        dts_requirements["components"][0]["id"] = "serial@10000000"
        assert not _validate(dts_requirements, SOFTWARE_REQUIREMENTS_SCHEMA)
        ir["cpu"]["platform_compatible"] = fact("riscv-virtio,qemu", svd, "/test/compatible")
        qemu_requirements = _software_requirements(ir, "0" * 64)
        assert ("board", "riscv-virtio,qemu") in {(item["kind"], item["value"]) for item in qemu_requirements["board_identity"]}
        unsafe_requirements = copy.deepcopy(requirements)
        next(item for item in unsafe_requirements["components"] if item["id"] == "observed-camera")["generated_mmio_allowed"] = True
        _write_json(run / "software_requirements.json", unsafe_requirements)
        assert not load_outputs(run)["ok"]
        _write_json(run / "software_requirements.json", requirements)
        ir["cpu"]["isa"] = fact("rv64imac", svd, "/test/isa")
        assert "rvv" not in {item["id"] for item in _reference_profile(ir, "0" * 64)["enabled_capabilities"]}
        ir["cpu"]["isa"] = fact("rv64gcv", svd, "/test/isa")
        assert "rvv" in {item["id"] for item in _reference_profile(ir, "0" * 64)["enabled_capabilities"]}
        unknowns = json.loads((run / "unknowns.json").read_text(encoding="utf-8"))
        unknowns["items"] = []
        _write_json(run / "unknowns.json", unknowns)
        assert not load_outputs(run)["ok"]

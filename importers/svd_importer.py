#!/usr/bin/env python3
"""Import field-level CMSIS-SVD metadata with source provenance."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from importers.common import report, write_json
from socimage.facts import fact


def _strip_namespaces(root: ET.Element) -> None:
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]


def text(node: ET.Element | None, name: str, default: str = "") -> str:
    if node is None:
        return default
    child = node.find(name)
    return child.text.strip() if child is not None and child.text else default


def number(value: str, default: int | None = None) -> int | None:
    if not value:
        return default
    cleaned = value.strip().replace("#", "")
    try:
        return int(cleaned, 0)
    except ValueError:
        return default


def _inherited(
    name: str,
    nodes: list[tuple[ET.Element | None, str]],
    parser: Any = str,
) -> tuple[Any, str] | tuple[None, None]:
    for node, locator in nodes:
        raw = text(node, name)
        if not raw:
            continue
        value = parser(raw)
        if value is not None:
            return value, f"{locator}/{name}"
    return None, None


def _field_bits(node: ET.Element) -> tuple[int | None, int | None]:
    offset = number(text(node, "bitOffset"))
    width = number(text(node, "bitWidth"))
    if offset is not None and width is not None:
        return offset, width
    lsb = number(text(node, "lsb"))
    msb = number(text(node, "msb"))
    if lsb is not None and msb is not None and msb >= lsb:
        return lsb, msb - lsb + 1
    match = re.fullmatch(r"\[(\d+):(\d+)\]", text(node, "bitRange"))
    if match:
        msb, lsb = map(int, match.groups())
        if msb >= lsb:
            return lsb, msb - lsb + 1
    return None, None


def _kind(name: str) -> str:
    lowered = name.lower()
    for candidate in ("uart", "serial", "gpio", "timer", "dma", "plic", "gic", "clint", "spi", "i2c", "usb", "sd", "ethernet", "camera", "display", "audio", "clock", "reset", "pinctrl", "pinmux", "ddr", "dram", "npu", "kpu"):
        if candidate in lowered:
            return {"serial": "uart", "pinctrl": "pinmux", "dram": "ddr"}.get(candidate, candidate)
    return "peripheral"


def parse_svd(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    _strip_namespaces(root)
    cpu_node = root.find("cpu")
    parsed: dict[str, Any] = {
        "device_name": text(root, "name", path.stem),
        "cpu": {},
        "peripherals": [],
    }
    if text(cpu_node, "name"):
        parsed["cpu"]["model"] = fact(text(cpu_node, "name"), path, "/device/cpu/name")
    if text(cpu_node, "revision"):
        parsed["cpu"]["revision"] = fact(text(cpu_node, "revision"), path, "/device/cpu/revision")
    if text(cpu_node, "endian"):
        parsed["cpu"]["endianness"] = fact(text(cpu_node, "endian"), path, "/device/cpu/endian")

    for peripheral_index, peripheral in enumerate(root.findall("./peripherals/peripheral")):
        peripheral_name = text(peripheral, "name", f"peripheral_{peripheral_index}")
        peripheral_locator = f"/device/peripherals/{peripheral_name}"
        base = number(text(peripheral, "baseAddress"))
        item: dict[str, Any] = {"id": peripheral_name, "kind": _kind(peripheral_name), "registers": []}
        if base is not None:
            item["base"] = fact(base, path, f"{peripheral_locator}/baseAddress", unit="byte_address")
        interrupt_values = [number(text(node, "value")) for node in peripheral.findall("interrupt")]
        interrupt_values = [value for value in interrupt_values if value is not None]
        if interrupt_values:
            value: Any = interrupt_values[0] if len(interrupt_values) == 1 else interrupt_values
            item["interrupts"] = fact(value, path, f"{peripheral_locator}/interrupt/value")
        maximum_end = 0
        registers_node = peripheral.find("registers")
        for register_index, register in enumerate(registers_node.findall("register") if registers_node is not None else []):
            register_name = text(register, "name", f"register_{register_index}")
            register_locator = f"{peripheral_locator}/registers/{register_name}"
            offset = number(text(register, "addressOffset"))
            if offset is None:
                continue
            inherited_nodes = [
                (register, register_locator),
                (peripheral, peripheral_locator),
                (root, "/device"),
            ]
            register_size, size_locator = _inherited("size", inherited_nodes, number)
            register_access, access_locator = _inherited("access", inherited_nodes)
            register_reset, reset_locator = _inherited("resetValue", inherited_nodes, number)
            register_item: dict[str, Any] = {
                "id": register_name,
                "offset": fact(offset, path, f"{register_locator}/addressOffset", unit="byte_offset"),
                "fields": [],
            }
            if register_size is not None:
                register_item["size"] = fact(register_size, path, str(size_locator), unit="bit")
                maximum_end = max(maximum_end, offset + (register_size + 7) // 8)
            if register_access:
                register_item["access"] = fact(register_access, path, str(access_locator))
            if register_reset is not None:
                register_item["reset_value"] = fact(register_reset, path, str(reset_locator))
            fields_node = register.find("fields")
            for field_index, field_node in enumerate(fields_node.findall("field") if fields_node is not None else []):
                field_name = text(field_node, "name", f"field_{field_index}")
                bit_offset, bit_width = _field_bits(field_node)
                if bit_offset is None or bit_width is None:
                    continue
                field_locator = f"{register_locator}/fields/{field_name}"
                field_item: dict[str, Any] = {
                    "id": field_name,
                    "bit_offset": fact(bit_offset, path, f"{field_locator}/bitOffset", unit="bit"),
                    "bit_width": fact(bit_width, path, f"{field_locator}/bitWidth", unit="bit"),
                }
                field_access, field_access_locator = _inherited(
                    "access",
                    [(field_node, field_locator), *inherited_nodes],
                )
                if field_access:
                    field_item["access"] = fact(field_access, path, str(field_access_locator))
                register_item["fields"].append(field_item)
            item["registers"].append(register_item)
        if maximum_end:
            item["size"] = fact(maximum_end, path, f"{peripheral_locator}/register-derived-size", state="standard_derived", unit="byte")
        parsed["peripherals"].append(item)
    return parsed


def import_svd(path: Path, out: Path) -> dict[str, Any]:
    parsed = parse_svd(path)
    target: dict[str, Any] = {"name": parsed["device_name"], "hardware_specs": {"svd": str(path)}}
    observations: list[dict[str, Any]] = []
    for peripheral in parsed["peripherals"]:
        base = peripheral.get("base", {}).get("value")
        item = {
            "name": peripheral["id"],
            "base": f"0x{base:x}" if isinstance(base, int) else "",
            "registers": [register["id"] for register in peripheral["registers"]],
            "field_count": sum(len(register["fields"]) for register in peripheral["registers"]),
        }
        observations.append(item)
        if peripheral["kind"] == "uart":
            target.setdefault("uart", {})["base"] = item["base"]
        elif peripheral["kind"] == "dma":
            target.setdefault("dma", {})["base"] = item["base"]
        elif peripheral["kind"] in {"npu", "kpu"}:
            target.setdefault("npu", {}).update(enabled=True, base=item["base"])
    result = report(path, target, observations, "svd_import_pass")
    result["hardware_ir"] = parsed
    result["evidence"]["register_fields_imported"] = any(item["field_count"] for item in observations)
    write_json(out / "target.draft.json", result)
    return result


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "demo.svd"
        source.write_text(
            """<device><name>example_riscv_ai</name><size>32</size><peripherals><peripheral>
            <name>DMA</name><baseAddress>0x20000000</baseAddress><registers><register>
            <name>CTRL</name><addressOffset>0x4</addressOffset><access>read-write</access>
            <fields><field><name>ENABLE</name><bitOffset>0</bitOffset><bitWidth>1</bitWidth></field></fields>
            </register></registers></peripheral></peripherals></device>""",
            encoding="utf-8",
        )
        parsed = parse_svd(source)
        field = parsed["peripherals"][0]["registers"][0]["fields"][0]
        assert field["bit_width"]["value"] == 1
        register = parsed["peripherals"][0]["registers"][0]
        assert register["size"]["sources"][0]["locator"] == "/device/size"
        assert register["access"]["sources"][0]["locator"].endswith("/CTRL/access")
        result = import_svd(source, root / "out")
        assert result["target"]["name"] == "example_riscv_ai", result
        assert result["target"]["dma"]["base"] == "0x20000000", result
        assert result["evidence"]["register_fields_imported"], result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="source")
    parser.add_argument("--out", default=str(ROOT / "build/import_svd"))
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    if not args.source:
        parser.error("--in is required unless --selftest is used")
    result = import_svd(Path(args.source).resolve(), Path(args.out).resolve())
    print(__import__("json").dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

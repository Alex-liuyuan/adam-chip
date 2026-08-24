#!/usr/bin/env python3
"""Import validated Device Tree YAML into provenance-bound hardware facts."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from importers.common import report, write_json
from socimage.facts import fact


def _cell_rows(value: Any) -> list[list[int]]:
    if not isinstance(value, list):
        return []
    rows = []
    for row in value:
        if isinstance(row, list) and all(isinstance(item, int) for item in row):
            rows.append(row)
    return rows


def _first_scalar(value: Any) -> Any:
    if isinstance(value, list) and value:
        if isinstance(value[0], list) and value[0]:
            return value[0][0]
        return value[0]
    return value


def _combine(cells: list[int]) -> int:
    value = 0
    for cell in cells:
        value = (value << 32) | cell
    return value


def _kind(name: str, compatible: list[str]) -> str:
    text = " ".join([name, *compatible]).lower()
    for candidate in ("uart", "serial", "gpio", "timer", "dma", "plic", "gic", "clint", "spi", "i2c", "usb", "sdhci", "mmc", "ethernet", "camera", "display", "audio", "clock", "reset", "pinctrl", "pinmux", "ddr", "dram", "npu", "kpu"):
        if candidate in text:
            return {"serial": "uart", "sdhci": "storage", "mmc": "storage", "pinctrl": "pinmux", "dram": "ddr"}.get(candidate, candidate)
    return "peripheral"


def _children(node: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for name, value in node.items():
        if not name.startswith("#") and isinstance(value, dict):
            yield name, value


def _property_int(node: dict[str, Any], name: str, default: int) -> int:
    value = _first_scalar(node.get(name))
    return value if isinstance(value, int) else default


def parse_dts(path: Path, work: Path | None = None) -> dict[str, Any]:
    dtc = shutil.which("dtc")
    if not dtc:
        raise RuntimeError("dtc is required to validate DTS input")
    proc = subprocess.run(
        [dtc, "-I", "dts", "-O", "yaml", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"dtc rejected {path}: {proc.stderr.strip()}")
    document = yaml.safe_load(proc.stdout)
    root = document[0] if isinstance(document, list) and document and isinstance(document[0], dict) else None
    if root is None:
        raise ValueError(f"dtc produced no Device Tree root for {path}")

    parsed: dict[str, Any] = {
        "device_name": str(_first_scalar(root.get("model")) or path.stem),
        "cpu": {},
        "memory_regions": [],
        "peripherals": [],
    }
    root_compatible = _first_scalar(root.get("compatible"))
    if isinstance(root_compatible, str):
        parsed["cpu"]["platform_compatible"] = fact(root_compatible, path, "/compatible")
    cpu_count = 0

    def walk(node: dict[str, Any], node_path: str, address_cells: int, size_cells: int) -> None:
        nonlocal cpu_count
        child_address_cells = _property_int(node, "#address-cells", address_cells)
        child_size_cells = _property_int(node, "#size-cells", size_cells)
        for name, child in _children(node):
            path_name = f"{node_path}/{name}" if node_path else f"/{name}"
            if str(_first_scalar(child.get("status")) or "okay") == "disabled":
                continue
            compatible_value = child.get("compatible", [])
            compatible = [str(value) for value in compatible_value] if isinstance(compatible_value, list) else [str(compatible_value)]
            reg_rows = _cell_rows(child.get("reg"))
            base = size = None
            if reg_rows and len(reg_rows[0]) >= child_address_cells + child_size_cells:
                base = _combine(reg_rows[0][:child_address_cells])
                size = _combine(reg_rows[0][child_address_cells:child_address_cells + child_size_cells]) if child_size_cells else 0
            device_type = str(_first_scalar(child.get("device_type")) or "")
            if device_type == "cpu" or name.startswith("cpu@"):
                cpu_count += 1
                isa = _first_scalar(child.get("riscv,isa"))
                if isinstance(isa, str):
                    parsed["cpu"].setdefault("isa", fact(isa, path, f"{path_name}/riscv,isa"))
                model = _first_scalar(child.get("compatible"))
                if isinstance(model, str):
                    parsed["cpu"].setdefault("model", fact(model, path, f"{path_name}/compatible"))
                cache_line = _first_scalar(child.get("d-cache-line-size"))
                if isinstance(cache_line, int) and cache_line > 0:
                    parsed["cpu"].setdefault("cache_line_bytes", fact(cache_line, path, f"{path_name}/d-cache-line-size", unit="byte"))
            elif device_type == "memory" or name.startswith("memory@"):
                if base is not None and size is not None:
                    parsed["memory_regions"].append(
                        {
                            "id": name,
                            "kind": fact("memory", path, f"{path_name}/device_type"),
                            "base": fact(base, path, f"{path_name}/reg/address", unit="byte_address"),
                            "size": fact(size, path, f"{path_name}/reg/size", unit="byte"),
                        }
                    )
            elif base is not None or compatible:
                item: dict[str, Any] = {
                    "id": name,
                    "kind": _kind(name, compatible),
                    "registers": [],
                }
                if compatible:
                    item["compatible"] = fact(compatible, path, f"{path_name}/compatible")
                if base is not None:
                    item["base"] = fact(base, path, f"{path_name}/reg/address", unit="byte_address")
                if size is not None:
                    item["size"] = fact(size, path, f"{path_name}/reg/size", unit="byte")
                irq_rows = _cell_rows(child.get("interrupts"))
                if irq_rows:
                    irq_value: Any = irq_rows[0][0] if len(irq_rows[0]) == 1 else irq_rows[0]
                    item["interrupts"] = fact(irq_value, path, f"{path_name}/interrupts", constraints=["controller-specific-cells"] if isinstance(irq_value, list) else [])
                for source_name, destination in (("clocks", "clock_refs"), ("resets", "reset_refs"), ("pinctrl-0", "pin_refs")):
                    rows = _cell_rows(child.get(source_name))
                    if rows:
                        item[destination] = fact(rows, path, f"{path_name}/{source_name}")
                parsed["peripherals"].append(item)
            walk(child, path_name, child_address_cells, child_size_cells)

    walk(root, "", _property_int(root, "#address-cells", 2), _property_int(root, "#size-cells", 1))
    if cpu_count:
        parsed["cpu"]["core_count"] = fact(cpu_count, path, "/cpus/*", state="standard_derived", unit="core")
    return parsed


def import_dts(path: Path, out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    parsed = parse_dts(path, out)
    target: dict[str, Any] = {"name": parsed["device_name"], "hardware_specs": {"dts": str(path)}}
    observations: list[dict[str, Any]] = []
    for peripheral in parsed["peripherals"]:
        base = peripheral.get("base", {}).get("value")
        irq = peripheral.get("interrupts", {}).get("value")
        compatible = peripheral.get("compatible", {}).get("value", [])
        node = {
            "name": peripheral["id"],
            "compatible": compatible[0] if compatible else "",
            "base": f"0x{base:x}" if isinstance(base, int) else "",
            "size": peripheral.get("size", {}).get("value"),
            "irq": irq,
        }
        observations.append(node)
        if peripheral["kind"] == "uart":
            target["uart"] = {"base": node["base"], "irq": irq, "kind": node["compatible"] or node["name"]}
        elif peripheral["kind"] == "dma":
            target["dma"] = {"base": node["base"], "irq": irq}
        elif peripheral["kind"] in {"npu", "kpu"}:
            target["npu"] = {"enabled": True, "base": node["base"], "irq": irq}
    result = report(path, target, observations, "dts_import_pass")
    result["hardware_ir"] = parsed
    result["evidence"]["dtc_validation_pass"] = True
    result["evidence"]["device_tree_yaml_parse_pass"] = True
    write_json(out / "target.draft.json", result)
    return result


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "demo.dts"
        source.write_text(
            '/dts-v1/;\n/ { model = "example_riscv_ai"; #address-cells = <1>; #size-cells = <1>; cpus { #address-cells = <1>; #size-cells = <0>; cpu@0 { device_type = "cpu"; compatible = "riscv"; reg = <0>; riscv,isa = "rv64imac"; }; }; memory@80000000 { device_type = "memory"; reg = <0x80000000 0x100000>; }; uart0: serial@10000000 { compatible = "ns16550a"; reg = <0x10000000 0x100>; interrupts = <5>; }; };\n',
            encoding="utf-8",
        )
        parsed = parse_dts(source)
        assert parsed["cpu"]["isa"]["value"] == "rv64imac", parsed
        assert parsed["memory_regions"][0]["base"]["value"] == 0x80000000, parsed
        result = import_dts(source, root / "out")
        assert result["target"]["name"] == "example_riscv_ai", result
        assert result["target"]["uart"]["base"] == "0x10000000", result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="source")
    parser.add_argument("--out", default=str(ROOT / "build/import_dts"))
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0
    if not args.source:
        parser.error("--in is required unless --selftest is used")
    result = import_dts(Path(args.source).resolve(), Path(args.out).resolve())
    print(__import__("json").dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Safe board discovery, binding, flash/readback and boot attribution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


class HilError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_system() -> dict[str, object]:
    serial = []
    for root in (Path("/dev/serial/by-id"), Path("/dev/serial/by-path")):
        if root.is_dir():
            serial.extend({"name": path.name, "path": str(path.resolve()), "stable_path": str(path)} for path in sorted(root.iterdir()) if path.is_symlink())
    usb = []
    for device in sorted(Path("/sys/bus/usb/devices").glob("*")):
        vendor, product = device / "idVendor", device / "idProduct"
        if vendor.is_file() and product.is_file():
            usb.append({
                "sysfs": str(device), "vendor": vendor.read_text().strip(), "product": product.read_text().strip(),
                "serial": (device / "serial").read_text().strip() if (device / "serial").is_file() else None,
            })
    storage = []
    proc = subprocess.run(["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,TYPE,TRAN,RM,RO,MODEL,SERIAL,MOUNTPOINTS"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if proc.returncode == 0:
        for item in json.loads(proc.stdout).get("blockdevices", []):
            mounted = any(value for value in item.get("mountpoints") or []) or any(any(value for value in child.get("mountpoints") or []) for child in item.get("children") or [])
            if item.get("type") == "disk" and item.get("rm") is True and item.get("ro") is False and not mounted:
                storage.append({key: item.get(key) for key in ("name", "path", "size", "tran", "model", "serial")})
    return {"schema": "soc-image.lab-inventory.v1", "serial": serial, "usb": usb, "storage": storage, "power": []}


def discover_lab(root: Path) -> list[dict[str, object]]:
    root = root.resolve()
    devices = []
    for descriptor in sorted(root.glob("*/device.json")):
        data = json.loads(descriptor.read_text(encoding="utf-8"))
        directory = descriptor.parent.resolve()
        storage = (directory / data["storage"]).resolve()
        serial = (directory / data["serial_log"]).resolve()
        if root not in storage.parents or root not in serial.parents or not storage.is_file() or not serial.is_file():
            raise HilError(f"unsafe lab descriptor: {descriptor}")
        devices.append({**data, "descriptor": str(descriptor), "storage_path": str(storage), "serial_path": str(serial)})
    return devices


def bind_unique(devices: list[dict[str, object]]) -> dict[str, object]:
    if len(devices) != 1:
        raise HilError(f"device_count_not_one:{len(devices)}")
    device = devices[0]
    identity = f"{device.get('board_id')}\0{device.get('serial')}\0{device.get('storage_path')}"
    return {**device, "identity_sha256": hashlib.sha256(identity.encode()).hexdigest()}


def flash_readback(binding: dict[str, object], image: Path, *, attempts: int = 2, corrupt_first: bool = False) -> dict[str, object]:
    if attempts < 1 or attempts > 2:
        raise HilError("flash attempts must be between one and two")
    storage = Path(str(binding["storage_path"]))
    payload = image.read_bytes()
    if not storage.is_file() or storage.stat().st_size < len(payload):
        raise HilError("storage is missing or too small")
    expected = hashlib.sha256(payload).hexdigest()
    for attempt in range(1, attempts + 1):
        with storage.open("r+b", buffering=0) as stream:
            stream.seek(0)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            if corrupt_first and attempt == 1:
                stream.seek(0)
                stream.write(b"BAD!")
                stream.flush()
                os.fsync(stream.fileno())
            stream.seek(0)
            actual = hashlib.sha256(stream.read(len(payload))).hexdigest()
        if actual == expected:
            return {"image_sha256": expected, "readback_sha256": actual, "attempts": attempt}
    raise HilError("flash_readback_mismatch")


def verify_boot(binding: dict[str, object], run_id: str, image_sha256: str) -> dict[str, str]:
    log = Path(str(binding["serial_path"])).read_text(encoding="utf-8", errors="replace")
    token = f"SOC_IMAGE_RUN_ID={run_id} IMAGE_SHA256={image_sha256}"
    if token not in log:
        raise HilError("boot_attribution_missing")
    return {"run_id": run_id, "image_sha256": image_sha256, "token": token}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("discover-system")
    lab = commands.add_parser("discover-lab")
    lab.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    result = discover_system() if args.command == "discover-system" else {"devices": discover_lab(args.root)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

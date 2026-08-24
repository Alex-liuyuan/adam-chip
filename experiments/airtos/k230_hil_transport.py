#!/usr/bin/env python3
"""Upload files and run commands on a CanMV-K230 RT-Smart board."""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import struct
import sys
import time
from pathlib import Path

import serial


IDE_BAUD = 12_000_000
CONSOLE_BAUD = 115_200
CMD_SCRIPT_EXEC = 0x05
CMD_SCRIPT_STOP = 0x06
SCRIPT_DONE = b"[mpy] enter repl"
PROMPT = b"msh />"


def command_header(command: int, length: int) -> bytes:
    return struct.pack("<BBI", 0x30, command, length)


class Board:
    def __init__(self, console: str, ide: str) -> None:
        self.console_path = console
        self.ide_path = ide
        self._open()

    def _open(self) -> None:
        self.console = serial.Serial(self.console_path, CONSOLE_BAUD, timeout=0.1, write_timeout=3)
        self.ide = serial.Serial(self.ide_path, IDE_BAUD, timeout=1, write_timeout=20)

    def close(self) -> None:
        self.ide.close()
        self.console.close()

    def reconnect(self) -> None:
        self.close()
        time.sleep(0.5)
        self._open()

    def _protocol(self, command: int, payload: bytes = b"") -> None:
        self.ide.write(command_header(command, len(payload)))
        if payload:
            self.ide.write(payload)
        self.ide.flush()

    def _read_until(self, marker: bytes, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        output = bytearray()
        while time.monotonic() < deadline:
            chunk = self.console.read(65536)
            if chunk:
                output.extend(chunk)
                if marker in output or (marker == PROMPT and re.search(rb"msh [^\r\n]*>", output)):
                    return bytes(output)
            else:
                time.sleep(0.02)
        raise TimeoutError(f"board did not emit {marker!r} within {timeout}s")

    def script(self, source: bytes, timeout: float = 10) -> bytes:
        self._protocol(CMD_SCRIPT_STOP)
        time.sleep(0.1)
        self.console.reset_input_buffer()
        self._protocol(CMD_SCRIPT_EXEC, source)
        return self._read_until(SCRIPT_DONE, timeout)

    def run(self, command: str, timeout: float) -> bytes:
        self.console.reset_input_buffer()
        self.console.write(command.encode("utf-8") + b"\r\n")
        self.console.flush()
        return self._read_until(PROMPT, timeout)

    def run_stream(self, command: str, timeout: float) -> None:
        self.console.reset_input_buffer()
        self.console.write(command.encode("utf-8") + b"\r\n")
        self.console.flush()
        deadline = time.monotonic() + timeout
        window = b""
        while time.monotonic() < deadline:
            chunk = self.console.read(65536)
            if not chunk:
                time.sleep(0.02)
                continue
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            window = (window + chunk)[-max(len(PROMPT), 64) :]
            if PROMPT in window:
                return
        raise TimeoutError(f"board did not emit {PROMPT!r} within {timeout}s")

    def run_mixed_stream(self, commands: list[str], verification_commands: list[str], source: bytes, timeout: float) -> None:
        markers = {
            b"AIRTOS_K230_LONG_PASS": False,
            b"AIRTOS_K230_COMPUTE_PASS": False,
            b"AIRTOS_K230_MIXED_PASS": False,
        }
        for command in commands:
            output = self.run(command, 15)
            sys.stdout.buffer.write(output)
            sys.stdout.buffer.flush()
            for marker in markers:
                markers[marker] = markers[marker] or marker in output
        self._protocol(CMD_SCRIPT_STOP)
        time.sleep(0.1)
        self._protocol(CMD_SCRIPT_EXEC, source)
        deadline = time.monotonic() + timeout
        window = b""
        while time.monotonic() < deadline:
            chunk = self.console.read(65536)
            if not chunk:
                time.sleep(0.02)
                continue
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            window = (window + chunk)[-4096:]
            for marker in markers:
                markers[marker] = markers[marker] or marker in window
            if b"AIRTOS_K230_LONG_FAIL" in window or b"AIRTOS_K230_COMPUTE_FAIL" in window or b"AIRTOS_K230_MIXED_FAIL" in window:
                self._protocol(CMD_SCRIPT_STOP)
                raise RuntimeError("mixed hardware-in-the-loop workload reported failure")
            if SCRIPT_DONE in window:
                for command in verification_commands:
                    output = self.run(command, 60)
                    sys.stdout.buffer.write(output)
                    sys.stdout.buffer.flush()
                    for marker in markers:
                        markers[marker] = markers[marker] or marker in output
                    if b"AIRTOS_K230_LONG_FAIL" in output or b"AIRTOS_K230_COMPUTE_FAIL" in output or b"AIRTOS_K230_MIXED_FAIL" in output:
                        raise RuntimeError("mixed hardware-in-the-loop verification log reported failure")
                missing = [marker.decode("ascii") for marker, found in markers.items() if not found]
                if missing:
                    raise RuntimeError("mixed hardware-in-the-loop workload ended without " + ", ".join(missing))
                print("AIRTOS_K230_FULL_24H_PASS")
                return
        self._protocol(CMD_SCRIPT_STOP)
        raise TimeoutError("mixed hardware-in-the-loop workload did not finish within timeout")

    def sha256(self, remote: str, timeout: float = 60) -> str:
        hash_file = remote + ".sha256"
        source = (
            "import hashlib,ubinascii\n"
            f"f=open({remote!r},'rb')\n"
            "h=hashlib.sha256()\n"
            "while True:\n"
            " b=f.read(65536)\n"
            " if not b: break\n"
            " h.update(b)\n"
            "f.close()\n"
            f"f=open({hash_file!r},'w')\n"
            "f.write(ubinascii.hexlify(h.digest()).decode())\n"
            "f.close()\n"
        ).encode("ascii")
        self.script(source, timeout)
        output = self.run(f"cat {hash_file}", 10).decode("utf-8", errors="replace")
        match = re.search(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", output)
        if match is not None:
            return match.group(0)
        raise RuntimeError(f"board did not return SHA-256 for {remote}: {output!r}")

    def concat(self, parts: list[str], remote: str) -> str:
        source = (
            f"parts={parts!r}\n"
            f"out=open({remote!r},'wb')\n"
            "for name in parts:\n"
            " f=open(name,'rb')\n"
            " while True:\n"
            "  b=f.read(65536)\n"
            "  if not b: break\n"
            "  out.write(b)\n"
            " f.close()\n"
            "out.close()\n"
        ).encode("ascii")
        self.script(source, 120)
        return self.sha256(remote, 120)

    def upload(self, local: Path, remote: str, chunk_size: int = 48 * 1024, retries: int = 3) -> str:
        digest = hashlib.sha256()
        with local.open("rb") as stream:
            offset = 0
            chunk_index = 0
            while chunk := stream.read(chunk_size):
                if chunk_index != 0 and chunk_index % 128 == 0:
                    self.reconnect()
                digest.update(chunk)
                encoded = base64.b64encode(chunk)
                mode = "wb" if offset == 0 else "r+b"
                source = (
                    "import ubinascii\n"
                    f"f=open({remote!r},{mode!r})\n"
                    f"f.seek({offset})\n"
                    f"f.write(ubinascii.a2b_base64({encoded!r}))\n"
                    "f.close()\n"
                ).encode("ascii")
                for attempt in range(retries):
                    try:
                        self.script(source)
                        break
                    except TimeoutError:
                        if attempt + 1 == retries:
                            raise
                        self.reconnect()
                offset += len(chunk)
                chunk_index += 1
        expected = digest.hexdigest()
        actual = self.sha256(remote, max(10, local.stat().st_size / 2_000_000))
        if expected != actual:
            raise RuntimeError(f"readback SHA-256 mismatch for {remote}: expected {expected}, got {actual}")
        return expected


def selftest() -> None:
    assert command_header(0x05, 3) == b"\x30\x05\x03\x00\x00\x00"
    assert base64.b64decode(base64.b64encode(b"airtos")) == b"airtos"
    assert hashlib.sha256(b"airtos").hexdigest() == "2a343476e44ac0b88ee48bbb1e3242320d6cd65ed0501bdfa8d16f474d9bd426"
    assert re.search(r"[0-9a-f]{64}", "a" * 64 + "\x00").group(0) == "a" * 64


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--console", default="/dev/serial/by-id/usb-1a86_USB_Dual_Serial_5C78109061-if00")
    parser.add_argument("--ide", default="/dev/serial/by-id/usb-Kendryte_CanMV_001000000-if00")
    parser.add_argument("--selftest", action="store_true")
    subparsers = parser.add_subparsers(dest="operation")
    upload = subparsers.add_parser("upload")
    upload.add_argument("local", type=Path)
    upload.add_argument("remote")
    run = subparsers.add_parser("run")
    run.add_argument("command")
    run.add_argument("--timeout", type=float, default=60)
    run.add_argument("--stream", action="store_true")
    mixed = subparsers.add_parser("mixed")
    mixed.add_argument("source", type=Path)
    mixed.add_argument("--command", action="append", required=True)
    mixed.add_argument("--verify-command", action="append", default=[])
    mixed.add_argument("--duration", type=int, required=True)
    mixed.add_argument("--heartbeat", type=int, default=60)
    mixed.add_argument("--timeout", type=float, required=True)
    concat = subparsers.add_parser("concat")
    concat.add_argument("remote")
    concat.add_argument("parts", nargs="+")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("K230_HIL_TRANSPORT_SELFTEST_PASS")
        return 0
    if not args.operation:
        parser.error("an operation is required")
    board = Board(args.console, args.ide)
    try:
        if args.operation == "upload":
            print(f"K230_UPLOAD_PASS sha256={board.upload(args.local, args.remote)} remote={args.remote}")
        elif args.operation == "run":
            if args.stream:
                board.run_stream(args.command, args.timeout)
            else:
                print(board.run(args.command, args.timeout).decode("utf-8", errors="replace"), end="")
        elif args.operation == "mixed":
            source = args.source.read_bytes() + f"\nmain({args.duration}, {args.heartbeat})\n".encode("ascii")
            board.run_mixed_stream(args.command, args.verify_command, source, args.timeout)
        else:
            print(f"K230_CONCAT_PASS sha256={board.concat(args.parts, args.remote)} remote={args.remote}")
    finally:
        board.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Show a SYSUOS K230 camera stream in a web browser."""

from __future__ import annotations

import argparse
import json
import signal
import struct
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import serial
from serial.tools import list_ports


VID, PID = 0x1209, 0xABD1
BAUDRATE = 12_000_000
CMD_SCRIPT_EXEC = 0x05
CMD_SCRIPT_STOP = 0x06
CMD_FB_ENABLE = 0x0D
CMD_FB_SIZE = 0x81
CMD_FB_DUMP = 0x82

BOARD_SCRIPT = b"""\
import sys
if "/sdcard/apps" not in sys.path:
    sys.path.append("/sdcard/apps")
import sysu_camera_live
sysu_camera_live.main()
"""

PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SYSUOS 实时画面</title>
<style>
:root{color-scheme:light;--bg:#f3f4f6;--surface:#fff;--ink:#17191c;--muted:#697077;--line:#d9dde1;--ok:#16803b;--bad:#c42b2b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;letter-spacing:0}
header{height:58px;background:var(--surface);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 max(18px,calc((100vw - 1080px)/2))}
h1{font-size:17px;line-height:1.2;margin:0;font-weight:650}.device{font:12px ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--muted)}
main{width:min(1080px,100%);margin:0 auto;padding:18px}.toolbar{min-height:38px;display:flex;gap:18px;align-items:center;justify-content:space-between;margin-bottom:10px}
.metrics{display:flex;gap:18px;align-items:center;font-size:13px;color:var(--muted);flex-wrap:wrap}.state{display:inline-flex;align-items:center;gap:7px;color:var(--ink)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--bad)}.dot.ok{background:var(--ok)}.actions{display:flex;gap:8px}
button,a.button{height:32px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--ink);font:13px inherit;padding:0 12px;display:inline-flex;align-items:center;text-decoration:none;cursor:pointer}
button:hover,a.button:hover{border-color:#9ca3aa;background:#f8f9fa}button:focus-visible,a.button:focus-visible{outline:2px solid #1769aa;outline-offset:2px}
.stage{position:relative;width:100%;aspect-ratio:4/3;max-height:calc(100vh - 144px);background:#111;overflow:hidden;border:1px solid #26292d;border-radius:6px;display:grid;place-items:center}
.stage img{width:100%;height:100%;object-fit:contain;display:block;position:relative;z-index:1}.message{position:absolute;color:#c8cdd2;font-size:14px;text-align:center;padding:20px}
@media(max-width:640px){header{height:52px;padding:0 14px}.device{display:none}main{padding:10px}.toolbar{align-items:flex-start}.metrics{gap:7px 14px}.actions{flex-direction:column}.stage{max-height:none}button,a.button{height:30px;padding:0 10px}}
</style>
</head>
<body>
<header><h1>SYSUOS 实时画面</h1><span class="device" id="device">正在连接开发板</span></header>
<main>
  <div class="toolbar">
    <div class="metrics">
      <span class="state"><i class="dot" id="dot"></i><span id="state">连接中</span></span>
      <span id="resolution">-- × --</span><span id="fps">-- FPS</span>
    </div>
    <div class="actions"><a class="button" href="/snapshot.jpg" download="sysuos-camera.jpg">保存截图</a><button id="fullscreen" type="button">全屏</button></div>
  </div>
  <div class="stage" id="stage"><div class="message" id="message">等待摄像头画面…</div><img id="video" src="/stream.mjpg" alt="SYSUOS 摄像头实时画面"></div>
</main>
<script>
const $=id=>document.getElementById(id), video=$('video'), message=$('message');
video.onload=()=>message.hidden=true;
video.onerror=()=>{message.hidden=false;message.textContent='画面连接中断，正在重试…';setTimeout(()=>video.src='/stream.mjpg?t='+Date.now(),1500)};
$('fullscreen').onclick=()=>$('stage').requestFullscreen();
async function update(){try{const s=await fetch('/api/status',{cache:'no-store'}).then(r=>r.json());$('dot').classList.toggle('ok',s.connected);$('state').textContent=s.connected?'已连接':'未连接';$('device').textContent=s.serial||'未发现开发板';$('resolution').textContent=s.width?s.width+' × '+s.height:'-- × --';$('fps').textContent=s.fps.toFixed(1)+' FPS';if(s.error&&!s.connected){message.hidden=false;message.textContent=s.error}}catch(e){$('dot').classList.remove('ok');$('state').textContent='服务断开'}}
update();setInterval(update,1000);
</script>
</body>
</html>
""".encode("utf-8")


def command_header(command: int, length: int) -> bytes:
    return struct.pack("<BBI", 0x30, command, length)


def is_jpeg(data: bytes) -> bool:
    return len(data) > 4 and data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9")


def find_serial(requested: str | None) -> str:
    if requested:
        path = Path(requested)
        if not path.exists():
            raise FileNotFoundError(f"串口不存在: {requested}")
        return str(path)
    matches = sorted(port.device for port in list_ports.comports() if port.vid == VID and port.pid == PID)
    if not matches:
        raise FileNotFoundError("未发现 SYSUOS K230 USB 调试串口 (1209:abd1)")
    return matches[0]


class Camera:
    def __init__(self, requested_serial: str | None) -> None:
        self.requested_serial = requested_serial
        self.serial_path = ""
        self.connected = False
        self.error = ""
        self.width = 0
        self.height = 0
        self.frame = b""
        self.sequence = 0
        self.frame_time = 0.0
        self.frame_times: deque[float] = deque(maxlen=30)
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="sysuos-camera", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        with self.condition:
            self.condition.notify_all()
        self.thread.join(timeout=3)

    @staticmethod
    def _write(transport: serial.Serial, command: int, length: int = 0, payload: bytes = b"") -> None:
        transport.write(command_header(command, length))
        if payload:
            transport.write(payload)
        transport.flush()

    @staticmethod
    def _read_exact(transport: serial.Serial, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = transport.read(size - len(data))
            if not chunk:
                raise TimeoutError(f"开发板响应超时 ({len(data)}/{size} 字节)")
            data.extend(chunk)
        return bytes(data)

    def _start_script(self, transport: serial.Serial) -> None:
        self._write(transport, CMD_SCRIPT_STOP)
        time.sleep(0.1)
        transport.reset_input_buffer()
        self._write(transport, CMD_SCRIPT_EXEC, len(BOARD_SCRIPT), BOARD_SCRIPT)
        time.sleep(2.0)
        self._write(transport, CMD_FB_ENABLE)
        transport.write(struct.pack("<H", 1))
        transport.flush()

    def _capture(self, transport: serial.Serial) -> None:
        self._write(transport, CMD_FB_SIZE, 12)
        width, height, size = struct.unpack("<III", self._read_exact(transport, 12))
        if not width or not height or size <= 3:
            time.sleep(0.02)
            return
        if width > 8192 or height > 8192 or size > 16 * 1024 * 1024:
            raise ValueError(f"开发板返回了无效帧: {width}x{height}, {size} 字节")
        self._write(transport, CMD_FB_DUMP, size)
        frame = self._read_exact(transport, size)
        if not is_jpeg(frame):
            raise ValueError("开发板返回的数据不是完整 JPEG")
        now = time.monotonic()
        with self.condition:
            self.width, self.height = width, height
            self.frame = frame
            self.frame_time = now
            self.frame_times.append(now)
            self.sequence += 1
            self.condition.notify_all()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            transport = None
            try:
                path = find_serial(self.requested_serial)
                self.serial_path = path
                transport = serial.Serial(path, BAUDRATE, timeout=1, write_timeout=2)
                transport.reset_input_buffer()
                transport.reset_output_buffer()
                self._start_script(transport)
                self.connected = True
                self.error = ""
                while not self.stop_event.is_set():
                    self._capture(transport)
            except Exception as exc:
                self.connected = False
                self.error = str(exc)
                self.stop_event.wait(2)
            finally:
                if transport is not None:
                    try:
                        self._write(transport, CMD_SCRIPT_STOP)
                    except Exception:
                        pass
                    transport.close()
        self.connected = False

    def wait_frame(self, previous: int, timeout: float = 5) -> tuple[bytes, int]:
        with self.condition:
            self.condition.wait_for(lambda: self.sequence != previous or self.stop_event.is_set(), timeout)
            return self.frame, self.sequence

    def snapshot(self) -> bytes:
        with self.condition:
            return self.frame

    def status(self) -> dict[str, object]:
        with self.condition:
            times = tuple(self.frame_times)
            fps = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 and times[-1] > times[0] else 0.0
            age = time.monotonic() - self.frame_time if self.frame_time else None
            return {
                "connected": self.connected,
                "serial": self.serial_path,
                "width": self.width,
                "height": self.height,
                "fps": round(fps, 1),
                "frame_age": round(age, 2) if age is not None else None,
                "error": self.error,
            }


def make_handler(camera: Camera) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._send(PAGE, "text/html; charset=utf-8")
            elif path == "/api/status":
                self._send(json.dumps(camera.status(), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            elif path == "/snapshot.jpg":
                frame = camera.snapshot()
                if frame:
                    self._send(frame, "image/jpeg")
                else:
                    self.send_error(503, "Camera frame is not ready")
            elif path == "/stream.mjpg":
                self._stream()
            else:
                self.send_error(404)

        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            sequence = -1
            try:
                while True:
                    frame, next_sequence = camera.wait_frame(sequence)
                    if not frame or next_sequence == sequence:
                        continue
                    sequence = next_sequence
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(frame)).encode("ascii")
                        + b"\r\n\r\n"
                        + frame
                        + b"\r\n"
                    )
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, _format: str, *args: object) -> None:
            pass

    return Handler


def bind_server(host: str, preferred_port: int, handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    last_error: OSError | None = None
    for port in range(preferred_port, preferred_port + 20):
        try:
            return ThreadingHTTPServer((host, port), handler)
        except OSError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def selftest() -> None:
    assert command_header(CMD_FB_SIZE, 12) == b"\x30\x81\x0c\x00\x00\x00"
    assert is_jpeg(b"\xff\xd8test\xff\xd9")
    assert not is_jpeg(b"not a jpeg")
    assert b"/stream.mjpg" in PAGE and b"aspect-ratio:4/3" in PAGE


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", help="SYSUOS USB debug serial device (auto-detected by default)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        print("ok")
        return 0

    camera = Camera(args.serial)
    server = bind_server(args.host, args.port, make_handler(camera))
    camera.start()
    port = server.server_address[1]
    print(f"SYSUOS 实时画面: http://127.0.0.1:{port}", flush=True)

    def stop(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        camera.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import gc
import os
import sys
import time


RESULT_PATH = "/sdcard/sysu_board_test_result.txt"
APP_PATH = "/sdcard/apps"
_results = []
_log = None


def _text(value):
    return str(value).replace("\n", " ").replace("|", "/")


def _emit(name, status, detail=""):
    line = "SYSU_TEST|%s|%s|%s" % (name, status, _text(detail))
    print(line)
    _results.append((name, status, _text(detail)))
    _log.write(line + "\n")
    _log.flush()


def _run(name, function):
    started = time.ticks_ms()
    try:
        value = function()
        if value is False:
            raise RuntimeError("returned False")
        _emit(name, "PASS", "%d ms" % time.ticks_diff(time.ticks_ms(), started))
    except Exception as exc:
        _emit(name, "FAIL", "%s: %s" % (type(exc).__name__, exc))


def _runtime():
    gc.collect()
    return sys.implementation.name == "micropython" and gc.mem_free() > 0


def _product():
    with open("/sdcard/sysu_product.json", "r") as handle:
        return "sysuos_k230_v3p0" in handle.read()


def _storage():
    path = "/sdcard/.sysu_storage_test"
    payload = "SYSU_STORAGE_PASS"
    with open(path, "w") as handle:
        handle.write(payload)
    with open(path, "r") as handle:
        passed = handle.read() == payload
    os.remove(path)
    return passed


def _module(name):
    __import__(name)
    return True


def _app(name):
    if APP_PATH not in sys.path:
        sys.path.append(APP_PATH)
    module = __import__(name)
    return module.main()


def main():
    global _log
    _results[:] = []
    _log = open(RESULT_PATH, "w")
    try:
        _log.write("SYSU_BOARD_TEST_BEGIN\n")
        _log.flush()
        _run("runtime", _runtime)
        _run("product", _product)
        _run("storage", _storage)
        _run("ulab", lambda: _module("ulab.numpy"))
        _run("network", lambda: _module("network"))
        _run("machine", lambda: _module("machine"))
        _run("display", lambda: _app("sysu_hil_display"))
        _run("camera", lambda: _app("sysu_hil_camera"))
        _run("kpu", lambda: _app("sysu_hil_kpu"))
        failed = sum(1 for _, status, _ in _results if status == "FAIL")
        marker = "SYSU_BOARD_TEST_PASS" if failed == 0 else "SYSU_BOARD_TEST_FAIL"
        summary = "%s|total=%d|failed=%d" % (marker, len(_results), failed)
        print(summary)
        _log.write(summary + "\n")
        _log.flush()
        return failed == 0
    finally:
        _log.close()
        _log = None
        gc.collect()


if __name__ == "__main__":
    main()

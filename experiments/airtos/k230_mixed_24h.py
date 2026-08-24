import gc
import sys
import time

import nncase_runtime as nn
import ulab.numpy as np
from media.media import MediaManager


APP_PATH = "/sdcard/apps"
FACE_MODEL = "/sdcard/examples/18-NNCase/face_detection/face_detection_320.kmodel"
FACE_INPUT = "/sdcard/examples/18-NNCase/face_detection/face_detection_ai2d_output.bin"
LOG_PATH = "/sdcard/airtos/mixed_24h.log"
CAMERA_RESTART_FRAMES = 3600
CAMERA_RESTART_LIMIT = 1

if APP_PATH not in sys.path:
    sys.path.append(APP_PATH)

from libs.PipeLine import PipeLine
from sysu_object_detector import MODEL_SIZE, ObjectDetector


def _emit(log, message):
    print(message)
    log.write(message + "\n")
    log.flush()


def _open_face(input_data):
    session = nn.kpu()
    session.load_kmodel(FACE_MODEL)
    tensor = nn.from_numpy(input_data)
    return session, tensor


def _close_face(session):
    if session is not None:
        del session
    nn.shrink_memory_pool()
    gc.collect()


def main(duration_seconds=86400, heartbeat_seconds=60):
    with open(FACE_INPUT, "rb") as handle:
        face_input = np.frombuffer(handle.read(), dtype=np.uint8).reshape((1, 3, 320, 320))
    log = open(LOG_PATH, "w")
    pipe = None
    detector = None
    face_session = None
    face_tensor = None
    started = time.ticks_ms()
    last_heartbeat = started
    frames = 0
    object_inferences = 0
    face_inferences = 0
    camera_restarts = 0
    kpu_restarts = 0
    frame_failures = 0
    inference_failures = 0
    ide_interrupts = 0
    lifecycle_failures = 0
    maximum_frame_ms = 0
    frame = None
    try:
        pipe = PipeLine(rgb888p_size=MODEL_SIZE, display_mode="virt", display_size=[320, 240])
        pipe.create(to_ide=False, fps=15)
        detector = ObjectDetector()
        face_session, face_tensor = _open_face(face_input)
        _emit(log, "AIRTOS_K230_MIXED_START duration_seconds=%d heartbeat_seconds=%d models=2" %
              (duration_seconds, heartbeat_seconds))
        while time.ticks_diff(time.ticks_ms(), started) < duration_seconds * 1000:
            frame_started = time.ticks_ms()
            try:
                frame = pipe.get_frame()
                if frame is None:
                    raise RuntimeError("camera returned no frame")
                detector.run(frame)
                detector.cur_img = None
                frame = None
                object_inferences += 1
                if frames % 10 == 0:
                    face_session.set_input_tensor(0, face_tensor)
                    face_session.run()
                    output = face_session.get_output_tensor(0).to_numpy()
                    if output.size == 0:
                        raise RuntimeError("face model returned empty output")
                    face_inferences += 1
                frames += 1
            except Exception as exc:
                if str(exc) == "IDE interrupt":
                    ide_interrupts += 1
                    _emit(log, "AIRTOS_K230_MIXED_IDE_INTERRUPT frame=%d count=%d" % (frames, ide_interrupts))
                    continue
                frame_failures += 1
                inference_failures += 1
                _emit(log, "AIRTOS_K230_MIXED_ERROR frame=%d detail=%s" % (frames, exc))
                break
            elapsed = time.ticks_diff(time.ticks_ms(), frame_started)
            if elapsed > maximum_frame_ms:
                maximum_frame_ms = elapsed
            if frames % 900 == 0:
                try:
                    previous_face = face_session
                    face_session = None
                    face_tensor = None
                    _close_face(previous_face)
                    face_session, face_tensor = _open_face(face_input)
                    kpu_restarts += 1
                except Exception as exc:
                    lifecycle_failures += 1
                    _emit(log, "AIRTOS_K230_MIXED_LIFECYCLE_ERROR kind=kpu detail=%s" % exc)
                    break
            if camera_restarts < CAMERA_RESTART_LIMIT and frames % CAMERA_RESTART_FRAMES == 0:
                try:
                    detector.cur_img = None
                    detector.deinit()
                    detector = None
                    frame = None
                    gc.collect()
                    pipe.destroy()
                    MediaManager.deinit()
                    pipe = PipeLine(rgb888p_size=MODEL_SIZE, display_mode="virt", display_size=[320, 240])
                    pipe.create(to_ide=False, fps=15)
                    detector = ObjectDetector()
                    camera_restarts += 1
                    kpu_restarts += 1
                except Exception as exc:
                    lifecycle_failures += 1
                    _emit(log, "AIRTOS_K230_MIXED_LIFECYCLE_ERROR kind=camera_kpu detail=%s" % exc)
                    break
            now = time.ticks_ms()
            if time.ticks_diff(now, last_heartbeat) >= heartbeat_seconds * 1000:
                _emit(log, "AIRTOS_K230_MIXED_HEARTBEAT elapsed_seconds=%d frames=%d object_inferences=%d "
                      "face_inferences=%d camera_restarts=%d kpu_restarts=%d frame_failures=%d "
                      "inference_failures=%d ide_interrupts=%d lifecycle_failures=%d maximum_frame_ms=%d" %
                      (time.ticks_diff(now, started) // 1000, frames, object_inferences, face_inferences,
                       camera_restarts, kpu_restarts, frame_failures, inference_failures,
                       ide_interrupts, lifecycle_failures, maximum_frame_ms))
                last_heartbeat = now
            gc.collect()
        elapsed_seconds = time.ticks_diff(time.ticks_ms(), started) // 1000
        _emit(log, "AIRTOS_K230_MIXED_RESULT elapsed_seconds=%d frames=%d object_inferences=%d "
              "face_inferences=%d camera_restarts=%d kpu_restarts=%d frame_failures=%d "
              "inference_failures=%d ide_interrupts=%d lifecycle_failures=%d maximum_frame_ms=%d" %
              (elapsed_seconds, frames, object_inferences, face_inferences, camera_restarts, kpu_restarts,
               frame_failures, inference_failures, ide_interrupts, lifecycle_failures, maximum_frame_ms))
        if elapsed_seconds >= duration_seconds and frame_failures == 0 and inference_failures == 0 and lifecycle_failures == 0:
            _emit(log, "AIRTOS_K230_MIXED_PASS")
        else:
            _emit(log, "AIRTOS_K230_MIXED_FAIL")
    finally:
        if detector is not None:
            detector.cur_img = None
            detector.deinit()
            detector = None
        frame = None
        gc.collect()
        if pipe is not None:
            pipe.destroy()
            MediaManager.deinit()
            pipe = None
        face_tensor = None
        _close_face(face_session)
        log.close()

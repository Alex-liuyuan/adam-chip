import gc
import os
import time

import aidemo
import nncase_runtime as nn
import ulab.numpy as np
from libs.AI2D import Ai2d
from libs.AIBase import AIBase
from libs.PipeLine import PipeLine


MODEL = "/sdcard/examples/kmodel/face_detection_320.kmodel"
ANCHORS = "/sdcard/examples/utils/prior_data_320.bin"
MODEL_SIZE = [320, 320]
CAMERA_SIZE = [640, 480]
DISPLAY_SIZE = [640, 480]
CONFIDENCE = 0.5
NMS = 0.2


class FaceDetector(AIBase):
    def __init__(self, anchors):
        super().__init__(MODEL, MODEL_SIZE, CAMERA_SIZE)
        self.anchors = anchors
        self.rgb888p_size = CAMERA_SIZE
        self.ai2d = Ai2d(0)
        self.ai2d.set_ai2d_dtype(
            nn.ai2d_format.NCHW_FMT,
            nn.ai2d_format.NCHW_FMT,
            np.uint8,
            np.uint8,
        )

    def configure(self):
        src_w, src_h = self.rgb888p_size
        scale = min(MODEL_SIZE[0] / src_w, MODEL_SIZE[1] / src_h)
        resized_w, resized_h = int(src_w * scale), int(src_h * scale)
        left = (MODEL_SIZE[0] - resized_w) // 2
        top = (MODEL_SIZE[1] - resized_h) // 2
        right = MODEL_SIZE[0] - resized_w - left
        bottom = MODEL_SIZE[1] - resized_h - top
        self.ai2d.pad([0, 0, 0, 0, top, bottom, left, right], 0, [104, 117, 123])
        self.ai2d.resize(nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
        self.ai2d.build([1, 3, src_h, src_w], [1, 3, MODEL_SIZE[1], MODEL_SIZE[0]])

    def postprocess(self, results):
        detections = aidemo.face_det_post_process(
            CONFIDENCE,
            NMS,
            MODEL_SIZE[1],
            self.anchors,
            self.rgb888p_size,
            results,
        )
        return detections[0] if detections else []


def draw(pipe, detections, fps):
    pipe.osd_img.clear()
    for detection in detections:
        x, y, width, height = [int(round(value)) for value in detection[:4]]
        pipe.osd_img.draw_rectangle(x, y, width, height, color=(255, 32, 220, 64), thickness=3)
    pipe.osd_img.draw_string_advanced(
        8,
        8,
        20,
        "KPU FACE  %d  %.1f FPS" % (len(detections), fps),
        color=(255, 255, 255, 255),
    )


def main():
    anchors = np.fromfile(ANCHORS, dtype=np.float).reshape((4200, 4))
    pipe = PipeLine(rgb888p_size=CAMERA_SIZE, display_mode="virt", display_size=DISPLAY_SIZE)
    detector = None
    try:
        pipe.create(to_ide=True, fps=30)
        detector = FaceDetector(anchors)
        detector.configure()
        frames = 0
        started = time.ticks_ms()
        print("SYSU_FACE_DETECTOR_READY")
        while True:
            os.exitpoint()
            detections = detector.run(pipe.get_frame())
            frames += 1
            elapsed = max(1, time.ticks_diff(time.ticks_ms(), started))
            fps = frames * 1000 / elapsed
            draw(pipe, detections, fps)
            pipe.show_image()
            if frames == 1 or frames % 30 == 0:
                print("SYSU_FACE_DETECTION faces=%d fps=%.1f" % (len(detections), fps))
            gc.collect()
    except KeyboardInterrupt:
        pass
    finally:
        if detector is not None:
            detector.deinit()
        pipe.destroy()


if __name__ == "__main__":
    main()

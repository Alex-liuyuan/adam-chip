import gc
import os
import time

import aidemo
import nncase_runtime as nn
from libs.AIBase import AIBase
from libs.PipeLine import PipeLine
from libs.Utils import get_colors


MODEL = "/sdcard/examples/kmodel/yolov8n_224.kmodel"
MODEL_SIZE = [224, 224]
DISPLAY_SIZE = [640, 480]
CONFIDENCE = 0.3
NMS = 0.4
MAX_BOXES = 30
LABELS = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
    "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich",
    "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
    "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
]


class ObjectDetector(AIBase):
    def __init__(self):
        super().__init__(MODEL, MODEL_SIZE, MODEL_SIZE)

    def preprocess(self, image):
        return [nn.from_numpy(image)]

    def postprocess(self, results):
        output = results[0][0].transpose()
        return aidemo.yolov8_det_postprocess(
            output.copy(),
            [MODEL_SIZE[1], MODEL_SIZE[0]],
            [MODEL_SIZE[1], MODEL_SIZE[0]],
            [DISPLAY_SIZE[1], DISPLAY_SIZE[0]],
            len(LABELS),
            CONFIDENCE,
            NMS,
            MAX_BOXES,
        )


def draw(pipe, detections, colors, fps):
    pipe.osd_img.clear()
    count = len(detections[0]) if detections else 0
    if detections:
        boxes, classes, scores = detections
        for index in range(count):
            x, y, width, height = [int(round(value)) for value in boxes[index]]
            class_id = classes[index]
            color = colors[class_id]
            pipe.osd_img.draw_rectangle(x, y, width, height, color=color, thickness=3)
            pipe.osd_img.draw_string_advanced(
                x,
                max(0, y - 24),
                20,
                "%s %.2f" % (LABELS[class_id], scores[index]),
                color=color,
            )
    pipe.osd_img.draw_string_advanced(
        8, 8, 20, "KPU OBJECTS %d  %.1f FPS" % (count, fps), color=(255, 255, 255, 255)
    )
    return count


def main():
    pipe = PipeLine(rgb888p_size=MODEL_SIZE, display_mode="virt", display_size=DISPLAY_SIZE)
    detector = None
    try:
        pipe.create(to_ide=True, fps=30)
        detector = ObjectDetector()
        colors = get_colors(len(LABELS))
        frames = 0
        started = time.ticks_ms()
        print("SYSU_OBJECT_DETECTOR_READY")
        while True:
            os.exitpoint()
            detections = detector.run(pipe.get_frame())
            frames += 1
            elapsed = max(1, time.ticks_diff(time.ticks_ms(), started))
            fps = frames * 1000 / elapsed
            count = draw(pipe, detections, colors, fps)
            pipe.show_image()
            if frames == 1 or frames % 30 == 0:
                print("SYSU_OBJECT_DETECTION objects=%d fps=%.1f" % (count, fps))
            gc.collect()
    except KeyboardInterrupt:
        pass
    finally:
        if detector is not None:
            detector.deinit()
        pipe.destroy()


if __name__ == "__main__":
    main()

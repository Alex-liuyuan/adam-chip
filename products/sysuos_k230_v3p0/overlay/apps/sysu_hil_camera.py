import time
from media.sensor import Sensor


def main():
    sensor = Sensor()
    try:
        sensor.reset()
        sensor.set_framesize(width=320, height=240)
        sensor.set_pixformat(Sensor.RGB565)
        sensor.run()
        time.sleep_ms(200)
        frame = sensor.snapshot()
        if frame.width() == 320 and frame.height() == 240:
            print("SYSU_CAMERA_FRAME_PASS")
            return True
        print("SYSU_CAMERA_FRAME_FAIL")
        return False
    finally:
        sensor.stop()


if __name__ == "__main__":
    main()

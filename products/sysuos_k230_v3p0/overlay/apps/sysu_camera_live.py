import time

from media.display import Display
from media.media import MediaManager
from media.sensor import Sensor


def main(seconds=0):
    sensor = Sensor()
    started = time.ticks_ms()
    frames = 0

    try:
        sensor.reset()
        sensor.set_framesize(width=320, height=240)
        sensor.set_pixformat(Sensor.RGB565)
        Display.init(Display.VIRT, width=320, height=240, to_ide=True)
        MediaManager.init()
        sensor.run()

        while not seconds or time.ticks_diff(time.ticks_ms(), started) < seconds * 1000:
            frame = sensor.snapshot()
            Display.show_image(frame)
            frames += 1
            if frames % 30 == 0:
                elapsed = time.ticks_diff(time.ticks_ms(), started)
                print("SYSU_CAMERA_LIVE|frames=%d|fps=%.1f" % (frames, frames * 1000 / elapsed))
    except KeyboardInterrupt:
        pass
    finally:
        sensor.stop()
        Display.deinit()
        MediaManager.deinit()

    elapsed = max(1, time.ticks_diff(time.ticks_ms(), started))
    print("SYSU_CAMERA_LIVE_PASS|frames=%d|fps=%.1f" % (frames, frames * 1000 / elapsed))
    return frames > 0


if __name__ == "__main__":
    main()

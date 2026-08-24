import time
import image
from media.display import Display


def main():
    frame = image.Image(320, 240, image.ARGB8888)
    try:
        Display.init(Display.VIRT, width=320, height=240, to_ide=True)
        frame.clear()
        frame.draw_string_advanced(8, 8, 24, "SYSU HIL", color=(255, 255, 255))
        Display.show_image(frame)
        time.sleep_ms(200)
        print("SYSU_DISPLAY_VIRT_PASS")
        return True
    finally:
        Display.deinit()


if __name__ == "__main__":
    main()

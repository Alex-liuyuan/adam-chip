import gc
import nncase_runtime as nn
import ulab.numpy as np


MODEL = "/sdcard/examples/18-NNCase/face_detection/face_detection_320.kmodel"
INPUT = "/sdcard/examples/18-NNCase/face_detection/face_detection_ai2d_output.bin"


def main():
    kpu = nn.kpu()
    try:
        kpu.load_kmodel(MODEL)
        with open(INPUT, "rb") as handle:
            data = np.frombuffer(handle.read(), dtype=np.uint8).reshape((1, 3, 320, 320))
        kpu.set_input_tensor(0, nn.from_numpy(data))
        kpu.run()
        output = kpu.get_output_tensor(0).to_numpy()
        if output.size > 0:
            print("SYSU_KPU_OUTPUT_PASS")
            return True
        print("SYSU_KPU_OUTPUT_FAIL")
        return False
    finally:
        del kpu
        gc.collect()
        nn.shrink_memory_pool()


if __name__ == "__main__":
    main()

import sys

import cv2
import torch


def main() -> None:
    print("Python:", sys.version)
    print("Torch:", torch.__version__)
    print("MPS available:", torch.backends.mps.is_available())
    print("OpenCV:", cv2.__version__)


if __name__ == "__main__":
    main()

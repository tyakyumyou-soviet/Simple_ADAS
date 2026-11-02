from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a small synthetic ADAS demo video.")
    parser.add_argument("--output", default="data/videos/demo_synthetic.mp4")
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--fps", type=float, default=20.0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output), fourcc, args.fps, (args.width, args.height))
    if not writer.isOpened():
        raise RuntimeError(f"Cannot write demo video: {output}")
    for idx in range(args.frames):
        writer.write(make_frame(args.width, args.height, idx, args.frames))
    writer.release()
    print(output)


def make_frame(width: int, height: int, idx: int, total: int) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    horizon = int(height * 0.42)
    frame[:horizon, :] = (180, 205, 220)
    frame[horizon:, :] = (55, 58, 60)
    cv2.rectangle(frame, (0, horizon), (width, height), (50, 55, 52), -1)
    cv2.rectangle(frame, (0, horizon), (int(width * 0.18), height), (95, 90, 78), -1)
    cv2.rectangle(frame, (int(width * 0.82), horizon), (width, height), (95, 90, 78), -1)

    left_bottom = (int(width * 0.31), height - 1)
    left_top = (int(width * 0.46), horizon + 10)
    right_top = (int(width * 0.54), horizon + 10)
    right_bottom = (int(width * 0.69), height - 1)
    cv2.line(frame, left_bottom, left_top, (230, 230, 210), 5)
    cv2.line(frame, right_bottom, right_top, (230, 230, 210), 5)
    for y in range(horizon + 35, height, 46):
        cv2.line(frame, (width // 2, y), (width // 2, min(height, y + 24)), (210, 210, 190), 3)

    car_y = int(height * (0.50 + 0.28 * idx / max(total - 1, 1)))
    car_w = int(width * (0.08 + 0.05 * idx / max(total - 1, 1)))
    car_h = int(car_w * 0.62)
    car_x = width // 2 - car_w // 2
    cv2.rectangle(frame, (car_x, car_y), (car_x + car_w, car_y + car_h), (40, 90, 210), -1)
    cv2.rectangle(frame, (car_x + 8, car_y + 6), (car_x + car_w - 8, car_y + car_h // 2), (25, 35, 55), -1)
    cv2.circle(frame, (car_x + 10, car_y + car_h), 5, (15, 15, 15), -1)
    cv2.circle(frame, (car_x + car_w - 10, car_y + car_h), 5, (15, 15, 15), -1)

    person_x = int(width * 0.15 + width * 0.28 * idx / max(total - 1, 1))
    person_y = int(height * 0.73)
    cv2.circle(frame, (person_x, person_y - 28), 9, (40, 55, 170), -1)
    cv2.line(frame, (person_x, person_y - 18), (person_x, person_y + 18), (40, 55, 170), 4)
    cv2.line(frame, (person_x, person_y + 18), (person_x - 12, person_y + 38), (35, 35, 35), 3)
    cv2.line(frame, (person_x, person_y + 18), (person_x + 12, person_y + 38), (35, 35, 35), 3)

    signal_x = int(width * 0.72)
    signal_y = int(height * 0.18)
    cv2.rectangle(frame, (signal_x - 18, signal_y - 12), (signal_x + 18, signal_y + 52), (25, 25, 25), -1)
    cv2.circle(frame, (signal_x, signal_y), 8, (0, 0, 230), -1)
    cv2.circle(frame, (signal_x, signal_y + 20), 8, (50, 50, 70), -1)
    cv2.circle(frame, (signal_x, signal_y + 40), 8, (40, 70, 40), -1)
    cv2.line(frame, (signal_x, signal_y + 52), (signal_x, horizon + 25), (50, 50, 50), 3)

    return frame


if __name__ == "__main__":
    main()

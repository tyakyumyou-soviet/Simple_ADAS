"""Generate camera intrinsics for Plan A IPM lane detection from chessboard photos."""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate a USB camera from chessboard images.")
    parser.add_argument("images", help="Glob pattern, e.g. data/calibration/*.jpg")
    parser.add_argument("--pattern", default="9x6", help="Inner chessboard corners as COLSxROWS")
    parser.add_argument("--square-mm", type=float, default=25.0)
    parser.add_argument("--output", default="outputs/logs/camera_calibration.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cols, rows = (int(value) for value in args.pattern.lower().split("x", maxsplit=1))
    object_points = np.zeros((rows * cols, 3), np.float32)
    object_points[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * args.square_mm
    object_sets: list[np.ndarray] = []
    image_sets: list[np.ndarray] = []
    image_size: tuple[int, int] | None = None
    for raw_path in sorted(glob.glob(args.images)):
        image = cv2.imread(raw_path)
        if image is None:
            continue
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCorners(gray, (cols, rows))
        if not found:
            continue
        refined = cv2.cornerSubPix(
            gray, corners, (11, 11), (-1, -1),
            (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001),
        )
        object_sets.append(object_points)
        image_sets.append(refined)
        image_size = (gray.shape[1], gray.shape[0])
    if image_size is None or len(object_sets) < 8:
        raise RuntimeError("At least 8 chessboard images with detected corners are required")
    rms, matrix, distortion, _, _ = cv2.calibrateCamera(object_sets, image_sets, image_size, None, None)
    report = {
        "images_used": len(object_sets),
        "image_size": list(image_size),
        "rms_reprojection_error": float(rms),
        "camera_matrix": matrix.reshape(-1).tolist(),
        "distortion_coeffs": distortion.reshape(-1).tolist(),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

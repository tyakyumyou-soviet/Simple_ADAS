from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train YOLO11 Japanese traffic signal/sign detector.")
    parser.add_argument("--data", required=True, help="YOLO dataset yaml path")
    parser.add_argument("--weights", default="yolo11s.pt")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--project", default="outputs/sign_training")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_path = Path(args.data)
    if not data_path.exists():
        raise FileNotFoundError(f"Dataset yaml not found: {data_path}")
    from ultralytics import YOLO

    model = YOLO(args.weights)
    model.train(data=str(data_path), epochs=args.epochs, imgsz=args.imgsz, project=args.project)
    model.val(data=str(data_path), imgsz=args.imgsz, project=args.project)


if __name__ == "__main__":
    main()

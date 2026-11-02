"""車載統合アプリの起動コマンド。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from main_window import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="車載統合システム")
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("車載統合システム")
    window = MainWindow(config_path=args.config)
    if window.runtime.config.get("fullscreen", False):
        window.showFullScreen()
    else:
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

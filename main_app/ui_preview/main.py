"""Macで統合画面の構成を確認するための起動口。"""
from __future__ import annotations

import sys
from PySide6.QtWidgets import QApplication
from main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("車載統合システム")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

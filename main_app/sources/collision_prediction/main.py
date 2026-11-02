from __future__ import annotations

import os
import sys
from argparse import ArgumentParser
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.utils.config import resolve_config_path
from src.utils.logger import configure_logging


def default_config_path() -> str:
    return 'config/pi_async_ai_hat_2.yaml'


def main() -> None:
    launch_cwd = Path.cwd()
    project_root = Path(__file__).resolve().parent
    parser = ArgumentParser(description="簡易ADAS")
    parser.add_argument("--config", default=default_config_path(), help="設定 YAML のパス")
    args = parser.parse_args()
    config_path = resolve_config_path(args.config, launch_cwd, project_root)
    # モデル/設定/出力の相対パスを、起動ディレクトリではなくプロジェクト基準に固定する。
    os.chdir(project_root)
    configure_logging()
    app = QApplication(sys.argv)
    if "Noto Sans CJK JP" in QFontDatabase.families():
        app.setFont(QFont("Noto Sans CJK JP"))
    window = MainWindow(str(config_path))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

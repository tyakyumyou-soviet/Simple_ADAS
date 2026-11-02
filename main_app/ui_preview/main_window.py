"""７インチのタッチ画面を想定した、統合UIの開発用プレビュー。"""
from __future__ import annotations

from pathlib import Path
import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)
from video_backend import make_video_worker
from icons import button_icon

ASSETS = Path(__file__).resolve().parent / "assets"
PROJECT = Path(__file__).resolve().parent.parent / "sources" / "collision_prediction"

STYLE = """
QMainWindow, QWidget#root { background: #0b1119; color: #edf3f6; }
QLabel { color: #e8eff3; background: transparent; }
QFrame#header { background: #111c27; border: 1px solid #243443; border-radius: 13px; }
QFrame#videoCard, QFrame#sideCard, QFrame#settingsCard { background: #111c27; border: 1px solid #263746; border-radius: 14px; }
QFrame#divider { background: #2a3b49; max-height: 1px; border: none; }
QLabel#brand { color: #f3f8fa; font-size: 20px; font-weight: 700; }
QLabel#eyebrow { color: #7eabb8; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QLabel#headerHint, QLabel#muted { color: #a3b5c0; font-size: 14px; }
QLabel#cardTitle { color: #eef5f7; font-size: 17px; font-weight: 700; }
QLabel#smallTitle { color: #b5c8d0; font-size: 14px; font-weight: 600; }
QLabel#value { color: #f0f5f6; font-size: 17px; font-weight: 700; }
QLabel#badge { color: #d2dfe3; background: #263644; border: 1px solid #344b58; border-radius: 8px; padding: 5px 10px; font-size: 14px; font-weight: 600; }
QLabel#video { color: #a2b7c1; background: #080e14; border: 1px solid #263745; border-radius: 10px; font-size: 17px; }
QPushButton { background: #243442; color: #edf4f6; border: 1px solid #3a5060; border-radius: 11px; padding: 8px 10px; font-size: 18px; font-weight: 600; }
QPushButton[navButton="true"] { padding: 0px; }
QPushButton:hover { background: #2b4350; }
QPushButton:pressed { background: #365963; }
QPushButton:checked { background: #315c5e; border-color: #76c8bd; }
QPushButton:disabled { color: #8f9fa9; background: #1c2934; border-color: #2c3d49; }
QPushButton#primary { background: #8ad6cc; color: #10222a; border: 1px solid #a3e6dc; }
QPushButton#primary:pressed { background: #6dbbb0; }
QPushButton#navActive { background: #315c5e; border-color: #5ea69e; color: #f1fffd; }
QLabel#status { color: #f2f6f6; background: rgba(0, 0, 0, 175); border-radius: 4px; padding: 4px 7px; font-size: 12px; font-weight: 600; }
QLabel#overlay { color: #f2f6f6; background: rgba(0, 0, 0, 175); border-radius: 4px; padding: 4px 7px; font-size: 13px; font-weight: 600; }
"""


def text_label(text: str, name: str, parent=None) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName(name)
    return label


def card(name: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName(name)
    return frame


class MainWindow(QMainWindow):
    def __init__(self, project: Path = PROJECT) -> None:
        super().__init__()
        self.project = project
        self.worker = None
        self.worker_error = None
        self.reverse = False
        self.setWindowTitle("車載統合システム - 開発画面")
        self.resize(1024, 600)
        self.setMinimumSize(720, 440)
        self.setStyleSheet(STYLE)
        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(8)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_home())
        self.pages.addWidget(self._build_settings())
        outer.addWidget(self.pages, 1)

        nav = QHBoxLayout()
        nav.setSpacing(8)
        self.reverse_button = self._nav_button("リバース画面に切り替える", "reverse")
        self.reverse_button.setCheckable(True)
        self.reverse_button.setIconSize(QSize(34, 34))
        self.event_button = self._nav_button("手動イベント録画（未接続）", "event")
        self.settings_button = self._nav_button("設定と転送", "settings")
        self.event_button.setEnabled(False)
        for button in (self.reverse_button, self.event_button, self.settings_button):
            nav.addWidget(button, 1)
        outer.insertLayout(0, nav)
        self.reverse_button.clicked.connect(self.toggle_reverse)
        self.settings_button.clicked.connect(self.toggle_settings)
        self.open_video_button.clicked.connect(self.choose_video)
        self.stop_video_button.clicked.connect(self.stop_video)
        self._set_navigation(False)

    def _build_home(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        video_card = card("videoCard")
        video_layout = QVBoxLayout(video_card)
        video_layout.setContentsMargins(10, 8, 10, 8)
        video_layout.setSpacing(8)
        self.video_label = QLabel("フロント映像：未接続\n録画・解析プログラム：未接続", objectName="video")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setWordWrap(True)
        self.video_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        overlays = QGridLayout(self.video_label)
        overlays.setContentsMargins(8, 8, 8, 8)
        overlays.setSpacing(6)
        self.camera_heading = text_label("フロントカメラ", "overlay")
        self.camera_badge = text_label("映像 未接続", "overlay")
        self.status_label = text_label("前後録画：未接続   AI：未接続   センサー：未接続", "status")
        self.distance_label = text_label("距離  左 --  /  右 --", "overlay")
        overlays.addWidget(self.camera_heading, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        overlays.addWidget(self.camera_badge, 0, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        overlays.setRowStretch(1, 1)
        overlays.addWidget(self.status_label, 2, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        overlays.addWidget(self.distance_label, 2, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        video_layout.addWidget(self.video_label, 1)
        layout.addWidget(video_card, 1)

        return page

    def _build_settings(self) -> QWidget:
        page = card("settingsCard")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(8)
        layout.addWidget(text_label("設定・転送", "cardTitle"))
        note = text_label("各機能は接続後に利用できます。", "muted")
        layout.addWidget(note)
        self.transfer_button = QPushButton("動画をスマートフォンに転送　｜　未接続")
        self.transfer_button.setAccessibleName("動画転送、未接続")
        self.transfer_button.setMinimumHeight(54)
        self.transfer_button.setEnabled(False)
        layout.addWidget(self.transfer_button)
        self.shutdown_button = QPushButton("電源停止　｜　未接続")
        self.shutdown_button.setMinimumHeight(54)
        self.shutdown_button.setEnabled(False)
        layout.addWidget(self.shutdown_button)
        layout.addSpacing(5)
        layout.addWidget(text_label("Macでの動作確認", "smallTitle"))
        self.open_video_button = QPushButton("動画ファイルを開く")
        self.open_video_button.setObjectName("primary")
        self.open_video_button.setMinimumHeight(54)
        self.stop_video_button = QPushButton("動画表示を停止")
        self.stop_video_button.setMinimumHeight(54)
        self.stop_video_button.setEnabled(False)
        row = QHBoxLayout()
        row.addWidget(self.open_video_button, 1)
        row.addWidget(self.stop_video_button, 1)
        layout.addLayout(row)
        info = text_label("確認用の動画表示です。録画とAI解析は動作しません。", "muted")
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addStretch()
        return page

    def _nav_button(self, accessible_name: str, icon_name: str) -> QPushButton:
        button = QPushButton()
        button.setProperty("navButton", True)
        button.setIcon(button_icon(icon_name))
        button.setIconSize(QSize(40, 40))
        button.setMinimumHeight(48)
        button.setAccessibleName(accessible_name)
        return button

    def _set_navigation(self, settings: bool) -> None:
        self.settings_button.setIcon(button_icon("back" if settings else "settings"))
        self.settings_button.setAccessibleName("映像画面に戻る" if settings else "設定と転送")
        self.settings_button.setObjectName("navActive" if settings else "")
        self.settings_button.style().unpolish(self.settings_button)
        self.settings_button.style().polish(self.settings_button)

    def toggle_settings(self) -> None:
        if self.pages.currentIndex() == 1:
            self.show_home()
        else:
            self.show_settings()

    def show_home(self) -> None:
        self.pages.setCurrentIndex(0)
        self._set_navigation(False)

    def show_settings(self) -> None:
        self.pages.setCurrentIndex(1)
        self._set_navigation(True)

    def toggle_reverse(self) -> None:
        if self.worker is not None:
            return
        self.reverse = not self.reverse
        self.reverse_button.setChecked(self.reverse)
        self.reverse_button.setIcon(button_icon("front" if self.reverse else "reverse"))
        self.reverse_button.setAccessibleName("フロント画面に戻す" if self.reverse else "リバース画面に切り替える")
        camera = "リア" if self.reverse else "フロント"
        self.camera_heading.setText(f"{camera}カメラ")
        self.video_label.setText(f"{camera}映像：未接続\n録画・解析プログラム：未接続")
        self.show_home()

    def choose_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "表示する動画を選択", "", "動画 (*.mp4 *.mov *.mkv *.avi);;全ファイル (*)")
        if path:
            self.start_video(Path(path))

    def start_video(self, path: Path) -> bool:
        if self.worker is not None:
            return False
        try:
            worker = make_video_worker(self.project, path)
        except Exception as exc:
            self.video_label.clear()
            self.video_label.setText(f"動画を開けません: {exc}")
            self.show_home()
            return False
        self.worker = worker
        self.worker_error = None
        self.open_video_button.setEnabled(False)
        self.stop_video_button.setEnabled(True)
        self.reverse_button.setEnabled(False)
        self.camera_heading.setText("動画プレビュー")
        self.camera_badge.setText("確認用")
        self.video_label.setText("動画を準備中")
        self.status_label.setText("動画準備中   録画・AI・センサー：未接続")
        self.show_home()
        worker.frame_ready.connect(self.on_video_frame)
        worker.error.connect(self.on_video_error)
        worker.finished.connect(self.on_video_finished)
        worker.start()
        return True

    def on_video_frame(self, frame: np.ndarray, _meta: dict) -> None:
        if self.sender() is not self.worker:
            return
        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        h, w = rgb.shape[:2]
        image = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888).copy()
        self.video_label.setPixmap(QPixmap.fromImage(image).scaled(
            self.video_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        self.status_label.setText("動画表示中   録画・AI・センサー：未接続")

    def on_video_error(self, message: str) -> None:
        if self.sender() is self.worker:
            self.worker_error = message

    def on_video_finished(self) -> None:
        if self.sender() is not self.worker:
            return
        self.worker = None
        self.video_label.clear()
        self.video_label.setText(f"動画表示エラー: {self.worker_error}" if self.worker_error else "動画表示：終了")
        self.camera_heading.setText("リアカメラ" if self.reverse else "フロントカメラ")
        self.camera_badge.setText("映像 未接続")
        self.status_label.setText("前後録画：未接続   AI：未接続   センサー：未接続")
        self.open_video_button.setEnabled(True)
        self.stop_video_button.setEnabled(False)
        self.reverse_button.setEnabled(True)

    def stop_video(self) -> None:
        if self.worker is not None:
            self.stop_video_button.setEnabled(False)
            self.status_label.setText("動画停止中   録画・AI・センサー：未接続")
            self.worker.stop()

    def closeEvent(self, event) -> None:
        if self.worker is not None:
            self.worker.stop()
            if not self.worker.wait(5000):
                self.status_label.setText("動画の停止を待っています")
                event.ignore()
                return
        event.accept()

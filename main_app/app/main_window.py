"""ラズパイの7インチタッチ画面向け車載統合UI。"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import sys
from PySide6.QtCore import QSize, Qt, QProcess, QTimer, QSettings
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QInputDialog, QDialog,
    QComboBox, QPushButton, QSlider, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)
from video_backend import make_video_worker
from icons import button_icon
from runtime import RuntimeController
from touch_choices import TouchComboBox, choose
from device_controls import AudioVolumeControl, BacklightControl

ASSETS = Path(__file__).resolve().parent / "assets"
PROJECT = Path(__file__).resolve().parent.parent / "sources" / "collision_prediction"

STYLE = """
QMainWindow, QWidget#root { background: #0b1119; color: #edf3f6; }
QDialog { background: #111c27; color: #edf3f6; }
QDialog QLabel { font-size: 14px; }
QLabel { color: #e8eff3; background: transparent; }
QFrame#header { background: #111c27; border: 1px solid #243443; border-radius: 13px; }
QFrame#videoCard, QFrame#sideCard, QFrame#settingsCard { background: #111c27; border: 1px solid #263746; border-radius: 14px; }
QFrame#settingsControl { background: #0d1721; border: 1px solid #263746; border-radius: 10px; }
QLabel#settingsTitle { color: #f3f8fa; font-size: 19px; font-weight: 700; }
QLabel#settingsValue { color: #e8eff3; font-size: 14px; font-weight: 600; }
QLabel#settingsNote { color: #91a5af; font-size: 12px; }
QSlider#settingsSlider { background: transparent; border: none; }
QSlider#settingsSlider::groove:horizontal { height: 5px; background: #667680; border-radius: 2px; }
QSlider#settingsSlider::sub-page:horizontal { background: #00df92; border-radius: 2px; }
QSlider#settingsSlider::add-page:horizontal { background: #667680; border-radius: 2px; }
QSlider#settingsSlider::handle:horizontal { width: 24px; margin: -10px 0; border-radius: 12px; background: #00e994; border: 2px solid #e3fff3; }
QSlider#settingsSlider:disabled::handle:horizontal { background: #71818a; border-color: #9ba8ad; }
QSlider#settingsSlider:disabled::sub-page:horizontal { background: #71818a; }
QComboBox#cameraDisplay { background: #d9d9d9; color: #111820; border: 2px solid #11c3ff; border-radius: 4px; min-height: 50px; padding: 4px 12px; font-size: 18px; }
QComboBox#cameraDisplay::drop-down { width: 42px; border: none; }
QComboBox#cameraDisplay QAbstractItemView { background: #17232d; color: #edf4f6; selection-background-color: #315c5e; selection-color: #ffffff; font-size: 18px; outline: 0; }
QFrame#devPanel { background: #0d1721; border: 1px solid #263746; border-radius: 10px; }
QPushButton#danger { background: #512b2d; color: #ffe8e6; border: 1px solid #784143; }
QPushButton#danger:pressed { background: #723638; }
QPushButton#danger:disabled { background: #1c2934; color: #82939d; border-color: #2c3d49; }
QFrame#divider { background: #2a3b49; max-height: 1px; border: none; }
QLabel#brand { color: #f3f8fa; font-size: 20px; font-weight: 700; }
QLabel#eyebrow { color: #7eabb8; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QLabel#headerHint, QLabel#muted { color: #a3b5c0; font-size: 14px; }
QLabel#cardTitle { color: #eef5f7; font-size: 17px; font-weight: 700; }
QLabel#smallTitle { color: #b5c8d0; font-size: 14px; font-weight: 600; }
QLabel#value { color: #f0f5f6; font-size: 17px; font-weight: 700; }
QLabel#badge { color: #d2dfe3; background: #263644; border: 1px solid #344b58; border-radius: 8px; padding: 5px 10px; font-size: 14px; font-weight: 600; }
QLabel#video { color: #a2b7c1; background: #080e14; border: 1px solid #263745; border-radius: 10px; font-size: 17px; }
QLabel#video[reverseActive="true"][pulse="true"] { border: 5px solid #efbd55; }
QLabel#video[reverseActive="true"][pulse="false"] { border: 1px solid #263745; }
QPushButton { background: #243442; color: #edf4f6; border: 1px solid #3a5060; border-radius: 11px; padding: 8px 10px; font-size: 18px; font-weight: 600; }
QPushButton[navButton="true"] { padding: 0px; }
QPushButton:hover { background: #2b4350; }
QPushButton:pressed { background: #365963; }
QPushButton:checked { background: #315c5e; border-color: #76c8bd; }
QPushButton:disabled { color: #8f9fa9; background: #1c2934; border-color: #2c3d49; }
QPushButton#primary { background: #8ad6cc; color: #10222a; border: 1px solid #a3e6dc; }
QPushButton#primary:pressed { background: #6dbbb0; }
QPushButton#primary:disabled { background: #1c2934; color: #82939d; border-color: #2c3d49; }
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
    def __init__(self, project: Path = PROJECT, config_path: Path | None = None) -> None:
        super().__init__()
        self.project = project
        self.config_path = config_path or Path(__file__).with_name("config.json")
        self.runtime = RuntimeController(self.config_path, self)
        self.worker = None
        self.worker_error = None
        self.preferences = QSettings("VehicleIntegration", "MainApp")
        self.camera_display_mode = self.preferences.value("camera_display", "front", str)
        if self.camera_display_mode not in {"front", "rear", "off"}:
            self.camera_display_mode = "front"
        self.reverse = False
        self.transfer_dialog = None
        self.audio_control = AudioVolumeControl()
        self.backlight_control = BacklightControl(self.runtime.config.get("brightness_file"))
        self.setWindowTitle("車載統合システム")
        self.resize(800, 480)
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
        self.reverse_pulse = False
        self.reverse_frame_timer = QTimer(self)
        self.reverse_frame_timer.setInterval(500)
        self.reverse_frame_timer.timeout.connect(self._pulse_reverse_frame)
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
        self.event_button.clicked.connect(self.runtime.request_manual_event)
        self.open_video_button.clicked.connect(self.choose_video)
        self.stop_video_button.clicked.connect(self.stop_video)
        self.transfer_button.clicked.connect(self.start_transfer)
        self.shutdown_button.clicked.connect(self.request_shutdown)
        self.voice_button.clicked.connect(self.choose_voice_language)
        self.camera_display.currentIndexChanged.connect(self.on_camera_display_changed)
        self.volume_apply_timer = QTimer(self)
        self.volume_apply_timer.setSingleShot(True)
        self.volume_apply_timer.setInterval(150)
        self.volume_apply_timer.timeout.connect(self.apply_volume)
        self.brightness_apply_timer = QTimer(self)
        self.brightness_apply_timer.setSingleShot(True)
        self.brightness_apply_timer.setInterval(35)
        self.brightness_apply_timer.timeout.connect(self.apply_brightness)
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        self.volume_slider.sliderReleased.connect(self.apply_volume)
        self.brightness_slider.valueChanged.connect(self.on_brightness_changed)
        self.brightness_slider.sliderReleased.connect(self.apply_brightness)
        self.device_refresh_timer = QTimer(self)
        self.device_refresh_timer.setInterval(3000)
        self.device_refresh_timer.timeout.connect(self.refresh_device_controls)
        self.device_refresh_timer.start()
        self._apply_camera_mode(self.camera_display_mode, return_to_video=False)
        self.runtime.status_changed.connect(self.on_runtime_status)
        self.runtime.log_changed.connect(self.on_runtime_log)
        self.runtime.recorder_changed.connect(self.on_recorder_changed)
        self.runtime.transfer_changed.connect(self.on_transfer_changed)
        self.runtime.transfer_phase_changed.connect(self.on_transfer_phase)
        transfer_available = self.runtime.command_available("transfer_command")
        self.transfer_button.setEnabled(transfer_available)
        if not transfer_available:
            self.transfer_button.setToolTip("転送ビューアをビルドしてから利用できます")
        shutdown_available = bool(self.runtime.config.get("allow_os_shutdown", False)) and sys.platform.startswith("linux")
        self.shutdown_button.setEnabled(shutdown_available)
        if not shutdown_available:
            self.shutdown_button.setToolTip("Raspberry Pi用設定で安全停止を有効にすると利用できます")
        self._set_navigation(False)
        if self.runtime.config.get("auto_start_recorder", False):
            self.runtime.start_recorder()

    def _build_home(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        video_card = card("videoCard")
        video_layout = QVBoxLayout(video_card)
        video_layout.setContentsMargins(10, 8, 10, 8)
        video_layout.setSpacing(8)
        initial_camera = "リア" if self.reverse else "フロント"
        initial_message = "カメラ表示 OFF\n録画は継続します" if self.camera_display_mode == "off" else f"{initial_camera}映像：未接続\n録画・解析プログラム：未接続"
        self.video_label = QLabel(initial_message, objectName="video")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setWordWrap(True)
        self.video_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.video_label.setProperty("reverseActive", self.camera_display_mode == "rear")
        self.video_label.setProperty("pulse", False)
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
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        layout.addWidget(text_label("設定", "settingsTitle"))
        layout.addWidget(self._slider_setting("音量", "volume"))
        layout.addWidget(self._slider_setting("光量", "brightness"))

        camera_row = card("settingsControl")
        camera_layout = QHBoxLayout(camera_row)
        camera_layout.setContentsMargins(14, 6, 10, 6)
        camera_layout.setSpacing(12)
        camera_title = text_label("カメラ表示", "settingsTitle")
        camera_title.setMinimumWidth(142)
        camera_layout.addWidget(camera_title)
        self.camera_display = TouchComboBox()
        self.camera_display.setObjectName("cameraDisplay")
        self.camera_display.addItem("フロント", "front")
        self.camera_display.addItem("リア", "rear")
        self.camera_display.addItem("OFF", "off")
        current_index = self.camera_display.findData(self.camera_display_mode)
        self.camera_display.setCurrentIndex(max(0, current_index))
        self.camera_display.setAccessibleName("表示するカメラ")
        self.camera_display.setMinimumHeight(52)
        camera_layout.addWidget(self.camera_display, 1)
        layout.addWidget(camera_row)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.transfer_button = QPushButton("転送")
        self.transfer_button.setObjectName("primary")
        self.transfer_button.setAccessibleName("動画転送ソフトを起動")
        self.transfer_button.setMinimumHeight(54)
        self.transfer_button.setEnabled(False)
        self.transfer_button.setToolTip("録画を安全に停止してから転送を開始します")
        actions.addWidget(self.transfer_button, 3)
        self.voice_button = QPushButton("音声変更")
        self.voice_button.setAccessibleName("音声ガイダンスの言語を変更")
        self.voice_button.setMinimumHeight(54)
        actions.addWidget(self.voice_button, 2)
        self.shutdown_button = QPushButton("電源停止")
        self.shutdown_button.setObjectName("danger")
        self.shutdown_button.setAccessibleName("システムを安全に停止")
        self.shutdown_button.setMinimumHeight(54)
        self.shutdown_button.setEnabled(False)
        self.shutdown_button.setToolTip("Raspberry Pi用設定で安全停止を有効にすると利用できます")
        actions.addWidget(self.shutdown_button, 2)
        layout.addLayout(actions)

        self.runtime_status = text_label("設定値は接続機器に反映されます", "settingsNote")
        self.runtime_status.setWordWrap(True)
        layout.addWidget(self.runtime_status)
        self.runtime_log = text_label("", "settingsNote")
        self.runtime_log.setWordWrap(False)
        self.runtime_log.setMaximumHeight(20)
        layout.addWidget(self.runtime_log)

        self.dev_panel = card("devPanel")
        dev_layout = QHBoxLayout(self.dev_panel)
        dev_layout.setContentsMargins(8, 5, 8, 5)
        dev_layout.addWidget(text_label("開発用", "settingsNote"))
        self.open_video_button = QPushButton("動画ファイルを開く")
        self.open_video_button.setMinimumHeight(46)
        self.stop_video_button = QPushButton("表示停止")
        self.stop_video_button.setMinimumHeight(46)
        self.stop_video_button.setEnabled(False)
        dev_layout.addWidget(self.open_video_button, 1)
        dev_layout.addWidget(self.stop_video_button, 1)
        self.dev_panel.setVisible(bool(self.runtime.config.get("development_tools", False)))
        layout.addWidget(self.dev_panel)

        volume = self.audio_control.get_percent()
        self.volume_slider.setValue(volume if volume is not None else 50)
        self.on_volume_changed(self.volume_slider.value())
        self.volume_slider.setEnabled(volume is not None)
        if volume is None:
            self.volume_value.setText("未接続")
        self.volume_slider.setToolTip("音声出力デバイスが検出された場合に操作できます")
        brightness = self.backlight_control.get_percent()
        self.brightness_slider.setValue(brightness if brightness is not None else 60)
        self.on_brightness_changed(self.brightness_slider.value())
        self.brightness_slider.setEnabled(brightness is not None and self.backlight_control.available)
        if brightness is None:
            self.brightness_value.setText("未対応")
        self.brightness_slider.setToolTip("制御可能なバックライトが見つかった場合に操作できます")
        self._update_voice_button()
        if not self.audio_control.available or not self.backlight_control.available:
            self.runtime_status.setText("音量・光量は、Raspberry Piで対応デバイスを検出すると操作できます")
        return page

    def _slider_setting(self, title: str, name: str) -> QFrame:
        row = card("settingsControl")
        line = QHBoxLayout(row)
        line.setContentsMargins(14, 4, 14, 4)
        line.setSpacing(14)
        label = text_label(title, "settingsTitle")
        label.setMinimumWidth(142)
        line.addWidget(label)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setObjectName("settingsSlider")
        slider.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        slider.setAutoFillBackground(False)
        slider.setStyleSheet("QSlider { background: transparent; border: none; }")
        slider.setRange(1 if name == "brightness" else 0, 100)
        slider.setSingleStep(1)
        slider.setPageStep(10)
        slider.setMinimumHeight(48)
        slider.setAccessibleName(title)
        value = text_label("--%", "settingsValue")
        value.setMinimumWidth(70)
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        line.addWidget(slider, 1)
        line.addWidget(value)
        if name == "volume":
            self.volume_slider = slider
            self.volume_value = value
        else:
            self.brightness_slider = slider
            self.brightness_value = value
        row.setMinimumHeight(58)
        return row

    def _update_voice_button(self) -> None:
        selected = self.preferences.value("voice_profile", "", str)
        profiles = self.runtime.config.get("voice_profiles", [])
        label = next((p["label"] for p in profiles if p["id"] == selected), "未選択")
        self.voice_button.setText(f"音声変更 · {label}")

    def choose_voice_language(self) -> None:
        profiles = self.runtime.config.get("voice_profiles", [])
        if not profiles:
            QMessageBox.information(self, "音声変更", "選択できる音声がまだ登録されていません。音声データ登録後、この一覧から選択できます。")
            return
        selected = choose(self, "音声を選択", [(p["id"], p["label"]) for p in profiles], self.preferences.value("voice_profile", "", str))
        if selected is not None:
            self.preferences.setValue("voice_profile", selected)
            self._update_voice_button()
            self.runtime_status.setText("音声を選択しました。警告音声の出力連携は未接続です")

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
        if self.worker is not None or self.runtime.embedded_transfer:
            return
        self.reverse = not self.reverse
        self.runtime.set_analysis_camera("rear" if self.reverse else "front")
        self._apply_camera_mode(self.camera_display_mode, return_to_video=True)

    def on_camera_display_changed(self, index: int) -> None:
        mode = self.camera_display.itemData(index)
        if mode in {"front", "rear", "off"}:
            self._apply_camera_mode(mode, return_to_video=False)

    def _apply_camera_mode(self, mode: str, return_to_video: bool) -> None:
        self.camera_display_mode = mode
        effective = "rear" if self.reverse else mode
        self.reverse_button.setChecked(self.reverse)
        self.reverse_button.setIcon(button_icon("front" if self.reverse else "reverse"))
        self.reverse_button.setAccessibleName("リバースを解除" if self.reverse else "リバースを有効にする")
        self.reverse_frame_timer.stop()
        self.reverse_pulse = self.reverse
        if self.reverse:
            self.reverse_frame_timer.start()
        self.video_label.setProperty("reverseActive", self.reverse)
        self.video_label.setProperty("pulse", self.reverse_pulse)
        self._refresh_video_frame_style()
        self.camera_display.blockSignals(True)
        self.camera_display.setCurrentIndex(self.camera_display.findData(mode))
        self.camera_display.blockSignals(False)
        self.camera_heading.setText({"front": "フロントカメラ", "rear": "リアカメラ", "off": "カメラ表示 OFF"}[effective])
        self.camera_badge.setText("映像 未接続" if effective != "off" else "表示 OFF")
        self.video_label.setText("カメラ表示 OFF" if effective == "off" else self.camera_heading.text()+"映像：未接続")
        self.preferences.setValue("camera_display", mode)
        if return_to_video:
            self.show_home()

    def _pulse_reverse_frame(self) -> None:
        if not self.reverse:
            return
        self.reverse_pulse = not self.reverse_pulse
        self.video_label.setProperty("pulse", self.reverse_pulse)
        self._refresh_video_frame_style()

    def _refresh_video_frame_style(self) -> None:
        self.video_label.style().unpolish(self.video_label)
        self.video_label.style().polish(self.video_label)
        self.video_label.update()

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


    def on_runtime_status(self, message: str) -> None:
        if message == "録画プログラム未設定":
            message = "録画プログラム未ビルド"
        elif message == "転送サーバーを起動できません":
            message = "転送ソフトの起動ファイルを確認してください"
        self.runtime_status.setText(message)
        self.status_label.setText(message + "　AI／センサー：未接続")

    def on_runtime_log(self, message: str) -> None:
        if "実行ファイルがありません" in message:
            short = ""
        elif "カメラ初期化" in message and "失敗" in message:
            short = "カメラを確認してください"
        else:
            short = message
        self.runtime_log.setToolTip(message)
        self.runtime_log.setText(short if len(short) <= 72 else short[:69] + "…")

    def on_recorder_changed(self, running: bool) -> None:
        self.event_button.setEnabled(running)

    def on_transfer_phase(self, phase):
        busy = phase in {"preparing", "stopping", "restoring"}
        self.transfer_button.setEnabled(not busy)
        self.reverse_button.setEnabled(not busy and not self.runtime.embedded_transfer)
        if phase == "error" and self.runtime.embedded_transfer:
            self.transfer_button.setText("転送停止を再試行")

    def on_transfer_changed(self, running: bool) -> None:
        self.transfer_button.setText("転送を終了" if running else "転送")
        self.reverse_button.setEnabled(not running)
        self.camera_display.setEnabled(not running)
        if running:
            self.reverse_frame_timer.stop()
            import qrcode
            url = self.runtime.transfer_url
            qr = qrcode.make(url).convert("RGB")
            picture = QImage(qr.tobytes(), qr.width, qr.height, qr.width*3, QImage.Format.Format_RGB888).copy()
            dialog = QDialog(self)
            self.transfer_dialog = dialog
            dialog.setWindowTitle("動画転送")
            dialog.setMinimumWidth(520)
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel("スマホを同じWi-Fiにつなぎ、QRコードを読み取ってください"))
            label = QLabel()
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setPixmap(QPixmap.fromImage(picture).scaled(230,230,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.FastTransformation))
            layout.addWidget(label)
            link = QLabel(url)
            link.setWordWrap(True)
            link.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(link)
            layout.addWidget(QLabel("転送中は録画を停止しています"))
            end = QPushButton("転送を終了して戻る")
            end.setMinimumHeight(48)
            end.clicked.connect(dialog.close)
            layout.addWidget(end)
            dialog.finished.connect(lambda _: self.runtime.end_transfer())
            dialog.setModal(True)
            dialog.show()
        else:
            if self.transfer_dialog:
                dialog, self.transfer_dialog = self.transfer_dialog, None
                dialog.close()
            self._apply_camera_mode(self.camera_display_mode, return_to_video=False)

    def refresh_device_controls(self) -> None:
        if self.pages.currentIndex() != 1:
            return
        if not self.volume_slider.isSliderDown() and not self.volume_apply_timer.isActive():
            volume = self.audio_control.get_percent()
            self.volume_slider.setEnabled(volume is not None)
            if volume is None:
                self.volume_value.setText("未接続")
            else:
                self.volume_slider.blockSignals(True)
                self.volume_slider.setValue(volume)
                self.volume_slider.blockSignals(False)
                self.volume_value.setText(f"{volume}%")
        if not self.brightness_slider.isSliderDown() and not self.brightness_apply_timer.isActive():
            if not self.backlight_control.available:
                self.backlight_control = BacklightControl(self.runtime.config.get("brightness_file"))
            brightness = self.backlight_control.get_percent()
            self.brightness_slider.setEnabled(brightness is not None and self.backlight_control.available)
            if brightness is None:
                self.brightness_value.setText("未対応")
            else:
                self.brightness_slider.blockSignals(True)
                self.brightness_slider.setValue(brightness)
                self.brightness_slider.blockSignals(False)
                self.brightness_value.setText(f"{brightness}%")

    def on_volume_changed(self, value: int) -> None:
        self.volume_value.setText(f"{value}%")
        if hasattr(self, "volume_apply_timer") and self.volume_slider.isEnabled():
            self.volume_apply_timer.start()

    def apply_volume(self) -> None:
        self.volume_apply_timer.stop()
        if not self.audio_control.set_percent(self.volume_slider.value()):
            self.runtime_status.setText("音量を変更できません。音声出力デバイスを確認してください")
        self.refresh_device_controls()

    def on_brightness_changed(self, value: int) -> None:
        self.brightness_value.setText(f"{value}%")
        if hasattr(self, "brightness_apply_timer") and self.brightness_slider.isEnabled() and not self.brightness_apply_timer.isActive():
            self.brightness_apply_timer.start()

    def apply_brightness(self) -> None:
        self.brightness_apply_timer.stop()
        if not self.backlight_control.set_percent(self.brightness_slider.value()):
            self.runtime_status.setText("光量を変更できません。バックライト制御デバイスを確認してください")
        self.refresh_device_controls()

    def start_transfer(self) -> None:
        if self.worker is not None:
            self.runtime_status.setText("動画確認を停止してから転送してください")
            return
        if self.runtime.embedded_transfer:
            self.runtime.end_transfer()
        else:
            self.runtime.begin_transfer()

    def request_shutdown(self) -> None:
        if not self.runtime.config.get("allow_os_shutdown", False):
            return
        answer = QMessageBox.question(self, "システム停止", "録画を安全に停止して端末をシャットダウンしますか？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.shutdown_button.setEnabled(False)
        self.shutdown_button.setText("安全に停止中…")
        self.runtime.stop()
        from PySide6.QtCore import QProcess
        QProcess.startDetached("shutdown", ["-h", "now"])

    def closeEvent(self, event) -> None:
        if self.worker is not None:
            self.worker.stop()
            if not self.worker.wait(5000):
                self.status_label.setText("動画の停止を待っています")
                event.ignore()
                return
        self.runtime.stop()
        event.accept()

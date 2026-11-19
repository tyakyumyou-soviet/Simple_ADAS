"""ラズパイの7インチタッチ画面向け車載統合UI。"""
from __future__ import annotations
from shared_frame import read_frame
from adas_settings_validation import validate_settings, display_interval_ms

from pathlib import Path
import json
import os
import tempfile
import numpy as np
import sys
import time
import shutil
from PySide6.QtCore import QSize, Qt, QProcess, QTimer, QSettings
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QInputDialog, QDialog,
    QComboBox, QPushButton, QSlider, QSizePolicy, QStackedWidget, QStyle, QStyleOptionSlider, QVBoxLayout, QWidget,
)
from video_backend import make_video_worker, make_external_video_worker
from icons import button_icon, warning_icon
from runtime import RuntimeController
from touch_choices import TouchComboBox, choose, exec_embedded
from device_controls import AudioVolumeControl, BacklightControl
from warning_audio import WarningAudio
from lens_settings import LensSettingsDialog, load_lens_settings

ASSETS = Path(__file__).resolve().parent / "assets"
PROJECT = Path(__file__).resolve().parent.parent / "sources" / "collision_prediction"

STYLE = """
QMainWindow, QWidget#root { background: #0b1119; color: #edf3f6; }
QDialog { background: #111c27; color: #edf3f6; }
QDialog QLabel { font-size: 14px; }
QLabel#detailTitle { color: #f3f8fa; font-size: 22px; font-weight: 700; }
QLabel#detailHint { color: #a3b5c0; font-size: 14px; }
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
QComboBox#cameraDisplay { background: #243442; color: #edf4f6; border: 1px solid #3a5060; border-radius: 10px; min-height: 38px; padding: 2px 12px; font-size: 18px; }
QComboBox#cameraDisplay:focus { border-color: #76c8bd; }
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


class TouchSlider(QSlider):
    """スライダーの上下を含む領域を、タップとドラッグに使う。"""
    def _set_from_x(self, x: float) -> None:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self)
        handle = style.subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self)
        span = max(1, groove.width() - handle.width())
        position = round(x - groove.x() - handle.width() / 2)
        self.setSliderPosition(QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), position, span, option.upsideDown))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self._set_from_x(event.position().x())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.isSliderDown():
            self._set_from_x(event.position().x())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self._set_from_x(event.position().x())
            self.setSliderDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, project: Path = PROJECT, config_path: Path | None = None) -> None:
        super().__init__()
        self.project = project
        self.config_path = config_path or Path(__file__).with_name("config.json")
        self.runtime = RuntimeController(self.config_path, self)
        self.worker = None
        self.worker_error = None
        self.preferences = QSettings("VehicleIntegration", "MainApp")
        self.fullscreen_enabled = self.preferences.value("fullscreen", self.runtime.config.get("fullscreen", False), type=bool)
        self.recording_requested = self.preferences.value("feature_recording", False, type=bool)
        self.adas_requested = self.preferences.value("feature_adas", False, type=bool)
        self._features_initialized = False
        self._feature_errors = {}
        self._transfer_retry_requested = False
        self._video_original_display = None
        self._video_original_reverse = None
        self._adas_status = "停止"
        self._sensor_status = "未接続"
        self._adas_alerts = []
        self._sensor_alerts = {}
        self._recorder_status = "停止"
        self._warning_sides = {}
        self._warning_blink = True
        self._preview_key = None
        self._preview_display_width = int(self.runtime._profile_value('ui', 'display_max_width', 320) or 0)
        self._overlay_max_age_ms = self._configured_overlay_max_age()
        self.warning_audio = WarningAudio(self)
        formal_profile = self.runtime.config.get("warning_audio_profiles", {}).get("formal", {})
        try:
            if formal_profile:
                self.warning_audio.register_profile("formal", formal_profile)
            selected_warning = self.preferences.value("warning_audio_profile", "provisional", str)
            if self.warning_audio.has_profile(selected_warning):
                self.warning_audio.select_profile(selected_warning)
        except (TypeError, ValueError, FileNotFoundError):
            pass  # 登録が不完全な場合は暫定音を使用し、詳細設定で未登録と表示する。
        self.camera_display_mode = self.preferences.value("camera_display", "front", str)
        if self.camera_display_mode not in {"front", "rear", "off"}:
            self.camera_display_mode = "front"
        self.reverse = False
        self.transfer_dialog = None
        self._shutdown_pending = False
        self._close_pending = False
        self._shutdown_process = None
        self.audio_control = AudioVolumeControl()
        self.backlight_control = BacklightControl(self.runtime.config.get("brightness_file"))
        # 起動時の初期値。設定画面は実際に反映された値を読み取る。
        self.audio_control.set_percent(70)
        self.backlight_control.set_percent(70)
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
        self.volume_apply_timer.setInterval(35)
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
        self.runtime.recorder_ready_changed.connect(self.on_recorder_changed)
        self.runtime.recorder_changed.connect(self.on_recorder_process_changed)
        self.runtime.adas_changed.connect(self.on_adas_process_changed)
        self.runtime.adas_result.connect(self.on_adas_result)
        self.runtime.video_finished.connect(lambda: QTimer.singleShot(0, self.stop_video))
        self.runtime.sensor_hub.status_changed.connect(self.on_sensor_status)
        self.runtime.sensor_hub.obstacle.connect(self.on_sensor_obstacle)
        self.sensor_expiry_timer = QTimer(self)
        self.sensor_expiry_timer.setInterval(250)
        self.sensor_expiry_timer.timeout.connect(self._expire_sensor_alerts)
        self.sensor_expiry_timer.start()
        self.warning_audio.error.connect(self.runtime_status.setText)
        self.warning_blink_timer = QTimer(self)
        self.warning_blink_timer.setInterval(350)
        self.warning_blink_timer.timeout.connect(self._blink_warnings)
        self.warning_stale_timer = QTimer(self)
        self.warning_stale_timer.setSingleShot(True)
        self.warning_stale_timer.setInterval(2500)
        self.warning_stale_timer.timeout.connect(self._clear_stale_alerts)
        self.feature_retry_timer = QTimer(self)
        self.feature_retry_timer.setInterval(5000)
        self.feature_retry_timer.timeout.connect(self._retry_requested_features)
        self.feature_retry_timer.start()
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(display_interval_ms({'ui': {k: self.runtime._profile_value('ui', k, d) for k,d in [('display_fps',30),('display_every_n_frames',1)]}}))
        self.preview_timer.timeout.connect(self._show_live_preview)
        self.preview_timer.start()
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
        self._refresh_main_status()
        self._features_initialized = True
        QTimer.singleShot(0, self._start_initial_features)

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
        self.feature_error_label = text_label("", "overlay")
        self.feature_error_label.setWordWrap(True)
        self.feature_error_label.setStyleSheet("color: #ffffff; background: #9f2727; border: 2px solid #ffb2a8; border-radius: 6px; padding: 7px; font-weight: bold;")
        self.feature_error_label.hide()
        self.event_status_label = text_label("", "overlay")
        self.event_status_label.hide()
        self.event_status_timer = QTimer(self)
        self.event_status_timer.setSingleShot(True)
        self.event_status_timer.timeout.connect(self.event_status_label.hide)
        overlays.addWidget(self.camera_heading, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        overlays.addWidget(self.camera_badge, 0, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.warning_left = QLabel()
        self.warning_right = QLabel()
        for light in (self.warning_left, self.warning_right):
            light.setFixedWidth(150)
            light.setMinimumHeight(80)
            light.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            light.setAlignment(Qt.AlignmentFlag.AlignCenter)
            light.hide()
        overlays.addWidget(self.warning_left, 2, 0, Qt.AlignmentFlag.AlignLeft)
        overlays.addWidget(self.warning_right, 2, 1, Qt.AlignmentFlag.AlignRight)
        overlays.setRowStretch(2, 1)
        overlays.addWidget(self.feature_error_label, 1, 0, 1, 2, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        overlays.addWidget(self.event_status_label, 3, 0, 1, 2, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        overlays.addWidget(self.status_label, 4, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        overlays.addWidget(self.distance_label, 4, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
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
        camera_layout.setContentsMargins(14, 3, 10, 3)
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
        self.camera_display.setMinimumHeight(44)
        camera_row.setMinimumHeight(50)
        camera_layout.addWidget(self.camera_display, 1)
        layout.addWidget(camera_row)

        feature_row = QHBoxLayout()
        self.recording_feature_button = QPushButton()
        self.recording_feature_button.setMinimumHeight(44)
        self.recording_feature_button.setCheckable(True)
        self.recording_feature_button.setChecked(self.recording_requested)
        self.recording_feature_button.setText("録画：開始待ち" if self.recording_requested else "録画：オフ")
        self.recording_feature_button.toggled.connect(self.toggle_recording_feature)
        feature_row.addWidget(self.recording_feature_button)
        self.adas_feature_button = QPushButton()
        self.adas_feature_button.setMinimumHeight(44)
        self.adas_feature_button.setCheckable(True)
        self.adas_feature_button.setChecked(self.adas_requested)
        self.adas_feature_button.setText("危険予知：開始待ち" if self.adas_requested else "危険予知：オフ")
        self.adas_feature_button.toggled.connect(self.toggle_adas_feature)
        feature_row.addWidget(self.adas_feature_button)
        layout.addLayout(feature_row)

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
        self.runtime_log.setVisible(bool(self.runtime.config.get("development_tools", False)))
        layout.addWidget(self.runtime_log)

        self.dev_panel = card("devPanel")
        dev_layout = QHBoxLayout(self.dev_panel)
        dev_layout.setContentsMargins(8, 5, 8, 5)
        dev_layout.addWidget(text_label("動画検証", "settingsNote"))
        self.open_video_button = QPushButton("動画ファイルを開く")
        self.open_video_button.setMinimumHeight(48)
        self.stop_video_button = QPushButton("表示停止")
        self.stop_video_button.setMinimumHeight(48)
        self.stop_video_button.setEnabled(False)
        dev_layout.addWidget(self.open_video_button, 1)
        dev_layout.addWidget(self.stop_video_button, 1)
        self.dev_panel.setVisible(bool(self.runtime.config.get("development_tools", False)))
        layout.addWidget(self.dev_panel)
        footer = QHBoxLayout()
        self.detail_button = QPushButton("詳細設定")
        self.detail_button.setMinimumSize(120, 40)
        self.detail_button.clicked.connect(self.open_detail_settings)
        footer.addWidget(self.detail_button)
        self.video_verify_button = QPushButton("動画検証")
        self.video_verify_button.setMinimumSize(120, 40)
        self.video_verify_button.clicked.connect(lambda: self.stop_video() if self.runtime.video_role else self.choose_video())
        footer.addWidget(self.video_verify_button)
        footer.addStretch()
        self.fullscreen_button = QPushButton()
        self.fullscreen_button.setFixedSize(125, 40)
        self.fullscreen_button.setStyleSheet("font-size: 13px; padding: 2px 6px;")
        self.fullscreen_button.setCheckable(True)
        self.fullscreen_button.setChecked(self.fullscreen_enabled)
        self.fullscreen_button.setText("全画面：オン" if self.fullscreen_enabled else "全画面：オフ")
        self.fullscreen_button.toggled.connect(self.set_fullscreen)
        footer.addWidget(self.fullscreen_button)
        layout.addLayout(footer)

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

    def open_detail_settings(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dialog.setWindowTitle("詳細設定")
        dialog.setObjectName("detailDialog")
        dialog.setMinimumSize(560, 400)
        dialog.resize(700, 440)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(8)
        title = QLabel("機器と警告音")
        title.setObjectName("detailTitle")
        layout.addWidget(title)
        intro = QLabel("前後カメラの接続先と、危険時に鳴らす音を設定します")
        intro.setObjectName("detailHint")
        layout.addWidget(intro)
        camera_card = card("settingsControl")
        camera_layout = QVBoxLayout(camera_card)
        camera_layout.setContentsMargins(16, 12, 16, 12)
        camera_layout.setSpacing(8)
        camera_title = QLabel("カメラの割り当て")
        camera_title.setObjectName("smallTitle")
        camera_layout.addWidget(camera_title)
        paths = sorted(Path("/dev/v4l/by-id").glob("*-video-index0"))
        selectors = {}
        for role, label in (("front", "フロント"), ("rear", "リア")):
            row = QHBoxLayout()
            row.setSpacing(12)
            role_title = QLabel(label + "カメラ")
            role_title.setObjectName("smallTitle")
            role_title.setFixedWidth(140)
            row.addWidget(role_title)
            selector = TouchComboBox()
            selector.setObjectName("cameraAssignment")
            selector.setAccessibleName(label + "カメラを選択")
            selector.addItem("未指定", "")
            selected = self.preferences.value("camera_device_" + role, "", str)
            for path in paths:
                selector.addItem(path.name.removesuffix("-video-index0"), str(path))
            if selected and selector.findData(selected) < 0:
                selector.addItem("未接続: " + selected, selected)
            selector.setCurrentIndex(max(0, selector.findData(selected)))
            selector.setMinimumHeight(46)
            selector.setStyleSheet("QComboBox { background:#192733; color:#edf4f6; border:1px solid #3a5060; border-radius:10px; padding:8px 14px; font-size:16px; } QComboBox::drop-down { width:48px; border:0; }")
            row.addWidget(selector, 1)
            camera_layout.addLayout(row)
            selectors[role] = selector
        layout.addWidget(camera_card)
        sound_card = card("settingsControl")
        sound_layout = QVBoxLayout(sound_card)
        sound_layout.setContentsMargins(16, 12, 16, 12)
        sound_layout.setSpacing(8)
        sound_title = QLabel("警告音")
        sound_title.setObjectName("smallTitle")
        sound_layout.addWidget(sound_title)
        sound = QPushButton()
        def update_sound_label():
            selected = self.preferences.value("warning_audio_profile", "provisional", str)
            if not self.warning_audio.has_profile(selected):
                selected = "provisional"
            sound.setText("警告音：" + ("正式音声" if selected == "formal" else "暫定音"))
        def choose_sound():
            options = [("provisional", "暫定音"), ("formal", "正式音声" if self.warning_audio.has_profile("formal") else "正式音声（未登録）")]
            selected = choose(dialog, "警告音を選択", options, self.preferences.value("warning_audio_profile", "provisional", str))
            if selected and not self.warning_audio.has_profile(selected):
                QMessageBox.information(dialog, "警告音", "正式音声はまだ登録されていません。")
            elif selected:
                self.warning_audio.select_profile(selected)
                self.preferences.setValue("warning_audio_profile", selected)
                update_sound_label()
        update_sound_label()
        sound.setMinimumHeight(48)
        sound.clicked.connect(choose_sound)
        sound_options = QHBoxLayout()
        sound_options.addWidget(sound, 1)
        overlay_button = QPushButton()
        overlay_button.setCheckable(True)
        overlay_button.setChecked(self.preferences.value("adas_overlay", False, bool))
        overlay_button.setMinimumHeight(44)
        def set_overlay(enabled):
            overlay_button.setText("検出枠・車線：" + ("オン" if enabled else "オフ"))
        set_overlay(overlay_button.isChecked())
        overlay_button.toggled.connect(set_overlay)
        sound_options.addWidget(overlay_button, 1)
        advanced_adas = QPushButton("危険予知の詳細")
        advanced_adas.setMinimumHeight(44)
        advanced_adas.clicked.connect(lambda: self.open_adas_settings(dialog))
        sound_options.addWidget(advanced_adas, 1)
        sound_layout.addLayout(sound_options)
        layout.addWidget(sound_card)
        note = QLabel("カメラの変更は保存後、録画を再起動すると反映されます。")
        note.setObjectName("detailHint")
        note.setWordWrap(True)
        layout.addWidget(note)
        save = QPushButton("保存")
        save.setMinimumHeight(48)
        def apply():
            front = selectors["front"].currentData()
            rear = selectors["rear"].currentData()
            if front and rear and Path(front).resolve() == Path(rear).resolve():
                note.setText("フロントとリアには別のカメラを指定してください")
                return
            overlay_enabled = overlay_button.isChecked()
            self.preferences.setValue("adas_overlay", overlay_enabled)
            if self.runtime.adas.state() == QProcess.ProcessState.Running:
                self.runtime.adas.write(b"OVERLAY_ON\n" if overlay_enabled else b"OVERLAY_OFF\n")
            self._preview_key = None
            changed = any(self.preferences.value("camera_device_" + role, "", str) != selector.currentData()
                          for role, selector in selectors.items())
            for role, selector in selectors.items():
                self.preferences.setValue("camera_device_" + role, selector.currentData())
            if changed and self.runtime.recorder.state() == QProcess.ProcessState.NotRunning:
                if self.runtime.stop_preview():
                    self._sync_preview()
            dialog.accept()
        save.clicked.connect(apply)
        cancel = QPushButton("戻る")
        cancel.setMinimumHeight(48)
        cancel.clicked.connect(dialog.reject)
        buttons = QHBoxLayout()
        lens_button = QPushButton("魚眼補正のオン／オフ")
        lens_button.setMinimumHeight(44)
        lens_button.clicked.connect(lambda: self.open_lens_settings(dialog))
        buttons.addWidget(lens_button)
        buttons.addStretch()
        cancel.setMinimumWidth(120)
        buttons.addWidget(cancel)
        save.setObjectName("primary")
        save.setMinimumWidth(150)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        dialog.exec()

    def open_lens_settings(self, parent) -> None:
        if self.runtime.transfer_phase != "idle" or self.runtime.hotspot or self.runtime.embedded_transfer:
            QMessageBox.information(parent, "魚眼補正", "転送を終了してから設定してください。")
            return
        before = {role: load_lens_settings(self.preferences, role) for role in ("front", "rear")}
        dialog = LensSettingsDialog(self.preferences, parent)
        if exec_embedded(dialog, parent) != QDialog.DialogCode.Accepted:
            return
        dialog.save(self.preferences)
        for role, label in (('front', '前'), ('rear', '後')):
            if not load_lens_settings(self.preferences, role)[0]:
                self._set_feature_error(f'魚眼補正（{label}）')
        if before == {role: load_lens_settings(self.preferences, role) for role in ("front", "rear")}:
            return
        if self.runtime.recorder.state() != QProcess.ProcessState.NotRunning:
            self.runtime_status.setText("魚眼補正を保存しました。録画を再開すると表示と危険予知へ反映します")
            QMessageBox.information(parent, "魚眼補正", "録画中のため、録画を再開した後に表示・危険予知へ反映します。")
        elif not self.runtime.set_video_source(self.runtime.video_role, self.runtime.video_path):
            self.runtime_status.setText("魚眼補正を保存しました。カメラ映像を再開できません")
        else:
            self._preview_key = None
            self.runtime_status.setText("魚眼補正を表示と危険予知に反映しました")

    def open_adas_settings(self, parent) -> None:
        project = Path(self.runtime.config.get("adas_project", self.project)).expanduser().resolve()
        try:
            sys.path.insert(0, str(project))
            from src.utils.config import load_config, deep_merge
            from src.ui.settings_dialog import SettingsDialog
            from adas_sidebar import AdasSidebarDialog
            base = load_config(project / "config/pi_async_ai_hat_2.yaml")
            path = Path.home() / ".config/VehicleIntegration/adas-profile.json"
            override = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            cfg = deep_merge(base, override)
            dialog = AdasSidebarDialog(cfg, parent, default_cfg=base, advanced_class=SettingsDialog)
            dialog.resize(min(700, self.width()), min(440, self.height()))
            if exec_embedded(dialog, parent) != QDialog.DialogCode.Accepted:
                return
            validate_settings(dialog.cfg, project)
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".adas-profile-", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(dialog.cfg, f, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            self.preview_timer.setInterval(display_interval_ms(dialog.cfg))
            self._preview_display_width = int(self.runtime._profile_value('ui', 'display_max_width', 320) or 0)
            self._overlay_max_age_ms = self._configured_overlay_max_age()
            running_adas = self.adas_requested and self.runtime.adas.state() != QProcess.ProcessState.NotRunning
            if running_adas and not self.runtime.stop_adas():
                raise RuntimeError("危険予知の停止を確認できません")
            if self.runtime.recorder.state() == QProcess.ProcessState.NotRunning:
                if not self.runtime.stop_preview():
                    raise RuntimeError("カメラ映像の停止を確認できません")
                if running_adas:
                    self._start_requested_adas()
                else:
                    self._sync_preview()
                self.runtime_status.setText("危険予知の設定を保存しました")
            else:
                if running_adas:
                    self._start_requested_adas()
                self.runtime_status.setText("設定を保存しました。映像の解像度は録画を再開すると反映されます")
        except Exception as exc:
            QMessageBox.warning(parent, "危険予知の設定", str(exc))

    def set_fullscreen(self, enabled: bool) -> None:
        self.fullscreen_enabled = enabled
        self.preferences.setValue("fullscreen", enabled)
        self.fullscreen_button.setText("全画面：オン" if enabled else "全画面：オフ")
        if enabled:
            self.showFullScreen()
        else:
            self.showNormal()

    def _slider_setting(self, title: str, name: str) -> QFrame:
        row = card("settingsControl")
        line = QHBoxLayout(row)
        line.setContentsMargins(14, 4, 14, 4)
        line.setSpacing(14)
        label = text_label(title, "settingsTitle")
        label.setMinimumWidth(142)
        line.addWidget(label)
        slider = TouchSlider(Qt.Orientation.Horizontal)
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
        if effective == "off":
            self.camera_badge.setText("表示 OFF")
            self.video_label.setText("カメラ表示 OFF")
        elif self.runtime.video_role == effective:
            self.camera_badge.setText("動画検証")
            self.video_label.setText("検証動画を読み込んでいます")
        elif not self.preferences.value("camera_device_" + effective, "", str):
            self.camera_badge.setText("カメラ未指定")
            self.video_label.setText(self.camera_heading.text() + "未指定\n設定の詳細設定から選択してください")
        else:
            self.camera_badge.setText("映像 未接続")
            self.video_label.setText(self.camera_heading.text() + "映像：未接続")
        self.preferences.setValue("camera_display", mode)
        self.runtime.preview_requested = effective != "off" or self.adas_requested
        self._preview_key = None
        if self._features_initialized:
            QTimer.singleShot(0, self._sync_preview)
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
        path, _ = QFileDialog.getOpenFileName(self, "検証する動画を選択", "", "動画 (*.mp4 *.mov *.mkv *.avi);;全ファイル (*)")
        if not path:
            return
        role = choose(self, "動画を入力するカメラ", [("front", "フロントカメラ"), ("rear", "リアカメラ")], "front")
        if role:
            self.start_video(Path(path), role)

    def start_video(self, path: Path, role: str = "front") -> bool:
        if self.runtime.video_role:
            self.runtime_status.setText("先に現在の動画検証を終了してください")
            return False
        if not path.is_file():
            self.runtime_status.setText("動画を開けません：ファイルが見つかりません")
            return False
        original = self.camera_display_mode
        original_reverse = self.reverse
        if not self.runtime.set_video_source(role, path):
            return False
        self._set_feature_error("動画検証")
        self._video_original_display = original
        self._video_original_reverse = original_reverse
        self.reverse = role == "rear"
        self.runtime.set_analysis_camera(role)
        self.video_verify_button.setText("動画検証を終了")
        self.open_video_button.setEnabled(False)
        self.stop_video_button.setEnabled(True)
        self._apply_camera_mode(role, return_to_video=True)
        self.preferences.setValue('camera_display', original)
        if self.adas_requested and self.runtime.adas.state() == QProcess.ProcessState.NotRunning:
            self._start_requested_adas()
        self._refresh_main_status()
        return True

    def stop_video(self) -> None:
        if not self.runtime.video_role:
            return
        original_reverse = self._video_original_reverse if self._video_original_reverse is not None else self.reverse
        test_camera = self.runtime.analysis_camera
        self.runtime.set_analysis_camera('rear' if original_reverse else 'front')
        if not self.runtime.set_video_source(None, None):
            self.runtime.set_analysis_camera(test_camera)
            return
        self.reverse = original_reverse
        self._video_original_reverse = None
        self._clear_warnings()
        self._set_feature_error("動画検証")
        self.video_verify_button.setText("動画検証")
        self.open_video_button.setEnabled(True)
        self.stop_video_button.setEnabled(False)
        original, self._video_original_display = self._video_original_display, None
        if original is not None:
            self._apply_camera_mode(original, return_to_video=False)
        self._refresh_main_status()
        self.show_home()

    def on_runtime_status(self, message: str) -> None:
        if message == "録画プログラム未設定":
            message = "録画プログラム未ビルド"
        elif message == "転送サーバーを起動できません":
            message = "転送ソフトの起動ファイルを確認してください"
        self.runtime_status.setText(message)
        if self.runtime.transfer_phase == "idle":
            if self.recording_requested and ("録画エラー" in message or "録画プロセス異常終了" in message):
                self._set_feature_error("録画", message + "（再試行中）")
            if self.adas_requested and ("危険予知エラー" in message or "危険予知が終了" in message):
                self._set_feature_error("危険予知", message + "（再試行中）")
            if "検証動画を再生できません" in message:
                self._set_feature_error("動画検証", message)
        self._refresh_main_status()

    def on_runtime_log(self, message: str) -> None:
        if '[録画画質警告]' in message:
            self._set_feature_error('録画画質', message.split('[録画画質警告]', 1)[1].strip())
        elif '[録画画質適合]' in message:
            self._set_feature_error('録画画質')
        for role, label in (('front', '前'), ('rear', '後')):
            if f'[カメラ画質差:{role}]' in message or f'[カメラ画質未確認:{role}]' in message:
                self._set_feature_error(f'カメラ画質（{label}）', message.split(']', 1)[-1].strip())
            elif f'[カメラ画質一致:{role}]' in message:
                self._set_feature_error(f'カメラ画質（{label}）')
            if f'[魚眼補正未適用:{role}]' in message:
                self._set_feature_error(f'魚眼補正（{label}）', message.split(']', 1)[-1].strip())
            elif f'[魚眼補正適用:{role}]' in message:
                self._set_feature_error(f'魚眼補正（{label}）')
        event_text = ""
        if "イベント保存失敗" in message or "イベント受付失敗" in message:
            event_text = "イベント保存失敗：設定画面を確認"
            self.runtime_status.setText(message)
        elif "イベント保存は一部欠落" in message:
            event_text = "イベント保存：一部欠落"
            self.runtime_status.setText(message)
        elif "イベント保存完了" in message:
            event_text = "イベント保存完了"
        elif "イベント保存予約" in message:
            event_text = "イベント保存中"
        if event_text:
            self.event_status_timer.stop()
            self.event_status_label.setText(event_text)
            self.event_status_label.show()
            if event_text == "イベント保存完了":
                self.event_status_timer.start(5000)
        if "実行ファイルがありません" in message:
            short = ""
        elif "カメラ初期化" in message and "失敗" in message:
            short = "カメラを確認してください"
        else:
            short = message
        self.runtime_log.setToolTip(message)
        self.runtime_log.setText(short if len(short) <= 72 else short[:69] + "…")

    def _start_initial_features(self) -> None:
        if self.runtime.closing:
            return
        if self.recording_requested:
            self._start_requested_recording()
        if self.adas_requested:
            self._start_requested_adas()
        if not self.recording_requested and not self.adas_requested:
            self._sync_preview()

    def _sync_preview(self) -> None:
        if self.runtime.closing or not self._features_initialized or self.runtime.embedded_transfer or self.runtime.transfer_phase not in {"idle", "error"}:
            return
        if self.runtime.recorder.state() != QProcess.ProcessState.NotRunning:
            return
        if self.runtime.preview_requested:
            self.runtime.start_preview()
        else:
            self.runtime.stop_preview()

    def _configured_overlay_max_age(self) -> int:
        try:
            return max(50, min(5000, int(self.runtime._profile_value("ui", "result_max_age_ms", 500))))
        except (TypeError, ValueError):
            return 500

    def _show_live_preview(self) -> None:
        if self.worker is not None or self.runtime.embedded_transfer:
            return
        role = "rear" if self.reverse else self.camera_display_mode
        if role == "off":
            return
        try:
            shared = read_frame(self.runtime.preview_dir / (role + '.frame'))
            if (self.preferences.value("adas_overlay", False, bool)
                    and self.runtime.adas.state() == QProcess.ProcessState.Running
                    and role == self.runtime.analysis_camera):
                try:
                    overlay = read_frame(self.runtime.preview_dir / (role + '.adas.frame'))
                    if 0 <= time.time_ns()-overlay.timestamp_ns < 150_000_000 and shared.timestamp_ns-overlay.timestamp_ns <= 150_000_000:
                        shared = overlay
                except OSError:
                    pass
            if time.time_ns() - shared.timestamp_ns > 2_000_000_000:
                raise OSError("映像が更新されていません")
            key = (role, shared.sequence, shared.timestamp_ns, self.video_label.width(), self.video_label.height())
            if key == self._preview_key:
                return
            image = QImage(shared.pixels, shared.width, shared.height, shared.width*3, QImage.Format.Format_RGB888).copy()
        except OSError:
            if self._preview_key is not None:
                self._preview_key = None
                self.video_label.clear()
                self.video_label.setText(self.camera_heading.text() + "映像：未接続")
                self.camera_badge.setText("映像 未接続")
            return
        if self._preview_display_width > 0 and image.width() > self._preview_display_width:
            image = image.scaledToWidth(self._preview_display_width, Qt.TransformationMode.SmoothTransformation)
        self._preview_key = key
        self.video_label.setPixmap(QPixmap.fromImage(image).scaled(
            self.video_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        self.camera_badge.setText("動画検証" if role == self.runtime.video_role else "映像")

    def _set_feature_error(self, feature: str, message: str = "") -> None:
        if message:
            self._feature_errors[feature] = message
        else:
            self._feature_errors.pop(feature, None)
        self.feature_error_label.setText("\n".join(f"{name}：{reason}" for name, reason in self._feature_errors.items()))
        self.feature_error_label.setVisible(bool(self._feature_errors))

    def _retry_requested_features(self) -> None:
        if (self.runtime.closing or self._shutdown_pending or self._close_pending
                or self.runtime.transfer_phase not in {"idle", "error"} or self.runtime.embedded_transfer
                or self.runtime.hotspot or self.runtime.transfer_requested):
            return
        if self._transfer_retry_requested:
            self.runtime.begin_transfer()
            return
        if self.recording_requested and self.runtime.recorder.state() == QProcess.ProcessState.NotRunning:
            self._start_requested_recording()
        # 危険予知プロセスが生存していても映像側だけが停止する場合がある。
        # 録画が映像を供給していない時はプレビューを再試行する。
        if (self.runtime.preview_requested and self.runtime.recorder.state() == QProcess.ProcessState.NotRunning
                and self.runtime.preview.state() == QProcess.ProcessState.NotRunning):
            self._sync_preview()
        if self.adas_requested and self.runtime.adas.state() == QProcess.ProcessState.NotRunning:
            self._start_requested_adas()

    def _start_requested_adas(self) -> None:
        if self.adas_requested and not self.runtime.start_adas():
            self.adas_feature_button.setText("危険予知：開始失敗")
            self._adas_status = "開始失敗"
            self._set_feature_error("危険予知", self.runtime_status.text() + "（再試行中）")
            self._refresh_main_status()

    def toggle_adas_feature(self, enabled: bool) -> None:
        if self.runtime.transfer_phase not in {"idle", "error"} or self.runtime.embedded_transfer:
            self.adas_feature_button.blockSignals(True)
            self.adas_feature_button.setChecked(self.adas_requested)
            self.adas_feature_button.blockSignals(False)
            self.runtime_status.setText("転送を終了してから危険予知を変更してください")
            return
        if enabled:
            self.adas_requested = True
            self.preferences.setValue("feature_adas", True)
            self.runtime.preview_requested = True
            self.adas_feature_button.setText("危険予知：開始待ち")
            self._start_requested_adas()
        elif self.runtime.stop_adas():
            self.adas_requested = False
            self._set_feature_error("危険予知")
            self.preferences.setValue("feature_adas", False)
            self.adas_feature_button.setText("危険予知：オフ")
            self._adas_status = "停止"
            self._clear_warnings()
            self.runtime.preview_requested = self.reverse or self.camera_display_mode != "off"
            self._sync_preview()
            self._refresh_main_status()
        else:
            self.adas_feature_button.blockSignals(True)
            self.adas_feature_button.setChecked(True)
            self.adas_feature_button.blockSignals(False)

    def on_adas_process_changed(self, running: bool) -> None:
        if running:
            self._adas_status = "準備中"
            self.adas_feature_button.setText("危険予知：準備中")
        else:
            self._adas_status = "停止" if not self.adas_requested else "停止中"
            self.adas_feature_button.setText("危険予知：オフ" if not self.adas_requested else "危険予知：停止")
            self._clear_warnings()
        self._refresh_main_status()

    def on_adas_result(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        kind = payload.get("type")
        role = payload.get("camera")
        if kind == "result":
            if role != self.runtime.analysis_camera or not self.adas_requested:
                return
            if self._adas_status != "稼働":
                self.runtime_status.setText("危険予知が動作しています")
            self._set_feature_error("危険予知")
            self._adas_status = "稼働"
            self.adas_feature_button.setText("危険予知：オン")
            now_ns = time.time_ns()
            emitted = payload.get("emitted_time_ns", now_ns)
            source = payload.get("source_time_ns", now_ns)
            self._adas_latency = {
                "transport_ms": max(0, (now_ns-emitted)/1e6),
                "source_to_ui_ms": max(0, (now_ns-source)/1e6),
                "analysis_ms": payload.get("analysis_ms"),
            }
            self.warning_stale_timer.start()
            alerts = payload.get("alerts", [])
            self._adas_alerts = alerts if isinstance(alerts, list) else []
            blind_reason = payload.get('blind_reason') if payload.get('blind') else None
            if blind_reason:
                self._set_feature_error('映像状態', str(blind_reason))
                self._adas_alerts.append({'level': 2, 'direction': '中央', 'category': '映像異常'})
            else:
                self._set_feature_error('映像状態')
            self._refresh_combined_warnings()
            self._refresh_main_status()
            warning_updated_ns = time.time_ns()
            self._adas_latency["source_to_warning_update_ms"] = max(0, (warning_updated_ns-source)/1e6)
            self._adas_latency["signal_to_warning_update_ms"] = max(0, (warning_updated_ns-emitted)/1e6)
            return
        if kind in {"status", "error"}:
            state = payload.get("status")
            if kind == "error":
                self._set_feature_error("危険予知", str(payload.get("message", "エラーが発生しました")) + "（再試行中）")
                self._adas_status = "エラー"
                self.adas_feature_button.setText("危険予知：エラー")
            elif state in {"switching", "stale", "stopped"}:
                self._adas_status = {"switching": "切替中", "stale": "映像待ち", "stopped": "停止"}[state]
            self._clear_warnings()
            self._refresh_main_status()

    def on_sensor_status(self, status: str) -> None:
        self._sensor_status = status
        if status != "監視中":
            self._sensor_alerts.clear()
            self._refresh_sensor_distances()
            self._refresh_combined_warnings()
        self._refresh_main_status()

    def on_sensor_obstacle(self, side: str, distance, level: int) -> None:
        if side not in {"left", "right"}:
            return
        if distance is None:
            self._sensor_alerts.pop(side, None)
        else:
            self._sensor_alerts[side] = {"level": level, "direction": "左" if side == "left" else "右",
                                         "category": "障害物", "distance": float(distance),
                                         "expires": time.monotonic() + 1.5}
        self._refresh_sensor_distances()
        self._refresh_combined_warnings()

    def _expire_sensor_alerts(self) -> None:
        now = time.monotonic()
        expired = [side for side, alert in self._sensor_alerts.items() if alert["expires"] <= now]
        for side in expired:
            del self._sensor_alerts[side]
        if expired:
            self._refresh_sensor_distances()
            self._refresh_combined_warnings()

    def _refresh_sensor_distances(self) -> None:
        def value(side):
            alert = self._sensor_alerts.get(side)
            return f"{alert['distance']:.2f}m" if alert else "--"
        self.distance_label.setText(f"距離  左 {value('left')}  /  右 {value('right')}")

    def _refresh_combined_warnings(self) -> None:
        self._set_warning_alerts(self._adas_alerts + list(self._sensor_alerts.values()))

    def _set_warning_alerts(self, alerts: list) -> None:
        sides = {}
        max_level = 0
        for item in alerts:
            if not isinstance(item, dict):
                continue
            try:
                level = int(item.get("level", 0))
            except (TypeError, ValueError):
                continue
            if level not in (2, 3):
                continue
            max_level = max(max_level, level)
            direction = item.get("direction")
            target_sides = {"左": ("left",), "右": ("right",), "中央": ("left", "right")}.get(direction, ())
            for side in target_sides:
                if side not in sides or level > sides[side][0]:
                    sides[side] = (level, str(item.get("category", "不明")))
        previous_sides = self._warning_sides
        # 新しい方向の警告・危険度上昇は点滅の消灯期間を待たず即時点灯する。
        if any(side not in previous_sides or value[0] > previous_sides[side][0]
               for side, value in sides.items()):
            self._warning_blink = True
        self._warning_sides = sides
        if sides and not self.warning_blink_timer.isActive():
            self._warning_blink = True
            self.warning_blink_timer.start()
        elif not sides:
            self.warning_blink_timer.stop()
        self.warning_audio.set_level(max_level)
        self._render_warning_lights()

    def _render_warning_lights(self) -> None:
        for side, label in (("left", self.warning_left), ("right", self.warning_right)):
            info = self._warning_sides.get(side)
            if not info or not self._warning_blink:
                label.hide()
                continue
            level, category = info
            color = "#ff4b4b" if level == 3 else "#ffd044"
            start, end = (0, 1) if side == "left" else (1, 0)
            label.setStyleSheet(f"background: qlineargradient(x1:{start}, y1:0, x2:{end}, y2:0, stop:0 {color}, stop:1 rgba(0, 0, 0, 0)); border: 3px solid {color}; border-radius: 12px;")
            label.setPixmap(warning_icon(category, color).pixmap(44, 44))
            label.setAccessibleName(f"{category} {'危険' if level == 3 else '注意'}")
            label.show()

    def _blink_warnings(self) -> None:
        self._warning_blink = not self._warning_blink
        self._render_warning_lights()

    def _clear_warnings(self) -> None:
        self.warning_stale_timer.stop()
        self._adas_alerts = []
        self._refresh_combined_warnings()

    def _clear_stale_alerts(self) -> None:
        self._adas_status = "応答なし"
        self._clear_warnings()
        self._refresh_main_status()

    def _refresh_main_status(self) -> None:
        test = "  動画検証中" if self.runtime.video_role else ""
        self.status_label.setText(f"録画：{self._recorder_status}   AI：{self._adas_status}   センサー：{self._sensor_status}{test}")

    def _start_requested_recording(self) -> None:
        if self.recording_requested and not self.runtime.start_recorder():
            self.recording_feature_button.setText("録画：開始失敗")
            self._recorder_status = "開始失敗"
            self._set_feature_error("録画", self.runtime_status.text() + "（再試行中）")
            self._refresh_main_status()

    def toggle_recording_feature(self, enabled: bool) -> None:
        if self.runtime.transfer_phase not in {"idle", "error"} or self.runtime.embedded_transfer:
            self.recording_feature_button.blockSignals(True)
            self.recording_feature_button.setChecked(self.recording_requested)
            self.recording_feature_button.blockSignals(False)
            self.runtime_status.setText("転送を終了してから録画を変更してください")
            return
        if enabled:
            self.recording_requested = True
            self.preferences.setValue("feature_recording", True)
            self.recording_feature_button.setText("録画：開始待ち")
            self._start_requested_recording()
        elif self.runtime.stop_recorder():
            self.recording_requested = False
            self._set_feature_error("録画")
            self.preferences.setValue("feature_recording", False)
            self.recording_feature_button.setText("録画：停止中" if self.runtime.recorder.state() != QProcess.ProcessState.NotRunning else "録画：オフ")
        else:
            self.recording_feature_button.blockSignals(True)
            self.recording_feature_button.setChecked(True)
            self.recording_feature_button.blockSignals(False)

    def on_recorder_process_changed(self, running: bool) -> None:
        self._recorder_status = "準備中" if running else "停止"
        if not running:
            self._set_feature_error('録画画質')
        if not running:
            self.recording_feature_button.setText("録画：停止" if self.recording_requested else "録画：オフ")
        self._refresh_main_status()

    def on_recorder_changed(self, running: bool) -> None:
        self.event_button.setEnabled(running)
        if running:
            self._set_feature_error("録画")
            self._recorder_status = "稼働"
            self.recording_feature_button.setText("録画：オン")
        self._refresh_main_status()

    def on_transfer_phase(self, phase):
        if phase == "error" and self._transfer_retry_requested:
            self._set_feature_error("転送", "開始できません。安全確認後に再試行します")
            if not self.runtime.hotspot and not self.runtime.embedded_transfer:
                self.transfer_button.setText("転送の再試行を中止")
        if phase == "idle" and self._shutdown_pending:
            QTimer.singleShot(0, self._complete_shutdown)
        elif phase == "idle" and self._close_pending:
            self._close_pending = False
            QTimer.singleShot(0, self.close)
        elif phase == "error" and (self._shutdown_pending or self._close_pending):
            self._shutdown_pending = False
            self._close_pending = False
            self.runtime.closing = False
            self.shutdown_button.setEnabled(True)
            self.shutdown_button.setText("電源停止")
        busy = phase in {"preparing", "stopping", "restoring"}
        self.transfer_button.setEnabled(not busy)
        self.recording_feature_button.setEnabled(not busy and not self.runtime.embedded_transfer)
        self.adas_feature_button.setEnabled(not busy and not self.runtime.embedded_transfer)
        self.reverse_button.setEnabled(not busy and not self.runtime.embedded_transfer)
        if phase == "error" and (self.runtime.embedded_transfer or self.runtime.hotspot):
            self.transfer_button.setText("転送停止を再試行")

    def on_transfer_changed(self, running: bool) -> None:
        if running:
            self._transfer_retry_requested = False
            self._set_feature_error("転送")
        self.transfer_button.setText("転送を終了" if running else "転送")
        self.reverse_button.setEnabled(not running)
        self.camera_display.setEnabled(not running)
        self.recording_feature_button.setEnabled(not running)
        self.adas_feature_button.setEnabled(not running)
        if running:
            self.reverse_frame_timer.stop()
            import qrcode
            url = self.runtime.transfer_url
            qr = qrcode.make(url).convert("RGB")
            picture = QImage(qr.tobytes(), qr.width, qr.height, qr.width*3, QImage.Format.Format_RGB888).copy()
            dialog = QDialog(self)
            dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
            dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.transfer_dialog = dialog
            dialog.setWindowTitle("動画転送")
            dialog.setMinimumWidth(520)
            layout = QVBoxLayout(dialog)
            wifi = self.runtime.transfer_wifi
            if wifi:
                layout.addWidget(QLabel("① Wi-Fiに接続 → ② 動画一覧を開く"))
                codes = QHBoxLayout()
                wifi_qr = qrcode.make(wifi["wifi_qr"]).convert("RGB")
                wifi_image = QImage(wifi_qr.tobytes(), wifi_qr.width, wifi_qr.height,
                                    wifi_qr.width * 3, QImage.Format.Format_RGB888).copy()
                for title, image in (("① Wi-Fi接続", wifi_image), ("② 動画一覧", picture)):
                    column = QVBoxLayout()
                    heading = QLabel(title)
                    heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    code = QLabel()
                    code.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    code.setPixmap(QPixmap.fromImage(image).scaled(160, 160,
                        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))
                    column.addWidget(heading)
                    column.addWidget(code)
                    codes.addLayout(column)
                layout.addLayout(codes)
                credentials = QLabel(f"Wi-Fi: {wifi['ssid']}　パスワード: {wifi['password']}")
                credentials.setWordWrap(True)
                layout.addWidget(credentials)
            else:
                layout.addWidget(QLabel("スマホを同じWi-Fiにつなぎ、QRコードを読み取ってください"))
                label = QLabel()
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setPixmap(QPixmap.fromImage(picture).scaled(200,200,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.FastTransformation))
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
        if hasattr(self, "volume_apply_timer") and self.volume_slider.isEnabled() and not self.volume_apply_timer.isActive():
            self.volume_apply_timer.start()

    def apply_volume(self) -> None:
        self.volume_apply_timer.stop()
        if not self.audio_control.set_percent(self.volume_slider.value()):
            self.runtime_status.setText("音量を変更できません。音声出力デバイスを確認してください")
        if not self.volume_slider.isSliderDown():
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
        if self.runtime.embedded_transfer or self.runtime.hotspot:
            self.runtime.end_transfer()
        elif self._transfer_retry_requested:
            self._transfer_retry_requested = False
            self._set_feature_error("転送")
            self.transfer_button.setText("転送")
        else:
            self._transfer_retry_requested = True
            if not self.runtime.begin_transfer():
                self._set_feature_error("転送", "開始できません。安全確認後に再試行します")
                self.transfer_button.setText("転送の再試行を中止")

    def request_shutdown(self) -> None:
        if not self.runtime.config.get("allow_os_shutdown", False):
            return
        answer = QMessageBox.question(self, "システム停止", "録画を安全に停止して端末をシャットダウンしますか？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.shutdown_button.setEnabled(False)
        self.shutdown_button.setText("安全に停止中…")
        if self.runtime.embedded_transfer or self.runtime.hotspot:
            self._shutdown_pending = True
            self.runtime.closing = True
            self.runtime.restart_recorder_after_transfer = False
            self.runtime.end_transfer()
        else:
            self._complete_shutdown()

    def _complete_shutdown(self) -> None:
        self._shutdown_pending = False
        if not self.runtime.stop():
            self.shutdown_button.setEnabled(True)
            self.shutdown_button.setText("電源停止")
            return
        sudo = shutil.which("sudo")
        systemctl = shutil.which("systemctl")
        if not sudo or not systemctl:
            self.runtime.closing = False
            self.shutdown_button.setEnabled(True)
            self.shutdown_button.setText("電源停止")
            self.runtime_status.setText("端末停止コマンドが見つかりません")
            return
        self._shutdown_process = QProcess(self)
        self._shutdown_process.finished.connect(self._shutdown_command_finished)
        self._shutdown_process.errorOccurred.connect(lambda _: self._shutdown_command_failed())
        self._shutdown_process.start(sudo, ["-n", systemctl, "poweroff"])

    def _shutdown_command_finished(self, code: int, _status) -> None:
        if code != 0:
            self._shutdown_command_failed()

    def _shutdown_command_failed(self) -> None:
        self.runtime.closing = False
        self.shutdown_button.setEnabled(True)
        self.shutdown_button.setText("電源停止")
        self.runtime_status.setText("端末を停止できません。権限と電源設定を確認してください")

    def closeEvent(self, event) -> None:
        if self.worker is not None:
            self.worker.stop()
            if not self.worker.wait(5000):
                self.status_label.setText("動画の停止を待っています")
                event.ignore()
                return
        self.warning_audio.stop()
        if self.runtime.embedded_transfer or self.runtime.hotspot:
            if self.runtime.transfer_phase not in {"preparing", "stopping", "restoring"}:
                self._close_pending = True
                self.runtime.closing = True
                self.runtime.restart_recorder_after_transfer = False
                self.runtime.end_transfer()
            event.ignore()
            return
        if not self.runtime.stop():
            event.ignore()
            return
        self.warning_audio.close()
        event.accept()

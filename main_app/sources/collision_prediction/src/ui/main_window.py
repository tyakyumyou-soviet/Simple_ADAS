from __future__ import annotations

from pathlib import Path
import json
import os
import time

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.render.renderer import display_alert_message
from src.input.camera import CameraSource
from src.input.video_file import VideoFileSource, RealtimeVideoSource
from src.ui.inference_thread import InferenceThread
from src.ui.async_camera_thread import AsyncCameraThread
from src.ui.camera_metrics import camera_follow_ratio
from src.ui.settings_dialog import SettingsDialog
from src.utils.config import (
    load_config,
    save_custom_profile,
)

HAILO_WEIGHTS = "models/hailo8/yolov8m.hef"
HAILO_YOLO26_WEIGHTS = [f"models/hailo8/yolo26{size}.hef" for size in ("n", "s", "m")]


class MainWindow(QMainWindow):
    def __init__(self, config_path: str | Path = "config/pi_async_ai_hat_2.yaml"):
        super().__init__()
        self.config_path = Path(config_path)
        self._profiles = self._build_profile_list()
        if not any(Path(path).resolve() == self.config_path.resolve() for _, path in self._profiles):
            self.config_path = Path(self._profiles[-1][1])
        self.cfg = load_config(self.config_path)
        ui_cfg = self.cfg.get("ui", {})
        self.setWindowTitle("簡易ADAS")
        self.resize(int(ui_cfg.get("width", 1280)), int(ui_cfg.get("height", 800)))
        self.thread: InferenceThread | None = None
        # 最後に開いたソースを再生成する factory（停止 → 再開で使う）
        self._last_source_factory = None
        self._settings_dialog: SettingsDialog | None = None
        self._perf_log_path = os.environ.get("CAR_PROGRAM2_PERF_LOG")
        self._perf_log_next = 0.0
        self._build_ui()
        self._build_menu()

    def closeEvent(self, event) -> None:
        # 詳細設定ダイアログが開いていれば閉じる
        if self._settings_dialog is not None:
            try:
                self._settings_dialog.close()
            except Exception:
                pass
            self._settings_dialog = None
        self._stop()
        super().closeEvent(event)

    def _build_ui(self) -> None:
        self.video_label = QLabel("入力ソースを選択してください")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(320, 240)
        self.video_label.setStyleSheet("background: #111; color: #ddd;")

        self.btn_play = QPushButton("再生/一時停止")
        self.btn_stop = QPushButton("停止")
        self.fps_label = QLabel("FPS: -")
        self.accel_label = QLabel("AI推論: 未実行")
        self.accel_label.setWordWrap(True)
        self.resolution_label = QLabel("解像度: 未取得")
        self.resolution_label.setWordWrap(True)
        self.frame_label = QLabel("フレーム: -")
        self.lag_label = QLabel("実時間比: -")
        self.lag_label.setMinimumWidth(140)
        self.lag_label.setToolTip("動画は元の再生速度との比、カメラは実測した入力FPSに対する追従率です。")
        self.lag_avg_label = QLabel("平均: -")
        self.lag_avg_label.setMinimumWidth(120)
        self.lag_avg_label.setToolTip("起動からの累積平均速度比")
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setEnabled(False)
        self.seek_slider.sliderReleased.connect(self._seek)

        self.center_label, self.center_slider = self._lane_slider("台形ゾーン中心", "center_x_ratio", 35, 65, 100)
        self.depth_label, self.depth_slider = self._lane_slider("台形の奥行き(固定値)", "zone_top_y_ratio", 20, 80, 100, invert_label=True)
        self.width_label, self.width_slider = self._lane_slider("手前幅", "zone_bottom_width_ratio", 20, 70, 100)
        self.curve_label, self.curve_slider = self._lane_slider("カーブ寄せ", "zone_top_offset_ratio", -20, 20, 100)
        # 奥行きモード切替
        self.depth_mode_label = QLabel("奥行きモード")
        self.depth_mode_combo = QComboBox()
        self.depth_mode_combo.addItems(["自動 (消失点ベース)", "固定 (スライダー値)"])
        self.depth_mode_combo.setCurrentIndex(0 if self.cfg.get("lane", {}).get("auto_depth", True) else 1)
        self.depth_mode_combo.currentIndexChanged.connect(self._sync_feature_flags)

        self.chk_enhancement = self._checkbox("視認性補正", "enable_enhancement")
        self.chk_detection = self._checkbox("検出/追跡", "enable_detection")
        self.chk_lanes = self._checkbox("車線/LDW", "enable_lanes")
        self.chk_curves = self._checkbox("曲線車線（試験中）", "curve_lanes", default=False)
        self.chk_signs = self._checkbox("信号/標識", "enable_signs")
        self.chk_risk = self._checkbox("危険判定", "enable_risk")
        self.chk_mask = self._checkbox("路面マスク", "show_debug_mask")
        self.chk_blind = self._checkbox("カメラ異常検知", "enable_blind_check")
        self.chk_blind.setToolTip("検出ゼロ + 画質劣化 (真っ暗/単色/ボケ) の AND で「検出不能」通知。レンズ汚れ・霧・遮蔽を一括カバー")
        scene_cfg = self.cfg.setdefault("hailo_scene", {})
        scene_cfg.setdefault("depth_enabled", scene_cfg.get("enabled", str(self.cfg.get("detector", {}).get("weights", "")).endswith(".hef")))
        self.chk_ai_depth = QCheckBox("AI奥行き推定")
        self.chk_ai_depth.setToolTip("AI HAT+の相対奥行き・接近傾向・進路の重なりを危険判定へ組み込みます。未分類障害物も対象。実距離ではありません。")
        self.chk_ai_depth.setChecked(bool(scene_cfg.get("depth_enabled", scene_cfg.get("enabled", True))))
        self.chk_ai_depth.toggled.connect(self._sync_feature_flags)
        self.chk_ai_depth_preview = self._checkbox("AI奥行き画像を左上に表示", "show_ai_depth_preview", default=False)
        self.chk_ai_depth_preview.setToolTip("AI奥行きの相対ヒートマップを映像の左上に重ねて表示します。")
        self.ai_depth_interval_label = QLabel("AI奥行きの更新間隔")
        self.ai_depth_interval_combo = QComboBox()
        for seconds in (0.2, 0.4, 0.6, 0.8, 1.0):
            self.ai_depth_interval_combo.addItem(f"{seconds:.1f}秒ごと", seconds)
        self.ai_depth_interval_combo.setToolTip("推論を行う間隔の目安です。処理が混み合うと更新は遅くなります。")
        scene_cfg.setdefault("depth_update_hz", 1.0)
        self._sync_ai_depth_interval()
        self.ai_depth_interval_combo.currentIndexChanged.connect(self._sync_feature_flags)

        # ROI モード切替 + 矩形パラメータ
        self.roi_mode_label = QLabel("ROI 推論")
        self.roi_mode_label.setToolTip("YOLO 入力を限定して高速化。OFF / 台形 (自車レーン) / 矩形 (手動)")
        self.roi_mode_combo = QComboBox()
        self._roi_mode_options = [
            ("OFF (全画面)", "off"),
            ("台形 (自車レーン)", "trapezoid"),
            ("矩形 (手動指定)", "rectangle"),
        ]
        for label, _ in self._roi_mode_options:
            self.roi_mode_combo.addItem(label)
        current_mode = str(self.cfg.get("ui", {}).get("roi_mode", "off"))
        # 後方互換: enable_roi_crop=True を trapezoid と解釈
        if current_mode == "off" and bool(self.cfg.get("ui", {}).get("enable_roi_crop", False)):
            current_mode = "trapezoid"
        try:
            ridx = next(i for i, (_, m) in enumerate(self._roi_mode_options) if m == current_mode)
        except StopIteration:
            ridx = 0
        self.roi_mode_combo.setCurrentIndex(ridx)
        self.roi_mode_combo.currentIndexChanged.connect(self._sync_feature_flags)

        # 矩形 ROI の 4 スライダー (X 位置 / Y 位置 / 幅 / 高さ、全て 0-100%)
        rect_cfg = self.cfg.get("ui", {}).get("roi_rect", {}) or {}
        self.roi_rect_x_label, self.roi_rect_x_slider = self._make_roi_slider(
            "ROI 矩形 X 位置", "x_ratio", int(float(rect_cfg.get("x_ratio", 0.05)) * 100))
        self.roi_rect_y_label, self.roi_rect_y_slider = self._make_roi_slider(
            "ROI 矩形 Y 位置", "y_ratio", int(float(rect_cfg.get("y_ratio", 0.30)) * 100))
        self.roi_rect_w_label, self.roi_rect_w_slider = self._make_roi_slider(
            "ROI 矩形 幅", "w_ratio", int(float(rect_cfg.get("w_ratio", 0.90)) * 100))
        self.roi_rect_h_label, self.roi_rect_h_slider = self._make_roi_slider(
            "ROI 矩形 高さ", "h_ratio", int(float(rect_cfg.get("h_ratio", 0.65)) * 100))
        self._set_roi_rect_sliders_enabled(current_mode == "rectangle")

        # 処理解像度（max_process_width）: 0 = 自動（元のまま）
        self.quality_label = QLabel("処理解像度")
        self.quality_combo = QComboBox()
        self._quality_options = [
            ("自動 (元のまま)", 0),
            ("1280px (高画質)", 1280),
            ("960px (標準)", 960),
            ("720px", 720),
            ("540px (軽量)", 540),
            ("360px (超軽量)", 360),
            ("320px (Pi 向け)", 320),
        ]
        self._camera_sizes = CameraSource.supported_sizes(0)
        if self._camera_sizes:
            self._quality_options = [(f"{w}×{h}", w) for w, h in self._camera_sizes]
        # 表示解像度 (display_max_width): overlay の精細さを決める
        self.display_quality_label = QLabel("表示解像度")
        self.display_quality_label.setToolTip(
            "表示キャンバスのサイズ。動画ピクセルは処理解像度のまま引き伸ばしされるが、"
            "BB/矢印/文字はこの解像度で描画される。大きいほど overlay が綺麗"
        )
        self.display_quality_combo = QComboBox()
        self._display_quality_options = [
            ("元動画サイズ", 0),
            ("1920px (高画質)", 1920),
            ("1280px (推奨)", 1280),
            ("960px", 960),
            ("720px", 720),
            ("540px (軽量)", 540),
            ("360px (超軽量)", 360),
            ("320px (Pi 向け)", 320),
            ("240px (極小)", 240),
            ("160px (最小)", 160),
            ("80px (実験)", 80),
        ]
        for label, _ in self._display_quality_options:
            self.display_quality_combo.addItem(label)
        current_dw = int(self.cfg.get("ui", {}).get("display_max_width", 0) or 0)
        try:
            didx = next(i for i, (_, w) in enumerate(self._display_quality_options) if w == current_dw)
        except StopIteration:
            self._display_quality_options.append((f"{current_dw}px (カスタム)", current_dw))
            self.display_quality_combo.addItem(self._display_quality_options[-1][0])
            didx = len(self._display_quality_options) - 1
        self.display_quality_combo.setCurrentIndex(didx)
        self.display_quality_combo.currentIndexChanged.connect(self._sync_feature_flags)

        # 重ね表示の大きさ (枠 / 矢印 / 文字すべてに効く倍率)
        self.thickness_label = QLabel("重ね表示の大きさ")
        self.thickness_label.setToolTip("BB / 矢印 / 文字すべての大きさ倍率。極小→極大の 5 段階")
        self.thickness_combo = QComboBox()
        self._thickness_options = [
            ("極小 (0.5x)", 0.5),
            ("小さい (0.75x)", 0.75),
            ("普通 (1.0x)", 1.0),
            ("大きい (1.5x)", 1.5),
            ("極大 (2.0x)", 2.0),
        ]
        for label, _ in self._thickness_options:
            self.thickness_combo.addItem(label)
        current_th = float(self.cfg.get("ui", {}).get("overlay_size_scale", 1.0))
        try:
            tidx = next(i for i, (_, v) in enumerate(self._thickness_options) if abs(v - current_th) < 1e-3)
        except StopIteration:
            tidx = 2  # 普通
        self.thickness_combo.setCurrentIndex(tidx)
        self.thickness_combo.currentIndexChanged.connect(self._sync_feature_flags)
        for label, _ in self._quality_options:
            self.quality_combo.addItem(label)
        current_w = int(self.cfg.get("ui", {}).get("max_process_width", 0) or 0)
        try:
            qidx = next(i for i, (_, w) in enumerate(self._quality_options) if w == current_w)
        except StopIteration:
            if self._camera_sizes:
                qidx = min(range(len(self._quality_options)), key=lambda i: (abs(self._quality_options[i][1]-current_w), self._quality_options[i][1]))
                self.cfg.setdefault("ui", {})["max_process_width"] = self._quality_options[qidx][1]
            else:
                self._quality_options.append((f"{current_w}px (カスタム)", current_w))
                self.quality_combo.addItem(self._quality_options[-1][0])
                qidx = len(self._quality_options) - 1
        self.quality_combo.setCurrentIndex(qidx)
        self.quality_combo.currentIndexChanged.connect(self._sync_feature_flags)

        # AI HAT+ に対応するモデルのみ表示する。
        self.yolo_label = QLabel("YOLOモデル")
        self.yolo_combo = QComboBox()
        self._yolo_options = [
            ("Hailo-8 YOLOv8m (AI HAT+)", HAILO_WEIGHTS),
            *[(f"Hailo-8 YOLO26{size} (AI HAT+)", weight)
              for size, weight in zip(("n", "s", "m"), HAILO_YOLO26_WEIGHTS)],
        ]
        for label, _ in self._yolo_options:
            self.yolo_combo.addItem(label)
        current_w = str(self.cfg.get("detector", {}).get("weights", "models/yolo11n.pt"))
        try:
            yidx = next(i for i, (_, p) in enumerate(self._yolo_options) if p == current_w)
        except StopIteration:
            yidx = 0
            self.cfg.setdefault("detector", {})["weights"] = self._yolo_options[yidx][1]
        self.yolo_combo.setCurrentIndex(yidx)
        self.yolo_combo.currentIndexChanged.connect(self._sync_feature_flags)

        # 解析間隔（detector + lane every_n_frames）
        self.skip_label = QLabel("解析間隔")
        self.skip_combo = QComboBox()
        self._skip_options = [(f"{n}フレーム毎" if n > 1 else "毎フレーム", n) for n in range(1, 21)]
        for label, _ in self._skip_options:
            self.skip_combo.addItem(label)
        current_n = int(self.cfg.get("detector", {}).get("every_n_frames", 1))
        try:
            sidx = next(i for i, (_, n) in enumerate(self._skip_options) if n == current_n)
        except StopIteration:
            sidx = 0
        self.skip_combo.setCurrentIndex(sidx)
        self.skip_combo.setEnabled(not bool(self.cfg.get("ui", {}).get("independent_schedule", False)))
        self.skip_combo.setToolTip("Pi 高速では詳細設定の各更新回数/秒を使用します。")
        self.skip_combo.currentIndexChanged.connect(self._sync_feature_flags)

        side = QVBoxLayout()
        side.addWidget(QLabel("プロファイル"))
        self.profile_combo = QComboBox()
        for profile_label, _ in self._profiles:
            self.profile_combo.addItem(profile_label)
        # 現在の config_path から初期選択を決定
        try:
            current_index = next(i for i, (_, p) in enumerate(self._profiles)
                                 if Path(p).resolve() == self.config_path.resolve())
        except StopIteration:
            current_index = 0
        self.profile_combo.setCurrentIndex(current_index)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        side.addWidget(self.profile_combo)
        side.addWidget(self.depth_mode_label)
        side.addWidget(self.depth_mode_combo)
        for label, slider in (
            (self.center_label, self.center_slider),
            (self.depth_label, self.depth_slider),
            (self.width_label, self.width_slider),
            (self.curve_label, self.curve_slider),
        ):
            side.addWidget(label)
            side.addWidget(slider)
        side.addWidget(self.yolo_label)
        side.addWidget(self.yolo_combo)
        side.addWidget(self.accel_label)
        side.addWidget(self.quality_label)
        side.addWidget(self.quality_combo)
        side.addWidget(self.display_quality_label)
        side.addWidget(self.display_quality_combo)
        side.addWidget(self.resolution_label)
        side.addWidget(self.thickness_label)
        side.addWidget(self.thickness_combo)
        side.addWidget(self.skip_label)
        side.addWidget(self.skip_combo)
        side.addWidget(QLabel("機能"))
        for checkbox in (
            self.chk_detection,
            self.chk_lanes,
            self.chk_curves,
            self.chk_risk,
            self.chk_signs,
            self.chk_enhancement,
            self.chk_mask,
            self.chk_blind,
            self.chk_ai_depth,
            self.chk_ai_depth_preview,
        ):
            side.addWidget(checkbox)
        side.addWidget(self.ai_depth_interval_label)
        side.addWidget(self.ai_depth_interval_combo)
        side.addWidget(self.roi_mode_label)
        side.addWidget(self.roi_mode_combo)
        for lbl, sld in (
            (self.roi_rect_x_label, self.roi_rect_x_slider),
            (self.roi_rect_y_label, self.roi_rect_y_slider),
            (self.roi_rect_w_label, self.roi_rect_w_slider),
            (self.roi_rect_h_label, self.roi_rect_h_slider),
        ):
            side.addWidget(lbl)
            side.addWidget(sld)
        self.btn_settings = QPushButton("詳細設定...")
        self.btn_settings.setToolTip("プロファイル YAML の全項目を編集 (ライブ反映)")
        self.btn_settings.clicked.connect(self._open_settings_dialog)
        side.addWidget(self.btn_settings)
        self.btn_save_profile = QPushButton("このプロファイルに保存")
        self.btn_save_profile.setToolTip("現在選択中のプロファイルに設定を保存します")
        self.btn_save_profile.clicked.connect(self._save_selected_profile)
        side.addWidget(self.btn_save_profile)
        side.addStretch(1)

        self.alert_table = QTableWidget(0, 5)
        self.alert_table.setHorizontalHeaderLabels(["レベル", "種別", "対象", "方向", "内容"])
        self.alert_table.setColumnHidden(1, True)
        self.alert_table.setColumnHidden(2, True)
        self.alert_table.verticalHeader().setVisible(False)
        self.alert_table.setMaximumHeight(180)

        center = QVBoxLayout()
        center.addWidget(self.video_label, 1)
        center.addWidget(self.alert_table)

        main = QHBoxLayout()
        left = QWidget()
        left.setLayout(side)
        left_scroll = QScrollArea()
        left_scroll.setWidget(left)
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(200)
        left_scroll.setMaximumWidth(280)
        self.setMinimumSize(560, 400)
        main.addWidget(left_scroll)
        main.addLayout(center, 1)

        ctrl = QHBoxLayout()
        ctrl.addWidget(self.btn_play)
        ctrl.addWidget(self.btn_stop)
        ctrl.addWidget(self.seek_slider, 1)
        ctrl.addWidget(self.fps_label)
        ctrl.addWidget(self.frame_label)
        ctrl.addWidget(self.lag_label)
        ctrl.addWidget(self.lag_avg_label)

        layout = QVBoxLayout()
        layout.addLayout(main, 1)
        layout.addLayout(ctrl)
        root = QWidget()
        root.setLayout(layout)
        self.setCentralWidget(root)

        self.btn_play.clicked.connect(self._play_pause)
        self.btn_stop.clicked.connect(self._stop)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("ファイル")
        open_action = QAction("動画ファイルを開く...", self)
        open_action.triggered.connect(self._open_file)
        camera_action = QAction("カメラを選択...", self)
        camera_action.triggered.connect(self._open_camera)
        file_menu.addAction(open_action)
        file_menu.addAction(camera_action)

    def _checkbox(self, text: str, key: str, default: bool = True) -> QCheckBox:
        checkbox = QCheckBox(text)
        checkbox.setChecked(bool(self.cfg.get("ui", {}).get(key, default)))
        checkbox.stateChanged.connect(self._sync_feature_flags)
        checkbox.setProperty("config_key", key)
        checkbox.setProperty("default_checked", default)
        return checkbox

    def _sync_feature_flags(self) -> None:
        changed = self.sender()
        ui_cfg = self.cfg.setdefault("ui", {})
        lane_cfg = self.cfg.setdefault("lane", {})
        for slider in (self.center_slider, self.depth_slider, self.width_slider, self.curve_slider):
            if changed is slider:
                lane_cfg[str(slider.property("config_key"))] = slider.value() / 100
        if changed is self.depth_mode_combo:
            lane_cfg["auto_depth"] = self.depth_mode_combo.currentIndex() == 0
        for checkbox in (
            self.chk_detection,
            self.chk_lanes,
            self.chk_curves,
            self.chk_risk,
            self.chk_signs,
            self.chk_enhancement,
            self.chk_mask,
            self.chk_blind,
            self.chk_ai_depth_preview,
        ):
            if changed is checkbox:
                ui_cfg[str(checkbox.property("config_key"))] = checkbox.isChecked()
        if changed is self.chk_ai_depth:
            self.cfg.setdefault("hailo_scene", {})["depth_enabled"] = self.chk_ai_depth.isChecked()
        if changed is self.ai_depth_interval_combo:
            seconds = self.ai_depth_interval_combo.currentData()
            if seconds:
                self.cfg.setdefault("hailo_scene", {})["depth_update_hz"] = 1.0 / float(seconds)
        # 処理解像度・表示解像度・解析間隔・YOLOモデル
        if changed is self.quality_combo:
            ui_cfg["max_process_width"] = int(self._quality_options[self.quality_combo.currentIndex()][1])
        if changed is self.display_quality_combo:
            ui_cfg["display_max_width"] = int(self._display_quality_options[self.display_quality_combo.currentIndex()][1])
        if changed is self.thickness_combo:
            ui_cfg["overlay_size_scale"] = float(self._thickness_options[self.thickness_combo.currentIndex()][1])
        detector_cfg = self.cfg.setdefault("detector", {})
        if changed is self.skip_combo:
            skip_value = int(self._skip_options[self.skip_combo.currentIndex()][1])
            detector_cfg["every_n_frames"] = skip_value
            lane_cfg["every_n_frames"] = skip_value
        if changed is self.yolo_combo:
            detector_cfg["weights"] = self._yolo_options[self.yolo_combo.currentIndex()][1]
        # ROI モード + 矩形パラメータ
        _, roi_mode = self._roi_mode_options[self.roi_mode_combo.currentIndex()]
        if changed is self.roi_mode_combo:
            ui_cfg["roi_mode"] = roi_mode
        for slider, key in ((self.roi_rect_x_slider, "x_ratio"), (self.roi_rect_y_slider, "y_ratio"),
                            (self.roi_rect_w_slider, "w_ratio"), (self.roi_rect_h_slider, "h_ratio")):
            if changed is slider:
                ui_cfg.setdefault("roi_rect", {})[key] = slider.value() / 100
        self._set_roi_rect_sliders_enabled(roi_mode == "rectangle")
        # 再生中ならスレッドに通知して Pipeline へ live 反映
        if (changed is self.quality_combo and self.thread is not None and self.thread.isRunning()
                and isinstance(self.thread.source, CameraSource)):
            was_paused = self.thread.paused
            self._start_source()
            if was_paused and self.thread is not None:
                self.thread.pause()
                self.btn_play.setText("再生")
        elif self.thread is not None and hasattr(self.thread, "apply_settings"):
            self.thread.apply_settings(self.cfg)

    def _lane_slider(
        self,
        text: str,
        key: str,
        min_value: int,
        max_value: int,
        scale: int,
        invert_label: bool = False,
    ) -> tuple[QLabel, QSlider]:
        label = QLabel()
        slider = QSlider(Qt.Horizontal)
        slider.setRange(min_value, max_value)
        slider.setValue(int(float(self.cfg.get("lane", {}).get(key, 0.5 if key == "center_x_ratio" else 0.0)) * scale))
        slider.setProperty("config_key", key)
        slider.setProperty("label_text", text)
        slider.setProperty("invert_label", invert_label)
        slider.valueChanged.connect(self._sync_feature_flags)
        slider.valueChanged.connect(lambda _value, target=slider, target_label=label: self._update_lane_slider_label(target_label, target))
        self._update_lane_slider_label(label, slider)
        return label, slider

    def _update_lane_slider_label(self, label: QLabel, slider: QSlider) -> None:
        value = slider.value()
        if bool(slider.property("invert_label")):
            value = 100 - value
        label.setText(f"{slider.property('label_text')}: {value}%")

    def _sync_ai_depth_interval(self) -> None:
        hz = max(0.1, float(self.cfg.get("hailo_scene", {}).get("depth_update_hz", 1.0)))
        seconds = 1.0 / hz
        combo = self.ai_depth_interval_combo
        combo.blockSignals(True)
        while combo.count() > 5:
            combo.removeItem(combo.count() - 1)
        index = next((i for i in range(combo.count()) if abs(float(combo.itemData(i)) - seconds) < 0.001), -1)
        if index < 0:
            combo.addItem(f"{seconds:.2f}秒ごと（カスタム）", seconds)
            index = combo.count() - 1
        combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _apply_feature_flags(self) -> None:
        ui_cfg = self.cfg.get("ui", {})
        lane_cfg = self.cfg.get("lane", {})
        self.depth_mode_combo.blockSignals(True)
        self.depth_mode_combo.setCurrentIndex(0 if lane_cfg.get("auto_depth", True) else 1)
        self.depth_mode_combo.blockSignals(False)
        for slider, label in (
            (self.center_slider, self.center_label),
            (self.depth_slider, self.depth_label),
            (self.width_slider, self.width_label),
            (self.curve_slider, self.curve_label),
        ):
            key = str(slider.property("config_key"))
            slider.blockSignals(True)
            slider.setValue(int(float(lane_cfg.get(key, slider.value() / 100)) * 100))
            slider.blockSignals(False)
            self._update_lane_slider_label(label, slider)
        for checkbox in (
            self.chk_detection,
            self.chk_lanes,
            self.chk_curves,
            self.chk_risk,
            self.chk_signs,
            self.chk_enhancement,
            self.chk_mask,
            self.chk_blind,
            self.chk_ai_depth_preview,
        ):
            key = str(checkbox.property("config_key"))
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(ui_cfg.get(key, checkbox.property("default_checked"))))
            checkbox.blockSignals(False)
        scene_cfg = self.cfg.get("hailo_scene", {})
        self.chk_ai_depth.blockSignals(True)
        self.chk_ai_depth.setChecked(bool(scene_cfg.get("depth_enabled", scene_cfg.get("enabled", True))))
        self.chk_ai_depth.blockSignals(False)
        self._sync_ai_depth_interval()
        # 処理解像度・解析間隔の再同期
        current_w = int(ui_cfg.get("max_process_width", 0) or 0)
        try:
            qidx = next(i for i, (_, w) in enumerate(self._quality_options) if w == current_w)
        except StopIteration:
            if self._camera_sizes:
                qidx = min(range(len(self._quality_options)), key=lambda i: (abs(self._quality_options[i][1]-current_w), self._quality_options[i][1]))
                ui_cfg["max_process_width"] = self._quality_options[qidx][1]
            else:
                self._quality_options.append((f"{current_w}px (カスタム)", current_w))
                self.quality_combo.addItem(self._quality_options[-1][0])
                qidx = len(self._quality_options) - 1
        self.quality_combo.blockSignals(True)
        self.quality_combo.setCurrentIndex(qidx)
        self.quality_combo.blockSignals(False)
        current_dw = int(ui_cfg.get("display_max_width", 0) or 0)
        try:
            didx = next(i for i, (_, w) in enumerate(self._display_quality_options) if w == current_dw)
        except StopIteration:
            self._display_quality_options.append((f"{current_dw}px (カスタム)", current_dw))
            self.display_quality_combo.addItem(self._display_quality_options[-1][0])
            didx = len(self._display_quality_options) - 1
        self.display_quality_combo.blockSignals(True)
        self.display_quality_combo.setCurrentIndex(didx)
        self.display_quality_combo.blockSignals(False)
        current_th = float(ui_cfg.get("overlay_size_scale", 1.0))
        try:
            tidx = next(i for i, (_, v) in enumerate(self._thickness_options) if abs(v - current_th) < 1e-3)
        except StopIteration:
            tidx = 2
        self.thickness_combo.blockSignals(True)
        self.thickness_combo.setCurrentIndex(tidx)
        self.thickness_combo.blockSignals(False)
        current_n = int(self.cfg.get("detector", {}).get("every_n_frames", 1))
        try:
            sidx = next(i for i, (_, n) in enumerate(self._skip_options) if n == current_n)
        except StopIteration:
            sidx = 0
        self.skip_combo.blockSignals(True)
        self.skip_combo.setCurrentIndex(sidx)
        self.skip_combo.blockSignals(False)
        self.skip_combo.setEnabled(not bool(ui_cfg.get("independent_schedule", False)))
        current_w_yolo = str(self.cfg.get("detector", {}).get("weights", "models/yolo11n.pt"))
        try:
            yidx = next(i for i, (_, p) in enumerate(self._yolo_options) if p == current_w_yolo)
        except StopIteration:
            yidx = 0
            self.cfg.setdefault("detector", {})["weights"] = self._yolo_options[yidx][1]
        self.yolo_combo.blockSignals(True)
        self.yolo_combo.setCurrentIndex(yidx)
        self.yolo_combo.blockSignals(False)
        # ROI モード + 矩形パラメータ
        current_mode = str(ui_cfg.get("roi_mode", "off"))
        if current_mode == "off" and bool(ui_cfg.get("enable_roi_crop", False)):
            current_mode = "trapezoid"
        try:
            ridx = next(i for i, (_, m) in enumerate(self._roi_mode_options) if m == current_mode)
        except StopIteration:
            ridx = 0
        self.roi_mode_combo.blockSignals(True)
        self.roi_mode_combo.setCurrentIndex(ridx)
        self.roi_mode_combo.blockSignals(False)
        rect_cfg = ui_cfg.get("roi_rect", {}) or {}
        for slider, key, default in (
            (self.roi_rect_x_slider, "x_ratio", 0.05),
            (self.roi_rect_y_slider, "y_ratio", 0.30),
            (self.roi_rect_w_slider, "w_ratio", 0.90),
            (self.roi_rect_h_slider, "h_ratio", 0.65),
        ):
            slider.blockSignals(True)
            slider.setValue(int(float(rect_cfg.get(key, default)) * 100))
            slider.blockSignals(False)
        self._set_roi_rect_sliders_enabled(current_mode == "rectangle")

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "動画選択", "", "動画 (*.mp4 *.mov *.avi *.mkv)")
        if path:
            self._last_source_factory = lambda p=path: VideoFileSource(p)
            self._start_source()

    def _open_camera(self) -> None:
        devices = CameraSource.list_devices()
        if not devices:
            self.video_label.setText("カメラが見つかりません")
            return
        labels = [f"Camera {idx}" for idx in devices]
        selected, ok = QInputDialog.getItem(self, "カメラ選択", "デバイス:", labels, 0, False)
        if ok and selected:
            idx = devices[labels.index(selected)]
            sizes = CameraSource.supported_sizes(idx)
            if sizes:
                self._camera_sizes = sizes
                self._quality_options = [(f"{w}×{h}", w) for w, h in sizes]
                self.quality_combo.blockSignals(True)
                self.quality_combo.clear()
                self.quality_combo.addItems([label for label, _ in self._quality_options])
                width = int(self.cfg.get("ui", {}).get("max_process_width", 0) or 0)
                choice = min(range(len(sizes)), key=lambda i: (abs(sizes[i][0]-width), sizes[i][0]))
                self.quality_combo.setCurrentIndex(choice)
                self.cfg.setdefault("ui", {})["max_process_width"] = sizes[choice][0]
                self.quality_combo.blockSignals(False)
            self._last_source_factory = lambda i=idx: CameraSource(i)
            self._start_source()

    def _start_source(self) -> None:
        """factory から新しいソースを作り、新しい thread を起動する。"""
        if self._last_source_factory is None:
            return
        self._stop()
        if self.thread is not None:
            return
        source = self._last_source_factory()
        if isinstance(source, VideoFileSource) and self.cfg.get("input", {}).get("video_mode") == "realtime" and self.cfg.get("ui", {}).get("async_preview", False):
            source = RealtimeVideoSource(source.path)
        if isinstance(source, CameraSource):
            input_cfg = self.cfg.get("input", {})
            width = max(0, int(self.cfg.get("ui", {}).get("max_process_width", 0) or 0))
            source.requested_width = width
            selected = self.quality_combo.currentIndex()
            source.requested_height = (self._camera_sizes[selected][1] if self._camera_sizes and 0 <= selected < len(self._camera_sizes) and self._camera_sizes[selected][0] == width else
                                       ({320: 240, 360: 270, 540: 304, 720: 405, 960: 540, 1280: 720}.get(width, round(width * 9 / 16)) if width else 0))
            source.requested_fps = max(0, float(input_cfg.get("camera_fps", 0) or 0))
            # Keep multiple driver buffers available; CameraSource continuously
            # drains them and publishes only its latest frame to the UI.
            source.requested_buffers = max(1, int(input_cfg.get("camera_buffers", 4) or 4))
        async_preview = isinstance(source, (CameraSource, RealtimeVideoSource)) and self.cfg.get("ui", {}).get("async_preview", False)
        self.thread = AsyncCameraThread(source, self.cfg) if async_preview else InferenceThread(source, self.cfg)
        self.accel_label.setText("AI推論: 準備中")
        self.thread.frame_ready.connect(self._on_frame)
        self.thread.error.connect(self._on_error)
        self.thread.finished_signal.connect(self._on_finished)
        self.thread.start()
        self.btn_play.setText("一時停止")

    def _on_frame(self, frame: np.ndarray, meta: dict) -> None:
        ui_started = time.monotonic()
        if self.sender() is not None and self.sender() is not self.thread:
            return
        if self.thread is not None and "_generation" in meta and meta["_generation"] != getattr(self.thread, "_generation", meta["_generation"]):
            self.thread.acknowledge_frame()
            return
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(image).scaled(self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.video_label.setPixmap(pixmap)
        self.fps_label.setText(f"FPS: {meta.get('fps', 0):.1f}")
        if meta.get("capture_fps") is not None:
            label = "処理" if meta.get("camera_rate_kind") == "processing" else "表示"
            self.fps_label.setText(f"{label} {meta.get('fps', 0):.1f} / 入力 {meta['capture_fps']:.1f} FPS")
        def size_text(key: str) -> str:
            size = meta.get(key)
            return f"{size[0]}×{size[1]}" if size else "不明"
        self.resolution_label.setText(
            f"入力: {size_text('input_size')} / 処理: {size_text('process_size')}\n"
            f"描画: {size_text('display_size')}"
        )
        requested = meta.get("camera_requested_size")
        if requested and all(requested) and tuple(requested) != tuple(meta.get("input_size", ())):
            self.resolution_label.setText(self.resolution_label.text() + f"\n要求: {requested[0]}×{requested[1]} (未対応)")
        if meta.get("device") == "Hailo-8":
            hw_ms = meta.get("hailo_hw_ms")
            if not meta.get("detector_enabled", True):
                self.accel_label.setText("AI HAT+: 検出OFF")
            elif hw_ms is not None:
                self.accel_label.setText(f"AI HAT+: {meta.get('detector_model', '')}\n直近の推論時間: {hw_ms:.1f} ms")
            else:
                self.accel_label.setText("AI HAT+: 推論待ち")
        else:
            self.accel_label.setText(f"AI推論: {meta.get('device', '未実行')}")
        if "hailo_scene" in self.cfg and "ai_depth_status" in meta:
            self.accel_label.setText(
                self.accel_label.text()
                + f"\nAI奥行き: {meta.get('ai_depth_status', 'OFF')}"
            )
            if meta.get("ai_front_target") is not None:
                self.accel_label.setText(self.accel_label.text() + f"\nAI推定の前方対象: #{meta['ai_front_target']}")
            errors = [str(meta[k]) for k in ("ai_depth_error",) if meta.get(k)]
            self.accel_label.setToolTip("\n".join(errors))
            if meta.get("risk_mode") == "ai_depth_fusion":
                self.accel_label.setText(self.accel_label.text() + "\n判定方式: AI奥行き融合")
                regions = meta.get("ai_depth_regions", [])
                if regions:
                    states = []
                    for direction in ("左前", "正面", "右前"):
                        levels = [r.get('level', 0) for r in regions if r.get('direction') == direction]
                        state = ('候補', '可能性', '注意', '強い注意')[max(levels)] if levels else '情報なし'
                        states.append(f"{direction}:{state}")
                    self.accel_label.setText(self.accel_label.text() + "\n" + " / ".join(states))
        elif self.cfg.get("ui", {}).get("async_preview", False):
            scene = self.cfg.get("hailo_scene", {})
            if not scene.get("depth_enabled", scene.get("enabled", False)):
                self.accel_label.setText(self.accel_label.text() + "\nAI奥行き: OFF")
        if meta.get("result_age_ms") is not None:
            self.accel_label.setText(self.accel_label.text() + f"\n結果の経過: {meta['result_age_ms']:.0f} ms")
        if "detector_hz_actual" in meta:
            self.accel_label.setText(self.accel_label.text() + f"\nYOLO {meta['detector_hz_actual']:.1f}回/秒 / 車線 {meta['lane_hz_actual']:.1f}回/秒")
        lane_state = str(meta.get("lane_state", "off"))
        lane_text = "検出" if meta.get("lane_detected", False) else "なし"
        self.frame_label.setText(f"フレーム: {meta.get('frame_idx', 0)} | 車線: {lane_text} ({lane_state})")
        if meta.get("input_kind") == "camera":
            rate_kind = meta.get("camera_rate_kind", "display")
            rate_label = "処理" if rate_kind == "processing" else "表示"
            follow = camera_follow_ratio(float(meta.get("fps", 0.0)), meta.get("capture_fps"))
            self.lag_label.setText(f"{rate_label}追従率: {follow * 100:.0f}%" if follow is not None else f"{rate_label}追従率: 計測中")
            color = "#3c3" if follow is not None and follow >= 0.95 else "#cc3" if follow is not None and follow >= 0.8 else "#e83"
            self.lag_label.setStyleSheet(f"color: {color}; font-weight: bold;")
            self.lag_label.setToolTip("実測したカメラ入力FPSに対する表示または処理FPSの比。AIの更新頻度や遅延を示す値ではありません。表示の間引き設定でも下がります。")
            self.lag_avg_label.setText(f"カメラ設定: {float(meta.get('source_fps', 0)):.1f} FPS")
            self.lag_avg_label.setStyleSheet("")
            self.lag_avg_label.setToolTip("カメラに要求または報告されたFPS。実際の入力FPSは明るさなどで変わる場合があります。")
        else:
            lag_pct = float(meta.get("lag_percent", 0.0))
            ratio = float(meta.get("realtime_ratio", 1.0))
            speed_pct = ratio * 100.0
            if lag_pct < 5:
                color, status = "#3c3", "リアルタイム"
            elif lag_pct < 20:
                color, status = "#cc3", "やや遅延"
            elif lag_pct < 50:
                color, status = "#e83", "遅延"
            else:
                color, status = "#e33", "重い遅延"
            self.lag_label.setText(f"実時間比 {speed_pct:.0f}% (-{lag_pct:.0f}% {status})")
            self.lag_label.setStyleSheet(f"color: {color}; font-weight: bold;")
            self.lag_label.setToolTip("動画本来の再生速度に対する処理速度。")
            avg_value = meta.get("avg_realtime_ratio")
            avg_ratio = float(avg_value) if avg_value is not None else 0.0
            avg_lag_pct = float(meta.get("avg_lag_percent") or 0.0)
            avg_speed_pct = avg_ratio * 100.0
            if avg_lag_pct < 5:
                avg_color = "#3c3"
            elif avg_lag_pct < 20:
                avg_color = "#cc3"
            elif avg_lag_pct < 50:
                avg_color = "#e83"
            else:
                avg_color = "#e33"
            self.lag_avg_label.setText(f"平均 {avg_speed_pct:.0f}% (-{avg_lag_pct:.0f}%)" if avg_value is not None else "平均: 計測中")
            self.lag_avg_label.setStyleSheet(f"color: {avg_color};")
            self.lag_avg_label.setToolTip("実際に解析したフレーム数から算出した平均処理速度比。一時停止中の時間を除き、飛ばしたフレームは数えません。")
        frame_count = meta.get("frame_count")
        if frame_count:
            self.seek_slider.setEnabled(True)
            self.seek_slider.blockSignals(True)
            self.seek_slider.setRange(0, int(frame_count) - 1)
            self.seek_slider.setValue(int(meta.get("frame_idx", 0)))
            self.seek_slider.blockSignals(False)
        self._update_alerts(meta.get("alerts", []))
        if self._perf_log_path and ui_started >= self._perf_log_next:
            self._perf_log_next = ui_started + 1.0
            sample = {key: meta.get(key) for key in (
                "fps", "capture_fps", "source_fps", "detector_hz_actual", "lane_hz_actual",
                "result_age_ms", "result_stale", "capture_dropped_frames", "analysis_replaced_frames",
                "input_kind", "camera_rate_kind", "preview_render_ms", "capture_to_emit_ms",
                "device", "detector_model", "input_size", "process_size", "display_size")}
            sample.update({"time": time.time(), "ui_callback_ms": (time.monotonic() - ui_started) * 1000,
                           "preview_brightness": float(frame[::8, ::8].mean()),
                           "profile": str(self.config_path)})
            try:
                with open(self._perf_log_path, "a", encoding="utf-8") as log:
                    log.write(json.dumps(sample, ensure_ascii=False) + "\n")
            except OSError:
                self._perf_log_path = None
        if self.thread is not None and hasattr(self.thread, "acknowledge_frame"):
            self.thread.acknowledge_frame()

    def _update_alerts(self, alerts) -> None:
        signature = tuple((a.level, a.kind, a.target_id, a.direction, a.message) for a in alerts)
        if signature == getattr(self, '_last_alert_table', None):
            return
        self._last_alert_table = signature
        self.alert_table.setRowCount(len(alerts))
        for row, alert in enumerate(alerts):
            values = [alert.level, alert.kind, alert.target_id if alert.target_id is not None else "-", alert.direction or "-", display_alert_message(alert.message)]
            for col, value in enumerate(values):
                self.alert_table.setItem(row, col, QTableWidgetItem(str(value)))
        self.alert_table.resizeColumnsToContents()

    def _on_error(self, message: str) -> None:
        if self.sender() is not None and self.sender() is not self.thread:
            return
        self.video_label.setText(message)
        self.accel_label.setText("AI推論: エラー")

    def _on_finished(self) -> None:
        if self.sender() is not None and self.sender() is not self.thread:
            return
        self.btn_play.setText("再生/一時停止")

    def _play_pause(self) -> None:
        # thread が無い場合 → 最後のソースで再起動
        if self.thread is None:
            if self._last_source_factory is not None:
                self._start_source()
            return
        if self.thread.paused:
            self.thread.resume()
            self.btn_play.setText("一時停止")
        else:
            self.thread.pause()
            self.btn_play.setText("再生")

    def _seek(self) -> None:
        if self.thread is not None:
            self.thread.seek(self.seek_slider.value())

    def _stop(self) -> None:
        if self.thread is not None:
            try:
                self.thread.stop()
                # 3 秒待っても終わらない場合は強制終了（カメラ read() ブロック等の対策）
                if not self.thread.wait(3000):
                    if isinstance(self.thread, AsyncCameraThread):
                        self.video_label.setText("解析の停止を待っています。しばらくしてから再試行してください。")
                        return
                    self.thread.requestInterruption()
                    self.thread.terminate()
                    self.thread.wait(1000)
            except Exception:
                pass
            self.thread = None
        self.btn_play.setText("再生/一時停止")

    def _make_roi_slider(self, text: str, key: str, value: int) -> tuple[QLabel, QSlider]:
        label = QLabel(f"{text}: {value}%")
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(value)
        slider.setProperty("roi_key", key)
        slider.setProperty("label_text", text)
        slider.valueChanged.connect(self._sync_feature_flags)
        slider.valueChanged.connect(lambda v, lbl=label, t=text: lbl.setText(f"{t}: {v}%"))
        return label, slider

    def _set_roi_rect_sliders_enabled(self, enabled: bool) -> None:
        for w in (self.roi_rect_x_slider, self.roi_rect_y_slider,
                  self.roi_rect_w_slider, self.roi_rect_h_slider):
            w.setEnabled(enabled)
        for w in (self.roi_rect_x_label, self.roi_rect_y_label,
                  self.roi_rect_w_label, self.roi_rect_h_label):
            w.setStyleSheet("" if enabled else "color: #777;")

    def _build_profile_list(self) -> list[tuple[str, str]]:
        return [
            ("Pi 高速 (AI HAT+)", "config/pi_async_ai_hat.yaml"),
            ("Pi 高速2 (AI HAT+)", "config/pi_async_ai_hat_2.yaml"),
        ]

    def _save_selected_profile(self) -> None:
        index = self.profile_combo.currentIndex()
        if not 0 <= index < len(self._profiles):
            return
        label, profile_path = self._profiles[index]
        path = Path(profile_path)
        try:
            save_custom_profile(self.cfg, path)
        except OSError as exc:
            self.video_label.setText(f"プロファイルを保存できませんでした: {exc}")
            return
        self.config_path = path
        self.video_label.setText(f"{label}プロファイルに保存しました: {path}")

    def _open_settings_dialog(self) -> None:
        # default = 現在ロードされているプロファイルのファイル値（リセット先）
        from src.utils.config import load_config
        default_cfg = load_config(self.config_path)
        if self._settings_dialog is None:
            dialog = SettingsDialog(self.cfg, self, default_cfg=default_cfg)
            dialog.settingsChanged.connect(self._on_dialog_settings_changed)
            self._settings_dialog = dialog
        else:
            self._settings_dialog.cfg = self.cfg
            self._settings_dialog.set_default_snapshot(default_cfg)
            self._settings_dialog.refresh_from_cfg()
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def _on_dialog_settings_changed(self, cfg: dict) -> None:
        """ダイアログで値が変わったら Pipeline へ即時反映し、左パネル UI とも同期する。"""
        self.cfg = cfg
        # 左パネル側の値（処理解像度コンボ、解析間隔コンボ、YOLO コンボ、各チェック）を再同期
        self._apply_feature_flags()
        if self.thread is not None and hasattr(self.thread, "apply_settings"):
            self.thread.apply_settings(self.cfg)

    def _on_profile_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._profiles):
            return
        _, path = self._profiles[index]
        target = Path(path)
        restart_camera = (self.thread is not None and self.thread.isRunning()
                          and isinstance(self.thread.source, CameraSource))
        was_paused = restart_camera and self.thread.paused
        self.config_path = target
        self.cfg = load_config(path)
        self._apply_feature_flags()
        if self._settings_dialog is not None:
            self._settings_dialog.cfg = self.cfg
            self._settings_dialog.set_default_snapshot(self.cfg)
            self._settings_dialog.refresh_from_cfg()
        # 再生中なら停止（次の動画/カメラ起動で新 cfg が反映される）
        if self.thread is not None:
            self._stop()
        if restart_camera:
            self._start_source()
            if was_paused and self.thread is not None:
                self.thread.pause()
                self.btn_play.setText("再生")

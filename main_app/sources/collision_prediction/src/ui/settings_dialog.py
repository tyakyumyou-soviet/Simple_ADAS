from __future__ import annotations

from typing import Any

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


# 各設定項目の説明（ツールチップに表示）
# キー: (section, key) — nested は (section, parent_key, sub_key)
TOOLTIPS: dict[tuple, str] = {
    # ---- Detector ----
    ("detector", "device"): (
        "推論デバイス。\n"
        "・auto: MPS (Apple Silicon) → CPU の順に自動選択（推奨）\n"
        "・mps: Apple GPU 強制（M1/M2 等で 3-5 倍高速、x86 Mac は失敗）\n"
        "・cpu: CPU 強制（ラズパイは事実上これ）"
    ),
    ("detector", "conf"): (
        "YOLO 推論時の最低信頼度。\n"
        "↑ 上げる: 誤検出減るが、薄い対象（遠方・暗所）を見落とす\n"
        "↓ 下げる: 検出感度↑だが FP（誤検出）増。0.15-0.25 が実用域"
    ),
    ("detector", "iou"): (
        "NMS の重なり閾値 (Non-Max Suppression)。\n"
        "↑ 上げる: 重なった BB が残る（密集シーンで欠落減）\n"
        "↓ 下げる: 重なった BB を厳しく統合（重複表示減）\n"
        "通常 0.45-0.55。多重 BB が出る時は下げる"
    ),
    ("detector", "imgsz"): (
        "YOLO 内部リサイズ後の入力辺長 (px)。\n"
        "↑ 大きく: 遠方の小物体が見える、推論遅い\n"
        "↓ 小さく: 速い (Pi は 320 推奨)、小物体は落ちる\n"
        "32 の倍数推奨"
    ),
    ("detector", "max_det"): (
        "1 フレームあたり保持する検出上限。\n"
        "↑ 上げる: 渋滞・群衆を取りこぼさない、後段処理重い\n"
        "↓ 下げる: 高速化、混雑時に重要対象を落とす可能性"
    ),
    ("detector", "every_n_frames"): (
        "YOLO を何フレに 1 回走らせるか。\n"
        "↑ 上げる: 大幅高速化（5 なら検出負荷 1/5）、間は LK で BB を補間\n"
        "↓ 1 が最高精度。5+ では LK 補間誤差で BB がズレ始める"
    ),
    ("detector", "conf_per_class", "person"): "人物検出の最終 conf。低めだと遠方歩行者を拾う・誤検出も増",
    ("detector", "conf_per_class", "bicycle"): "自転車検出の最終 conf。横断時危険度高いので低めに設定",
    ("detector", "conf_per_class", "motorcycle"): "バイク検出の最終 conf",
    ("detector", "conf_per_class", "car"): "乗用車検出の最終 conf。高めで誤検出（赤い柱等）を抑制",
    ("detector", "conf_per_class", "bus"): "バス検出の最終 conf",
    ("detector", "conf_per_class", "truck"): "トラック検出の最終 conf",
    # ---- Tracker ----
    ("tracker", "track_buffer"): (
        "物体ロスト後に ID を保持するフレーム数。\n"
        "↑ 上げる: 一瞬の遮蔽に強い、誤って別物体に ID 付け替わるリスク\n"
        "↓ 下げる: ID 切り替わりが早い、瞬間遮蔽で ID 切れる\n"
        "※変更は次回起動時反映"
    ),
    # ---- Segmenter ----
    ("segmenter", "enabled"): (
        "路面/歩道セグメンテーション (SegFormer) を実行するか。\n"
        "ON: 歩道上の人を除外、白線なし道で車線フォールバック\n"
        "OFF: 大幅高速化（-15ms 程度）、歩道判定が無くなる"
    ),
    ("segmenter", "every_n_frames"): (
        "セグメンテーション推論の間隔。\n"
        "↑ 上げる: 軽い、ただし古いマスクが使われる\n"
        "路面は急変しないので 15-30 で十分"
    ),
    ("segmenter", "input_size"): (
        "SegFormer 入力辺長。↓ 256 で速い・粗い / ↑ 512 で詳細だが重い\n"
        "※変更は次回起動時反映"
    ),
    # ---- Depth ----
    ("depth", "enabled"): (
        "単眼深度モデル (Depth Anything V2) を実行するか。\n"
        "ON: 物体までの実距離推定精度↑、ただし重い (+30-80ms)\n"
        "OFF: 軽量な IPM (逆透視) フォールバックで概算距離を出す"
    ),
    ("depth", "every_n_frames"): "深度推論の間隔。距離は急変しないので 5-15 で十分",
    ("depth", "cam_height_m"): (
        "カメラ取り付け高さ (m)。IPM 計算で実距離換算に使う。\n"
        "正確に設定すると距離・TTC 精度↑（実測推奨）"
    ),
    # ---- Lane ----
    ("lane", "dashed_support"): (
        "点線車線を縦長カーネルで結合して扱うか。\n"
        "ON: 点線が連続線として認識される（高速道・幅員大の道で必須）\n"
        "OFF: 誤結合がない代わりに点線が分断"
    ),
    ("lane", "hough_threshold"): (
        "Hough 線分検出の最低投票数。\n"
        "↑ 上げる: 強い直線しか拾わない（ノイズ耐性↑）、薄い車線見落とす\n"
        "↓ 下げる: 弱い線も拾う（FP 増、街路樹影等を誤検出）"
    ),
    ("lane", "min_line_length"): (
        "車線として扱う最小線分長 (px)。\n"
        "↑ 上げる: 短いノイズ無視（点線は分断されがち）\n"
        "↓ 下げる: 点線片も拾うがゴミも増える"
    ),
    ("lane", "max_line_gap"): (
        "1 本の線とみなす許容ギャップ (px)。\n"
        "↑ 上げる: 点線同士を連結しやすい\n"
        "↓ 下げる: 別線として扱う（隣車線と混同するリスク↓）"
    ),
    ("lane", "ldw_threshold_px"): "LDW 旧パラメータ。現在は偏差率で判定するため未使用に近い",
    ("lane", "ldw_release_px"): "LDW 旧パラメータ。現在は偏差率で判定するため未使用に近い",
    ("lane", "every_n_frames"): (
        "車線検出の間隔。\n"
        "↑ 上げる: 軽量化、急カーブで反応遅れ\n"
        "通常 1-3 が実用域"
    ),
    # ---- Risk ----
    ("risk", "ttc_critical_s"): (
        "Time-To-Collision がこの秒数以下で critical 警告。\n"
        "↑ 上げる: 早めに警告（過剰反応のリスク↑）\n"
        "↓ 下げる: 直前まで警告しない（見落としリスク↑）\n"
        "通常 1.0-2.0 秒"
    ),
    ("risk", "ttc_warn_s"): (
        "TTC がこの秒数以下で warn (黄色) 警告。\n"
        "critical < warn の関係を保つ。3.0 秒前後が標準"
    ),
    ("risk", "follow_distance_factor"): (
        "適正車間距離係数。自車速度に応じた目安距離との比。\n"
        "↑ 上げる: 車間広めを要求 → 警告出やすい\n"
        "↓ 下げる: 詰めても警告しにくい"
    ),
    # ---- UI ----
    ("ui", "max_process_width"): (
        "パイプライン全体の入力幅 (px)。縦横比を保ってリサイズ。\n"
        "カメラは指定幅に拡大・縮小。動画では指定幅を上限とする。\n"
        "↑ 上げる: 精度↑、重い\n"
        "↓ 下げる: 大幅高速化、Pi なら 320-540 推奨\n"
        "0 = 自動 (元のまま)"
    ),
    ("ui", "display_max_width"): (
        "表示キャンバスの幅 (px)。動画ピクセルは処理解像度のまま引き伸ばすが、\n"
        "BB/矢印/文字はこの解像度で描画される (overlay の精細さ)。\n"
        "↑ 上げる: overlay 綺麗、描画コスト微増\n"
        "↓ 下げる: 全体が小さく / overlay 太く\n"
        "0 = 元動画サイズに合わせる"
    ),
    ("ui", "overlay_size_scale"): (
        "Overlay (BB / 矢印 / 文字) の大きさ倍率。\n"
        "0.5 = 極小 / 1.0 = 標準 / 1.5 = 大きい / 2.0 = 極大\n"
        "高解像度動画で目立たない時は上げる、邪魔な時は下げる"
    ),
    ("ui", "display_every_n_frames"): (
        "UI 表示を何フレに 1 回更新するか。\n"
        "↑ 上げる: 描画コスト↓、映像はカクつく\n"
        "通常 1 (毎フレーム描画)"
    ),
    ("ui", "signs_every_n_frames"): (
        "信号/標識検出の間隔。\n"
        "信号は遠方で見つけて追跡できれば良いので 2-10 で十分"
    ),
    ("ui", "enable_ego_motion"): (
        "自車の動き（速度・旋回・消失点）を裏方で推定。\n"
        "ON: 停車中の対向車を「動いている」と誤判定しなくなる\n"
        "OFF: 軽いが相対速度誤判定が増える（推奨 ON）"
    ),
    ("ui", "enable_distance"): (
        "物体までの距離計算を実行するか。\n"
        "ON: BB ラベルに距離 (m) 表示、TTC 計算でも使用、車間距離警告が動作\n"
        "OFF: depth.predict と距離推定をスキップ → 大幅高速化 (depth ON 時 -30〜80ms)\n"
        "     距離表示・車間距離警告は消え、TTC は looming (BB 拡大率) のみで判定"
    ),
    ("ui", "enable_blind_check"): (
        "カメラ異常検知 (検出不能状態の通知)。\n"
        "ON: 「直近 N 秒検出ゼロ」 AND 「画質劣化 (真っ暗 / 真っ白 / 単色 / 完全ボケ)」\n"
        "    の AND 条件で画面上部に赤帯警告。レンズ汚れ・霧・遮蔽・夜間故障等を一括カバー\n"
        "OFF: 通知しない\n"
        "AND 条件のため、何もない道で誤通知しない (画質正常なら通知出ない)"
    ),
    ("ui", "blind_check_seconds"): (
        "カメラ異常検知の時間条件 (秒)。\n"
        "↑ 大きい: チラつき減るが、異常検知が遅れる\n"
        "↓ 小さい: 反応速いが、信号待ち等で誤通知しやすい\n"
        "通常 1.5-5.0 秒、デフォルト 2.0 (感度寄り)"
    ),
}

# グループの概要説明
GROUP_DESCRIPTIONS = {
    "Detector": "YOLO の検出パラメータ。速度 vs 精度の最大トレードオフ箇所。",
    "Tracker": "ByteTrack の追跡パラメータ。ID 維持の挙動を決める。",
    "Segmenter": "路面/歩道セグメンテーション。歩道上の歩行者除外と車線フォールバックに使用。",
    "Depth": "単眼深度推定。距離計算の精度を決めるが負荷大。",
    "Lane": "古典手法の車線検出パラメータ。光線条件で要調整。",
    "Risk": "衝突予測の閾値。早めに警告するか、確実な時だけかのバランス。",
    "UI": "表示・全体パイプラインの間引き設定。",
}


class SettingsDialog(QDialog):
    """プロファイル YAML で指定できる全項目を編集する詳細設定ダイアログ。"""

    settingsChanged = Signal(dict)

    def __init__(self, cfg: dict[str, Any], parent: QWidget | None = None, default_cfg: dict[str, Any] | None = None):
        super().__init__(parent)
        self.cfg = cfg
        # プロファイル直後のスナップショット = リセット先
        self._default_cfg: dict[str, Any] = copy.deepcopy(default_cfg if default_cfg is not None else cfg)
        self.setWindowTitle("詳細設定 (各項目を hover で説明表示)")
        self.resize(640, 760)
        self.setMinimumSize(420, 360)
        self.setSizeGripEnabled(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._building = True
        self._widgets: dict[tuple, QWidget] = {}

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        inner = QWidget()
        inner.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QVBoxLayout(inner)
        layout.setSpacing(8)

        header = QLabel(
            "各項目にカーソルを乗せると <b>メリット / デメリット</b> の詳しい説明が出ます。"
            " 変更は即座にパイプラインへ反映されます。"
        )
        header.setWordWrap(True)
        header.setStyleSheet("color: #cdd; background: #243; padding: 8px; border-radius: 4px;")
        layout.addWidget(header)

        layout.addWidget(self._build_detector_group())
        layout.addWidget(self._build_tracker_group())
        layout.addWidget(self._build_segmenter_group())
        layout.addWidget(self._build_depth_group())
        layout.addWidget(self._build_lane_group())
        layout.addWidget(self._build_risk_group())
        layout.addWidget(self._build_ui_group())
        layout.addWidget(self._build_camera_group())
        layout.addStretch(1)
        scroll.setWidget(inner)

        reset_btn = QPushButton("デフォルトに戻す")
        reset_btn.setToolTip("ダイアログを開いた時点のプロファイル値に全項目を戻す")
        reset_btn.clicked.connect(self._reset_to_defaults)
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addWidget(reset_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(scroll, 1)
        root.addLayout(btn_row)

        self._building = False

    # --------- helpers ---------

    def _add_row(self, form: QFormLayout, label_text: str, widget: QWidget, tooltip: str | None) -> None:
        label = QLabel(label_text)
        label.setWordWrap(False)
        if tooltip:
            label.setToolTip(tooltip)
            widget.setToolTip(tooltip)
            label.setCursor(Qt.WhatsThisCursor)
        form.addRow(label, widget)

    def _tip(self, section: str, key: str) -> str:
        return TOOLTIPS.get((section, key), "")

    def _tip_nested(self, section: str, parent_key: str, sub_key: str) -> str:
        return TOOLTIPS.get((section, parent_key, sub_key), "")

    def _spin(self, section: str, key: str, *, vmin: int, vmax: int, step: int = 1, default: int = 0) -> QSpinBox:
        w = QSpinBox()
        w.setRange(vmin, vmax)
        w.setSingleStep(step)
        w.setValue(int(self.cfg.get(section, {}).get(key, default)))
        w.valueChanged.connect(lambda v, s=section, k=key: self._set(s, k, int(v)))
        self._widgets[(section, key)] = w
        return w

    def _dspin(self, section: str, key: str, *, vmin: float, vmax: float, step: float = 0.05, decimals: int = 2, default: float = 0.0) -> QDoubleSpinBox:
        w = QDoubleSpinBox()
        w.setRange(vmin, vmax)
        w.setSingleStep(step)
        w.setDecimals(decimals)
        w.setValue(float(self.cfg.get(section, {}).get(key, default)))
        w.valueChanged.connect(lambda v, s=section, k=key: self._set(s, k, float(v)))
        self._widgets[(section, key)] = w
        return w

    def _check(self, section: str, key: str, *, default: bool = False) -> QCheckBox:
        w = QCheckBox()
        w.setChecked(bool(self.cfg.get(section, {}).get(key, default)))
        w.stateChanged.connect(lambda _s, s=section, k=key, cb=w: self._set(s, k, cb.isChecked()))
        self._widgets[(section, key)] = w
        return w

    def _combo(self, section: str, key: str, options: list[tuple[str, Any]], *, default: Any = None) -> QComboBox:
        w = QComboBox()
        values = []
        for label, value in options:
            w.addItem(label)
            values.append(value)
        current = self.cfg.get(section, {}).get(key, default)
        try:
            w.setCurrentIndex(values.index(current))
        except ValueError:
            w.setCurrentIndex(0)
        w.currentIndexChanged.connect(lambda i, s=section, k=key, vals=values: self._set(s, k, vals[i]))
        w.setProperty("_values", values)
        self._widgets[(section, key)] = w
        return w

    def _nested_dspin(self, section: str, parent_key: str, sub_key: str, *, vmin: float, vmax: float, step: float = 0.01, decimals: int = 2, default: float = 0.0) -> QDoubleSpinBox:
        w = QDoubleSpinBox()
        w.setRange(vmin, vmax)
        w.setSingleStep(step)
        w.setDecimals(decimals)
        parent = self.cfg.get(section, {}).get(parent_key, {}) or {}
        w.setValue(float(parent.get(sub_key, default)))
        w.valueChanged.connect(lambda v, s=section, p=parent_key, k=sub_key: self._set_nested(s, p, k, float(v)))
        self._widgets[(section, parent_key, sub_key)] = w
        return w

    def _set(self, section: str, key: str, value: Any) -> None:
        if self._building:
            return
        self.cfg.setdefault(section, {})[key] = value
        self.settingsChanged.emit(self.cfg)

    def _set_nested(self, section: str, parent_key: str, sub_key: str, value: Any) -> None:
        if self._building:
            return
        parent = self.cfg.setdefault(section, {}).setdefault(parent_key, {})
        parent[sub_key] = value
        self.settingsChanged.emit(self.cfg)

    def _make_group(self, title: str, key: str) -> tuple[QGroupBox, QFormLayout]:
        g = QGroupBox(title)
        layout = QVBoxLayout(g)
        desc = QLabel(GROUP_DESCRIPTIONS.get(key, ""))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #999; font-size: 11px;")
        layout.addWidget(desc)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignTop)
        form.setVerticalSpacing(6)
        layout.addLayout(form)
        return g, form

    # --------- groups ---------

    def _build_detector_group(self) -> QGroupBox:
        g, f = self._make_group("検出 (Detector / YOLO)", "Detector")
        self._add_row(f, "Device", self._combo("detector", "device", [
            ("auto (推奨)", "auto"), ("mps (Apple Silicon)", "mps"), ("cpu", "cpu"),
        ], default="auto"), self._tip("detector", "device"))
        self._add_row(f, "YOLO conf", self._dspin("detector", "conf", vmin=0.01, vmax=1.0, step=0.01, decimals=2, default=0.18), self._tip("detector", "conf"))
        self._add_row(f, "IoU (NMS)", self._dspin("detector", "iou", vmin=0.1, vmax=0.95, step=0.05, decimals=2, default=0.5), self._tip("detector", "iou"))
        self._add_row(f, "YOLO imgsz", self._spin("detector", "imgsz", vmin=160, vmax=1280, step=32, default=480), self._tip("detector", "imgsz"))
        self._add_row(f, "Max detections", self._spin("detector", "max_det", vmin=10, vmax=500, step=10, default=120), self._tip("detector", "max_det"))
        self._add_row(f, "検出フレーム間隔", self._spin("detector", "every_n_frames", vmin=1, vmax=10, default=1), self._tip("detector", "every_n_frames"))
        self._add_row(f, "検出位相", self._spin("detector", "phase", vmin=0, vmax=10, default=1), "同じ周期の車線検出と重ならない開始フレーム")
        for cls, default in (("person", 0.18), ("bicycle", 0.15), ("motorcycle", 0.25), ("car", 0.32), ("bus", 0.32), ("truck", 0.32)):
            self._add_row(f, f"  conf [{cls}]", self._nested_dspin("detector", "conf_per_class", cls, vmin=0.01, vmax=1.0, step=0.01, decimals=2, default=default), self._tip_nested("detector", "conf_per_class", cls))
        return g

    def _build_tracker_group(self) -> QGroupBox:
        g, f = self._make_group("追跡 (Tracker / ByteTrack)", "Tracker")
        self._add_row(f, "Track buffer", self._spin("tracker", "track_buffer", vmin=5, vmax=120, default=30), self._tip("tracker", "track_buffer"))
        return g

    def _build_segmenter_group(self) -> QGroupBox:
        g, f = self._make_group("路面セグメンテーション (SegFormer)", "Segmenter")
        self._add_row(f, "有効化", self._check("segmenter", "enabled", default=False), self._tip("segmenter", "enabled"))
        self._add_row(f, "実行フレーム間隔", self._spin("segmenter", "every_n_frames", vmin=1, vmax=60, default=18), self._tip("segmenter", "every_n_frames"))
        self._add_row(f, "入力サイズ", self._spin("segmenter", "input_size", vmin=128, vmax=1024, step=32, default=256), self._tip("segmenter", "input_size"))
        return g

    def _build_depth_group(self) -> QGroupBox:
        g, f = self._make_group("単眼深度 (Depth Anything)", "Depth")
        self._add_row(f, "有効化", self._check("depth", "enabled", default=False), self._tip("depth", "enabled"))
        self._add_row(f, "実行フレーム間隔", self._spin("depth", "every_n_frames", vmin=1, vmax=60, default=12), self._tip("depth", "every_n_frames"))
        self._add_row(f, "カメラ高さ (m)", self._dspin("depth", "cam_height_m", vmin=0.3, vmax=3.0, step=0.05, decimals=2, default=1.2), self._tip("depth", "cam_height_m"))
        return g

    def _build_lane_group(self) -> QGroupBox:
        g, f = self._make_group("車線検出 (古典手法)", "Lane")
        self._add_row(f, "点線サポート", self._check("lane", "dashed_support", default=True), self._tip("lane", "dashed_support"))
        self._add_row(f, "Hough 閾値", self._spin("lane", "hough_threshold", vmin=5, vmax=200, default=24), self._tip("lane", "hough_threshold"))
        self._add_row(f, "最小線分長 (px)", self._spin("lane", "min_line_length", vmin=5, vmax=300, default=18), self._tip("lane", "min_line_length"))
        self._add_row(f, "最大線分ギャップ (px)", self._spin("lane", "max_line_gap", vmin=10, vmax=500, default=180), self._tip("lane", "max_line_gap"))
        self._add_row(f, "LDW 閾値 (px, 旧)", self._spin("lane", "ldw_threshold_px", vmin=5, vmax=200, default=30), self._tip("lane", "ldw_threshold_px"))
        self._add_row(f, "LDW 解除 (px, 旧)", self._spin("lane", "ldw_release_px", vmin=5, vmax=200, default=50), self._tip("lane", "ldw_release_px"))
        self._add_row(f, "車線フレーム間隔", self._spin("lane", "every_n_frames", vmin=1, vmax=10, default=1), self._tip("lane", "every_n_frames"))
        self._add_row(f, "車線位相", self._spin("lane", "phase", vmin=0, vmax=10, default=0), "同じ周期のYOLOと重ならない開始フレーム")
        return g

    def _build_risk_group(self) -> QGroupBox:
        g, f = self._make_group("危険判定 (Risk)", "Risk")
        self._add_row(f, "TTC critical (秒)", self._dspin("risk", "ttc_critical_s", vmin=0.3, vmax=10.0, step=0.1, decimals=2, default=1.5), self._tip("risk", "ttc_critical_s"))
        self._add_row(f, "TTC warn (秒)", self._dspin("risk", "ttc_warn_s", vmin=0.5, vmax=15.0, step=0.1, decimals=2, default=3.0), self._tip("risk", "ttc_warn_s"))
        self._add_row(f, "車間距離係数", self._dspin("risk", "follow_distance_factor", vmin=0.1, vmax=3.0, step=0.05, decimals=2, default=0.7), self._tip("risk", "follow_distance_factor"))
        return g

    def _build_ui_group(self) -> QGroupBox:
        g, f = self._make_group("UI / 全般", "UI")
        self._add_row(f, "処理解像度上限 (0=自動)", self._spin("ui", "max_process_width", vmin=0, vmax=1920, step=20, default=960), self._tip("ui", "max_process_width"))
        self._add_row(f, "表示解像度 (0=元動画)", self._spin("ui", "display_max_width", vmin=0, vmax=3840, step=40, default=0), self._tip("ui", "display_max_width"))
        self._add_row(f, "Overlay 大きさ倍率", self._dspin("ui", "overlay_size_scale", vmin=0.2, vmax=3.0, step=0.1, decimals=2, default=1.0), self._tip("ui", "overlay_size_scale"))
        self._add_row(f, "表示フレーム間隔", self._spin("ui", "display_every_n_frames", vmin=1, vmax=10, default=1), self._tip("ui", "display_every_n_frames"))
        self._add_row(f, "信号検出フレーム間隔", self._spin("ui", "signs_every_n_frames", vmin=1, vmax=60, default=2), self._tip("ui", "signs_every_n_frames"))
        self._add_row(f, "エゴモーション (裏方)", self._check("ui", "enable_ego_motion", default=True), self._tip("ui", "enable_ego_motion"))
        self._add_row(f, "距離計算", self._check("ui", "enable_distance", default=True), self._tip("ui", "enable_distance"))
        self._add_row(f, "カメラ異常検知", self._check("ui", "enable_blind_check", default=False), self._tip("ui", "enable_blind_check"))
        self._add_row(f, "異常検知 時間条件 (秒)", self._dspin("ui", "blind_check_seconds", vmin=0.5, vmax=30.0, step=0.5, decimals=1, default=2.0), self._tip("ui", "blind_check_seconds"))
        return g

    def _build_camera_group(self) -> QGroupBox:
        g, f = self._make_group("カメラ取得 / 実時間処理", "Camera")
        self._add_row(f, "取得幅 (0=自動)", self._spin("input", "camera_width", vmin=0, vmax=3840, default=0), "変更後にカメラを停止して再選択。対応しないサイズは実取得値を表示します。")
        self._add_row(f, "取得高さ (0=自動)", self._spin("input", "camera_height", vmin=0, vmax=2160, default=0), "変更後にカメラを停止して再選択します。")
        self._add_row(f, "取得 FPS (0=自動)", self._spin("input", "camera_fps", vmin=0, vmax=120, default=0), "カメラ再選択時に要求します。実際の入力FPSは画面に表示します。")
        self._add_row(f, "動画の解析方法", self._combo("input", "video_mode", [("全フレーム", "all_frames"), ("実時間を優先", "realtime")], default="all_frames"), "入力を開き直すと反映。実時間優先は遅れた動画フレームを飛ばします。")
        self._add_row(f, "YOLO 更新回数/秒", self._dspin("detector", "update_hz", vmin=0.1, vmax=30, step=0.5, decimals=1, default=5.0), "Pi 高速プロファイルで有効。")
        self._add_row(f, "車線 更新回数/秒", self._dspin("lane", "update_hz", vmin=0.1, vmax=30, step=0.5, decimals=1, default=5.0), "Pi 高速プロファイルで有効。")
        self._add_row(f, "表示上限 FPS", self._spin("ui", "display_fps", vmin=1, vmax=60, default=30), "Pi 高速のカメラ表示に適用します。")
        self._add_row(f, "結果の有効期間 (ms)", self._spin("ui", "result_max_age_ms", vmin=50, vmax=5000, step=50, default=500), "撮影からの経過時間。期限切れの認識結果を表示しません。")
        return g

    # --------- public ---------

    def set_default_snapshot(self, cfg: dict[str, Any]) -> None:
        """リセット先のスナップショットを更新（プロファイル切替時に呼ぶ）。"""
        self._default_cfg = copy.deepcopy(cfg)

    def _reset_to_defaults(self) -> None:
        """スナップショット値で self.cfg を全置換し、UI も再描画。"""
        # cfg の中身を deep copy で置換（参照は維持して MainWindow 側にも反映させる）
        self.cfg.clear()
        self.cfg.update(copy.deepcopy(self._default_cfg))
        self.refresh_from_cfg()
        self.settingsChanged.emit(self.cfg)

    def refresh_from_cfg(self) -> None:
        """プロファイル切替などで cfg が差し替わった際の再同期。"""
        self._building = True
        # combo の value マッピングを保持
        for key, w in self._widgets.items():
            if len(key) == 3:
                section, parent_key, sub_key = key
                val = (self.cfg.get(section, {}).get(parent_key, {}) or {}).get(sub_key)
            else:
                section, k = key
                val = self.cfg.get(section, {}).get(k)
            if val is None:
                continue
            if isinstance(w, QCheckBox):
                w.setChecked(bool(val))
            elif isinstance(w, QSpinBox):
                w.setValue(int(val))
            elif isinstance(w, QDoubleSpinBox):
                w.setValue(float(val))
            elif isinstance(w, QComboBox):
                # combo のオプション values は widget.property("_values") に保存しておく
                values = w.property("_values")
                if values is not None and val in values:
                    w.setCurrentIndex(values.index(val))
        self._building = False

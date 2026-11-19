"""Car Program 2 の主要な調整項目を7インチ画面から編集する。"""
from copy import deepcopy
from pathlib import Path
from touch_choices import TouchComboBox, exec_embedded
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QPushButton, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget, QAbstractSpinBox, QScroller)


_ASSETS = Path(__file__).resolve().parent / 'assets'
_SPIN_ARROWS = """
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color: #81909a; background: #17232b; }
QSpinBox, QDoubleSpinBox { padding-right: 90px; min-width: 160px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 40px; height: 38px; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: top right; right: 42px; width: 40px; height: 38px; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(%s); width: 15px; height: 15px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(%s); width: 15px; height: 15px; }
""" % ((_ASSETS / 'plus.svg').as_posix(), (_ASSETS / 'minus.svg').as_posix())


class AdasSidebarDialog(QDialog):
    def __init__(self, cfg, parent=None, *, default_cfg=None, advanced_class=None):
        super().__init__(parent)
        self.cfg = deepcopy(cfg)
        self.default_cfg = deepcopy(default_cfg if default_cfg is not None else cfg)
        self.setWindowTitle('危険予知の設定')
        self.resize(680, 440)
        root = QVBoxLayout(self)
        title = QLabel('危険予知  ·  Pi高速2')
        title.setStyleSheet('font-size: 19px; font-weight: bold;')
        root.addWidget(title)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); inner.setObjectName('adasContent')
        inner.setStyleSheet("""
            QWidget#adasContent { background: #0d1721; }
            QLabel { color: #edf4f6; font-size: 16px; }
            QComboBox, QSpinBox, QDoubleSpinBox { color: #edf4f6; background: #243442; border: 1px solid #3a5060; border-radius: 8px; padding: 4px 10px; font-size: 16px; }
            QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 38px; background: #36525e; border: 1px solid #5d7783; }
            QCheckBox { color: #edf4f6; font-size: 16px; spacing: 10px; }
            QCheckBox::indicator { width: 24px; height: 24px; border: 2px solid #7eabb8; border-radius: 5px; background: #192733; }
            QCheckBox::indicator:checked { background: #00df92; border-color: #b9ffdf; }
        """)
        inner.setStyleSheet(inner.styleSheet() + _SPIN_ARROWS)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #263746; border-radius: 10px; background: #0d1721; } QScrollBar:vertical { width: 22px; background: #172630; } QScrollBar::handle:vertical { background: #6d9198; border-radius: 7px; min-height: 48px; }")
        self.form = QFormLayout(inner)
        self.form.setContentsMargins(14, 12, 14, 12)
        self.form.setSpacing(8)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        QScroller.grabGesture(scroll.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        self.controls = {}
        self._section('車線ゾーン')
        self._choice('車線の奥行き', ('lane', 'auto_depth'), [('自動', True), ('固定', False)], True)
        for label, key, low, high, default in (
            ('台形ゾーン中心', 'center_x_ratio', .35, .65, .5),
            ('台形の奥行き', 'zone_top_y_ratio', .2, .8, .45),
            ('手前幅', 'zone_bottom_width_ratio', .2, .7, .5),
            ('カーブ寄せ', 'zone_top_offset_ratio', -.2, .2, 0)):
            self._decimal(label, ('lane', key), low, high, default, .01)
        self._section('解析と表示')
        self._choice('YOLOモデル', ('detector', 'weights'), [(f'Hailo-8 YOLO26{x}', f'models/hailo8/yolo26{x}.hef') for x in ('n','s','m')] + [('Hailo-8 YOLOv8m', 'models/hailo8/yolov8m.hef')], 'models/hailo8/yolo26s.hef')
        self._choice('処理解像度', ('ui', 'max_process_width'), [(f'{x}px' if x else '自動', x) for x in (0,320,360,540,640,720,960,1280)], 960)
        self._choice('表示解像度', ('ui', 'display_max_width'), [(f'{x}px' if x else '元のサイズ', x) for x in (0,160,240,320,360,540,720,960,1280,1920)], 360)
        self._choice('重ね表示の大きさ', ('ui', 'overlay_size_scale'), [(f'{x}倍', x) for x in (.5,.75,1.,1.5,2.)], 1.)
        self._decimal('YOLO更新回数/秒', ('detector','update_hz'), .1, 30, 15., .5)
        self._decimal('車線更新回数/秒', ('lane','update_hz'), .1, 30, 15., .5)
        self._integer('解析間隔（フレーム）', ('detector','every_n_frames'), 1, 20, 1)
        if bool(self._get(('ui', 'independent_schedule'), False)):
            self.controls[('detector','every_n_frames')].setEnabled(False)
            self.controls[('detector','every_n_frames')].setToolTip('Pi高速2では「その他の詳細」でYOLO・車線の更新回数を設定します')
        self._section('使用する機能')
        for label,key,default in [('検出・追跡','enable_detection',True),('車線・車線逸脱','enable_lanes',True),('曲線車線','curve_lanes',False),('危険判定','enable_risk',True),('信号・標識','enable_signs',True),('視認性補正','enable_enhancement',True),('路面マスク表示','show_debug_mask',False),('カメラ異常検知','enable_blind_check',True),('AI奥行き画像','show_ai_depth_preview',False)]:
            self._check(label, ('ui',key), default)
        self._check('AI奥行き推定', ('hailo_scene','depth_enabled'), True)
        self._choice('AI奥行きの更新間隔', ('hailo_scene','depth_update_hz'), [(f'{x:.1f}秒ごと', 1/x) for x in (.2,.4,.6,.8,1.)], 1/0.6)
        self._section('推論範囲')
        self._choice('ROI推論', ('ui','roi_mode'), [('全画面','off'),('台形','trapezoid'),('矩形','rectangle')], 'off')
        for label,key,default in [('ROI矩形 X','x_ratio',.05),('ROI矩形 Y','y_ratio',.30),('ROI矩形 幅','w_ratio',.90),('ROI矩形 高さ','h_ratio',.65)]:
            self._decimal(label, ('ui','roi_rect',key), 0, 1, default, .01)
        scroll.setWidget(inner); root.addWidget(scroll, 1)
        buttons=QHBoxLayout()
        if advanced_class:
            advanced=QPushButton('その他の詳細'); advanced.clicked.connect(lambda: self._advanced(advanced_class)); buttons.addWidget(advanced)
        cancel=QPushButton('戻る');cancel.clicked.connect(self.reject);buttons.addWidget(cancel)
        save=QPushButton('保存');save.setObjectName('primary');save.clicked.connect(self._save);buttons.addWidget(save)
        for i in range(buttons.count()): buttons.itemAt(i).widget().setMinimumHeight(44)
        root.addLayout(buttons)

    def _section(self, title):
        label = QLabel(title)
        label.setStyleSheet('color: #8ad6cc; font-size: 16px; font-weight: bold; padding-top: 8px;')
        self.form.addRow(label)

    def _get(self, path, default):
        value=self.cfg
        for key in path:
            if not isinstance(value, dict) or key not in value: return default
            value=value[key]
        return value

    def _add(self, label, path, widget):
        widget.setMinimumHeight(42); self.form.addRow(label, widget); self.controls[path]=widget

    def _choice(self, label, path, options, default):
        box=TouchComboBox()
        box.setAccessibleName(label)
        for text,value in options: box.addItem(text,value)
        value=self._get(path,default); idx=box.findData(value)
        if idx < 0:
            box.addItem(str(value),value);idx=box.count()-1
        box.setCurrentIndex(idx);self._add(label,path,box)

    def _decimal(self,label,path,low,high,default,step):
        box=QDoubleSpinBox();box.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus);box.setRange(low,high);box.setSingleStep(step);box.setDecimals(2)
        box.setValue(float(self._get(path,default)));self._add(label,path,box)

    def _integer(self,label,path,low,high,default):
        box=QSpinBox();box.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus);box.setRange(low,high);box.setValue(int(self._get(path,default)));self._add(label,path,box)

    def _check(self,label,path,default):
        box=QCheckBox();box.setChecked(bool(self._get(path,default)));box.setText('オン' if box.isChecked() else 'オフ');box.toggled.connect(lambda checked: box.setText('オン' if checked else 'オフ'));self._add(label,path,box)

    def _save(self):
        for path,widget in self.controls.items():
            value = widget.currentData() if isinstance(widget,QComboBox) else widget.isChecked() if isinstance(widget,QCheckBox) else widget.value()
            node=self.cfg
            for key in path[:-1]: node=node.setdefault(key,{})
            node[path[-1]]=value
        # 旧Car Program 2と同じく解析間隔は車線にも反映する。
        if not self.cfg.get('ui', {}).get('independent_schedule', False):
            self.cfg.setdefault('lane',{})['every_n_frames']=self.cfg['detector']['every_n_frames']
        self.accept()

    def _advanced(self, cls):
        self._save_to_cfg_without_closing()
        dialog=cls(deepcopy(self.cfg),self,default_cfg=self.default_cfg)
        dialog.setStyleSheet('''
            QDialog { background: #111c27; color: #edf4f6; }
            QScrollArea { background: #0d1721; border: 1px solid #263746; border-radius: 8px; }
            QScrollArea QWidget { background: #0d1721; color: #edf4f6; }
            QGroupBox { color: #8ad6cc; border: 1px solid #3a5060; border-radius: 8px; margin-top: 12px; padding: 12px 8px 8px; font-size: 16px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QLabel, QCheckBox { color: #edf4f6; font-size: 16px; }
            QComboBox, QSpinBox, QDoubleSpinBox { color: #edf4f6; background: #243442; border: 1px solid #3a5060; border-radius: 6px; padding: 3px 8px; font-size: 16px; }
            QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 38px; background: #36525e; border: 1px solid #5d7783; }
            QCheckBox::indicator { width: 24px; height: 24px; border: 2px solid #7eabb8; border-radius: 5px; background: #192733; }
            QCheckBox::indicator:checked { background: #00df92; border-color: #b9ffdf; }
            QScrollBar:vertical { width: 22px; background: #172630; }
            QScrollBar::handle:vertical { background: #6d9198; border-radius: 7px; min-height: 48px; }
        ''')
        dialog.setStyleSheet(dialog.styleSheet() + _SPIN_ARROWS)
        for box in dialog.findChildren(QAbstractSpinBox):
            box.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
            box.setMinimumHeight(40)
        for box in dialog.findChildren(QComboBox):
            box.setMinimumHeight(40)
            box.view().setStyleSheet('QAbstractItemView { background: #243442; color: #edf4f6; } QAbstractItemView::item { min-height: 44px; padding: 4px; }')
        for label in dialog.findChildren(QLabel):
            if 'カーソルを乗せる' in label.text():
                label.setText('変更は前の画面で保存すると反映されます。現在使えない項目はグレー表示です。')
        unsupported = {('risk','follow_distance_factor'): '車間距離係数（現在未対応）',
                       ('input','video_mode'): '動画の解析方法（実時間に固定）'}
        if str(self.cfg.get('detector',{}).get('weights','')).endswith('.hef'):
            unsupported.update({('detector','device'): 'Device（AI HATを使用）',
                                ('detector','imgsz'): 'YOLO imgsz（HEFモデルで固定）',
                                ('tracker','track_buffer'): 'Track buffer（現行Hailoでは未対応）'})
        if 'yolo26' in str(self.cfg.get('detector',{}).get('weights','')).lower():
            unsupported[('detector','iou')] = 'IoU（YOLO26ではNMSなし）'
        if self.cfg.get('ui',{}).get('independent_schedule'):
            for section, key, text in [('detector','every_n_frames','検出フレーム間隔'),('detector','phase','検出位相'),('lane','every_n_frames','車線フレーム間隔'),('lane','phase','車線位相')]:
                unsupported[(section,key)] = text + '（更新回数/秒を使用）'
        widgets = getattr(dialog, '_widgets', {})
        for path, explanation in unsupported.items():
            if path in widgets:
                widget = widgets[path]
                widget.setEnabled(False)
                widget.setToolTip(explanation)
                for form in dialog.findChildren(QFormLayout):
                    label = form.labelForField(widget)
                    if isinstance(label, QLabel):
                        label.setText(explanation)
                        label.setWordWrap(True)
        for form in dialog.findChildren(QFormLayout):
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            form.setVerticalSpacing(10)
        for scroll in dialog.findChildren(QScrollArea):
            QScroller.grabGesture(scroll.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        dialog.resize(min(680,self.width()),min(440,self.height()))
        if exec_embedded(dialog, self) != QDialog.DialogCode.Accepted:
            return
        self.cfg=dialog.cfg
        for path, widget in self.controls.items():
            value=self._get(path,None)
            if value is None:
                continue
            widget.blockSignals(True)
            if isinstance(widget,QComboBox):
                index=widget.findData(value)
                if index < 0:
                    widget.addItem(str(value),value)
                    index=widget.count()-1
                widget.setCurrentIndex(index)
            elif isinstance(widget,QCheckBox):
                widget.setChecked(bool(value))
            else:
                widget.setValue(value)
            widget.blockSignals(False)

    def _save_to_cfg_without_closing(self):
        for path,widget in self.controls.items():
            value=widget.currentData() if isinstance(widget,QComboBox) else widget.isChecked() if isinstance(widget,QCheckBox) else widget.value()
            node=self.cfg
            for key in path[:-1]: node=node.setdefault(key,{})
            node[path[-1]]=value

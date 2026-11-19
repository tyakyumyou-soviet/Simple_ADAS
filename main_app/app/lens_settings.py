"""前後カメラそれぞれの表示・解析用レンズ補正。"""
from calibrated_lens import profile_for
from math import isfinite
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QVBoxLayout)
from touch_choices import TouchComboBox


def load_lens_settings(preferences, role):
    if role not in ('front', 'rear'):
        raise ValueError('不正なカメラ')
    enabled = preferences.value(f'lens_{role}_enabled', True, bool)
    values = []
    for key in ('k1', 'k2'):
        try:
            value = float(preferences.value(f'lens_{role}_{key}', 0.0))
            if not isfinite(value) or not -1 <= value <= 1:
                raise ValueError(key)
        except (ValueError, TypeError):
            value = 0.0
        values.append(value)
    return enabled, values[0], values[1]


def fill_lens_environment(environment, preferences):
    for role in ('front', 'rear'):
        enabled, k1, k2 = load_lens_settings(preferences, role)
        environment.insert(f'LENS_{role.upper()}_ENABLED', '1' if enabled else '0')
        environment.insert(f'LENS_{role.upper()}_K1', str(k1))
        environment.insert(f'LENS_{role.upper()}_K2', str(k2))


def lens_from_environment(role, environ):
    prefix = f'LENS_{role.upper()}_'
    if environ.get(prefix + 'ENABLED') != '1':
        return None
    if profile_for(role, environ.get(role.upper() + '_DEVICE', '')):
        return None  # 校正補正と手動補正を二重適用しない。
    values = tuple(float(environ.get(prefix + key, '0')) for key in ('K1', 'K2'))
    if not all(isfinite(x) and -1 <= x <= 1 for x in values):
        raise ValueError('魚眼補正値が範囲外です')
    return values


class LensSettingsDialog(QDialog):
    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self.setWindowTitle('魚眼補正')
        self.values = {role: list(load_lens_settings(preferences, role)) for role in ('front', 'rear')}
        self.calibrated = {role: bool(profile_for(role, preferences.value('camera_device_' + role, '', str))) for role in ('front', 'rear')}
        self.role = 'front'
        layout = QVBoxLayout(self); layout.setSpacing(8)
        title = QLabel('魚眼補正'); title.setObjectName('detailTitle'); layout.addWidget(title)
        self.camera = TouchComboBox(); self.camera.setObjectName('cameraDisplay'); self.camera.setAccessibleName('補正するカメラ')
        self.camera.addItem('フロントカメラ', 'front'); self.camera.addItem('リアカメラ', 'rear')
        self.camera.setMinimumHeight(44); self.camera.currentIndexChanged.connect(self._change_camera)
        layout.addWidget(self.camera)
        self.enabled = QCheckBox('魚眼補正：オン'); self.enabled.setMinimumHeight(42)
        self.enabled.setStyleSheet('QCheckBox { color: #edf4f6; font-size: 17px; spacing: 10px; } QCheckBox::indicator { width: 24px; height: 24px; border: 2px solid #7eabb8; border-radius: 5px; background: #192733; } QCheckBox::indicator:checked { background: #00df92; border-color: #b9ffdf; }')
        self.enabled.toggled.connect(self._save_current); layout.addWidget(self.enabled)
        self.sliders = []; self.labels = []
        for index, text in enumerate(('補正の強さ', '端の調整')):
            line = QHBoxLayout(); label = QLabel(); label.setMinimumWidth(150)
            slider = QSlider(Qt.Horizontal); slider.setObjectName("settingsSlider"); slider.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True); slider.setStyleSheet("QSlider { background: transparent; border: none; }"); slider.setRange(-100, 100); slider.setMinimumHeight(44)
            slider.setAccessibleName(text); slider.valueChanged.connect(self._save_current)
            line.addWidget(label); line.addWidget(slider, 1); layout.addLayout(line)
            self.sliders.append(slider); self.labels.append((label, text))
        self.calibration_note = QLabel(); self.calibration_note.setWordWrap(True); layout.addWidget(self.calibration_note)
        note = QLabel('校正済みカメラは自動補正します。未登録カメラはスライダーで調整できます。表示と危険予知に適用し、録画は補正前の映像を保存します。')
        note.setWordWrap(True); note.setObjectName('detailHint'); layout.addWidget(note)
        buttons=QHBoxLayout(); cancel=QPushButton('戻る'); cancel.clicked.connect(self.reject)
        save=QPushButton('保存'); save.setObjectName('primary'); save.clicked.connect(self.accept)
        for button in (cancel, save): button.setMinimumHeight(44); buttons.addWidget(button)
        layout.addLayout(buttons); self._load_current()

    def _load_current(self):
        enabled, k1, k2 = self.values[self.role]
        calibrated = self.calibrated[self.role]
        self.calibration_note.setText('校正データ使用：解像度変更と中央切り出しの画角に自動調整。周辺視野を広く残すため、端に黒い部分が出る場合があります。' if calibrated else '手動補正：このカメラの校正データは未登録です。')
        for widget in (self.enabled, *self.sliders): widget.blockSignals(True)
        self.enabled.setChecked(enabled)
        self.sliders[0].setValue(round(k1*100)); self.sliders[1].setValue(round(k2*100))
        for widget in (self.enabled, *self.sliders): widget.blockSignals(False)
        self._save_current()

    def _save_current(self, *_):
        self.enabled.setText('魚眼補正：' + ('オン' if self.enabled.isChecked() else 'オフ'))
        self.values[self.role] = [self.enabled.isChecked(), *(slider.value()/100 for slider in self.sliders)]
        for slider, (label, text) in zip(self.sliders, self.labels):
            label.setText(f'{text}  {slider.value()/100:+.2f}')
            slider.setEnabled(self.enabled.isChecked() and not self.calibrated[self.role])

    def _change_camera(self, _index):
        self._save_current(); self.role = self.camera.currentData(); self._load_current()

    def save(self, preferences):
        self._save_current()
        for role, (enabled, k1, k2) in self.values.items():
            preferences.setValue(f'lens_{role}_enabled', enabled)
            preferences.setValue(f'lens_{role}_k1', k1)
            preferences.setValue(f'lens_{role}_k2', k2)
        preferences.sync()

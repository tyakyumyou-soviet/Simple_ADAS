"""危険度に応じた暫定警告音。再生先はシステムの標準音声出力。"""
from __future__ import annotations

import math
import shutil
import struct
import tempfile
import wave
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class WarningAudio(QObject):
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._directory = tempfile.TemporaryDirectory(prefix="vehicle-alert-")
        self._short = self._make_tone("attention.wav", 0.42, 1800, pulses=True)
        self._continuous = self._make_tone("danger.wav", 10.0, 1800)
        self._profiles = {"provisional": {1: self._short, 2: self._short, 3: self._continuous}}
        self._profile = "provisional"
        self._player = shutil.which("pw-play") or shutil.which("paplay")
        self._process = QProcess(self)
        self._process.errorOccurred.connect(self._on_error)
        self._process.finished.connect(self._finished)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._play)
        self._level = 0
        self._restarting = False

    def _make_tone(self, name: str, seconds: float, frequency: float, pulses: bool = False) -> str:
        rate = 44100
        count = round(rate * seconds)
        frames = bytearray()
        for index in range(count):
            fade = min(1.0, index / (rate * 0.01), (count - index - 1) / (rate * 0.01))
            if pulses:
                position = index % round(rate * 0.14)
                length = round(rate * 0.09)
                fade = min(1.0, position / (rate * 0.005), max(0, length - position) / (rate * 0.005))
            sample = round(32767 * 0.15 * fade * math.sin(2 * math.pi * frequency * index / rate))
            frames.extend(struct.pack('<h', sample))
        path = str(Path(self._directory.name) / name)
        with wave.open(path, 'wb') as output:
            output.setparams((1, 2, rate, count, 'NONE', 'not compressed'))
            output.writeframes(frames)
        return path

    def register_profile(self, name: str, paths: dict) -> None:
        if not name or name == "provisional":
            raise ValueError("不正な警告音プロファイル")
        files = {}
        for level in (1, 2, 3):
            raw = paths.get(str(level), paths.get(level))
            if not raw or not Path(raw).expanduser().is_file():
                raise FileNotFoundError(f"危険度{level}の音声ファイルがありません")
            files[level] = str(Path(raw).expanduser().absolute())
        self._profiles[name] = files

    def select_profile(self, name: str) -> None:
        if name not in self._profiles:
            raise ValueError("選択した警告音は登録されていません")
        if name == self._profile:
            return
        level = self._level
        self.set_level(0)
        self._profile = name
        if level:
            self.set_level(level)

    def has_profile(self, name: str) -> bool:
        return name in self._profiles

    def set_level(self, level: int) -> None:
        level = max(0, min(3, int(level)))
        if level == self._level:
            return
        self._level = level
        self._timer.stop()
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._restarting = True
            self._process.kill()
        elif level:
            self._timer.start(0)

    def _play(self) -> None:
        if not self._level or self._process.state() != QProcess.ProcessState.NotRunning:
            return
        if not self._player:
            self._level = 0
            self.error.emit("警告音を再生できません: 音声出力が見つかりません")
            return
        self._process.start(self._player, [self._profiles[self._profile][self._level]])

    def _finished(self, code: int, _status) -> None:
        if self._restarting:
            self._restarting = False
            if self._level:
                self._timer.start(0)
            return
        if self._level and code == 0:
            self._timer.start({1: 900, 2: 250, 3: 0}[self._level])
        elif self._level and code != 0:
            self._level = 0
            self.error.emit("警告音の再生に失敗しました")

    def _on_error(self, _error) -> None:
        if self._restarting:
            return
        if self._level:
            self._level = 0
            self._timer.stop()
            self.error.emit("警告音を再生できません")

    def stop(self) -> None:
        self.set_level(0)

    def close(self) -> None:
        self.stop()
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.waitForFinished(3000)
        self._directory.cleanup()

"""Raspberry Pi OS の音量・バックライト制御。未検出時は操作を無効にする。"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


class AudioVolumeControl:
    def __init__(self) -> None:
        self.wpctl = shutil.which("wpctl") if sys.platform.startswith("linux") else None
        self.pactl = shutil.which("pactl") if sys.platform.startswith("linux") else None

    @property
    def available(self) -> bool:
        return bool(self.wpctl or self.pactl)

    def has_real_output(self) -> bool:
        if self.pactl:
            try:
                result = subprocess.run([self.pactl, "get-default-sink"], capture_output=True, text=True, timeout=1, check=True)
                name = result.stdout.strip().lower()
                return bool(name) and name not in {"auto_null", "dummy_output"}
            except (OSError, subprocess.SubprocessError):
                pass
        if self.wpctl:
            try:
                result = subprocess.run([self.wpctl, "inspect", "@DEFAULT_AUDIO_SINK@"], capture_output=True, text=True, timeout=1, check=True)
                info = result.stdout.lower()
                return not any(marker in info for marker in ("auto_null", "dummy output", "support.null-audio-sink"))
            except (OSError, subprocess.SubprocessError):
                pass
        return False

    def get_percent(self) -> int | None:
        if not self.has_real_output():
            return None
        if self.wpctl:
            try:
                result = subprocess.run([self.wpctl, "get-volume", "@DEFAULT_AUDIO_SINK@"], capture_output=True, text=True, timeout=1, check=True)
                match = re.search(r"Volume:\s*([0-9.]+)", result.stdout)
                if match:
                    return max(0, min(100, round(float(match.group(1)) * 100)))
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
        if self.pactl:
            try:
                result = subprocess.run([self.pactl, "get-sink-volume", "@DEFAULT_SINK@"], capture_output=True, text=True, timeout=1, check=True)
                match = re.search(r"/(?:\s*)(\d+)%", result.stdout)
                if match:
                    return max(0, min(100, int(match.group(1))))
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
        return None

    def set_percent(self, percent: int) -> bool:
        percent = max(0, min(100, int(percent)))
        if not self.has_real_output():
            return False
        if self.wpctl:
            try:
                result = subprocess.run([self.wpctl, "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent / 100:.2f}"], capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    if percent > 0:
                        unmute = subprocess.run([self.wpctl, "set-mute", "@DEFAULT_AUDIO_SINK@", "0"], capture_output=True, timeout=2)
                        return unmute.returncode == 0
                    return True
            except (OSError, subprocess.SubprocessError):
                pass
        if self.pactl:
            try:
                result = subprocess.run([self.pactl, "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"], capture_output=True, text=True, timeout=2)
                if result.returncode == 0 and percent > 0:
                    result = subprocess.run([self.pactl, "set-sink-mute", "@DEFAULT_SINK@", "0"], capture_output=True, timeout=2)
                return result.returncode == 0
            except (OSError, subprocess.SubprocessError):
                pass
        return False


class BacklightControl:
    def __init__(self, configured_path: str | None = None) -> None:
        self.brightness_path: Path | None = None
        self.maximum = 0
        if not sys.platform.startswith("linux"):
            return
        candidates = [Path(configured_path).expanduser()] if configured_path else sorted(Path("/sys/class/backlight").glob("*/brightness"))
        for candidate in candidates:
            maximum_path = candidate.with_name("max_brightness")
            try:
                maximum = int(maximum_path.read_text().strip())
                if maximum > 0 and candidate.exists() and os.access(candidate, os.W_OK):
                    self.brightness_path = candidate
                    self.maximum = maximum
                    break
            except (OSError, ValueError):
                continue

    @property
    def available(self) -> bool:
        return self.brightness_path is not None and self.maximum > 0

    def get_percent(self) -> int | None:
        if not self.available:
            return None
        try:
            value = int(self.brightness_path.read_text().strip())
            return max(0, min(100, round(value * 100 / self.maximum)))
        except (OSError, ValueError, ZeroDivisionError):
            return None

    def set_percent(self, percent: int) -> bool:
        if not self.available:
            return False
        value = round(max(0, min(100, int(percent))) * self.maximum / 100)
        try:
            self.brightness_path.write_text(f"{value}\n")
            return True
        except OSError:
            return False

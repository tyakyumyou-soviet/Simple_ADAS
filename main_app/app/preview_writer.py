"""同一端末の表示・解析へ最新フレームを渡すプレビュー領域。"""
from __future__ import annotations

from shared_frame import RawFrame, write_frame
import fcntl
import os
import tempfile
from pathlib import Path


class PreviewWriter:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink() or self.directory.stat().st_uid != os.getuid():
            raise RuntimeError('プレビュー保存先の所有者または形式が不正です')
        os.chmod(self.directory, 0o700)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
        self._lock_fd = os.open(self.directory / '.lock', flags, 0o600)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            os.close(self._lock_fd)
            self._lock_fd = None
            raise RuntimeError('別のカメラサービスがプレビューを使用中です')
        # 異常終了で前回のフレームが残っていても、新しい映像として使わない。
        try:
            for role in ('front', 'rear'):
                (self.directory / (role + '.frame')).unlink(missing_ok=True)
                for candidate in self.directory.glob('.' + role + '-*'):
                    if candidate.is_symlink() or not candidate.is_file():
                        raise RuntimeError('プレビューの一時ファイルが不正です')
                    candidate.unlink()
        except Exception:
            os.close(self._lock_fd)
            self._lock_fd = None
            raise

    def write(self, role: str, image: RawFrame) -> None:
        if role not in ('front', 'rear'):
            raise ValueError('不正なカメラ')
        if self._lock_fd is None:
            raise RuntimeError('プレビューは終了しています')
        write_frame(self.directory / (role + '.frame'), image)

    def close(self) -> None:
        if self._lock_fd is None:
            return
        try:
            for role in ('front', 'rear'):
                (self.directory / (role + '.frame')).unlink(missing_ok=True)
        finally:
            os.close(self._lock_fd)
            self._lock_fd = None

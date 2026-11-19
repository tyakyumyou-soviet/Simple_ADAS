"""非圧縮RGB画像をmmapでプロセス間共有する。Piでは/runのRAM領域を使用。"""
import fcntl
import mmap
import os
import struct
import time
from dataclasses import dataclass
from pathlib import Path

_HEADER = struct.Struct('<8sIIQQ')
_MAGIC = b'RGBFRAME'
_CAPACITY = 32 * 1024 * 1024

@dataclass(frozen=True)
class RawFrame:
    width: int
    height: int
    pixels: bytes
    timestamp_ns: int = 0
    sequence: int = 0

    def bgr(self):
        import numpy as np
        return np.frombuffer(self.pixels, dtype=np.uint8).reshape(self.height, self.width, 3)[:, :, ::-1].copy()


def write_frame(path: Path, frame: RawFrame):
    size = frame.width * frame.height * 3
    if min(frame.width, frame.height) <= 0 or size != len(frame.pixels) or size + _HEADER.size > _CAPACITY:
        raise ValueError('非圧縮画像の寸法が不正です')
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if os.fstat(fd).st_size != _CAPACITY:
            os.ftruncate(fd, _CAPACITY)
        with mmap.mmap(fd, _CAPACITY) as memory:
            memory[_HEADER.size:_HEADER.size+size] = frame.pixels
            memory[:_HEADER.size] = _HEADER.pack(_MAGIC, frame.width, frame.height,
                frame.timestamp_ns or time.time_ns(), frame.sequence or time.monotonic_ns())
    finally:
        os.close(fd)


def read_frame(path: Path):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        if os.fstat(fd).st_size != _CAPACITY:
            raise OSError('共有画像が未初期化です')
        with mmap.mmap(fd, _CAPACITY, access=mmap.ACCESS_READ) as memory:
            magic, width, height, stamp, seq = _HEADER.unpack(memory[:_HEADER.size])
            size = width * height * 3
            if magic != _MAGIC or min(width, height) <= 0 or size+_HEADER.size > _CAPACITY:
                raise OSError('共有画像のヘッダーが不正です')
            return RawFrame(width, height, memory[_HEADER.size:_HEADER.size+size], stamp, seq)
    finally:
        os.close(fd)

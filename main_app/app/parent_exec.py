"""Linuxで親が終了したときにカメラ取得プロセスを残さない。"""
from __future__ import annotations

import ctypes
import os
import signal
import sys


def main() -> int:
    if len(sys.argv) < 3:
        return 2
    expected_parent = int(sys.argv[1])
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), '親プロセス終了時の停止設定に失敗しました')
    if os.getppid() != expected_parent:
        return 1
    os.execvp(sys.argv[2], sys.argv[2:])
    return 1


if __name__ == '__main__':
    raise SystemExit(main())

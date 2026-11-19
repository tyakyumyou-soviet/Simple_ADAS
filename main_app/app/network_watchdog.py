"""親プロセスが異常終了した場合に一時APを止め、元の接続へ戻す。"""
from __future__ import annotations

import argparse
import os
import select
import subprocess
import sys
import time


def restore(prefix, device: str, previous_uuid: str, ap_uuid: str) -> bool:
    def run(*args):
        return subprocess.run([*prefix, '--wait', '15', *args], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=20).returncode == 0
    def current():
        result = subprocess.run([*prefix, '-g', 'GENERAL.CON-UUID', 'device', 'show', device],
                                capture_output=True, text=True, timeout=5)
        value = result.stdout.strip()
        return '' if value in ('--', '') else value
    try:
        active = current()
        if active == ap_uuid:
            run('connection', 'down', 'uuid', ap_uuid)
            active = current()
        # 利用者が別ネットワークを選んだ場合、その接続を上書きしない。
        if previous_uuid and not active:
            run('connection', 'up', 'uuid', previous_uuid, 'ifname', device)
            active = current()
        if active == ap_uuid or (previous_uuid and not active):
            return False
        if not run('connection', 'delete', 'uuid', ap_uuid):
            # 既に削除済みの場合だけ成功とする。
            probe = subprocess.run([*prefix, '-g', 'connection.uuid', 'connection', 'show', 'uuid', ap_uuid],
                                   capture_output=True, text=True, timeout=5)
            if probe.returncode == 0:
                return False
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', required=True, type=int)
    parser.add_argument('--device', required=True)
    parser.add_argument('--previous', default='')
    parser.add_argument('--ap-uuid', required=True)
    parser.add_argument('--nmcli', required=True)
    parser.add_argument('--sudo', default='')
    parser.add_argument('--timeout', type=int, default=960)
    args = parser.parse_args()
    prefix = ([args.sudo, '-n'] if args.sudo else []) + [args.nmcli]
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        try:
            os.kill(args.pid, 0)
        except ProcessLookupError:
            break
        except PermissionError:
            pass
        ready, _, _ = select.select([sys.stdin], [], [], 1.0)
        if ready:
            command = sys.stdin.readline().strip()
            if command == 'done':
                return 0
            if command in ('restore', ''):
                break
    for attempt in range(3):
        if restore(prefix, args.device, args.previous, args.ap_uuid):
            return 0
        time.sleep(2)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())

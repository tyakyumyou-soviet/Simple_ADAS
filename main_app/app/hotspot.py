"""転送時だけNetworkManagerの一時アクセスポイントを使う。"""
from __future__ import annotations

import ipaddress
import os
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from network_watchdog import restore


class HotspotError(RuntimeError):
    pass


def wifi_qr(ssid: str, password: str) -> str:
    def escape(value: str) -> str:
        for char in ('\\', ';', ',', ':', '"'):
            value = value.replace(char, '\\' + char)
        return value
    return f'WIFI:T:WPA;S:{escape(ssid)};P:{escape(password)};;'


class WifiHotspot:
    def __init__(self, device='wlan0', timeout_seconds=900, *, nmcli=None, sudo=None):
        self.device = device
        self.timeout_seconds = int(timeout_seconds)
        self.nmcli = nmcli or shutil.which('nmcli')
        self.sudo = sudo if sudo is not None else shutil.which('sudo')
        if not self.nmcli:
            raise HotspotError('NetworkManagerが見つかりません')
        self.prefix = ([self.sudo, '-n'] if self.sudo else []) + [self.nmcli]
        self.previous_uuid = ''
        self.ap_uuid = str(uuid.uuid4())
        self.ssid = 'SimpleADAS-' + secrets.token_hex(3).upper()
        self.password = secrets.token_urlsafe(12)
        self.address = ''
        self.watchdog = None
        self.created = False
        self.active = False

    def _run(self, *args, timeout=25):
        try:
            result = subprocess.run([*self.prefix, '--wait', '15', *args], capture_output=True,
                                    text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise HotspotError(f'ネットワーク操作に失敗しました: {type(exc).__name__}') from exc
        if result.returncode:
            error = result.stderr.strip().replace(self.password, '[非表示]')
            raise HotspotError(f'ネットワーク操作に失敗しました: {error or result.returncode}')
        return result.stdout.strip()

    def _current_uuid(self) -> str:
        value = self._run('-g', 'GENERAL.CON-UUID', 'device', 'show', self.device)
        return '' if value in ('', '--') else value

    def _spawn_watchdog(self):
        script = Path(__file__).with_name('network_watchdog.py')
        cmd = [sys.executable, str(script), '--pid', str(os.getpid()), '--device', self.device,
               '--previous', self.previous_uuid, '--ap-uuid', self.ap_uuid,
               '--nmcli', self.nmcli, '--timeout', str(self.timeout_seconds + 60)]
        if self.sudo:
            cmd.extend(['--sudo', self.sudo])
        self.watchdog = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, start_new_session=True)

    def start(self) -> dict:
        if self.created:
            raise HotspotError('アクセスポイントは既に準備済みです')
        self.previous_uuid = self._current_uuid()
        try:
            self._run('connection', 'add', 'type', 'wifi', 'ifname', self.device,
                      'con-name', 'SimpleADAS-' + self.ap_uuid[:8], 'autoconnect', 'no',
                      'ssid', self.ssid, 'mode', 'ap', '--',
                      'connection.uuid', self.ap_uuid, 'ipv4.method', 'shared',
                      'ipv6.method', 'disabled', '802-11-wireless.band', 'bg',
                      '802-11-wireless-security.key-mgmt', 'wpa-psk',
                      '802-11-wireless-security.psk', self.password)
            self.created = True
            self._spawn_watchdog()
            self._run('connection', 'up', 'uuid', self.ap_uuid, 'ifname', self.device)
            if self._current_uuid() != self.ap_uuid:
                raise HotspotError('アクセスポイントの起動を確認できません')
            for _ in range(10):
                values = self._run('-g', 'IP4.ADDRESS', 'device', 'show', self.device)
                for item in values.splitlines():
                    try:
                        address = ipaddress.ip_interface(item).ip
                        if address.version == 4 and not address.is_loopback:
                            self.address = str(address)
                            break
                    except ValueError:
                        continue
                if self.address:
                    break
                time.sleep(0.2)
            if not self.address:
                raise HotspotError('アクセスポイントのIPアドレスを取得できません')
            self.active = True
            return {'ssid': self.ssid, 'password': self.password, 'address': self.address,
                    'wifi_qr': wifi_qr(self.ssid, self.password)}
        except Exception:
            if self.created:
                self.stop()
            raise

    def stop(self) -> bool:
        if not self.created:
            return True
        ok = restore(self.prefix, self.device, self.previous_uuid, self.ap_uuid)
        if not ok:
            if self.watchdog and self.watchdog.stdin:
                try:
                    self.watchdog.stdin.write(b'restore\n')
                    self.watchdog.stdin.flush()
                except (OSError, BrokenPipeError):
                    pass
            return False
        self.created = False
        self.active = False
        if self.watchdog:
            if self.watchdog.stdin:
                try:
                    self.watchdog.stdin.write(b'done\n')
                    self.watchdog.stdin.flush()
                    self.watchdog.stdin.close()
                except (OSError, BrokenPipeError):
                    pass
            try:
                self.watchdog.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.watchdog.terminate()
                self.watchdog.wait(timeout=3)
            self.watchdog = None
        return True

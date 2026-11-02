"""既存RustビューアのWeb画面と互換APIを持つLAN転送セッション。"""
import json
import mimetypes
import secrets
import socket
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

FOLDERS = [{"name": f"{label} · {name}", "path": f"{camera}/{category}", "artworkClass": "artwork-normal", "barClass": "bar-normal", "icon": "▶"}
           for camera, label in (("front", "フロント"), ("rear", "リア"))
           for category, name in (("continuous", "通常"), ("event", "イベント"), ("manual", "手動"))]


def finalized(path):
    if path.suffix.lower() != '.mp4':
        return False
    try:
        size = path.stat().st_size
        with path.open('rb') as source:
            offset = 0
            while offset + 8 <= size:
                source.seek(offset)
                header = source.read(8)
                length = int.from_bytes(header[:4], 'big')
                if header[4:8] == b'moov':
                    return length >= 8 and offset + length <= size
                if length == 1:
                    length = int.from_bytes(source.read(8), 'big')
                if length < 8:
                    break
                offset += length
    except OSError:
        pass
    return False


class SessionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args):
        self.connections = set()
        self.connection_condition = threading.Condition()
        super().__init__(*args)

    def process_request(self, request, address):
        with self.connection_condition:
            self.connections.add(request)
        try:
            super().process_request(request, address)
        except Exception:
            self.shutdown_request(request)
            raise

    def shutdown_request(self, request):
        try:
            super().shutdown_request(request)
        finally:
            with self.connection_condition:
                self.connections.discard(request)
                self.connection_condition.notify_all()

    def close_clients(self, timeout=5):
        deadline = time.monotonic() + timeout
        with self.connection_condition:
            for connection in tuple(self.connections):
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()
            while self.connections:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('転送接続の停止を確認できません')
                self.connection_condition.wait(remaining)


class TransferSession:
    def __init__(self, root: Path, static: Path, advertised_host=None):
        self.root = root.resolve()
        self.static = static.resolve()
        self.token = secrets.token_urlsafe(24)
        self.server = None
        self.thread = None
        self.active = False
        self.url = ''
        self.advertised_host = advertised_host

    def start(self):
        for folder in FOLDERS:
            (self.root / folder['path']).mkdir(parents=True, exist_ok=True)
        session = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *_):
                pass  # URLs contain session credentials.
            def send(self, status, body=b'', content_type='text/plain; charset=utf-8', extra=()):
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                for key, value in extra:
                    self.send_header(key, value)
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(body)
            def do_HEAD(self):
                self.do_GET()
            def do_GET(self):
                try:
                    self.dispatch()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except OSError:
                    self.send(404)
            def dispatch(self):
                route = urlsplit(self.path)
                if route.path == '/connect/' + session.token:
                    self.send(302, extra=[('Location', '/'), ('Set-Cookie', f'dashcam={session.token}; HttpOnly; SameSite=Strict; Path=/')])
                    return
                cookies = SimpleCookie()
                try:
                    cookies.load(self.headers.get('Cookie', ''))
                except Exception:
                    self.send(403); return
                if 'dashcam' not in cookies or not secrets.compare_digest(cookies['dashcam'].value, session.token):
                    self.send(403, '端末画面のQRコードから接続してください'.encode()); return
                if route.path == '/api/videos':
                    selected = parse_qs(route.query).get('folder', [None])[0]
                    allowed = [f['path'] for f in FOLDERS]
                    if selected is not None and selected not in allowed:
                        self.send(403); return
                    videos = []
                    for folder in ([selected] if selected else allowed):
                        for path in (session.root / folder).rglob('*.mp4'):
                            real = path.resolve()
                            if not real.is_relative_to(session.root) or not finalized(real):
                                continue
                            stat = real.stat()
                            videos.append(dict(path=path.relative_to(session.root).as_posix(), name=path.name, folder=folder, size=stat.st_size, modified=int(stat.st_mtime), mime='video/mp4'))
                    videos.sort(key=lambda item: item['modified'], reverse=True)
                    self.send(200, json.dumps(dict(total=len(videos), videos=videos)).encode(), 'application/json'); return
                if route.path.startswith(('/video/', '/download/')):
                    relative = unquote(route.path.split('/', 2)[2])
                    path = (session.root / relative).resolve()
                    if not path.is_relative_to(session.root) or not any(path.is_relative_to((session.root / f['path']).resolve()) for f in FOLDERS) or not finalized(path):
                        self.send(404); return
                    size = path.stat().st_size
                    start, end, status = 0, size - 1, 200
                    requested = self.headers.get('Range')
                    if requested:
                        try:
                            if not requested.startswith('bytes=') or ',' in requested:
                                raise ValueError()
                            left, right = requested[6:].split('-', 1)
                            if not left:
                                count = int(right)
                                if count <= 0: raise ValueError()
                                start = max(0, size-count)
                            else:
                                start = int(left)
                                end = min(size-1, int(right)) if right else size-1
                            if start < 0 or start > end or start >= size: raise ValueError()
                            status = 206
                        except ValueError:
                            self.send(416, extra=[('Content-Range', f'bytes */{size}')]); return
                    self.send_response(status)
                    self.send_header('Content-Type', 'video/mp4')
                    self.send_header('Content-Length', str(end-start+1))
                    self.send_header('Accept-Ranges', 'bytes')
                    if status == 206: self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                    if route.path.startswith('/download/'):
                        self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + __import__('urllib.parse', fromlist=['quote']).quote(path.name))
                    self.end_headers()
                    if self.command == 'HEAD': return
                    with path.open('rb') as source:
                        source.seek(start)
                        remaining = end-start+1
                        while remaining and session.active:
                            data = source.read(min(65536, remaining))
                            if not data: break
                            self.wfile.write(data); remaining -= len(data)
                    return
                assets = {'/': 'index.html', '/static/app.js': 'app.js', '/static/style.css': 'style.css'}
                name = assets.get(route.path)
                if not name:
                    self.send(404); return
                data = (session.static / name).read_bytes()
                if name == 'app.js':
                    text = data.decode()
                    begin = text.index('const FOLDERS = [')
                    finish = text.index('];', begin)+2
                    data = (text[:begin]+'const FOLDERS = '+json.dumps(FOLDERS, ensure_ascii=False)+';'+text[finish:]).encode()
                self.send(200, data, mimetypes.guess_type(name)[0] or 'application/octet-stream')

        self.active = True
        self.server = SessionHTTPServer(('0.0.0.0', 0), Handler)
        self.server.daemon_threads = True
        host = self.advertised_host
        if not host:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                    probe.connect(('192.0.2.1', 9))
                    host = probe.getsockname()[0]
            except OSError:
                host = '127.0.0.1'
        self.url = f'http://{host}:{self.server.server_port}/connect/{self.token}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.url

    def stop(self):
        self.active = False
        if self.server:
            server = self.server
            if self.thread and self.thread.is_alive():
                server.shutdown()
            server.server_close()
            server.close_clients()
            if self.thread:
                self.thread.join(timeout=5)
                if self.thread.is_alive():
                    raise TimeoutError('転送待受スレッドの停止を確認できません')
            self.server = None
        self.url = ''
        return True

"""動画検証を危険予知用Python環境で実行する子プロセス。"""
import base64
import dataclasses
import json
import os
import sys
import threading
from pathlib import Path

import cv2
from PySide6.QtCore import QCoreApplication
from video_backend import make_video_worker
from alert_adapter import adapt_alert


def main():
    project, video = map(Path, sys.argv[1:3])
    os.chdir(project)
    app = QCoreApplication([])
    worker = make_video_worker(project, video, adas=True)
    failed = []
    def frame_ready(frame, meta):
        ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            tracks = meta.get('tracks', [])
            classes = {track.track_id: track.cls for track in tracks}
            alerts = [dataclasses.asdict(adapt_alert(alert, classes)) for alert in meta.get('alerts', [])]
            packet = {'jpeg': base64.b64encode(encoded.tobytes()).decode('ascii'),
                      'alerts': alerts, 'track_count': len(tracks)}
            print('FRAME ' + json.dumps(packet, ensure_ascii=False, separators=(',', ':')), flush=True)
    def error(message):
        failed.append(message)
        print('VIDEO_ERROR ' + str(message).replace('\n', ' '), flush=True)
    worker.frame_ready.connect(frame_ready)
    worker.error.connect(error)
    worker.finished.connect(app.quit)
    def commands():
        for line in sys.stdin:
            if line.strip() == 'STOP':
                worker.stop()
                break
    threading.Thread(target=commands, daemon=True).start()
    worker.start()
    app.exec()
    worker.wait()
    return int(bool(failed))


if __name__ == '__main__':
    raise SystemExit(main())

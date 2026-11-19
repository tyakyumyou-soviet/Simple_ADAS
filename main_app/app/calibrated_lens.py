"""同一画角の解像度変更に対応する魚眼校正。"""
import json
import os
from pathlib import Path
from shared_frame import RawFrame


def same_camera(recorded, device):
    """同じ実デバイスの別名を許可し、確認できない別パスは拒否する。"""
    if not recorded or not device:
        return False
    if recorded == device:
        return True
    try:
        return os.path.samefile(recorded, device)
    except OSError:
        return False


def profile_for(role, device):
    path = Path(__file__).parent / 'calibration' / (role + '.json')
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    if not same_camera(data.get('camera_device'), device):
        return None
    return data


def from_environment(role, environ):
    if environ.get('LENS_' + role.upper() + '_ENABLED') != '1':
        return None
    data = profile_for(role, environ.get(role.upper() + '_DEVICE', ''))
    return CalibratedLens(data, role) if data else None


class CalibratedLens:
    def __init__(self, data, role=None):
        import numpy as np
        self.role = role or "unknown"
        self.size = tuple(data['image_size'])
        self.K = np.asarray(data['K'], dtype=np.float64)
        self.D = np.asarray(data['D'], dtype=np.float64).reshape(4, 1)
        if self.K.shape != (3, 3) or not np.isfinite(self.K).all() or not np.isfinite(self.D).all():
            raise ValueError('校正データが不正です')
        self.maps = {}
        self.warned = set()

    def camera_matrix(self, size):
        width, height = size
        base_w, base_h = self.size
        # 多くのカメラは16:9モードを4:3センサーの中央切り出しで作る。
        # 校正時の画角を保ったまま縮尺し、中央切り出し分だけ主点を移動する。
        K = self.K.copy()
        scale = max(width / base_w, height / base_h)
        K[0, :] *= scale
        K[1, :] *= scale
        K[0, 2] -= (base_w * scale - width) / 2
        K[1, 2] -= (base_h * scale - height) / 2
        return K

    def apply(self, frame):
        import cv2
        import numpy as np
        size = (frame.width, frame.height)
        if size not in self.maps:
            try:
                K = self.camera_matrix(size)
            except ValueError as exc:
                if size not in self.warned:
                    print(f'[魚眼補正未適用:{self.role}] ' + str(exc) + '。元映像を使用します。', flush=True)
                    self.warned.add(size)
                return frame
            # balance=1 は元の周辺視野を最大限残す。端の黒い余白は
            # 検出対象を切り捨てるより安全で、画面側で扱える。
            P = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(K, self.D, size, np.eye(3), balance=1.0)
            self.maps[size] = cv2.fisheye.initUndistortRectifyMap(K, self.D, np.eye(3), P, size, cv2.CV_16SC2)
        image = np.frombuffer(frame.pixels, np.uint8).reshape(frame.height, frame.width, 3)
        result = cv2.remap(image, *self.maps[size], cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        return RawFrame(frame.width, frame.height, result.tobytes(), frame.timestamp_ns, frame.sequence)

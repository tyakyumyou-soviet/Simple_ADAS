"""解析幅に足りる実カメラの取得モードを選ぶ。"""
import re
import subprocess


def supported_sizes(device):
    try:
        result = subprocess.run(['v4l2-ctl','-d',device,'--list-formats-ext'],capture_output=True,text=True,timeout=2,check=True)
        # 同じデバイスでも形式によって対応サイズが違うためMJPEGのみ参照。
        text = result.stdout.split("'MJPG'",1)[1].split("\n\t[",1)[0]
        return {(int(w),int(h)) for w,h in re.findall(r'Size:\s*Discrete\s+(\d+)x(\d+)',text)}
    except (OSError,subprocess.SubprocessError,IndexError):
        return set()


def capture_size(width, height, process_width, supported):
    target = max(width,process_width or width)
    if supported:
        same = [(w,h) for w,h in supported if w*height == h*width]
        adequate = [(w,h) for w,h in same if w >= target]
        if adequate:return min(adequate)
        if same:return max(same)
        return width,height
    return target, max(1,round(target*height/width))


def parse_modes(output):
    """v4l2-ctl の離散MJPEG/YUYVモードを幅・高さ・FPS・形式で返す。"""
    modes = []
    fmt = None
    size = None
    stepwise = False
    for line in output.splitlines():
        match = re.search(r"\[\d+\]:\s*'([^']+)'", line)
        if match:
            fmt = {'MJPG': 'mjpeg', 'YUYV': 'yuyv422'}.get(match.group(1))
            size = None
            continue
        if fmt and 'Size: Stepwise' in line:
            stepwise = True
        match = re.search(r'Size:\s*Discrete\s+(\d+)x(\d+)', line)
        if fmt and match:
            size = (int(match.group(1)), int(match.group(2)))
            modes.append((size[0], size[1], None, fmt))
            continue
        match = re.search(r'\(([\d.]+)\s+fps\)', line)
        if fmt and size and match:
            modes.append((size[0], size[1], float(match.group(1)), fmt))
    # 連続解像度は列挙されていないため、未対応と断定しない。
    if stepwise:
        return None
    known = {(w,h,fmt) for w,h,rate,fmt in modes if rate is not None}
    return [m for m in modes if m[2] is not None or (m[0],m[1],m[3]) not in known]


def supported_modes(device):
    try:
        output = subprocess.run(['v4l2-ctl', '-d', device, '--list-formats-ext'], capture_output=True, text=True, timeout=2, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_modes(output)


def closest_mode(width, height, fps, modes):
    if modes is None:
        return (width, height, float(fps), 'mjpeg')
    if not modes:
        return None
    # 解像度差を基準に、FPS差を同じ比率の尺度で加算。完全同点ではMJPEGを優先。
    def score(mode):
        w, h, rate, fmt = mode
        effective = fps if rate is None else rate
        error = abs(w-width)/width + abs(h-height)/height + abs(effective-fps)/fps
        return (error, fmt != 'mjpeg', abs(w-width)+abs(h-height), -effective)
    w, h, rate, fmt = min(modes, key=score)
    return (w, h, float(fps if rate is None else rate), fmt)

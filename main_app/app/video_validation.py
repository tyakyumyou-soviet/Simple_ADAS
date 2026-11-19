import json
import subprocess
from pathlib import Path


def validate_video(path):
    path = Path(path)
    if not path.is_file(): raise ValueError('動画ファイルが見つかりません')
    try:
        result = subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,codec_name','-of','json',str(path)],capture_output=True,text=True,timeout=8,check=True)
        stream = json.loads(result.stdout)['streams'][0]
        if min(int(stream['width']),int(stream['height'])) <= 0:raise ValueError()
        subprocess.run(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0','-frames:v','1','-an','-f','null','-'],capture_output=True,timeout=8,check=True)
    except (OSError,subprocess.SubprocessError,ValueError,KeyError,IndexError) as exc:
        raise ValueError('動画の映像を読み取れません。別のファイルを選んでください') from exc

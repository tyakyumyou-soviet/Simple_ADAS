"""連続入力を一つのFFmpegプロセスでMP4ラップへ分割する。"""
from __future__ import annotations

from calibrated_lens import from_environment
from shared_frame import RawFrame
import csv
import json
import os
import re
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Segment:
    path: Path
    start: float
    end: float


class SegmentCapture:
    """on_segmentは完成したファイルについて監視スレッドから一度ずつ呼ばれる。"""

    def __init__(self, directory: Path, input_args: list[str], on_segment: Callable[[Segment], None],
                 on_error: Callable[[str], None], *, role: str, fps: float = 30,
                 segment_seconds: float = 600, bitrate: str = "3M", codec: str = "libx264",
                 on_preview: Callable[[bytes], None] | None = None, preview_fps: float = 10,
                 preview_only: bool = False, audio_args: list[str] | None = None,
                 audio_input_index: int | None = None, wallclock_input: bool = True, preview_width: int = 320,
                 lens_correction: tuple[float, float] | None = None, expected_eof=False, on_eof=None):
        if role not in ("front", "rear") or fps <= 0 or segment_seconds <= 0:
            raise ValueError("録画設定が不正です")
        self.directory = Path(directory).resolve()
        self.input_args = list(input_args)
        self._calibrated_lens = from_environment(role, os.environ) if 'v4l2' in self.input_args else None
        self._timestamped_preview = on_preview is not None and 'v4l2' in self.input_args
        self._lens_requested = 'v4l2' in self.input_args and os.environ.get('LENS_'+role.upper()+'_ENABLED') == '1'
        self._lens_reported_size = None
        self.wallclock_input = wallclock_input
        self.audio_args = list(audio_args) if audio_args else None
        self.audio_input_index = (1 if self.audio_args else audio_input_index)
        if self.audio_input_index not in (None, 0, 1):
            raise ValueError("音声入力番号が不正です")
        if preview_only and self.audio_input_index is not None:
            raise ValueError("プレビュー専用時に音声は録音できません")
        self.on_segment = on_segment
        self.on_error = on_error
        self.role = role
        self.fps = fps
        self.segment_seconds = segment_seconds
        self.bitrate = bitrate
        self.codec = codec
        self.on_preview = on_preview
        self.preview_only = preview_only
        if preview_only and on_preview is None:
            raise ValueError("プレビュー受信先が必要です")
        self.preview_fps = preview_fps
        if not 160 <= int(preview_width) <= 1280:
            raise ValueError("プレビュー解像度が不正です")
        self.preview_width = int(preview_width)
        if lens_correction is not None and (len(lens_correction) != 2 or any(not -1 <= float(x) <= 1 for x in lens_correction)):
            raise ValueError("魚眼補正値が不正です")
        self.expected_eof = expected_eof
        self.on_eof = on_eof
        self.lens_correction = lens_correction
        if on_preview is not None and preview_fps <= 0:
            raise ValueError("プレビューFPSが不正です")
        self._preview_queue = queue.Queue(maxsize=1)
        self._preview_reader = None
        self._preview_consumer = None
        self.session = f"{role}_{time.time_ns()}_{uuid.uuid4().hex[:12]}"
        self.list_path = self.directory / ("." + self.session + ".csv")
        self.pattern = self.directory / (self.session + "_%09d.mp4")
        self._process = None
        self._thread = None
        self._log = None
        self._processed: set[str] = set()
        self._stopping = threading.Event()
        self._failure = None
        self._last_preview_monotonic = None
        self.started_wall_ns = None
        self.started_monotonic_ns = None
        self.input_start_ns = None
        self._timeline_origin_ns = None
        self._timeline_lock = threading.Lock()

    def command(self) -> list[str]:
        # 固定GOPと強制キーフレームで、セグメントの境界を再生可能にする。
        command = ["ffmpeg", "-hide_banner", "-loglevel", "info", "-nostats"]
        if "v4l2" in self.input_args:
            # 遅れて溜まったフレームを順番に処理し続けないよう、入力待ちを最小にする。
            command += ["-fflags", "nobuffer", "-thread_queue_size", "1"]
        if self._timestamped_preview:
            # V4L2のカーネル取得時刻をUnix時刻で保持し、受信時刻で置き換えない。
            command += ["-copyts"]
        if not self.preview_only and self.wallclock_input and not self._timestamped_preview:
            command += ["-use_wallclock_as_timestamps", "1"]
        # MJPEGのフレーム並列デコードは次フレーム待ちを生む。
        if "mjpeg" in self.input_args:
            command += ["-threads", "1"]
        if self._timestamped_preview and '-timestamps' not in self.input_args:
            command += ["-timestamps", "abs"]
        command += self.input_args
        if self.audio_args:
            if self.wallclock_input:
                command += ["-use_wallclock_as_timestamps", "1"]
            command += self.audio_args
        if not self.preview_only:
            command += ["-copyts", "-start_at_zero", "-map", "0:v:0"]
            if self.audio_input_index is not None:
                audio_filter = ("" if self.wallclock_input else "asetpts=PTS-STARTPTS,") + "lowpass=f=8000,aresample=async=1"
                command += ["-map", f"{self.audio_input_index}:a:0", "-c:a", "aac", "-b:a", "64k", "-ar", "48000",
                            "-af", audio_filter]
            if self.expected_eof and self.audio_input_index is not None:
                # 検証動画の終端で、終わりのないマイク入力を待たずに録画を確定する。
                command += ["-shortest"]
            command += ["-c:v", self.codec, "-preset", "ultrafast",
                        "-b:v", self.bitrate, "-pix_fmt", "yuv420p", "-g", str(max(1, round(self.fps))),
                        "-force_key_frames", f"expr:gte(t,n_forced*{self.segment_seconds})",
                        "-f", "segment", "-segment_time", str(self.segment_seconds),
                        "-segment_format", "mp4", "-reset_timestamps", "1",
                        "-segment_list", str(self.list_path), "-segment_list_type", "csv", str(self.pattern)]
        if self.on_preview is not None:
            # fpsフィルターは次のフレームを待つため、間引きは受信したフレームで直ちに行う。
            # 入力FPSは暗所の自動露出などで要求値を下回る。フレーム番号で間引くと
            # 低FPS時にも不要に半減するため、入力タイムスタンプ間隔で制御する。
            interval = max(0.0, 1.0 / self.preview_fps - 0.001)
            filters = f"select=isnan(prev_selected_t)+gte(t-prev_selected_t\\,{interval:.6f}),scale=min(iw\\,{self.preview_width}):-2"
            if self.lens_correction is not None and any(self.lens_correction):
                k1, k2 = self.lens_correction
                filters += f",lenscorrection=cx=0.5:cy=0.5:k1={float(k1):.6f}:k2={float(k2):.6f}:i=bilinear"
            if self._timestamped_preview:
                command += ["-map", "0:v:0", "-an", "-vf", filters, "-fps_mode", "passthrough",
                            "-c:v", "rawvideo", "-pix_fmt", "rgb24", "-threads", "1",
                            "-flush_packets", "1", "-f", "nut", "pipe:1"]
            else:
                command += ["-map", "0:v:0", "-an", "-vf", filters,
                            "-fps_mode", "passthrough", "-c:v", "ppm", "-pix_fmt", "rgb24", "-threads", "1",
                            "-flush_packets", "1", "-f", "image2pipe", "pipe:1"]
        return command

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("この録画セッションは既に開始しています")
        self.directory.mkdir(parents=True, exist_ok=True)
        self._log = tempfile.TemporaryFile(mode="w+b")
        try:
            self.started_wall_ns = time.time_ns()
            self.started_monotonic_ns = time.monotonic_ns()
            if not self.wallclock_input:
                self.input_start_ns = self.started_wall_ns
            command = self.command()
            if sys.platform.startswith("linux"):
                command = [sys.executable, str(Path(__file__).with_name("parent_exec.py")), str(os.getpid()), *command]
            self._process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE if self.on_preview else subprocess.DEVNULL,
                                             stderr=self._log)
        except Exception:
            self._log.close()
            self._log = None
            raise
        if self.on_preview:
            self._preview_reader = threading.Thread(target=self._read_preview, name=f"preview-read-{self.role}", daemon=True)
            self._preview_consumer = threading.Thread(target=self._consume_preview, name=f"preview-use-{self.role}", daemon=True)
            self._preview_reader.start()
            self._preview_consumer.start()
        self._thread = threading.Thread(target=self._monitor, name=f"segment-{self.role}", daemon=True)
        self._thread.start()

    def _read_preview(self) -> None:
        if self._timestamped_preview:
            self._read_timestamped_preview()
            return
        stream = self._process.stdout
        while True:
            magic = stream.readline()
            if not magic:
                break
            if magic.strip() != b'P6':
                self.on_error('非圧縮プレビューのヘッダーが不正です')
                return
            dimensions = stream.readline()
            while dimensions.startswith(b'#'):
                dimensions = stream.readline()
            try:
                width, height = map(int, dimensions.split())
                if stream.readline().strip() != b'255' or min(width, height) <= 0 or width*height*3 > 31*1024*1024:
                    raise ValueError()
            except ValueError:
                self.on_error('非圧縮プレビューの寸法が不正です')
                return
            size = width*height*3
            data = bytearray()
            while len(data) < size:
                chunk = stream.read(size-len(data))
                if not chunk:
                    return
                data.extend(chunk)
            self._last_preview_monotonic = time.monotonic()
            frame = RawFrame(width, height, bytes(data), time.time_ns(), time.monotonic_ns())
            try:
                self._preview_queue.put_nowait(frame)
            except queue.Full:
                try:
                    self._preview_queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._preview_queue.put_nowait(frame)
                except queue.Full:
                    pass

    def _read_timestamped_preview(self) -> None:
        try:
            import av
            container = av.open(self._process.stdout, format='nut', mode='r', buffer_size=4096,
                                options={'probesize': '32', 'analyzeduration': '0'})
            for decoded in container.decode(video=0):
                if decoded.pts is None or decoded.time_base is None:
                    self.on_error(f'{self.role}カメラの撮影時刻を取得できません')
                    continue
                stamp = int(decoded.pts * decoded.time_base * 1_000_000_000)
                # 録画出力の -start_at_zero は同じ入力から作るプレビューPTSも相対化する。
                # FFmpegの入力開始時刻を足して、共有フレームにはカメラ時刻を記録する。
                if stamp < 10_000_000_000 and not self.preview_only:
                    origin = self._read_input_start()
                    if origin is None:
                        self.on_error(f'{self.role}カメラの撮影時刻の基準を取得できません')
                        continue
                    stamp += origin
                now_ns = time.time_ns()
                if stamp <= 0 or stamp > now_ns + 1_000_000_000:
                    self.on_error(f'{self.role}カメラの撮影時刻が不正です (source={stamp}, clock={now_ns})')
                    continue
                data = decoded.to_ndarray(format='rgb24').tobytes()
                frame = RawFrame(decoded.width, decoded.height, data, stamp, time.monotonic_ns())
                self._last_preview_monotonic = time.monotonic()
                try:
                    self._preview_queue.put_nowait(frame)
                except queue.Full:
                    try:
                        self._preview_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._preview_queue.put_nowait(frame)
                    except queue.Full:
                        pass
            container.close()
        except Exception as exc:
            if self._process.poll() is None:
                self.on_error(f'{self.role}撮影時刻付き映像を読めません: {exc}')

    def _consume_preview(self) -> None:
        while self._process.poll() is None or not self._preview_queue.empty():
            try:
                frame = self._preview_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                result = self._calibrated_lens.apply(frame) if self._calibrated_lens else frame
                size = (frame.width, frame.height)
                if self._lens_requested and size != self._lens_reported_size:
                    if self._calibrated_lens and size in self._calibrated_lens.maps:
                        print(f'[魚眼補正適用:{self.role}] 校正データを適用中', flush=True)
                    elif self._calibrated_lens is None and self.lens_correction and any(self.lens_correction):
                        print(f'[魚眼補正適用:{self.role}] 手動補正を適用中', flush=True)
                    elif self._calibrated_lens is None:
                        print(f'[魚眼補正未適用:{self.role}] このカメラの校正データがありません', flush=True)
                    self._lens_reported_size = size
                self.on_preview(result)
            except Exception as exc:
                # プレビューの障害で録画を停止しない。
                self.on_error(f"{self.role}プレビューエラー: {exc}")
                return

    def _read_input_start(self) -> int | None:
        if self.input_start_ns is not None:
            return self.input_start_ns
        if self._log is None:
            return None
        data = os.pread(self._log.fileno(), 131072, 0)
        match = re.search(rb'Input #0,.*?Duration:\s*[^,]+,\s*start:\s*([0-9]+(?:\.[0-9]+)?)', data, re.S)
        if not match:
            return None
        try:
            self.input_start_ns = int(Decimal(match.group(1).decode('ascii')) * 1_000_000_000)
        except (InvalidOperation, ValueError):
            return None
        return self.input_start_ns

    def _ensure_timeline(self, first_segment: Path) -> int:
        with self._timeline_lock:
            if self._timeline_origin_ns is not None:
                return self._timeline_origin_ns
            source_start = self._read_input_start()
            if source_start is None:
                raise RuntimeError("カメラ映像の開始時刻を確認できません")
            try:
                result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=start_time", "-of", "json", str(first_segment)],
                    capture_output=True, text=True, timeout=5, check=True)
                data = json.loads(result.stdout)
                relative_ns = int(Decimal(data["streams"][0]["start_time"]) * 1_000_000_000)
            except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, InvalidOperation) as exc:
                raise RuntimeError("録画ラップの開始時刻を確認できません") from exc
            self._timeline_origin_ns = source_start - relative_ns
            return self._timeline_origin_ns

    def completed_segments(self) -> list[Segment]:
        self._read_input_start()
        if not self.list_path.exists():
            return []
        try:
            with self.list_path.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.reader(stream))
        except (OSError, csv.Error):
            return []
        segments = []
        origin = None
        for row in rows:
            if len(row) != 3:
                continue
            try:
                name, start, end = row[0], float(row[1]), float(row[2])
            except ValueError:
                continue  # 書き込み途中の行は次回読む
            if Path(name).name != name or not name.startswith(self.session + "_"):
                raise RuntimeError("録画セグメント一覧のパスが不正です")
            path = self.directory / name
            if end <= start:
                raise RuntimeError(f"録画時間が不正です: {name}")
            if not path.is_file():
                if name in self._processed:
                    continue  # 保存済み・通知済みの古いラップは容量整理で消える。
                raise RuntimeError(f"完成した録画ファイルを確認できません: {name}")
            if origin is None:
                origin = self._ensure_timeline(path)
            segments.append(Segment(path, origin / 1_000_000_000 + start,
                                    origin / 1_000_000_000 + end))
        return segments

    def current_segment_path(self) -> Path | None:
        if not self.running:
            return None
        paths = sorted(self.directory.glob(self.session + "_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].mp4"))
        if not paths:
            return None
        completed = {segment.path for segment in self.completed_segments()}
        # 境界で現行ファイルがまだ作られていない場合は推測しない。
        return None if paths[-1] in completed else paths[-1]

    def _consume(self) -> None:
        for segment in self.completed_segments():
            name = segment.path.name
            if name not in self._processed:
                self.on_segment(segment)
                self._processed.add(name)

    def _monitor(self) -> None:
        try:
            while self._process.poll() is None:
                self._consume()
                if (self.on_preview is not None and self._last_preview_monotonic is not None
                        and not self._stopping.is_set()
                        and time.monotonic() - self._last_preview_monotonic > 3):
                    raise RuntimeError(f"{self.role}の映像更新が停止しました")
                time.sleep(0.1)
            self._consume()
            result = self._process.returncode
            if result != 0:
                self._log.seek(0)
                error = self._log.read().decode(errors="replace")[-4000:]
                raise RuntimeError(f"{self.role}録画が終了しました ({result}): {error}")
            if not self._stopping.is_set() and self.expected_eof:
                if self.on_eof: self.on_eof()
                return
            if not self._stopping.is_set():
                raise RuntimeError(f"{self.role}録画が予期せず終了しました")
        except Exception as exc:
            self._failure = str(exc)
            try:
                self.on_error(self._failure)
            finally:
                if self._process.poll() is None:
                    self._process.terminate()

    def stop(self, timeout: float = 10) -> None:
        if self._process is None:
            return
        self._stopping.set()
        if self._process.poll() is None:
            try:
                self._process.stdin.write(b"q\n")
                self._process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
            self._failure = "録画停止がタイムアウトし、動画を確定できませんでした"
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            raise RuntimeError("録画監視の停止を確認できません")
        if self._preview_reader:
            self._preview_reader.join(timeout=timeout)
            if self._preview_reader.is_alive():
                raise RuntimeError("プレビュー入力の停止を確認できません")
        if self._preview_consumer:
            self._preview_consumer.join(timeout=timeout)
            if self._preview_consumer.is_alive():
                raise RuntimeError("プレビュー処理の停止を確認できません")
        if self._process.stdout:
            self._process.stdout.close()
        if self._process.stdin:
            self._process.stdin.close()
        if self._log:
            self._log.close()
        if self._failure:
            raise RuntimeError(self._failure)

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

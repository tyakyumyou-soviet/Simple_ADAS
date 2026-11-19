"""既存の録画・転送プロセスをUIから安全に操作する実行時制御。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from video_validation import validate_video
from capture_geometry import closest_mode, supported_modes
from transfer_service import TransferSession
from lens_settings import fill_lens_environment
from hotspot import WifiHotspot
from sensor_hub import SensorHub
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QSettings, QThread, QTimer, Signal


class _ProcessAdapter:
    """転送時にQProcessを停止し、転送前に動いていたものだけ復帰する。"""
    def __init__(self, process, start, stop):
        self.process = process
        self._start = start
        self._stop = stop

    def is_running(self):
        return self.process.state() != QProcess.ProcessState.NotRunning

    def stop(self):
        if not self._stop():
            raise RuntimeError("安全停止を確認できません")

    def start(self):
        if not self._start():
            raise RuntimeError("起動を要求できません")
        if self.process.state() == QProcess.ProcessState.Starting and not self.process.waitForStarted(5000):
            raise RuntimeError("プロセス起動を確認できません")


class _NetworkWorker(QThread):
    result = Signal(object, object)

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.action = action

    def run(self):
        try:
            self.result.emit(self.action(), None)
        except Exception as exc:
            self.result.emit(None, str(exc))


class RuntimeController(QObject):
    status_changed = Signal(str)
    log_changed = Signal(str)
    transfer_changed = Signal(bool)
    recorder_changed = Signal(bool)
    recorder_ready_changed = Signal(bool)
    analysis_camera_changed = Signal(str)
    transfer_phase_changed = Signal(str)
    adas_changed = Signal(bool)
    adas_result = Signal(object)
    preview_changed = Signal(bool)
    video_finished = Signal()

    def __init__(self, config_path: Path, parent=None):
        super().__init__(parent)
        # 相対パスの設定でも、作業ディレクトリを二重に連結しない。
        self.config_path = Path(config_path).expanduser().resolve()
        self.config = self._load_config()
        self.embedded_transfer = None
        self.transfer_url = ""
        self.transfer_wifi = None
        self.hotspot = None
        self._network_worker = None
        self.analysis_camera = "front"
        self.video_ended_pending = False
        self.video_recorder_active = False
        self.video_role = None
        self.video_path = None
        self.adas_adapter = None
        self.closing = False
        self.transfer_phase = "idle"
        self.services = {}
        self.sensor_hub = SensorHub(self)
        self.sensor_hub.impact.connect(lambda timestamp: self.request_event("impact", timestamp))
        self.services["センサー"] = self.sensor_hub
        self.resume_services = {}
        self.resume_errors = []
        self.resume_expected = 0
        self.recorder_output_buffer = ""
        self.recorder_last_error = ""
        self.recorder_stop_after_start = False
        self.preview_dir = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir())) / f"vehicle-preview-{os.getuid()}"
        self.restore_watchdog = QTimer(self)
        self.restore_watchdog.setSingleShot(True)
        self.restore_watchdog.setInterval(20000)
        self.restore_watchdog.timeout.connect(self._restore_timed_out)
        self.transfer_expiry = QTimer(self)
        self.transfer_expiry.setSingleShot(True)
        self.transfer_expiry.timeout.connect(self.end_transfer)
        self.recorder = QProcess(self)
        self.transfer = QProcess(self)
        self.preview = QProcess(self)
        self.adas = QProcess(self)
        self.preview_requested = False
        self.preview_intentional_stop = False
        self.adas_intentional_stop = False
        self.adas_output_buffer = ""
        self._preview_adapter = _ProcessAdapter(self.preview, self.start_preview, self.stop_preview)
        self._adas_process_adapter = _ProcessAdapter(self.adas, self.start_adas, self.stop_adas)
        self.preview.errorOccurred.connect(lambda error: self._auxiliary_error("映像", self.preview, error))
        self.adas.errorOccurred.connect(lambda error: self._auxiliary_error("危険予知", self.adas, error))
        self.preview.started.connect(lambda: self.preview_changed.emit(True))
        self.preview_output_buffer = ""
        self.preview.finished.connect(self._preview_finished)
        self.preview.readyReadStandardOutput.connect(self._read_preview_output)
        self.preview.readyReadStandardError.connect(lambda: self.log_changed.emit(bytes(self.preview.readAllStandardError()).decode(errors="replace").strip()))
        self.adas.started.connect(lambda: self.adas_changed.emit(True))
        self.adas.finished.connect(self._adas_finished)
        self.adas.readyReadStandardOutput.connect(self._read_adas_output)
        self.adas.readyReadStandardError.connect(lambda: self.log_changed.emit(bytes(self.adas.readAllStandardError()).decode(errors="replace").strip()))
        self.transfer_requested = False
        self.restart_recorder_after_transfer = False
        self.recorder_ready = set()
        self.recorder.started.connect(self._recorder_started)
        self.recorder.readyReadStandardOutput.connect(self._read_recorder_output)
        self.recorder.readyReadStandardError.connect(self._read_recorder_error)
        self.recorder.errorOccurred.connect(lambda error: self._process_error("録画", self.recorder, error))
        self.recorder.finished.connect(self._recorder_finished)
        self.transfer.started.connect(lambda: (self.transfer_changed.emit(True), self.status_changed.emit("転送サーバー起動中")))
        self.transfer.readyReadStandardOutput.connect(self._read_transfer_output)
        self.transfer.readyReadStandardError.connect(self._read_transfer_error)
        self.transfer.errorOccurred.connect(lambda error: self._process_error("転送", self.transfer, error))
        self.transfer.finished.connect(self._transfer_finished)

    def _load_config(self) -> dict:
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            self.log_changed.emit(f"設定ファイルを読めません: {exc}")
            return {}

    def _storage_root(self) -> Path:
        root = Path(self.config.get("storage_path", "../sources/dashcam/videos")).expanduser()
        if not root.is_absolute():
            root = (self.config_path.parent / root).resolve()
        return root / "video-test" if self.video_role else root

    def _command(self, key: str) -> list[str]:
        if key == "recorder_command" and self.config.get("recording_backend") == "segmented":
            root = self._storage_root()
            command = [sys.executable, str(Path(__file__).with_name("dashcam_service.py")),
                       "--media-dir", str(root), "--preview-dir", str(self.preview_dir)]
            if self.config.get("development_tools") and self.config.get("recording_test_source"):
                command.extend(["--test-source", "--segment-seconds", "2", "--fps", "5", "--size", "160x120"])
            else:
                env, _ = self._camera_environment()
                width, height = int(env.value('ADAS_CAMERA_WIDTH')), int(env.value('ADAS_CAMERA_HEIGHT'))
                command.extend(['--size', f'{width}x{height}', '--fps', env.value('ADAS_CAMERA_FPS')])
                quality = []
                for role, label in (('front','前'), ('rear','後')):
                    if env.value(role.upper() + '_DEVICE') and role != self.video_role:
                        w = int(env.value('ADAS_' + role.upper() + '_WIDTH') or width)
                        h = int(env.value('ADAS_' + role.upper() + '_HEIGHT') or height)
                        if w < 1280 or h < 720:
                            quality.append(f'{label}{w}×{h}')
                if not quality and not env.value('FRONT_DEVICE') and not env.value('REAR_DEVICE') and (width < 1280 or height < 720):
                    quality.append(f'{width}×{height}')
                if quality:
                    self.log_changed.emit('[録画画質警告] ' + '・'.join(quality) + 'は要件の720p以上には未達です')
                else:
                    self.log_changed.emit('[録画画質適合]')
            return command
        value = self.config.get(key, [])
        if isinstance(value, str):
            return [value] if value else []
        return [str(part) for part in value] if isinstance(value, list) else []

    def command_available(self, key: str) -> bool:
        if key == "transfer_command":
            return True
        command = self._command(key)
        if not command:
            return False
        program = Path(command[0]).expanduser()
        if not program.is_absolute():
            program = (self.config_path.parent / program).resolve()
        return program.is_file() and program.stat().st_mode & 0o111 != 0

    @staticmethod
    def _child_command(program: str, arguments: list[str]) -> tuple[str, list[str]]:
        if sys.platform.startswith("linux"):
            wrapper = str(Path(__file__).with_name("parent_exec.py"))
            return sys.executable, [wrapper, str(os.getpid()), program, *arguments]
        return program, arguments

    def _launch(self, process: QProcess, command: list[str], cwd_key: str) -> bool:
        if not command:
            return False
        program = Path(command[0]).expanduser()
        if not program.is_absolute():
            program = (self.config_path.parent / program).resolve()
        if not program.is_file():
            self.log_changed.emit(f"実行ファイルがありません: {program}")
            return False
        working = Path(self.config.get(cwd_key, self.config_path.parent)).expanduser()
        if not working.is_absolute():
            working = (self.config_path.parent / working).resolve()
        process.setWorkingDirectory(str(working))
        child_program, child_arguments = self._child_command(str(program), command[1:])
        process.setProgram(child_program)
        process.setArguments(child_arguments)
        process.start()
        return True

    def _auxiliary_error(self, label, process, error) -> None:
        self.log_changed.emit(f"{label}プロセスエラー: {process.errorString()} ({error.name})")
        if label == "危険予知":
            self.adas_changed.emit(False)
            self.adas_result.emit({"type": "error", "message": process.errorString(), "alerts": []})
        else:
            self.preview_changed.emit(False)

    def _profile_value(self, section: str, key: str, default):
        path = Path.home() / ".config/VehicleIntegration/adas-profile.json"
        try:
            if path.is_file():
                values = json.loads(path.read_text(encoding="utf-8"))
                value = values.get(section, {}).get(key)
                if value is not None:
                    return value
            import yaml
            project = Path(self.config.get("adas_project", Path(__file__).resolve().parent.parent / "sources/collision_prediction")).expanduser()
            current = project / "config/pi_async_ai_hat_2.yaml"
            visited = set()
            while current.is_file() and current.resolve() not in visited:
                visited.add(current.resolve())
                values = yaml.safe_load(current.read_text(encoding="utf-8")) or {}
                value = values.get(section, {}).get(key)
                if value is not None:
                    return value
                parent = values.get("extends")
                if not parent:
                    break
                current = current.parent / parent
        except (OSError, ValueError, TypeError, AttributeError, ImportError):
            pass
        return default

    def _preview_width(self) -> int:
        try:
            width = int(self._profile_value("ui", "max_process_width", 320) or 1280)
            return min(1280, max(160, width))
        except (ValueError, TypeError):
            return 320

    def _camera_environment(self) -> tuple[QProcessEnvironment, dict[str, str]]:
        preferences = QSettings("VehicleIntegration", "MainApp")
        devices = {role: preferences.value("camera_device_" + role, "", str) for role in ("front", "rear")}
        environment = QProcessEnvironment.systemEnvironment()
        fill_lens_environment(environment, preferences)
        environment.insert("ADAS_PREVIEW_WIDTH", str(self._preview_width()))
        for key, default, upper in (("camera_width", 640, 3840), ("camera_height", 480, 2160), ("camera_fps", 15, 120)):
            try:
                value = int(self._profile_value("input", key, default) or default)
                value = min(upper, max(1, value))
            except (TypeError, ValueError):
                value = default
            environment.insert("ADAS_" + key.upper(), str(value))
        width = int(environment.value('ADAS_CAMERA_WIDTH'))
        height = int(environment.value('ADAS_CAMERA_HEIGHT'))
        try:
            requested = int(self._profile_value('ui', 'max_process_width', width) or width)
        except (ValueError, TypeError):
            requested = width
        target_w = max(width, requested)
        target_h = max(1, round(target_w * height / width))
        fps = float(environment.value('ADAS_CAMERA_FPS'))
        selected = {}
        for role, device in devices.items():
            modes = None
            if device and role != self.video_role and Path(device).exists() and sys.platform.startswith('linux'):
                modes = supported_modes(device)
                if modes is None:
                    self.log_changed.emit(f'[カメラ画質未確認:{role}] 対応モードを取得できません。指定値で起動を試みます')
            mode = closest_mode(target_w, target_h, fps, modes)
            if mode is None:
                environment.insert('ADAS_' + role.upper() + '_MODE_ERROR', '利用可能なMJPEG/YUYVモードがありません')
                continue
            w, h, rate, fmt = mode
            selected[role] = mode
            for key,value in [('WIDTH',w),('HEIGHT',h),('FPS',rate),('FORMAT',fmt)]:
                environment.insert('ADAS_' + role.upper() + '_' + key, str(value))
            environment.insert(role.upper() + '_DEVICE', device)
            if device and role != self.video_role and (w,h,rate)!=(target_w,target_h,fps):
                self.log_changed.emit(f'[カメラ画質差:{role}] 指定 {target_w}×{target_h} {fps:g}fps → 対応 {w}×{h} {rate:g}fps')
            elif device:
                self.log_changed.emit(f'[カメラ画質一致:{role}]')
        front = selected.get('front', (target_w,target_h,fps,'mjpeg'))
        environment.insert('ADAS_CAMERA_WIDTH', str(front[0]))
        environment.insert('ADAS_CAMERA_HEIGHT', str(front[1]))
        environment.insert('ADAS_CAMERA_FPS', str(front[2]))
        environment.insert('ADAS_PREVIEW_WIDTH', str(min(1280, max([target_w] + [m[0] for m in selected.values()]))))
        return environment, devices

    def _testing_sources(self) -> bool:
        return bool(self.config.get("development_tools") and self.config.get("recording_test_source"))

    def start_preview(self) -> bool:
        if self.closing:
            return False
        if self.preview.state() != QProcess.ProcessState.NotRunning:
            return True
        if self.recorder.state() != QProcess.ProcessState.NotRunning:
            return False  # 録画サービスが同じプレビューを供給する
        environment, devices = self._camera_environment()
        for role, device in devices.items():
            error = environment.value('ADAS_' + role.upper() + '_MODE_ERROR')
            if device and role != self.video_role and error:
                self.status_changed.emit(('前' if role == 'front' else '後') + 'カメラ：' + error)
                return False
        active = [path for role, path in devices.items() if path and role != self.video_role]
        if self.video_role and self.video_path:
            active.append(str(self.video_path))
        if not self._testing_sources() and (not active or any(not Path(path).exists() for path in active)):
            self.log_changed.emit("カメラを詳細設定で指定してください")
            return False
        if len(active) == 2 and Path(active[0]).resolve() == Path(active[1]).resolve():
            self.log_changed.emit("前後に別のカメラを指定してください")
            return False
        command = [sys.executable, str(Path(__file__).with_name("preview_service.py")),
                   "--preview-dir", str(self.preview_dir)]
        if self._testing_sources():
            command.append("--test-source")
        if self.video_role and self.video_path:
            command += ["--video-role", self.video_role, "--video-path", str(self.video_path)]
        self.preview.setProcessEnvironment(environment)
        self.preview_intentional_stop = False
        self.preview_output_buffer = ""
        return self._launch(self.preview, command, "preview_working_directory")

    def stop_preview(self) -> bool:
        if self.preview.state() == QProcess.ProcessState.NotRunning:
            return True
        self.preview_intentional_stop = True
        if self.preview.state() == QProcess.ProcessState.Starting and not self.preview.waitForStarted(5000):
            return False
        self.preview.write(b"STOP\n")
        self.preview.closeWriteChannel()
        if not self.preview.waitForFinished(10000):
            self.log_changed.emit("カメラ映像の停止を確認できません")
            return False
        return self.preview.exitStatus() == QProcess.ExitStatus.NormalExit and self.preview.exitCode() == 0

    def start_adas(self) -> bool:
        if self.closing:
            return False
        if self.adas.state() != QProcess.ProcessState.NotRunning:
            return True
        _, devices = self._camera_environment()
        if (not self._testing_sources() and self.analysis_camera != self.video_role
                and (not devices[self.analysis_camera] or not Path(devices[self.analysis_camera]).exists())):
            self.status_changed.emit("解析するカメラを詳細設定で指定してください")
            return False
        if self.recorder.state() == QProcess.ProcessState.NotRunning and not self.start_preview():
            self.status_changed.emit("解析用のカメラ映像を開始できません")
            return False
        project = Path(self.config.get("adas_project", Path(__file__).resolve().parent.parent / "sources/collision_prediction")).expanduser().resolve()
        config = (Path(self.config["adas_config"]).expanduser().resolve()
                  if self.config.get("development_tools") and self.config.get("adas_config")
                  else (project / "config/pi_async_ai_hat_2.yaml").resolve())
        # 仮想環境のpythonはシンボリックリンクでも、そのパスで起動する必要がある。
        python = Path(self.config.get("adas_python", sys.executable)).expanduser().absolute()
        if not python.is_file() or not config.is_file() or not (project / "src/pipeline.py").is_file():
            self.status_changed.emit("危険予知プログラムまたは設定が見つかりません")
            return False
        command = [str(python), str(Path(__file__).with_name("adas_service.py")), "--project", str(project),
                   "--config", str(config), "--frame-dir", str(self.preview_dir), "--camera", self.analysis_camera]
        override_path = Path.home() / ".config/VehicleIntegration/adas-profile.json"
        if override_path.is_file():
            command += ["--overrides", str(override_path)]
        if QSettings("VehicleIntegration", "MainApp").value("adas_overlay", False, bool):
            command.append("--overlay")
        self.adas.setWorkingDirectory(str(project))
        child_program, child_arguments = self._child_command(command[0], command[1:])
        self.adas.setProgram(child_program)
        self.adas.setArguments(child_arguments)
        self.adas_intentional_stop = False
        self.adas_output_buffer = ""
        self.adas.start()
        self.status_changed.emit("危険予知を起動しています")
        return True

    def stop_adas(self) -> bool:
        if self.adas.state() == QProcess.ProcessState.NotRunning:
            return True
        self.adas_intentional_stop = True
        self.adas_result.emit({"type": "status", "status": "stopped", "alerts": []})
        if self.adas.state() == QProcess.ProcessState.Starting and not self.adas.waitForStarted(5000):
            return False
        self.adas.write(b"STOP\n")
        self.adas.closeWriteChannel()
        if not self.adas.waitForFinished(15000):
            self.log_changed.emit("危険予知の停止を確認できません")
            return False
        return self.adas.exitStatus() == QProcess.ExitStatus.NormalExit and self.adas.exitCode() == 0

    def _read_adas_output(self) -> None:
        self.adas_output_buffer += bytes(self.adas.readAllStandardOutput()).decode(errors="replace")
        lines = self.adas_output_buffer.split("\n")
        self.adas_output_buffer = lines.pop()
        for line in lines:
            if not line.startswith("ADAS_JSON "):
                if line.strip():
                    self.log_changed.emit(line)
                continue
            try:
                payload = json.loads(line[len("ADAS_JSON "):])
                if not isinstance(payload, dict):
                    raise ValueError("JSON形式が不正です")
            except (ValueError, json.JSONDecodeError) as exc:
                self.log_changed.emit(f"危険予知データエラー: {exc}")
                continue
            self.adas_result.emit(payload)
            if payload.get("type") == "error":
                self.status_changed.emit("危険予知エラー: " + str(payload.get("message", "不明")))

    def _adas_finished(self, code: int, _status) -> None:
        self.adas_changed.emit(False)
        self.adas_result.emit({"type": "status", "status": "stopped", "alerts": []})
        if not self.adas_intentional_stop:
            self.status_changed.emit(f"危険予知が終了しました ({code})")

    def _read_preview_output(self):
        self.preview_output_buffer += bytes(self.preview.readAllStandardOutput()).decode(errors='replace')
        lines = self.preview_output_buffer.split('\n')
        self.preview_output_buffer = lines.pop()
        for line in lines:
            self.log_changed.emit(line)
            if line.startswith('PREVIEW_JSON '):
                try:
                    if json.loads(line[13:]).get('status') == 'video_ended':
                        self.video_ended_pending = True
                        self.video_finished.emit()
                except (ValueError, AttributeError): pass

    def _preview_finished(self, code: int, _status) -> None:
        self._read_preview_output()
        self.preview_changed.emit(False)
        if self.video_ended_pending:
            return
        if not self.preview_intentional_stop:
            self.log_changed.emit(f"カメラ映像が終了しました ({code})")
            if self.video_role and not self.closing and self.transfer_phase == "idle":
                self.status_changed.emit("検証動画を再生できません。動画ファイルを確認してください")

    def start_recorder(self) -> bool:
        if self.closing:
            return False
        if self.recorder.state() != QProcess.ProcessState.NotRunning:
            return True
        self.recorder_stop_after_start = False
        self.recorder_ready.clear()
        self.recorder_ready_changed.emit(False)
        self.recorder_output_buffer = ""
        self.recorder_last_error = ""
        preferences = QSettings("VehicleIntegration", "MainApp")
        front = preferences.value("camera_device_front", "", str)
        rear = preferences.value("camera_device_rear", "", str)
        if self.video_role == "front" and self.video_path:
            front = str(self.video_path)
        elif self.video_role == "rear" and self.video_path:
            rear = str(self.video_path)
        test_source = self.config.get("development_tools") and self.config.get("recording_test_source")
        if not test_source and (not front or not rear or not Path(front).exists() or not Path(rear).exists()):
            self.status_changed.emit("前後のカメラを詳細設定で指定してください")
            return False
        if not test_source and Path(front).resolve() == Path(rear).resolve():
            self.status_changed.emit("前後に別のカメラを指定してください")
            return False
        environment, _ = self._camera_environment()
        for role, device in (('front', front), ('rear', rear)):
            error = environment.value('ADAS_' + role.upper() + '_MODE_ERROR')
            if device and role != self.video_role and error:
                self.status_changed.emit(('前' if role == 'front' else '後') + 'カメラ：' + error)
                return False
        if not self.stop_preview():
            self.status_changed.emit("録画前にカメラ映像を停止できません")
            return False
        if self.video_role and self.video_path:
            environment.insert("VIDEO_ROLE", self.video_role)
            environment.insert("VIDEO_PATH", str(self.video_path))
        environment.insert("FRONT_DEVICE", front)
        environment.insert("REAR_DEVICE", rear)
        self.recorder.setProcessEnvironment(environment)
        if not self._launch(self.recorder, self._command("recorder_command"), "recorder_working_directory"):
            self.status_changed.emit("録画プログラム未設定")
            return False
        self.status_changed.emit("録画プロセス起動待ち")
        return True

    def stop_recorder(self) -> bool:
        if self.transfer_phase not in {"idle", "error"}:
            self.status_changed.emit("転送処理の完了を待ってください")
            return False
        state = self.recorder.state()
        if state == QProcess.ProcessState.NotRunning:
            return True
        if state == QProcess.ProcessState.Starting:
            self.recorder_stop_after_start = True
            self.status_changed.emit("録画起動後に停止します")
            return True
        self.recorder.write(b"F\n")
        self.recorder.closeWriteChannel()
        self.status_changed.emit("録画を安全に停止しています")
        return True

    def request_event(self, cause: str, trigger_ns: int | None = None) -> bool:
        if cause not in {"manual", "impact"}:
            raise ValueError("不正なイベント原因")
        if (self.recorder.state() != QProcess.ProcessState.Running
                or self.recorder_ready != {"front", "rear"}):
            self.log_changed.emit("前後の録画準備が完了していないため、イベント保存を要求できません")
            return False
        code = "E" if cause == "manual" else "A"
        timestamp = time.time_ns() if trigger_ns is None else int(trigger_ns)
        if timestamp < 0:
            raise ValueError("不正なイベント発生時刻")
        line = f"{code} {timestamp}\n" if self.config.get("recording_backend") == "segmented" else f"{code}\n"
        self.recorder.write(line.encode("ascii"))
        self.log_changed.emit("手動イベント保存を要求しました" if cause == "manual" else "衝撃イベント保存を要求しました")
        return True

    def request_manual_event(self) -> bool:
        return self.request_event("manual")

    def _phase(self, phase, message):
        self.transfer_phase = phase
        self.transfer_phase_changed.emit(phase)
        self.status_changed.emit(message)

    def register_service(self, name, adapter):
        """Adapter contract: is_running(), stop(), start(); stop/start complete synchronously."""
        self.services[name] = adapter

    def begin_transfer(self) -> bool:
        if self.embedded_transfer or self.transfer_phase not in {"idle", "error"}:
            return False
        if self.recorder.state() == QProcess.ProcessState.Starting:
            self.status_changed.emit("録画起動処理の完了を待ってから転送してください")
            return False
        self.resume_services = {}
        self.resume_errors = []
        self.restart_recorder_after_transfer = self.recorder.state() == QProcess.ProcessState.Running
        self.resume_expected = int(self.restart_recorder_after_transfer)
        self._phase("preparing", "転送準備中：各機能を停止しています")
        services = dict(self.services)
        services["危険予知"] = self._adas_process_adapter
        services["カメラ映像"] = self._preview_adapter
        if self.adas_adapter is not None:
            services["AI"] = self.adas_adapter
        try:
            for name, adapter in services.items():
                if adapter.is_running():
                    self.resume_services[name] = adapter
                    self.resume_expected += 1
                    adapter.stop()
                    if adapter.is_running():
                        raise RuntimeError(f"{name}の停止を確認できません")
        except Exception as exc:
            self.log_changed.emit(str(exc))
            self.resume_errors.append(f"転送準備失敗: {exc}")
            self.restart_recorder_after_transfer = False  # recorder has not been stopped
            self._resume_after_transfer()
            return False
        self.transfer_requested = True
        if self.restart_recorder_after_transfer:
            self.status_changed.emit("転送準備中：録画を安全停止しています")
            self.recorder.write(b"F\n")
            self.recorder.closeWriteChannel()
        else:
            self._start_transfer()
        return True

    def set_video_source(self, role, video_path) -> bool:
        """録画ファイルを確定してから、選択側の入力を動画／実カメラへ切替える。"""
        if role not in (None, "front", "rear") or bool(role) != bool(video_path):
            raise ValueError("動画入力の指定が不正です")
        if video_path and not Path(video_path).is_file():
            self.status_changed.emit("動画ファイルが見つかりません")
            return False
        if video_path:
            try: validate_video(video_path)
            except ValueError as exc:
                self.status_changed.emit('検証動画を再生できません：' + str(exc))
                return False
        if self.closing or self.transfer_phase != "idle" or self.embedded_transfer or self.hotspot:
            self.status_changed.emit("転送・停止処理が終わってから動画入力を変更してください")
            return False
        was_adas = self.adas.state() != QProcess.ProcessState.NotRunning
        was_recording = (self.recorder.state() != QProcess.ProcessState.NotRunning
                         or (role is None and self.video_recorder_active))
        previous = self.video_role, self.video_path
        if was_adas and not self.stop_adas():
            self.status_changed.emit("危険予知の停止を確認できません")
            return False
        if was_recording and self.recorder.state() != QProcess.ProcessState.NotRunning:
            if not self.stop_recorder() or not self.recorder.waitForFinished(20000) or self.recorder.exitCode() != 0:
                self.status_changed.emit("録画ファイルを確定できず、入力を変更しませんでした")
                if was_adas: self.start_adas()
                return False
        if not self.stop_preview():
            self.status_changed.emit("カメラ映像の停止を確認できません")
            if was_recording: self.start_recorder()
            if was_adas: self.start_adas()
            return False
        self.video_ended_pending = False
        self.video_recorder_active = False
        self.video_role, self.video_path = role, Path(video_path).resolve() if video_path else None
        self.preview_requested = bool(role) or self.preview_requested
        started = self.start_recorder() if was_recording else self.start_preview() if self.preview_requested else True
        if not started:
            if role is None:
                if was_adas: self.start_adas()
                self.status_changed.emit("動画検証を終了しました。実カメラを確認してください")
                return True
            self.video_role, self.video_path = previous
            if was_recording: self.start_recorder()
            elif self.preview_requested: self.start_preview()
            if was_adas: self.start_adas()
            self.status_changed.emit("動画入力を開始できません。元の入力に戻しました")
            return False
        if was_adas and not self.start_adas():
            self.status_changed.emit("映像を切り替えました。危険予知は再試行します")
        else:
            self.status_changed.emit("動画をカメラ入力として使用中" if role else "実カメラに戻しました")
        return True

    def set_analysis_camera(self, camera):
        if camera not in {"front", "rear"}:
            raise ValueError(camera)
        self.analysis_camera = camera
        if self.adas.state() != QProcess.ProcessState.NotRunning:
            self.adas_result.emit({"type": "status", "status": "switching", "camera": camera, "alerts": []})
            self.adas.write((camera.upper() + "\n").encode())
        if self.adas_adapter is not None:
            self.adas_adapter.set_camera(camera)
        self.analysis_camera_changed.emit(camera)

    def _start_transfer(self) -> None:
        self.transfer_requested = False
        if self.config.get("transfer_network_mode", "lan") == "ap":
            try:
                self.hotspot = WifiHotspot(
                    device=self.config.get("transfer_wifi_device", "wlan0"),
                    timeout_seconds=int(self.config.get("transfer_timeout_seconds", 900)))
                self._phase("preparing", "転送準備中：Wi-Fiを起動しています")
                self._run_network(self.hotspot.start, self._hotspot_started)
            except Exception as exc:
                self.resume_errors.append(f"Wi-Fi起動失敗: {exc}")
                self.hotspot = None
                self._resume_after_transfer()
        else:
            self._start_transfer_http(self.config.get("transfer_advertised_host"))

    def _run_network(self, action, callback) -> None:
        if self._network_worker is not None and self._network_worker.isRunning():
            raise RuntimeError("ネットワーク処理が進行中です")
        worker = _NetworkWorker(action, self)
        self._network_worker = worker
        worker.result.connect(callback)
        worker.finished.connect(lambda: self._network_worker_finished(worker))
        worker.start()

    def _network_worker_finished(self, worker) -> None:
        if self._network_worker is worker:
            self._network_worker = None
        worker.deleteLater()

    def _hotspot_started(self, info, error) -> None:
        if error:
            self.log_changed.emit(f"Wi-Fi起動失敗: {error}")
            self.resume_errors.append(f"Wi-Fi起動失敗: {error}")
            if self.hotspot and self.hotspot.created:
                QTimer.singleShot(0, lambda: self._stop_hotspot_then_restore())
            else:
                self.hotspot = None
                self._resume_after_transfer()
            return
        self.transfer_wifi = info
        self._start_transfer_http(info["address"])

    def _start_transfer_http(self, advertised_host) -> None:
        root = self._storage_root()
        static = Path(__file__).resolve().parent.parent / "sources/video_viewer/static"
        try:
            self.embedded_transfer = TransferSession(root, static, advertised_host)
            self.transfer_url = self.embedded_transfer.start()
        except Exception as exc:
            self.embedded_transfer = None
            self.log_changed.emit(f"転送を開始できません: {exc}")
            self.resume_errors.append(f"転送起動失敗: {exc}")
            self.transfer_changed.emit(False)
            if self.hotspot:
                QTimer.singleShot(0, lambda: self._stop_hotspot_then_restore())
            else:
                self._resume_after_transfer()
            return
        self.transfer_expiry.start(int(self.config.get("transfer_timeout_seconds", 900)) * 1000)
        self._phase("active", "転送中：他の機能は停止しています")
        self.transfer_changed.emit(True)

    def end_transfer(self) -> None:
        if self.transfer_phase in {"preparing", "stopping", "restoring"}:
            return
        self.transfer_expiry.stop()
        if self.embedded_transfer:
            self._phase("stopping", "転送停止中：接続終了を確認しています")
            try:
                if self.embedded_transfer.stop() is not True:
                    raise RuntimeError("転送停止の完了通知がありません")
            except Exception as exc:
                self._phase("error", f"転送停止失敗：復帰を保留します · {exc}")
                return
            self.embedded_transfer = None
            self.transfer_url = ""
        if self.hotspot:
            self._stop_hotspot_then_restore()
        elif self.transfer.state() != QProcess.ProcessState.NotRunning:
            self.transfer.terminate()
        else:
            self.transfer_wifi = None
            self.transfer_changed.emit(False)
            if not self.closing:
                self._resume_after_transfer()
            else:
                self._phase("idle", "転送停止を確認しました")

    def _stop_hotspot_then_restore(self) -> None:
        if not self.hotspot:
            self.transfer_wifi = None
            self.transfer_changed.emit(False)
            self._resume_after_transfer()
            return
        self._phase("stopping", "転送停止中：Wi-Fiを元に戻しています")
        try:
            self._run_network(self.hotspot.stop, self._hotspot_stopped)
        except RuntimeError:
            # 開始スレッドの終了シグナル処理を待って再試行する。
            QTimer.singleShot(100, self._stop_hotspot_then_restore)

    def _hotspot_stopped(self, stopped, error) -> None:
        if error or not stopped:
            self._phase("error", f"Wi-Fiの復帰を確認できません · {error or '再試行してください'}")
            return
        self.hotspot = None
        self.transfer_wifi = None
        self.transfer_changed.emit(False)
        if not self.closing:
            self._resume_after_transfer()
        else:
            self._phase("idle", "転送停止を確認しました")

    def _restore_recorder(self) -> None:
        # Restore the pre-transfer state irrespective of the boot auto-start setting.
        self.restart_recorder_after_transfer = False
        if not self.start_recorder():
            self.resume_errors.append("録画を再開できません")
            self._restore_services()
            self._finish_restore()
        else:
            self.restore_watchdog.start()

    def _resume_after_transfer(self):
        self._phase("restoring", "転送停止確認済み：各機能を復帰しています")
        if self.restart_recorder_after_transfer:
            self._restore_recorder()
        else:
            self._restore_services()
            self._finish_restore()

    def _restore_services(self):
        items = list(self.resume_services.items())
        # 録画していない場合は映像供給を先に再開する。
        items.sort(key=lambda item: 0 if item[0] == "カメラ映像" else 1)
        self.resume_services = {}
        for name, adapter in items:
            try:
                if not adapter.is_running():
                    if name == "AI":
                        adapter.set_camera(self.analysis_camera)
                    adapter.start()
                if not adapter.is_running():
                    raise RuntimeError("再開を確認できません")
            except Exception as exc:
                self.resume_errors.append(f"{name}: {exc}")

    def _finish_restore(self):
        self.restore_watchdog.stop()
        if self.resume_errors:
            self._phase("error", "復帰失敗：" + " / ".join(self.resume_errors))
        else:
            message = "転送停止を確認し、停止前の機能の再起動を指示しました" if self.resume_expected else "転送停止確認済み（転送前に稼働していた機能はありません）"
            self._phase("idle", message)

    def _restore_timed_out(self):
        self.resume_errors.append("前後カメラの録画再開を確認できません")
        self._restore_services()
        self._finish_restore()

    def _recorder_started(self) -> None:
        if self.video_role:
            self.video_recorder_active = True
        if self.recorder_stop_after_start:
            self.recorder_stop_after_start = False
            self.stop_recorder()
            return
        self.recorder_changed.emit(True)
        self.status_changed.emit("録画プロセス稼働中・カメラ初期化確認中")

    def _read_recorder_output(self) -> None:
        self.recorder_output_buffer += bytes(self.recorder.readAllStandardOutput()).decode(errors="replace")
        lines = self.recorder_output_buffer.split("\n")
        self.recorder_output_buffer = lines.pop()
        for line in lines:
            self.log_changed.emit(line)
            if line.startswith("[動画検証終了]"):
                self.video_ended_pending = True
                self.video_finished.emit()
            if line.startswith("[録画エラー]"):
                self.recorder_last_error = line.removeprefix("[録画エラー]").strip()
                self.status_changed.emit("録画エラー: " + self.recorder_last_error)
            previous_ready = self.recorder_ready == {"front", "rear"}
            if "録画開始]" in line:
                if "フロント" in line:
                    self.recorder_ready.add("front")
                elif "リア" in line:
                    self.recorder_ready.add("rear")
            if self.recorder_ready == {"front", "rear"} and not previous_ready:
                self.recorder_ready_changed.emit(True)
                if self.transfer_phase == "restoring":
                    self._restore_services()
                    self._finish_restore()
                else:
                    self.status_changed.emit("前後の録画処理を開始（映像確認待ち）")

    def _read_recorder_error(self) -> None:
        for line in bytes(self.recorder.readAllStandardError()).decode(errors="replace").splitlines():
            self.log_changed.emit(f"録画エラー: {line}")

    def _recorder_finished(self, code: int, _status) -> None:
        self._read_recorder_output()
        self.recorder_ready.clear()
        self.recorder_ready_changed.emit(False)
        self.recorder_changed.emit(False)
        if not self.closing and not self.transfer_requested and self.transfer_phase in {"idle", "error"} and self.preview_requested and not self.video_ended_pending:
            self.start_preview()
        if self.transfer_requested:
            self.transfer_requested = False
            if code != 0:
                self.status_changed.emit(f"録画の正常停止を確認できず転送を中止しました ({code})")
                self.log_changed.emit("録画ファイルの確定を確認できなかったため、転送を開始しません")
                self.transfer_changed.emit(False)
                self.resume_errors.append("転送準備中の録画停止が異常終了しました")
                self._resume_after_transfer()
                return
            self.log_changed.emit("録画プロセス停止を確認しました")
            self.transfer_requested = True
            self._start_transfer()
        elif self.restart_recorder_after_transfer:
            self._restore_recorder()
        else:
            if self.transfer_phase == "restoring":
                self.resume_errors.append(f"録画再開後に終了しました ({code})")
                self._restore_services()
                self._finish_restore()
            else:
                if code == 0:
                    self.status_changed.emit("録画停止")
                else:
                    detail = f": {self.recorder_last_error}" if self.recorder_last_error else ""
                    self.status_changed.emit(f"録画プロセス異常終了 ({code}){detail}")

    def _read_transfer_output(self) -> None:
        for line in bytes(self.transfer.readAllStandardOutput()).decode(errors="replace").splitlines():
            self.log_changed.emit(line)

    def _read_transfer_error(self) -> None:
        for line in bytes(self.transfer.readAllStandardError()).decode(errors="replace").splitlines():
            self.log_changed.emit(f"転送エラー: {line}")

    def _transfer_finished(self, code: int, _status) -> None:
        self.transfer_changed.emit(False)
        self.log_changed.emit(f"転送ビューアが終了しました (code={code})")
        if self.restart_recorder_after_transfer:
            self._restore_recorder()

    def _process_error(self, label: str, process: QProcess, error) -> None:
        self.log_changed.emit(f"{label}プロセスエラー: {process.errorString()} ({error.name})")
        if label == "録画":
            self.recorder_ready.clear()
            self.recorder_ready_changed.emit(False)
            self.recorder_changed.emit(False)
            if self.transfer_phase == "restoring":
                self.resume_errors.append("録画プロセスの再起動に失敗しました")
                self._restore_services()
                self._finish_restore()
        else:
            self.transfer_changed.emit(False)
            if error == QProcess.ProcessError.FailedToStart and self.restart_recorder_after_transfer:
                self._restore_recorder()

    def stop(self) -> bool:
        """転送と録画の停止確認が取れた場合だけ成功を返す。"""
        if self.transfer_phase in {"preparing", "stopping", "restoring"}:
            self.status_changed.emit("処理の完了を待ってから終了してください")
            return False
        self.closing = True
        try:
            self.sensor_hub.stop()
        except Exception as exc:
            self.closing = False
            self.status_changed.emit(f"センサーの停止を確認できません: {exc}")
            return False
        if not self.stop_adas() or not self.stop_preview():
            self.closing = False
            self.status_changed.emit("危険予知またはカメラの停止を確認できません")
            return False
        self.restart_recorder_after_transfer = False
        self.end_transfer()
        self.transfer_requested = False
        if self.embedded_transfer is not None or self.hotspot is not None:
            self.closing = False
            self.status_changed.emit("転送の停止を確認できず、終了を中止しました")
            return False
        if self.transfer.state() != QProcess.ProcessState.NotRunning:
            self.transfer.terminate()
            if not self.transfer.waitForFinished(5000):
                self.closing = False
                self.status_changed.emit("転送プロセスの停止を確認できません")
                return False
        if self.recorder.state() == QProcess.ProcessState.Starting:
            if not self.recorder.waitForStarted(5000):
                self.closing = False
                self.status_changed.emit("録画の起動状態を確認できず、終了を中止しました")
                return False
        if self.recorder.state() == QProcess.ProcessState.Running:
            self.recorder.write(b"F\n")
            self.recorder.closeWriteChannel()
            if not self.recorder.waitForFinished(20000):
                self.closing = False
                self.status_changed.emit("録画停止を確認できず、終了を中止しました")
                return False
            if self.recorder.exitStatus() != QProcess.ExitStatus.NormalExit or self.recorder.exitCode() != 0:
                self.closing = False
                self.status_changed.emit("録画が異常終了したため、終了を中止しました")
                return False
        return True

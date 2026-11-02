"""既存の録画・転送プロセスをUIから安全に操作する実行時制御。"""
from __future__ import annotations

import json
from pathlib import Path
from transfer_service import TransferSession
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal


class RuntimeController(QObject):
    status_changed = Signal(str)
    log_changed = Signal(str)
    transfer_changed = Signal(bool)
    recorder_changed = Signal(bool)
    analysis_camera_changed = Signal(str)
    transfer_phase_changed = Signal(str)

    def __init__(self, config_path: Path, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.config = self._load_config()
        self.embedded_transfer = None
        self.transfer_url = ""
        self.analysis_camera = "front"
        self.adas_adapter = None
        self.closing = False
        self.transfer_phase = "idle"
        self.services = {}
        self.resume_services = {}
        self.resume_errors = []
        self.resume_expected = 0
        self.recorder_output_buffer = ""
        self.restore_watchdog = QTimer(self)
        self.restore_watchdog.setSingleShot(True)
        self.restore_watchdog.setInterval(20000)
        self.restore_watchdog.timeout.connect(self._restore_timed_out)
        self.transfer_expiry = QTimer(self)
        self.transfer_expiry.setSingleShot(True)
        self.transfer_expiry.timeout.connect(self.end_transfer)
        self.recorder = QProcess(self)
        self.transfer = QProcess(self)
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

    def _command(self, key: str) -> list[str]:
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
        process.setProgram(str(program))
        process.setArguments(command[1:])
        process.start()
        return True

    def start_recorder(self) -> bool:
        if self.recorder.state() != QProcess.ProcessState.NotRunning:
            return True
        self.recorder_ready.clear()
        self.recorder_output_buffer = ""
        if not self._launch(self.recorder, self._command("recorder_command"), "recorder_working_directory"):
            self.status_changed.emit("録画プログラム未設定")
            return False
        self.status_changed.emit("録画プロセス起動待ち")
        return True

    def request_manual_event(self) -> bool:
        if self.recorder.state() != QProcess.ProcessState.Running:
            self.log_changed.emit("録画プロセスが起動していないため、イベント保存を要求できません")
            return False
        self.recorder.write(b"E\n")
        self.log_changed.emit("手動イベント保存を要求しました")
        return True

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

    def set_analysis_camera(self, camera):
        if camera not in {"front", "rear"}:
            raise ValueError(camera)
        self.analysis_camera = camera
        if self.adas_adapter is not None:
            self.adas_adapter.set_camera(camera)
        self.analysis_camera_changed.emit(camera)

    def _start_transfer(self) -> None:
        self.transfer_requested = False
        root = Path(self.config.get("storage_path", "../sources/dashcam/videos"))
        if not root.is_absolute():
            root = (self.config_path.parent / root).resolve()
        static = Path(__file__).resolve().parent.parent / "sources/video_viewer/static"
        try:
            self.embedded_transfer = TransferSession(root, static, self.config.get("transfer_advertised_host"))
            self.transfer_url = self.embedded_transfer.start()
        except Exception as exc:
            self.embedded_transfer = None
            self.log_changed.emit(f"転送を開始できません: {exc}")
            self.resume_errors.append(f"転送起動失敗: {exc}")
            self.transfer_changed.emit(False)
            self._resume_after_transfer()
            return
        self.transfer_expiry.start(int(self.config.get("transfer_timeout_seconds", 900)) * 1000)
        self._phase("active", "転送中：他の機能は停止しています")
        self.transfer_changed.emit(True)

    def end_transfer(self) -> None:
        if self.transfer_phase in {"stopping", "restoring"}:
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
            self.transfer_changed.emit(False)
            if not self.closing:
                self._resume_after_transfer()
            else:
                self._phase("idle", "転送停止を確認しました")
        elif self.transfer.state() != QProcess.ProcessState.NotRunning:
            self.transfer.terminate()

    def _restore_recorder(self) -> None:
        # Restore the pre-transfer state irrespective of the boot auto-start setting.
        self.restart_recorder_after_transfer = False
        if not self.start_recorder():
            self.resume_errors.append("録画を再開できません")
            self._finish_restore()
        else:
            self.restore_watchdog.start()

    def _resume_after_transfer(self):
        self._phase("restoring", "転送停止確認済み：各機能を復帰しています")
        for name, adapter in self.resume_services.items():
            try:
                if not adapter.is_running():
                    if name == "AI":
                        adapter.set_camera(self.analysis_camera)
                    adapter.start()
                if not adapter.is_running():
                    raise RuntimeError("再開を確認できません")
            except Exception as exc:
                self.resume_errors.append(f"{name}: {exc}")
        self.resume_services = {}
        if self.restart_recorder_after_transfer:
            self._restore_recorder()
        else:
            self._finish_restore()

    def _finish_restore(self):
        self.restore_watchdog.stop()
        if self.resume_errors:
            self._phase("error", "復帰失敗：" + " / ".join(self.resume_errors))
        else:
            message = "転送停止・転送前の稼働状態への復帰を確認しました" if self.resume_expected else "転送停止確認済み（転送前に稼働していた機能はありません）"
            self._phase("idle", message)

    def _restore_timed_out(self):
        self.resume_errors.append("前後カメラの録画再開を確認できません")
        self._finish_restore()

    def _recorder_started(self) -> None:
        self.recorder_changed.emit(True)
        self.status_changed.emit("録画プロセス稼働中・カメラ初期化確認中")

    def _read_recorder_output(self) -> None:
        self.recorder_output_buffer += bytes(self.recorder.readAllStandardOutput()).decode(errors="replace")
        lines = self.recorder_output_buffer.split("\n")
        self.recorder_output_buffer = lines.pop()
        for line in lines:
            self.log_changed.emit(line)
            if "録画開始]" in line:
                if "フロント" in line:
                    self.recorder_ready.add("front")
                elif "リア" in line:
                    self.recorder_ready.add("rear")
            if self.recorder_ready == {"front", "rear"}:
                if self.transfer_phase == "restoring":
                    self._finish_restore()
                else:
                    self.status_changed.emit("前後カメラ録画中")

    def _read_recorder_error(self) -> None:
        for line in bytes(self.recorder.readAllStandardError()).decode(errors="replace").splitlines():
            self.log_changed.emit(f"録画エラー: {line}")

    def _recorder_finished(self, code: int, _status) -> None:
        self.recorder_changed.emit(False)
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
                self._finish_restore()
            else:
                self.status_changed.emit("録画停止" if code == 0 else f"録画プロセス異常終了 ({code})")

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
            self.recorder_changed.emit(False)
            if self.transfer_phase == "restoring":
                self.resume_errors.append("録画プロセスの再起動に失敗しました")
                self._finish_restore()
        else:
            self.transfer_changed.emit(False)
            if error == QProcess.ProcessError.FailedToStart and self.restart_recorder_after_transfer:
                self._restore_recorder()

    def stop(self) -> None:
        self.closing = True
        self.restart_recorder_after_transfer = False
        self.end_transfer()
        self.transfer_requested = False
        if self.transfer.state() != QProcess.ProcessState.NotRunning:
            self.transfer.terminate()
            self.transfer.waitForFinished(3000)
        if self.recorder.state() == QProcess.ProcessState.Running:
            self.recorder.write(b"F\n")
            self.recorder.closeWriteChannel()
            self.recorder.waitForFinished(5000)

"""録画とイベントの保存状態。完成済みセグメントを扱う保存層。"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path

ROLES = ("front", "rear")
SLOTS = ("previous", "current", "next")
SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")


class StoreError(RuntimeError):
    pass


class RecordingStore:
    """呼び出し元は完成済みのファイルだけをadd_clipへ渡す。"""

    def __init__(self, root: Path, normal_limit: int = 60_000_000_000,
                 event_limit: int = 20_000_000_000):
        self.root = Path(root).resolve()
        self.normal_limit = int(normal_limit)
        self.event_limit = int(event_limit)
        if min(self.normal_limit, self.event_limit) <= 0:
            raise ValueError("保存上限は正の値にしてください")
        self.state_dir = self.root / ".event-state"
        if self.state_dir.is_symlink():
            raise StoreError("状態ディレクトリがシンボリックリンクです")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        for role in ROLES:
            role_path = self.root / role
            if role_path.is_symlink():
                raise StoreError("カメラの保存先がシンボリックリンクです")
            for category in ("continuous", "event", "manual"):
                directory = role_path / category
                if directory.is_symlink():
                    raise StoreError("録画の保存先がシンボリックリンクです")
                directory.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.state_dir / "lock"

    @contextmanager
    def _lock(self):
        with self.lock_path.open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _manifest_path(self, event_id: str) -> Path:
        if not SAFE_ID.fullmatch(event_id):
            raise ValueError("不正なイベントID")
        return self.state_dir / (event_id + ".json")

    def _read(self, event_id: str) -> dict:
        try:
            data = json.loads(self._manifest_path(event_id).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StoreError(f"イベント情報を読めません: {event_id}: {exc}") from exc
        if data.get("id") != event_id or data.get("kind") not in ("event", "manual"):
            raise StoreError(f"イベント情報が不正です: {event_id}")
        return data

    def _write(self, data: dict) -> None:
        dest = self._manifest_path(data["id"])
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.state_dir,
                                             prefix=".manifest-", delete=False) as temp:
                temp_name = temp.name
                json.dump(data, temp, ensure_ascii=False, sort_keys=True)
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(temp_name, dest)
            fd = os.open(self.state_dir, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)

    def _relative_source(self, source: Path, role: str, *, allow_future: bool = False) -> str:
        path = Path(source)
        if path.is_symlink():
            raise StoreError("シンボリックリンクは録画として扱えません")
        parent = (self.root / role / "continuous").resolve()
        if path.parent.resolve() != parent or path.suffix.lower() != ".mp4":
            raise StoreError(f"録画対象が不正です: {path}")
        if path.exists() and not path.is_file():
            raise StoreError(f"録画対象がファイルではありません: {path}")
        if not allow_future and not path.is_file():
            raise StoreError(f"録画対象がありません: {path}")
        return (parent / path.name).relative_to(self.root).as_posix()

    def _all_events(self) -> list[dict]:
        # 不正な状態ファイルを黙って無視すると保護を失うため、操作全体を中止する。
        return [self._read(path.stem) for path in sorted(self.state_dir.glob("*.json"))]

    def begin_event(self, kind: str, trigger_ns: int | None = None) -> str:
        if kind not in ("manual", "event"):
            raise ValueError("不正なイベント種別")
        now = time.time_ns() if trigger_ns is None else int(trigger_ns)
        if now < 0:
            raise ValueError("不正な発生時刻")
        event_id = f"{now:020d}_{uuid.uuid4().hex}"
        data = {"version": 1, "id": event_id, "kind": kind, "trigger_ns": now,
                "status": "pending", "slots": {role: {slot: None for slot in SLOTS} for role in ROLES}}
        with self._lock():
            self._write(data)
        return event_id

    def begin_event_with_sources(self, kind: str, sources: dict, trigger_ns: int | None = None) -> str:
        """全カメラの前・現・次を一括予約する。存在しない次ラップも予約可能。"""
        if kind not in ("manual", "event"):
            raise ValueError("不正なイベント種別")
        now = time.time_ns() if trigger_ns is None else int(trigger_ns)
        if now < 0:
            raise ValueError("不正な発生時刻")
        event_id = f"{now:020d}_{uuid.uuid4().hex}"
        with self._lock():
            slots = {}
            for role in ROLES:
                slots[role] = {}
                for slot in SLOTS:
                    source = sources[role][slot]
                    if source is None:
                        slots[role][slot] = {"state": "missing"}
                    else:
                        relative = self._relative_source(source, role, allow_future=(slot == "next"))
                        slots[role][slot] = {"source": relative, "state": "reserved"}
            data = {"version": 1, "id": event_id, "kind": kind, "trigger_ns": now,
                    "status": "pending", "slots": slots}
            self._write(data)
        return event_id

    def rebind_missing_next(self, role: str, replacement: Path) -> list[str]:
        """録画停止で未作成だった次ラップを、再開後の最初のラップへ引き継ぐ。"""
        if role not in ROLES:
            raise ValueError("不正なカメラ")
        with self._lock():
            new_source = self._relative_source(replacement, role, allow_future=True)
            updated = []
            for data in self._all_events():
                if data.get("status") != "pending":
                    continue
                entry = data["slots"][role].get("next")
                if not entry or entry.get("state") != "reserved" or not entry.get("source"):
                    continue
                original = self.root / entry["source"]
                if original.is_symlink():
                    raise StoreError(f"予約されたラップがシンボリックリンクです: {original}")
                if original.exists() or entry["source"] == new_source:
                    continue
                entry.setdefault("previous_sources", []).append(entry["source"])
                entry["source"] = new_source
                data["interrupted"] = True
                self._write(data)
                updated.append(data["id"])
            return updated

    def events_for_completed_clip(self, source: Path) -> list[tuple[str, str, str]]:
        """確定ラップを待つ予約の一覧。コピーはロック外で呼び出せる。"""
        source = Path(source).resolve()
        with self._lock():
            matches = []
            for data in self._all_events():
                if data.get("status") != "pending":
                    continue
                for role in ROLES:
                    for slot, entry in data["slots"][role].items():
                        if (entry and entry.get("state") == "reserved" and entry.get("source")
                                and (self.root / entry["source"]).resolve() == source):
                            matches.append((data["id"], role, slot))
            return matches

    def settle_event(self, event_id: str) -> str:
        """予約のコピー完了を確認する。欠落ラップがあれば不完全として保持する。"""
        with self._lock():
            data = self._read(event_id)
            if data["status"] != "pending":
                return data["status"]
            entries = [data["slots"][role][slot] for role in ROLES for slot in SLOTS]
            if any(not entry or entry.get("state") == "reserved" for entry in entries):
                return "pending"
            if any(entry.get("state") not in ("saved", "missing") for entry in entries):
                raise StoreError("不正なイベントのラップ状態です")
            data["status"] = "incomplete" if data.get("interrupted") or any(entry["state"] == "missing" for entry in entries) else "complete"
            self._write(data)
            return data["status"]

    def reserve(self, event_id: str, role: str, slot: str, source: Path) -> None:
        if role not in ROLES or slot not in SLOTS:
            raise ValueError("不正なカメラまたはラップ")
        with self._lock():
            data = self._read(event_id)
            if data["status"] != "pending":
                raise StoreError("完了済みイベントを変更できません")
            relative = self._relative_source(source, role)
            existing = data["slots"][role][slot]
            if existing and existing.get("source") != relative:
                raise StoreError("ラップの予約が競合しています")
            if not existing:
                data["slots"][role][slot] = {"source": relative, "state": "reserved"}
                self._write(data)

    def import_complete_legacy_events(self) -> list[str]:
        """旧版の前後3本が揃ったイベントだけ管理対象にする。動画自体は変更しない。"""
        from transfer_service import finalized
        imported = []
        with self._lock():
            for kind, prefix in (("manual", "MANUAL"), ("event", "ACCIDENT")):
                front_base = self.root / "front" / kind
                rear_base = self.root / "rear" / kind
                for front_dir in sorted(front_base.iterdir()):
                    event_id = front_dir.name
                    match = re.fullmatch(prefix + r"_(\d{8}_\d{6})", event_id)
                    rear_dir = rear_base / event_id
                    if (not match or front_dir.is_symlink() or rear_dir.is_symlink()
                            or not front_dir.is_dir() or not rear_dir.is_dir()
                            or self._manifest_path(event_id).exists()):
                        continue
                    files = {}
                    valid = True
                    for role, directory in (("front", front_dir), ("rear", rear_dir)):
                        entries = list(directory.iterdir())
                        if any(path.is_symlink() or not path.is_file() for path in entries):
                            valid = False
                            break
                        videos = sorted(path for path in entries if path.suffix.lower() == ".mp4")
                        expected = re.compile(kind.upper() + "_" + role + r"_video_\d{8}_\d{6}\.mp4")
                        if len(videos) != 3 or any(not expected.fullmatch(path.name) or not finalized(path) for path in videos):
                            valid = False
                            break
                        # 動画以外は旧版のサムネイルだけを認める。
                        if any(path.suffix.lower() not in (".mp4", ".jpg") for path in entries):
                            valid = False
                            break
                        files[role] = videos
                    if not valid:
                        continue
                    try:
                        trigger_ns = int(datetime.strptime(match.group(1), "%Y%m%d_%H%M%S").timestamp() * 1_000_000_000)
                    except (ValueError, OverflowError):
                        continue
                    slots = {role: {slot: {"state": "saved", "destination": path.relative_to(self.root).as_posix(),
                                           "size": path.stat().st_size}
                                    for slot, path in zip(SLOTS, files[role])} for role in ROLES}
                    self._write({"version": 1, "id": event_id, "kind": kind, "trigger_ns": trigger_ns,
                                 "status": "complete", "slots": slots, "legacy_imported": True})
                    imported.append(event_id)
        return imported

    def _event_usage(self) -> int:
        total = 0
        for role in ROLES:
            for kind in ("event", "manual"):
                for path in (self.root / role / kind).rglob("*"):
                    if path.is_symlink():
                        raise StoreError(f"イベント領域にシンボリックリンクがあります: {path}")
                    if path.is_file():
                        total += path.stat().st_size
        return total

    def _event_dir(self, data: dict, role: str) -> Path:
        # role, kind, idを検証し、管理対象以外のパスは削除しない。
        if role not in ROLES or data["kind"] not in ("event", "manual"):
            raise StoreError("不正な保存先")
        self._manifest_path(data["id"])
        return self.root / role / data["kind"] / data["id"]

    def _delete_event(self, data: dict) -> None:
        data["status"] = "deleting"
        self._write(data)
        for role in ROLES:
            directory = self._event_dir(data, role)
            if directory.is_symlink():
                raise StoreError(f"削除先がシンボリックリンクです: {directory}")
            if directory.exists():
                shutil.rmtree(directory)
        self._manifest_path(data["id"]).unlink()

    def _ensure_event_space(self, extra: int, current_event: str) -> None:
        if extra < 0 or extra > self.event_limit:
            raise StoreError("イベント保存枠が不足しています")
        events = self._all_events()
        # 削除途中のイベントは再起動後も同じ単位で削除を完了する。
        for event in events:
            if event.get("status") == "deleting":
                self._delete_event(event)
        candidates = sorted((event for event in events if event.get("status") in ("complete", "incomplete")
                             and not any(entry and entry.get("state") == "reserved"
                                         for role in ROLES for entry in event["slots"][role].values())
                             and event["id"] != current_event),
                            key=lambda event: (event["trigger_ns"], event["id"]))
        used = self._event_usage()
        while used + extra > self.event_limit and candidates:
            self._delete_event(candidates.pop(0))
            used = self._event_usage()
        if used + extra > self.event_limit:
            raise StoreError("イベント保存枠が不足しています。未完了の保存は削除しません")

    @staticmethod
    def _digest(path: Path) -> bytes:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.digest()

    def copy_reserved(self, event_id: str, role: str, slot: str) -> None:
        if role not in ROLES or slot not in SLOTS:
            raise ValueError("不正なカメラまたはラップ")
        with self._lock():
            data = self._read(event_id)
            entry = data["slots"][role][slot]
            if data["status"] != "pending" or not entry:
                raise StoreError("保存予約がありません")
            if entry["state"] == "saved":
                return
            source = self.root / entry["source"]
            self._relative_source(source, role)
            size = source.stat().st_size
            directory = self._event_dir(data, role)
            if directory.is_symlink():
                raise StoreError("保存先がシンボリックリンクです")
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / f"{slot}_{source.name}"
            if destination.is_symlink():
                raise StoreError("保存先がシンボリックリンクです")
            # 終了済みコピーとその直後の状態更新の間で中断された場合、
            # 内容が一致すれば再コピーせずに保存済みとして復旧する。
            if destination.exists():
                if destination.stat().st_size != size or self._digest(destination) != self._digest(source):
                    raise StoreError("既存のイベント動画と保存対象が一致しません")
                entry.update({"state": "saved", "destination": destination.relative_to(self.root).as_posix(), "size": size})
                self._write(data)
                return
            # 一時ファイルはロック内でしか作らないので、残っていれば異常終了の残骸。
            for orphan in directory.glob(".copy-*"):
                if orphan.is_symlink() or not orphan.is_file():
                    raise StoreError("不正な一時ファイルがあります")
                orphan.unlink()
            self._ensure_event_space(size, event_id)
            fd, temporary = tempfile.mkstemp(prefix=".copy-", dir=directory)
            try:
                with os.fdopen(fd, "wb") as target, source.open("rb") as original:
                    shutil.copyfileobj(original, target, 1024 * 1024)
                    target.flush()
                    os.fsync(target.fileno())
                if os.path.getsize(temporary) != size or source.stat().st_size != size:
                    raise StoreError("コピー中に録画ファイルのサイズが変化しました")
                os.replace(temporary, destination)
                dir_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            entry.update({"state": "saved", "destination": destination.relative_to(self.root).as_posix(), "size": size})
            self._write(data)

    def complete_event(self, event_id: str) -> None:
        with self._lock():
            data = self._read(event_id)
            if any(not data["slots"][role][slot] or data["slots"][role][slot].get("state") != "saved"
                   for role in ROLES for slot in SLOTS):
                raise StoreError("未保存のラップがあるため完了できません")
            data["status"] = "complete"
            self._write(data)

    def protected_sources(self) -> set[Path]:
        with self._lock():
            protected = set()
            for data in self._all_events():
                if data.get("status") != "pending":
                    continue
                for role in ROLES:
                    for entry in data["slots"][role].values():
                        if entry and entry.get("source"):
                            protected.add(self.root / entry["source"])
            return protected

    def cleanup_continuous(self, finalized: list[Path], active: set[Path] | None = None) -> list[Path]:
        """確定済みとして渡された動画だけを削除する。未確定・予約中は削除しない。"""
        with self._lock():
            protected = set()
            for data in self._all_events():
                if data.get("status") == "pending":
                    for role in ROLES:
                        for entry in data["slots"][role].values():
                            if entry and entry.get("source"):
                                protected.add((self.root / entry["source"]).resolve())
            protected.update(Path(path).resolve() for path in (active or set()))
            existing = []
            for role in ROLES:
                directory = self.root / role / "continuous"
                for path in directory.iterdir():
                    if path.is_symlink():
                        raise StoreError(f"録画領域にシンボリックリンクがあります: {path}")
                    if path.is_file():
                        existing.append(path)
            used = sum(path.stat().st_size for path in existing)
            candidates = []
            for path in finalized:
                path = Path(path)
                for role in ROLES:
                    if path.parent.resolve() == (self.root / role / "continuous").resolve():
                        relative = self._relative_source(path, role)
                        checked = self.root / relative
                        if checked.resolve() not in protected:
                            candidates.append(checked)
                        break
                else:
                    raise StoreError(f"録画領域外です: {path}")
            candidates = sorted(set(candidates), key=lambda path: (path.stat().st_mtime_ns, str(path)))
            deleted = []
            for path in candidates:
                if used <= self.normal_limit:
                    break
                size = path.stat().st_size
                path.unlink()
                used -= size
                deleted.append(path)
            if used > self.normal_limit:
                raise StoreError("通常録画枠が不足しています。保護中・未確定の動画は削除しません")
            return deleted

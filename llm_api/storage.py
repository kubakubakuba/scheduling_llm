"""Small SQLite persistence layer for conversation workspaces."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationStore:
    def __init__(self, path: str | Path | None = None):
        configured = path or os.getenv("SCHEDULING_DB_PATH", "data/conversations.sqlite3")
        self.path = Path(configured).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    deleted_at TEXT,
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    workspace_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(conversation_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS messages_conversation_idx ON messages(conversation_id, sequence);
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
            """)
            db.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', '1')")

    def create(self, settings: dict[str, Any] | None = None, title: str = "New conversation") -> dict:
        conversation_id = str(uuid.uuid4())
        now = _now()
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO conversations(id,title,created_at,updated_at,settings_json) VALUES (?,?,?,?,?)", (conversation_id, title, now, now, json.dumps(settings or {})))
        return self.get(conversation_id)

    def get(self, conversation_id: str, include_deleted: bool = False) -> dict | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=?" + ("" if include_deleted else " AND deleted_at IS NULL"), (conversation_id,)).fetchone()
            if row is None:
                return None
            messages = db.execute("SELECT role,content,payload_json,created_at,sequence FROM messages WHERE conversation_id=? ORDER BY sequence", (conversation_id,)).fetchall()
            result = dict(row)
            result["settings"] = json.loads(result.pop("settings_json") or "{}")
            result["workspace"] = json.loads(result.pop("workspace_json") or "{}")
            result["pinned"] = bool(result["pinned"])
            result["messages"] = [{"role": item["role"], "content": item["content"], **json.loads(item["payload_json"] or "{}"), "created_at": item["created_at"], "sequence": item["sequence"]} for item in messages]
            return result

    def list(self, include_deleted: bool = False) -> list[dict]:
        with self._lock, self._connect() as db:
            condition = "" if include_deleted else " WHERE deleted_at IS NULL"
            rows = db.execute("SELECT id,title,created_at,updated_at,pinned,deleted_at FROM conversations" + condition + " ORDER BY pinned DESC, updated_at DESC").fetchall()
            return [{**dict(row), "pinned": bool(row["pinned"])} for row in rows]

    def update(self, conversation_id: str, *, title: str | None = None, pinned: bool | None = None, settings: dict | None = None, workspace: dict | None = None) -> None:
        assignments, values = [], []
        if title is not None:
            assignments.append("title=?"); values.append(title)
        if pinned is not None:
            assignments.append("pinned=?"); values.append(int(pinned))
        if settings is not None:
            assignments.append("settings_json=?"); values.append(json.dumps(settings))
        if workspace is not None:
            assignments.append("workspace_json=?"); values.append(json.dumps(workspace))
        if not assignments:
            return
        assignments.append("updated_at=?"); values.append(_now()); values.append(conversation_id)
        with self._lock, self._connect() as db:
            db.execute("UPDATE conversations SET " + ",".join(assignments) + " WHERE id=?", values)

    def append_message(self, conversation_id: str, role: str, content: str = "", payload: dict | None = None) -> None:
        with self._lock, self._connect() as db:
            sequence = db.execute("SELECT COALESCE(MAX(sequence), -1)+1 FROM messages WHERE conversation_id=?", (conversation_id,)).fetchone()[0]
            now = _now()
            db.execute("INSERT INTO messages(conversation_id,sequence,role,content,payload_json,created_at) VALUES (?,?,?,?,?,?)", (conversation_id, sequence, role, content or "", json.dumps(payload or {}), now))
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))

    def save_workspace(self, conversation_id: str, workspace: dict) -> None:
        self.update(conversation_id, workspace=workspace)

    def trash(self, conversation_id: str) -> None:
        self.update_deleted(conversation_id, _now())

    def restore(self, conversation_id: str) -> None:
        self.update_deleted(conversation_id, None)

    def update_deleted(self, conversation_id: str, deleted_at: str | None) -> None:
        with self._lock, self._connect() as db:
            db.execute("UPDATE conversations SET deleted_at=?,updated_at=? WHERE id=?", (deleted_at, _now(), conversation_id))

    def purge(self, conversation_id: str) -> None:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT path FROM artifacts WHERE conversation_id=?", (conversation_id,)).fetchall()
            artifact_root = (self.path.parent / "artifacts").resolve()
            for row in rows:
                candidate = Path(row["path"]).expanduser().resolve()
                if candidate == artifact_root or artifact_root not in candidate.parents:
                    continue
                if candidate.is_dir():
                    shutil.rmtree(candidate, ignore_errors=True)
                elif candidate.is_file():
                    candidate.unlink(missing_ok=True)
            db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))

    def create_artifact(self, conversation_id: str, kind: str, path: str | Path, metadata: dict | None = None, artifact_id: str | None = None) -> str:
        artifact_id = artifact_id or str(uuid.uuid4())
        now = _now()
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO artifacts(id,conversation_id,kind,path,metadata_json,created_at) VALUES (?,?,?,?,?,?)",
                (artifact_id, conversation_id, kind, str(path), json.dumps(metadata or {}), now),
            )
        return artifact_id

    def get_artifact(self, conversation_id: str, artifact_id: str) -> dict | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM artifacts WHERE id=? AND conversation_id=?", (artifact_id, conversation_id)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
            return result

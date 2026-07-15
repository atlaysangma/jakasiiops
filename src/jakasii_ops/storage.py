from __future__ import annotations

import json
import sqlite3
from threading import RLock
from pathlib import Path
from typing import Any


class OpsStore:
    """Append-first local state for exact facts, tasks, mappings and audit."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            self.connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY,
                    store_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    body TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_records_store_kind
                    ON records(store_id, kind, created_at);
                CREATE TABLE IF NOT EXISTS settings (
                    store_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY(store_id, key)
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    store_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    target TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self.connection.commit()

    def put_record(self, kind: str, record: dict[str, Any]) -> None:
        with self._lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO records(id, store_id, kind, created_at, body) VALUES (?, ?, ?, ?, ?)",
                (
                    record["id"],
                    record["store_id"],
                    kind,
                    record.get("created_at") or record.get("occurred_at") or record.get("generated_at"),
                    json.dumps(record, ensure_ascii=False, default=str),
                ),
            )
            self.connection.commit()

    def list_records(self, store_id: str, kind: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT body FROM records WHERE store_id = ? AND kind = ? ORDER BY created_at, id",
                (store_id, kind),
            ).fetchall()
        return [json.loads(row["body"]) for row in rows]

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT body FROM records WHERE id = ?", (record_id,)
            ).fetchone()
        return json.loads(row["body"]) if row else None

    def set_setting(self, store_id: str, key: str, value: Any) -> None:
        with self._lock:
            self.connection.execute(
                "INSERT INTO settings(store_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(store_id, key) DO UPDATE SET value = excluded.value",
                (store_id, key, json.dumps(value, ensure_ascii=False, default=str)),
            )
            self.connection.commit()

    def get_setting(self, store_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self.connection.execute(
                "SELECT value FROM settings WHERE store_id = ? AND key = ?",
                (store_id, key),
            ).fetchone()
        return json.loads(row["value"]) if row else default

    def add_audit(
        self, store_id: str, action: str, actor: str, target: str, detail: dict[str, Any]
    ) -> None:
        with self._lock:
            self.connection.execute(
                "INSERT INTO audit_log(store_id, action, actor, target, detail) VALUES (?, ?, ?, ?, ?)",
                (store_id, action, actor, target, json.dumps(detail, ensure_ascii=False)),
            )
            self.connection.commit()

    def audit_log(self, store_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM audit_log WHERE store_id = ? ORDER BY sequence", (store_id,)
            ).fetchall()
        return [dict(row) | {"detail": json.loads(row["detail"])} for row in rows]

    def close(self) -> None:
        with self._lock:
            self.connection.close()

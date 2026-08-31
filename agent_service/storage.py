from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default


class ManagedConnection(sqlite3.Connection):
    """sqlite connection whose context manager also closes the file handle.

    sqlite3.Connection.__exit__ commits/rolls back but intentionally leaves the
    connection open. That is easy to miss and prevents database cleanup on
    Windows. AgentStorage always treats a connection context as one unit of
    work, so closing on exit is the safer ownership rule here.
    """

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class AgentStorage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=20, factory=ManagedConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=20000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_db(self) -> None:
        with self._lock, self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS agent_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS event_receipts (
                    event_id TEXT PRIMARY KEY,
                    cursor TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    processed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_event_receipts_account_cursor
                    ON event_receipts(account_id, cursor);

                CREATE TABLE IF NOT EXISTS records (
                    record_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL DEFAULT '',
                    chat_id TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL DEFAULT 'note',
                    title TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL DEFAULT '',
                    data_json TEXT NOT NULL DEFAULT '{}',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    source_event_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_records_scope_time
                    ON records(account_id, chat_id, updated_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_records_source_kind
                    ON records(source_event_id, kind)
                    WHERE source_event_id <> '';

                CREATE TABLE IF NOT EXISTS templates (
                    template_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    body TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS monitors (
                    monitor_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    event_type TEXT NOT NULL DEFAULT 'message.created',
                    account_id TEXT NOT NULL DEFAULT '',
                    chat_id TEXT NOT NULL DEFAULT '',
                    message_type TEXT NOT NULL DEFAULT '',
                    contains_text TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL DEFAULT 'record',
                    action_config_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_monitors_enabled_type
                    ON monitors(enabled, event_type);

                CREATE TABLE IF NOT EXISTS monitor_runs (
                    run_id TEXT PRIMARY KEY,
                    monitor_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    action_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(monitor_id) REFERENCES monitors(monitor_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_monitor_runs_event
                    ON monitor_runs(event_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS schedules (
                    schedule_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    task_type TEXT NOT NULL,
                    account_id TEXT NOT NULL DEFAULT '',
                    chat_id TEXT NOT NULL DEFAULT '',
                    template_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    interval_seconds INTEGER NOT NULL DEFAULT 3600,
                    next_run_at TEXT NOT NULL,
                    last_run_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_schedules_due
                    ON schedules(enabled, next_run_at);

                CREATE TABLE IF NOT EXISTS scheduler_runs (
                    run_id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(schedule_id) REFERENCES schedules(schedule_id) ON DELETE CASCADE
                );
                """
            )
            self._ensure_default_templates(conn)

    def _ensure_default_templates(self, conn: sqlite3.Connection) -> None:
        now = utc_now_iso()
        defaults = [
            ("event-note", "Event note", "{{message.text}}"),
            ("monitor-reply", "Monitor reply", "收到：{{message.text}}"),
            ("summary-record", "Summary record", "{{summary}}"),
        ]
        for template_id, name, body in defaults:
            conn.execute(
                """
                INSERT OR IGNORE INTO templates
                    (template_id, name, body, enabled, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (template_id, name, body, now, now),
            )

    def get_meta(self, key: str, default: str = "") -> str:
        with self._lock, self.connect() as conn:
            row = conn.execute("SELECT value FROM agent_meta WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_meta(self, key: str, value: Any) -> None:
        now = utc_now_iso()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_meta (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, str(value), now),
            )

    def event_seen(self, event_id: str) -> bool:
        with self._lock, self.connect() as conn:
            row = conn.execute("SELECT 1 FROM event_receipts WHERE event_id=?", (event_id,)).fetchone()
        return bool(row)

    def store_event(self, event: dict[str, Any]) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO event_receipts
                    (event_id, cursor, account_id, event_type, occurred_at, payload_json, processed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(event.get("event_id") or ""),
                    str(event.get("cursor") or ""),
                    str(event.get("account_id") or ""),
                    str(event.get("event_type") or ""),
                    str(event.get("occurred_at") or ""),
                    json_dumps(event.get("payload") or {}),
                    utc_now_iso(),
                ),
            )

    @staticmethod
    def _record_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["data"] = json_loads(item.pop("data_json", "{}"), {})
        item["tags"] = json_loads(item.pop("tags_json", "[]"), [])
        return item

    def create_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        record_id = str(payload.get("record_id") or f"rec-{uuid.uuid4().hex}")
        source_event_id = str(payload.get("source_event_id") or "")
        kind = str(payload.get("kind") or "note")[:80]
        with self._lock, self.connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO records (
                        record_id, account_id, chat_id, kind, title, body,
                        data_json, tags_json, source_event_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        str(payload.get("account_id") or ""),
                        str(payload.get("chat_id") or ""),
                        kind,
                        str(payload.get("title") or "")[:500],
                        str(payload.get("body") or ""),
                        json_dumps(payload.get("data") or {}),
                        json_dumps(payload.get("tags") or []),
                        source_event_id,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                if source_event_id:
                    row = conn.execute(
                        "SELECT * FROM records WHERE source_event_id=? AND kind=?",
                        (source_event_id, kind),
                    ).fetchone()
                    existing = self._record_row(row)
                    if existing:
                        return existing
                raise
            row = conn.execute("SELECT * FROM records WHERE record_id=?", (record_id,)).fetchone()
        result = self._record_row(row)
        assert result is not None
        return result

    def list_records(
        self,
        *,
        account_id: str = "",
        chat_id: str = "",
        kind: str = "",
        query: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        where = []
        params: list[Any] = []
        if account_id:
            where.append("account_id=?")
            params.append(account_id)
        if chat_id:
            where.append("chat_id=?")
            params.append(chat_id)
        if kind:
            where.append("kind=?")
            params.append(kind)
        if query:
            where.append("(title LIKE ? OR body LIKE ?)")
            needle = f"%{query}%"
            params.extend([needle, needle])
        clause = " WHERE " + " AND ".join(where) if where else ""
        params.append(max(1, min(int(limit), 500)))
        with self._lock, self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM records{clause} ORDER BY updated_at DESC LIMIT ?", tuple(params)
            ).fetchall()
        return [item for row in rows if (item := self._record_row(row)) is not None]

    def delete_record(self, record_id: str) -> bool:
        with self._lock, self.connect() as conn:
            cursor = conn.execute("DELETE FROM records WHERE record_id=?", (record_id,))
            return cursor.rowcount > 0

    @staticmethod
    def _template_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        return item

    def upsert_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        template_id = str(payload.get("template_id") or f"tpl-{uuid.uuid4().hex}")
        name = str(payload.get("name") or template_id)[:200]
        body = str(payload.get("body") or "")
        enabled = 1 if payload.get("enabled", True) else 0
        now = utc_now_iso()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO templates (template_id, name, body, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(template_id) DO UPDATE SET
                    name=excluded.name, body=excluded.body, enabled=excluded.enabled, updated_at=excluded.updated_at
                """,
                (template_id, name, body, enabled, now, now),
            )
            row = conn.execute("SELECT * FROM templates WHERE template_id=?", (template_id,)).fetchone()
        result = self._template_row(row)
        assert result is not None
        return result

    def get_template(self, template_id: str) -> dict[str, Any] | None:
        with self._lock, self.connect() as conn:
            row = conn.execute("SELECT * FROM templates WHERE template_id=?", (template_id,)).fetchone()
        return self._template_row(row)

    def list_templates(self) -> list[dict[str, Any]]:
        with self._lock, self.connect() as conn:
            rows = conn.execute("SELECT * FROM templates ORDER BY name, template_id").fetchall()
        return [item for row in rows if (item := self._template_row(row)) is not None]

    @staticmethod
    def _monitor_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        item["action_config"] = json_loads(item.pop("action_config_json", "{}"), {})
        return item

    def upsert_monitor(self, payload: dict[str, Any]) -> dict[str, Any]:
        monitor_id = str(payload.get("monitor_id") or f"mon-{uuid.uuid4().hex}")
        now = utc_now_iso()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO monitors (
                    monitor_id, name, enabled, event_type, account_id, chat_id,
                    message_type, contains_text, action, action_config_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(monitor_id) DO UPDATE SET
                    name=excluded.name, enabled=excluded.enabled, event_type=excluded.event_type,
                    account_id=excluded.account_id, chat_id=excluded.chat_id,
                    message_type=excluded.message_type, contains_text=excluded.contains_text,
                    action=excluded.action, action_config_json=excluded.action_config_json,
                    updated_at=excluded.updated_at
                """,
                (
                    monitor_id,
                    str(payload.get("name") or monitor_id)[:200],
                    1 if payload.get("enabled", True) else 0,
                    str(payload.get("event_type") or "message.created"),
                    str(payload.get("account_id") or ""),
                    str(payload.get("chat_id") or ""),
                    str(payload.get("message_type") or ""),
                    str(payload.get("contains_text") or ""),
                    str(payload.get("action") or "record"),
                    json_dumps(payload.get("action_config") or {}),
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM monitors WHERE monitor_id=?", (monitor_id,)).fetchone()
        result = self._monitor_row(row)
        assert result is not None
        return result

    def list_monitors(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        where = " WHERE enabled=1" if enabled_only else ""
        with self._lock, self.connect() as conn:
            rows = conn.execute(f"SELECT * FROM monitors{where} ORDER BY name, monitor_id").fetchall()
        return [item for row in rows if (item := self._monitor_row(row)) is not None]

    def monitor_action_done(self, action_key: str) -> bool:
        with self._lock, self.connect() as conn:
            row = conn.execute("SELECT 1 FROM monitor_runs WHERE action_key=?", (action_key,)).fetchone()
        return bool(row)

    def record_monitor_run(
        self,
        monitor_id: str,
        event_id: str,
        action_key: str,
        status: str,
        *,
        result: Any = None,
        error: str = "",
    ) -> dict[str, Any]:
        run_id = f"mrun-{uuid.uuid4().hex}"
        now = utc_now_iso()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO monitor_runs
                    (run_id, monitor_id, event_id, action_key, status, result_json, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, monitor_id, event_id, action_key, status, json_dumps(result or {}), error, now),
            )
            row = conn.execute("SELECT * FROM monitor_runs WHERE action_key=?", (action_key,)).fetchone()
        item = dict(row)
        item["result"] = json_loads(item.pop("result_json", "{}"), {})
        return item

    @staticmethod
    def _schedule_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        item["payload"] = json_loads(item.pop("payload_json", "{}"), {})
        return item

    def upsert_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        schedule_id = str(payload.get("schedule_id") or f"sch-{uuid.uuid4().hex}")
        now = utc_now_iso()
        next_run_at = str(payload.get("next_run_at") or now)
        interval_seconds = max(60, int(payload.get("interval_seconds") or 3600))
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO schedules (
                    schedule_id, name, enabled, task_type, account_id, chat_id, template_id,
                    payload_json, interval_seconds, next_run_at, last_run_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)
                ON CONFLICT(schedule_id) DO UPDATE SET
                    name=excluded.name, enabled=excluded.enabled, task_type=excluded.task_type,
                    account_id=excluded.account_id, chat_id=excluded.chat_id, template_id=excluded.template_id,
                    payload_json=excluded.payload_json, interval_seconds=excluded.interval_seconds,
                    next_run_at=excluded.next_run_at, updated_at=excluded.updated_at
                """,
                (
                    schedule_id,
                    str(payload.get("name") or schedule_id)[:200],
                    1 if payload.get("enabled", True) else 0,
                    str(payload.get("task_type") or "record"),
                    str(payload.get("account_id") or ""),
                    str(payload.get("chat_id") or ""),
                    str(payload.get("template_id") or ""),
                    json_dumps(payload.get("payload") or {}),
                    interval_seconds,
                    next_run_at,
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM schedules WHERE schedule_id=?", (schedule_id,)).fetchone()
        result = self._schedule_row(row)
        assert result is not None
        return result

    def list_schedules(self) -> list[dict[str, Any]]:
        with self._lock, self.connect() as conn:
            rows = conn.execute("SELECT * FROM schedules ORDER BY next_run_at, name").fetchall()
        return [item for row in rows if (item := self._schedule_row(row)) is not None]

    def due_schedules(self, now: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        now = now or utc_now_iso()
        with self._lock, self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM schedules
                WHERE enabled=1 AND next_run_at<=?
                ORDER BY next_run_at, schedule_id
                LIMIT ?
                """,
                (now, max(1, min(int(limit), 200))),
            ).fetchall()
        return [item for row in rows if (item := self._schedule_row(row)) is not None]

    def finish_schedule_run(
        self,
        schedule: dict[str, Any],
        status: str,
        *,
        result: Any = None,
        error: str = "",
        next_run_at: str,
    ) -> dict[str, Any]:
        run_id = f"srun-{uuid.uuid4().hex}"
        now = utc_now_iso()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO scheduler_runs (run_id, schedule_id, status, result_json, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, schedule["schedule_id"], status, json_dumps(result or {}), error, now),
            )
            conn.execute(
                """
                UPDATE schedules
                SET last_run_at=?, next_run_at=?, updated_at=?
                WHERE schedule_id=?
                """,
                (now, next_run_at, now, schedule["schedule_id"]),
            )
        return {
            "run_id": run_id,
            "schedule_id": schedule["schedule_id"],
            "status": status,
            "result": result or {},
            "error": error,
            "created_at": now,
            "next_run_at": next_run_at,
        }

    def counts(self) -> dict[str, int]:
        tables = ["event_receipts", "records", "templates", "monitors", "monitor_runs", "schedules", "scheduler_runs"]
        with self._lock, self.connect() as conn:
            return {table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}


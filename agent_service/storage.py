from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .crashpoint import crash_point, raise_fault


class StorageError(RuntimeError):
    """Base class for agent storage failures."""


class StorageClosedError(StorageError):
    """Raised when storage is used after an explicit shutdown.

    Fail closed: after ``close()`` the process must not silently reopen a
    database behind the operator's back.
    """


class StorageTransactionError(StorageError):
    """Raised when a transaction boundary would be violated."""


class StorageUnavailableError(StorageError):
    """Raised when the writer connection became unusable.

    The caller must treat all in-flight work as uncommitted, drop the writer
    and reconcile before continuing. Never keep using an uncertain writer.
    """


#: sqlite3 error strings that mean "this connection can no longer be trusted".
#: Anything matched here invalidates the writer instead of being retried on it.
_CONNECTION_FATAL_MARKERS = (
    "disk i/o error",
    "database disk image is malformed",
    "file is not a database",
    "database or disk is full",
    "unable to open database file",
    "no such table",
    "sqlite objects created in a thread can only be used in that same thread",
)


def _is_fatal_connection_error(exc: BaseException) -> bool:
    if isinstance(exc, sqlite3.ProgrammingError):
        return True
    if isinstance(exc, (sqlite3.DatabaseError, sqlite3.OperationalError, sqlite3.InterfaceError)):
        text = str(exc).lower()
        return any(marker in text for marker in _CONNECTION_FATAL_MARKERS)
    return False


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

    This type is used only for short-lived bootstrap/one-off connections
    (``AgentStorage.connect``). The steady-state writer is a
    :class:`WriterConnection`, which is owned by the storage object and must
    NOT be closed by a context manager.
    """

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class WriterConnection(sqlite3.Connection):
    """The single long-lived writer connection owned by AgentStorage.

    Ownership rules (RC.14 V4 workstream A):

    * One connection per :class:`AgentStorage`, created lazily and closed only
      by an explicit ``close()``/``shutdown()``. It is never closed by a
      context manager, so a batch no longer pays the "last close of a WAL
      database" checkpoint + fsync + unlink cost on every batch.
    * ``with conn:`` still commits on clean exit and rolls back on exception,
      so a multi-statement unit of work stays atomic.
    * When an explicit :meth:`AgentStorage.session` transaction is already
      open (``_txn_depth > 0``) a nested ``with conn:`` block must NOT commit:
      the outer explicit transaction owns the boundary. This is what keeps
      "cursor advances only inside the same atomic boundary as its durable
      writes" true no matter which helper is called in between.
    * ``check_same_thread=False`` is set at connect time because the poll
      worker and the scheduler worker are different threads. Concurrency is
      governed by ``AgentStorage._lock`` (a re-entrant lock held for the whole
      transaction), not by sqlite's thread check.
    """

    _txn_depth = 0

    def __exit__(self, exc_type, exc_value, traceback):
        if getattr(self, "_txn_depth", 0) > 0:
            # Inside an explicit AgentStorage.session() transaction: propagate
            # the outcome, but never commit from a nested block.
            return False
        return super().__exit__(exc_type, exc_value, traceback)


class AgentStorage:
    """Single-connection SQLite owner for the agent's local durable state.

    Invariants held by construction (RC.14 V4 workstream A):

    * ``journal_mode = WAL`` and ``synchronous = FULL`` are set explicitly on
      the writer connection instead of relying on process defaults.
    * exactly one writer connection exists per storage object, so there is no
      ungoverned multi-writer competition; every write in the process goes
      through it under ``_lock``.
    * transaction boundaries are explicit: ``session()`` issues
      ``BEGIN IMMEDIATE``, then ``COMMIT`` or ``ROLLBACK``.
    * the connection is closed by an explicit ``close()``/``shutdown()`` only.
      Nothing depends on interpreter teardown.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._writer: WriterConnection | None = None
        self._closed = False
        self._writer_generation = 0
        self._writer_open_count = 0
        self._writer_invalidations = 0
        self._writer_failures = 0
        self._stray_transaction_rollbacks = 0
        self.init_db()

    # ------------------------------------------------------------------
    # connection ownership
    # ------------------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        """Open a short-lived connection.

        Bootstrap and one-off use only (schema init, tests, tooling). The
        steady-state write path uses :meth:`writer` so that no batch pays a
        connection open/close cycle.
        """
        conn = sqlite3.connect(self.path, timeout=20, factory=ManagedConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=20000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _open_writer(self) -> WriterConnection:
        conn = sqlite3.connect(
            self.path,
            timeout=20,
            factory=WriterConnection,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=20000")
        conn.execute("PRAGMA foreign_keys=ON")
        # Pin the durability contract explicitly rather than inheriting it.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn._txn_depth = 0
        return conn

    def writer(self) -> WriterConnection:
        """Return the single long-lived writer connection, opening it lazily.

        Callers must hold ``self._lock``. Raises :class:`StorageClosedError`
        after an explicit shutdown, so a stopped process cannot silently
        resume writing.
        """
        if self._closed:
            raise StorageClosedError("agent storage is closed; refusing to reopen implicitly")
        conn = self._writer
        if conn is None:
            conn = self._open_writer()
            self._writer = conn
            self._writer_generation += 1
            self._writer_open_count += 1
        return conn

    def writer_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "writer_open_count": self._writer_open_count,
                "writer_generation": self._writer_generation,
                "writer_invalidations": self._writer_invalidations,
                "writer_failures": self._writer_failures,
                "stray_transaction_rollbacks": self._stray_transaction_rollbacks,
                "writer_open": self._writer is not None,
                "closed": self._closed,
                "txn_depth": getattr(self._writer, "_txn_depth", 0) if self._writer else 0,
            }

    def invalidate_writer(self, reason: str = "") -> dict[str, Any]:
        """Drop the writer connection so the next call reopens it.

        Used on connection failure (C5) and by ``reconcile``. Safe to call
        when no writer is open.
        """
        with self._lock:
            conn, self._writer = self._writer, None
            self._writer_generation += 1
            if conn is None:
                return {"ok": True, "dropped": False, "reason": reason}
            try:
                if conn.in_transaction:
                    conn.rollback()
            except sqlite3.Error:
                pass
            try:
                conn.close()
            except sqlite3.Error:
                pass
            self._writer_invalidations += 1
            return {"ok": True, "dropped": True, "reason": reason}

    def reconcile(self, *, deep: bool = False) -> dict[str, Any]:
        """Reopen the writer and re-establish the durability contract.

        Fail-closed recovery step after a connection failure: the uncertain
        connection is discarded, a fresh one is opened, and the persisted
        cursor plus receipt count are read back so the caller can decide where
        to resume. ``deep=True`` additionally runs ``quick_check`` (expensive
        on a production-size database, so it is opt-in).
        """
        with self._lock:
            if self._closed:
                raise StorageClosedError("agent storage is closed; reconcile refused")
            dropped = self.invalidate_writer("reconcile")
            conn = self.writer()
            journal = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            synchronous = int(conn.execute("PRAGMA synchronous").fetchone()[0])
            cursor = self.get_meta("core_cursor", "0")
            receipts = int(conn.execute("SELECT COUNT(*) FROM event_receipts").fetchone()[0])
            result: dict[str, Any] = {
                "ok": True,
                "dropped": dropped.get("dropped", False),
                "generation": self._writer_generation,
                "journal_mode": journal,
                "synchronous": synchronous,
                "cursor": cursor,
                "receipts": receipts,
                "durability_contract_ok": journal == "wal" and synchronous == 2,
            }
            if deep:
                result["quick_check"] = conn.execute("PRAGMA quick_check(1)").fetchone()[0]
            return result

    def close(self) -> dict[str, Any]:
        """Explicit shutdown: flush the WAL, then close the writer.

        Idempotent. Rolls back any transaction still open, checkpoints the WAL
        into the main database (the durable flush) and closes the handle. After
        this, :meth:`writer` raises instead of silently reopening.
        """
        with self._lock:
            if self._closed:
                return {"ok": True, "already_closed": True, "closed": False}
            self._closed = True
            conn, self._writer = self._writer, None
            info: dict[str, Any] = {
                "ok": True,
                "already_closed": False,
                "closed": False,
                "open_transaction_rolled_back": False,
                "wal_checkpoint": None,
            }
            if conn is None:
                return info
            try:
                if conn.in_transaction:
                    conn.rollback()
                    info["open_transaction_rolled_back"] = True
                try:
                    info["wal_checkpoint"] = list(conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
                except sqlite3.Error as exc:
                    info["wal_checkpoint_error"] = str(exc)
                conn.close()
                info["closed"] = True
            except sqlite3.Error as exc:
                info["ok"] = False
                info["error"] = str(exc)
            return info

    def shutdown(self) -> dict[str, Any]:
        """Alias for :meth:`close` used by the service shutdown path."""
        return self.close()

    @contextlib.contextmanager
    def session(self, *, immediate: bool = True):
        """One explicit, atomic write transaction on the long-lived writer.

        The cursor advance for a batch lives inside this same boundary, so a
        cursor can never point past its durable receipts.
        """
        with self._lock:
            conn = self.writer()
            if getattr(conn, "_txn_depth", 0) > 0:
                raise StorageTransactionError("nested AgentStorage.session() is not supported")
            if conn.in_transaction:
                # Defensive: a dangling implicit transaction would make
                # BEGIN IMMEDIATE fail. Discard it rather than nesting.
                conn.rollback()
                self._stray_transaction_rollbacks += 1
            try:
                if immediate:
                    conn.execute("BEGIN IMMEDIATE")
                conn._txn_depth = 1
                yield conn
                raise_fault("fail_writer", "disk I/O error")
                crash_point("before_commit")
                conn.commit()
                crash_point("after_commit")
            except BaseException as exc:
                self._writer_failures += 1 if _is_fatal_connection_error(exc) else 0
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                if _is_fatal_connection_error(exc):
                    self.invalidate_writer(f"session:{type(exc).__name__}")
                    raise StorageUnavailableError(str(exc)) from exc
                raise
            finally:
                conn._txn_depth = 0

    def init_db(self) -> None:
        with self._lock:
            conn = self.connect()
            try:
                self._init_schema(conn)
            finally:
                conn.close()

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        # Schema DDL is idempotent (CREATE ... IF NOT EXISTS) and additive-only
        # for identity v2. ``with conn:`` commits the DDL and the additive
        # column/template statements in one unit before the handle is closed.
        with conn:
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
                    expected_wechat_identity_uuid TEXT NOT NULL DEFAULT '',
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
                    instance_uuid TEXT NOT NULL DEFAULT '',
                    expected_wechat_identity_uuid TEXT NOT NULL DEFAULT '',
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
            self._additive_identity_columns(conn)
            self._ensure_default_templates(conn)

    @staticmethod
    def _additive_identity_columns(conn: sqlite3.Connection) -> None:
        """Identity v2 (F6/F7) columns, added additively for existing databases.

        Legacy rows keep '' meaning "no identity binding recorded"; execution
        paths treat that as fail-closed instead of guessing an identity.
        """
        for table, column in (
            ("monitors", "expected_wechat_identity_uuid"),
            ("schedules", "instance_uuid"),
            ("schedules", "expected_wechat_identity_uuid"),
        ):
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")

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

    def get_meta(self, key: str, default: str = "", *, conn: sqlite3.Connection | None = None) -> str:
        if conn is not None:
            row = conn.execute("SELECT value FROM agent_meta WHERE key=?", (key,)).fetchone()
            return str(row["value"]) if row else default
        with self._lock, self.writer() as c:
            row = c.execute("SELECT value FROM agent_meta WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_meta(self, key: str, value: Any, *, conn: sqlite3.Connection | None = None) -> None:
        now = utc_now_iso()
        query = """
        INSERT INTO agent_meta (key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """
        params = (key, str(value), now)
        if conn is not None:
            conn.execute(query, params)
            return
        with self._lock, self.writer() as c:
            c.execute(query, params)

    def event_seen(self, event_id: str, *, conn: sqlite3.Connection | None = None) -> bool:
        if conn is not None:
            row = conn.execute("SELECT 1 FROM event_receipts WHERE event_id=?", (event_id,)).fetchone()
            return bool(row)
        with self._lock, self.writer() as c:
            row = c.execute("SELECT 1 FROM event_receipts WHERE event_id=?", (event_id,)).fetchone()
        return bool(row)

    def store_event(self, event: dict[str, Any], *, conn: sqlite3.Connection | None = None) -> None:
        query = """
        INSERT OR IGNORE INTO event_receipts
            (event_id, cursor, account_id, event_type, occurred_at, payload_json, processed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            str(event.get("event_id") or ""),
            str(event.get("cursor") or ""),
            str(event.get("account_id") or ""),
            str(event.get("event_type") or ""),
            str(event.get("occurred_at") or ""),
            json_dumps(event.get("payload") or {}),
            utc_now_iso(),
        )
        if conn is not None:
            conn.execute(query, params)
            return
        with self._lock, self.writer() as c:
            c.execute(query, params)

    @staticmethod
    def _record_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["data"] = json_loads(item.pop("data_json", "{}"), {})
        item["tags"] = json_loads(item.pop("tags_json", "[]"), [])
        return item

    def create_record(self, payload: dict[str, Any], *, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        now = utc_now_iso()
        record_id = str(payload.get("record_id") or f"rec-{uuid.uuid4().hex}")
        source_event_id = str(payload.get("source_event_id") or "")
        kind = str(payload.get("kind") or "note")[:80]
        query = """
        INSERT INTO records (
            record_id, account_id, chat_id, kind, title, body,
            data_json, tags_json, source_event_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
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
        )
        if conn is not None:
            try:
                conn.execute(query, params)
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

        with self._lock, self.writer() as c:
            try:
                c.execute(query, params)
            except sqlite3.IntegrityError:
                if source_event_id:
                    row = c.execute(
                        "SELECT * FROM records WHERE source_event_id=? AND kind=?",
                        (source_event_id, kind),
                    ).fetchone()
                    existing = self._record_row(row)
                    if existing:
                        return existing
                raise
            row = c.execute("SELECT * FROM records WHERE record_id=?", (record_id,)).fetchone()
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
        with self._lock, self.writer() as conn:
            rows = conn.execute(
                f"SELECT * FROM records{clause} ORDER BY updated_at DESC LIMIT ?", tuple(params)
            ).fetchall()
        return [item for row in rows if (item := self._record_row(row)) is not None]

    def delete_record(self, record_id: str) -> bool:
        with self._lock, self.writer() as conn:
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
        with self._lock, self.writer() as conn:
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

    def get_template(self, template_id: str, *, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        if conn is not None:
            row = conn.execute("SELECT * FROM templates WHERE template_id=?", (template_id,)).fetchone()
            return self._template_row(row)
        with self._lock, self.writer() as c:
            row = c.execute("SELECT * FROM templates WHERE template_id=?", (template_id,)).fetchone()
        return self._template_row(row)

    def list_templates(self) -> list[dict[str, Any]]:
        with self._lock, self.writer() as conn:
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

    @staticmethod
    def _validate_monitor(payload: dict[str, Any]) -> None:
        # Identity v2 F7: a rule must state its scope explicitly. An empty
        # account scope would match every WeChat identity and is refused.
        if not str(payload.get("account_id") or "").strip():
            raise ValueError("monitor account_id is required: rules must be scoped to one WeChat slot")
        if str(payload.get("action") or "record") == "send_text":
            # F7: an auto-reply must never silently answer from a different
            # identity, so the expected identity is part of the rule itself.
            if not str(payload.get("expected_wechat_identity_uuid") or "").strip():
                raise ValueError(
                    "send_text monitor requires expected_wechat_identity_uuid bound to the scoped account"
                )

    def upsert_monitor(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_monitor(payload)
        monitor_id = str(payload.get("monitor_id") or f"mon-{uuid.uuid4().hex}")
        now = utc_now_iso()
        with self._lock, self.writer() as conn:
            conn.execute(
                """
                INSERT INTO monitors (
                    monitor_id, name, enabled, event_type, account_id, chat_id,
                    message_type, contains_text, action, action_config_json,
                    expected_wechat_identity_uuid, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(monitor_id) DO UPDATE SET
                    name=excluded.name, enabled=excluded.enabled, event_type=excluded.event_type,
                    account_id=excluded.account_id, chat_id=excluded.chat_id,
                    message_type=excluded.message_type, contains_text=excluded.contains_text,
                    action=excluded.action, action_config_json=excluded.action_config_json,
                    expected_wechat_identity_uuid=excluded.expected_wechat_identity_uuid,
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
                    str(payload.get("expected_wechat_identity_uuid") or ""),
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM monitors WHERE monitor_id=?", (monitor_id,)).fetchone()
        result = self._monitor_row(row)
        assert result is not None
        return result

    def get_monitor(self, monitor_id: str) -> dict[str, Any] | None:
        with self._lock, self.writer() as conn:
            row = conn.execute("SELECT * FROM monitors WHERE monitor_id=?", (monitor_id,)).fetchone()
        return self._monitor_row(row)

    def delete_monitor(self, monitor_id: str) -> bool:
        with self._lock, self.writer() as conn:
            cursor = conn.execute("DELETE FROM monitors WHERE monitor_id=?", (monitor_id,))
            return cursor.rowcount > 0

    def list_monitors(self, *, enabled_only: bool = False, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
        where = " WHERE enabled=1" if enabled_only else ""
        query = f"SELECT * FROM monitors{where} ORDER BY name, monitor_id"
        if conn is not None:
            rows = conn.execute(query).fetchall()
            return [item for row in rows if (item := self._monitor_row(row)) is not None]
        with self._lock, self.writer() as c:
            rows = c.execute(query).fetchall()
        return [item for row in rows if (item := self._monitor_row(row)) is not None]

    def monitor_action_done(self, action_key: str, *, conn: sqlite3.Connection | None = None) -> bool:
        if conn is not None:
            row = conn.execute("SELECT 1 FROM monitor_runs WHERE action_key=?", (action_key,)).fetchone()
            return bool(row)
        with self._lock, self.writer() as c:
            row = c.execute("SELECT 1 FROM monitor_runs WHERE action_key=?", (action_key,)).fetchone()
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
        identity: dict[str, Any] | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        run_id = f"mrun-{uuid.uuid4().hex}"
        now = utc_now_iso()
        merged_result: dict[str, Any] = dict(result or {})
        if identity is not None:
            merged_result["identity"] = dict(identity)
        query = """
        INSERT OR IGNORE INTO monitor_runs
            (run_id, monitor_id, event_id, action_key, status, result_json, error, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (run_id, monitor_id, event_id, action_key, status, json_dumps(merged_result), error, now)
        if conn is not None:
            conn.execute(query, params)
            row = conn.execute("SELECT * FROM monitor_runs WHERE action_key=?", (action_key,)).fetchone()
            item = dict(row)
            item["result"] = json_loads(item.pop("result_json", "{}"), {})
            return item
        with self._lock, self.writer() as c:
            c.execute(query, params)
            row = c.execute("SELECT * FROM monitor_runs WHERE action_key=?", (action_key,)).fetchone()
        item = dict(row)
        item["result"] = json_loads(item.pop("result_json", "{}"), {})
        return item

    def list_monitor_runs(self, monitor_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock, self.writer() as conn:
            rows = conn.execute(
                """
                SELECT * FROM monitor_runs
                WHERE monitor_id=?
                ORDER BY created_at DESC, run_id DESC
                LIMIT ?
                """,
                (monitor_id, max(1, min(int(limit), 100))),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["result"] = json_loads(item.pop("result_json", "{}"), {})
            items.append(item)
        return items

    @staticmethod
    def _schedule_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        item["payload"] = json_loads(item.pop("payload_json", "{}"), {})
        return item

    @staticmethod
    def _validate_schedule(payload: dict[str, Any]) -> None:
        # Identity v2 F6: a scheduled send must be pinned to one WeChat slot
        # and one expected identity at creation time; the scheduler re-checks
        # the live binding before every execution and on every retry.
        if str(payload.get("task_type") or "record") == "send_text":
            if not str(payload.get("account_id") or "").strip():
                raise ValueError("send_text schedule requires account_id")
            if not str(payload.get("chat_id") or "").strip():
                raise ValueError("send_text schedule requires chat_id")
            if not str(payload.get("expected_wechat_identity_uuid") or "").strip():
                raise ValueError(
                    "send_text schedule requires expected_wechat_identity_uuid bound to the scoped account"
                )

    def upsert_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_schedule(payload)
        schedule_id = str(payload.get("schedule_id") or f"sch-{uuid.uuid4().hex}")
        now = utc_now_iso()
        next_run_at = str(payload.get("next_run_at") or now)
        interval_seconds = max(60, int(payload.get("interval_seconds") or 3600))
        with self._lock, self.writer() as conn:
            conn.execute(
                """
                INSERT INTO schedules (
                    schedule_id, name, enabled, task_type, account_id, chat_id, template_id,
                    payload_json, interval_seconds, next_run_at, last_run_at,
                    instance_uuid, expected_wechat_identity_uuid, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?)
                ON CONFLICT(schedule_id) DO UPDATE SET
                    name=excluded.name, enabled=excluded.enabled, task_type=excluded.task_type,
                    account_id=excluded.account_id, chat_id=excluded.chat_id, template_id=excluded.template_id,
                    payload_json=excluded.payload_json, interval_seconds=excluded.interval_seconds,
                    next_run_at=excluded.next_run_at,
                    instance_uuid=excluded.instance_uuid,
                    expected_wechat_identity_uuid=excluded.expected_wechat_identity_uuid,
                    updated_at=excluded.updated_at
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
                    str(payload.get("instance_uuid") or ""),
                    str(payload.get("expected_wechat_identity_uuid") or ""),
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM schedules WHERE schedule_id=?", (schedule_id,)).fetchone()
        result = self._schedule_row(row)
        assert result is not None
        return result

    def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        with self._lock, self.writer() as conn:
            row = conn.execute("SELECT * FROM schedules WHERE schedule_id=?", (schedule_id,)).fetchone()
        return self._schedule_row(row)

    def delete_schedule(self, schedule_id: str) -> bool:
        with self._lock, self.writer() as conn:
            cursor = conn.execute("DELETE FROM schedules WHERE schedule_id=?", (schedule_id,))
            return cursor.rowcount > 0

    def list_schedules(self) -> list[dict[str, Any]]:
        with self._lock, self.writer() as conn:
            rows = conn.execute("SELECT * FROM schedules ORDER BY next_run_at, name").fetchall()
        return [item for row in rows if (item := self._schedule_row(row)) is not None]

    def due_schedules(self, now: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        now = now or utc_now_iso()
        with self._lock, self.writer() as conn:
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
        with self._lock, self.writer() as conn:
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

    def list_scheduler_runs(self, schedule_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock, self.writer() as conn:
            rows = conn.execute(
                """
                SELECT * FROM scheduler_runs
                WHERE schedule_id=?
                ORDER BY created_at DESC, run_id DESC
                LIMIT ?
                """,
                (schedule_id, max(1, min(int(limit), 100))),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["result"] = json_loads(item.pop("result_json", "{}"), {})
            items.append(item)
        return items

    def delete_template(self, template_id: str) -> bool:
        with self._lock, self.writer() as conn:
            cursor = conn.execute("DELETE FROM templates WHERE template_id=?", (template_id,))
            return cursor.rowcount > 0

    def counts(self) -> dict[str, int]:
        tables = ["event_receipts", "records", "templates", "monitors", "monitor_runs", "schedules", "scheduler_runs"]
        with self._lock, self.writer() as conn:
            return {table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}


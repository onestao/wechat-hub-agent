from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MEMORY_SOURCE = ROOT / "memory"
if str(MEMORY_SOURCE) not in sys.path:
    sys.path.insert(0, str(MEMORY_SOURCE))

# Reuse the upstream AI-memory vector/search primitives instead of creating a
# second embedding/ranking implementation for the MCP service.
import ai_memory_core as legacy_memory  # noqa: E402

from .storage import AgentStorage, json_dumps, json_loads, utc_now_iso  # noqa: E402


def parse_rfc3339(value: str) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return int(datetime.fromisoformat(text).timestamp())
    except ValueError:
        return 0


def message_text(message: dict[str, Any]) -> str:
    text = str(message.get("text") or "").strip()
    if text:
        return text
    kind = str(message.get("type") or "unsupported")
    filename = str(message.get("filename") or "").strip()
    media_id = str(message.get("media_id") or "").strip()
    pieces = [f"[{kind}]"]
    if filename:
        pieces.append(filename)
    if media_id:
        pieces.append(f"media:{media_id}")
    return " ".join(pieces)


class EventMemoryIndex:
    """Agent-owned memory populated only from Core normalized events."""

    def __init__(self, storage: AgentStorage, vector_dim: int = legacy_memory.DEFAULT_DIM):
        self.storage = storage
        self.vector_dim = max(64, min(int(vector_dim), 4096))
        self.init_db()

    def init_db(self) -> None:
        with self.storage._lock, self.storage.connect() as conn:  # noqa: SLF001 - shared DB owner
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS event_memory_chunks (
                    chunk_uid TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    direction TEXT NOT NULL DEFAULT '',
                    message_type TEXT NOT NULL DEFAULT '',
                    author_id TEXT NOT NULL DEFAULT '',
                    author_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    created_ts INTEGER NOT NULL DEFAULT 0,
                    text TEXT NOT NULL,
                    source_json TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    indexed_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_event_memory_message
                    ON event_memory_chunks(account_id, message_id);
                CREATE INDEX IF NOT EXISTS idx_event_memory_scope_time
                    ON event_memory_chunks(account_id, chat_id, created_ts DESC);

                CREATE TABLE IF NOT EXISTS event_memory_vectors (
                    chunk_uid TEXT PRIMARY KEY,
                    dim INTEGER NOT NULL,
                    norm REAL NOT NULL,
                    vector BLOB NOT NULL,
                    FOREIGN KEY(chunk_uid) REFERENCES event_memory_chunks(chunk_uid) ON DELETE CASCADE
                );
                """
            )
            self._ensure_fts(conn)

    @staticmethod
    def _ensure_fts(conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_memory_fts'"
        ).fetchone()
        if row:
            return True
        ddls = (
            """
            CREATE VIRTUAL TABLE event_memory_fts USING fts5(
                chunk_uid UNINDEXED,
                account_id UNINDEXED,
                chat_id UNINDEXED,
                text,
                tokenize='trigram'
            )
            """,
            """
            CREATE VIRTUAL TABLE event_memory_fts USING fts5(
                chunk_uid UNINDEXED,
                account_id UNINDEXED,
                chat_id UNINDEXED,
                text,
                tokenize='unicode61 remove_diacritics 2'
            )
            """,
        )
        for ddl in ddls:
            try:
                conn.execute(ddl)
                return True
            except sqlite3.Error:
                continue
        return False

    @staticmethod
    def chunk_uid(account_id: str, message_id: str) -> str:
        return hashlib.sha256(f"{account_id}\x1f{message_id}".encode("utf-8")).hexdigest()

    def ingest_message(self, event: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
        account_id = str(message.get("account_id") or event.get("account_id") or "")
        message_id = str(message.get("message_id") or "")
        chat_id = str(message.get("chat_id") or "")
        if not account_id or not message_id or not chat_id:
            return {"ok": False, "reason": "missing_identity"}
        author = message.get("author") if isinstance(message.get("author"), dict) else {}
        content = message_text(message)
        chunk_uid = self.chunk_uid(account_id, message_id)
        source = {
            "event_id": event.get("event_id"),
            "event_type": event.get("event_type"),
            "account_id": account_id,
            "message": message,
        }
        content_hash = hashlib.sha256(
            json.dumps(source, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        created_at = str(message.get("created_at") or event.get("occurred_at") or "")
        vector, norm = legacy_memory.vector_for_text(content, self.vector_dim)
        indexed_at = utc_now_iso()
        with self.storage._lock, self.storage.connect() as conn:  # noqa: SLF001
            previous = conn.execute(
                "SELECT content_sha256 FROM event_memory_chunks WHERE chunk_uid=?", (chunk_uid,)
            ).fetchone()
            if previous and previous["content_sha256"] == content_hash:
                return {"ok": True, "chunk_uid": chunk_uid, "changed": False}
            conn.execute(
                """
                INSERT INTO event_memory_chunks (
                    chunk_uid, account_id, message_id, chat_id, direction, message_type,
                    author_id, author_name, created_at, created_ts, text, source_json,
                    content_sha256, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_uid) DO UPDATE SET
                    chat_id=excluded.chat_id, direction=excluded.direction,
                    message_type=excluded.message_type, author_id=excluded.author_id,
                    author_name=excluded.author_name, created_at=excluded.created_at,
                    created_ts=excluded.created_ts, text=excluded.text,
                    source_json=excluded.source_json, content_sha256=excluded.content_sha256,
                    indexed_at=excluded.indexed_at
                """,
                (
                    chunk_uid,
                    account_id,
                    message_id,
                    chat_id,
                    str(message.get("direction") or ""),
                    str(message.get("type") or ""),
                    str(author.get("member_id") or ""),
                    str(author.get("display_name") or ""),
                    created_at,
                    parse_rfc3339(created_at),
                    content,
                    json_dumps(source),
                    content_hash,
                    indexed_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO event_memory_vectors (chunk_uid, dim, norm, vector)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chunk_uid) DO UPDATE SET
                    dim=excluded.dim, norm=excluded.norm, vector=excluded.vector
                """,
                (chunk_uid, self.vector_dim, norm, legacy_memory.pack_vector(vector)),
            )
            if self._ensure_fts(conn):
                conn.execute("DELETE FROM event_memory_fts WHERE chunk_uid=?", (chunk_uid,))
                conn.execute(
                    "INSERT INTO event_memory_fts (chunk_uid, account_id, chat_id, text) VALUES (?, ?, ?, ?)",
                    (chunk_uid, account_id, chat_id, content),
                )
        return {"ok": True, "chunk_uid": chunk_uid, "changed": True}

    def _candidate_ids(
        self,
        conn: sqlite3.Connection,
        query: str,
        account_id: str,
        chat_id: str,
        max_candidates: int = 800,
    ) -> dict[str, float]:
        candidates: dict[str, float] = {}
        fts_query = legacy_memory.sanitize_fts_query(query)
        if fts_query and self._ensure_fts(conn):
            filters = ["event_memory_fts MATCH ?"]
            params: list[Any] = [fts_query]
            if account_id:
                filters.append("account_id=?")
                params.append(account_id)
            if chat_id:
                filters.append("chat_id=?")
                params.append(chat_id)
            try:
                rows = conn.execute(
                    f"SELECT chunk_uid FROM event_memory_fts WHERE {' AND '.join(filters)} LIMIT ?",
                    (*params, max_candidates),
                ).fetchall()
                for row in rows:
                    candidates[row["chunk_uid"]] = 1.0
            except sqlite3.Error:
                pass

        filters = []
        params = []
        if account_id:
            filters.append("account_id=?")
            params.append(account_id)
        if chat_id:
            filters.append("chat_id=?")
            params.append(chat_id)
        if query.strip():
            filters.append("text LIKE ?")
            params.append(f"%{query.strip()}%")
        where = " WHERE " + " AND ".join(filters) if filters else ""
        rows = conn.execute(
            f"SELECT chunk_uid FROM event_memory_chunks{where} ORDER BY created_ts DESC LIMIT ?",
            (*params, max_candidates // 2),
        ).fetchall()
        for row in rows:
            candidates[row["chunk_uid"]] = max(candidates.get(row["chunk_uid"], 0.0), 0.8)

        recent_filters = []
        recent_params: list[Any] = []
        if account_id:
            recent_filters.append("account_id=?")
            recent_params.append(account_id)
        if chat_id:
            recent_filters.append("chat_id=?")
            recent_params.append(chat_id)
        recent_where = " WHERE " + " AND ".join(recent_filters) if recent_filters else ""
        rows = conn.execute(
            f"SELECT chunk_uid FROM event_memory_chunks{recent_where} ORDER BY created_ts DESC LIMIT 300",
            tuple(recent_params),
        ).fetchall()
        for row in rows:
            candidates.setdefault(row["chunk_uid"], 0.05)
        return candidates

    def search(
        self,
        query: str,
        *,
        account_id: str = "",
        chat_id: str = "",
        limit: int = 8,
    ) -> dict[str, Any]:
        query = str(query or "").strip()
        if not query:
            return {"query": query, "results": []}
        limit = max(1, min(int(limit), 50))
        query_vector, _ = legacy_memory.vector_for_text(query, self.vector_dim)
        query_terms = legacy_memory.terms_for_text(query)
        now_ts = int(time.time())
        with self.storage._lock, self.storage.connect() as conn:  # noqa: SLF001
            candidates = self._candidate_ids(conn, query, account_id, chat_id)
            if not candidates:
                return {"query": query, "results": []}
            placeholders = ",".join("?" for _ in candidates)
            rows = conn.execute(
                f"""
                SELECT c.*, v.dim, v.vector
                FROM event_memory_chunks c
                JOIN event_memory_vectors v ON v.chunk_uid=c.chunk_uid
                WHERE c.chunk_uid IN ({placeholders})
                """,
                tuple(candidates.keys()),
            ).fetchall()
        scored: list[dict[str, Any]] = []
        for row in rows:
            vector = legacy_memory.unpack_vector(row["vector"], row["dim"])
            semantic = legacy_memory.cosine(query_vector, vector)
            keyword = legacy_memory.keyword_score(query_terms, row["text"])
            # The upstream search keeps a small pool of recent candidates so
            # semantic scoring can rescue weak keyword matches. Preserve that
            # strategy, but do not surface a candidate when both semantic and
            # lexical relevance are exactly zero.
            if semantic <= 0.0 and keyword <= 0.0:
                continue
            age_days = max(0.0, (now_ts - int(row["created_ts"] or now_ts)) / 86400)
            recency = 1.0 / (1.0 + age_days / 30.0)
            score = 0.68 * semantic + 0.22 * keyword + 0.10 * recency + 0.05 * candidates[row["chunk_uid"]]
            scored.append(
                {
                    "score": round(float(score), 6),
                    "semantic_score": round(float(semantic), 6),
                    "keyword_score": round(float(keyword), 6),
                    "recency_score": round(float(recency), 6),
                    "chunk_uid": row["chunk_uid"],
                    "account_id": row["account_id"],
                    "message_id": row["message_id"],
                    "chat_id": row["chat_id"],
                    "direction": row["direction"],
                    "message_type": row["message_type"],
                    "author_id": row["author_id"],
                    "author_name": row["author_name"],
                    "created_at": row["created_at"],
                    "text": row["text"],
                    "source": json_loads(row["source_json"], {}),
                }
            )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return {
            "query": query,
            "account_id": account_id,
            "chat_id": chat_id,
            "results": scored[:limit],
        }

    def recent(self, account_id: str, chat_id: str, limit: int = 20) -> list[dict[str, Any]]:
        if not account_id or not chat_id:
            return []
        with self.storage._lock, self.storage.connect() as conn:  # noqa: SLF001
            rows = conn.execute(
                """
                SELECT * FROM event_memory_chunks
                WHERE account_id=? AND chat_id=?
                ORDER BY created_ts DESC, indexed_at DESC
                LIMIT ?
                """,
                (account_id, chat_id, max(1, min(int(limit), 200))),
            ).fetchall()
        return [
            {
                "account_id": row["account_id"],
                "message_id": row["message_id"],
                "chat_id": row["chat_id"],
                "direction": row["direction"],
                "message_type": row["message_type"],
                "author_id": row["author_id"],
                "author_name": row["author_name"],
                "created_at": row["created_at"],
                "text": row["text"],
            }
            for row in rows
        ]

    def context(
        self,
        account_id: str,
        chat_id: str,
        query: str,
        *,
        recent_limit: int = 20,
        memory_limit: int = 8,
    ) -> dict[str, Any]:
        recent = self.recent(account_id, chat_id, recent_limit)
        memories = self.search(
            query,
            account_id=account_id,
            chat_id=chat_id,
            limit=memory_limit,
        ).get("results", []) if query else []
        lines = ["# Recent messages"]
        for item in reversed(recent):
            speaker = item["author_name"] or item["author_id"] or ("me" if item["direction"] == "outgoing" else "unknown")
            lines.append(f"- {item['created_at']} {speaker}: {item['text']}")
        if memories:
            lines.append("\n# Relevant long-term memories")
            for item in memories:
                speaker = item["author_name"] or item["author_id"] or "unknown"
                lines.append(f"- {item['created_at']} {speaker}: {item['text']}")
        return {
            "account_id": account_id,
            "chat_id": chat_id,
            "query": query,
            "recent": recent,
            "memories": memories,
            "prompt_context": "\n".join(lines),
        }

    def count(self) -> int:
        with self.storage._lock, self.storage.connect() as conn:  # noqa: SLF001
            return int(conn.execute("SELECT COUNT(*) FROM event_memory_chunks").fetchone()[0])


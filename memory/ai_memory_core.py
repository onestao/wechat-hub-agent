#!/usr/bin/env python3
"""Local AI memory index for the read-only WeChat memory database.

The index is intentionally self-contained: SQLite FTS plus deterministic
hashing vectors. It can be rebuilt from runtime/memory/wechat_memory.sqlite
and never writes to the original WeChat data.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from message_parse import message_index_text


DEFAULT_DIM = 384
DEFAULT_BATCH_SIZE = 2000
DEFAULT_OVERLAP_SECONDS = 3600
DISPLAY_TZ_NAME = "Asia/Shanghai"
try:
    DISPLAY_TZ = ZoneInfo(DISPLAY_TZ_NAME)
except ZoneInfoNotFoundError:
    DISPLAY_TZ = timezone(timedelta(hours=8), DISPLAY_TZ_NAME)

WORD_RE = re.compile(r"[A-Za-z0-9_@.\-]+|[\u4e00-\u9fff]+")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def unix_to_local_text(value: int | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromtimestamp(int(value), DISPLAY_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return str(value)


def content_hash(*parts) -> str:
    h = hashlib.sha256()
    for part in parts:
        if part is None:
            h.update(b"\x00")
        elif isinstance(part, bytes):
            h.update(part)
        else:
            h.update(str(part).encode("utf-8", errors="replace"))
        h.update(b"\x1f")
    return h.hexdigest()


def open_source_db(path: Path) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def open_ai_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def init_ai_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=DELETE;

        CREATE TABLE IF NOT EXISTS ai_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ai_chunks (
            chunk_uid TEXT PRIMARY KEY,
            chat_username TEXT NOT NULL,
            chat_display_name TEXT,
            sender_hint TEXT,
            start_time INTEGER,
            end_time INTEGER,
            type_label TEXT,
            message_count INTEGER NOT NULL DEFAULT 1,
            text TEXT NOT NULL,
            source_json TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_ai_chunks_chat_time
            ON ai_chunks(chat_username, end_time DESC);
        CREATE INDEX IF NOT EXISTS idx_ai_chunks_type
            ON ai_chunks(type_label);

        CREATE TABLE IF NOT EXISTS ai_vectors (
            chunk_uid TEXT PRIMARY KEY,
            dim INTEGER NOT NULL,
            norm REAL NOT NULL,
            vector BLOB NOT NULL,
            FOREIGN KEY(chunk_uid) REFERENCES ai_chunks(chunk_uid) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS ai_indexed_messages (
            message_uid TEXT PRIMARY KEY,
            content_sha256 TEXT NOT NULL,
            chunk_uid TEXT NOT NULL,
            create_time INTEGER,
            indexed_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_ai_indexed_messages_time
            ON ai_indexed_messages(create_time);

        CREATE TABLE IF NOT EXISTS ai_index_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            source_memory_db TEXT NOT NULL,
            scanned_messages INTEGER NOT NULL DEFAULT 0,
            indexed_messages INTEGER NOT NULL DEFAULT 0,
            skipped_messages INTEGER NOT NULL DEFAULT 0,
            details_json TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    ensure_fts(conn)


def ensure_fts(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_chunks_fts'"
    ).fetchone()
    if row:
        return True
    for ddl in (
        """
        CREATE VIRTUAL TABLE ai_chunks_fts USING fts5(
            chunk_uid UNINDEXED,
            chat_username UNINDEXED,
            text,
            tokenize='trigram'
        )
        """,
        """
        CREATE VIRTUAL TABLE ai_chunks_fts USING fts5(
            chunk_uid UNINDEXED,
            chat_username UNINDEXED,
            text,
            tokenize='unicode61 remove_diacritics 2'
        )
        """,
    ):
        try:
            conn.execute(ddl)
            return True
        except sqlite3.Error:
            continue
    return False


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM ai_meta WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else default


def set_meta(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        """
        INSERT INTO ai_meta (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, str(value)),
    )


def clean_message_text(row: sqlite3.Row | dict) -> tuple[str, str]:
    data = {key: row[key] for key in row.keys()} if isinstance(row, sqlite3.Row) else row
    return message_index_text(data)


def source_rows(
    source_conn: sqlite3.Connection,
    since_time: int,
    batch_size: int,
    overlap_seconds: int,
) -> list[sqlite3.Row]:
    lower_bound = max(0, int(since_time or 0) - max(0, int(overlap_seconds)))
    return source_conn.execute(
        """
        SELECT m.message_uid, m.chat_username, m.chat_display_name, m.local_id,
               m.type_label, m.create_time, m.source, m.message_content,
               m.compress_content, m.content_sha256,
               mm.media_path, mm.thumb_path, mm.mime_type, mm.status AS media_status
        FROM messages m
        LEFT JOIN message_media mm ON mm.message_uid = m.message_uid
        WHERE COALESCE(m.create_time, 0) >= ?
        ORDER BY COALESCE(m.create_time, 0), m.chat_username, m.local_id
        LIMIT ?
        """,
        (lower_bound, int(batch_size)),
    ).fetchall()


def terms_for_text(text: str) -> list[str]:
    terms: list[str] = []
    for match in WORD_RE.finditer((text or "").lower()):
        token = match.group(0)
        if not token:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            terms.extend(token)
            if len(token) >= 2:
                terms.extend(token[i : i + 2] for i in range(len(token) - 1))
            if len(token) >= 3:
                terms.extend(token[i : i + 3] for i in range(len(token) - 2))
        else:
            if len(token) > 1:
                terms.append(token)
    return terms


def vector_for_text(text: str, dim: int = DEFAULT_DIM) -> tuple[list[float], float]:
    vec = [0.0] * dim
    terms = terms_for_text(text)
    if not terms:
        return vec, 0.0
    counts: dict[str, int] = {}
    for term in terms:
        counts[term] = counts.get(term, 0) + 1
    for term, count in counts.items():
        digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "little", signed=False)
        idx = value % dim
        sign = -1.0 if (value >> 8) & 1 else 1.0
        weight = (1.0 + math.log1p(count)) * (1.0 + min(len(term), 8) * 0.03)
        vec[idx] += sign * weight
    norm = math.sqrt(sum(item * item for item in vec))
    if norm:
        vec = [item / norm for item in vec]
    return vec, norm


def pack_vector(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack_vector(blob: bytes, dim: int) -> tuple[float, ...]:
    if not blob:
        return tuple()
    expected = dim * 4
    if len(blob) != expected:
        dim = len(blob) // 4
    return struct.unpack(f"<{dim}f", blob[: dim * 4])


def cosine(vec_a: list[float], vec_b: tuple[float, ...]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    size = min(len(vec_a), len(vec_b))
    return sum(vec_a[i] * vec_b[i] for i in range(size))


def build_chunk(row: sqlite3.Row) -> dict:
    sender, message_text = clean_message_text(row)
    display_name = row["chat_display_name"] or row["chat_username"]
    time_text = unix_to_local_text(row["create_time"])
    speaker = sender or "me"
    text = "\n".join(
        part
        for part in (
            f"chat: {display_name}",
            f"sender: {speaker}",
            f"time: {time_text}" if time_text else "",
            f"type: {row['type_label'] or 'unknown'}",
            f"content: {message_text}",
        )
        if part
    )
    source = {
        "message_uid": row["message_uid"],
        "chat_username": row["chat_username"],
        "chat_display_name": display_name,
        "sender_hint": sender,
        "local_id": row["local_id"],
        "type_label": row["type_label"],
        "create_time": row["create_time"],
        "content": message_text,
        "media_path": row["media_path"],
        "thumb_path": row["thumb_path"],
        "mime_type": row["mime_type"],
        "media_status": row["media_status"],
    }
    return {
        "chunk_uid": row["message_uid"],
        "chat_username": row["chat_username"],
        "chat_display_name": display_name,
        "sender_hint": sender,
        "start_time": row["create_time"],
        "end_time": row["create_time"],
        "type_label": row["type_label"],
        "message_count": 1,
        "text": text,
        "source_json": json.dumps(source, ensure_ascii=False),
        "content_sha256": content_hash(row["content_sha256"], text),
    }


def upsert_chunk(conn: sqlite3.Connection, chunk: dict, dim: int = DEFAULT_DIM) -> None:
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO ai_chunks (
            chunk_uid, chat_username, chat_display_name, sender_hint, start_time,
            end_time, type_label, message_count, text, source_json,
            content_sha256, indexed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chunk_uid) DO UPDATE SET
            chat_username=excluded.chat_username,
            chat_display_name=excluded.chat_display_name,
            sender_hint=excluded.sender_hint,
            start_time=excluded.start_time,
            end_time=excluded.end_time,
            type_label=excluded.type_label,
            message_count=excluded.message_count,
            text=excluded.text,
            source_json=excluded.source_json,
            content_sha256=excluded.content_sha256,
            indexed_at=excluded.indexed_at
        """,
        (
            chunk["chunk_uid"],
            chunk["chat_username"],
            chunk["chat_display_name"],
            chunk["sender_hint"],
            chunk["start_time"],
            chunk["end_time"],
            chunk["type_label"],
            chunk["message_count"],
            chunk["text"],
            chunk["source_json"],
            chunk["content_sha256"],
            now,
        ),
    )
    vec, norm = vector_for_text(chunk["text"], dim)
    conn.execute(
        """
        INSERT INTO ai_vectors (chunk_uid, dim, norm, vector)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chunk_uid) DO UPDATE SET
            dim=excluded.dim,
            norm=excluded.norm,
            vector=excluded.vector
        """,
        (chunk["chunk_uid"], dim, norm, pack_vector(vec)),
    )
    if ensure_fts(conn):
        conn.execute("DELETE FROM ai_chunks_fts WHERE chunk_uid=?", (chunk["chunk_uid"],))
        conn.execute(
            "INSERT INTO ai_chunks_fts (chunk_uid, chat_username, text) VALUES (?, ?, ?)",
            (chunk["chunk_uid"], chunk["chat_username"], chunk["text"]),
        )


def index_once(
    source_memory_db: Path,
    ai_db: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
    overlap_seconds: int = DEFAULT_OVERLAP_SECONDS,
    dim: int = DEFAULT_DIM,
) -> dict:
    started_mono = time.time()
    started_at = utc_now_iso()
    if not source_memory_db.exists():
        raise FileNotFoundError(f"source memory db not found: {source_memory_db}")

    with open_ai_db(ai_db) as ai_conn:
        init_ai_db(ai_conn)
        since_time = int(get_meta(ai_conn, "last_source_create_time", "0") or 0)
        run_id = ai_conn.execute(
            "INSERT INTO ai_index_runs (started_at, source_memory_db) VALUES (?, ?)",
            (started_at, str(source_memory_db)),
        ).lastrowid

        scanned = indexed = skipped = 0
        max_time = since_time
        type_counts: dict[str, int] = {}

        with open_source_db(source_memory_db) as source_conn:
            rows = source_rows(source_conn, since_time, batch_size, overlap_seconds)

        for row in rows:
            scanned += 1
            max_time = max(max_time, int(row["create_time"] or 0))
            chunk = build_chunk(row)
            previous = ai_conn.execute(
                "SELECT content_sha256 FROM ai_indexed_messages WHERE message_uid=?",
                (row["message_uid"],),
            ).fetchone()
            if previous and previous["content_sha256"] == chunk["content_sha256"]:
                skipped += 1
                continue
            upsert_chunk(ai_conn, chunk, dim=dim)
            ai_conn.execute(
                """
                INSERT INTO ai_indexed_messages (
                    message_uid, content_sha256, chunk_uid, create_time, indexed_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(message_uid) DO UPDATE SET
                    content_sha256=excluded.content_sha256,
                    chunk_uid=excluded.chunk_uid,
                    create_time=excluded.create_time,
                    indexed_at=excluded.indexed_at
                """,
                (
                    row["message_uid"],
                    chunk["content_sha256"],
                    chunk["chunk_uid"],
                    row["create_time"],
                    utc_now_iso(),
                ),
            )
            indexed += 1
            label = row["type_label"] or "unknown"
            type_counts[label] = type_counts.get(label, 0) + 1

        if max_time >= since_time:
            set_meta(ai_conn, "last_source_create_time", max_time)
        set_meta(ai_conn, "source_memory_db", str(source_memory_db))
        set_meta(ai_conn, "vector_dim", dim)
        set_meta(ai_conn, "updated_at", utc_now_iso())

        total_chunks = ai_conn.execute("SELECT COUNT(*) AS n FROM ai_chunks").fetchone()["n"]
        total_messages = ai_conn.execute("SELECT COUNT(*) AS n FROM ai_indexed_messages").fetchone()["n"]
        finished_at = utc_now_iso()
        details = {
            "type_counts": type_counts,
            "last_source_create_time": max_time,
            "total_chunks": total_chunks,
            "total_indexed_messages": total_messages,
            "elapsed_seconds": round(time.time() - started_mono, 3),
        }
        ai_conn.execute(
            """
            UPDATE ai_index_runs
            SET finished_at=?, scanned_messages=?, indexed_messages=?,
                skipped_messages=?, details_json=?
            WHERE id=?
            """,
            (
                finished_at,
                scanned,
                indexed,
                skipped,
                json.dumps(details, ensure_ascii=False),
                run_id,
            ),
        )

    return {
        "ok": True,
        "started_at": started_at,
        "finished_at": finished_at,
        "source_memory_db": str(source_memory_db),
        "ai_db": str(ai_db),
        "scanned_messages": scanned,
        "indexed_messages": indexed,
        "skipped_messages": skipped,
        **details,
    }


def sanitize_fts_query(query: str) -> str:
    tokens = terms_for_text(query)
    tokens = [token.replace('"', "") for token in tokens if token.strip()]
    if not tokens:
        return ""
    return " OR ".join(f'"{token}"' for token in tokens[:16])


def keyword_score(query_terms: list[str], text: str) -> float:
    if not query_terms:
        return 0.0
    lowered = (text or "").lower()
    hits = sum(1 for term in query_terms if term and term in lowered)
    return hits / max(1, len(query_terms))


def candidate_chunk_ids(
    conn: sqlite3.Connection,
    query: str,
    chat: str = "",
    days: int = 0,
    max_candidates: int = 1200,
) -> dict[str, float]:
    candidates: dict[str, float] = {}
    params = []
    filters = []
    if chat:
        filters.append("chat_username=?")
        params.append(chat)
    if days > 0:
        filters.append("COALESCE(end_time, 0) >= ?")
        params.append(int(time.time()) - days * 86400)
    where = (" WHERE " + " AND ".join(filters)) if filters else ""

    fts_query = sanitize_fts_query(query)
    if fts_query and ensure_fts(conn):
        try:
            fts_params = [fts_query]
            fts_filter = ""
            if chat:
                fts_filter = " AND chat_username=?"
                fts_params.append(chat)
            for row in conn.execute(
                f"""
                SELECT chunk_uid, bm25(ai_chunks_fts) AS rank
                FROM ai_chunks_fts
                WHERE ai_chunks_fts MATCH ? {fts_filter}
                LIMIT ?
                """,
                (*fts_params, max_candidates),
            ):
                candidates[row["chunk_uid"]] = max(candidates.get(row["chunk_uid"], 0.0), 1.0)
        except sqlite3.Error:
            pass

    like = f"%{query.strip()}%"
    if query.strip():
        for row in conn.execute(
            f"""
            SELECT chunk_uid
            FROM ai_chunks
            {where + (' AND ' if where else ' WHERE ')} text LIKE ?
            ORDER BY end_time DESC
            LIMIT ?
            """,
            (*params, like, max_candidates // 2),
        ):
            candidates[row["chunk_uid"]] = max(candidates.get(row["chunk_uid"], 0.0), 0.8)

    for row in conn.execute(
        f"""
        SELECT chunk_uid
        FROM ai_chunks
        {where}
        ORDER BY end_time DESC
        LIMIT ?
        """,
        (*params, min(400, max_candidates)),
    ):
        candidates.setdefault(row["chunk_uid"], 0.05)
    return candidates


def search_chunks(
    ai_db: Path,
    query: str,
    chat: str = "",
    limit: int = 8,
    days: int = 0,
) -> dict:
    if not ai_db.exists():
        return {"query": query, "results": [], "error": "ai memory db not found"}
    query = (query or "").strip()
    if not query:
        return {"query": query, "results": []}
    limit = max(1, min(int(limit), 50))
    query_vec, _ = vector_for_text(query)
    query_terms = terms_for_text(query)
    now_ts = int(time.time())

    with open_ai_db(ai_db) as conn:
        init_ai_db(conn)
        candidates = candidate_chunk_ids(conn, query, chat=chat, days=days)
        if not candidates:
            return {"query": query, "results": []}
        placeholders = ",".join("?" for _ in candidates)
        rows = conn.execute(
            f"""
            SELECT c.*, v.dim, v.vector
            FROM ai_chunks c
            JOIN ai_vectors v ON v.chunk_uid = c.chunk_uid
            WHERE c.chunk_uid IN ({placeholders})
            """,
            tuple(candidates.keys()),
        ).fetchall()

    scored = []
    for row in rows:
        vec = unpack_vector(row["vector"], row["dim"])
        semantic = cosine(query_vec, vec)
        keyword = keyword_score(query_terms, row["text"])
        age_days = max(0.0, (now_ts - int(row["end_time"] or now_ts)) / 86400)
        recency = 1.0 / (1.0 + age_days / 30.0)
        score = 0.68 * semantic + 0.22 * keyword + 0.10 * recency + 0.05 * candidates[row["chunk_uid"]]
        source = json.loads(row["source_json"])
        scored.append(
            {
                "score": round(float(score), 6),
                "semantic_score": round(float(semantic), 6),
                "keyword_score": round(float(keyword), 6),
                "recency_score": round(float(recency), 6),
                "chunk_uid": row["chunk_uid"],
                "chat_username": row["chat_username"],
                "chat_display_name": row["chat_display_name"],
                "sender_hint": row["sender_hint"],
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "time_text": unix_to_local_text(row["end_time"]),
                "type_label": row["type_label"],
                "text": row["text"],
                "source": source,
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return {"query": query, "results": scored[:limit]}


def list_chats(source_memory_db: Path, ai_db: Path) -> dict:
    if not source_memory_db.exists():
        return {"chats": [], "error": "source memory db not found"}
    with open_source_db(source_memory_db) as source_conn:
        rows = source_conn.execute(
            """
            SELECT c.username, c.display_name, c.is_group,
                   COUNT(m.message_uid) AS message_count,
                   MAX(m.create_time) AS latest_time
            FROM chats c
            LEFT JOIN messages m ON m.chat_username = c.username
            GROUP BY c.username
            ORDER BY COALESCE(MAX(m.create_time), c.sort_timestamp, c.last_timestamp, 0) DESC
            """
        ).fetchall()
    indexed_counts = {}
    if ai_db.exists():
        with open_ai_db(ai_db) as ai_conn:
            init_ai_db(ai_conn)
            indexed_counts = {
                row["chat_username"]: row["n"]
                for row in ai_conn.execute(
                    "SELECT chat_username, COUNT(*) AS n FROM ai_chunks GROUP BY chat_username"
                )
            }
    chats = []
    for row in rows:
        chats.append(
            {
                "username": row["username"],
                "display_name": row["display_name"],
                "is_group": row["is_group"],
                "message_count": row["message_count"],
                "indexed_count": indexed_counts.get(row["username"], 0),
                "latest_time": row["latest_time"],
                "latest_time_text": unix_to_local_text(row["latest_time"]),
            }
        )
    return {"chats": chats}


def recent_messages(source_memory_db: Path, chat: str, limit: int = 20) -> list[dict]:
    if not source_memory_db.exists() or not chat:
        return []
    limit = max(1, min(int(limit), 100))
    with open_source_db(source_memory_db) as conn:
        rows = conn.execute(
            """
            SELECT message_uid, chat_username, chat_display_name, local_id, type_label,
                   create_time, source, message_content, compress_content, content_sha256
            FROM messages
            WHERE chat_username=?
            ORDER BY create_time DESC, local_id DESC
            LIMIT ?
            """,
            (chat, limit),
        ).fetchall()
    output = []
    for row in rows:
        sender, text = clean_message_text(row)
        output.append(
            {
                "message_uid": row["message_uid"],
                "chat_username": row["chat_username"],
                "chat_display_name": row["chat_display_name"],
                "sender_hint": sender,
                "type_label": row["type_label"],
                "create_time": row["create_time"],
                "time_text": unix_to_local_text(row["create_time"]),
                "text": text,
            }
        )
    return output


def build_context(
    source_memory_db: Path,
    ai_db: Path,
    chat: str,
    query: str,
    recent_limit: int = 20,
    memory_limit: int = 8,
) -> dict:
    recent = recent_messages(source_memory_db, chat, recent_limit)
    memories = search_chunks(ai_db, query, chat=chat, limit=memory_limit).get("results", []) if query else []
    lines = ["# Recent messages"]
    for item in reversed(recent):
        speaker = item["sender_hint"] or "me"
        lines.append(f"- {item['time_text']} {speaker}: {item['text']}")
    if memories:
        lines.append("\n# Relevant long-term memories")
        for item in memories:
            source = item.get("source") or {}
            speaker = item["sender_hint"] or "me"
            content = source.get("content") or item["text"]
            lines.append(f"- {item['time_text']} {speaker}: {content}")
    return {
        "chat": chat,
        "query": query,
        "recent": recent,
        "memories": memories,
        "prompt_context": "\n".join(lines),
    }


def status(source_memory_db: Path, ai_db: Path, status_file: Path | None = None) -> dict:
    payload = {
        "ok": ai_db.exists(),
        "source_memory_db": str(source_memory_db),
        "ai_db": str(ai_db),
    }
    if source_memory_db.exists():
        with open_source_db(source_memory_db) as source_conn:
            payload["source_messages"] = source_conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
            payload["source_chats"] = source_conn.execute("SELECT COUNT(*) AS n FROM chats").fetchone()["n"]
    if ai_db.exists():
        with open_ai_db(ai_db) as conn:
            init_ai_db(conn)
            payload["indexed_chunks"] = conn.execute("SELECT COUNT(*) AS n FROM ai_chunks").fetchone()["n"]
            payload["indexed_messages"] = conn.execute("SELECT COUNT(*) AS n FROM ai_indexed_messages").fetchone()["n"]
            payload["last_source_create_time"] = get_meta(conn, "last_source_create_time", "0")
            payload["updated_at"] = get_meta(conn, "updated_at", "")
            row = conn.execute(
                """
                SELECT started_at, finished_at, scanned_messages, indexed_messages,
                       skipped_messages, details_json
                FROM ai_index_runs
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            payload["last_run"] = dict(row) if row else None
    if status_file and status_file.exists():
        try:
            payload["worker"] = json.loads(status_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return payload

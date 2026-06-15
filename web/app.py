#!/usr/bin/env python3
"""Small read-only web UI/API for the local WeChat memory database."""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "memory"))

from message_parse import message_display_parts

STATIC_DIR = Path(__file__).resolve().parent / "static"
MEMORY_DB = ROOT / "runtime/memory/wechat_memory.sqlite"
STATUS_FILE = ROOT / "runtime/memory/sync_status.json"
RUNTIME_DIR = ROOT / "runtime"
MEDIA_DIR = RUNTIME_DIR / "media"


def json_response(handler: BaseHTTPRequestHandler, payload, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler: BaseHTTPRequestHandler, text: str, status: int = 404) -> None:
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def clamp_int(value, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, parsed))


def db_connect() -> sqlite3.Connection:
    uri = f"file:{MEMORY_DB}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def checkpoint_memory_db() -> None:
    conn = sqlite3.connect(str(MEMORY_DB), timeout=2)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def row_dict(row: sqlite3.Row) -> dict:
    return {key: json_safe(row[key]) for key in row.keys()}


def json_safe(value):
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return f"[binary:{len(value)} bytes]"
    return value


def is_noisy_text(value: str | None) -> bool:
    if not value:
        return False
    sample = value[:200]
    control = sum(1 for ch in sample if ord(ch) < 32 and ch not in "\n\r\t")
    replacement = sample.count("\ufffd")
    return control + replacement > 4


def display_for_message(item: dict) -> dict:
    parts = message_display_parts(
        item.get("message_content"),
        item.get("compress_content"),
        item.get("type_label"),
        item.get("source"),
    )
    sender = parts.pop("sender_hint", "")
    display = parts.get("display_content", "")
    item.update(parts)
    item["sender_hint"] = sender
    item["is_outgoing"] = 1 if not sender else 0
    media_path = item.get("media_path") or item.get("thumb_path")
    if media_path and item.get("media_status") in ("ready",):
        clean_path = str(media_path).replace("\\", "/")
        if clean_path.startswith("media/"):
            clean_path = clean_path.removeprefix("media/")
        item["media_url"] = "/media/" + clean_path
    item["display_content"] = display
    if is_noisy_text(item.get("source")):
        item["source"] = ""
    return item


def read_status() -> dict:
    if not STATUS_FILE.exists():
        return {"ok": None, "message": "sync status not found"}
    try:
        with STATUS_FILE.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc)}


def api_summary() -> dict:
    with db_connect() as conn:
        chats = conn.execute("SELECT COUNT(*) AS n FROM chats").fetchone()["n"]
        messages = conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
        groups = conn.execute("SELECT COUNT(*) AS n FROM chats WHERE is_group=1").fetchone()["n"]
        type_counts = [
            row_dict(row)
            for row in conn.execute(
                "SELECT type_label AS type, COUNT(*) AS count FROM messages GROUP BY type_label ORDER BY count DESC"
            )
        ]
        bounds = conn.execute("SELECT MIN(create_time) AS min_time, MAX(create_time) AS max_time FROM messages").fetchone()
        latest = conn.execute(
            """
            SELECT chat_username, chat_display_name, create_time, type_label
            FROM messages
            ORDER BY create_time DESC, local_id DESC
            LIMIT 1
            """
        ).fetchone()
    return {
        "chats": chats,
        "groups": groups,
        "messages": messages,
        "type_counts": type_counts,
        "time_range": row_dict(bounds),
        "latest_message": row_dict(latest) if latest else None,
        "sync": read_status(),
    }


def api_chats(query: dict) -> dict:
    search = (query.get("q") or [""])[0].strip()
    with db_connect() as conn:
        params = []
        where = ""
        if search:
            where = "WHERE username LIKE ? OR display_name LIKE ?"
            like = f"%{search}%"
            params.extend([like, like])
        rows = conn.execute(
            f"""
            SELECT c.username, c.display_name, c.is_group, c.last_timestamp, c.sort_timestamp,
                   COUNT(m.message_uid) AS message_count,
                   MAX(m.create_time) AS latest_time
            FROM chats c
            LEFT JOIN messages m ON m.chat_username = c.username
            {where}
            GROUP BY c.username
            ORDER BY COALESCE(MAX(m.create_time), c.sort_timestamp, c.last_timestamp, 0) DESC
            """,
            params,
        ).fetchall()
    return {"chats": [row_dict(row) for row in rows]}


def api_messages(query: dict) -> dict:
    chat = (query.get("chat") or [""])[0]
    limit = clamp_int((query.get("limit") or [80])[0], 80, 1, 300)
    before = (query.get("before") or [""])[0]
    after = (query.get("after") or [""])[0]
    msg_type = (query.get("type") or [""])[0]
    if not chat:
        return {"messages": []}

    clauses = ["m.chat_username = ?"]
    params = [chat]
    if before:
        clauses.append("m.create_time < ?")
        params.append(clamp_int(before, 0, 0, 99_999_999_999))
    if after:
        clauses.append("m.create_time > ?")
        params.append(clamp_int(after, 0, 0, 99_999_999_999))
    if msg_type:
        clauses.append("m.type_label = ?")
        params.append(msg_type)
    params.append(limit)

    with db_connect() as conn:
        rows = conn.execute(
            f"""
            SELECT m.message_uid, m.chat_username, m.chat_display_name, m.local_id, m.server_id,
                   m.local_type, m.base_type, m.app_subtype, m.type_label, m.real_sender_id,
                   m.create_time, m.source, m.message_content, m.compress_content,
                   mm.media_path, mm.thumb_path, mm.mime_type, mm.width, mm.height,
                   mm.status AS media_status, mm.error AS media_error
            FROM messages m
            LEFT JOIN message_media mm ON mm.message_uid = m.message_uid
            WHERE {" AND ".join(clauses)}
            ORDER BY m.create_time DESC, m.local_id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    messages = [display_for_message(row_dict(row)) for row in rows]
    return {"messages": messages}


def api_search(query: dict) -> dict:
    term = (query.get("q") or [""])[0].strip()
    limit = clamp_int((query.get("limit") or [80])[0], 80, 1, 200)
    chat = (query.get("chat") or [""])[0]
    msg_type = (query.get("type") or [""])[0]
    if not term:
        return {"results": []}
    clauses = ["(m.message_content LIKE ? OR m.compress_content LIKE ? OR m.source LIKE ?)"]
    like = f"%{term}%"
    params = [like, like, like]
    if chat:
        clauses.append("m.chat_username = ?")
        params.append(chat)
    if msg_type:
        clauses.append("m.type_label = ?")
        params.append(msg_type)
    params.append(limit)
    with db_connect() as conn:
        rows = conn.execute(
            f"""
            SELECT m.message_uid, m.chat_username, m.chat_display_name, m.local_id, m.type_label,
                   m.create_time, m.source, m.message_content, m.compress_content,
                   mm.media_path, mm.thumb_path, mm.mime_type, mm.width, mm.height,
                   mm.status AS media_status, mm.error AS media_error
            FROM messages m
            LEFT JOIN message_media mm ON mm.message_uid = m.message_uid
            WHERE {" AND ".join(clauses)}
            ORDER BY m.create_time DESC, m.local_id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return {"results": [display_for_message(row_dict(row)) for row in rows]}


def api_types() -> dict:
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT type_label AS type, COUNT(*) AS count FROM messages GROUP BY type_label ORDER BY count DESC"
        ).fetchall()
    return {"types": [row_dict(row) for row in rows]}


def serve_media(handler: BaseHTTPRequestHandler, path: str) -> None:
    rel = unquote(path.removeprefix("/media/")).lstrip("/")
    target = (MEDIA_DIR / rel).resolve()
    media_root = MEDIA_DIR.resolve()
    if target != media_root and media_root not in target.parents:
        text_response(handler, "not found", 404)
        return
    if not target.exists() or not target.is_file():
        text_response(handler, "not found", 404)
        return
    mime, _ = mimetypes.guess_type(str(target))
    handler.send_response(200)
    handler.send_header("Content-Type", mime or "application/octet-stream")
    handler.send_header("Content-Length", str(target.stat().st_size))
    handler.send_header("Cache-Control", "private, max-age=60")
    handler.end_headers()
    with target.open("rb") as f:
        shutil.copyfileobj(f, handler.wfile)


def serve_static(handler: BaseHTTPRequestHandler, path: str) -> None:
    if path == "/":
        target = STATIC_DIR / "index.html"
    else:
        rel = unquote(path).lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            text_response(handler, "not found", 404)
            return
    if not target.exists() or not target.is_file():
        text_response(handler, "not found", 404)
        return
    mime, _ = mimetypes.guess_type(str(target))
    body = target.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", mime or "application/octet-stream")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A003
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} {fmt % args}", flush=True)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path.startswith("/api/"):
                json_response(self, self.handle_api(parsed.path, query))
            elif parsed.path.startswith("/media/"):
                serve_media(self, parsed.path)
            else:
                serve_static(self, parsed.path)
        except sqlite3.Error as exc:
            json_response(self, {"error": f"database error: {exc}"}, 500)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 500)

    def handle_api(self, path: str, query: dict) -> dict:
        try:
            return route_api(path, query)
        except sqlite3.OperationalError as exc:
            if "disk I/O error" not in str(exc):
                raise
            checkpoint_memory_db()
            return route_api(path, query)


def route_api(path: str, query: dict) -> dict:
    if path == "/api/summary":
        return api_summary()
    if path == "/api/chats":
        return api_chats(query)
    if path == "/api/messages":
        return api_messages(query)
    if path == "/api/search":
        return api_search(query)
    if path == "/api/types":
        return api_types()
    if path == "/api/status":
        return read_status()
    return {"error": "not found"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve local WeChat memory web UI")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving WeChat memory UI at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

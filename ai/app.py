#!/usr/bin/env python3
"""HTTP API for local WeChat AI memory."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "memory"))

from ai_memory_core import build_context, index_once, list_chats, search_chunks, status


CONFIG = {
    "source_memory_db": ROOT / "runtime/memory/wechat_memory.sqlite",
    "ai_db": ROOT / "runtime/ai-memory/ai_memory.sqlite",
    "status_file": ROOT / "runtime/ai-memory/ai_status.json",
    "index_interval": 5.0,
    "batch_size": 2000,
    "overlap_seconds": 3600,
    "vector_dim": 384,
}
STOP_INDEXER = threading.Event()


def json_response(handler: BaseHTTPRequestHandler, payload, status_code: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def clamp_int(value, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, parsed))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def run_indexer() -> None:
    while not STOP_INDEXER.is_set():
        try:
            payload = index_once(
                source_memory_db=CONFIG["source_memory_db"],
                ai_db=CONFIG["ai_db"],
                batch_size=CONFIG["batch_size"],
                overlap_seconds=CONFIG["overlap_seconds"],
                dim=CONFIG["vector_dim"],
            )
            payload["interval_seconds"] = CONFIG["index_interval"]
            write_json(CONFIG["status_file"], payload)
            print(json.dumps(payload, ensure_ascii=False), flush=True)
        except Exception as exc:
            payload = {
                "ok": False,
                "finished_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "interval_seconds": CONFIG["index_interval"],
                "error": str(exc),
            }
            write_json(CONFIG["status_file"], payload)
            print(json.dumps(payload, ensure_ascii=False), flush=True)
        STOP_INDEXER.wait(max(float(CONFIG["index_interval"]), 1.0))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A003
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} {fmt % args}", flush=True)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            payload = route_get(parsed.path, query)
            json_response(self, payload, 200 if "error" not in payload else 404)
        except sqlite3.Error as exc:
            json_response(self, {"error": f"database error: {exc}"}, 500)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 500)

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        length = clamp_int(self.headers.get("Content-Length"), 0, 0, 2_000_000)
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            json_response(self, {"error": f"invalid json: {exc}"}, 400)
            return
        try:
            result = route_post(parsed.path, payload)
            json_response(self, result, 200 if "error" not in result else 404)
        except sqlite3.Error as exc:
            json_response(self, {"error": f"database error: {exc}"}, 500)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 500)


def route_get(path: str, query: dict) -> dict:
    if path in ("/", "/api/status"):
        return status(CONFIG["source_memory_db"], CONFIG["ai_db"], CONFIG["status_file"])
    if path == "/api/chats":
        return list_chats(CONFIG["source_memory_db"], CONFIG["ai_db"])
    if path == "/api/search":
        q = (query.get("q") or [""])[0]
        chat = (query.get("chat") or [""])[0]
        limit = clamp_int((query.get("limit") or [8])[0], 8, 1, 50)
        days = clamp_int((query.get("days") or [0])[0], 0, 0, 3650)
        return search_chunks(CONFIG["ai_db"], q, chat=chat, limit=limit, days=days)
    if path == "/api/context":
        q = (query.get("q") or [""])[0]
        chat = (query.get("chat") or [""])[0]
        recent_limit = clamp_int((query.get("recent_limit") or [20])[0], 20, 1, 100)
        memory_limit = clamp_int((query.get("memory_limit") or [8])[0], 8, 1, 50)
        if not chat:
            return {"error": "chat is required"}
        return build_context(CONFIG["source_memory_db"], CONFIG["ai_db"], chat, q, recent_limit, memory_limit)
    return {"error": "not found"}


def route_post(path: str, payload: dict) -> dict:
    if path == "/api/index":
        return index_once(
            source_memory_db=CONFIG["source_memory_db"],
            ai_db=CONFIG["ai_db"],
            batch_size=clamp_int(payload.get("batch_size"), 5000, 1, 100_000),
            overlap_seconds=clamp_int(payload.get("overlap_seconds"), 3600, 0, 86_400),
            dim=clamp_int(payload.get("vector_dim"), 384, 64, 4096),
        )
    if path == "/api/search":
        return search_chunks(
            CONFIG["ai_db"],
            payload.get("q") or payload.get("query") or "",
            chat=payload.get("chat") or "",
            limit=clamp_int(payload.get("limit"), 8, 1, 50),
            days=clamp_int(payload.get("days"), 0, 0, 3650),
        )
    if path == "/api/context":
        chat = payload.get("chat") or ""
        if not chat:
            return {"error": "chat is required"}
        return build_context(
            CONFIG["source_memory_db"],
            CONFIG["ai_db"],
            chat,
            payload.get("q") or payload.get("query") or "",
            recent_limit=clamp_int(payload.get("recent_limit"), 20, 1, 100),
            memory_limit=clamp_int(payload.get("memory_limit"), 8, 1, 50),
        )
    return {"error": "not found"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve local WeChat AI memory API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--source-memory-db", type=Path, default=CONFIG["source_memory_db"])
    parser.add_argument("--ai-db", type=Path, default=CONFIG["ai_db"])
    parser.add_argument("--status-file", type=Path, default=CONFIG["status_file"])
    parser.add_argument("--index-interval", type=float, default=CONFIG["index_interval"])
    parser.add_argument("--batch-size", type=int, default=CONFIG["batch_size"])
    parser.add_argument("--overlap-seconds", type=int, default=CONFIG["overlap_seconds"])
    parser.add_argument("--vector-dim", type=int, default=CONFIG["vector_dim"])
    parser.add_argument("--no-indexer", action="store_true")
    args = parser.parse_args(argv)
    CONFIG.update(
        {
            "source_memory_db": args.source_memory_db,
            "ai_db": args.ai_db,
            "status_file": args.status_file,
            "index_interval": args.index_interval,
            "batch_size": args.batch_size,
            "overlap_seconds": args.overlap_seconds,
            "vector_dim": args.vector_dim,
        }
    )
    if not args.no_indexer:
        threading.Thread(target=run_indexer, daemon=True, name="ai-memory-indexer").start()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving WeChat AI memory API at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STOP_INDEXER.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

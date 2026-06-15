#!/usr/bin/env python3
"""Command-line helper for the local WeChat AI memory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "memory"))

from ai_memory_core import build_context, index_once, list_chats, search_chunks, status


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Query or maintain WeChat AI memory")
    parser.add_argument("--source-memory-db", type=Path, default=Path("runtime/memory/wechat_memory.sqlite"))
    parser.add_argument("--ai-db", type=Path, default=Path("runtime/ai-memory/ai_memory.sqlite"))
    parser.add_argument("--status-file", type=Path, default=Path("runtime/ai-memory/ai_status.json"))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status")
    sub.add_parser("chats")

    index_cmd = sub.add_parser("index")
    index_cmd.add_argument("--batch-size", type=int, default=100000)
    index_cmd.add_argument("--overlap-seconds", type=int, default=86400)
    index_cmd.add_argument("--vector-dim", type=int, default=384)

    search_cmd = sub.add_parser("search")
    search_cmd.add_argument("query")
    search_cmd.add_argument("--chat", default="")
    search_cmd.add_argument("--limit", type=int, default=8)
    search_cmd.add_argument("--days", type=int, default=0)

    context_cmd = sub.add_parser("context")
    context_cmd.add_argument("query")
    context_cmd.add_argument("--chat", required=True)
    context_cmd.add_argument("--recent-limit", type=int, default=20)
    context_cmd.add_argument("--memory-limit", type=int, default=8)
    return parser.parse_args(argv)


def resolve(path: Path) -> Path:
    if path.is_absolute():
        return path
    return Path.cwd() / path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source_memory_db = resolve(args.source_memory_db)
    ai_db = resolve(args.ai_db)
    status_file = resolve(args.status_file)

    if args.command == "status":
        payload = status(source_memory_db, ai_db, status_file)
    elif args.command == "chats":
        payload = list_chats(source_memory_db, ai_db)
    elif args.command == "index":
        payload = index_once(
            source_memory_db,
            ai_db,
            batch_size=args.batch_size,
            overlap_seconds=args.overlap_seconds,
            dim=args.vector_dim,
        )
    elif args.command == "search":
        payload = search_chunks(ai_db, args.query, chat=args.chat, limit=args.limit, days=args.days)
    elif args.command == "context":
        payload = build_context(
            source_memory_db,
            ai_db,
            args.chat,
            args.query,
            recent_limit=args.recent_limit,
            memory_limit=args.memory_limit,
        )
    else:
        raise RuntimeError(f"unknown command: {args.command}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

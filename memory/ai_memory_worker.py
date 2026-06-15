#!/usr/bin/env python3
"""Periodic AI memory indexing worker."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

from ai_memory_core import index_once, status, utc_now_iso


STOP = False


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def handle_stop(signum, frame) -> None:  # noqa: ARG001
    global STOP
    STOP = True


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Run local WeChat AI memory indexer")
    parser.add_argument("--interval", type=float, default=5.0, help="Polling interval seconds")
    parser.add_argument("--source-memory-db", type=Path, default=Path("runtime/memory/wechat_memory.sqlite"))
    parser.add_argument("--ai-db", type=Path, default=Path("runtime/ai-memory/ai_memory.sqlite"))
    parser.add_argument("--status-file", type=Path, default=Path("runtime/ai-memory/ai_status.json"))
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument("--overlap-seconds", type=int, default=3600)
    parser.add_argument("--vector-dim", type=int, default=384)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args(argv)


def resolve_args(args):
    root = Path.cwd()
    for key in ("source_memory_db", "ai_db", "status_file"):
        value = getattr(args, key)
        if not value.is_absolute():
            setattr(args, key, root / value)
    return args


def run_once(args) -> dict:
    result = index_once(
        source_memory_db=args.source_memory_db,
        ai_db=args.ai_db,
        batch_size=args.batch_size,
        overlap_seconds=args.overlap_seconds,
        dim=args.vector_dim,
    )
    result["interval_seconds"] = args.interval
    return result


def main(argv: list[str] | None = None) -> int:
    args = resolve_args(parse_args(argv))
    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    while not STOP:
        try:
            payload = run_once(args)
            write_json(args.status_file, payload)
            print(json.dumps(payload, ensure_ascii=False), flush=True)
        except Exception as exc:
            payload = {
                "ok": False,
                "finished_at": utc_now_iso(),
                "interval_seconds": args.interval,
                "error": str(exc),
            }
            try:
                payload["status"] = status(args.source_memory_db, args.ai_db)
            except Exception:
                pass
            write_json(args.status_file, payload)
            print(json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)

        if args.once:
            return 0 if payload.get("ok") else 1
        deadline = time.time() + max(args.interval, 1.0)
        while not STOP and time.time() < deadline:
            time.sleep(min(0.25, deadline - time.time()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

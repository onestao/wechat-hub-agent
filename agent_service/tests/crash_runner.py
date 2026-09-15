"""Subprocess driver for the RC.14 V4 deterministic crash matrix (C1-C5).

Runs the real ``AgentService`` against a local mock Core over HTTP. The mock
Core is deliberately faithful to the frozen V1 contract, including the hard
``limit <= 200`` cap on ``/v1/events/poll`` that forces a 400-event local
atomic batch to be assembled from two polls.

Safety properties (same discipline as the Phase 3 bench harness):

* binds to ``127.0.0.1`` only, never contacts the production Core,
* refuses the production consumer id,
* hard-blocks ``POST /v1/send/text`` with HTTP 409 so no real send can happen,
* writes only to the ``--db`` path given on the command line.

Modes
-----
``once``
    Drive ``process_events_once()`` in a loop (optionally with recovery after
    an injected writer fault). Used by C1, C2, C3 and C5.
``serve``
    Run the real production entrypoint (``agent_service.app.main``) with
    workers started, so an externally delivered SIGTERM lands inside a batch.
    Used by C4.

Evidence is printed as one ``CRASH_RUNNER_RESULT=<json>`` line and written to
``--out``.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_service.crashpoint import armed_point  # noqa: E402
from agent_service.service import AgentService, AgentSettings  # noqa: E402

ACCOUNT_ID = "account-a"
IDENTITY_UUID = "identity-a-uuid"
INSTANCE_UUID = "instance-a-uuid"
ACCOUNTS = [
    {
        "account_id": ACCOUNT_ID,
        "display_name": "Crash Matrix A",
        "enabled": True,
        "instance_uuid": INSTANCE_UUID,
        "wechat_identity_uuid": IDENTITY_UUID,
        "identity_binding_state": "bound",
    }
]


def build_event(index: int, mix: str) -> dict[str, Any]:
    """Deterministic event for absolute 1-based ``index`` (cursor == index)."""
    if mix == "mixed" and index % 10 == 0:
        return {
            "event_id": f"crash-msg-{index}",
            "cursor": str(index),
            "account_id": ACCOUNT_ID,
            "event_type": "message.created",
            "occurred_at": "2026-09-15T00:00:00Z",
            "payload": {
                "message": {
                    "account_id": ACCOUNT_ID,
                    "message_id": f"msg-{index}",
                    "chat_id": "chat-crash",
                    "type": "text",
                    "direction": "incoming",
                    "created_at": "2026-09-15T00:00:00Z",
                    "text": f"crash matrix message {index}",
                    "author": {"member_id": "user-1", "display_name": "User One", "is_self": False},
                }
            },
        }
    return {
        "event_id": f"crash-evt-{index}",
        "cursor": str(index),
        "account_id": ACCOUNT_ID,
        "event_type": "status.created",
        "occurred_at": "2026-09-15T00:00:00Z",
        "payload": {"status": "online", "account_id": ACCOUNT_ID},
    }


class MockCore:
    """Cursor-authoritative mock Core with a file-backed checkpoint."""

    def __init__(self, state_path: Path, total_events: int, mix: str):
        self.state_path = state_path
        self.total_events = int(total_events)
        self.mix = mix
        self.lock = threading.Lock()
        self.state = self._load()
        self.polls = 0
        self.commits = 0
        self.sends: list[dict[str, Any]] = []
        # Cumulative across processes so a replay run cannot reset the counter
        # that proves "no duplicate external effect".
        self.send_blocked = int(self.state.get("send_blocked") or 0)

    def _load(self) -> dict[str, Any]:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {"cursor": 0, "commits": 0}

    def _save(self) -> None:
        self.state["commits"] = self.commits
        self.state["send_blocked"] = self.send_blocked
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def poll(self, after: int, limit: int) -> dict[str, Any]:
        # Faithful to Core: the contract caps limit at 200 regardless of ask.
        limit = max(1, min(int(limit), 200))
        start = max(int(after), int(self.state["cursor"])) + 1
        out = []
        cursor = start
        while cursor <= self.total_events and len(out) < limit:
            out.append(build_event(cursor, self.mix))
            cursor += 1
        nxt = int(out[-1]["cursor"]) if out else max(int(after), int(self.state["cursor"]))
        return {"events": out, "next_cursor": nxt, "has_more": cursor <= self.total_events}

    def commit(self, cursor: int) -> None:
        with self.lock:
            self.state["cursor"] = max(int(self.state["cursor"]), int(cursor))
            self.commits += 1
            self._save()


def make_handler(core: MockCore):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # noqa: A003
            return

        def _json(self, obj: Any, status: int = 200) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict[str, Any]:
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}

        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path == "/health":
                return self._json({"status": "ok", "contract_version": 1, "service": "crash-mock-core"})
            if parsed.path == "/v1/accounts":
                return self._json({"accounts": ACCOUNTS})
            if parsed.path == "/v1/events/poll":
                after = int((query.get("after") or ["0"])[0])
                limit = int((query.get("limit") or ["200"])[0])
                with core.lock:
                    core.polls += 1
                return self._json(core.poll(after, limit))
            if parsed.path.endswith("/chats"):
                return self._json({"chats": []})
            return self._json({"error": {"code": "not_found", "message": parsed.path}}, 404)

        def do_POST(self):  # noqa: N802
            parsed = urlparse(self.path)
            payload = self._body()
            if parsed.path == "/v1/events/commit":
                cursor = int(payload.get("processed_through_cursor") or 0)
                core.commit(cursor)
                return self._json(
                    {
                        "consumer_id": payload.get("consumer_id"),
                        "acked_count": len(payload.get("event_ids") or []),
                        "checkpoint": {
                            "consumer_id": payload.get("consumer_id"),
                            "processed_through_cursor": cursor,
                        },
                    }
                )
            if parsed.path == "/v1/events/ack":
                return self._json(
                    {
                        "consumer_id": payload.get("consumer_id"),
                        "acked_event_ids": payload.get("event_ids") or [],
                        "acked_count": len(payload.get("event_ids") or []),
                    }
                )
            if parsed.path == "/v1/events/checkpoint":
                core.commit(int(payload.get("processed_through_cursor") or 0))
                return self._json(
                    {
                        "consumer_id": payload.get("consumer_id"),
                        "processed_through_cursor": core.state["cursor"],
                    }
                )
            if parsed.path == "/v1/send/text":
                with core.lock:
                    core.send_blocked += 1
                    core._save()
                return self._json(
                    {"error": {"code": "crash_matrix_send_blocked", "message": "sends hard-blocked"}}, 409
                )
            return self._json({"error": {"code": "not_found", "message": parsed.path}}, 404)

    return Handler


def start_mock_core(core: MockCore) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(core))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def register_monitors(service: AgentService, *, external: bool) -> None:
    service.storage.upsert_monitor(
        {
            "monitor_id": "crash-record",
            "name": "crash record",
            "account_id": ACCOUNT_ID,
            "event_type": "message.created",
            "action": "record",
            "enabled": True,
        }
    )
    if external:
        service.storage.upsert_monitor(
            {
                "monitor_id": "crash-send",
                "name": "crash send",
                "account_id": ACCOUNT_ID,
                "event_type": "message.created",
                "action": "send_text",
                "expected_wechat_identity_uuid": IDENTITY_UUID,
                "action_config": {"text": "crash-matrix-auto-reply"},
                "enabled": True,
            }
        )


def run_once_mode(args, core: MockCore, base: str) -> dict[str, Any]:
    settings = AgentSettings(
        core_url=base,
        db_path=Path(args.db),
        consumer_id=args.consumer_id,
        poll_interval_seconds=0.0,
        poll_timeout_seconds=0,
        poll_batch_size=args.batch,
        scheduler_interval_seconds=300.0,
        vector_dim=384,
        core_commit_batch_threshold=args.commit_threshold,
        core_commit_interval_seconds=args.commit_interval,
    )
    service = AgentService(settings)
    register_monitors(service, external=args.external_monitor)

    batches: list[dict[str, Any]] = []
    recovered: dict[str, Any] | None = None
    reconciled: dict[str, Any] | None = None
    for idx in range(1, args.max_batches + 1):
        result = service.process_events_once()
        batches.append(
            {
                "idx": idx,
                "ok": bool(result.get("ok")),
                "error": result.get("error"),
                "error_code": result.get("error_code"),
                "events": result.get("events"),
                "processed": result.get("processed"),
                "duplicates": result.get("duplicates"),
                "cursor": result.get("cursor"),
                "core_polls": result.get("core_polls"),
                "has_more": result.get("has_more"),
            }
        )
        if result.get("ok"):
            if int(result.get("events") or 0) == 0:
                break
            continue
        if not args.recover_on_failure:
            break
        # C5 recovery path: discard the uncertain writer, reconcile, retry once.
        reconciled = service.storage.reconcile()
        retry = service.process_events_once()
        recovered = {
            "ok": bool(retry.get("ok")),
            "error": retry.get("error"),
            "error_code": retry.get("error_code"),
            "events": retry.get("events"),
            "processed": retry.get("processed"),
            "duplicates": retry.get("duplicates"),
            "cursor": retry.get("cursor"),
        }
        batches.append({"idx": f"{idx}-retry", **recovered})
        if not retry.get("ok"):
            break

    evidence = {
        "mode": "once",
        "armed_point": args.armed_point,
        "batches": batches,
        "reconciled": reconciled,
        "writer_stats": service.storage.writer_stats(),
        "cursor": service.storage.get_meta("core_cursor", "0"),
        "counts": service.storage.counts(),
        "memory_chunks": service.memory.count(),
        "core_state_cursor": core.state["cursor"],
        "core_polls": core.polls,
        "core_commits": core.commits,
        "send_blocked": core.send_blocked,
    }
    shutdown = service.shutdown()
    evidence["shutdown"] = shutdown
    evidence["cursor_after_shutdown"] = service.storage.get_meta("core_cursor", "0") if not shutdown else None
    return evidence


def run_serve_mode(args, core: MockCore, base: str) -> dict[str, Any]:
    from agent_service import app as app_module

    argv = [
        "--db", args.db,
        "--core-url", base,
        "--consumer-id", args.consumer_id,
        "--poll-batch", str(args.batch),
        "--poll-interval", "0.25",
        "--host", "127.0.0.1",
        "--port", str(args.port),
    ]
    if args.ready_file:
        Path(args.ready_file).write_text("ready\n", encoding="utf-8")
    code = app_module.main(argv)
    return {"mode": "serve", "armed_point": args.armed_point, "exit_code": code,
            "core_state_cursor": core.state["cursor"], "core_polls": core.polls,
            "core_commits": core.commits, "send_blocked": core.send_blocked}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--consumer-id", required=True)
    parser.add_argument("--mode", choices=["once", "serve"], default="once")
    parser.add_argument("--mix", choices=["status", "mixed"], default="status")
    parser.add_argument("--events", type=int, default=400)
    parser.add_argument("--batch", type=int, default=400)
    parser.add_argument("--commit-threshold", type=int, default=600)
    parser.add_argument("--commit-interval", type=float, default=20.0)
    parser.add_argument("--max-batches", type=int, default=10)
    parser.add_argument("--recover-on-failure", action="store_true")
    parser.add_argument("--external-monitor", action="store_true")
    parser.add_argument("--ready-file", default="")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)

    if args.consumer_id == "wechat-agent":
        print("REFUSING: consumer_id must not be the production consumer id", file=sys.stderr)
        return 2

    args.armed_point = armed_point()
    core = MockCore(Path(args.state), args.events, args.mix)
    server, base = start_mock_core(core)
    print(f"CRASH_RUNNER_MOCK_CORE={base} armed={args.armed_point or 'none'}", flush=True)

    if args.mode == "serve":
        # The real entrypoint installs its own SIGTERM handler.
        evidence = run_serve_mode(args, core, base)
    else:
        evidence = run_once_mode(args, core, base)

    server.shutdown()
    Path(args.out).write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print("CRASH_RUNNER_RESULT=" + json.dumps(evidence), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

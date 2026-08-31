from __future__ import annotations

import argparse
import json
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .legacy_ai import builtin_skills
from .mcp import MCPServer
from .service import AgentService, AgentSettings


MAX_JSON_BODY = 2_000_000


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def query_first(query: dict[str, list[str]], name: str, default: str = "") -> str:
    return str((query.get(name) or [default])[0] or default)


def query_int(query: dict[str, list[str]], name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(query_first(query, name, str(default)))
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


class AgentHandler(BaseHTTPRequestHandler):
    service: AgentService
    mcp: MCPServer
    server_version = "WeChatAgent/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"wechat-agent http: {fmt % args}", flush=True)

    def _send_json(self, status: int, payload: Any, *, content_type: str = "application/json; charset=utf-8") -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body_json(self) -> Any:
        length_raw = self.headers.get("Content-Length", "0")
        try:
            length = int(length_raw)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length < 0 or length > MAX_JSON_BODY:
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        try:
            if path in {"/", "/health", "/api/status"}:
                self._send_json(200, self.service.status())
                return
            if path == "/api/skills":
                public = []
                for item in builtin_skills():
                    public.append({key: value for key, value in item.items() if key != "body"})
                self._send_json(200, {"skills": public})
                return
            if path == "/api/records":
                self._send_json(
                    200,
                    {
                        "records": self.service.storage.list_records(
                            account_id=query_first(query, "account_id"),
                            chat_id=query_first(query, "chat_id"),
                            kind=query_first(query, "kind"),
                            query=query_first(query, "q"),
                            limit=query_int(query, "limit", 100, 1, 500),
                        )
                    },
                )
                return
            if path == "/api/monitors":
                self._send_json(200, {"monitors": self.service.storage.list_monitors()})
                return
            if path == "/api/templates":
                self._send_json(200, {"templates": self.service.storage.list_templates()})
                return
            if path == "/api/schedules":
                self._send_json(200, {"schedules": self.service.storage.list_schedules()})
                return
            if path == "/api/memory/search":
                self._send_json(
                    200,
                    self.service.memory.search(
                        query_first(query, "q"),
                        account_id=query_first(query, "account_id"),
                        chat_id=query_first(query, "chat_id"),
                        limit=query_int(query, "limit", 8, 1, 50),
                    ),
                )
                return
            if path == "/api/memory/context":
                account_id = query_first(query, "account_id")
                chat_id = query_first(query, "chat_id")
                if not account_id or not chat_id:
                    self._send_json(400, {"ok": False, "error": "account_id and chat_id are required"})
                    return
                self._send_json(
                    200,
                    self.service.memory.context(
                        account_id,
                        chat_id,
                        query_first(query, "q"),
                        recent_limit=query_int(query, "recent_limit", 20, 1, 200),
                        memory_limit=query_int(query, "memory_limit", 8, 1, 50),
                    ),
                )
                return
            if path == "/mcp":
                # Streamable HTTP permits an SSE GET stream. This stateless
                # implementation exposes a short capability event; JSON-RPC
                # messages are sent via POST /mcp.
                body = b"event: endpoint\ndata: {\"name\":\"wechat-agent\",\"transport\":\"streamable-http\"}\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._send_json(404, {"ok": False, "error": "not found"})
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            payload = self._body_json()
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        try:
            if path == "/mcp":
                response = self.mcp.handle(payload)
                if response is None:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    self._send_json(200, response)
                return
            if path == "/api/poll":
                self._send_json(200, self.service.process_events_once())
                return
            if path == "/api/scheduler/run":
                self._send_json(200, self.service.run_scheduler_once())
                return
            if path == "/api/records":
                if not isinstance(payload, dict):
                    raise ValueError("record payload must be an object")
                self._send_json(201, self.service.storage.create_record(payload))
                return
            if path == "/api/monitors":
                if not isinstance(payload, dict):
                    raise ValueError("monitor payload must be an object")
                self._send_json(200, self.service.storage.upsert_monitor(payload))
                return
            if path == "/api/templates":
                if not isinstance(payload, dict):
                    raise ValueError("template payload must be an object")
                self._send_json(200, self.service.storage.upsert_template(payload))
                return
            if path == "/api/schedules":
                if not isinstance(payload, dict):
                    raise ValueError("schedule payload must be an object")
                self._send_json(200, self.service.storage.upsert_schedule(payload))
                return
            self._send_json(404, {"ok": False, "error": "not found"})
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        prefix = "/api/records/"
        if path.startswith(prefix):
            record_id = unquote(path[len(prefix) :])
            if record_id and self.service.storage.delete_record(record_id):
                self._send_json(200, {"ok": True, "record_id": record_id})
            else:
                self._send_json(404, {"ok": False, "error": "record not found"})
            return
        self._send_json(404, {"ok": False, "error": "not found"})


def create_server(host: str, port: int, service: AgentService) -> ThreadingHTTPServer:
    mcp = MCPServer(service)
    handler = type("BoundAgentHandler", (AgentHandler,), {"service": service, "mcp": mcp})
    return ThreadingHTTPServer((host, port), handler)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    defaults = AgentSettings.from_env()
    parser = argparse.ArgumentParser(description="Decoupled WeChat Agent MCP/Monitor service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--core-url", default=defaults.core_url)
    parser.add_argument("--db", type=Path, default=defaults.db_path)
    parser.add_argument("--consumer-id", default=defaults.consumer_id)
    parser.add_argument("--poll-interval", type=float, default=defaults.poll_interval_seconds)
    parser.add_argument("--poll-timeout", type=int, default=defaults.poll_timeout_seconds)
    parser.add_argument("--poll-batch", type=int, default=defaults.poll_batch_size)
    parser.add_argument("--scheduler-interval", type=float, default=defaults.scheduler_interval_seconds)
    parser.add_argument("--vector-dim", type=int, default=defaults.vector_dim)
    parser.add_argument("--no-workers", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = AgentSettings(
        core_url=args.core_url,
        db_path=args.db,
        consumer_id=args.consumer_id,
        poll_interval_seconds=max(0.25, args.poll_interval),
        poll_timeout_seconds=max(0, min(args.poll_timeout, 30)),
        poll_batch_size=max(1, min(args.poll_batch, 200)),
        scheduler_interval_seconds=max(0.5, args.scheduler_interval),
        vector_dim=max(64, min(args.vector_dim, 4096)),
    )
    service = AgentService(settings)
    if args.once:
        result = service.run_once()
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0 if result.get("poll", {}).get("ok") else 1

    server = create_server(args.host, args.port, service)
    if not args.no_workers:
        service.start_workers()

    stopping = False

    def stop_handler(signum, frame):  # noqa: ARG001
        nonlocal stopping
        if stopping:
            return
        stopping = True
        service.stop_workers()
        # BaseServer.shutdown() must run from a thread other than the one in
        # serve_forever(), otherwise Python can deadlock during SIGTERM.
        threading.Thread(target=server.shutdown, name="wechat-agent-http-stop", daemon=True).start()

    try:
        signal.signal(signal.SIGTERM, stop_handler)
        signal.signal(signal.SIGINT, stop_handler)
    except ValueError:
        # Tests can construct the server outside the main thread.
        pass
    print(f"WeChat Agent listening on http://{args.host}:{server.server_port}; MCP at /mcp", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.stop_workers()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


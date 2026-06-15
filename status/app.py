#!/usr/bin/env python3
"""Service status dashboard for the local WeChat memory suite."""

from __future__ import annotations

import argparse
import json
import mimetypes
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import AF_UNIX, SOCK_STREAM, socket
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
MEMORY_DB = ROOT / "runtime/memory/wechat_memory.sqlite"
AI_DB = ROOT / "runtime/ai-memory/ai_memory.sqlite"
SYNC_STATUS_FILE = ROOT / "runtime/memory/sync_status.json"
AI_STATUS_FILE = ROOT / "runtime/ai-memory/ai_status.json"
DOCKER_SOCK = Path("/var/run/docker.sock")
SERVICE_CONTAINERS = [
    "wechat-selkies",
    "wechat-memory-sync",
    "wechat-ai-memory",
    "wechat-agent-console",
]

try:
    DISPLAY_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    DISPLAY_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")


def now_local() -> datetime:
    return datetime.now(DISPLAY_TZ)


def iso_now() -> str:
    return now_local().isoformat(timespec="seconds")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        fixed = value.replace("Z", "+00:00")
        return datetime.fromisoformat(fixed).astimezone(DISPLAY_TZ)
    except ValueError:
        return None


def unix_to_text(value) -> str:
    if not value:
        return ""
    try:
        return datetime.fromtimestamp(int(value), DISPLAY_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return str(value)


def age_seconds(value: str | None) -> float | None:
    dt = parse_time(value)
    if not dt:
        return None
    return max(0.0, (now_local() - dt).total_seconds())


def read_json(path: Path) -> dict:
    if not path.exists():
        return {"ok": None, "missing": True, "path": str(path)}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc), "path": str(path)}


def db_connect(path: Path) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def db_counts() -> dict:
    payload = {
        "memory_db_exists": MEMORY_DB.exists(),
        "ai_db_exists": AI_DB.exists(),
    }
    if MEMORY_DB.exists():
        with db_connect(MEMORY_DB) as conn:
            payload.update(
                {
                    "chats": conn.execute("SELECT COUNT(*) AS n FROM chats").fetchone()["n"],
                    "groups": conn.execute("SELECT COUNT(*) AS n FROM chats WHERE is_group=1").fetchone()["n"],
                    "messages": conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"],
                    "media": conn.execute("SELECT COUNT(*) AS n FROM message_media").fetchone()["n"],
                    "latest_message_time": conn.execute(
                        "SELECT MAX(create_time) AS t FROM messages"
                    ).fetchone()["t"],
                }
            )
    if AI_DB.exists():
        with db_connect(AI_DB) as conn:
            payload.update(
                {
                    "indexed_chunks": conn.execute("SELECT COUNT(*) AS n FROM ai_chunks").fetchone()["n"],
                    "indexed_messages": conn.execute("SELECT COUNT(*) AS n FROM ai_indexed_messages").fetchone()["n"],
                }
            )
    payload["latest_message_time_text"] = unix_to_text(payload.get("latest_message_time"))
    return payload


def probe_http(host: str, port: int, path: str = "/", timeout: float = 1.5) -> dict:
    started = time.time()
    conn = HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        response.read(2048)
        elapsed = round((time.time() - started) * 1000)
        return {
            "ok": 200 <= response.status < 500,
            "status": response.status,
            "latency_ms": elapsed,
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "latency_ms": None,
            "error": str(exc),
        }
    finally:
        conn.close()


def docker_request(method: str, path: str, timeout: float = 1.5) -> tuple[int, dict | list | str]:
    if not DOCKER_SOCK.exists():
        return 0, {"error": "docker socket not mounted"}
    sock = socket(AF_UNIX, SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(DOCKER_SOCK))
        request = (
            f"{method} {path} HTTP/1.1\r\n"
            "Host: docker\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("utf-8")
        sock.sendall(request)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    except Exception as exc:
        return 0, {"error": str(exc)}
    finally:
        sock.close()

    raw = b"".join(chunks)
    header, _, body = raw.partition(b"\r\n\r\n")
    status_line = header.splitlines()[0].decode("latin1", errors="replace") if header else ""
    try:
        status_code = int(status_line.split()[1])
    except (IndexError, ValueError):
        status_code = 0
    if b"Transfer-Encoding: chunked" in header:
        body = decode_chunked(body)
    try:
        return status_code, json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return status_code, body.decode("utf-8", errors="replace")


def decode_chunked(body: bytes) -> bytes:
    output = bytearray()
    pos = 0
    while pos < len(body):
        line_end = body.find(b"\r\n", pos)
        if line_end < 0:
            break
        size_text = body[pos:line_end].split(b";", 1)[0]
        try:
            size = int(size_text, 16)
        except ValueError:
            break
        pos = line_end + 2
        if size == 0:
            break
        output.extend(body[pos : pos + size])
        pos += size + 2
    return bytes(output)


def docker_container_status(names: list[str]) -> dict:
    containers = {}
    for name in names:
        status_code, info = docker_request("GET", f"/containers/{name}/json")
        item = {
            "name": name,
            "ok": False,
            "available": status_code == 200,
            "error": "",
        }
        if status_code == 200 and isinstance(info, dict):
            state = info.get("State") or {}
            config = info.get("Config") or {}
            item.update(
                {
                    "ok": state.get("Running") is True and not state.get("Restarting") and not state.get("Dead"),
                    "id": (info.get("Id") or "")[:12],
                    "image": config.get("Image") or info.get("Image") or "",
                    "status": state.get("Status") or "",
                    "running": bool(state.get("Running")),
                    "restarting": bool(state.get("Restarting")),
                    "paused": bool(state.get("Paused")),
                    "oom_killed": bool(state.get("OOMKilled")),
                    "dead": bool(state.get("Dead")),
                    "exit_code": state.get("ExitCode"),
                    "error": state.get("Error") or "",
                    "started_at": to_local_iso(state.get("StartedAt")),
                    "finished_at": to_local_iso(state.get("FinishedAt")),
                    "restart_count": info.get("RestartCount", 0),
                    "ports": summarize_ports(info.get("NetworkSettings", {}).get("Ports") or {}),
                }
            )
        else:
            item["error"] = info.get("error") if isinstance(info, dict) else str(info)
        containers[name] = item

    stats_code, stats = docker_request("GET", "/containers/json?all=1")
    if stats_code == 200 and isinstance(stats, list):
        by_name = {}
        for entry in stats:
            for raw_name in entry.get("Names") or []:
                by_name[raw_name.lstrip("/")] = entry
        for name, item in containers.items():
            entry = by_name.get(name)
            if entry:
                item["docker_status_text"] = entry.get("Status") or ""
                item["created"] = unix_to_text(entry.get("Created"))
    return containers


def to_local_iso(value: str | None) -> str:
    dt = parse_time(value)
    if not dt or (dt.year <= 1):
        return ""
    return dt.isoformat(timespec="seconds")


def summarize_ports(ports: dict) -> list[str]:
    output = []
    for internal, bindings in ports.items():
        if not bindings:
            output.append(internal)
            continue
        for binding in bindings:
            host = binding.get("HostIp") or ""
            port = binding.get("HostPort") or ""
            output.append(f"{host}:{port}->{internal}")
    return output


def health_from_status(payload: dict, max_age: int = 30) -> dict:
    ok = payload.get("ok") is True
    age = age_seconds(payload.get("finished_at"))
    stale = age is None or age > max_age
    return {
        "ok": bool(ok and not stale),
        "reported_ok": payload.get("ok"),
        "age_seconds": round(age, 1) if age is not None else None,
        "stale": stale,
    }


def api_status() -> dict:
    sync_status = read_json(SYNC_STATUS_FILE)
    ai_status = read_json(AI_STATUS_FILE)
    counts = db_counts()
    containers = docker_container_status(SERVICE_CONTAINERS)
    probes = {
        "wechat_web": probe_http("wechat-selkies", 3000, "/"),
        "ai_memory": probe_http("wechat-ai-memory", 8090, "/api/status"),
        "agent_console": probe_http("wechat-agent-console", 8078, "/api/status"),
    }
    services = [
        {
            "id": "wechat-selkies",
            "name": "微信浏览器",
            "port": 3000,
            "url": "http://localhost:3000",
            "kind": "browser-wechat",
            "health": probes["wechat_web"],
            "container": containers.get("wechat-selkies"),
            "description": "浏览器里的 Linux 微信桌面环境",
        },
        {
            "id": "wechat-memory-sync",
            "name": "聊天同步",
            "port": None,
            "url": "",
            "kind": "worker",
            "health": health_from_status(sync_status),
            "container": containers.get("wechat-memory-sync"),
            "description": "只读解密、入库、媒体同步",
            "details": sync_status,
        },
        {
            "id": "wechat-ai-memory",
            "name": "AI 记忆库",
            "port": 8090,
            "url": "http://localhost:8090/api/status",
            "kind": "ai-memory",
            "health": health_from_status(ai_status),
            "container": containers.get("wechat-ai-memory"),
            "description": "增量索引群记忆并提供检索上下文",
            "details": ai_status,
        },
        {
            "id": "wechat-agent-console",
            "name": "Agent 控制台",
            "port": 8078,
            "url": "http://localhost:8078",
            "kind": "agent-console",
            "health": probes["agent_console"],
            "container": containers.get("wechat-agent-console"),
            "description": "统一入口：聊天记录、服务状态、LLM、人格和记忆层",
        },
    ]
    overall_ok = all(
        item["health"].get("ok") is True and (not item.get("container") or item["container"].get("ok") is True)
        for item in services
    )
    return {
        "ok": overall_ok,
        "generated_at": iso_now(),
        "counts": counts,
        "sync": sync_status,
        "ai": ai_status,
        "containers": containers,
        "services": services,
    }


def json_response(handler: BaseHTTPRequestHandler, payload, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
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


def serve_static(handler: BaseHTTPRequestHandler, path: str) -> None:
    if path == "/":
        target = STATIC_DIR / "index.html"
    else:
        rel = unquote(path).lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        root = STATIC_DIR.resolve()
        if target != root and root not in target.parents:
            text_response(handler, "not found", 404)
            return
    if not target.exists() or not target.is_file():
        text_response(handler, "not found", 404)
        return
    mime, _ = mimetypes.guess_type(str(target))
    handler.send_response(200)
    handler.send_header("Content-Type", mime or "application/octet-stream")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    with target.open("rb") as f:
        shutil.copyfileobj(f, handler.wfile)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A003
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} {fmt % args}", flush=True)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/status":
                json_response(self, api_status())
            else:
                serve_static(self, parsed.path)
        except sqlite3.Error as exc:
            json_response(self, {"ok": False, "error": f"database error: {exc}"}, 500)
        except Exception as exc:
            json_response(self, {"ok": False, "error": str(exc)}, 500)

    def do_HEAD(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path.startswith("/api/"):
            self.send_response(200)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve WeChat suite status dashboard")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8079)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving WeChat suite status dashboard at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from typing import Any, Callable

from .service import AgentService


MCP_PROTOCOL_VERSION = "2025-06-18"


def tool_result(payload: Any) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ],
        "structuredContent": payload,
        "isError": False,
    }


def tool_error(message: str, *, data: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"error": message}
    if data is not None:
        payload["data"] = data
    result = tool_result(payload)
    result["isError"] = True
    return result


class McpError(RuntimeError):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = int(code)
        self.message = str(message)
        self.data = data


class MCPServer:
    def __init__(self, service: AgentService):
        self.service = service
        self._tools: dict[str, tuple[dict[str, Any], Callable[[dict[str, Any]], Any]]] = {}
        self._register_tools()

    def _register(self, name: str, description: str, schema: dict[str, Any], fn: Callable[[dict[str, Any]], Any]) -> None:
        self._tools[name] = (
            {
                "name": name,
                "description": description,
                "inputSchema": schema,
            },
            fn,
        )

    def _register_tools(self) -> None:
        object_schema = {"type": "object", "additionalProperties": False, "properties": {}}
        self._register(
            "wechat_accounts",
            "List WeChat accounts exposed by Core V1.",
            object_schema,
            lambda args: {"accounts": self.service.core.list_accounts()},
        )
        self._register(
            "wechat_chats",
            "List/search chats for one WeChat account.",
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["account_id"],
                "properties": {
                    "account_id": {"type": "string"},
                    "query": {"type": "string", "default": ""},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 100},
                },
            },
            lambda args: self.service.core.list_chats(
                str(args["account_id"]), query=str(args.get("query") or ""), limit=int(args.get("limit") or 100)
            ),
        )
        self._register(
            "wechat_send_text",
            "Queue account-aware text through Core. This does not operate the WeChat GUI directly.",
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["account_id", "chat_id", "text"],
                "properties": {
                    "account_id": {"type": "string"},
                    "chat_id": {"type": "string"},
                    "text": {"type": "string", "minLength": 1},
                    "target_message_id": {"type": "string"},
                    "mention_member_ids": {"type": "array", "items": {"type": "string"}},
                    "client_request_id": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
            },
            lambda args: self.service.core.send_text(
                str(args["account_id"]),
                str(args["chat_id"]),
                str(args["text"]),
                target_message_id=str(args.get("target_message_id") or ""),
                mention_member_ids=list(args.get("mention_member_ids") or []),
                client_request_id=str(args.get("client_request_id") or ""),
                idempotency_key=str(args.get("idempotency_key") or ""),
            ),
        )
        self._register(
            "memory_search",
            "Search Agent-owned memory indexed from Core normalized events.",
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "account_id": {"type": "string"},
                    "chat_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8},
                },
            },
            lambda args: self.service.memory.search(
                str(args["query"]),
                account_id=str(args.get("account_id") or ""),
                chat_id=str(args.get("chat_id") or ""),
                limit=int(args.get("limit") or 8),
            ),
        )
        self._register(
            "memory_context",
            "Build recent plus long-term account-scoped chat context from Agent memory.",
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["account_id", "chat_id"],
                "properties": {
                    "account_id": {"type": "string"},
                    "chat_id": {"type": "string"},
                    "query": {"type": "string", "default": ""},
                    "recent_limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
                    "memory_limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8},
                },
            },
            lambda args: self.service.memory.context(
                str(args["account_id"]),
                str(args["chat_id"]),
                str(args.get("query") or ""),
                recent_limit=int(args.get("recent_limit") or 20),
                memory_limit=int(args.get("memory_limit") or 8),
            ),
        )
        self._register(
            "records_list",
            "List durable Agent records.",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "account_id": {"type": "string"},
                    "chat_id": {"type": "string"},
                    "kind": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
                },
            },
            lambda args: {
                "records": self.service.storage.list_records(
                    account_id=str(args.get("account_id") or ""),
                    chat_id=str(args.get("chat_id") or ""),
                    kind=str(args.get("kind") or ""),
                    query=str(args.get("query") or ""),
                    limit=int(args.get("limit") or 100),
                )
            },
        )
        self._register(
            "records_create",
            "Create a durable Agent record.",
            {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "account_id": {"type": "string"},
                    "chat_id": {"type": "string"},
                    "kind": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "data": {"type": "object"},
                },
            },
            lambda args: self.service.storage.create_record(args),
        )
        self._register(
            "templates_list",
            "List Agent templates.",
            object_schema,
            lambda args: {"templates": self.service.storage.list_templates()},
        )
        self._register(
            "templates_upsert",
            "Create or update a safe non-executable Agent template.",
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "body"],
                "properties": {
                    "template_id": {"type": "string"},
                    "name": {"type": "string"},
                    "body": {"type": "string"},
                    "enabled": {"type": "boolean", "default": True},
                },
            },
            lambda args: self.service.storage.upsert_template(args),
        )
        self._register(
            "monitors_list",
            "List Monitor Engine definitions.",
            object_schema,
            lambda args: {"monitors": self.service.storage.list_monitors()},
        )
        self._register(
            "monitors_upsert",
            "Create/update an event monitor. Actions: record, send_text, summary, image_understanding.",
            {
                "type": "object",
                "additionalProperties": True,
                "required": ["name"],
                "properties": {
                    "monitor_id": {"type": "string"},
                    "name": {"type": "string"},
                    "enabled": {"type": "boolean"},
                    "event_type": {"type": "string"},
                    "account_id": {"type": "string"},
                    "chat_id": {"type": "string"},
                    "message_type": {"type": "string"},
                    "contains_text": {"type": "string"},
                    "action": {"type": "string", "enum": ["record", "send_text", "summary", "image_understanding"]},
                    "action_config": {"type": "object"},
                },
            },
            lambda args: self.service.storage.upsert_monitor(args),
        )
        self._register(
            "scheduler_list",
            "List recurring scheduler jobs.",
            object_schema,
            lambda args: {"schedules": self.service.storage.list_schedules()},
        )
        self._register(
            "scheduler_upsert",
            "Create/update a recurring Agent job. Minimum interval is 60 seconds.",
            {
                "type": "object",
                "additionalProperties": True,
                "required": ["name", "task_type"],
                "properties": {
                    "schedule_id": {"type": "string"},
                    "name": {"type": "string"},
                    "enabled": {"type": "boolean"},
                    "task_type": {"type": "string", "enum": ["record", "send_text", "summary"]},
                    "account_id": {"type": "string"},
                    "chat_id": {"type": "string"},
                    "template_id": {"type": "string"},
                    "payload": {"type": "object"},
                    "interval_seconds": {"type": "integer", "minimum": 60},
                    "next_run_at": {"type": "string"},
                },
            },
            lambda args: self.service.storage.upsert_schedule(args),
        )
        self._register(
            "agent_poll",
            "Run one Core event poll/ingest/monitor cycle now.",
            object_schema,
            lambda args: self.service.process_events_once(),
        )

    def tools(self) -> list[dict[str, Any]]:
        return [definition for definition, _ in self._tools.values()]

    def handle(self, request: Any) -> Any:
        if isinstance(request, list):
            responses = []
            for item in request:
                response = self._handle_one(item)
                if response is not None:
                    responses.append(response)
            return responses if responses else None
        return self._handle_one(request)

    def _handle_one(self, request: Any) -> dict[str, Any] | None:
        if not isinstance(request, dict):
            return self._error(None, -32600, "Invalid Request")
        request_id = request.get("id")
        method = request.get("method")
        if not isinstance(method, str):
            return self._error(request_id, -32600, "Invalid Request")
        # JSON-RPC notifications do not get responses.
        is_notification = "id" not in request
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "wechat-agent", "version": "0.1.0"},
                    "instructions": (
                        "Use account_id with all WeChat operations. Memory/records are Agent-owned; "
                        "the server never reads Core SQLite directly."
                    ),
                }
            elif method in {"notifications/initialized", "notifications/cancelled"}:
                return None
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.tools()}
            elif method == "tools/call":
                params = request.get("params") if isinstance(request.get("params"), dict) else {}
                name = str(params.get("name") or "")
                arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
                entry = self._tools.get(name)
                if not entry:
                    raise McpError(-32602, f"Unknown tool: {name}")
                _, fn = entry
                try:
                    payload = fn(arguments)
                except (KeyError, TypeError, ValueError) as exc:
                    result = tool_error(f"invalid tool arguments: {exc}")
                except Exception as exc:
                    result = tool_error(str(exc))
                else:
                    result = tool_result(payload)
            else:
                raise McpError(-32601, f"Method not found: {method}")
            if is_notification:
                return None
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except McpError as exc:
            if is_notification:
                return None
            return self._error(request_id, exc.code, exc.message, exc.data)
        except Exception as exc:
            if is_notification:
                return None
            return self._error(request_id, -32603, "Internal error", str(exc))

    @staticmethod
    def _error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
        error: dict[str, Any] = {"code": int(code), "message": str(message)}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}


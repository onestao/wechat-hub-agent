from __future__ import annotations

from typing import Any

from .core_client import CoreClient
from .memory_index import EventMemoryIndex, message_text
from .storage import AgentStorage
from .templates import render_template


def event_message(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    return message


def monitor_matches(monitor: dict[str, Any], event: dict[str, Any]) -> bool:
    if not monitor.get("enabled"):
        return False
    if monitor.get("event_type") and monitor.get("event_type") != event.get("event_type"):
        return False
    if monitor.get("account_id") and monitor.get("account_id") != event.get("account_id"):
        return False
    message = event_message(event)
    chat_id = str(message.get("chat_id") or (event.get("payload") or {}).get("chat_id") or "")
    if monitor.get("chat_id") and monitor.get("chat_id") != chat_id:
        return False
    if monitor.get("message_type") and monitor.get("message_type") != message.get("type"):
        return False
    needle = str(monitor.get("contains_text") or "").strip().lower()
    if needle and needle not in message_text(message).lower():
        return False
    return True


class MonitorEngine:
    def __init__(
        self,
        storage: AgentStorage,
        core: CoreClient,
        memory: EventMemoryIndex,
        ai: Any,
    ):
        self.storage = storage
        self.core = core
        self.memory = memory
        self.ai = ai

    def process_event(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        event_id = str(event.get("event_id") or "")
        for monitor in self.storage.list_monitors(enabled_only=True):
            if not monitor_matches(monitor, event):
                continue
            action_key = f"{monitor['monitor_id']}:{event_id}:{monitor.get('action') or 'record'}"
            if self.storage.monitor_action_done(action_key):
                continue
            try:
                result = self._run_action(monitor, event)
                run = self.storage.record_monitor_run(
                    monitor["monitor_id"], event_id, action_key, "success", result=result
                )
            except Exception as exc:  # persist action failure; event processing itself remains durable
                run = self.storage.record_monitor_run(
                    monitor["monitor_id"], event_id, action_key, "failed", error=str(exc)
                )
            results.append(run)
        return results

    def _context(self, monitor: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        message = event_message(event)
        return {
            "event": event,
            "message": message,
            "monitor": monitor,
            "account_id": str(message.get("account_id") or event.get("account_id") or ""),
            "chat_id": str(message.get("chat_id") or (event.get("payload") or {}).get("chat_id") or ""),
        }

    def _render_action_text(
        self,
        monitor: dict[str, Any],
        context: dict[str, Any],
        *,
        default: str = "",
    ) -> str:
        config = monitor.get("action_config") if isinstance(monitor.get("action_config"), dict) else {}
        template_id = str(config.get("template_id") or "")
        if template_id:
            template = self.storage.get_template(template_id)
            if not template or not template.get("enabled"):
                raise RuntimeError(f"template not available: {template_id}")
            return render_template(str(template.get("body") or ""), context)
        return render_template(str(config.get("text") or config.get("body") or default), context)

    def _run_action(self, monitor: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        action = str(monitor.get("action") or "record")
        context = self._context(monitor, event)
        message = context["message"]
        config = monitor.get("action_config") if isinstance(monitor.get("action_config"), dict) else {}
        if action == "record":
            body = self._render_action_text(monitor, context, default="{{message.text}}")
            if not body.strip():
                body = message_text(message)
            title = render_template(str(config.get("title") or monitor.get("name") or "Monitor record"), context)
            record = self.storage.create_record(
                {
                    "account_id": context["account_id"],
                    "chat_id": context["chat_id"],
                    "kind": str(config.get("kind") or f"monitor:{monitor['monitor_id']}"),
                    "title": title,
                    "body": body,
                    "tags": config.get("tags") or [],
                    "data": {"event": event, "monitor_id": monitor["monitor_id"]},
                    "source_event_id": str(event.get("event_id") or ""),
                }
            )
            return {"action": action, "record": record}

        if action == "send_text":
            text = self._render_action_text(monitor, context)
            if not text.strip():
                raise RuntimeError("send_text monitor rendered empty text")
            if not context["account_id"] or not context["chat_id"]:
                raise RuntimeError("send_text monitor requires account_id and chat_id")
            receipt = self.core.send_text(
                context["account_id"],
                context["chat_id"],
                text,
                target_message_id=str(config.get("reply_to_source") and message.get("message_id") or ""),
                idempotency_key=f"agent-monitor:{monitor['monitor_id']}:{event.get('event_id')}",
                client_request_id=f"monitor:{monitor['monitor_id']}:{event.get('event_id')}",
            )
            return {"action": action, "receipt": receipt}

        if action == "summary":
            if not context["account_id"] or not context["chat_id"]:
                raise RuntimeError("summary monitor requires account_id and chat_id")
            recent = self.memory.recent(
                context["account_id"], context["chat_id"], int(config.get("message_limit") or 50)
            )
            result = self.ai.summarize(
                list(reversed(recent)),
                instruction=str(config.get("instruction") or ""),
                account_id=context["account_id"],
                chat_id=context["chat_id"],
            )
            if not result.get("ok"):
                raise RuntimeError(str(result.get("error") or "summary failed"))
            body = str(result.get("message") or result.get("summary") or "").strip()
            record = self.storage.create_record(
                {
                    "account_id": context["account_id"],
                    "chat_id": context["chat_id"],
                    "kind": str(config.get("kind") or f"summary:{monitor['monitor_id']}"),
                    "title": str(config.get("title") or f"{monitor['name']} summary"),
                    "body": body,
                    "data": {"llm": result, "event_id": event.get("event_id")},
                    "source_event_id": str(event.get("event_id") or ""),
                }
            )
            return {"action": action, "record": record, "llm": result}

        if action == "image_understanding":
            if not context["account_id"] or not message.get("media_id"):
                raise RuntimeError("image_understanding requires account_id and media_id")
            media = self.core.get_media(context["account_id"], str(message["media_id"]))
            result = self.ai.understand_image(
                bytes(media.body),
                filename=str(message.get("filename") or "image.jpg"),
                message=message,
                instruction=str(config.get("instruction") or ""),
            )
            if not result.get("ok"):
                raise RuntimeError(str(result.get("error") or "image understanding failed"))
            body = str(result.get("message") or "").strip()
            record = self.storage.create_record(
                {
                    "account_id": context["account_id"],
                    "chat_id": context["chat_id"],
                    "kind": str(config.get("kind") or f"image_understanding:{monitor['monitor_id']}"),
                    "title": str(config.get("title") or "Image understanding"),
                    "body": body,
                    "data": {"llm": result, "media_id": message.get("media_id")},
                    "source_event_id": str(event.get("event_id") or ""),
                }
            )
            return {"action": action, "record": record, "llm": result}

        raise RuntimeError(f"unsupported monitor action: {action}")


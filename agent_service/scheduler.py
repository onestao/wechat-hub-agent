from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .core_client import CoreClient
from .memory_index import EventMemoryIndex
from .storage import AgentStorage, utc_now_iso
from .templates import render_template


def parse_time(value: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class SchedulerEngine:
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

    def run_due(self, *, limit: int = 50) -> list[dict[str, Any]]:
        results = []
        for schedule in self.storage.due_schedules(limit=limit):
            due_at = str(schedule.get("next_run_at") or utc_now_iso())
            next_time = parse_time(due_at) + timedelta(seconds=max(60, int(schedule.get("interval_seconds") or 3600)))
            now = datetime.now(timezone.utc)
            while next_time <= now:
                next_time += timedelta(seconds=max(60, int(schedule.get("interval_seconds") or 3600)))
            next_run_at = next_time.isoformat(timespec="seconds")
            try:
                result = self._run(schedule, due_at)
                run = self.storage.finish_schedule_run(
                    schedule, "success", result=result, next_run_at=next_run_at
                )
            except Exception as exc:
                run = self.storage.finish_schedule_run(
                    schedule, "failed", error=str(exc), next_run_at=next_run_at
                )
            results.append(run)
        return results

    def _run(self, schedule: dict[str, Any], due_at: str) -> dict[str, Any]:
        task_type = str(schedule.get("task_type") or "record")
        payload = schedule.get("payload") if isinstance(schedule.get("payload"), dict) else {}
        context = {
            "schedule": schedule,
            "payload": payload,
            "account_id": schedule.get("account_id") or "",
            "chat_id": schedule.get("chat_id") or "",
            "due_at": due_at,
        }
        text = str(payload.get("text") or payload.get("body") or "")
        template_id = str(schedule.get("template_id") or payload.get("template_id") or "")
        if template_id:
            template = self.storage.get_template(template_id)
            if not template or not template.get("enabled"):
                raise RuntimeError(f"template not available: {template_id}")
            text = render_template(str(template.get("body") or ""), context)
        else:
            text = render_template(text, context)

        if task_type == "record":
            record = self.storage.create_record(
                {
                    "account_id": schedule.get("account_id") or "",
                    "chat_id": schedule.get("chat_id") or "",
                    "kind": str(payload.get("kind") or "scheduled"),
                    "title": render_template(str(payload.get("title") or schedule.get("name") or "Scheduled record"), context),
                    "body": text,
                    "tags": payload.get("tags") or [],
                    "data": {"schedule_id": schedule["schedule_id"], "due_at": due_at, "payload": payload},
                }
            )
            return {"task_type": task_type, "record": record}

        if task_type == "send_text":
            if not schedule.get("account_id") or not schedule.get("chat_id"):
                raise RuntimeError("send_text schedule requires account_id and chat_id")
            if not text.strip():
                raise RuntimeError("send_text schedule rendered empty text")
            receipt = self.core.send_text(
                str(schedule["account_id"]),
                str(schedule["chat_id"]),
                text,
                idempotency_key=f"agent-schedule:{schedule['schedule_id']}:{due_at}",
                client_request_id=f"schedule:{schedule['schedule_id']}:{due_at}",
            )
            return {"task_type": task_type, "receipt": receipt}

        if task_type == "summary":
            if not schedule.get("account_id") or not schedule.get("chat_id"):
                raise RuntimeError("summary schedule requires account_id and chat_id")
            recent = self.memory.recent(
                str(schedule["account_id"]),
                str(schedule["chat_id"]),
                int(payload.get("message_limit") or 100),
            )
            llm = self.ai.summarize(
                list(reversed(recent)),
                instruction=str(payload.get("instruction") or ""),
                account_id=str(schedule["account_id"]),
                chat_id=str(schedule["chat_id"]),
            )
            if not llm.get("ok"):
                raise RuntimeError(str(llm.get("error") or "summary failed"))
            body = str(llm.get("message") or llm.get("summary") or "")
            record = self.storage.create_record(
                {
                    "account_id": schedule["account_id"],
                    "chat_id": schedule["chat_id"],
                    "kind": str(payload.get("kind") or "scheduled_summary"),
                    "title": str(payload.get("title") or schedule.get("name") or "Scheduled summary"),
                    "body": body,
                    "data": {"schedule_id": schedule["schedule_id"], "due_at": due_at, "llm": llm},
                }
            )
            return {"task_type": task_type, "record": record, "llm": llm}

        raise RuntimeError(f"unsupported schedule task_type: {task_type}")


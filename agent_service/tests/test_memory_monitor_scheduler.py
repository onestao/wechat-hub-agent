from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_service.memory_index import EventMemoryIndex
from agent_service.monitor import MonitorEngine
from agent_service.scheduler import SchedulerEngine
from agent_service.storage import AgentStorage, utc_now_iso
from agent_service.tests.helpers import FakeAI, FakeCore
from agent_service.templates import render_template


class MemoryMonitorSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "agent.sqlite"
        self.storage = AgentStorage(self.db_path)
        self.memory = EventMemoryIndex(self.storage)
        self.core = FakeCore()
        self.ai = FakeAI()

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def text_event(event_id: str = "evt-1"):
        return {
            "event_id": event_id,
            "cursor": "1",
            "account_id": "account-a",
            "event_type": "message.created",
            "occurred_at": "2026-08-31T07:00:01Z",
            "payload": {
                "message": {
                    "account_id": "account-a",
                    "message_id": "msg-1",
                    "chat_id": "chat-a",
                    "type": "text",
                    "direction": "incoming",
                    "created_at": "2026-08-31T07:00:01Z",
                    "text": "部署今晚九点开始",
                    "author": {"member_id": "alice", "display_name": "Alice", "is_self": False},
                }
            },
        }

    def test_event_memory_reuses_search_and_is_account_scoped(self):
        event = self.text_event()
        first = self.memory.ingest_message(event, event["payload"]["message"])
        second = self.memory.ingest_message(event, event["payload"]["message"])
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(self.memory.count(), 1)

        hit = self.memory.search("部署 九点", account_id="account-a", chat_id="chat-a")
        self.assertEqual(len(hit["results"]), 1)
        self.assertEqual(hit["results"][0]["message_id"], "msg-1")
        miss = self.memory.search("部署", account_id="account-b")
        self.assertEqual(miss["results"], [])

        context = self.memory.context("account-a", "chat-a", "部署")
        self.assertIn("部署今晚九点开始", context["prompt_context"])

    def test_monitor_record_and_send_are_idempotent(self):
        event = self.text_event()
        self.memory.ingest_message(event, event["payload"]["message"])
        self.storage.upsert_monitor(
            {
                "monitor_id": "deploy-record",
                "name": "deployment watcher",
                "contains_text": "部署",
                "action": "record",
                "action_config": {"title": "部署提醒", "text": "{{message.author.display_name}}: {{message.text}}"},
            }
        )
        engine = MonitorEngine(self.storage, self.core, self.memory, self.ai)
        first = engine.process_event(event)
        second = engine.process_event(event)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        records = self.storage.list_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["body"], "Alice: 部署今晚九点开始")

        event2 = self.text_event("evt-2")
        event2["payload"]["message"]["message_id"] = "msg-2"
        self.storage.upsert_monitor(
            {
                "monitor_id": "deploy-reply",
                "name": "deployment reply",
                "contains_text": "部署",
                "action": "send_text",
                "action_config": {"text": "收到 {{message.message_id}}", "reply_to_source": True},
            }
        )
        first_send = engine.process_event(event2)
        second_send = engine.process_event(event2)
        self.assertGreaterEqual(len(first_send), 1)
        self.assertEqual(second_send, [])
        self.assertEqual(len(self.core.sends), 1)
        self.assertEqual(self.core.sends[0]["target_message_id"], "msg-2")
        self.assertTrue(self.core.sends[0]["idempotency_key"].startswith("agent-monitor:"))

    def test_summary_and_image_actions_use_ai_adapter(self):
        event = self.text_event()
        self.memory.ingest_message(event, event["payload"]["message"])
        self.storage.upsert_monitor(
            {
                "monitor_id": "summary",
                "name": "summary",
                "contains_text": "部署",
                "action": "summary",
            }
        )
        engine = MonitorEngine(self.storage, self.core, self.memory, self.ai)
        runs = engine.process_event(event)
        self.assertEqual(runs[0]["status"], "success")
        self.assertEqual(len(self.ai.summary_calls), 1)
        self.assertTrue(any(item["kind"].startswith("summary:") for item in self.storage.list_records()))

        image_event = {
            "event_id": "evt-image",
            "cursor": "2",
            "account_id": "account-a",
            "event_type": "message.created",
            "occurred_at": "2026-08-31T07:00:02Z",
            "payload": {
                "message": {
                    "account_id": "account-a",
                    "message_id": "img-1",
                    "chat_id": "chat-a",
                    "type": "image",
                    "direction": "incoming",
                    "created_at": "2026-08-31T07:00:02Z",
                    "media_id": "media-1",
                    "filename": "pic.png",
                    "author": {"member_id": "alice", "display_name": "Alice", "is_self": False},
                }
            },
        }
        self.storage.upsert_monitor(
            {
                "monitor_id": "vision",
                "name": "vision",
                "message_type": "image",
                "action": "image_understanding",
            }
        )
        image_runs = engine.process_event(image_event)
        self.assertTrue(any(run["monitor_id"] == "vision" and run["status"] == "success" for run in image_runs))
        self.assertEqual(self.ai.image_calls[0]["size"], len(self.core.media))

    def test_template_renderer_has_no_expression_evaluation(self):
        context = {"message": {"text": "hello"}}
        self.assertEqual(render_template("x={{ message.text }}", context), "x=hello")
        self.assertEqual(render_template("{{message.missing}}", context), "")
        self.assertEqual(render_template("{{__import__('os').system('x')}}", context), "{{__import__('os').system('x')}}")

    def test_scheduler_persists_record_and_advances(self):
        schedule = self.storage.upsert_schedule(
            {
                "schedule_id": "hourly-note",
                "name": "hourly note",
                "task_type": "record",
                "payload": {"body": "due={{due_at}}", "kind": "checkpoint"},
                "interval_seconds": 60,
                "next_run_at": utc_now_iso(),
            }
        )
        engine = SchedulerEngine(self.storage, self.core, self.memory, self.ai)
        runs = engine.run_due()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "success")
        records = self.storage.list_records(kind="checkpoint")
        self.assertEqual(len(records), 1)
        updated = next(item for item in self.storage.list_schedules() if item["schedule_id"] == schedule["schedule_id"])
        self.assertNotEqual(updated["next_run_at"], schedule["next_run_at"])


if __name__ == "__main__":
    unittest.main()


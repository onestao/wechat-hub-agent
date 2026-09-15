"""Identity v2 fail-closed behaviour and CRUD coverage for automation rules.

Covers taskbook F5/F6/F7/F9:
- send_text schedules pin instance_uuid + expected identity and re-validate
  the live binding before every execution (and every retry);
- monitors are explicitly scoped and refuse to execute on identity
  mismatch/unresolved state; every run log records identity + instance;
- rules, schedules, templates and their execution logs survive restarts and
  are deletable (Console CRUD backend).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_service.monitor import MonitorEngine
from agent_service.scheduler import SchedulerEngine
from agent_service.storage import AgentStorage, utc_now_iso
from agent_service.tests.helpers import FakeAI, FakeCore


def text_event(event_id: str = "evt-1", account_id: str = "account-a", chat_id: str = "chat-a"):
    return {
        "event_id": event_id,
        "cursor": "1",
        "account_id": account_id,
        "event_type": "message.created",
        "occurred_at": "2026-08-31T07:00:01Z",
        "payload": {
            "message": {
                "account_id": account_id,
                "message_id": f"msg-{event_id}",
                "chat_id": chat_id,
                "type": "text",
                "direction": "incoming",
                "created_at": "2026-08-31T07:00:01Z",
                "text": "部署今晚九点开始",
                "author": {"member_id": "alice", "display_name": "Alice", "is_self": False},
            }
        },
    }


class MonitorIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.storage = AgentStorage(Path(self.tempdir.name) / "agent.sqlite")
        self.core = FakeCore()
        self.engine = MonitorEngine(self.storage, self.core, None, FakeAI())

    def tearDown(self):
        self.storage.close()
        self.tempdir.cleanup()

    def test_monitor_requires_explicit_account_scope(self):
        with self.assertRaises(ValueError):
            self.storage.upsert_monitor({"name": "global watcher", "action": "record"})

    def test_send_monitor_requires_expected_identity(self):
        with self.assertRaises(ValueError):
            self.storage.upsert_monitor(
                {
                    "name": "reply",
                    "account_id": "account-a",
                    "action": "send_text",
                    "action_config": {"text": "hi"},
                }
            )

    def test_reply_executes_only_while_bound_and_logs_identity(self):
        self.storage.upsert_monitor(
            {
                "monitor_id": "reply",
                "name": "reply",
                "account_id": "account-a",
                "expected_wechat_identity_uuid": "identity-a-uuid",
                "contains_text": "部署",
                "action": "send_text",
                "action_config": {"text": "收到"},
            }
        )
        runs = self.engine.process_event(text_event())
        self.assertEqual(runs[0]["status"], "success")
        self.assertEqual(len(self.core.sends), 1)
        self.assertEqual(self.core.sends[0]["expected_wechat_identity_uuid"], "identity-a-uuid")
        logged = self.storage.list_monitor_runs("reply")[0]
        self.assertEqual(
            logged["result"]["identity"],
            {
                "account_id": "account-a",
                "instance_uuid": "instance-a-uuid",
                "wechat_identity_uuid": "identity-a-uuid",
            },
        )

    def test_reply_fails_closed_when_identity_changed(self):
        self.storage.upsert_monitor(
            {
                "monitor_id": "reply",
                "name": "reply",
                "account_id": "account-a",
                "expected_wechat_identity_uuid": "identity-a-uuid",
                "action": "send_text",
                "action_config": {"text": "收到"},
            }
        )
        self.core.accounts[0]["wechat_identity_uuid"] = "identity-b-uuid"
        runs = self.engine.process_event(text_event())
        self.assertEqual(runs[0]["status"], "failed")
        self.assertIn("identity binding changed", runs[0]["error"])
        self.assertEqual(self.core.sends, [])

    def test_reply_fails_closed_when_unbound_or_unknown(self):
        self.storage.upsert_monitor(
            {
                "monitor_id": "reply",
                "name": "reply",
                "account_id": "account-a",
                "expected_wechat_identity_uuid": "identity-a-uuid",
                "action": "send_text",
                "action_config": {"text": "收到"},
            }
        )
        self.core.accounts[0]["identity_binding_state"] = "mismatch"
        runs = self.engine.process_event(text_event())
        self.assertEqual(runs[0]["status"], "failed")
        self.assertIn("identity binding state", runs[0]["error"])
        self.assertEqual(self.core.sends, [])

        self.core.accounts[0]["identity_binding_state"] = "unbound"
        runs = self.engine.process_event(text_event("evt-2"))
        self.assertEqual(runs[0]["status"], "failed")
        self.assertEqual(self.core.sends, [])

        # Events from other slots never match a scoped rule at all.
        runs = self.engine.process_event(text_event("evt-3", account_id="account-unknown"))
        self.assertEqual(runs, [])
        self.assertEqual(self.core.sends, [])


class ScheduleIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.storage = AgentStorage(Path(self.tempdir.name) / "agent.sqlite")
        self.core = FakeCore()
        self.engine = SchedulerEngine(self.storage, self.core, None, FakeAI())

    def tearDown(self):
        self.storage.close()
        self.tempdir.cleanup()

    def make_schedule(self, schedule_id: str = "hourly-send") -> dict:
        return self.storage.upsert_schedule(
            {
                "schedule_id": schedule_id,
                "name": "hourly send",
                "task_type": "send_text",
                "account_id": "account-a",
                "chat_id": "chat-a",
                "instance_uuid": "instance-a-uuid",
                "expected_wechat_identity_uuid": "identity-a-uuid",
                "payload": {"text": "hello"},
                "interval_seconds": 3600,
                "next_run_at": utc_now_iso(),
            }
        )

    def test_send_schedule_requires_identity_binding(self):
        with self.assertRaises(ValueError):
            self.storage.upsert_schedule(
                {
                    "name": "no identity",
                    "task_type": "send_text",
                    "account_id": "account-a",
                    "chat_id": "chat-a",
                    "payload": {"text": "hello"},
                }
            )

    def test_send_schedule_runs_while_binding_matches(self):
        self.make_schedule()
        runs = self.engine.run_due()
        self.assertEqual(runs[0]["status"], "success")
        self.assertEqual(len(self.core.sends), 1)
        self.assertEqual(self.core.sends[0]["expected_wechat_identity_uuid"], "identity-a-uuid")
        self.assertEqual(self.core.sends[0]["idempotency_key"].startswith("agent-schedule:"), True)
        stored = self.storage.list_scheduler_runs("hourly-send")[0]
        self.assertEqual(stored["result"]["identity"]["wechat_identity_uuid"], "identity-a-uuid")

    def test_send_schedule_fails_closed_on_identity_change_and_recovers(self):
        schedule = self.make_schedule()
        self.core.accounts[0]["wechat_identity_uuid"] = "identity-b-uuid"
        blocked = self.engine.run_due()
        self.assertEqual(blocked[0]["status"], "failed")
        self.assertIn("identity binding changed", blocked[0]["error"])
        self.assertEqual(self.core.sends, [])

        # Retry must re-validate: pull next_run_at forward like the interval
        # elapsed, identity restored -> the retry succeeds.
        self.core.accounts[0]["wechat_identity_uuid"] = "identity-a-uuid"
        self.storage.upsert_schedule(
            {
                "schedule_id": schedule["schedule_id"],
                "name": "hourly send",
                "task_type": "send_text",
                "account_id": "account-a",
                "chat_id": "chat-a",
                "instance_uuid": "instance-a-uuid",
                "expected_wechat_identity_uuid": "identity-a-uuid",
                "payload": {"text": "hello"},
                "interval_seconds": 3600,
                "next_run_at": utc_now_iso(),
            }
        )
        recovered = self.engine.run_due()
        self.assertEqual(recovered[0]["status"], "success")
        self.assertEqual(len(self.core.sends), 1)

    def test_send_schedule_fails_closed_on_instance_change(self):
        self.make_schedule()
        self.core.accounts[0]["instance_uuid"] = "instance-c-uuid"
        runs = self.engine.run_due()
        self.assertEqual(runs[0]["status"], "failed")
        self.assertIn("runtime instance changed", runs[0]["error"])
        self.assertEqual(self.core.sends, [])

    def test_record_schedule_stamps_identity_without_requiring_it(self):
        self.storage.upsert_schedule(
            {
                "schedule_id": "hourly-note",
                "name": "hourly note",
                "task_type": "record",
                "account_id": "account-a",
                "payload": {"body": "checkpoint"},
                "interval_seconds": 60,
                "next_run_at": utc_now_iso(),
            }
        )
        runs = self.engine.run_due()
        self.assertEqual(runs[0]["status"], "success")
        stored = self.storage.list_scheduler_runs("hourly-note")[0]
        self.assertEqual(stored["result"]["identity"]["wechat_identity_uuid"], "identity-a-uuid")


class AutomationCrudAndPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "agent.sqlite"

    def tearDown(self):
        # Each test opens and explicitly closes its own AgentStorage handle.
        self.tempdir.cleanup()

    def test_rules_schedules_templates_and_runs_survive_restart(self):
        storage = AgentStorage(self.db_path)
        storage.upsert_monitor(
            {
                "monitor_id": "watcher",
                "name": "watcher",
                "account_id": "account-a",
                "expected_wechat_identity_uuid": "identity-a-uuid",
                "contains_text": "部署",
                "action": "record",
            }
        )
        storage.upsert_schedule(
            {
                "schedule_id": "hourly",
                "name": "hourly",
                "task_type": "record",
                "account_id": "account-a",
                "payload": {"body": "note"},
                "next_run_at": utc_now_iso(),
            }
        )
        storage.upsert_template({"template_id": "tpl", "name": "tpl", "body": "hi"})
        engine = MonitorEngine(storage, FakeCore(), None, FakeAI())
        engine.process_event(text_event())
        storage.record_monitor_run(
            "watcher", "evt-manual", "watcher:evt-manual:record", "success", result={}
        )

        reopened = AgentStorage(self.db_path)
        try:
            self.assertEqual([m["monitor_id"] for m in reopened.list_monitors()], ["watcher"])
            self.assertEqual([s["schedule_id"] for s in reopened.list_schedules()], ["hourly"])
            template_ids = [t["template_id"] for t in reopened.list_templates()]
            self.assertIn("tpl", template_ids)
            self.assertIn("summary-record", template_ids)
            self.assertEqual(len(reopened.list_monitor_runs("watcher")), 2)
            self.assertEqual(
                reopened.get_monitor("watcher")["expected_wechat_identity_uuid"], "identity-a-uuid"
            )
        finally:
            reopened.close()
            storage.close()

    def test_delete_monitor_schedule_and_template(self):
        storage = AgentStorage(self.db_path)
        storage.upsert_monitor(
            {
                "monitor_id": "watcher",
                "name": "watcher",
                "account_id": "account-a",
                "action": "record",
            }
        )
        storage.record_monitor_run("watcher", "evt-1", "watcher:evt-1:record", "success", result={})
        storage.upsert_schedule(
            {
                "schedule_id": "hourly",
                "name": "hourly",
                "task_type": "record",
                "account_id": "account-a",
                "payload": {"body": "note"},
                "next_run_at": utc_now_iso(),
            }
        )
        storage.upsert_template({"template_id": "tpl", "name": "tpl", "body": "hi"})

        self.assertTrue(storage.delete_monitor("watcher"))
        self.assertIsNone(storage.get_monitor("watcher"))
        self.assertEqual(storage.list_monitor_runs("watcher"), [])

        self.assertTrue(storage.delete_schedule("hourly"))
        self.assertIsNone(storage.get_schedule("hourly"))
        self.assertEqual(storage.list_scheduler_runs("hourly"), [])

        self.assertTrue(storage.delete_template("tpl"))
        self.assertFalse(storage.delete_template("tpl"))
        self.assertFalse(storage.delete_monitor("watcher"))
        self.assertFalse(storage.delete_schedule("hourly"))
        storage.close()


if __name__ == "__main__":
    unittest.main()

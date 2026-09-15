"""Mandatory failure injection and fault boundary test suite for Agent RC.14 catch-up remediation.

Covers Taskbook Section 6:
1. fault before first event write -> no local progress
2. fault in the middle of a local transaction segment -> all writes in that segment roll back and cursor remains at previous committed boundary
3. fault after local commit but before Core ack -> restart/retry remains idempotent
4. Core ack failure after local commit -> no event loss and later reconciliation is safe
5. Core checkpoint failure after local commit -> local state remains valid and later checkpoint can advance monotonically
6. duplicate page replay -> zero duplicate receipt/memory/record growth
7. message memory/vector/FTS fault -> no cursor/data split
8. local-only monitor action -> idempotent under replay
9. external-side-effect monitor boundary -> batching cannot cause duplicate remote action after a local rollback
10. account A/B isolation and Identity v2 fail-closed behavior unchanged
"""

from __future__ import annotations

import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from agent_service.service import AgentService, AgentSettings
from agent_service.tests.helpers import FakeAI


class MockCoreService:
    def __init__(self):
        self.contract_major = 1
        self.accounts = [
            {
                "account_id": "account-a",
                "instance_uuid": "instance-a",
                "wechat_identity_uuid": "identity-a",
                "identity_binding_state": "bound",
            },
            {
                "account_id": "account-b",
                "instance_uuid": "instance-b",
                "wechat_identity_uuid": "identity-b",
                "identity_binding_state": "bound",
            },
        ]
        self.pages: list[dict[str, Any]] = []
        self.poll_calls: list[dict[str, Any]] = []
        self.ack_calls: list[list[str]] = []
        self.checkpoint_calls: list[dict[str, Any]] = []
        self.sends: list[dict[str, Any]] = []
        self.ack_failure: Exception | None = None
        self.checkpoint_failure: Exception | None = None
        self.poll_failure: Exception | None = None

    def ensure_contract(self, expected_major: int = 1) -> dict[str, Any]:
        return {"ok": True, "service": "mock-core", "contract_version": expected_major}

    def list_accounts(self) -> list[dict[str, Any]]:
        return [dict(a) for a in self.accounts]

    def poll_events(self, after: str = "0", limit: int = 100, consumer_id: str = "wechat-agent", timeout: int = 0) -> dict[str, Any]:
        if self.poll_failure:
            raise self.poll_failure
        self.poll_calls.append({"after": after, "limit": limit, "consumer_id": consumer_id})
        if self.pages:
            return self.pages.pop(0)
        return {"events": [], "next_cursor": after, "has_more": False}

    def ack_events(self, consumer_id: str, event_ids: list[str]) -> dict[str, Any]:
        if self.ack_failure:
            raise self.ack_failure
        self.ack_calls.append(list(event_ids))
        return {"consumer_id": consumer_id, "acked_event_ids": event_ids, "acked_count": len(event_ids)}

    def checkpoint_events(self, consumer_id: str, checkpoint: int, last_event_id: str = "") -> dict[str, Any]:
        if self.checkpoint_failure:
            raise self.checkpoint_failure
        self.checkpoint_calls.append({"consumer_id": consumer_id, "checkpoint": checkpoint, "last_event_id": last_event_id})
        return {"consumer_id": consumer_id, "checkpoint": checkpoint, "last_event_id": last_event_id}

    def send_text(self, account_id: str, chat_id: str, text: str, **kwargs: Any) -> dict[str, Any]:
        item = {"account_id": account_id, "chat_id": chat_id, "text": text, **kwargs}
        self.sends.append(item)
        return {"send_id": f"send-{len(self.sends)}", "status": "accepted", **item}


def make_status_event(event_id: str, cursor: int, account_id: str = "account-a") -> dict[str, Any]:
    return {
        "event_id": event_id,
        "cursor": str(cursor),
        "account_id": account_id,
        "event_type": "status.created",
        "occurred_at": "2026-08-31T07:00:00Z",
        "payload": {"status": "online", "account_id": account_id},
    }


def make_message_event(event_id: str, cursor: int, text: str = "hello world", account_id: str = "account-a", chat_id: str = "chat-1") -> dict[str, Any]:
    return {
        "event_id": event_id,
        "cursor": str(cursor),
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
                "text": text,
                "author": {"member_id": "user-1", "display_name": "User One", "is_self": False},
            }
        },
    }


class AgentCatchupFailureInjectionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "agent.sqlite"
        self.settings = AgentSettings(
            db_path=self.db_path,
            consumer_id="wechat-agent",
            poll_batch_size=100,
            core_commit_batch_threshold=1,
        )
        self.core = MockCoreService()
        self.ai = FakeAI()
        self.service = AgentService(self.settings, core=self.core, ai=self.ai)

    def tearDown(self):
        self.service.stop_workers()
        self.tempdir.cleanup()

    def test_1_fault_before_first_event_write(self):
        # 1. Fault before first event write -> no local progress.
        self.service.storage.set_meta("core_cursor", "100")
        events = [make_status_event(f"evt-{i}", 100 + i) for i in range(1, 4)]
        self.core.pages.append({"events": events, "next_cursor": "103", "has_more": False})

        with patch.object(self.service.storage, "session", side_effect=sqlite3.OperationalError("disk I/O error")):
            res = self.service.process_events_once()
            self.assertFalse(res["ok"])

        self.assertEqual(self.service.storage.get_meta("core_cursor"), "100")
        counts = self.service.storage.counts()
        self.assertEqual(counts["event_receipts"], 0)
        self.assertEqual(len(self.core.checkpoint_calls), 0)

    def test_2_fault_mid_segment_atomic_rollback(self):
        # 2. Fault in middle of local transaction segment -> all writes in that segment roll back.
        self.service.storage.set_meta("core_cursor", "50")
        events = [make_status_event(f"evt-{i}", 50 + i) for i in range(1, 6)]
        self.core.pages.append({"events": events, "next_cursor": "55", "has_more": False})

        original_store = self.service.storage.store_event
        def fail_on_third(event, conn=None):
            if event.get("event_id") == "evt-3":
                raise RuntimeError("simulated crash mid-segment on evt-3")
            return original_store(event, conn=conn)

        with patch.object(self.service.storage, "store_event", side_effect=fail_on_third):
            res = self.service.process_events_once()
            self.assertFalse(res["ok"])

        self.assertEqual(self.service.storage.get_meta("core_cursor"), "50")
        counts = self.service.storage.counts()
        self.assertEqual(counts["event_receipts"], 0)
        self.assertEqual(len(self.core.checkpoint_calls), 0)

    def test_3_fault_after_commit_before_ack_idempotent_retry(self):
        # 3. Fault after local commit but before Core ack -> restart/retry remains idempotent.
        self.service.storage.set_meta("core_cursor", "10")
        events = [
            make_status_event("evt-1", 11),
            make_message_event("evt-2", 12, "remember this"),
        ]
        self.core.pages.append({"events": copy.deepcopy(events), "next_cursor": "12", "has_more": False})

        with patch.object(self.core, "ack_events", side_effect=RuntimeError("process killed before ack")):
            res = self.service.process_events_once()
            self.assertFalse(res["ok"])

        self.assertEqual(self.service.storage.get_meta("core_cursor"), "12")
        counts1 = self.service.storage.counts()
        self.assertEqual(counts1["event_receipts"], 2)
        self.assertEqual(self.service.memory.count(), 1)

        self.core.pages.append({"events": copy.deepcopy(events), "next_cursor": "12", "has_more": False})
        res2 = self.service.process_events_once()
        self.assertTrue(res2["ok"])
        self.assertEqual(res2["duplicates"], 2)
        self.assertEqual(res2["processed"], 0)

        counts2 = self.service.storage.counts()
        self.assertEqual(counts2["event_receipts"], 2)
        self.assertEqual(self.service.memory.count(), 1)
        self.assertEqual(len(self.core.ack_calls), 1)
        self.assertIn("evt-1", self.core.ack_calls[0])
        self.assertIn("evt-2", self.core.ack_calls[0])

    def test_4_core_ack_failure_after_commit_safe(self):
        # 4. Core ack failure after local commit -> no event loss and later reconciliation is safe.
        self.service.storage.set_meta("core_cursor", "20")
        events = [make_status_event("evt-21", 21)]
        self.core.pages.append({"events": copy.deepcopy(events), "next_cursor": "21", "has_more": False})

        self.core.ack_failure = RuntimeError("Core 502 Bad Gateway on ack")
        res = self.service.process_events_once()
        self.assertFalse(res["ok"])

        self.assertEqual(self.service.storage.get_meta("core_cursor"), "21")
        self.assertTrue(self.service.storage.event_seen("evt-21"))

        self.core.ack_failure = None
        self.core.pages.append({"events": copy.deepcopy(events), "next_cursor": "21", "has_more": False})
        res2 = self.service.process_events_once()
        self.assertTrue(res2["ok"])
        self.assertEqual(res2["duplicates"], 1)
        self.assertEqual(len(self.core.ack_calls), 1)

    def test_5_core_checkpoint_failure_after_commit(self):
        # 5. Core checkpoint failure after local commit -> local state remains valid.
        self.service.storage.set_meta("core_cursor", "30")
        events_page1 = [make_status_event(f"evt-{i}", i) for i in (31, 32)]
        self.core.pages.append({"events": copy.deepcopy(events_page1), "next_cursor": "32", "has_more": True})

        self.core.checkpoint_failure = RuntimeError("Core 503 Checkpoint Busy")
        res1 = self.service.process_events_once()
        self.assertEqual(self.service.storage.get_meta("core_cursor"), "32")
        self.assertTrue(self.service.storage.event_seen("evt-32"))

        self.core.checkpoint_failure = None
        events_page2 = [make_status_event(f"evt-{i}", i) for i in (33, 34)]
        self.core.pages.append({"events": copy.deepcopy(events_page2), "next_cursor": "34", "has_more": False})
        res2 = self.service.process_events_once()
        self.assertTrue(res2["ok"])
        self.assertEqual(self.service.storage.get_meta("core_cursor"), "34")

        self.assertEqual(len(self.core.checkpoint_calls), 1)
        self.assertEqual(self.core.checkpoint_calls[0]["checkpoint"], 34)

    def test_6_duplicate_page_replay_zero_growth(self):
        # 6. Duplicate page replay -> zero duplicate receipt/memory/record growth.
        self.service.storage.upsert_monitor({
            "monitor_id": "mon-record",
            "name": "Record all",
            "account_id": "account-a",
            "action": "record",
            "enabled": True,
        })
        page = [
            make_status_event("evt-101", 101),
            make_message_event("evt-102", 102, "msg one"),
            make_message_event("evt-103", 103, "msg two"),
        ]

        self.core.pages.append({"events": copy.deepcopy(page), "next_cursor": "103", "has_more": False})
        res1 = self.service.process_events_once()
        self.assertTrue(res1["ok"])
        self.assertEqual(res1["processed"], 3)
        self.assertEqual(res1["duplicates"], 0)

        receipts_1 = self.service.storage.counts()["event_receipts"]
        memory_1 = self.service.memory.count()
        records_1 = self.service.storage.counts()["records"]
        self.assertEqual(receipts_1, 3)
        self.assertEqual(memory_1, 2)
        self.assertGreaterEqual(records_1, 1)

        self.core.pages.append({"events": copy.deepcopy(page), "next_cursor": "103", "has_more": False})
        res2 = self.service.process_events_once()
        self.assertTrue(res2["ok"])
        self.assertEqual(res2["processed"], 0)
        self.assertEqual(res2["duplicates"], 3)

        self.assertEqual(self.service.storage.counts()["event_receipts"], receipts_1)
        self.assertEqual(self.service.memory.count(), memory_1)
        self.assertEqual(self.service.storage.counts()["records"], records_1)

    def test_7_message_memory_fault_prevents_cursor_data_split(self):
        # 7. Message memory/vector/FTS fault -> no cursor/data split.
        self.service.storage.set_meta("core_cursor", "70")
        events = [
            make_status_event("evt-71", 71),
            make_message_event("evt-72", 72, "important message"),
        ]
        self.core.pages.append({"events": events, "next_cursor": "72", "has_more": False})

        with patch.object(self.service.memory, "ingest_message", side_effect=sqlite3.OperationalError("FTS corrupt")):
            res = self.service.process_events_once()
            self.assertFalse(res["ok"])

        self.assertEqual(self.service.storage.get_meta("core_cursor"), "70")
        self.assertEqual(self.service.storage.counts()["event_receipts"], 0)
        self.assertEqual(self.service.memory.count(), 0)

    def test_8_local_only_monitor_action_idempotent_replay(self):
        # 8. Local-only monitor action -> idempotent under replay.
        self.service.storage.upsert_monitor({
            "monitor_id": "mon-local-1",
            "name": "Note taker",
            "account_id": "account-a",
            "action": "record",
            "enabled": True,
        })
        event = make_message_event("evt-note", 81, "please take note")
        self.core.pages.append({"events": [copy.deepcopy(event)], "next_cursor": "81", "has_more": False})

        res1 = self.service.process_events_once()
        self.assertTrue(res1["ok"])
        rec_count1 = self.service.storage.counts()["records"]
        self.assertEqual(rec_count1, 1)

        self.core.pages.append({"events": [copy.deepcopy(event)], "next_cursor": "81", "has_more": False})
        res2 = self.service.process_events_once()
        self.assertTrue(res2["ok"])
        rec_count2 = self.service.storage.counts()["records"]
        self.assertEqual(rec_count2, 1)

    def test_9_external_side_effect_boundary(self):
        # 9. External-side-effect monitor boundary -> batching cannot cause duplicate remote action after a local rollback.
        self.service.storage.upsert_monitor({
            "monitor_id": "mon-send",
            "name": "Send reply",
            "account_id": "account-a",
            "action": "send_text",
            "expected_wechat_identity_uuid": "identity-a",
            "enabled": True,
            "action_config": {"text": "auto reply"},
        })

        events = [
            make_status_event("evt-s1", 91),
            make_message_event("evt-s2", 92, "trigger remote send"),
            make_status_event("evt-s3", 93),
        ]
        self.core.pages.append({"events": copy.deepcopy(events), "next_cursor": "93", "has_more": False})

        original_store = self.service.storage.store_event
        def fail_on_s3(event, conn=None):
            if event.get("event_id") == "evt-s3":
                raise RuntimeError("error on evt-s3 after external action")
            return original_store(event, conn=conn)

        with patch.object(self.service.storage, "store_event", side_effect=fail_on_s3):
            res = self.service.process_events_once()
            self.assertFalse(res["ok"])

        self.assertEqual(len(self.core.sends), 1)
        self.assertEqual(self.core.sends[0]["text"], "auto reply")

        self.assertTrue(self.service.storage.event_seen("evt-s1"))
        self.assertTrue(self.service.storage.event_seen("evt-s2"))
        self.assertFalse(self.service.storage.event_seen("evt-s3"))
        self.assertEqual(self.service.storage.get_meta("core_cursor"), "92")

    def test_10_account_isolation_and_identity_v2_fail_closed(self):
        # 10. Account A/B isolation and Identity v2 fail-closed behavior unchanged.
        self.service.storage.upsert_monitor({
            "monitor_id": "mon-isolated",
            "name": "Only Account A",
            "account_id": "account-a",
            "action": "send_text",
            "expected_wechat_identity_uuid": "identity-a",
            "enabled": True,
            "action_config": {"text": "hello A"},
        })

        event_b = make_message_event("evt-b", 1, "msg for B", account_id="account-b")
        self.core.pages.append({"events": [event_b], "next_cursor": "1", "has_more": False})
        res_b = self.service.process_events_once()
        self.assertTrue(res_b["ok"])
        self.assertEqual(len(self.core.sends), 0)

        self.core.accounts[0]["identity_binding_state"] = "unbound"
        event_a = make_message_event("evt-a", 2, "msg for A", account_id="account-a")
        self.core.pages.append({"events": [event_a], "next_cursor": "2", "has_more": False})
        res_a = self.service.process_events_once()
        self.assertTrue(res_a["ok"])
        self.assertEqual(len(self.core.sends), 0)
        runs = self.service.storage.list_monitor_runs("mon-isolated")
        self.assertGreaterEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failed")
        self.assertIn("unbound", runs[0]["error"])

    def test_11_poll_loop_backlog_has_more_no_sleep(self):
        # Phase 1.5: backlog with has_more=True immediately continues without 2s sleep
        evt1 = make_status_event("evt-bl-1", 1)
        evt2 = make_status_event("evt-bl-2", 2)
        self.core.pages = [
            {"events": [evt1], "next_cursor": "1", "has_more": True},
            {"events": [evt2], "next_cursor": "2", "has_more": True},
            {"events": [], "next_cursor": "2", "has_more": False},
        ]

        wait_calls = []
        real_wait = self.service._stop.wait
        def spied_wait(timeout=None):
            wait_calls.append(timeout)
            # Stop after we observe the caught-up sleep
            if timeout and timeout >= 1.0:
                self.service._stop.set()
                return True
            return real_wait(timeout=0)

        with patch.object(self.service._stop, "wait", side_effect=spied_wait):
            self.service._poll_loop()

        # Page 1 -> Page 2 had has_more=True with progress, so no sleep was called
        # After Page 3, has_more=False, so normal sleep was called
        self.assertEqual(self.service.storage.get_meta("core_cursor"), "2")
        self.assertEqual(len(wait_calls), 1)
        self.assertEqual(wait_calls[0], self.service.settings.poll_interval_seconds)

    def test_12_poll_loop_caught_up_has_more_false_normal_sleep(self):
        # Phase 1.5: caught up with has_more=False preserves normal poll_interval_seconds sleep
        self.core.pages = [
            {"events": [], "next_cursor": "0", "has_more": False},
        ]

        wait_calls = []
        def spied_wait(timeout=None):
            wait_calls.append(timeout)
            self.service._stop.set()
            return True

        with patch.object(self.service._stop, "wait", side_effect=spied_wait):
            self.service._poll_loop()

        self.assertEqual(len(wait_calls), 1)
        self.assertEqual(wait_calls[0], self.service.settings.poll_interval_seconds)

    def test_13_poll_loop_error_bounded_backoff(self):
        # Phase 1.5: poll error enforces bounded backoff (>= 2.0s)
        self.core.poll_failure = RuntimeError("simulated core outage")

        wait_calls = []
        def spied_wait(timeout=None):
            wait_calls.append(timeout)
            self.service._stop.set()
            return True

        with patch.object(self.service._stop, "wait", side_effect=spied_wait):
            self.service._poll_loop()

        self.assertEqual(len(wait_calls), 1)
        self.assertGreaterEqual(wait_calls[0], 2.0)

    def test_14_poll_loop_anti_busy_spin_stalled_progress(self):
        # Phase 1.5: has_more=True but no cursor or events progress enforces fail-safe backoff (not busy-spin)
        self.core.pages = [
            {"events": [], "next_cursor": "0", "has_more": True},
        ]

        wait_calls = []
        def spied_wait(timeout=None):
            wait_calls.append(timeout)
            self.service._stop.set()
            return True

        with patch.object(self.service._stop, "wait", side_effect=spied_wait):
            self.service._poll_loop()

        self.assertEqual(len(wait_calls), 1)
        self.assertGreaterEqual(wait_calls[0], 1.0)

    def test_15_poll_loop_shutdown_responsiveness(self):
        # Phase 1.5: setting _stop promptly exits loop
        self.service._stop.set()
        # Should return immediately without executing any poll calls
        self.service._poll_loop()
        self.assertEqual(len(self.core.poll_calls), 0)


if __name__ == "__main__":
    unittest.main()
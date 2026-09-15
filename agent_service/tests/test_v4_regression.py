"""RC.14 V4 regression guard for the V3 catch-up optimizations.

V4 must not regress any V3 behaviour. Each test below pins one V3 feature and
one V4 invariant:

* contract cache (TTL + fail-closed invalidation)
* identity cache (TTL + invalidation restricted to account lifecycle events)
* HTTP keep-alive on every Core request
* adaptive Core checkpoint cadence (batch threshold and caught-up flush)
* duplicate suppression
* graceful stop flush (local cursor == Core checkpoint, no pending acks)
* V4: a 400-event local atomic batch is assembled from polls that never exceed
  Core's 200-event contract limit
* V4: the cursor never advances past its durable receipts, and the cursor write
  lives in the same transaction as those receipts
"""
from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from agent_service.core_client import CoreApiError, CoreClient, CoreResponse
from agent_service.service import CORE_POLL_HARD_LIMIT, AgentService, AgentSettings


def status_event(index: int) -> dict[str, Any]:
    return {
        "event_id": f"v4-evt-{index}",
        "cursor": str(index),
        "account_id": "account-a",
        "event_type": "status.created",
        "occurred_at": "2026-09-15T00:00:00Z",
        "payload": {"status": "online"},
    }


def account_event(index: int, event_type: str = "account.identity_bound") -> dict[str, Any]:
    return {
        "event_id": f"v4-acc-{index}",
        "cursor": str(index),
        "account_id": "account-a",
        "event_type": event_type,
        "occurred_at": "2026-09-15T00:00:00Z",
        "payload": {"account": {"account_id": "account-a", "wechat_identity_uuid": "identity-a"}},
    }


class RecordingCore:
    """Core stand-in that records the exact poll limits it was asked for."""

    def __init__(self, total: int = 400):
        self.total = int(total)
        self.checkpoint = 0
        self.poll_limits: list[int] = []
        self.ack_calls: list[list[str]] = []
        self.contract_calls = 0
        self.accounts = [
            {
                "account_id": "account-a",
                "instance_uuid": "instance-a",
                "wechat_identity_uuid": "identity-a",
                "identity_binding_state": "bound",
            }
        ]
        #: when set, the next poll returns exactly these events
        self.override_page: list[dict[str, Any]] | None = None

    def ensure_contract(self, expected_major: int = 1) -> dict[str, Any]:
        self.contract_calls += 1
        return {"ok": True, "service": "recording-core", "contract_version": expected_major}

    def list_accounts(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.accounts]

    def poll_events(self, *, after: str = "0", limit: int = 200, consumer_id: str = "", timeout: int = 0):
        # Mirror Core's frozen contract: hard cap at 200.
        effective = max(1, min(int(limit), CORE_POLL_HARD_LIMIT))
        self.poll_limits.append(effective)
        if self.override_page is not None:
            events = list(self.override_page)
            self.override_page = None
            nxt = int(events[-1]["cursor"]) if events else int(after or "0")
            return {"events": events, "next_cursor": nxt, "has_more": False}
        start = int(after or "0") + 1
        events = [status_event(i) for i in range(start, min(start + effective, self.total + 1))]
        nxt = int(events[-1]["cursor"]) if events else int(after or "0")
        return {"events": events, "next_cursor": nxt, "has_more": nxt < self.total}

    def commit_events(self, consumer_id: str, cursor: int, event_ids: list[str], *, last_event_id: str = "", **kw):
        self.checkpoint = max(self.checkpoint, int(cursor))
        self.ack_calls.append(list(event_ids))
        return {
            "consumer_id": consumer_id,
            "acked_count": len(event_ids),
            "checkpoint": {"consumer_id": consumer_id, "processed_through_cursor": self.checkpoint},
        }


class V4RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "agent.sqlite"
        self.services: list[AgentService] = []

    def tearDown(self):
        for service in self.services:
            try:
                service.shutdown()
            except Exception:
                pass
        self.tempdir.cleanup()

    def _service(self, core: RecordingCore, **overrides) -> AgentService:
        base = AgentSettings(
            db_path=self.db_path,
            consumer_id="v4-regression",
            poll_interval_seconds=0.0,
            poll_batch_size=400,
            core_commit_batch_threshold=600,
            core_commit_interval_seconds=20.0,
        )
        settings = dataclasses.replace(base, **overrides)
        service = AgentService(settings, core=core)
        self.services.append(service)
        return service

    # -- V4: batch 400 via multiple contract-limited polls ----------------
    def test_local_batch_400_is_two_polls_of_at_most_200(self):
        core = RecordingCore(total=400)
        service = self._service(core)
        result = service.process_events_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["events"], 400)
        self.assertEqual(result["local_batch_target"], 400)
        self.assertEqual(result["core_polls"], 2)
        self.assertEqual(core.poll_limits, [200, 200])
        self.assertEqual(service.storage.get_meta("core_cursor", "0"), "400")
        self.assertEqual(service.storage.counts()["event_receipts"], 400)
        self.assertEqual(result["duplicates"], 0)

    def test_batch_target_never_exceeds_contract_limit_per_poll(self):
        core = RecordingCore(total=1000)
        service = self._service(core)
        service.process_events_once()
        self.assertTrue(core.poll_limits)
        self.assertLessEqual(max(core.poll_limits), CORE_POLL_HARD_LIMIT)
        self.assertEqual(service.storage.get_meta("core_cursor", "0"), "400")

    # -- V4: cursor never runs ahead of durable receipts ------------------
    def test_cursor_never_exceeds_durable_receipts(self):
        core = RecordingCore(total=1600)
        service = self._service(core)
        for _ in range(4):
            result = service.process_events_once()
            if not result.get("ok") or int(result.get("events") or 0) == 0:
                break
            cursor = int(service.storage.get_meta("core_cursor", "0") or 0)
            with service.storage._lock:  # noqa: SLF001 - assertion helper
                conn = service.storage.writer()
                durable = int(
                    conn.execute(
                        "SELECT COALESCE(MAX(CAST(cursor AS INTEGER)), 0) FROM event_receipts"
                    ).fetchone()[0]
                )
                receipts = int(conn.execute("SELECT COUNT(*) FROM event_receipts").fetchone()[0])
            self.assertLessEqual(cursor, durable, "cursor must not pass durable receipts")
            self.assertEqual(receipts, durable, "receipts must be contiguous up to the cursor")

    def test_cursor_write_is_inside_the_same_transaction_as_the_receipts(self):
        core = RecordingCore(total=400)
        service = self._service(core)
        observed: list[tuple[int, int]] = []
        original = service.storage.set_meta

        def spy(key, value, *, conn=None):
            if key == "core_cursor" and conn is not None:
                observed.append(
                    (
                        int(value),
                        int(conn.execute("SELECT COUNT(*) FROM event_receipts").fetchone()[0]),
                    )
                )
            return original(key, value, conn=conn)

        with patch.object(service.storage, "set_meta", side_effect=spy):
            service.process_events_once()
        self.assertTrue(observed, "the cursor must be written inside the batch transaction")
        cursor, receipts_inside_txn = observed[-1]
        self.assertEqual(cursor, 400)
        self.assertEqual(receipts_inside_txn, 400)
        self.assertEqual(int(service.storage.get_meta("core_cursor", "0")), receipts_inside_txn)

    # -- V3 regression: contract cache ------------------------------------
    def test_contract_cache_ttl_and_fail_closed_invalidation(self):
        client = CoreClient("http://127.0.0.1:8080", contract_ttl=60.0)
        with patch.object(
            client, "_request", return_value=CoreResponse(200, {"contract_version": 1}, {})
        ) as req:
            client.ensure_contract(1)
            client.ensure_contract(1)
            self.assertEqual(req.call_count, 1, "contract must be cached within the TTL")
            client.ensure_contract(1, force=True)
            self.assertEqual(req.call_count, 2)

        client2 = CoreClient("http://127.0.0.1:8080")
        with patch.object(
            client2, "_request", return_value=CoreResponse(200, {"contract_version": 7}, {})
        ):
            with self.assertRaises(CoreApiError):
                client2.ensure_contract(1)
            self.assertIsNone(client2._cached_contract, "mismatch must clear the cache")

    def test_http_keepalive_header_is_sent(self):
        client = CoreClient("http://127.0.0.1:8080")
        captured: dict[str, Any] = {}

        class FakeResponse:
            status = 200
            headers: dict[str, str] = {}

            def read(self):
                return b'{"ok": true}'

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout=None):
            captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
            captured["url"] = request.full_url
            return FakeResponse()

        with patch("agent_service.core_client.urlopen", side_effect=fake_urlopen):
            client.health()
        self.assertEqual(captured["headers"].get("connection"), "keep-alive")
        self.assertEqual(captured["headers"].get("accept"), "application/json")

    # -- V3 regression: identity cache ------------------------------------
    def test_identity_cache_invalidated_only_by_account_lifecycle(self):
        core = RecordingCore(total=1)
        service = self._service(core)
        service.monitor.identity_ttl = 3600.0

        invalidations: list[int] = []
        original = service.monitor.invalidate_identity_cache

        def spy():
            invalidations.append(1)
            return original()

        with patch.object(service.monitor, "invalidate_identity_cache", side_effect=spy):
            service.process_events_once()  # status-only page
            self.assertEqual(len(invalidations), 0, "heartbeat events must not invalidate the cache")
            self.assertIsNotNone(service.monitor._cached_identity_view)

            service.process_events_once()  # another status-only page
            self.assertEqual(len(invalidations), 0)

            service.storage.set_meta("core_cursor", "1")
            core.override_page = [account_event(2)]
            service.process_events_once()
            self.assertEqual(
                len(invalidations), 1, "account lifecycle events must invalidate the identity cache"
            )

    # -- V3 regression: adaptive Core checkpoint cadence ------------------
    def test_adaptive_core_checkpoint_by_batch_threshold(self):
        core = RecordingCore(total=6)
        service = self._service(
            core, poll_batch_size=2, core_commit_batch_threshold=4, core_commit_interval_seconds=3600.0
        )
        first = service.process_events_once()
        self.assertTrue(first["ok"])
        self.assertEqual(first["events"], 2)
        self.assertEqual(len(core.ack_calls), 0, "below threshold: Core commit must be deferred")
        self.assertEqual(service.storage.get_meta("core_cursor", "0"), "2")

        second = service.process_events_once()
        self.assertTrue(second["ok"])
        self.assertGreaterEqual(len(core.ack_calls), 1, "threshold reached: Core commit fires")
        self.assertEqual(core.checkpoint, 4)

    def test_core_checkpoint_on_caught_up_page(self):
        core = RecordingCore(total=3)
        service = self._service(
            core, core_commit_batch_threshold=10_000, core_commit_interval_seconds=3600.0
        )
        result = service.process_events_once()
        self.assertTrue(result["ok"])
        self.assertFalse(result["has_more"])
        self.assertGreaterEqual(len(core.ack_calls), 1, "caught-up page must flush to Core")
        self.assertEqual(core.checkpoint, 3)

    # -- V3 regression: duplicate suppression -----------------------------
    def test_duplicate_suppression_zero_growth(self):
        core = RecordingCore(total=400)
        service = self._service(core)
        service.process_events_once()
        first = service.storage.counts()

        service.storage.set_meta("core_cursor", "0")  # force redelivery
        replay = service.process_events_once()
        self.assertEqual(replay["duplicates"], 400)
        self.assertEqual(replay["processed"], 0)
        second = service.storage.counts()
        self.assertEqual(second["event_receipts"], first["event_receipts"])
        self.assertEqual(service.memory.count(), 0)

    # -- V3 regression: graceful stop flush -------------------------------
    def test_graceful_stop_flush_aligns_cursor_with_core(self):
        core = RecordingCore(total=800)
        service = self._service(
            core, core_commit_batch_threshold=10_000, core_commit_interval_seconds=3600.0
        )
        result = service.process_events_once()
        self.assertTrue(result["has_more"])
        self.assertEqual(len(core.ack_calls), 0, "deferred Core commit is still pending")

        service.stop_workers()
        self.assertGreaterEqual(len(core.ack_calls), 1, "stop must flush pending acks")
        self.assertEqual(core.checkpoint, 400)
        self.assertEqual(service.storage.get_meta("core_cursor", "0"), "400")

        shutdown = service.shutdown()
        self.assertTrue(shutdown["storage"]["closed"])
        self.assertFalse(Path(str(self.db_path) + "-wal").exists(), "WAL must be checkpointed away")

    # -- encoding ---------------------------------------------------------
    def test_receipt_payload_round_trips_as_json(self):
        core = RecordingCore(total=2)
        service = self._service(core)
        service.process_events_once()
        with service.storage._lock:  # noqa: SLF001
            conn = service.storage.writer()
            rows = conn.execute("SELECT payload_json FROM event_receipts LIMIT 1").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIsInstance(json.loads(rows[0]["payload_json"]), dict)


if __name__ == "__main__":
    unittest.main()

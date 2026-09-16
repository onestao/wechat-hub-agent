"""RC.14 V5 minimal production-path optimisation — regression guard.

V5 changes exactly two things and nothing else:

* **V5-1** the catch-up identity path may no longer bypass the identity TTL
  cache. ``MonitorEngine._resolve_identity()`` used to call
  ``identity_view(force=True)`` on a cache miss, which turned every miss into an
  extra full ``GET /v1/accounts``. It now fails closed instead, and recovery is
  bounded by the TTL or by an explicit ``invalidate_identity_cache()``.
* **V5-2** a Core that does not implement ``POST /v1/events/commit`` is a
  *capability state*, not a per-batch event. It is discovered once, cached, and
  every later batch goes straight to the canonical ack + checkpoint path.

Storage semantics are deliberately untouched by V5 (long-lived writer, local
batch 400, ``journal_mode=wal``, ``synchronous=FULL``).
"""
from __future__ import annotations

import dataclasses
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from agent_service.core_client import CoreApiError, CoreClient, CoreResponse
from agent_service.monitor import IdentityBlocked, MonitorEngine
from agent_service.service import AgentService, AgentSettings

ACCOUNT_A = {
    "account_id": "account-a",
    "instance_uuid": "instance-a",
    "wechat_identity_uuid": "identity-a",
    "identity_binding_state": "bound",
}
ACCOUNT_B = {
    "account_id": "account-b",
    "instance_uuid": "instance-b",
    "wechat_identity_uuid": "identity-b",
    "identity_binding_state": "bound",
}


class CountingCore:
    """Minimal Core stand-in that counts identity fetches."""

    def __init__(self, accounts: list[dict[str, Any]] | None = None):
        self.accounts = [dict(row) for row in (accounts if accounts is not None else [ACCOUNT_A])]
        self.list_accounts_calls = 0
        self.fail_with: Exception | None = None

    def list_accounts(self) -> list[dict[str, Any]]:
        self.list_accounts_calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        return [dict(row) for row in self.accounts]


def monitor_row(account_id: str, action: str = "record", expected: str = "") -> dict[str, Any]:
    row = {"monitor_id": "m-1", "account_id": account_id, "action": action, "enabled": True}
    if expected:
        row["expected_wechat_identity_uuid"] = expected
    return row


class IdentityCacheV5Tests(unittest.TestCase):
    def _engine(self, core: CountingCore, ttl: float = 60.0) -> MonitorEngine:
        return MonitorEngine(MagicMock(), core, MagicMock(), MagicMock(), identity_ttl=ttl)

    def test_repeated_batches_within_ttl_fetch_accounts_once(self):
        core = CountingCore()
        engine = self._engine(core)
        for _ in range(25):
            view = engine.identity_view()
            self.assertIn("account-a", view)
        self.assertEqual(core.list_accounts_calls, 1, "25 batches inside the TTL must cost one fetch")
        self.assertEqual(engine.identity_fetch_count, 1)
        self.assertEqual(engine.identity_cache_hit_count, 24)

    def test_ttl_expiry_refreshes(self):
        core = CountingCore()
        engine = self._engine(core, ttl=60.0)
        with patch("agent_service.monitor.time.monotonic", return_value=1_000.0):
            engine.identity_view()
        with patch("agent_service.monitor.time.monotonic", return_value=1_030.0):
            engine.identity_view()
            self.assertEqual(core.list_accounts_calls, 1, "still inside the TTL window")
        with patch("agent_service.monitor.time.monotonic", return_value=1_061.0):
            engine.identity_view()
        self.assertEqual(core.list_accounts_calls, 2, "TTL expiry must refresh")

    def test_identity_invalidation_refreshes(self):
        core = CountingCore()
        engine = self._engine(core)
        engine.identity_view()
        engine.identity_view()
        self.assertEqual(core.list_accounts_calls, 1)
        engine.invalidate_identity_cache()
        engine.identity_view()
        self.assertEqual(core.list_accounts_calls, 2, "invalidation must refresh")

    def test_account_switch_does_not_reuse_stale_identity(self):
        core = CountingCore([ACCOUNT_A])
        engine = self._engine(core)
        engine.identity_view()
        with self.assertRaises(IdentityBlocked):
            engine._resolve_identity(
                monitor_row("account-b"), "account-b", identity_view=engine.identity_view()
            )
        self.assertEqual(core.list_accounts_calls, 1, "an unresolved account must not force a fetch")

        # The account really exists now; only an explicit invalidation (what an
        # account lifecycle event does) makes it visible inside the TTL window.
        core.accounts = [ACCOUNT_A, ACCOUNT_B]
        engine.invalidate_identity_cache()
        identity, bound = engine._resolve_identity(
            monitor_row("account-b"), "account-b", identity_view=engine.identity_view()
        )
        self.assertEqual(identity["wechat_identity_uuid"], "identity-b")
        self.assertEqual(bound["account_id"], "account-b")
        self.assertEqual(core.list_accounts_calls, 2)

    def test_unresolved_account_does_not_bypass_ttl(self):
        """The V5-1 regression: N batches with an unknown account = 1 fetch."""
        core = CountingCore([ACCOUNT_A])
        engine = self._engine(core)
        for _ in range(10):
            with self.assertRaises(IdentityBlocked):
                engine._resolve_identity(
                    monitor_row("ghost"), "ghost", identity_view=engine.identity_view()
                )
        self.assertEqual(core.list_accounts_calls, 1, "a miss must never bypass the TTL cache")
        self.assertEqual(engine.identity_unresolved_count, 10)

    def test_core_error_fails_closed(self):
        core = CountingCore()
        core.fail_with = CoreApiError(0, "core_unavailable", "boom")
        engine = self._engine(core)
        with self.assertRaises(CoreApiError):
            engine.identity_view()
        self.assertIsNone(engine._cached_identity_view, "a failed fetch must not poison the cache")

    def test_explicit_force_still_bypasses_ttl(self):
        core = CountingCore()
        engine = self._engine(core)
        engine.identity_view()
        engine.identity_view(force=True)
        self.assertEqual(core.list_accounts_calls, 2, "the admin/external force path must still work")

    def test_external_action_rule_still_forces_refresh(self):
        core = CountingCore([ACCOUNT_A])
        engine = self._engine(core)
        engine.identity_view()
        engine._resolve_identity(monitor_row("account-a", action="send"), "account-a", identity_view=None)
        self.assertEqual(core.list_accounts_calls, 2, "side-effecting rules keep the fresh read")

    def test_expected_identity_mismatch_still_blocks(self):
        core = CountingCore([ACCOUNT_A])
        engine = self._engine(core)
        with self.assertRaises(IdentityBlocked):
            engine._resolve_identity(
                monitor_row("account-a", expected="identity-old"),
                "account-a",
                identity_view=engine.identity_view(),
            )


class RoutedCore:
    """Real ``CoreClient`` with a routed ``_request``; records every endpoint hit.

    Delegates the whole Core surface so it can stand in for ``CoreClient`` in
    ``AgentService`` while still letting the test inspect request counts.
    """

    def __init__(self, *, commit_supported: bool, accounts: list[dict[str, Any]] | None = None, total: int = 600):
        self.commit_supported = bool(commit_supported)
        self.total = int(total)
        self.calls: list[str] = []
        self.accounts = [dict(row) for row in (accounts if accounts is not None else [ACCOUNT_A])]
        self.client = CoreClient("http://127.0.0.1:8080", contract_ttl=60.0)
        self._patch = patch.object(self.client, "_request", side_effect=self._route)
        self._patch.start()

    def __getattr__(self, name: str) -> Any:
        if name == "client":
            raise AttributeError(name)
        return getattr(self.client, name)

    def stop(self) -> None:
        self._patch.stop()

    def _route(self, method: str, path: str, **kwargs: Any) -> CoreResponse:
        self.calls.append(f"{method} {path}")
        if path == "/health":
            return CoreResponse(200, {"ok": True, "contract_version": 1}, {})
        if path == "/v1/accounts":
            return CoreResponse(200, {"accounts": [dict(r) for r in self.accounts]}, {})
        if path == "/v1/events/commit":
            if self.commit_supported:
                payload = kwargs.get("payload") or {}
                return CoreResponse(
                    200,
                    {
                        "consumer_id": payload.get("consumer_id"),
                        "acked_count": len(payload.get("event_ids") or []),
                        "processed_through_cursor": payload.get("processed_through_cursor"),
                    },
                    {},
                )
            self.client._clear_contract_cache()  # mirrors the real HTTPError path
            raise CoreApiError(404, "not_found", "unknown path")
        if path == "/v1/events/ack":
            payload = kwargs.get("payload") or {}
            return CoreResponse(
                200,
                {
                    "consumer_id": payload.get("consumer_id"),
                    "acked_event_ids": payload.get("event_ids") or [],
                    "acked_count": len(payload.get("event_ids") or []),
                },
                {},
            )
        if path == "/v1/events/checkpoint":
            payload = kwargs.get("payload") or {}
            return CoreResponse(
                200,
                {
                    "consumer_id": payload.get("consumer_id"),
                    "processed_through_cursor": payload.get("processed_through_cursor"),
                    "last_event_id": payload.get("last_event_id", ""),
                    "subscription_account_id": payload.get("subscription_account_id", ""),
                },
                {},
            )
        if path == "/v1/events/poll":
            query = kwargs.get("query") or {}
            after = int(query.get("after") or 0)
            limit = max(1, min(int(query.get("limit") or 50), 200))  # Core's frozen cap
            events = [
                {
                    "event_id": f"v5-evt-{index}",
                    "cursor": str(index),
                    "account_id": "account-a",
                    "event_type": "status.created",
                    "occurred_at": "2026-09-16T00:00:00Z",
                    "payload": {"status": "online"},
                }
                for index in range(after + 1, min(after + limit, self.total) + 1)
            ]
            nxt = int(events[-1]["cursor"]) if events else after
            return CoreResponse(
                200, {"events": events, "next_cursor": nxt, "has_more": nxt < self.total}, {}
            )
        raise AssertionError(f"unexpected path {path}")

    def count(self, needle: str) -> int:
        return sum(1 for call in self.calls if call.endswith(needle))


class CommitCapabilityV5Tests(unittest.TestCase):
    def setUp(self):
        self.routed: list[RoutedCore] = []

    def tearDown(self):
        for routed in self.routed:
            routed.stop()

    def _routed(self, *, commit_supported: bool) -> RoutedCore:
        routed = RoutedCore(commit_supported=commit_supported)
        self.routed.append(routed)
        return routed

    def test_unsupported_commit_endpoint_discovered_once(self):
        routed = self._routed(commit_supported=False)
        for cursor in (100, 200, 300):
            result = routed.client.commit_events("c-1", cursor, ["e-1", "e-2"])
            self.assertEqual(result["mode"], "fallback_2phase")
            self.assertFalse(result["commit_endpoint_supported"])
        self.assertEqual(routed.count("/v1/events/commit"), 1, "the 404 must be discovered exactly once")
        self.assertEqual(routed.client.event_commit_probe_count, 1)
        self.assertIs(routed.client.event_commit_endpoint_supported, False)

    def test_zero_commit_probe_after_discovery(self):
        routed = self._routed(commit_supported=False)
        routed.client.commit_events("c-1", 100, ["e-1"])
        before = routed.count("/v1/events/commit")
        for cursor in range(101, 121):
            routed.client.commit_events("c-1", cursor, [f"e-{cursor}"])
        self.assertEqual(routed.count("/v1/events/commit") - before, 0, "no commit probes on later batches")

    def test_ack_and_checkpoint_semantics_unchanged(self):
        routed = self._routed(commit_supported=False)
        routed.client.commit_events(
            "c-1",
            4_242,
            ["e-1", "e-2", "e-3"],
            last_event_id="event-xyz",
            subscription_account_id="account-a",
        )
        self.assertEqual(routed.count("/v1/events/ack"), 1)
        self.assertEqual(routed.count("/v1/events/checkpoint"), 1)
        result = routed.client.commit_events(
            "c-1", 4_243, ["e-4"], last_event_id="event-abc", subscription_account_id="account-a"
        )
        self.assertEqual(result["acked_count"], 1)
        self.assertEqual(result["checkpoint"]["processed_through_cursor"], 4_243)
        self.assertEqual(result["checkpoint"]["last_event_id"], "event-abc")
        self.assertEqual(result["checkpoint"]["subscription_account_id"], "account-a")

    def test_empty_event_ids_skip_the_ack_call(self):
        routed = self._routed(commit_supported=False)
        result = routed.client.commit_events("c-1", 7, [])
        self.assertEqual(result["acked_count"], 0)
        self.assertEqual(routed.count("/v1/events/ack"), 0, "no ids -> no ack round trip")

    def test_supported_commit_endpoint_is_not_reprobed(self):
        routed = self._routed(commit_supported=True)
        for cursor in (1, 2, 3):
            result = routed.client.commit_events("c-1", cursor, ["e-1"])
            self.assertTrue(result["commit_endpoint_supported"])
        self.assertEqual(routed.count("/v1/events/commit"), 3, "a supported endpoint is used every time")
        self.assertIs(routed.client.event_commit_endpoint_supported, True)

    def test_restart_rediscovers_capability(self):
        routed = self._routed(commit_supported=False)
        routed.client.commit_events("c-1", 1, ["e-1"])
        fresh = CoreClient("http://127.0.0.1:8080")
        self.assertIsNone(fresh.event_commit_endpoint_supported, "a new process starts undiscovered")

    def test_contract_change_invalidates_capability(self):
        routed = self._routed(commit_supported=False)
        routed.client.commit_events("c-1", 1, ["e-1"])
        self.assertIs(routed.client.event_commit_endpoint_supported, False)
        routed.client.invalidate_contract_cache()
        self.assertIsNone(routed.client.event_commit_endpoint_supported)
        routed.client.commit_events("c-1", 2, ["e-2"])
        self.assertEqual(routed.count("/v1/events/commit"), 2, "re-probed once after the contract change")

    def test_transient_transport_error_does_not_drop_capability(self):
        routed = self._routed(commit_supported=False)
        routed.client.commit_events("c-1", 1, ["e-1"])
        self.assertIs(routed.client.event_commit_endpoint_supported, False)
        # A transport failure on an unrelated endpoint must not resurrect the probe.
        with patch.object(
            routed.client, "_request", side_effect=CoreApiError(0, "core_unavailable", "boom")
        ):
            with self.assertRaises(CoreApiError):
                routed.client.poll_events(after="0", limit=200)
        self.assertIs(routed.client.event_commit_endpoint_supported, False)
        routed.client.commit_events("c-1", 2, ["e-2"])
        self.assertEqual(routed.count("/v1/events/commit"), 1, "capability cache survived the transient error")

    def test_non_404_error_still_raises(self):
        routed = self._routed(commit_supported=False)

        def boom(method: str, path: str, **kwargs: Any) -> CoreResponse:
            if path == "/v1/events/commit":
                raise CoreApiError(500, "internal_error", "kaboom")
            return routed._route(method, path, **kwargs)

        with patch.object(routed.client, "_request", side_effect=boom):
            with self.assertRaises(CoreApiError) as ctx:
                routed.client.commit_events("c-1", 1, ["e-1"])
        self.assertEqual(ctx.exception.status, 500)
        self.assertIsNone(
            routed.client.event_commit_endpoint_supported, "a 500 is not evidence of a missing endpoint"
        )


class V5ServiceLevelTests(unittest.TestCase):
    """Both V5 fixes observed through the real catch-up batch path."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "agent.sqlite"
        self.services: list[AgentService] = []
        self.routed: list[RoutedCore] = []

    def tearDown(self):
        for service in self.services:
            try:
                service.shutdown()
            except Exception:
                pass
        for routed in self.routed:
            routed.stop()
        self.tempdir.cleanup()

    def _service(self, core: Any) -> AgentService:
        settings = AgentSettings(
            db_path=self.db_path,
            consumer_id="v5-regression",
            poll_interval_seconds=0.0,
            poll_batch_size=400,
            core_commit_batch_threshold=1,
            core_commit_interval_seconds=0.0,
        )
        service = AgentService(settings, core=core)
        self.services.append(service)
        return service

    def _routed(self, *, commit_supported: bool) -> RoutedCore:
        routed = RoutedCore(commit_supported=commit_supported)
        self.routed.append(routed)
        return routed

    def test_two_batches_share_one_identity_fetch(self):
        routed = self._routed(commit_supported=False)
        service = self._service(routed)
        first = service.process_events_once()
        second = service.process_events_once()
        self.assertTrue(first["ok"] and second["ok"])
        self.assertEqual(
            routed.count("/v1/accounts"), 1, "two catch-up batches inside the TTL must cost one accounts fetch"
        )
        self.assertEqual(service.monitor.identity_fetch_count, 1)

    def test_two_batches_probe_commit_once(self):
        routed = self._routed(commit_supported=False)
        service = self._service(routed)
        service.process_events_once()
        service.process_events_once()
        self.assertEqual(routed.count("/v1/events/commit"), 1, "the known-404 probe must not repeat per batch")
        self.assertGreaterEqual(routed.count("/v1/events/ack"), 1)


if __name__ == "__main__":
    unittest.main()

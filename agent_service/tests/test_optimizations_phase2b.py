from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from agent_service.core_client import CoreApiError, CoreClient, CoreResponse
from agent_service.monitor import IdentityBlocked, MonitorEngine
from agent_service.service import AgentService, AgentSettings
from agent_service.storage import AgentStorage


class TestPhase2BOptimizations(unittest.TestCase):
    def test_contract_caching(self):
        client = CoreClient("http://127.0.0.1:8080", contract_ttl=60.0)
        with patch.object(
            client, "_request", return_value=CoreResponse(200, {"contract_version": 1, "ok": True}, {})
        ) as mock_req:
            # 1. First call fetches from Core
            res1 = client.ensure_contract(1)
            self.assertEqual(res1["contract_version"], 1)
            self.assertEqual(mock_req.call_count, 1)

            # 2. Second call within TTL returns cached result (0 network calls)
            res2 = client.ensure_contract(1)
            self.assertEqual(res2["contract_version"], 1)
            self.assertEqual(mock_req.call_count, 1)

            # 3. Force bypasses cache
            res3 = client.ensure_contract(1, force=True)
            self.assertEqual(res3["contract_version"], 1)
            self.assertEqual(mock_req.call_count, 2)

    def test_contract_caching_fail_closed_on_mismatch(self):
        client = CoreClient("http://127.0.0.1:8080", contract_ttl=60.0)
        with patch.object(
            client, "_request", return_value=CoreResponse(200, {"contract_version": 999, "ok": True}, {})
        ):
            with self.assertRaises(CoreApiError) as ctx:
                client.ensure_contract(1)
            self.assertEqual(ctx.exception.code, "unsupported_contract")
            self.assertIsNone(client._cached_contract)

    def test_identity_view_caching(self):
        storage = MagicMock()
        client = MagicMock()
        client.list_accounts.return_value = [
            {"account_id": "acc-1", "identity_binding_state": "bound", "wechat_identity_uuid": "id-1"}
        ]
        engine = MonitorEngine(storage, client, MagicMock(), MagicMock(), identity_ttl=60.0)

        # 1. First call fetches
        v1 = engine.identity_view()
        self.assertEqual(len(v1), 1)
        self.assertEqual(client.list_accounts.call_count, 1)

        # 2. Second call cached
        v2 = engine.identity_view()
        self.assertEqual(len(v2), 1)
        self.assertEqual(client.list_accounts.call_count, 1)

        # 3. Invalidation triggers fresh fetch
        engine.invalidate_identity_cache()
        v3 = engine.identity_view()
        self.assertEqual(len(v3), 1)
        self.assertEqual(client.list_accounts.call_count, 2)

    def test_commit_events_fallback(self):
        client = CoreClient("http://127.0.0.1:8080")
        with patch.object(client, "_request") as mock_req:
            # Simulate 404 from older Core on /v1/events/commit
            def fake_request(method, path, **kwargs):
                if path == "/v1/events/commit":
                    raise CoreApiError(404, "not_found", "Endpoint not found")
                elif path == "/v1/events/ack":
                    return CoreResponse(200, {"consumer_id": "test", "acked_count": 2}, {})
                elif path == "/v1/events/checkpoint":
                    return CoreResponse(200, {"consumer_id": "test", "checkpoint": 100}, {})
                raise RuntimeError(f"Unexpected path: {path}")

            mock_req.side_effect = fake_request

            res = client.commit_events("test", 100, ["evt-1", "evt-2"])
            self.assertEqual(res["consumer_id"], "test")
            self.assertEqual(res["acked_count"], 2)
            self.assertEqual(res.get("mode"), "fallback_2phase")


if __name__ == "__main__":
    unittest.main()

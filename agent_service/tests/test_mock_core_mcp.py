from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from agent_service.app import create_server as create_agent_server
from agent_service.core_client import CoreClient
from agent_service.mcp import MCPServer
from agent_service.service import AgentService, AgentSettings
from agent_service.tests.helpers import FakeAI


PROJECT_ROOT = Path(__file__).resolve().parents[4]


def load_mock_core_module():
    path = PROJECT_ROOT / "stack" / "mock-core" / "app.py"
    spec = importlib.util.spec_from_file_location("wechat_hub_mock_core_for_agent_tests", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Mock Core: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MockCoreMcpIntegrationTests(unittest.TestCase):
    def setUp(self):
        mock_core = load_mock_core_module()
        self.core_state = mock_core.MockCoreState()
        self.core_server = mock_core.create_server("127.0.0.1", 0, self.core_state)
        self.core_thread = threading.Thread(target=self.core_server.serve_forever, daemon=True)
        self.core_thread.start()
        self.tempdir = tempfile.TemporaryDirectory()
        settings = AgentSettings(
            core_url=f"http://127.0.0.1:{self.core_server.server_port}",
            db_path=Path(self.tempdir.name) / "agent.sqlite",
            consumer_id="agent-test",
            poll_interval_seconds=1,
            poll_timeout_seconds=0,
            poll_batch_size=100,
            scheduler_interval_seconds=1,
            vector_dim=384,
        )
        self.service = AgentService(settings, core=CoreClient(settings.core_url), ai=FakeAI())

    def tearDown(self):
        self.core_server.shutdown()
        self.core_server.server_close()
        self.core_thread.join(timeout=2)
        self.tempdir.cleanup()

    def test_poll_ack_memory_and_duplicate_safety(self):
        self.service.storage.upsert_monitor(
            {
                "monitor_id": "alpha-note",
                "name": "Alpha hello",
                "account_id": "account-alpha",
                "contains_text": "Hello",
                "action": "record",
                "action_config": {"text": "{{message.text}}"},
            }
        )
        result = self.service.process_events_once()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["events"], 3)
        self.assertEqual(result["processed"], 3)
        self.assertEqual(result["indexed_messages"], 2)
        self.assertEqual(result["cursor"], "3")
        self.assertEqual(self.service.memory.count(), 2)
        self.assertEqual(self.core_state.acked["agent-test"], {"event-0001", "event-0002", "event-0003"})

        alpha = self.service.memory.search("Hello", account_id="account-alpha")
        beta = self.service.memory.search("Hello", account_id="account-beta")
        self.assertEqual(len(alpha["results"]), 1)
        self.assertEqual(beta["results"], [])
        self.assertEqual(len(self.service.storage.list_records()), 1)

        second = self.service.process_events_once()
        self.assertTrue(second["ok"])
        self.assertEqual(second["events"], 0)
        self.assertEqual(self.service.memory.count(), 2)
        self.assertEqual(len(self.service.storage.list_records()), 1)

    def test_mcp_initialize_tools_and_core_send(self):
        self.service.process_events_once()
        mcp = MCPServer(self.service)
        initialized = mcp.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "test"}}}
        )
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "wechat-agent")
        tools = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {item["name"] for item in tools["result"]["tools"]}
        self.assertIn("memory_search", names)
        self.assertIn("wechat_send_text", names)
        search = mcp.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "memory_search", "arguments": {"query": "Hello", "account_id": "account-alpha"}},
            }
        )
        self.assertFalse(search["result"]["isError"])
        self.assertEqual(len(search["result"]["structuredContent"]["results"]), 1)
        sent = mcp.handle(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "wechat_send_text",
                    "arguments": {
                        "account_id": "account-alpha",
                        "chat_id": "alpha-private-1",
                        "text": "Agent MCP hello",
                        "idempotency_key": "agent-test-send-1",
                    },
                },
            }
        )
        self.assertFalse(sent["result"]["isError"])
        self.assertEqual(len(self.core_state.sends), 1)

    def test_streamable_http_mcp_post_and_sse_get(self):
        agent_server = create_agent_server("127.0.0.1", 0, self.service)
        thread = threading.Thread(target=agent_server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{agent_server.server_port}"
        try:
            request = Request(
                base + "/mcp",
                data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertIn("tools", payload["result"])
            with urlopen(base + "/mcp", timeout=5) as response:
                body = response.read().decode("utf-8")
                self.assertEqual(response.headers.get_content_type(), "text/event-stream")
                self.assertIn("streamable-http", body)
        finally:
            agent_server.shutdown()
            agent_server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()


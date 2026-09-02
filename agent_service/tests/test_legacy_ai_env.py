from __future__ import annotations

import os
import unittest
from unittest import mock

from agent_service.legacy_ai import apply_llm_env


class LegacyAIEnvironmentTests(unittest.TestCase):
    def test_optional_environment_overrides_and_invalid_numeric_fallback(self):
        profile = {
            "base_url": "https://legacy.invalid/v1",
            "model": "legacy-model",
            "api_key": "legacy-key",
            "temperature": 0.4,
            "max_tokens": 512,
            "timeout_seconds": 30,
        }
        with mock.patch.dict(
            os.environ,
            {
                "WECHAT_AGENT_LLM_BASE_URL": "https://headless.example/v1",
                "WECHAT_AGENT_LLM_MODEL": "headless-model",
                "WECHAT_AGENT_LLM_API_KEY": "headless-key",
                "WECHAT_AGENT_LLM_TEMPERATURE": "0.25",
                "WECHAT_AGENT_LLM_MAX_TOKENS": "not-a-number",
                "WECHAT_AGENT_LLM_TIMEOUT_SECONDS": "45",
            },
            clear=False,
        ):
            configured = apply_llm_env(profile)

        self.assertEqual(configured["base_url"], "https://headless.example/v1")
        self.assertEqual(configured["model"], "headless-model")
        self.assertEqual(configured["api_key"], "headless-key")
        self.assertEqual(configured["temperature"], 0.25)
        self.assertEqual(configured["max_tokens"], 512)
        self.assertEqual(configured["timeout_seconds"], 45)


if __name__ == "__main__":
    unittest.main()

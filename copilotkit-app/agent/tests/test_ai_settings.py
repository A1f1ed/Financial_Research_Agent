import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai import AuthenticationError
from pydantic import ValidationError

from src import ai_settings, preferences, research_store
from src.model import compatible_model, create_chat_model


class AISettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.enterContext(patch.object(research_store, "DB", root / "test.sqlite3"))
        self.env_file = root / ".env"
        self.env_file.write_text("UNRELATED_SETTING=preserved\n", encoding="utf-8")
        self.enterContext(patch.object(preferences, "ENV_FILE", self.env_file))
        self.enterContext(patch.dict(os.environ, {}, clear=True))

    def test_migrate_qwen_settings_and_prefer_configured_environment_urls(self):
        preferences.write_setting("ai", preferences.AISettings(model="qwen-old", timeout=120))
        # Simulate the old schema, before it had a provider or base_url.
        with research_store.connect() as db:
            db.execute("UPDATE preferences SET body=? WHERE key='ai'", (json.dumps({"model": "qwen-old", "temperature": 0, "timeout": 120}),))
        os.environ.update(DASHSCOPE_BASE_URL="https://example.com/qwen", DEEPSEEK_BASE_URL="https://example.com/deepseek", ZHIPU_BASE_URL="https://example.com/glm")
        self.assertEqual(preferences.public_ai_settings()["model"], "qwen-old")
        for provider, suffix in [("dashscope", "qwen"), ("deepseek", "deepseek"), ("glm", "glm")]:
            self.assertEqual(preferences.public_ai_settings(provider)["base_url"], f"https://example.com/{suffix}")

    def test_profiles_keys_and_blank_key_preservation(self):
        for provider in preferences.PROVIDERS:
            profile = preferences.AISettings(provider=provider, model=f"{provider}-custom", api_key=f"fake-{provider}")
            result = preferences.save_ai_profile(profile)
            self.assertTrue(result["credential_configured"])
            self.assertNotIn("api_key", result)
            self.assertNotIn(f"fake-{provider}", json.dumps(preferences.read_setting(f"ai:{provider}")))
            self.assertNotIn(f"fake-{provider}", repr(profile))
        preferences.save_ai_profile(preferences.AISettings(provider="deepseek", model="deepseek-other", api_key=""))
        self.assertEqual(preferences.provider_key("deepseek"), "fake-deepseek")
        self.assertEqual(preferences.public_ai_settings()["provider"], "deepseek")
        self.assertEqual(preferences.public_ai_settings("glm")["model"], "glm-custom")
        self.assertIn("UNRELATED_SETTING=preserved", self.env_file.read_text())

    def test_provider_specific_factories_and_live_selection(self):
        for provider in preferences.PROVIDERS:
            profile = preferences.AISettings(provider=provider, model=preferences.PROVIDERS[provider]["model"], api_key=f"fake-{provider}")
            preferences.save_ai_profile(profile)
            model = create_chat_model("openai:other", enable_thinking=False)
            self.assertEqual(model.model_name, profile.model)
            self.assertEqual(model.openai_api_base, preferences.PROVIDERS[provider]["base_url"])
            self.assertEqual(model.openai_api_key.get_secret_value(), f"fake-{provider}")
            expected = {"enable_thinking": False} if provider == "dashscope" else None if provider == "glm" else {"thinking": {"type": "disabled"}}
            self.assertEqual(model.extra_body, expected)
            self.assertFalse(model.use_responses_api)

    def test_fresh_install_can_construct_agent_model_before_a_key_is_entered(self):
        self.assertFalse(preferences.public_ai_settings()["credential_configured"])
        model = create_chat_model("openai:qwen3.8-flash")
        self.assertEqual(model.openai_api_key.get_secret_value(), "not-configured")
        self.assertIsNone(preferences.read_setting("ai"))

    async def test_connection_uses_draft_without_saving_or_tools(self):
        invoke = AsyncMock(return_value=SimpleNamespace(text="你好！"))
        draft = preferences.AISettings(provider="glm", model="glm-custom", api_key="temporary-key", base_url="https://example.com/custom")
        with patch.object(ai_settings, "compatible_model", return_value=SimpleNamespace(ainvoke=invoke)) as factory:
            result = await ai_settings.test_connection(draft)
        self.assertTrue(result["ok"])
        self.assertEqual(result["reply"], "你好！")
        self.assertIsNone(preferences.read_setting("ai"))
        self.assertNotIn("temporary-key", self.env_file.read_text())
        self.assertEqual(factory.call_args.args[0]["base_url"], draft.base_url)
        self.assertEqual(factory.call_args.kwargs["api_key"], "temporary-key")
        self.assertEqual(factory.call_args.kwargs["max_retries"], 0)
        self.assertEqual(invoke.call_args.args[0][0]["role"], "user")
        self.assertIn("你好", invoke.call_args.args[0][0]["content"])

    async def test_failure_timeout_empty_and_missing_key_are_safe(self):
        draft = preferences.AISettings(provider="deepseek", model="deepseek-flash", api_key="private-test-key")
        authentication = AuthenticationError("private-test-key", response=httpx.Response(401, request=httpx.Request("POST", "https://example.com")), body=None)
        for failure, code in [(TimeoutError(), "timeout"), (authentication, "authentication"), (RuntimeError("private-test-key"), "unexpected")]:
            with self.subTest(code=code), patch.object(ai_settings, "compatible_model", return_value=SimpleNamespace(ainvoke=AsyncMock(side_effect=failure))):
                result = await ai_settings.test_connection(draft)
                self.assertEqual(result["code"], code)
                self.assertNotIn("private-test-key", json.dumps(result))
        with patch.object(ai_settings, "compatible_model", return_value=SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(text="")))):
            self.assertEqual((await ai_settings.test_connection(draft))["code"], "empty_reply")
        draft.api_key = None
        with patch.object(ai_settings, "compatible_model") as factory:
            self.assertEqual((await ai_settings.test_connection(draft))["code"], "missing_key")
            factory.assert_not_called()

    def test_http_save_redacts_and_rejects_invalid_input(self):
        app = FastAPI()
        app.include_router(ai_settings.router)
        client = TestClient(app)
        response = client.put("/research/settings/ai", json={"provider": "glm", "model": "glm-5.3", "api_key": "fake-secret"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("fake-secret", response.text)
        self.assertNotIn("api_key", response.json())
        for url in ["http://example.com", "https://key:secret@example.com", "https://example.com?key=secret", "https://example.com/chat/completions"]:
            with self.subTest(url=url), self.assertRaises(ValidationError):
                preferences.AISettings(model="glm-5.3", base_url=url)
        self.assertEqual(client.put("/research/settings/ai", json={"provider": "unknown", "model": "test"}).status_code, 422)

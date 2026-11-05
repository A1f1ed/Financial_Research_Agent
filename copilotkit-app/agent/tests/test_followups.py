import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src import followups, research_store


class FollowupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.enterContext(patch.object(research_store, "DB", Path(directory.name) / "test.sqlite3"))
        self.turn = followups.Turn(thread_id="report-a", report_id="report-a", message_id="reply",
                                   question="What supports the conclusion?", answer="Evidence [S1] supports it.")
        research_store.save_report({"id": "report-a", "evidence": {"sources": [{"id": "S1"}]}})

    async def test_concurrent_generation_is_scoped_and_replay_is_read_only(self):
        invoke = AsyncMock(return_value=SimpleNamespace(text='["What does [S1] show?", "What does [S2] show?", "What does [S1] show?"]'))
        with patch.object(followups, "create_chat_model", return_value=SimpleNamespace(ainvoke=invoke)):
            left, right = await asyncio.gather(*(followups.generate_followups(self.turn) for _ in range(2)))
            self.assertEqual(left, right)
            self.assertEqual(left, {"questions": ["What does [S1] show?"]})
            self.assertEqual(followups.read_followups("report-a", "reply", "report-a"), left)
            self.assertEqual(followups.read_followups("report-a", "reply"), {"questions": []})
            invoke.assert_awaited_once()

    async def test_failure_returns_no_suggestions(self):
        model = SimpleNamespace(ainvoke=AsyncMock(side_effect=TimeoutError))
        with patch.object(followups, "create_chat_model", return_value=model):
            self.assertEqual(await followups.generate_followups(self.turn), {"questions": []})
            self.assertIsNone(followups.saved(("report-a", "reply", "report-a")))

import asyncio
from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from src.research_data import eligible, local_date, indicators, relative_returns
from src.research_models import ResearchConfig, normalize_symbol
from src.research_workflow import validate_citations, run_financial_research


class DataContractTests(unittest.TestCase):
    def test_hong_kong_bar_uses_exchange_date(self):
        self.assertEqual(local_date("2026-10-29T16:00:00Z"), date(2026, 10, 30))
        self.assertFalse(eligible({"time": "2026-10-31T16:00:00Z"}, date(2026, 10, 31)))
        self.assertTrue(eligible({"publish_at": "2026-10-31T10:30:00Z"}, date(2026, 10, 31)))

    def test_period_end_and_undated_data_are_not_publication_proof(self):
        self.assertFalse(eligible({"fp_end": "1735574400"}, date(2026, 10, 31)))
        self.assertFalse(eligible({"published_at": "not-a-date"}, date(2026, 10, 31)))
        self.assertFalse(eligible({"published_at": "2026-11-01T01:00:00Z"}, date(2026, 10, 31)))

    def test_symbols_cannot_inject_commands(self):
        self.assertEqual(normalize_symbol("01211.hk"), "1211.HK")
        for value in ("1211.HK;whoami", "--help", "../.env", "0.HK"):
            with self.assertRaises(ValueError):
                normalize_symbol(value)
        with self.assertRaises(ValueError):
            ResearchConfig(symbol="AAPL.US", market="HK")

    def test_flat_prices_rsi_and_minimum_samples(self):
        bars = [{"date": f"2026-01-{i+1:02}", "close": 100} for i in range(25)]
        result = indicators(bars)
        self.assertEqual(result["rsi14"], 50)
        self.assertEqual(result["return_20d"], 0)
        self.assertIsNone(result["ma60"])
        self.assertEqual(result["max_drawdown_pct"], 0)

    def test_comparisons_align_dates_and_require_enough_data(self):
        result = relative_returns([{"date": "2026-10-29", "close": 10}], [{"date": "2026-10-30", "close": 11}])
        self.assertEqual(result["aligned_sessions"], 0)
        self.assertIsNone(result["excess_20d_pct"])

    def test_hallucinated_references_are_removed(self):
        value = validate_citations({"summary": "结论[S999]", "stance": "偏多", "source_ids": ["S999"]}, {"S1"})
        self.assertEqual(value["stance"], "证据不足")
        self.assertEqual(value["source_ids"], [])
        self.assertNotIn("[S999]", value["summary"])


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_analysts_and_switches_control_execution(self):
        configuration = ResearchConfig(analysts=["technical", "sentiment"], include_sentiment=False,
                                       include_risk=False, depth="quick").model_dump(mode="json")
        runtime = SimpleNamespace(state={"research_config": configuration}, config={}, tool_call_id="test")
        evidence = {"sources": [{"id": "S1"}], "gaps": [], "excluded_after_cutoff_or_undated": 0}
        finding = {"summary": "测试", "stance": "中性", "findings": [], "risks": [], "missing": [], "source_ids": ["S1"]}
        analyst_mock = AsyncMock(return_value=finding)
        with patch("src.research_workflow.retrieve_market_evidence", SimpleNamespace(ainvoke=AsyncMock(return_value=evidence))), \
             patch("src.research_workflow.analyst_research", SimpleNamespace(ainvoke=analyst_mock)), \
             patch("src.research_workflow.synthesize_research", SimpleNamespace(ainvoke=AsyncMock(return_value={"summary": "完成"}))), \
             patch("src.research_workflow.copilotkit_emit_state", AsyncMock()), patch("src.research_workflow.save_report"):
            command = await run_financial_research.coroutine(runtime=runtime)
            report = command.update["research"]
            self.assertEqual(list(report["findings"]), ["technical"])
            self.assertEqual([s["id"] for s in report["stages"]], ["data", "technical", "synthesis"])
            self.assertEqual(analyst_mock.await_count, 1)
            self.assertEqual(report["evidence_coverage"], 100)

    async def test_cancellation_saves_partial_report(self):
        runtime = SimpleNamespace(state={"research_config": ResearchConfig().model_dump(mode="json")}, config={}, tool_call_id="test")
        with patch("src.research_workflow.retrieve_market_evidence", SimpleNamespace(ainvoke=AsyncMock(side_effect=asyncio.CancelledError))), \
             patch("src.research_workflow.copilotkit_emit_state", AsyncMock()), patch("src.research_workflow.save_report") as save:
            with self.assertRaises(asyncio.CancelledError):
                await run_financial_research.coroutine(runtime=runtime)
            self.assertEqual(save.call_args[0][0]["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()

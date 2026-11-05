from datetime import date, datetime, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from src.research_models import ResearchConfig
from src.scheduled_briefs import BriefOptions, completed_market_sessions, execute_brief, mainland_sessions
from src.workbench import Schedule


class ScheduledBriefTests(IsolatedAsyncioTestCase):
    def test_price_plan_can_track_both_mainland_exchanges(self):
        config = ResearchConfig(symbol="510300.SH", market="SH", as_of=date(2026, 11, 4))
        plan = {"name": "沪深异动", "config": config, "workflow": "watch", "repeat": "daily", "time": "18:00"}
        schedule = Schedule(**plan, symbols=["510300.SH", "159915.SZ"])
        self.assertEqual(schedule.symbols, ["510300.SH", "159915.SZ"])
        with self.assertRaisesRegex(ValueError, "标的市场必须与计划市场一致"):
            Schedule(**plan, symbols=["510300.SH", "2800.HK"])

    async def test_watch_matches_reference_sessions_and_preserves_fallback_source(self):
        sessions = ["2026-11-03", "2026-11-04"]
        config = ResearchConfig(symbol="510300.SH", market="SH", as_of=date(2026, 11, 4))
        source = "https://web.ifzq.gtimg.cn/example"

        async def candles(symbol, cutoff_config, *, lookback_days, required_sessions):
            self.assertEqual(cutoff_config.as_of, date(2026, 11, 4))
            self.assertEqual(required_sessions, sessions)
            return {"provider": "腾讯财经", "source": source, "bars": [
                {"date": day, "volume": 100 if index == 0 or symbol == "510300.SH" else 0, "close": 10 + index}
                for index, day in enumerate(sessions)
            ]}

        with (
            patch("src.scheduled_briefs.datetime", wraps=datetime) as clock,
            patch("src.scheduled_briefs.mainland_sessions", AsyncMock(return_value=(sessions, "Longbridge", "https://example.com"))),
            patch("src.scheduled_briefs.candles", candles),
            patch("src.scheduled_briefs.save_report"),
        ):
            clock.now.return_value = datetime(2026, 11, 4, 10, tzinfo=timezone.utc)
            result = await execute_brief(config, BriefOptions(workflow="watch", symbols=["510300.SH", "159915.SZ"]), "test")

        self.assertEqual(result["status"], "partial")
        calendar, prices = result["evidence"]["sources"]
        self.assertEqual(calendar["kind"], "calendar")
        self.assertEqual((prices["provider"], prices["url"], prices["published_at"]), ("腾讯财经", source, sessions[-1]))
        self.assertIn("159915.SZ", result["evidence"]["gaps"][0])
        self.assertIn("1 个标的的完整日线", result["assessment"]["summary"])

    async def test_calendar_uses_reference_only_when_primary_unavailable(self):
        sessions = ["2026-10-29", "2026-10-30"]
        alternate = AsyncMock(return_value=([
            {"date": day, "volume": 100} for day in sessions
        ], "https://web.ifzq.gtimg.cn/example"))
        with (
            patch("src.research_data.cli", AsyncMock(return_value={"trading_days": sessions, "half_trading_days": []})) as cli,
            patch("src.scheduled_briefs.tencent_candles", alternate),
        ):
            days, provider, _ = await mainland_sessions(date(2026, 10, 31), 2)
            self.assertEqual((days, provider), (sessions, "Longbridge"))
            alternate.assert_not_awaited()
            cli.side_effect = RuntimeError("unavailable")
            days, provider, _ = await mainland_sessions(date(2026, 10, 31), 2)
            self.assertEqual((days, provider), (sessions, "腾讯财经"))

    async def test_us_half_day_close_requires_buffer_before_including_today(self):
        calendar = {date(2026, 11, 25): False, date(2026, 11, 27): True}
        with patch("src.scheduled_briefs.exchange_calendar", AsyncMock(return_value=calendar)):
            before = await completed_market_sessions("US", date(2026, 11, 27),
                                                    datetime(2026, 11, 27, 18, 14, tzinfo=timezone.utc), 1)
            after = await completed_market_sessions("US", date(2026, 11, 27),
                                                   datetime(2026, 11, 27, 18, 15, tzinfo=timezone.utc), 2)
        self.assertEqual(before[0], ["2026-11-25"])
        self.assertEqual(after[0], ["2026-11-25", "2026-11-27"])

    async def test_us_after_close_brief_aligns_today_and_marks_missing_candles(self):
        config = ResearchConfig(symbol="SPY.US", market="US", as_of=date(2025, 11, 28))
        sessions = ["2025-11-26", "2025-11-28"]

        async def candles(symbol, scoped, *, lookback_days, required_sessions):
            self.assertEqual((scoped.as_of, required_sessions), (date(2025, 11, 28), sessions))
            return {"provider": "Longbridge", "source": "https://longbridge.com/quote/" + symbol,
                    "bars": [{"date": day, "volume": 100 if symbol == "SPY.US" else 0, "close": 10 + index}
                             for index, day in enumerate(sessions)]}

        with (
            patch("src.scheduled_briefs.datetime", wraps=datetime) as clock,
            patch("src.scheduled_briefs.exchange_calendar", AsyncMock(return_value={
                date(2025, 11, 26): False, date(2025, 11, 28): True,
            })),
            patch("src.scheduled_briefs.candles", candles),
            patch("src.scheduled_briefs.save_report"),
        ):
            clock.now.return_value = datetime(2025, 11, 28, 18, 30, tzinfo=timezone.utc)
            result = await execute_brief(config, BriefOptions(workflow="watch", symbols=["SPY.US", "QQQ.US"]), "test")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["evidence"]["sources"][1]["published_at"], sessions[-1])
        self.assertIn("2025-11-28", result["evidence"]["sources"][1]["content"])
        self.assertIn("QQQ.US", result["evidence"]["gaps"][0])

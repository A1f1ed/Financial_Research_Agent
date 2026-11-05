from datetime import date, datetime
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from src.market_review import ReviewRequest, SHANGHAI, completed_cutoff, market_review
from src.research_data import candles, tencent_bars
from src.research_models import ResearchConfig


class MarketReviewTests(IsolatedAsyncioTestCase):
    def test_today_before_close_uses_prior_day(self):
        day = date(2026, 10, 30)
        self.assertEqual(completed_cutoff(day, datetime(2026, 10, 30, 14, 59, tzinfo=SHANGHAI)), date(2026, 10, 29))
        self.assertEqual(completed_cutoff(day, datetime(2026, 10, 30, 15, 30, tzinfo=SHANGHAI)), day)

    async def test_compare_same_sessions_without_forward_filling_missing_samples(self):
        request = ReviewRequest(as_of=date(2026, 10, 31), benchmark="510300.SH",
                                symbols=["510500.SH", "510500.sh", "159915.SZ"])

        async def candles(symbol, config, **kwargs):
            prices = {"510300.SH": [10, 11], "510500.SH": [10, 12], "159915.SZ": [10]}[symbol]
            bars = [{"date": f"2026-10-{29 + index}", "close": value, "volume": 100}
                    for index, value in enumerate(prices)]
            return {"bars": bars, "note": None, "provider": "Longbridge", "source": f"https://longbridge.com/quote/{symbol}"}

        with patch("src.market_review.candles", candles):
            result = await market_review(request)

        self.assertEqual(result["session"], "2026-10-30")
        self.assertEqual(result["requested_count"], 2)
        self.assertEqual(result["symbols"], ["510500.SH", "159915.SZ"])
        self.assertEqual([row["symbol"] for row in result["sample"]], ["510500.SH"])
        self.assertEqual(result["sample"][0]["relative_pct"], 10)
        self.assertIsNone(result["sample"][0]["volume_ratio"])
        self.assertEqual(result["gaps"][0]["symbol"], "159915.SZ")

    def test_tencent_preserves_raw_prices_and_normalizes_board_volume(self):
        day = date(2026, 10, 30)
        row = ["2026-10-30", "10", "11", "12", "9", "120"]
        for code, expected_volume in (("510300", 12000), ("688981", 120)):
            payload = {"code": 0, "data": {f"sh{code}": {"day": [row]}}}
            [bar] = tencent_bars(payload, f"{code}.SH", day, day)
            self.assertEqual((bar["close"], bar["volume"]), (11, expected_volume))
            with self.assertRaises(ValueError):
                tencent_bars(payload, f"{code}.SH", date(2026, 10, 29), date(2026, 10, 29))

    async def test_longbridge_remains_primary_and_fallback_keeps_actual_provenance(self):
        config = ResearchConfig(symbol="510300.SH", market="SH", as_of=date(2026, 10, 30))
        alternate = [{"date": "2026-10-29"}, {"date": "2026-10-30"}]
        backup = AsyncMock(return_value=(alternate, "https://web.ifzq.gtimg.cn/source"))
        with (
            patch("src.research_data.cli", AsyncMock(side_effect=RuntimeError("权限不足"))),
            patch("src.research_data.tencent_candles", backup),
        ):
            result = await candles(config.symbol, config)
        self.assertEqual((result["bars"], result["provider"], result["source"]),
                         (alternate, "腾讯财经", "https://web.ifzq.gtimg.cn/source"))
        backup.assert_awaited_once()

        raw = [{"time": day, "open": 10, "close": 11, "high": 12, "low": 9, "volume": 100}
               for day in ("2026-10-29", "2026-10-30")]
        backup.reset_mock()
        with (
            patch("src.research_data.cli", AsyncMock(return_value=raw)),
            patch("src.research_data.tencent_candles", backup),
        ):
            result = await candles(config.symbol, config)
        self.assertEqual(result["provider"], "Longbridge")
        backup.assert_not_awaited()

    async def test_requested_sessions_trigger_fallback_even_with_many_primary_bars(self):
        config = ResearchConfig(symbol="510300.SH", market="SH", as_of=date(2026, 10, 30))
        primary = [{"time": f"2026-10-{day}", "open": 10, "close": 11, "high": 12, "low": 9, "volume": 100}
                   for day in range(19, 30)]
        sessions = ["2026-10-29", "2026-10-30"]
        alternate = [{"date": day, "volume": 100} for day in sessions]
        with (
            patch("src.research_data.cli", AsyncMock(return_value=primary)),
            patch("src.research_data.tencent_candles", AsyncMock(return_value=(alternate, "https://web.ifzq.gtimg.cn/example"))),
        ):
            result = await candles(config.symbol, config, required_sessions=sessions)
        self.assertEqual((result["bars"], result["provider"]), (alternate, "腾讯财经"))

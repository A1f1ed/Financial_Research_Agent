from datetime import date
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from src.market_sentiment import corroborated, follow_through_summary, market_industry_history, market_sentiment, parse_pool, read_pool


class MarketSentimentTests(IsolatedAsyncioTestCase):
    session = date(2026, 11, 3)
    row = {"c": "002086", "m": 0, "p": 11000, "zdp": 10, "lbc": 4, "hybk": "测试行业"}

    def test_complete_pool_and_independent_session_required(self):
        with self.assertRaises(ValueError):
            parse_pool({"rc": 0, "data": {"tc": 2, "pool": [self.row]}})
        result = parse_pool({"rc": 0, "data": {"tc": 1, "pool": [self.row]}})
        [sample] = result["rows"]
        bars = [{"date": "2026-11-02", "volume": 100, "close": 10},
                {"date": "2026-11-03", "volume": 100, "close": 11}]
        self.assertTrue(corroborated(sample, bars, self.session))
        self.assertFalse(corroborated(sample, bars, date(2026, 11, 4)))
        self.assertFalse(corroborated({**sample, "change": 20}, bars, self.session))

    async def test_stale_empty_pool_is_unknown(self):
        with patch("src.market_sentiment.fetch_eastmoney", AsyncMock(return_value={"rows": [], "provider_date": "20261104"})):
            pool = await read_pool("broken", self.session)
        self.assertIsNone(pool["count"])

    async def test_overlapping_pool_blocks_break_rate(self):
        row = {"code": "002086", "symbol": "002086.SZ", "days": 4, "industry": "测试行业"}

        async def mocked_pool(kind, _):
            rows = [] if kind == "down" else [row]
            return {"label": kind, "count": len(rows), "sample": [], "rows": rows, "source": "https://example.com"}

        with patch("src.market_sentiment.read_pool", mocked_pool):
            result = await market_sentiment(self.session)
        self.assertIsNone(result["break_rate"])
        self.assertEqual(result["ladder"], [{"days": 4, "count": 1}])

    async def test_industry_history_keeps_missing_days_and_unclassified_rows_distinct(self):
        sessions = ["2026-10-30", "2026-11-02", "2026-11-03"]
        bars = [{"date": day, "volume": 100} for day in sessions]
        [member] = parse_pool({"rc": 0, "data": {"tc": 1, "pool": [self.row]}})["rows"]
        pools = AsyncMock(side_effect=[
            {"count": None, "rows": [], "sample": [], "source": "first"},
            {"count": 1, "rows": [{**member, "industry": ""}], "sample": [], "source": "second"},
            {"count": 1, "rows": [member], "sample": [], "source": "third"},
        ])
        with patch("src.market_sentiment.tencent_candles", AsyncMock(return_value=(bars, "calendar"))), \
             patch("src.market_sentiment.read_pool", pools):
            result = await market_industry_history(self.session)
        self.assertEqual([day["session"].isoformat() for day in result["days"]], sessions)
        self.assertEqual([(day["classified"], day["total"]) for day in result["days"]], [(0, None), (0, 1), (1, 1)])
        [industry] = result["industries"]
        self.assertEqual(industry["members"][:2], [None, []])
        self.assertEqual(industry["members"][2][0]["symbol"], "002086.SZ")

    def test_follow_through_uses_prior_cohort_and_separates_missing_data(self):
        first = {"code": "002086", "market_id": 0, "days": 1, "change": 10.0}
        second = {"code": "601123", "market_id": 1, "days": 2, "change": 10.0}
        prior = {"count": 2, "rows": [first, second]}
        observed = {"count": 2, "rows": [{**first, "change": -2.0}, {**second, "market_id": 0, "change": 50.0}]}
        current = {"count": 1, "rows": [second]}
        result = follow_through_summary(prior, observed, current)
        self.assertEqual((result["observed_count"], result["median"], result["down"]), (1, -2, 1))
        self.assertEqual((result["resealed"], result["reseal_rate"]), (1, 50))
        self.assertEqual(result["groups"][1]["observed"], 0)
        missing = {"count": None, "rows": []}
        self.assertIsNone(follow_through_summary(prior, observed, missing)["reseal_rate"])
        self.assertIsNone(follow_through_summary(missing, observed, current)["observed_count"])

from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from fastapi import HTTPException

from src import research_store
from src.market_review import SHANGHAI
from src.review_checks import CheckRequest, create_check, delete_check, list_checks, run_check, run_due_checks, verify_check


class ReviewCheckTests(IsolatedAsyncioTestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.enterContext(patch.object(research_store, "DB", Path(directory.name) / "test.sqlite3"))

    def test_report_origin_uses_persisted_condition_and_latest_valid_bar(self):
        report_id = str(uuid4())
        research_store.save_report({"id": report_id, "symbol": "510300.SH", "status": "complete", "as_of": "2026-10-31",
            "assessment": {"invalidation_conditions": ["复核基准下行 [S1]", "观察财务变动"]},
            "evidence": {"bars": [{"date": "2026-10-29", "volume": 100}, {"date": "2026-10-30", "volume": 100},
                                  {"date": "2026-10-31", "volume": 0}, {"date": "2026-11-02", "volume": 100}]}})
        payload = {"symbol": "510300.SH", "benchmark": "510300.SH", "baseline": "2026-10-30",
                   "metric": "day_pct", "direction": "lte", "threshold": -2,
                   "report_origin": {"report_id": report_id, "condition_index": 0, "condition": "tampered"}}
        entry = create_check(CheckRequest.model_validate(payload))
        self.assertEqual(entry["report_origin"]["condition"], "复核基准下行 [S1]")
        with self.assertRaises(HTTPException) as mismatch:
            create_check(CheckRequest.model_validate({**payload, "baseline": "2026-10-29"}))
        self.assertEqual(mismatch.exception.status_code, 422)
        research_store.archive_report(report_id)
        with self.assertRaises(HTTPException) as archived:
            create_check(CheckRequest.model_validate(payload))
        self.assertEqual(archived.exception.status_code, 404)
        self.assertEqual(list_checks()["checks"], [entry])

    async def test_next_benchmark_session_is_fixed_and_missing_sample_stays_pending(self):
        entry = create_check(CheckRequest(symbol="159915.SZ", benchmark="510300.SH", baseline="2026-10-30",
                                          metric="relative_pct", direction="gte", threshold=0.5))
        key = UUID(entry["id"])
        missing = {"159915.SZ"}

        async def candles(symbol, config, *, required_sessions, **kwargs):
            self.assertEqual(config.as_of, date(2026, 11, 2))
            self.assertEqual(required_sessions, ("2026-10-30", "2026-11-02"))
            prices = [100, 101, 103] if symbol == "510300.SH" else [100, 102, 95]
            bars = [{"date": day, "close": price, "volume": 100} for day, price in
                    zip(("2026-10-30", "2026-11-02", "2026-11-03"), prices)
                    if not (symbol in missing and day == "2026-11-02")]
            return {"bars": bars, "source": f"https://longbridge.com/quote/{symbol}", "provider": "Longbridge"}

        with (
            patch("src.review_checks.candles", candles),
            patch("src.review_checks.exchange_sessions", AsyncMock(return_value=[date(2026, 10, 30), date(2026, 11, 2)])),
        ):
            pending = await verify_check(key)
            self.assertIsNone(pending["result"])
            self.assertIn("2026-11-02", pending["message"])
            missing = {"510300.SH"}
            pending = await verify_check(key)
            self.assertIsNone(pending["result"])
            self.assertIn("基准在基线或目标日 2026-11-02 缺少有效成交日线", pending["message"])
            missing = set()
            completed = await verify_check(key)
        self.assertEqual(completed["result"]["session"], "2026-11-02")
        self.assertEqual(completed["result"]["value"], 1)
        self.assertTrue(completed["result"]["met"])
        self.assertTrue(completed["result"]["retrospective"])
        self.assertEqual(completed["result"]["trigger"], "manual")
        self.assertEqual(await verify_check(key), completed)
        self.assertEqual(list_checks()["checks"], [completed])
        delete_check(key)
        self.assertEqual(list_checks()["checks"], [])

    async def test_auto_worker_waits_for_close_then_settles_once(self):
        entry = create_check(CheckRequest(symbol="510300.SH", benchmark="510300.SH", baseline="2026-10-30",
                                          metric="day_pct", direction="gte", threshold=1))
        before = datetime(2026, 11, 2, 14, 30, tzinfo=SHANGHAI)
        close = before + timedelta(minutes=45)
        bars = [{"date": "2026-10-30", "close": 100, "volume": 100},
                {"date": "2026-11-02", "close": 102, "volume": 100}]
        with (
            patch("src.review_checks.candles", AsyncMock(return_value={"bars": bars, "source": "https://example.com", "provider": "Longbridge"})) as candles,
            patch("src.review_checks.exchange_sessions", AsyncMock(return_value=[date(2026, 10, 30), date(2026, 11, 2)])) as calendar,
        ):
            waiting = await run_check(entry["id"], before, "manual")
            self.assertEqual(waiting["target_session"], "2026-11-02")
            self.assertEqual(waiting["next_attempt_at"], close.isoformat())
            await run_due_checks(before)
            candles.assert_not_awaited()
            calendar.assert_awaited_once()
            await run_due_checks(close)
            await run_due_checks(close)
            candles.assert_awaited_once()
        [check] = list_checks()["checks"]
        self.assertEqual(check["result"]["trigger"], "auto")
        self.assertIsNone(check["next_attempt_at"])

    async def test_calendar_outage_remains_pending_and_blocks_price_inference(self):
        entry = create_check(CheckRequest(symbol="510300.SH", benchmark="510300.SH", baseline="2026-10-30",
                                          metric="day_pct", direction="gte", threshold=1))
        now = datetime(2026, 11, 3, 16, 0, tzinfo=SHANGHAI)
        with (
            patch("src.review_checks.exchange_sessions", AsyncMock(side_effect=TimeoutError)),
            patch("src.review_checks.candles", AsyncMock()) as candles,
        ):
            pending = await run_check(entry["id"], now, "auto")
        candles.assert_not_awaited()
        self.assertEqual(pending["next_attempt_at"], (now + timedelta(minutes=15)).isoformat())
        self.assertIsNone(pending["result"])
        self.assertEqual(list_checks()["checks"], [pending])

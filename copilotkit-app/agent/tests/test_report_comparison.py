from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from src import research_store
from src.report_comparison import ComparisonRequest, aligned_prices, compare_reports


def report(symbol, as_of="2024-10-30", closes=(10, 11, 12)):
    return {
        "id": str(uuid4()), "symbol": symbol, "as_of": as_of, "status": "complete",
        "created_at": "2024-10-30T15:20:00+08:00", "config": {"analysts": ["technical"]},
        "evidence": {"bars": [{"date": f"2024-10-{28+index}", "close": close, "volume": 100}
                              for index, close in enumerate(closes)], "gaps": [], "sources": [
            {"id": "S1", "kind": "prices", "symbol": symbol},
            {"id": "S2", "kind": "prices", "symbol": "510300.SH"},
        ]},
    }


class ReportComparisonTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        database = patch.object(research_store, "DB", Path(directory.name) / "reports.sqlite3")
        database.start()
        self.addCleanup(database.stop)

    def compare(self, *reports, points=20):
        for value in reports:
            research_store.save_report(value)
        return compare_reports(ComparisonRequest(report_ids=[value["id"] for value in reports], points=points))

    def test_same_day_mainland_comparison_uses_common_baseline_and_own_sources(self):
        left, right = report("600519.SH"), report("000402.SZ", closes=(100, 80, 110))
        result = self.compare(left, right)
        self.assertEqual(result["mode"], "cross_section")
        self.assertEqual([value["symbol"] for value in result["reports"]], ["000402.SZ", "600519.SH"])
        prices = result["prices"]
        self.assertEqual((prices["used_sessions"], prices["start_session"], prices["end_session"]),
                         (3, "2024-10-28", "2024-10-30"))
        self.assertEqual(prices["series"][0], {"date": "2024-10-28", "price_0": 100, "price_1": 100})
        self.assertEqual(prices["series"][-1]["price_0"], 110)
        self.assertEqual([stat["change_pct"] for stat in prices["stats"]], [10, 20])
        self.assertTrue(all(stat["source_ids"] == ["S1"] for stat in prices["stats"]))
        self.assertEqual(research_store.get_report(left["id"]), left)

    def test_no_fill_for_missing_or_suspended_dates_and_no_post_cutoff_prices(self):
        left, right = report("600519.SH"), report("000402.SZ", closes=(100, 80, 110))
        right["evidence"]["bars"][1]["volume"] = 0
        right["evidence"]["bars"].extend([
            {"date": "2024-10-31", "close": 10000, "volume": 100},
            {"date": "2024-10-27", "close": float("nan"), "volume": 100},
            {"date": "bad", "close": 1, "volume": 100},
        ])
        original = deepcopy(left)
        prices = aligned_prices([left, right], 5)
        self.assertEqual([row["date"] for row in prices["series"]], ["2024-10-28", "2024-10-30"])
        self.assertEqual(prices["stats"][1]["change_pct"], 10)
        self.assertEqual(left, original)
        self.assertTrue(any("排除 4" in gap for gap in prices["gaps"]))

    def test_insufficient_shared_data_has_no_return_or_curve(self):
        left, right = report("600519.SH"), report("000402.SZ")
        right["evidence"]["bars"] = right["evidence"]["bars"][-1:]
        prices = aligned_prices([left, right], 20)
        self.assertEqual(prices["series"], [])
        self.assertIsNone(prices["start_session"])
        self.assertTrue(all(stat["change_pct"] is None for stat in prices["stats"]))
        self.assertTrue(any("2024-10-30" == stat["last_session"] for stat in prices["stats"]))

    def test_window_uses_latest_shared_dates_before_rebasing(self):
        left, right = report("600519.SH"), report("000402.SZ")
        dates = ["2024-10-21", "2024-10-22", "2024-10-23", "2024-10-24", "2024-10-25", "2024-10-28", "2024-10-29"]
        for value, multiplier in [(left, 1), (right, 10)]:
            value["evidence"]["bars"] = [{"date": session, "close": (index + 1) * multiplier, "volume": 100}
                                         for index, session in enumerate(dates)]
        prices = aligned_prices([left, right], 5)
        self.assertEqual((prices["common_sessions"], prices["used_sessions"]), (7, 5))
        self.assertEqual((prices["start_session"], prices["end_session"]), ("2024-10-23", "2024-10-29"))
        self.assertEqual(prices["series"][0]["price_0"], 100)
        self.assertEqual(prices["stats"][0]["change_pct"], 133.3333)
        self.assertEqual(prices["stats"][0]["change_pct"], prices["stats"][1]["change_pct"])

    def test_duplicate_dates_are_excluded_instead_of_arbitrary_last_price(self):
        left, right = report("600519.SH"), report("000402.SZ")
        right["evidence"]["bars"].append({"date": "2024-10-30", "close": 900, "volume": 100})
        prices = aligned_prices([left, right], 5)
        self.assertEqual(prices["end_session"], "2024-10-29")
        self.assertEqual(prices["stats"][1]["change_pct"], 10)
        self.assertTrue(any("最新有效行情为 2024-10-30" in gap for gap in prices["gaps"]))

    def test_missing_volume_or_price_source_is_explicit(self):
        left, right = report("600519.SH"), report("000402.SZ")
        right["evidence"]["sources"] = []
        for bar in right["evidence"]["bars"]:
            del bar["volume"]
        prices = aligned_prices([left, right], 5)
        self.assertEqual(prices["used_sessions"], 0)
        self.assertEqual(prices["stats"][1]["source_ids"], [])
        self.assertTrue(any("来源编号" in gap for gap in prices["gaps"]))

    def test_different_dates_or_markets_are_rejected_for_cross_section(self):
        for right in [report("000402.SZ", as_of="2024-10-29"), report("1211.HK")]:
            with self.subTest(right=right["symbol"], as_of=right["as_of"]):
                with self.assertRaises(HTTPException) as error:
                    self.compare(report("600519.SH"), right)
                self.assertEqual(error.exception.status_code, 422)

    def test_historical_comparison_still_orders_records_without_new_price_window(self):
        older, newer = report("1211.HK", as_of="2024-10-28"), report("1211.HK")
        result = self.compare(newer, older)
        self.assertEqual(result["mode"], "history")
        self.assertIsNone(result["prices"])
        self.assertEqual(result["reports"][0]["id"], older["id"])

    def test_archived_failed_brief_and_missing_evidence_are_not_comparable(self):
        left, right = report("600519.SH"), report("000402.SZ")
        self.compare(left, right)
        research_store.archive_report(left["id"])
        with self.assertRaises(HTTPException) as error:
            compare_reports(ComparisonRequest(report_ids=[left["id"], right["id"]]))
        self.assertEqual(error.exception.status_code, 404)
        for field, value in [("status", "failed"), ("workflow", "morning"), ("evidence", {})]:
            invalid = report("600519.SH")
            invalid[field] = value
            with self.subTest(field=field), self.assertRaises(HTTPException) as error:
                self.compare(invalid, right)
            self.assertEqual(error.exception.status_code, 422)

    def test_request_requires_distinct_reports_and_bounded_window(self):
        value = report("600519.SH")
        with self.assertRaises(HTTPException):
            self.compare(value, value)
        for ids, points in [([value["id"]], 20), ([value["id"]] * 3, 20), ([value["id"]] * 2, 1000)]:
            with self.subTest(points=points, count=len(ids)), self.assertRaises(ValidationError):
                ComparisonRequest(report_ids=ids, points=points)

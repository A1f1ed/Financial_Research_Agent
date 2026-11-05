from datetime import date
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from src.a_share_events import attach_holder_filings, covered_symbol, holder_filing_matches, normalize_events


class AShareEventTests(TestCase):
    def test_unverified_future_unlock_and_post_cutoff_publication_are_excluded(self):
        cutoff = date(2026, 10, 30)
        symbol = "300750.SZ"
        unlock = {"SECUCODE": symbol, "FREE_DATE": "2026-11-20 00:00:00", "EUTIME": "2026-10-29 10:00:00",
                  "ABLE_FREE_SHARES": 321.25, "FREE_SHARES": 200000, "A20_ADJCHRATE": 99}
        page = ([], "https://data.eastmoney.com/")
        pages = [page, ([unlock], page[1])]
        self.assertEqual(normalize_events(pages, symbol, cutoff)["events"], [])
        filing = {"title": "关于限售股份上市流通的公告", "excerpt": "上市流通日为2026年11月20日。",
                  "publish_at": "2026-10-30T16:01:00Z", "url": "https://www.cninfo.com.cn/test"}
        self.assertEqual(normalize_events(pages, symbol, cutoff, [filing])["events"], [])
        filing["publish_at"] = "2026-10-30T09:00:00+08:00"
        [event] = normalize_events(pages, symbol, cutoff, [filing])["events"]
        self.assertEqual(event["state"], "已披露待发生")
        self.assertEqual(event["published_at"], "2026-10-30")
        self.assertEqual(event["filing_url"], filing["url"])
        self.assertEqual(event["url"], page[1])
        self.assertIn("321.2500 万股", event["description"])
        self.assertNotIn("200000", event["description"])

    def test_billboard_requires_exact_exchange_and_keeps_disclosure_separate(self):
        cutoff = date(2026, 10, 30)
        symbol = "300911.SZ"
        row = {"SECUCODE": symbol, "TRADE_DATE": "2026-10-29", "EXPLANATION": "盘后披露",
               "BILLBOARD_NET_AMT": -25000, "D5_CLOSE_ADJCHRATE": 93}
        result = normalize_events([([row, {**row, "SECUCODE": "300911.SH"}], "https://data.eastmoney.com/"),
                                   TimeoutError()], symbol, cutoff)
        [event] = result["events"]
        self.assertIsNone(event["published_at"])
        self.assertIn("-2.50 万元", event["description"])
        self.assertNotIn("93", event["description"])
        self.assertTrue(any("暂不可用" in gap for gap in result["gaps"]))
        self.assertFalse(covered_symbol("510300.SH"))

    def test_holder_change_requires_as_of_disclosure_and_consistent_realized_interval(self):
        cutoff = date(2026, 11, 5)
        source = "https://data.eastmoney.com/"
        row = {"SECURITY_CODE": "000402", "HOLDER_NAME": "和谐健康保险股份有限公司", "DIRECTION": "减持",
               "START_DATE": "2026-10-20", "END_DATE": "2026-11-03", "NOTICE_DATE": "2026-11-05",
               "EITIME": "2026-11-04 17:32:27", "CHANGE_NUM_SYMBOL": -2252.06, "MARKET": "二级市场",
               "NEWEST_PRICE": 99.5, "HOLD_RATIO": 10}
        invalid = [{**row, **changes} for changes in (
            {"SECURITY_CODE": "600402"}, {"NOTICE_DATE": "2026-11-06"}, {"NOTICE_DATE": None},
            {"EITIME": "2026-11-06"}, {"END_DATE": "2026-11-30"}, {"START_DATE": "2026-11-04"},
            {"CHANGE_NUM_SYMBOL": 2252.06}, {"CHANGE_NUM_SYMBOL": None},
        )]
        pages = [([], source), ([], source), ([row, *invalid], source)]
        self.assertEqual(normalize_events(pages, "000402.SZ", date(2026, 11, 4))["events"], [])
        [event] = normalize_events(pages, "000402.SZ", cutoff)["events"]
        self.assertEqual((event["kind"], event["date"], event["published_at"], event["state"]),
                         ("holder_change", "2026-11-03", "2026-11-05", "减持"))
        self.assertIn("2,252.0600 万股", event["description"])
        self.assertIn("占总股本 10%", event["description"])
        self.assertNotIn("99.5", event["description"])


class HolderFilingTests(IsolatedAsyncioTestCase):
    notice = date(2026, 11, 5)
    pdf = "https://disc.static.szse.cn/download/disc/disk03/finalpage/2026-11-05/example.PDF"
    text = ("证券代码：000402。和谐健康保险股份有限公司（以下简称“和谐健康”）。"
            "和谐健康于2026年10月20日、10月21日及11月3日减持公司股份2,252.06万股。")

    def event(self):
        return {"kind": "holder_change", "holder": "和谐健康保险股份有限公司", "published_at": str(self.notice),
                "start_date": "2026-10-20", "date": "2026-11-03", "state": "减持", "shares_10k": 2252.06,
                "filing_url": None, "note": "抽取的披露样本。"}

    def test_filing_must_match_exact_code_holder_direction_amount_and_dates(self):
        self.assertTrue(holder_filing_matches(self.text, "000402", self.event()))
        self.assertTrue(holder_filing_matches(self.text.replace("2,252.06万股", "22,520,600股"), "000402", self.event()))
        for old, new in (("000402", "000498"), ("和谐健康", "另一股东"), ("减持", "增持"),
                         ("2,252.06", "2,252.60"), ("11月3日", "2025年11月3日")):
            with self.subTest(field=old):
                self.assertFalse(holder_filing_matches(self.text.replace(old, new), "000402", self.event()))

    async def test_only_allowlisted_and_date_aligned_pdf_can_be_attached(self):
        base = {"file_name": "股东权益变动提示性公告", "publish_at": "2026-11-04T09:24:55Z"}
        filings = [
            {**base, "file_urls": ["https://disc.static.szse.cn.example.com/finalpage/2026-11-05/a.pdf"]},
            {**base, "file_urls": [self.pdf.replace("11-05", "11-04")]},
            {**base, "publish_at": "2026-11-05T17:00:00Z", "file_urls": [self.pdf]},
            {**base, "file_urls": [self.pdf]},
        ]
        event = self.event()
        with patch("src.a_share_events.filing_text", AsyncMock(return_value=self.text)) as read:
            await attach_holder_filings({"events": [event]}, "000402.SZ", self.notice, filings)
        read.assert_awaited_once_with(self.pdf)
        self.assertEqual(event["filing_url"], self.pdf)

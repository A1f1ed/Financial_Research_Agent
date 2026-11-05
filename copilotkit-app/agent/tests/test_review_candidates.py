from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from src import research_store
from src.review_candidates import CandidateRequest, add_candidate, initialize_candidates, list_candidates, remove_candidate


class ReviewCandidateTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        database = patch.object(research_store, "DB", Path(directory.name) / "test.sqlite3")
        database.start()
        self.addCleanup(database.stop)

    def test_legacy_note_survives_and_exact_observations_are_idempotent(self):
        initialize_candidates()
        with research_store.connect() as db:
            db.execute("INSERT INTO review_candidates VALUES (?,?,?,?)", ("000402.SZ", "2024-10-25", "510300.SH", "观察备注"))
        initialize_candidates()
        initialize_candidates()
        for origin in ("ladder", "industry", "industry"):
            add_candidate(CandidateRequest(symbol="000402.SZ", session="2024-10-28", benchmark="510300.SH", origin=origin))
        item, = list_candidates()["candidates"]
        self.assertEqual((item["note"], item["session"]), ("观察备注", "2024-10-25"))
        self.assertEqual([row["origin"] for row in item["observations"]], ["industry", "ladder", "legacy"])
        self.assertIn("date=20241028", item["observations"][0]["source_url"])
        remove_candidate("000402.SZ")
        initialize_candidates()
        self.assertEqual(list_candidates()["candidates"], [])
        with research_store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM candidate_observations").fetchone()[0], 0)

    def test_report_observation_validates_scope_and_survives_archival(self):
        initialize_candidates()
        report_id = str(uuid4())
        research_store.save_report({
            "id": report_id, "status": "complete", "symbol": "000402.SZ", "as_of": "2024-10-27",
            "config": {"benchmark": "510300.SH"}, "evidence": {"bars": [{"date": "2024-10-25", "volume": 100}]},
        })
        candidate = {"symbol": "000402.SZ", "benchmark": "510300.SH", "origin": "report", "report_id": report_id}
        with self.assertRaises(HTTPException) as mismatch:
            add_candidate(CandidateRequest(**candidate, session="2024-10-27"))
        self.assertEqual(mismatch.exception.status_code, 422)
        add_candidate(CandidateRequest(**candidate, session="2024-10-25"))
        self.assertTrue(list_candidates()["candidates"][0]["observations"][0]["report_available"])
        research_store.archive_report(report_id)
        self.assertFalse(list_candidates()["candidates"][0]["observations"][0]["report_available"])

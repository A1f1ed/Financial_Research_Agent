"""Real PostgreSQL tests; SQLite is used only to construct legacy import input.

Run explicitly with APERTURE_RUN_INTEGRATION=1. Each run creates and drops its
own aperture_test_* database, never the application or rehearsal database.
"""
from contextlib import closing
from alembic import command
from alembic.config import Config
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Send
from psycopg import connect as pg_connect, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from src.infrastructure.config import Infrastructure
from src.infrastructure.cache import MarketCache
from redis.exceptions import ConnectionError as RedisConnectionError
from src.persistence.database import engine_for, transaction
from src.persistence.business import BusinessRepository
from src.persistence.jobs import JobRepository, MissingRecord, StateConflict
from src.jobs.dispatcher import dispatch, recover
from src.persistence.migrate_legacy import import_business, import_checkpoints, readonly, snapshot, upgrade
from src.persistence.models import Base, Report, Preference, Outbox, RunEvent


@unittest.skipUnless(os.getenv("APERTURE_RUN_INTEGRATION") == "1", "Requires explicit isolated PostgreSQL integration run")
class PostgreSQLFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = Infrastructure.read()
        cls.database = "aperture_test_" + uuid4().hex
        cls.params = conninfo_to_dict(cls.settings.checkpoint_url)
        with pg_connect(make_conninfo(**cls.params), autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.database)))
        cls.bind = engine_for(make_url(cls.settings.database_url).set(database=cls.database).render_as_string(hide_password=False))
        upgrade(cls.bind)

    @classmethod
    def tearDownClass(cls):
        MarketCache(cls.bind).clear_test_namespace()
        cls.bind.dispose()
        if not cls.database.startswith("aperture_test_"):
            raise AssertionError("Refusing to drop a non-test database")
        with pg_connect(make_conninfo(**cls.params), autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(cls.database)))

    def setUp(self):
        with self.bind.begin() as connection:
            tables = ", ".join('research."' + table.name + '"' for table in Base.metadata.sorted_tables)
            connection.execute(text("TRUNCATE " + tables + " RESTART IDENTITY"))
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "legacy.sqlite3"
        with closing(sqlite3.connect(self.source)) as db, db:
            db.executescript("""
                CREATE TABLE reports (id TEXT PRIMARY KEY, body TEXT NOT NULL, archived INTEGER DEFAULT 0);
                CREATE TABLE preferences (key TEXT PRIMARY KEY, body TEXT NOT NULL);
            """)
            db.executemany("INSERT INTO reports VALUES (?,?,?)", [
                ("report-a", json.dumps({"id": "report-a", "summary": "证据—not SQL: ' ; DROP TABLE reports;", "value": 1.25}), 0),
                ("report-b", json.dumps({"id": "report-b", "summary": "Archived source"}), 1),
            ])
            db.execute("INSERT INTO preferences VALUES (?,?)", ("ai", json.dumps({"provider": "dashscope", "model": "fixture"})))

    def test_business_migrations_downgrade_and_reupgrade_in_isolated_database(self):
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with self.bind.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            self.assertIsNone(connection.scalar(text("SELECT to_regclass('research.reports')")))
            command.upgrade(config, "head")
            predicate = connection.scalar(text("SELECT pg_get_expr(indpred,indrelid) FROM pg_index WHERE indexrelid='research.ix_outbox_pending'::regclass"))
            self.assertIn("failed_at IS NULL", predicate)
            command.check(config)

    def test_readonly_snapshot_and_idempotent_semantic_import(self):
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        backup = self.source.with_name("snapshot.sqlite3")
        snapshot(self.source, backup)
        first = import_business(backup, self.bind)
        second = import_business(backup, self.bind)
        self.assertEqual(first, second)
        self.assertEqual(first["reports"]["count"], 2)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)
        with readonly(backup) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM reports")
        with transaction(self.bind) as db:
            self.assertEqual(db.get(Report, "report-a").body["value"], 1.25)
            self.assertTrue(db.get(Report, "report-b").archived)

    def test_existing_difference_aborts_without_overwriting(self):
        import_business(self.source, self.bind)
        with transaction(self.bind) as db:
            db.get(Report, "report-a").body = {"id": "report-a", "summary": "Newer user edit"}
        with self.assertRaisesRegex(ValueError, "differs"):
            import_business(self.source, self.bind)
        with transaction(self.bind) as db:
            self.assertEqual(db.get(Report, "report-a").body["summary"], "Newer user edit")

    def test_source_extra_rows_do_not_partially_commit_on_conflict(self):
        import_business(self.source, self.bind)
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("INSERT INTO reports VALUES (?,?,?)", ("new", json.dumps({"id": "new"}), 0))
            db.execute("UPDATE preferences SET body=?", (json.dumps({"model": "different"}),))
        with self.assertRaises(ValueError):
            import_business(self.source, self.bind)
        with transaction(self.bind) as db:
            self.assertIsNone(db.get(Report, "new"))
            self.assertEqual(db.get(Preference, "ai").body["model"], "fixture")

    def test_identity_continues_after_legacy_insertion_order(self):
        import_business(self.source, self.bind)
        with transaction(self.bind) as db:
            report = Report(id="new", body={"id": "new"})
            db.add(report)
            db.flush()
            self.assertGreater(report.record_order, 2)

    def test_transaction_rollback_and_jsonb_query(self):
        with self.assertRaises(RuntimeError):
            with transaction(self.bind) as db:
                db.add(Report(id="rolled-back", body={"nested": {"unit": "RMB’000"}}))
                db.flush()
                raise RuntimeError("Cancel this transaction")
        with transaction(self.bind) as db:
            self.assertIsNone(db.get(Report, "rolled-back"))
            db.add(Report(id="json", body={"nested": {"unit": "RMB’000"}}))
        with transaction(self.bind) as db:
            found = db.scalars(select(Report).where(Report.body["nested"]["unit"].astext == "RMB’000")).one()
            self.assertEqual(found.id, "json")

    def test_pgvector_is_real_and_bad_financial_values_are_rejected(self):
        with self.bind.connect() as db:
            self.assertEqual(db.execute(text("SELECT '[1,0]'::vector <=> '[1,0]'::vector")).scalar_one(), 0)
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("UPDATE reports SET body=? WHERE id='report-a'", ('{"id":"report-a","value":NaN}',))
        with self.assertRaises(ValueError):
            import_business(self.source, self.bind)
        with transaction(self.bind) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Report)), 0)

    def test_chinese_keyword_baseline_does_not_assume_english_tokenization(self):
        with self.bind.begin() as db:
            # The simple dictionary indexes an uninterrupted Chinese phrase as
            # one lexeme; a substring query does not match automatically.
            hit = db.scalar(text("SELECT to_tsvector('simple', '经营现金流量净额') @@ plainto_tsquery('simple', '现金流')"))
            self.assertFalse(hit)
            db.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            score = db.scalar(text("SELECT word_similarity('现金流', '经营现金流量净额')"))
            self.assertGreater(score, 0)
            self.assertTrue(db.scalar(text("SELECT '经营现金流量净额' ILIKE :pattern"), {"pattern": "%现金流%"}))

    def test_checkpoint_messages_send_and_pending_writes_survive_and_conflicts_fail(self):
        source = self.source.with_name("checkpoints.sqlite3")
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {
            "messages": [HumanMessage(content="Fixture question"),
                         AIMessage(content="", tool_calls=[{"name": "read_fixture", "args": {}, "id": "call-fixture"}]),
                         ToolMessage(content="Fixture result", tool_call_id="call-fixture")],
            "dispatch": [Send("fixture", {"document_id": "fixture"})],
        }
        checkpoint["channel_versions"] = {"messages": "1", "dispatch": "1"}
        with closing(sqlite3.connect(source)) as connection:
            saver = SqliteSaver(connection)
            config = saver.put({"configurable": {"thread_id": "fixture-thread", "checkpoint_ns": ""}},
                               checkpoint, {"source": "input", "step": 0}, checkpoint["channel_versions"])
            saver.put_writes(config, [("messages", [AIMessage(content="Pending fixture")]), ("__error__", "original error")],
                             "fixture-task", "fixture-path")
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        params = {**self.params, "dbname": self.database, "options": "-c search_path=agent,public"}
        conninfo = make_conninfo(**params)
        first = import_checkpoints(source, conninfo)
        second = import_checkpoints(source, conninfo)
        self.assertEqual(first, second)
        self.assertEqual((first["count"], first["writes"]), (1, 2))
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        with pg_connect(conninfo, autocommit=True, prepare_threshold=0, row_factory=dict_row) as target:
            saver = PostgresSaver(target)
            restored = saver.get_tuple(config)
            self.assertEqual(restored.checkpoint["channel_values"]["messages"][2].tool_call_id, "call-fixture")
            self.assertEqual(restored.checkpoint["channel_values"]["dispatch"][0].node, "fixture")
            saver.put_writes(config, [("__error__", "newer error")], "fixture-task", "fixture-path")
        with self.assertRaisesRegex(ValueError, "pending writes differ"):
            import_checkpoints(source, conninfo)

    def test_business_repository_preserves_archive_order_and_projects_reports(self):
        repository = BusinessRepository(self.bind)
        repository.save_report({"id": "one", "symbol": "FIXTURE.HK", "evidence": {"large": "not a list field"}})
        repository.save_report({"id": "two", "symbol": "OTHER.HK"})
        self.assertEqual([row["id"] for row in repository.list_reports(1)], ["two"])
        self.assertNotIn("evidence", repository.list_reports()[0])
        self.assertTrue(repository.archive_report("one"))
        repository.save_report({"id": "one", "symbol": "FIXTURE.HK", "updated": True})
        self.assertIsNone(repository.get_report("one"))
        self.assertTrue(repository.get_report("one", include_archived=True)["updated"])
        self.assertEqual([row["id"] for row in repository.list_reports()], ["two"])

    def test_postgres_settings_followups_and_redis_market_cache_scope(self):
        repository = BusinessRepository(self.bind)
        repository.write_settings({"ai": {"model": "first"}, "ai:fixture": {"model": "first"}})
        repository.write_settings({"ai": {"model": "second"}})
        self.assertEqual(repository.read_setting("ai")["model"], "second")
        self.assertEqual(repository.read_setting("ai:fixture")["model"], "first")
        repository.put_cache("fixture", [], fetched=100)
        self.assertEqual(repository.cached("fixture", 10, now=105), [])
        self.assertIsNone(repository.cached("fixture", 10, now=111))
        self.assertIsNone(repository.cached("fixture", 10, now=99))
        cache = MarketCache(self.bind)
        with cache.client() as client:
            self.assertGreater(client.ttl(cache.key("fixture")), 0)
        with patch.object(MarketCache, "client", side_effect=RedisConnectionError("fixture outage")):
            self.assertIsNone(repository.cached("fixture", 10, now=105))
            self.assertFalse(repository.put_cache("fixture", ["unavailable"]))
        repository.save_followups("thread", "message", ["First?"], "report-a")
        repository.save_followups("thread", "message", ["Should not replace"], "report-a")
        self.assertEqual(repository.followups("thread", "message", "report-a"), ["First?"])
        self.assertIsNone(repository.followups("thread", "message", "report-b"))

    def test_enqueued_task_and_outbox_commit_together(self):
        repository = JobRepository(self.bind)
        key = repository.create_job("Fixture research", {"symbol": "FIXTURE.HK"})
        with transaction(self.bind) as db:
            queued = db.scalar(select(Outbox).where(Outbox.aggregate_id == key))
            self.assertEqual(queued.payload, {"job_id": key})
            self.assertIsNone(queued.delivered_at)
        self.assertEqual(repository.task_detail(key)["status"], "queued")
        with self.assertRaises(StateConflict):
            repository.hide_task(key)

    def test_run_now_serializes_concurrent_requests_and_deleted_plan_keeps_history(self):
        repository = JobRepository(self.bind)
        key = repository.create_schedule({"name": "Fixture plan", "enabled": False}, None)
        build = lambda body: {"symbol": "FIXTURE.HK"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls = list(pool.map(lambda _: repository.run_schedule(key, build), range(2)))
        self.assertEqual(calls[0]["id"], calls[1]["id"])
        self.assertEqual(sum(not row["existing"] for row in calls), 1)
        run = calls[0]["id"]
        repository.cancel(run)
        repository.hide_task(run)
        self.assertEqual(repository.list_tasks(), [])
        self.assertEqual(len(repository.list_tasks(schedule_id=key)), 1)
        repository.archive_schedule(key)
        self.assertEqual(repository.list_schedules(), [])
        self.assertEqual(len(repository.list_tasks(schedule_id=key)), 1)
        with self.assertRaises(MissingRecord):
            repository.run_schedule(key, build)

    def test_expired_lease_cannot_publish_or_finish_after_reclaim(self):
        repository = JobRepository(self.bind)
        business = BusinessRepository(self.bind)
        key = repository.create_job("Fixture", {"symbol": "FIXTURE.HK"})
        now = datetime.now(timezone.utc)
        self.assertEqual(repository.claim(key, "old", now=now, lease_seconds=10)["state"], "claimed")
        self.assertEqual(repository.claim(key, "duplicate", now=now)["state"], "leased")
        later = now + timedelta(seconds=11)
        self.assertEqual(repository.claim(key, "new", now=later)["state"], "claimed")
        report = {"id": key, "symbol": "FIXTURE.HK", "config": {}, "status": "complete", "stages": []}
        with self.assertRaises(StateConflict):
            repository.save_report(key, "old", report, now=later)
        self.assertFalse(repository.finish(key, "old", "complete", now=later))
        repository.save_report(key, "new", report, now=later)
        self.assertTrue(repository.finish(key, "new", "complete", now=later))
        self.assertEqual(business.get_report(key)["status"], "complete")
        self.assertEqual(repository.claim(key, "duplicate", now=later)["state"], "finished")
        with transaction(self.bind) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(RunEvent)), 1)

    def test_cancel_blocks_late_report_and_survives_task_hiding(self):
        repository = JobRepository(self.bind)
        key = repository.create_job("Fixture", {"symbol": "FIXTURE.HK"})
        repository.claim(key, "token")
        report = {"id": key, "status": "running", "stages": [{"id": "data", "status": "running"}]}
        repository.save_report(key, "token", report)
        repository.cancel(key)
        self.assertFalse(repository.heartbeat(key, "token"))
        with self.assertRaises(StateConflict):
            repository.save_report(key, "token", {**report, "status": "complete"})
        repository.hide_task(key)
        self.assertEqual(repository.list_tasks(), [])
        self.assertEqual(BusinessRepository(self.bind).get_report(key)["stages"][0]["status"], "cancelled")

    def test_confirmed_outbox_delivery_is_recorded_and_bounded_failures_are_visible(self):
        repository = JobRepository(self.bind)
        key = repository.create_job("Fixture", {"symbol": "FIXTURE.HK"})
        seen = []
        def publish(topic, payload, message_id):
            seen.append((topic, payload, message_id))
        self.assertEqual(dispatch(publish, bind=self.bind), {"sent": 1, "failed": 0})
        self.assertEqual(dispatch(publish, bind=self.bind), {"sent": 0, "failed": 0})
        self.assertEqual(seen[0][1], {"job_id": key})
        other = repository.create_job("Unavailable broker", {"symbol": "FIXTURE.HK"})
        def unavailable(*_args):
            raise TimeoutError("fixture")
        now = datetime.now(timezone.utc)
        dispatch(unavailable, bind=self.bind, now=now, max_attempts=2)
        dispatch(unavailable, bind=self.bind, now=now + timedelta(seconds=3), max_attempts=2)
        self.assertEqual(repository.task_detail(other)["status"], "failed")
        with transaction(self.bind) as db:
            row = db.scalar(select(Outbox).where(Outbox.aggregate_id == other))
            self.assertIsNotNone(row.failed_at)
            self.assertEqual(row.attempts, 2)

    def test_expired_worker_recovery_is_bounded_and_fences_old_results(self):
        repository = JobRepository(self.bind)
        key = repository.create_job("Fixture", {"symbol": "FIXTURE.HK"})
        now = datetime.now(timezone.utc)
        repository.claim(key, "first", now=now, lease_seconds=1)
        self.assertEqual(recover(bind=self.bind, now=now + timedelta(seconds=2), max_recoveries=1), 1)
        self.assertEqual(repository.task_detail(key)["status"], "queued")
        later = now + timedelta(seconds=3)
        repository.claim(key, "second", now=later, lease_seconds=1)
        repository.save_report(key, "second", {"id": key, "status": "running", "config": {},
            "evidence": {"sources": [{"id": "S1", "title": "Retained source"}]},
            "stages": [{"id": "data", "status": "complete"}, {"id": "synthesis", "status": "running"}]}, now=later)
        self.assertFalse(repository.finish(key, "first", "complete", now=later))
        recover(bind=self.bind, now=later + timedelta(seconds=2), max_recoveries=1)
        self.assertEqual(repository.task_detail(key)["status"], "failed")
        report = BusinessRepository(self.bind).get_report(key)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["stages"][1]["status"], "failed")
        self.assertEqual(report["evidence"]["sources"][0]["id"], "S1")

    def test_worker_error_ends_report_progress_without_erasing_evidence(self):
        repository = JobRepository(self.bind)
        key = repository.create_job("Fixture", {"symbol": "FIXTURE.HK"})
        repository.claim(key, "worker")
        repository.save_report(key, "worker", {"id": key, "status": "running", "config": {},
            "evidence": {"sources": [{"id": "S1"}]}, "stages": [{"id": "data", "status": "running"}]})
        self.assertTrue(repository.finish(key, "worker", "failed", error="Provider unavailable"))
        report = BusinessRepository(self.bind).get_report(key)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["stages"][0]["status"], "failed")
        self.assertEqual(len(report["evidence"]["sources"]), 1)


if __name__ == "__main__":
    unittest.main()

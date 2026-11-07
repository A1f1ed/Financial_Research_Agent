from postgres_fixture import postgres_fixture
import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

from src import research_store, workbench
from src.research_models import ResearchConfig
from src.research_workflow import read_current_research, run_financial_research
from src.persistence.models import Job, Schedule as StoredSchedule
from sqlalchemy import select
import json


class WorkbenchTests(IsolatedAsyncioTestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.enterContext(postgres_fixture())
        workbench.initialize_queue()
        self.config = ResearchConfig(symbol="1211.HK", market="HK")
        self.delivered = set()

    def claim_jobs(self, capacity):
        # Simulate broker delivery only; the real runner claims/fences PostgreSQL.
        workbench.dispatch_due_schedules()
        with research_store.connect() as db:
            rows = db.scalars(select(Job).where(Job.status == "queued").order_by(Job.record_order)).all()
            result = [(row.id, json.dumps(row.config)) for row in rows if row.id not in self.delivered][:capacity]
            self.delivered.update(row[0] for row in result)
            return result

    async def test_manual_jobs_run_concurrently_with_distinct_reports(self):
        ids = [workbench.create_job(self.config)["id"] for _ in range(2)]
        both_started = asyncio.Event()
        started = set()

        async def fake_research(config, *, report_id):
            started.add(report_id)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=2)
            research_store.save_report({
                "id": report_id, "symbol": config.symbol, "status": "complete",
                "config": config.model_dump(mode="json"), "created_at": datetime.now(timezone.utc).isoformat(),
            })
            return {"status": "complete"}

        with patch("src.research_workflow.execute_research", fake_research):
            claimed = self.claim_jobs(3)
            self.assertEqual({row[0] for row in claimed}, set(ids))
            self.assertEqual(self.claim_jobs(3), [])
            await asyncio.gather(*(workbench.run_job(*row) for row in claimed))

        tasks = workbench.tasks()["tasks"]
        self.assertEqual({task["report_id"] for task in tasks}, set(ids))
        self.assertTrue(all(task["status"] == "complete" for task in tasks))

    async def test_report_qa_uses_only_bound_report(self):
        research_store.save_report({
            "id": "report-a", "symbol": "1211.HK", "as_of": "2026-10-31",
            "evidence": {"sources": [{"id": "S1"}]},
        })
        runtime = SimpleNamespace(state={
            "research_qa_report_id": "report-a", "research": {"id": "other-report"},
        }, tool_call_id="qa-tool")
        report = read_current_research.func(runtime)
        self.assertEqual((report["id"], report["sources"][0]["id"]), ("report-a", "S1"))
        result = await run_financial_research.coroutine(runtime, self.config.model_dump(mode="json"))
        self.assertIn("请就当前报告提问", result.update["messages"][0].content)

    def test_legacy_report_opens_as_task_and_can_be_removed_from_list(self):
        research_store.save_report({
            "id": "legacy", "symbol": self.config.symbol, "status": "complete",
            "config": self.config.model_dump(mode="json"),
            "created_at": datetime.now(timezone.utc).isoformat(), "stages": [], "elapsed_seconds": 12,
        })
        self.assertEqual(workbench.task_detail("legacy")["report_id"], "legacy")
        workbench.hide_task("legacy")
        self.assertEqual(workbench.tasks()["tasks"], [])
        self.assertIsNotNone(research_store.get_report("legacy"))

    def test_deleting_a_run_and_plan_preserves_the_execution_history(self):
        plan = workbench.Schedule(name="删除测试", config=self.config, repeat="daily", time="09:00", enabled=False)
        plan_id = workbench.create_schedule(plan)["id"]
        run_id = workbench.run_schedule_now(plan_id)["id"]
        with self.assertRaises(HTTPException) as error:
            workbench.hide_task(run_id)
        self.assertEqual(error.exception.status_code, 409)
        with research_store.connect() as db:
            setattr(db.get(Job, run_id), "status", "complete")
        workbench.hide_task(run_id)
        workbench.remove_schedule(plan_id)
        self.assertEqual(workbench.tasks()["tasks"], [])
        self.assertEqual(workbench.schedules()["schedules"], [])
        self.assertEqual(workbench.schedule_history(plan_id)["tasks"][0]["id"], run_id)

    def test_recent_manual_tasks_merge_legacy_reports_and_exclude_scheduled_runs(self):
        older = workbench.create_job(self.config)["id"]
        plan_id = workbench.create_schedule(
            workbench.Schedule(name="测试计划", config=self.config, repeat="daily", time="09:00")
        )["id"]
        workbench.run_schedule_now(plan_id)
        research_store.save_report({
            "id": "legacy", "symbol": self.config.symbol, "status": "complete",
            "created_at": "2099-01-01T00:00:00+00:00",
        })
        self.assertEqual([row["id"] for row in workbench.tasks(kind="manual", limit=1)["tasks"]], ["legacy"])
        self.assertEqual([row["id"] for row in workbench.tasks(kind="manual", limit=3)["tasks"]], ["legacy", older])

    async def test_due_schedule_queues_once_and_advances(self):
        schedule = workbench.Schedule(name="测试计划", config=self.config, repeat="daily", time="09:00")
        key = workbench.create_schedule(schedule)["id"]
        self.assertEqual(self.claim_jobs(3), [])
        with research_store.connect() as db:
            setattr(db.get(StoredSchedule, key), "next_run", datetime(2000, 1, 1, tzinfo=timezone.utc))
        [(job_id, raw_config)] = self.claim_jobs(3)
        self.assertEqual(self.claim_jobs(3), [])
        config = ResearchConfig.model_validate_json(raw_config)
        self.assertEqual(config.as_of, datetime.now(workbench.market_zone("HK")).date())
        task = workbench.tasks()["tasks"][0]
        self.assertEqual((task["id"], task["schedule_id"], task["kind"]), (job_id, key, "scheduled"))
        self.assertGreater(workbench.schedules()["schedules"][0]["next_run"], datetime.now(timezone.utc).isoformat())

    async def test_trading_day_schedule_skips_holidays_and_runs_once_on_a_half_day(self):
        config = ResearchConfig(symbol="SPY.US", market="US")
        plan = workbench.Schedule(name="美股晨报测试", config=config, workflow="morning", repeat="trading_days", time="08:00")
        key = workbench.create_schedule(plan)["id"]
        self.assertIsNone(workbench.schedules()["schedules"][0]["next_run"])
        holiday = datetime(2026, 11, 26, 13, 0, tzinfo=timezone.utc)
        half_day = holiday + timedelta(days=1)
        with patch("src.research_data.cli", AsyncMock(return_value={
            "trading_days": ["2026-11-30"], "half_trading_days": ["2026-11-27"],
        })):
            await workbench.sync_trading_schedules(holiday, {})
            with research_store.connect() as db:
                self.assertEqual(db.get(StoredSchedule, key).next_run.isoformat(), half_day.isoformat())
            self.assertEqual(workbench.tasks()["tasks"], [])
            await workbench.sync_trading_schedules(half_day, {})
            await workbench.sync_trading_schedules(half_day, {})
        [task] = workbench.schedule_history(key)["tasks"]
        self.assertEqual(task["trigger"], "clock")
        self.assertEqual(workbench.task_detail(task["id"])["config"]["as_of"], "2026-11-27")

    async def test_calendar_outage_keeps_schedule_pending_and_expired_run_is_skipped(self):
        plan = workbench.Schedule(name="日历降级测试", config=self.config, repeat="trading_days", time="09:00")
        key = workbench.create_schedule(plan)["id"]
        due = datetime(2026, 11, 5, 1, 0, tzinfo=timezone.utc)
        with research_store.connect() as db:
            setattr(db.get(StoredSchedule, key), "next_run", due)
        retry = {}
        with patch.object(workbench, "exchange_sessions", AsyncMock(side_effect=TimeoutError)) as calendar:
            await workbench.sync_trading_schedules(due, retry)
            await workbench.sync_trading_schedules(due + timedelta(seconds=10), retry)
            calendar.assert_awaited_once()
        self.assertEqual(workbench.tasks()["tasks"], [])
        with patch.object(workbench, "exchange_sessions", AsyncMock(return_value=[date(2026, 11, 5), date(2026, 11, 6)])):
            await workbench.sync_trading_schedules(due + timedelta(minutes=16), retry)
        self.assertEqual(workbench.tasks()["tasks"], [])
        with research_store.connect() as db:
            self.assertEqual(db.get(StoredSchedule, key).next_run.isoformat(),
                             (due + timedelta(days=1)).isoformat())

    async def test_close_anchor_uses_half_day_and_queues_once(self):
        plan = workbench.Schedule(name="半日市收盘", config=ResearchConfig(symbol="SPY.US", market="US"),
                                  repeat="trading_days", time="16:30", timing="after_close", offset_minutes=30)
        key = workbench.create_schedule(plan)["id"]
        holiday = datetime(2026, 11, 26, 18, 0, tzinfo=timezone.utc)
        due = datetime(2026, 11, 27, 18, 30, tzinfo=timezone.utc)
        calendar = {date(2026, 11, 27): True, date(2026, 11, 30): False}
        with patch.object(workbench, "exchange_calendar", AsyncMock(return_value=calendar)):
            await workbench.sync_trading_schedules(holiday, {})
            with research_store.connect() as db:
                self.assertEqual(db.get(StoredSchedule, key).next_run.isoformat(), due.isoformat())
            await workbench.sync_trading_schedules(due, {})
            await workbench.sync_trading_schedules(due, {})
        [task] = workbench.schedule_history(key)["tasks"]
        self.assertEqual(task["trigger"], "clock")
        with research_store.connect() as db:
            self.assertEqual(db.get(StoredSchedule, key).next_run.isoformat(),
                             "2026-11-30T21:30:00+00:00")

    def test_open_anchor_handles_dst_and_rejects_incompatible_repeats(self):
        from pydantic import ValidationError
        plan = workbench.Schedule(name="开盘前", config=ResearchConfig(symbol="SPY.US", market="US"),
                                  repeat="trading_days", time="09:00", timing="before_open", offset_minutes=30)
        self.assertEqual(workbench.trading_run_time(plan, date(2026, 10, 30)).isoformat(), "2026-10-30T13:00:00+00:00")
        self.assertEqual(workbench.trading_run_time(plan, date(2026, 11, 2)).isoformat(), "2026-11-02T14:00:00+00:00")
        with self.assertRaises(ValidationError):
            workbench.Schedule.model_validate({**plan.model_dump(), "repeat": "daily"})
        with self.assertRaises(ValidationError):
            workbench.Schedule.model_validate({**plan.model_dump(), "timing": "after_close", "offset_minutes": 0})

    async def test_pause_during_calendar_lookup_wins_and_allows_manual_run(self):
        plan = workbench.Schedule(name="暂停竞态测试", config=self.config, repeat="trading_days", time="09:00")
        key = workbench.create_schedule(plan)["id"]
        now = datetime(2026, 11, 5, 0, 30, tzinfo=timezone.utc)

        async def pause_then_return(*_args):
            workbench.update_schedule(key, plan.model_copy(update={"enabled": False}))
            return [date(2026, 11, 5)]

        with patch.object(workbench, "exchange_sessions", pause_then_return):
            await workbench.sync_trading_schedules(now, {})
        [paused] = workbench.schedules()["schedules"]
        self.assertFalse(paused["enabled"])
        self.assertIsNone(paused["next_run"])
        workbench.run_schedule_now(key)
        self.assertEqual(workbench.schedule_history(key)["tasks"][0]["trigger"], "manual")

    async def test_run_now_preserves_schedule_and_reuses_active_job(self):
        for enabled in (True, False):
            schedule = workbench.Schedule(name="测试立即运行", config=self.config, repeat="daily", time="09:00", enabled=enabled)
            key = workbench.create_schedule(schedule)["id"]
            before = next(item for item in workbench.schedules()["schedules"] if item["id"] == key)
            first = workbench.run_schedule_now(key)
            self.assertFalse(first["existing"])
            self.assertEqual(workbench.run_schedule_now(key), {"id": first["id"], "existing": True})
            self.assertEqual(next(item for item in workbench.schedules()["schedules"] if item["id"] == key), before)
            task = workbench.task_detail(first["id"])
            self.assertEqual(task["status"], "queued")
            self.assertEqual(task["config"]["as_of"], datetime.now(workbench.market_zone("HK")).date().isoformat())

    async def test_news_plan_filters_window_and_history_by_plan(self):
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        async def fake_cli(*args, fresh):
            self.assertEqual(args[:3], ("news", "search", "港股"))
            self.assertTrue(fresh)
            return [
                {"title": "当日市场观察", "time": (now - timedelta(hours=1)).isoformat()},
                {"title": "当日市场观察！", "time": (now - timedelta(hours=2)).isoformat()},
                {"title": "过期记录", "time": (now - timedelta(days=2)).isoformat()},
                {"title": "未来记录", "time": (now + timedelta(hours=1)).isoformat()},
                {"title": "无法验证时间", "time": str(now.date())},
            ]
        plan = workbench.Schedule(name="资讯测试", config=self.config, workflow="news", repeat="daily", time="09:00", enabled=False)
        plan_id = workbench.create_schedule(plan)["id"]
        other_id = workbench.create_schedule(plan)["id"]
        job_id = workbench.run_schedule_now(plan_id)["id"]
        with patch("src.scheduled_briefs.cli", fake_cli):
            await workbench.run_job(*self.claim_jobs(1)[0])
        report = research_store.get_report(job_id)
        self.assertEqual(report["status"], "complete")
        self.assertEqual([source["title"] for source in report["evidence"]["sources"]], ["当日市场观察"])
        self.assertEqual(workbench.schedule_history(plan_id)["tasks"][0]["trigger"], "manual")
        self.assertEqual(workbench.schedule_history(other_id)["tasks"], [])
        self.assertEqual(len(workbench.tasks()["tasks"]), 1)

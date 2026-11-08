"""Real PostgreSQL/version/lease/retrieval evaluation paths; provider calls mocked."""
import asyncio
from datetime import datetime, timedelta, timezone
import os
import unittest
from uuid import uuid4
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
import integration_tests.test_knowledge_search as fixtures
from src.evaluations.api import router
from src.evaluations.contracts import DatasetInput, DatasetEdit, RunOptions
from src.evaluations.repository import EvaluationRepository
from src.evaluations.execution import execute_evaluation, reserve, BudgetExceeded
from src.evaluations.tools import read_evaluation_failure, read_evaluation_run
from src.persistence.database import transaction
from src.persistence.models import EvaluationVersion, EvaluationRun, EvaluationAttempt, Job, Outbox, Document
from src.persistence.jobs import JobRepository, StateConflict
from src.jobs.runner import run_job


@unittest.skipUnless(os.getenv("APERTURE_RUN_INTEGRATION") == "1", "Requires isolated PostgreSQL")
class EvaluationTests(unittest.IsolatedAsyncioTestCase):
    setUpClass = classmethod(fixtures.SearchTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.SearchTests.tearDownClass.__func__)
    material = fixtures.SearchTests.material
    build = fixtures.SearchTests.build

    def setUp(self):
        fixtures.SearchTests.setUp(self)
        self.repo = EvaluationRepository()
        async def isolated_list(): return JobRepository().list_tasks(limit=20)
        mock=patch("src.evaluations.execution.task_list",isolated_list);mock.start();self.addCleanup(mock.stop)

    def case(self, **changes):
        return {"id": "cash-flow", "name": "Synthetic cash flow original page", "target": "retrieval", "question": "cash flow",
            "scope": {"collection_ids": [self.collection["id"]], "as_of": "2026-10-31", "market": "HK"}, **changes}

    def publish(self, cases=None):
        data = self.repo.save(DatasetInput(name="Synthetic evaluation", cases=cases or [self.case()]))
        version = self.repo.publish(data["id"], data["revision"])
        return data, version

    def start(self, version, **kwargs):
        return self.repo.start(RunOptions(version_id=version["id"], **kwargs))["id"]

    async def test_online_versioned_retrieval_and_no_paid_replay(self):
        doc = self.material("Synthetic disclosed cash flow is 100 units."); await self.build(doc)
        future = self.material("Future cash flow MUST NOT LEAK", "2026-11-01"); await self.build(future)
        data, version = self.publish([self.case(expected={"pages": [{"document_id": doc, "page_number": 2}]})])
        key = self.start(version, mode="retrieval_benchmark", repetitions=30)
        await run_job(key)
        result = self.repo.detail(key)
        self.assertEqual(result["summary"]["counts"]["passed"], 30)
        self.assertEqual(result["summary"]["recall_at_5"], 1)
        self.assertEqual(result["summary"]["latency"]["samples"], 30)
        self.assertEqual(result["counters"]["reserved_calls"], 0)
        first = result["attempts"][0]
        self.assertNotIn(future, [h["document_id"] for h in first["citations"]])
        await run_job(key)
        self.assertEqual(self.repo.detail(key)["summary"], result["summary"])
        with transaction() as db:
            outbox = db.scalar(select(Outbox).where(Outbox.aggregate_id == key))
            self.assertEqual(outbox.topic, "evaluation.execute")
        self.assertEqual(JobRepository().task_detail(key)["kind"], "evaluation")
        edited = self.repo.save(DatasetEdit(name="Changed rules", cases=[self.case(expected={"pages": [{"document_id": doc, "page_number": 1}]})], expected_revision=2), data["id"])
        second = self.repo.publish(data["id"], edited["revision"])
        next_key = self.start(second, parent_run_id=key)
        await run_job(next_key)
        comparison = self.repo.compare(key, next_key)
        self.assertFalse(comparison["comparable"])
        self.assertEqual(self.repo.detail(next_key)["summary"]["counts"]["failed"], 1)
        with transaction() as db:
            self.assertEqual(db.get(EvaluationVersion, version["id"]).body["cases"][0]["expected"]["pages"][0]["page_number"], 2)

    async def test_frozen_answers_hidden_from_agent_and_default_http(self):
        self.material("Synthetic scope for frozen case")
        _, version = self.publish([self.case(partition="acceptance", expected={"reference_note": "FROZEN_CANARY_ANSWER"})])
        with self.assertRaises(ValueError): self.start(version, partition="acceptance")
        key = self.start(version, partition="acceptance", acceptance_confirmed=True)
        await run_job(key)
        attempt = self.repo.detail(key)["attempts"][0]
        safe = await read_evaluation_failure.ainvoke({"run_id": key, "attempt_id": attempt["id"]})
        self.assertNotIn("FROZEN_CANARY_ANSWER", str(safe)); self.assertNotIn("result", safe)
        safe_run = await read_evaluation_run.ainvoke({"run_id": key})
        self.assertNotIn("FROZEN_CANARY_ANSWER", str(safe_run))
        app = FastAPI(); app.include_router(router)
        with TestClient(app) as client:
            data_id = self.repo.detail(key)["dataset_id"]
            hidden = client.get(f"/research/evaluations/datasets/{data_id}")
            self.assertNotIn("FROZEN_CANARY_ANSWER", hidden.text)
            explicit = client.get(f"/research/evaluations/datasets/{data_id}?reveal_frozen=true")
            self.assertIn("FROZEN_CANARY_ANSWER", explicit.text)
            self.assertEqual(client.post("/research/evaluations/runs",json={"version_id":version["id"]},headers={"Origin":"https://untrusted.invalid"}).status_code,403)

    async def test_budget_reservation_is_atomic_and_retained(self):
        data, version = self.publish([self.case(target="task_list", scope=None)])
        key = self.start(version, allow_model=True, max_calls=1, max_tokens=100)
        token = str(uuid4()); JobRepository().claim(key,token)
        with transaction() as db:
            attempt = db.scalar(select(EvaluationAttempt).where(EvaluationAttempt.run_id == key)); attempt_id = attempt.id
        reserve(key,attempt_id,token,90)
        with self.assertRaises(BudgetExceeded):reserve(key,attempt_id,token,10)
        self.assertEqual(self.repo.detail(key)["counters"],{"reserved_calls":1,"reserved_tokens":90})
        JobRepository().cancel(key)
        with self.assertRaises(StateConflict):reserve(key,attempt_id,token,1)

    async def test_worker_loss_does_not_repeat_in_flight_attempt(self):
        _, version = self.publish([self.case(target="task_list",scope=None)])
        key = self.start(version,repetitions=2)
        with transaction() as db:
            first = db.scalar(select(EvaluationAttempt).where(EvaluationAttempt.run_id == key).order_by(EvaluationAttempt.record_order))
            first.status="in_flight"; first.result={"model_calls":1,"reserved_tokens":99}
        await run_job(key)
        result=self.repo.detail(key)
        self.assertEqual(result["summary"]["counts"]["interrupted"],1)
        self.assertEqual(result["summary"]["counts"]["passed"],1)
        self.assertEqual(result["summary"]["model_calls"],1)
        self.assertEqual(result["status"],"partial")

    async def test_partial_timeout_unsupported_and_budget_stay_in_denominator(self):
        cases=[self.case(id="a",target="task_list",scope=None), self.case(id="b",target="task_list",scope=None),
            self.case(id="c",target="vision",scope=None),self.case(id="d",target="task_list",scope=None)]
        _,version=self.publish(cases);key=self.start(version)
        async def execute(case,*args):
            if case["id"]=="a":return {"list_valid":True}
            if case["id"]=="b":raise TimeoutError()
            if case["id"]=="c":return {"status":"unsupported"}
            raise BudgetExceeded()
        with patch("src.evaluations.execution.execute_case",execute):await run_job(key)
        summary=self.repo.detail(key)["summary"]
        self.assertEqual(summary["total"],4);self.assertEqual(summary["pass_rate_all"],.25)
        for status in ("passed","timeout","unsupported","budget_exceeded"):self.assertEqual(summary["counts"][status],1)

    async def test_source_changes_require_new_version_and_archive_retains_history(self):
        doc=self.material("Synthetic source");await self.build(doc)
        data,version=self.publish()
        with transaction() as db:db.get(Document,doc).metadata_revision+=1
        key=self.start(version);await run_job(key)
        self.assertEqual(self.repo.detail(key)["summary"]["counts"]["error"],1)
        current=self.repo.dataset(data["id"]);archived=self.repo.archive(data["id"],current["revision"],True)
        self.assertEqual(self.repo.detail(key)["summary"]["total"],1)
        with self.assertRaises(StateConflict):self.start(version)
        self.repo.archive(data["id"],archived["revision"],False)
        with self.assertRaises(StateConflict):self.repo.publish(data["id"],current["revision"])

    async def test_cancel_fences_late_results_and_preserves_completed(self):
        _,version=self.publish([self.case(target="task_list",scope=None)])
        key=self.start(version,repetitions=2);token=str(uuid4());JobRepository().claim(key,token)
        from src.evaluations.execution import save_result
        with transaction() as db:
            attempt=db.scalar(select(EvaluationAttempt).where(EvaluationAttempt.run_id==key).order_by(EvaluationAttempt.record_order));attempt.status="in_flight";attempt_id=attempt.id
        save_result(key,attempt_id,token,"passed",{"checks":{"contract":True}},.1)
        JobRepository().cancel(key)
        result=self.repo.detail(key)
        self.assertEqual(result["summary"]["counts"]["passed"],1);self.assertEqual(result["summary"]["counts"]["cancelled"],1)
        with self.assertRaises(StateConflict):save_result(key,attempt_id,token,"failed",{},.1)

    async def test_actual_agent_graph_excludes_frozen_expectations_and_records_calls(self):
        from integration_tests.test_document_chat import EvidenceModel
        seen=[]
        class ObservedModel(EvidenceModel):
            def _generate(self,messages,stop=None,run_manager=None,**kwargs):
                seen.extend(str(m.content) for m in messages)
                result=super()._generate(messages,stop=stop,run_manager=run_manager,**kwargs)
                result.generations[0].message.usage_metadata={"input_tokens":10,"output_tokens":5,"total_tokens":15}
                return result
        doc=self.material("Synthetic inventory provision disclosure for a fixed original.");await self.build(doc)
        _,version=self.publish([self.case(target="agent",partition="acceptance",question="Explain inventory provision",expected={"reference_note":"FROZEN_EXPECTATION_NEVER_SEND","pages":[{"document_id":doc,"page_number":2}]})])
        key=self.start(version,partition="acceptance",acceptance_confirmed=True,allow_model=True,max_calls=4,max_tokens=200000)
        with patch("src.model.compatible_model",return_value=ObservedModel()),patch("src.preferences.provider_key",return_value="synthetic"):
            await run_job(key)
        data=self.repo.detail(key)
        self.assertEqual(data["summary"]["counts"]["passed"],1,str(data["attempts"]))
        self.assertEqual(data["summary"]["model_calls"],2)
        self.assertEqual(data["summary"]["reported_tokens"],30)
        self.assertNotIn("FROZEN_EXPECTATION_NEVER_SEND"," ".join(seen))
        self.assertTrue(data["attempts"][0]["source_links"])

    async def test_comparison_keeps_cases_added_on_either_side(self):
        first, v1 = self.publish([self.case(id="old", target="task_list", scope=None)])
        old_run = self.start(v1); await run_job(old_run)
        draft = self.repo.save(DatasetEdit(name="Expanded", cases=[self.case(id="old", target="task_list", scope=None), self.case(id="added", target="task_list", scope=None)], expected_revision=2), first["id"])
        v2 = self.repo.publish(first["id"], draft["revision"])
        new_run = self.start(v2); await run_job(new_run)
        comparison = self.repo.compare(old_run, new_run)
        self.assertEqual(len(comparison["differences"]), 2)
        added = next(x for x in comparison["differences"] if x["case_id"] == "added")
        self.assertEqual((added["left_status"], added["right_status"]), ("missing", "passed"))
        self.assertEqual(self.repo.runs()["items"][0]["dataset_name"], "Expanded")

    async def test_reviewed_calculation_keeps_exact_values_and_date_periods(self):
        from integration_tests.test_knowledge_figures import FigureTests
        from src.knowledge.figures import FigureRepository
        self.figures = FigureRepository()
        await FigureTests.source(self)
        figure = self.figures.create(self.collection["id"], FigureTests.inputs(self))
        _, version = self.publish([self.case(target="calculation", collection_id=self.collection["id"], calculation={"operation":"convert","figure_ids":[figure["id"]],"target_unit":"millions"}, expected={"number":{"value":"0.1","tolerance":"0","currency":"CNY","unit":"millions","period_start":"2026-01-01","period_end":"2026-06-30"}})])
        key = self.start(version); await run_job(key)
        result = self.repo.detail(key)
        self.assertEqual(result["status"], "complete", str(result))
        self.assertEqual(result["summary"]["counts"]["passed"], 1, str(result["attempts"]))
        self.assertEqual(result["attempts"][0]["calculation"]["period_end"], "2026-06-30")

    async def test_page_budget_and_concurrent_runs(self):
        doc=self.material("Synthetic source");await self.build(doc)
        _,version=self.publish()
        with self.assertRaises(StateConflict):self.start(version,max_pages=1)
        keys=[self.start(version),self.start(version)]
        await asyncio.gather(*(run_job(key) for key in keys))
        self.assertTrue(all(self.repo.detail(key)["status"]=="complete" for key in keys))
        self.assertNotEqual(self.repo.detail(keys[0])["attempts"][0]["id"],self.repo.detail(keys[1])["attempts"][0]["id"])

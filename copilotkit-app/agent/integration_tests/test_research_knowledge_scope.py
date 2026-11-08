"""Submission-time snapshots on real isolated PostgreSQL; synthetic text, no provider calls."""
import os
import unittest
from uuid import uuid4
from unittest.mock import patch

from sqlalchemy import select,func
import integration_tests.test_knowledge_search as search_cases
from src.persistence.database import transaction
from src.persistence.jobs import JobRepository,StateConflict
from src.persistence.models import Job,Outbox,Document,DocumentReference
from src.research_models import ResearchConfig
from src.knowledge.contracts import MembershipChange
from src.knowledge.research_scope import collect_research_documents,merge_document_evidence


@unittest.skipUnless(os.getenv("APERTURE_RUN_INTEGRATION")=="1","Requires isolated PostgreSQL")
class ResearchKnowledgeTests(unittest.IsolatedAsyncioTestCase):
    setUpClass=classmethod(search_cases.SearchTests.setUpClass.__func__)
    tearDownClass=classmethod(search_cases.SearchTests.tearDownClass.__func__)
    setUp=search_cases.SearchTests.setUp
    material=search_cases.SearchTests.material
    build=search_cases.SearchTests.build

    def config(self):return ResearchConfig(knowledge_collection_ids=[self.collection["id"]],question="cash flow",as_of="2026-10-31")
    def submit(self):
        raw=self.config().model_dump(mode="json");raw["_knowledge_snapshot"]={"spoofed":True}
        key=JobRepository().create_job("Synthetic pinned research",raw)
        with transaction() as db:return key,db.get(Job,key).config["_knowledge_snapshot"]

    async def test_snapshot_is_atomic_server_owned_and_does_not_expand_with_collection(self):
        original=self.material("Synthetic cash flow disclosure, 100 original units.")
        future=self.material("Synthetic cash flow FUTURE EXCLUDED","2026-11-01")
        for key in (original,future):await self.build(key)
        job,snapshot=self.submit()
        self.assertNotIn("spoofed",snapshot)
        self.assertEqual(snapshot["eligible_count"],1)
        added=self.material("Synthetic cash flow LATER ADDITION MUST NOT LEAK");await self.build(added)
        current=self.collections.detail(self.collection["id"])
        self.collections.members(current["id"],MembershipChange(expected_revision=current["revision"],action="remove",document_ids=[original]))
        result=await collect_research_documents(self.config(),snapshot,job)
        self.assertEqual({hit["document_id"] for hit in result["hits"]},{original})
        self.assertTrue(any("excluded at submission" in gap for gap in result["gaps"]))
        evidence=merge_document_evidence({"sources":[{"id":"S1"}],"gaps":[]},result)
        source=evidence["sources"][1]
        self.assertEqual(source["id"],"S2")
        self.assertEqual(source["document_id"],original)
        self.assertIn("/evidence/",source["url"])
        self.assertEqual(evidence["knowledge_scope"],snapshot)
        with transaction() as db:
            self.assertTrue(db.scalar(select(func.count()).select_from(Outbox).where(Outbox.aggregate_id==job)))
            self.assertTrue(db.scalar(select(func.count()).select_from(DocumentReference).where(DocumentReference.owner_id==job)))

    async def test_changed_metadata_and_archive_are_excluded_without_rebinding(self):
        original=self.material("Synthetic cash flow original.");await self.build(original)
        job,snapshot=self.submit()
        with transaction() as db:db.get(Document,original).metadata_revision+=1
        changed=await collect_research_documents(self.config(),snapshot,job)
        self.assertEqual(changed["hits"],[])
        self.assertTrue(any("changed after submission" in gap for gap in changed["gaps"]))
        with transaction() as db:db.get(Document,original).archived=True
        archived=await collect_research_documents(self.config(),snapshot,job)
        self.assertEqual(archived["hits"],[])
        with self.assertRaises(StateConflict):await collect_research_documents(self.config(),None,job)

    async def test_empty_scope_refuses_job_and_outbox_and_unselected_scope_is_ignored(self):
        with transaction() as db:before=db.scalar(select(func.count()).select_from(Job))
        with self.assertRaises(StateConflict):self.submit()
        with transaction() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Job)),before)
        config=ResearchConfig().model_dump(mode="json");config["_knowledge_snapshot"]={"spoofed":True}
        key=JobRepository().create_job("Synthetic ordinary research",config)
        with transaction() as db:self.assertNotIn("_knowledge_snapshot",db.get(Job,key).config)

    async def test_worker_receives_pinned_scope_and_export_keeps_source_identity(self):
        original=self.material("Synthetic cash flow disclosure.");await self.build(original)
        key,snapshot=self.submit()
        from src.jobs.runner import run_job
        from src.research_store import save_report
        from src.research_exports import markdown
        async def execute(config,*,report_id,knowledge_snapshot):
            self.assertEqual(knowledge_snapshot,snapshot)
            evidence=merge_document_evidence({"sources":[],"gaps":[]},await collect_research_documents(config,knowledge_snapshot,report_id))
            report={"id":report_id,"symbol":config.symbol,"as_of":str(config.as_of),"created_at":snapshot["pinned_at"],"config":config.model_dump(mode="json"),"status":"complete","assessment":{},"findings":{},"stages":[],"evidence":evidence}
            exported=markdown(report)
            for expected in [original,"/evidence/","metadata",snapshot["pinned_at"]]:self.assertIn(expected,exported)
            save_report(report)
            return report
        with patch("src.research_workflow.execute_research",execute):
            self.assertEqual((await run_job(key))["status"],"complete")
        self.assertEqual(JobRepository().task_detail(key)["knowledge_scope"],snapshot)

"""Real PostgreSQL extraction/review state; synthetic model output only."""
import asyncio
from datetime import datetime,timedelta,timezone
import json
import os
import unittest
from unittest.mock import AsyncMock,patch

from langchain_core.messages import AIMessage
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func,select
import integration_tests.test_graphs as graph_cases
from src.graphs.contracts import (ExtractionOptions,ExtractionStart,GraphEdit,IdentityResolution,ResolveCandidate,RevisionInput)
from src.graphs.extraction import ExtractionRepository,exact_evidence
from src.graphs.repository import GraphRepository
from src.graphs.api import router
from src.jobs.runner import run_job
from src.knowledge.contracts import ScopeRequest
from src.persistence.database import transaction
from src.persistence.jobs import JobRepository,StateConflict
from src.persistence.models import Document,GraphEntity,GraphExtractionCandidate,GraphExtractionUnit,GraphRelation,Job


def output(**changes):
    value={"source":{"name":"Synthetic Alpha group","kind":"group","aliases":[],"symbols":[],"quote":"Synthetic Alpha group","identity_uncertain":False},
        "target":{"name":"Synthetic Alpha brand","kind":"brand","aliases":[],"symbols":[],"quote":"Synthetic Alpha brand","identity_uncertain":False},
        "relation_type":"owns","assertion":"disclosed","valid_from":"2026-10-01","valid_until":None,
        "explanation":"Synthetic fixture relationship only","quote":"Synthetic Alpha group owns Synthetic Alpha brand."}
    return {**value,**changes}


def message(relations=None):
    return AIMessage(content=json.dumps({"relations":[output()] if relations is None else relations}),
        usage_metadata={"input_tokens":100,"output_tokens":50,"total_tokens":150})


@unittest.skipUnless(os.getenv("APERTURE_RUN_INTEGRATION")=="1","Requires isolated PostgreSQL")
class ExtractionTests(unittest.TestCase):
    setUpClass=classmethod(graph_cases.GraphTests.setUpClass.__func__)
    tearDownClass=classmethod(graph_cases.GraphTests.tearDownClass.__func__)
    material=graph_cases.GraphTests.material
    cleanup_projection=graph_cases.GraphTests.cleanup_projection
    entity=graph_cases.GraphTests.entity

    def setUp(self):
        graph_cases.GraphTests.setUp(self)
        self.extracts=ExtractionRepository()
        for name,value in (("provider_key","synthetic-not-a-provider-key"),("model_profile",{"provider":"deepseek","model":"synthetic-only","base_url":"https://example.invalid/v1","temperature":0,"timeout":60})):
            stub=patch("src.graphs.extraction."+name,return_value=value);stub.start();self.addCleanup(stub.stop)

    def start(self,**changes):
        options=ExtractionOptions(**changes);preview=self.extracts.preview(self.key,options)
        return self.extracts.create(self.key,ExtractionStart(**options.model_dump(),plan_key=preview["plan_key"]))

    def run_with(self,row,response=None):
        model=AsyncMock(return_value=response or message())
        with patch("src.graphs.extraction.extract_segment",new=model):
            result=asyncio.run(run_job(row["job_id"]))
        return result,model

    def candidate(self):return self.extracts.candidates(self.key)["candidates"][0]

    def resolution(self,row,**changes):
        return ResolveCandidate(expected_revision=row["revision"],reason="Synthetic explicit identity review",
            source=IdentityResolution(mode="new",name="Synthetic Alpha group",kind="group"),
            target=IdentityResolution(mode="new",name="Synthetic Alpha brand",kind="brand"),
            valid_from="2026-10-01",explanation="Synthetic review only",**changes)

    def test_preview_dedup_no_auto_entities_or_publication_and_terminal_redelivery(self):
        preview=self.extracts.preview(self.key,ExtractionOptions(max_calls=1))
        self.assertEqual(preview["budget"]["max_provider_requests"],1)
        self.assertEqual(JobRepository().list_tasks(kind="knowledge"),[])
        first=self.start(max_calls=1);second=self.start(max_calls=1)
        self.assertEqual(first["job_id"],second["job_id"])
        result,model=self.run_with(first);self.assertEqual(result["status"],"complete");self.assertEqual(model.await_count,1)
        with patch("src.graphs.extraction.extract_segment",new=AsyncMock(side_effect=AssertionError("No duplicate charge"))):
            self.assertEqual(asyncio.run(run_job(first["job_id"]))["status"],"complete")
        self.assertEqual(self.start(max_calls=1)["id"],first["id"])
        with transaction() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(GraphEntity)),0)
            self.assertEqual(db.scalar(select(func.count()).select_from(GraphRelation)),0)
        candidate=self.candidate();self.assertEqual(candidate["status"],"pending")
        self.assertTrue(self.extracts.candidate(self.key,candidate["id"])["evidence_current"])

    def test_rejected_proposal_is_retained_across_explicit_rerun(self):
        first=self.start();self.run_with(first);candidate=self.candidate()
        self.extracts.reject(self.key,candidate["id"],RevisionInput(expected_revision=1,reason="Unsupported fixture"))
        rerun=self.start(force=True);self.run_with(rerun)
        self.assertEqual(self.extracts.candidates(self.key)["total"],0)
        rejected=self.extracts.candidates(self.key,status="rejected",run_id=rerun["id"])
        self.assertEqual(rejected["total"],1);self.assertEqual(rejected["candidates"][0]["id"],candidate["id"])

    def test_explicit_identity_mapping_ambiguity_and_atomic_stale_rejection(self):
        first=self.entity("Synthetic Alpha group","group");self.entity("Synthetic Alpha group","company")
        row=self.start();self.run_with(row);candidate=self.candidate();detail=self.extracts.candidate(self.key,candidate["id"])
        self.assertEqual(len(detail["identity_options"]["source"]["matches"]),2)
        inputs=self.resolution(candidate)
        inputs.source=IdentityResolution(mode="existing",entity_id=first["id"],expected_revision=99)
        with self.assertRaises(StateConflict):self.extracts.resolve(self.key,candidate["id"],inputs)
        self.assertEqual(self.repository.detail(self.key)["entity_count"],2)
        inputs.source=IdentityResolution(mode="existing",entity_id=first["id"],expected_revision=first["revision"])
        resolved=self.extracts.resolve(self.key,candidate["id"],inputs)
        self.assertEqual(resolved["status"],"resolved");self.assertEqual(resolved["relation"]["status"],"candidate")
        self.assertEqual(resolved["resolution"]["source_id"],first["id"])
        self.assertEqual(self.repository.detail(self.key)["entity_count"],3)
        with self.assertRaises(StateConflict):self.extracts.resolve(self.key,candidate["id"],inputs)

    def test_interrupted_provider_reservation_is_not_replayed_and_prior_units_survive(self):
        second=self.material(graph_cases.TEXT)
        current=self.repository.detail(self.key)
        self.repository.edit(self.key,GraphEdit(name=current["name"],scope=ScopeRequest(document_ids=[self.document,second],as_of="2026-10-31"),
            expected_revision=current["revision"],reason="Two source units"))
        row=self.start();calls=AsyncMock(side_effect=[message(),asyncio.CancelledError()])
        with patch("src.graphs.extraction.extract_segment",new=calls):
            with self.assertRaises(asyncio.CancelledError):asyncio.run(run_job(row["job_id"]))
        self.assertEqual(calls.await_count,2)
        with transaction() as db:
            job=db.get(Job,row["job_id"]);job.lease_until=datetime.now(timezone.utc)-timedelta(seconds=1)
        with patch("src.graphs.extraction.extract_segment",new=AsyncMock(side_effect=AssertionError("Unknown provider outcome must not replay"))):
            self.assertEqual(asyncio.run(run_job(row["job_id"]))["status"],"failed")
        detail=self.extracts.detail(self.key,row["id"])
        self.assertEqual(detail["result"]["completed_units"],1);self.assertEqual(detail["result"]["unknown_outcomes"],1)
        self.assertEqual(self.extracts.candidates(self.key)["total"],1)

    def test_invalid_quote_partial_results_and_timeout_feedback(self):
        row=self.start();result,_=self.run_with(row,message([output(),output(quote="Forged financial evidence")]))
        self.assertEqual(result["status"],"failed");self.assertEqual(self.extracts.candidates(self.key)["total"],1)
        detail=self.extracts.detail(self.key,row["id"])
        self.assertEqual(detail["units"][0]["result"]["invalid_proposals"],1)
        timed=self.start(force=True)
        with patch("src.graphs.extraction.extract_segment",new=AsyncMock(side_effect=TimeoutError())):
            self.assertEqual(asyncio.run(run_job(timed["job_id"]))["status"],"failed")
        self.assertEqual(self.extracts.detail(self.key,timed["id"])["result"]["unknown_outcomes"],1)

    def test_scope_change_blocks_stale_preview_and_inflight_results(self):
        options=ExtractionOptions();preview=self.extracts.preview(self.key,options)
        with transaction() as db:db.get(Document,self.document).metadata_revision+=1
        with self.assertRaises(StateConflict):self.extracts.create(self.key,ExtractionStart(**options.model_dump(),plan_key=preview["plan_key"]))
        row=self.start()
        async def archive(*args):
            from src.documents.repository import DocumentRepository
            DocumentRepository().archive(self.document);return message()
        with patch("src.graphs.extraction.extract_segment",side_effect=archive):
            self.assertEqual(asyncio.run(run_job(row["job_id"]))["status"],"failed")
        self.assertEqual(self.extracts.candidates(self.key)["total"],0)

    def test_budget_coverage_cancel_and_no_answer_do_not_invent_relations(self):
        with transaction() as db:
            from src.persistence.models import DocumentPage
            db.get(DocumentPage,(self.document,2)).text=graph_cases.TEXT*30
        preview=self.extracts.preview(self.key,ExtractionOptions(max_calls=1,characters_per_call=1000))
        self.assertGreater(preview["coverage"]["deferred_units"],0)
        row=self.start(max_calls=1,characters_per_call=1000)
        JobRepository().cancel(row["job_id"])
        with patch("src.graphs.extraction.extract_segment",new=AsyncMock(side_effect=AssertionError("Cancelled job must not call provider"))):
            self.assertEqual(asyncio.run(run_job(row["job_id"]))["status"],"cancelled")
        fresh=self.start(max_calls=1,characters_per_call=1000);result,_=self.run_with(fresh,message([]))
        self.assertEqual(result["status"],"complete");self.assertEqual(self.extracts.candidates(self.key)["total"],0)

    def test_quote_matching_preserves_original_newlines_unicode_and_rejects_ambiguity(self):
        source={"document_id":self.document,"page_number":2,"start_offset":50}
        text="😀集团\r\n制造商 owns 品牌。"
        evidence=exact_evidence(source,text,"制造商 owns 品牌。")
        self.assertEqual(evidence.start_offset,55);self.assertEqual(evidence.quote,"制造商 owns 品牌。")
        with self.assertRaises(ValueError):exact_evidence(source,"Same Same","Same")

    def test_http_preview_start_origin_budget_and_extra_model_fields(self):
        app=FastAPI();app.include_router(router);client=TestClient(app)
        base="/research/graphs/"+self.key+"/extractions"
        options=ExtractionOptions(max_calls=1).model_dump(mode="json")
        self.assertEqual(client.post(base+"/preview",json=options,headers={"origin":"https://untrusted.invalid"}).status_code,403)
        self.assertEqual(client.post(base+"/preview",json={**options,"max_calls":21}).status_code,422)
        self.assertEqual(client.post(base+"/preview",json={**options,"base_url":"https://untrusted.invalid"}).status_code,422)
        preview=client.post(base+"/preview",json=options);self.assertEqual(preview.status_code,200)
        created=client.post(base,json={**options,"plan_key":preview.json()["plan_key"]});self.assertEqual(created.status_code,201)
        detail=client.get(base+"/"+created.json()["id"]);self.assertEqual(detail.status_code,200)
        self.assertEqual(detail.json()["status"],"queued")

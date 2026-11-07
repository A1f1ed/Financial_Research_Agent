"""Isolated PostgreSQL authority and real Neo4j paths; synthetic claims only."""
import asyncio
from datetime import date
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
import integration_tests.test_knowledge_search as materials
from src.documents.repository import DocumentRepository
from src.graphs.api import router
from src.graphs.contracts import (EntityInput, EntityEdit, EvidenceInput, GraphInput, GraphEdit, GraphQueryInput,
    RelationInput, RelationEdit, ReviewInput, RevisionInput)
from src.graphs.projection import driver, query_graph, queue_projection, saved_queries
from src.graphs.repository import GraphRepository
from src.jobs.runner import run_job
from src.knowledge.contracts import ScopeRequest
from src.persistence.database import transaction
from src.persistence.jobs import JobRepository, MissingRecord, StateConflict
from src.persistence.models import Document, GraphProjection, Job

TEXT="Synthetic Alpha group owns Synthetic Alpha brand. The synthetic policy applies to the brand. This fixture is not a real financial fact."


@unittest.skipUnless(os.getenv("APERTURE_RUN_INTEGRATION")=="1","Requires isolated PostgreSQL and real local Neo4j")
class GraphTests(unittest.TestCase):
    setUpClass=classmethod(materials.SearchTests.setUpClass.__func__)
    tearDownClass=classmethod(materials.SearchTests.tearDownClass.__func__)
    material=materials.SearchTests.material

    def setUp(self):
        materials.SearchTests.setUp(self)
        self.repository=GraphRepository(); self.projections=[]
        self.addCleanup(self.cleanup_projection)
        self.document=self.material(TEXT)
        self.evidence=EvidenceInput(document_id=self.document,page_number=2,start_offset=0,end_offset=len(TEXT),quote=TEXT)
        self.graph=self.repository.create(GraphInput(name="Synthetic graph only",scope=ScopeRequest(collection_ids=[self.collection["id"]],as_of="2026-10-31")))
        self.key=self.graph["id"]

    def cleanup_projection(self):
        if not self.projections: return
        with driver() as client:
            client.execute_query("MATCH (n:ApertureEntity) WHERE n.projection_id IN $ids DETACH DELETE n",ids=self.projections,database_="neo4j")

    def entity(self,name,kind="company",evidence=None):
        return self.repository.save_entity(self.key,EntityInput(name=name,kind=kind,evidence=[evidence or self.evidence]))

    def relation(self,source,target,**kwargs):
        return self.repository.save_relation(self.key,RelationInput(source_id=source["id"],target_id=target["id"],
            relation_type="owns",assertion="disclosed",valid_from="2026-10-01",explanation="Synthetic fixture source only",evidence=[self.evidence],**kwargs))

    def accept(self,row):
        return self.repository.review(self.key,row["id"],ReviewInput(expected_revision=row["revision"],reason="Synthetic review",action="accept"))

    def enqueue(self,force=False):
        row=queue_projection(self.key,force=force); self.projections.append(row["id"]); return row

    def sync(self,force=False):
        row=self.enqueue(force)
        self.assertEqual(asyncio.run(run_job(row["job_id"]))["status"],"complete")
        return row

    def query(self,entity,**kwargs):
        return query_graph(self.key,GraphQueryInput(entity_id=entity["id"],as_of="2026-10-31",**kwargs))

    def test_exact_evidence_fixed_scope_and_distinct_identity(self):
        group=self.entity("Synthetic Alpha","group"); company=self.entity("Synthetic Alpha","company")
        self.assertNotEqual(group["id"],company["id"])
        invalid=self.evidence.model_copy(update={"quote":"Made up claim"})
        with self.assertRaises(StateConflict): self.entity("Forged",evidence=invalid)
        later=self.material(TEXT)
        outside=self.evidence.model_copy(update={"document_id":later})
        with self.assertRaises(StateConflict): self.entity("Silently added source",evidence=outside)
        other=self.repository.create(GraphInput(name="Another graph",scope=ScopeRequest(document_ids=[later],as_of="2026-10-31")))
        with self.assertRaises(MissingRecord): self.repository.entity(other["id"],company["id"])
        future=self.material(TEXT,"2026-11-01",add=False)
        current=self.repository.detail(self.key)
        self.repository.edit(self.key,GraphEdit(name=current["name"],scope=ScopeRequest(document_ids=[future],as_of="2026-10-31"),
            expected_revision=current["revision"],reason="Switch to future source"))
        with self.assertRaises(StateConflict): self.entity("Future",evidence=self.evidence.model_copy(update={"document_id":future}))

    def test_review_rejection_dedup_and_revision_conflict(self):
        one,two=self.entity("One"),self.entity("Two","brand")
        row=self.relation(one,two)
        rejected=self.repository.review(self.key,row["id"],ReviewInput(expected_revision=1,reason="Not supported",action="reject"))
        duplicate=self.relation(one,two)
        self.assertEqual(duplicate["id"],rejected["id"]); self.assertEqual(duplicate["status"],"rejected")
        with self.assertRaises(StateConflict): self.accept(row)
        revised=self.repository.save_relation(self.key,RelationEdit(source_id=one["id"],target_id=two["id"],relation_type="owns",assertion="disclosed",
            valid_from="2026-10-01",explanation="Clarified source",evidence=[self.evidence],expected_revision=rejected["revision"],reason="Explicit reconsideration"),row["id"])
        accepted=self.accept(revised)
        self.assertEqual(accepted["status"],"accepted")
        self.assertEqual(self.repository.history(self.key,row["id"])["total"],4)
        with self.assertRaises(StateConflict): self.repository.review(self.key,row["id"],ReviewInput(expected_revision=revised["revision"],reason="Stale browser",action="revoke"))

    def test_missing_time_changed_metadata_and_inference_never_promoted(self):
        one,two=self.entity("One"),self.entity("Two","region")
        row=self.repository.save_relation(self.key,RelationInput(source_id=one["id"],target_id=two["id"],relation_type="may_affect",assertion="inferred",
            explanation="Hypothesis, not disclosure",evidence=[self.evidence]))
        with self.assertRaises(StateConflict): self.accept(row)
        with self.assertRaises(ValidationError): RelationInput(source_id=one["id"],target_id=two["id"],relation_type="may_affect",assertion="disclosed",explanation="Wrong",evidence=[self.evidence])
        with self.assertRaises(StateConflict): self.repository.save_relation(self.key,RelationEdit(source_id=one["id"],target_id=two["id"],relation_type="owns",assertion="disclosed",
            explanation="Cannot relabel",evidence=[self.evidence],expected_revision=1,reason="Forbidden reclassification"),row["id"])
        direct=self.relation(one,two)
        with transaction() as db: db.get(Document,self.document).metadata_revision+=1
        with self.assertRaises(StateConflict): self.accept(direct)

    def test_real_two_hop_sync_revoke_and_retained_snapshot(self):
        one,two,three=self.entity("One"),self.entity("Two","brand"),self.entity("Three","region")
        first=self.accept(self.relation(one,two)); self.accept(self.relation(two,three))
        queued=self.enqueue(); self.assertEqual(self.enqueue()["job_id"],queued["job_id"])
        self.assertEqual(asyncio.run(run_job(queued["job_id"]))["status"],"complete")
        result=self.query(one,max_hops=2,name="Synthetic two-hop query")
        self.assertEqual(len(result["nodes"]),3); self.assertEqual(len(result["edges"]),2)
        self.assertTrue(any(len(path["edges"])==2 for path in result["paths"]))
        self.assertEqual(self.enqueue()["job_id"],queued["job_id"])
        self.repository.review(self.key,first["id"],ReviewInput(expected_revision=first["revision"],reason="Withdraw unsupported claim",action="revoke"))
        with self.assertRaises(StateConflict): self.query(one,max_hops=2)
        self.sync(); new=self.query(one,max_hops=2)
        self.assertEqual(new["edges"],[])
        old=saved_queries(self.key,query_id=result["id"])
        self.assertTrue(old["historical"]); self.assertEqual(len(old["snapshot"]["edges"]),2)

    def test_inference_effective_dates_and_archived_sources_filter_real_paths(self):
        one,two=self.entity("One"),self.entity("Two","policy")
        inputs=RelationInput(source_id=one["id"],target_id=two["id"],relation_type="may_affect",assertion="inferred",
            valid_from="2026-10-30",explanation="Unverified impact hypothesis",evidence=[self.evidence])
        edge=self.accept(self.repository.save_relation(self.key,inputs)); self.sync()
        self.assertEqual(self.query(one)["edges"],[])
        self.assertEqual(len(self.query(one,include_inferred=True)["edges"]),1)
        self.assertEqual(self.query(one,include_inferred=True,valid_on=date(2026,10,29))["edges"],[])
        saved=self.query(one,include_inferred=True)
        DocumentRepository().archive(self.document)
        with self.assertRaises(StateConflict): self.query(one,include_inferred=True)
        self.assertEqual(saved_queries(self.key,query_id=saved["id"])["snapshot"]["edges"][0]["id"],edge["id"])

    def test_projection_failure_stale_build_and_rebuild_preserve_publication(self):
        one,two=self.entity("One"),self.entity("Two")
        self.accept(self.relation(one,two)); original=self.sync()
        failed=self.enqueue(force=True)
        with patch("src.graphs.projection.write_projection",side_effect=RuntimeError("Synthetic connection failure")):
            self.assertEqual(asyncio.run(run_job(failed["job_id"]))["status"],"failed")
        self.assertEqual(self.repository.detail(self.key)["projection_id"],original["id"])
        self.assertEqual(len(self.query(one)["edges"]),1)
        stale=self.enqueue(force=True); self.entity("New identity")
        self.assertEqual(asyncio.run(run_job(stale["job_id"]))["status"],"failed")
        self.assertEqual(self.repository.detail(self.key)["projection_id"],original["id"])
        latest=self.sync(); self.assertNotEqual(latest["id"],original["id"])
        self.assertEqual(len(self.query(one)["edges"]),1)

    def test_slow_query_cannot_publish_after_scope_or_review_change(self):
        from src.graphs.projection import traverse
        one,two=self.entity("One"),self.entity("Two")
        edge=self.accept(self.relation(one,two)); self.sync()
        def changing(*args):
            result=traverse(*args)
            self.repository.review(self.key,edge["id"],ReviewInput(expected_revision=edge["revision"],reason="Concurrent revoke",action="revoke"))
            return result
        with patch("src.graphs.projection.traverse",side_effect=changing):
            with self.assertRaises(StateConflict): self.query(one)
        self.assertEqual(saved_queries(self.key)["total"],0)

    def test_identity_revision_requires_relationship_review_and_page_changes_block_queries(self):
        from src.graphs.projection import traverse
        from src.persistence.models import DocumentPage
        one,two=self.entity("One"),self.entity("Two")
        edge=self.accept(self.relation(one,two));self.sync()
        def changing_page(*args):
            result=traverse(*args)
            with transaction() as db: db.get(DocumentPage,(self.document,2)).text="Changed extraction without a metadata edit"
            return result
        with patch("src.graphs.projection.traverse",side_effect=changing_page):
            with self.assertRaises(StateConflict): self.query(one)
        self.assertEqual(saved_queries(self.key)["total"],0)
        with transaction() as db: db.get(DocumentPage,(self.document,2)).text=TEXT
        self.repository.save_entity(self.key,EntityEdit(name="One corrected",kind="company",evidence=[self.evidence],
            expected_revision=one["revision"],reason="Correct identity"),one["id"])
        current=self.repository.relation(self.key,edge["id"])
        self.assertEqual(current["status"],"candidate")
        self.assertEqual(current["revision"],edge["revision"]+1)
        with self.assertRaises(StateConflict): self.query(one)

    def test_http_origin_uuid_bounds_and_archived_history(self):
        app=FastAPI(); app.include_router(router); client=TestClient(app)
        self.assertEqual(client.post("/research/graphs",json={},headers={"origin":"https://untrusted.invalid"}).status_code,422)
        payload=GraphInput(name="Browser graph",scope=ScopeRequest(document_ids=[self.document],as_of="2026-10-31")).model_dump(mode="json")
        self.assertEqual(client.post("/research/graphs",json=payload,headers={"origin":"https://untrusted.invalid"}).status_code,403)
        self.assertEqual(client.get("/research/graphs/not-a-uuid").status_code,422)
        self.assertEqual(client.get("/research/graphs?page_size=101").status_code,422)
        current=self.repository.detail(self.key)
        self.repository.archive(self.key,RevisionInput(expected_revision=current["revision"],reason="Synthetic cleanup"))
        self.assertEqual(self.repository.history(self.key)["total"],2)
        with self.assertRaises(StateConflict): self.entity("Archived mutation")
        self.assertTrue(client.get("/research/graphs/"+self.key).json()["archived"])

    def test_path_limit_is_explicit_and_does_not_persist_over_limit(self):
        one,two=self.entity("One"),self.entity("Two")
        edge=self.accept(self.relation(one,two));self.sync()
        path={"nodes":[one["id"],two["id"]],"edges":[edge["id"]]}
        with patch("src.graphs.projection.traverse",return_value=[path]*1001):
            result=self.query(one)
        self.assertTrue(result["truncated"]);self.assertEqual(len(result["paths"]),1000)
        self.assertEqual(len(saved_queries(self.key,query_id=result["id"])["snapshot"]["paths"]),1000)

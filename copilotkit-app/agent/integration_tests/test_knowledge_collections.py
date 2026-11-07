"""Metadata-plane behavior on an isolated PostgreSQL database; no model calls.

These fixtures register synthetic document metadata only. Actual byte storage,
browser uploads and extraction are exercised separately in test_documents.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import os
import unittest
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from tests.postgres_fixture import postgres_fixture
from src.documents.api import router as document_router
from src.documents.contracts import MetadataUpdate, UploadMetadata
from src.documents.repository import DocumentRepository
from src.knowledge.api import router
from src.knowledge.contracts import CollectionEdit, CollectionInput, MembershipChange, ScopeRequest
from src.knowledge.repository import CollectionRepository
from src.persistence.database import transaction
from src.persistence.jobs import StateConflict
from src.persistence.models import Base, CollectionMember, Document, DocumentReference, Job


@unittest.skipUnless(os.getenv("APERTURE_RUN_INTEGRATION") == "1", "Requires explicit isolated PostgreSQL test run")
class CollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = postgres_fixture(); cls.bind = cls.fixture.__enter__()

    @classmethod
    def tearDownClass(cls): cls.fixture.__exit__(None, None, None)

    def setUp(self):
        with self.bind.begin() as connection:
            tables = ", ".join('research."' + table.name + '"' for table in Base.metadata.sorted_tables)
            connection.execute(text("TRUNCATE " + tables + " RESTART IDENTITY"))
        self.repository, self.documents = CollectionRepository(), DocumentRepository()
        app = FastAPI(); app.include_router(router); app.include_router(document_router)
        self.client = TestClient(app); self.addCleanup(self.client.close)

    def doc(self, **inputs):
        digest = hashlib.sha256(uuid4().bytes).hexdigest()
        result = self.documents.register(digest, "synthetic-metadata-only/"+digest,
            {"byte_size": 100, "page_count": 2, "media_type": "application/pdf"}, "synthetic.pdf",
            UploadMetadata(title="Synthetic metadata test", **inputs))
        return result["document"]["id"]

    def create(self, name="Synthetic collection"):
        return self.repository.create(CollectionInput(name=name, symbols=["01211.HK"], topics=["EV", "EV"]))

    def test_create_edit_cas_history_and_no_implicit_execution(self):
        created = self.create(); key = created["id"]
        self.assertEqual(created["symbols"], ["1211.HK"])
        self.assertEqual(created["topics"], ["EV"])
        edit = CollectionEdit(name="Reviewed collection", description="Audit test", expected_revision=1, reason="Clarify scope")
        self.assertEqual(self.repository.edit(key, edit)["revision"], 2)
        with self.assertRaises(StateConflict): self.repository.edit(key, edit)
        history = self.repository.history(key)["revisions"]
        self.assertEqual([row["revision"] for row in history], [2, 1])
        self.assertEqual(history[1]["snapshot"]["name"], "Synthetic collection")
        with transaction() as db: self.assertEqual(db.scalar(select(func.count()).select_from(Job)), 0)

    def test_members_are_exact_versions_and_collection_scope_does_not_leak(self):
        first, other = self.create(), self.create("Other company")
        one = self.doc(published_on="2026-10-30", publication_basis="Fixture only")
        two = self.doc(published_on="2026-10-30", publication_basis="Fixture only")
        self.repository.members(first["id"], MembershipChange(expected_revision=1, action="add", document_ids=[one, one]))
        self.repository.members(other["id"], MembershipChange(expected_revision=1, action="add", document_ids=[two]))
        results = self.documents.list(collection_id=first["id"])
        self.assertEqual([row["id"] for row in results["documents"]], [one])
        self.assertEqual([row["id"] for row in self.documents.list(collection_id=first["id"], outside_collection=True)["documents"]], [two])
        snapshot = self.repository.scope(ScopeRequest(collection_ids=[first["id"]], as_of="2026-10-31"))
        self.assertEqual([row["id"] for row in snapshot["documents"]], [one])
        self.assertEqual(snapshot["collections"][0]["revision"], 2)
        self.assertEqual(snapshot["semantic_index"], "not_checked")

    def test_remove_archive_restore_preserve_originals_other_collections_and_citations(self):
        first, second = self.create(), self.create("Second collection")
        document = self.doc(published_on="2026-10-30", publication_basis="Fixture")
        for value in (first, second): self.repository.members(value["id"], MembershipChange(expected_revision=1, action="add", document_ids=[document]))
        with transaction() as db: db.add(DocumentReference(id=str(uuid4()), document_id=document, owner_type="report", owner_id="synthetic", snapshot={"title":"Retained"}))
        self.assertEqual(self.repository.detail(first["id"])["coverage"]["references"], 1)
        self.repository.archive(first["id"], 2)
        with self.assertRaises(StateConflict): self.repository.scope(ScopeRequest(collection_ids=[first["id"]], as_of="2026-10-31"))
        self.assertEqual(self.repository.scope(ScopeRequest(collection_ids=[second["id"]], as_of="2026-10-31"))["eligible_count"], 1)
        self.assertFalse(self.documents.detail(document)["archived"])
        self.repository.archive(first["id"], 3, False)
        self.repository.members(first["id"], MembershipChange(expected_revision=4, action="remove", document_ids=[document]))
        self.assertEqual(self.repository.detail(first["id"])["coverage"]["documents"], 0)
        self.assertEqual(self.documents.detail(document)["reference_count"], 1)
        self.assertEqual(self.repository.detail(second["id"])["coverage"]["documents"], 1)

    def test_server_enforces_dates_unknown_precision_and_market_day_boundary(self):
        value = self.create(); key = value["id"]
        day = self.doc(collection_id=key, published_on="2026-10-31", publication_basis="Day only")
        instant = self.doc(collection_id=key, published_at="2026-11-01T03:59:59Z", publication_basis="Instant")
        unknown = self.doc(collection_id=key)
        future = self.doc(collection_id=key, published_on="2026-11-02", publication_basis="Future")
        hk = self.repository.scope(ScopeRequest(collection_ids=[key], as_of="2026-10-31", market="HK"))
        self.assertEqual(hk["eligible_count"], 1)
        self.assertEqual({row["id"]:row["exclusion"] for row in hk["documents"]}[instant], "published_after_cutoff")
        us = self.repository.scope(ScopeRequest(collection_ids=[key], as_of="2026-10-31", market="US"))
        self.assertEqual(us["eligible_count"], 2)
        exact = self.repository.scope(ScopeRequest(collection_ids=[key], as_of_at="2026-10-31T12:00:00+08:00", market="HK"))
        self.assertEqual({row["id"]:row["exclusion"] for row in exact["documents"]}[day], "publication_precision_insufficient")
        explore = self.repository.scope(ScopeRequest(collection_ids=[key], as_of="2026-10-31", mode="explore"))
        states = {row["id"]: row for row in explore["documents"]}
        self.assertTrue(states[unknown]["eligible"]); self.assertEqual(states[unknown]["warning"], "publication_unknown")
        self.assertFalse(states[future]["eligible"])

    def test_scope_fingerprint_changes_on_metadata_revision_and_archive(self):
        value = self.create(); key = value["id"]
        doc = self.doc(collection_id=key, published_on="2026-10-31", publication_basis="Fixture")
        request = ScopeRequest(collection_ids=[key], as_of="2026-10-31")
        before = self.repository.scope(request)
        material_before = self.repository.detail(key)["material_revision"]
        self.documents.update_metadata(doc, MetadataUpdate(title="New date", published_on="2026-11-01", publication_basis="Correction", reason="Corrected publication", expected_revision=1))
        after = self.repository.scope(request)
        self.assertNotEqual(before["scope_fingerprint"], after["scope_fingerprint"])
        self.assertNotEqual(material_before, self.repository.detail(key)["material_revision"])
        self.assertEqual(before["eligible_count"], 1); self.assertEqual(after["eligible_count"], 0)
        self.documents.archive(doc)
        self.assertEqual(self.repository.scope(request)["documents"][0]["exclusion"], "document_archived")

    def test_concurrent_membership_changes_have_one_winner_and_no_partial_updates(self):
        value = self.create(); first, second = self.doc(), self.doc()
        def change(document):
            try:
                CollectionRepository(self.bind).members(value["id"], MembershipChange(action="add", document_ids=[document], expected_revision=1))
                return "saved"
            except StateConflict: return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(change, [first, second]))
        self.assertCountEqual(results, ["saved", "conflict"])
        self.assertEqual(self.repository.detail(value["id"])["coverage"]["documents"], 1)
        missing = str(uuid4())
        response = self.client.post(f'/research/knowledge/collections/{value["id"]}/members', json={"action":"add","expected_revision":2,"document_ids":[first, missing]})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.repository.detail(value["id"])["revision"], 2)

    def test_collection_list_pagination_filters_and_read_projection(self):
        self.create("Named_100% collection"); self.create("Another collection")
        self.assertEqual(self.repository.list(query="_100%")["total"], 1)
        self.assertEqual(len(self.repository.list(page=2, page_size=1)["collections"]), 1)
        result = self.client.get('/research/knowledge/collections?page_size=1').json()
        self.assertNotIn("object_key", result["collections"][0])
        self.assertEqual(result["collections"][0]["coverage"]["text_pages"], 0)
        self.assertEqual(self.client.post('/research/knowledge/collections', headers={"Origin":"https://untrusted.example"}, json={"name":"Rejected"}).status_code, 403)
        self.assertEqual(self.client.post('/research/knowledge/scope', json={"collection_ids":[str(uuid4())],"as_of":"2026-10-31"}).status_code, 404)


if __name__ == "__main__": unittest.main()

"""Real PG/pgvector and leased jobs; synthetic source text/vectors only.

Provider mocks test failure/dimension boundaries, never claim live quality.
Browser verification separately uses retained official PDF originals.
"""
import asyncio
import hashlib
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import func, select, text
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.postgres_fixture import postgres_fixture
from src.documents.contracts import UploadMetadata
from src.documents.repository import DocumentRepository
from src.knowledge.chunks import page_chunks
from src.knowledge.contracts import CollectionInput, IndexRequest, MembershipChange, SearchRequest
from src.knowledge.embeddings import EmbeddingSettings, settings, validate_vectors, verification_key
from src.knowledge import embeddings
from src.knowledge.api import router
from src.knowledge.indexing import IndexRepository
from src.knowledge.repository import CollectionRepository
from src.knowledge.retrieval import search, search_detail
from src.jobs.runner import run_job
from src.persistence.business import BusinessRepository
from src.persistence.database import database_override, transaction
from src.persistence.jobs import JobRepository, StateConflict
from src.persistence.models import Base, Document, DocumentPage, DocumentReference, Job, KnowledgeChunk, KnowledgeIndex


@unittest.skipUnless(os.getenv("APERTURE_RUN_INTEGRATION") == "1", "Requires isolated PostgreSQL integration run")
class SearchTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = postgres_fixture(); cls.bind = cls.fixture.__enter__()

    @classmethod
    def tearDownClass(cls): cls.fixture.__exit__(None, None, None)

    def setUp(self):
        # IsolatedAsyncioTestCase has its own Context: a class-level ContextVar
        # override does not propagate into async methods.
        token = database_override.set(self.bind)
        self.addCleanup(database_override.reset, token)
        with self.bind.begin() as db:
            db.execute(text("TRUNCATE " + ", ".join('research."'+table.name+'"' for table in Base.metadata.sorted_tables) + " RESTART IDENTITY"))
        self.collections = CollectionRepository(); self.indices = IndexRepository()
        self.collection = self.collections.create(CollectionInput(name="Synthetic retrieval fixtures"))

    def material(self, content, publication="2026-10-29", add=True, status="text_ready"):
        digest = hashlib.sha256(uuid4().bytes).hexdigest()
        stored = DocumentRepository().register(digest, "synthetic-only/"+digest,
            {"byte_size": 100, "page_count": 2, "media_type": "application/pdf"}, "synthetic.pdf",
            UploadMetadata(title="Synthetic evidence " + digest[:6], published_on=publication, publication_basis="Synthetic fixture date" if publication else ""))
        key = stored["document"]["id"]
        with transaction() as db:
            doc = db.get(Document, key); doc.status = "ready"
            db.get(Job, stored["job_id"]).status = "complete"
            db.add(DocumentPage(document_id=key, page_number=2, width=100, height=100, text=content,
                status=status, extraction_version="synthetic-test-v1", text_object_key="synthetic-not-a-real-object"))
        if add:
            value = self.collections.detail(self.collection["id"])
            self.collections.members(value["id"], MembershipChange(expected_revision=value["revision"], action="add", document_ids=[key]))
        return key

    async def build(self, key, mode="keyword", force=False):
        row = self.indices.create(IndexRequest(document_ids=[key], mode=mode, force=force))["indices"][0]
        await run_job(row["job_id"])
        return row

    def request(self, query="经营现金流", **overrides):
        return SearchRequest(collection_ids=[self.collection["id"]], as_of="2026-10-31", query=query, **overrides)

    async def test_keyword_dates_scope_and_retained_exact_citations(self):
        inside = self.material("合成资料：经营现金流与净利润需要分别核验。\nOperating cash flow must be checked separately.")
        future = self.material("经营现金流 FUTURE MUST NOT LEAK", "2026-11-01")
        unrelated = self.material("经营现金流 OTHER COLLECTION MUST NOT LEAK", add=False)
        for key in (inside, future, unrelated): await self.build(key)
        with patch("src.knowledge.retrieval.embed", new=AsyncMock(side_effect=AssertionError("Keyword search must not call a model"))):
            found = await search(self.request())
        self.assertEqual([hit["document_id"] for hit in found["hits"]], [inside])
        self.assertEqual(found["hits"][0]["page_number"], 2)
        self.assertEqual(found["scope"]["excluded_count"], 1)
        english = await search(self.request("operating cash flow"))
        self.assertEqual(english["hits"][0]["document_id"], inside)
        before = search_detail(found["id"])
        DocumentRepository().archive(inside)
        after = await search(self.request())
        self.assertEqual(after["hits"], [])
        self.assertEqual(search_detail(found["id"]), before)
        with transaction() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(DocumentReference).where(DocumentReference.owner_id == found["id"])), 1)

    async def test_atomic_rebuild_failure_and_cancel_keep_current_index(self):
        key = self.material("Synthetic cash flow disclosure")
        first = await self.build(key)
        second = self.indices.create(IndexRequest(document_ids=[key], force=True))["indices"][0]
        with patch("src.knowledge.indexing.page_chunks", side_effect=ValueError("Synthetic parsing failure")):
            self.assertEqual((await run_job(second["job_id"]))["status"], "failed")
        third = self.indices.create(IndexRequest(document_ids=[key], force=True))["indices"][0]
        JobRepository().cancel(third["job_id"])
        self.assertEqual((await run_job(third["job_id"]))["status"], "cancelled")
        with transaction() as db:
            self.assertTrue(db.get(KnowledgeIndex, first["id"]).published)
            self.assertFalse(db.get(KnowledgeIndex, second["id"]).published)
            self.assertEqual(db.scalar(select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.index_id == second["id"])), 0)
        fourth = await self.build(key, force=True)
        with transaction() as db:
            self.assertFalse(db.get(KnowledgeIndex, first["id"]).published)
            self.assertTrue(db.get(KnowledgeIndex, fourth["id"]).published)
        self.assertEqual((await run_job(fourth["job_id"]))["status"], "complete")

    async def test_concurrent_build_dedup_and_no_half_batch_enqueue(self):
        key = self.material("Synthetic revenue evidence")
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(lambda _: IndexRepository(self.bind).create(IndexRequest(document_ids=[key])), range(2)))
        self.assertEqual(rows[0]["indices"][0]["job_id"], rows[1]["indices"][0]["job_id"])
        other = self.material("Second synthetic source")
        DocumentRepository().archive(other)
        with self.assertRaises(StateConflict): self.indices.create(IndexRequest(document_ids=[key, other]))
        with transaction() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Job).where(Job.kind == "knowledge")), 1)

    async def test_pgvector_hybrid_profile_isolation_and_late_scope_change(self):
        config = EmbeddingSettings(dimensions=64).model_dump()
        BusinessRepository().write_settings({"embedding": config})
        with patch("src.knowledge.embeddings.credential", return_value="synthetic-test-key"):
            BusinessRepository().write_settings({"embedding:test": {"verification_key": verification_key(config), "status": "success"}})
            key = self.material("Synthetic battery margin evidence")
            fake = AsyncMock(return_value=([[1.0]+[0.0]*63], 7))
            with patch("src.knowledge.indexing.embed", fake): await self.build(key, "hybrid")
            with patch("src.knowledge.retrieval.embed", fake):
                result = await search(self.request("profitability", search_mode="hybrid"))
            self.assertEqual(result["hits"][0]["channels"]["semantic"]["value"], 0)
            self.assertEqual(result["embedding_tokens"], 7)
            async def archive_while_embedding(*args, **kwargs):
                DocumentRepository().archive(key)
                return ([[1.0]+[0.0]*63], 7)
            with patch("src.knowledge.retrieval.embed", side_effect=archive_while_embedding):
                with self.assertRaises(StateConflict): await search(self.request("profitability", search_mode="hybrid"))
            changed = {**config, "dimensions": 128}
            BusinessRepository().write_settings({"embedding": changed})
            with self.assertRaises(StateConflict): self.indices.create(IndexRequest(document_ids=[key], mode="hybrid"))

    async def test_unknown_dates_unindexed_and_image_gaps_are_distinct(self):
        unknown = self.material("Synthetic revenue evidence", None)
        result = await search(self.request("revenue"))
        self.assertEqual(result["scope"]["eligible_count"], 0)
        await self.build(unknown)
        explore = self.request("revenue"); explore.mode = "explore"
        result = await search(explore)
        self.assertEqual(result["hits"][0]["publication_warning"], "publication_unknown")
        known = self.material("Synthetic unindexed evidence")
        result = await search(self.request("evidence"))
        self.assertEqual(result["gaps"][0]["document_id"], known)
        image = self.material("", status="needs_vision")
        row = await self.build(image)
        self.assertEqual(JobRepository().task_detail(row["job_id"])["status"], "failed")

    async def test_embedding_configuration_test_failure_and_secret_isolation(self):
        with TemporaryDirectory() as directory:
            env = Path(directory) / ".env"; env.write_text("UNRELATED=retained\n", encoding="utf-8")
            with patch.object(embeddings, "ENV_FILE", env), patch.object(embeddings, "provider_key", return_value="synthetic-provider-key"):
                value = embeddings.save_settings(EmbeddingSettings(api_key="synthetic-dedicated-key", dimensions=64))
                self.assertNotIn("api_key", value)
                self.assertFalse(value["verified"])
                self.assertIn("UNRELATED=retained", env.read_text())
                self.assertEqual(embeddings.credential(value), "synthetic-dedicated-key")
                other = {**value, "provider": "deepseek"}
                self.assertEqual(embeddings.credential(other), "synthetic-provider-key")
                with patch.object(embeddings, "embed", new=AsyncMock(return_value=([[1.0]*64,[1.0]*64], 5))):
                    passed = await embeddings.test_settings()
                self.assertTrue(passed["verified"])
                changed = EmbeddingSettings(dimensions=128)
                self.assertFalse(embeddings.save_settings(changed)["verified"])
                with patch.object(embeddings, "embed", new=AsyncMock(side_effect=TimeoutError("Must not expose synthetic-dedicated-key"))):
                    failed = await embeddings.test_settings()
                self.assertEqual(failed["test"]["error_type"], "TimeoutError")
                self.assertNotIn("synthetic-dedicated-key", str(failed))
                self.assertFalse(failed["verified"])

    async def test_archive_during_embedding_stops_remaining_batches_and_publication(self):
        config = EmbeddingSettings(dimensions=64).model_dump()
        BusinessRepository().write_settings({"embedding": config})
        with patch("src.knowledge.embeddings.credential", return_value="synthetic-test-key"):
            BusinessRepository().write_settings({"embedding:test": {"verification_key": verification_key(config), "status": "success"}})
            key = self.material("Synthetic financial disclosure. " * 150)
            previous = await self.build(key)
            row = self.indices.create(IndexRequest(document_ids=[key], mode="hybrid"))["indices"][0]
            async def archive_mid_build(texts, *_args):
                DocumentRepository().archive(key)
                return ([[1.0]+[0.0]*63 for _ in texts], len(texts))
            with patch("src.knowledge.indexing.embed", side_effect=archive_mid_build) as mocked:
                self.assertEqual((await run_job(row["job_id"]))["status"], "failed")
            self.assertEqual(mocked.call_count, 1)
            with transaction() as db:
                self.assertTrue(db.get(KnowledgeIndex, previous["id"]).published)
                self.assertFalse(db.get(KnowledgeIndex, row["id"]).published)
                self.assertEqual(db.scalar(select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.index_id == row["id"])), 0)

    def test_http_validation_missing_records_and_write_origin(self):
        app = FastAPI(); app.include_router(router)
        with TestClient(app) as client:
            self.assertEqual(client.get('/research/knowledge/indices?document_id=invalid').status_code, 422)
            self.assertEqual(client.get('/research/knowledge/searches/'+str(uuid4())).status_code, 404)
            self.assertEqual(client.post('/research/knowledge/indices', json={'document_ids':[str(uuid4())]}).status_code, 404)
            with patch.object(embeddings, 'test_settings', new=AsyncMock(side_effect=AssertionError('Forbidden origin must not call provider'))):
                self.assertEqual(client.post('/research/knowledge/embedding/test', headers={'origin':'https://untrusted.example'}, json={}).status_code, 403)
            bad = self.request().model_dump(mode='json'); bad.update(as_of=None,as_of_at='2026-10-31T09:00:00')
            self.assertEqual(client.post('/research/knowledge/search',json=bad).status_code,422)


class ChunkAndVectorTests(unittest.TestCase):
    def test_page_offsets_no_gaps_no_cross_page_and_bounded_vectors(self):
        body = "财务表格\n" * 500
        page = SimpleNamespace(page_number=4, text=body, status="text_ready", extraction_version="test")
        chunks = page_chunks([page]); covered = set()
        for chunk in chunks:
            self.assertEqual(chunk["text"], body[chunk["start_offset"]:chunk["end_offset"]])
            self.assertLessEqual(len(chunk["text"]), 900)
            self.assertEqual(chunk["page_number"], 4)
            covered.update(range(chunk["start_offset"], chunk["end_offset"]))
        self.assertEqual(len(covered), len(body))
        for vector in ([0.0]*64, [float("nan")]*64, [1.0]*63):
            with self.assertRaises(ValueError): validate_vectors(SimpleNamespace(data=[SimpleNamespace(index=0, embedding=vector)]), 1, 64)

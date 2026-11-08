"""Real isolated PostgreSQL + S3 with newly generated, clearly synthetic files.

S3 cleanup is restricted to hashes produced by this test. The application DB,
existing documents, model endpoints and broker dispatch are never used.
"""
import asyncio
from datetime import date
import hashlib
import io
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import func, select, text

from tests.postgres_fixture import postgres_fixture
from src.documents.api import router, UploadBodyLimit
from src.documents.contracts import EXTRACTION_VERSION, MetadataUpdate, UploadMetadata
from src.documents.processing import process, store_original
from src.documents.repository import DocumentRepository
from src.infrastructure.objects import ObjectStore
from src.jobs.runner import run_job
from src.persistence.database import transaction
from src.persistence.jobs import JobRepository, StateConflict
from src.persistence.models import Base, Document, DocumentPage, DocumentReference, Job, Outbox, Report


def synthetic_pdf(pages=1):
    stream = io.BytesIO(); canvas = Canvas(stream)
    for number in range(pages):
        canvas.drawString(40, 760, f"SYNTHETIC TEST MATERIAL - NOT FINANCIAL EVIDENCE {uuid4()} page {number+1}")
        canvas.drawString(40, 730, "Revenue 100, cost 60, operating margin 40 percent. Generated fixture only.")
        canvas.showPage()
    canvas.save()
    return stream.getvalue()


@unittest.skipUnless(os.getenv("APERTURE_RUN_INTEGRATION") == "1", "Requires isolated PostgreSQL and authenticated S3")
class DocumentLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = postgres_fixture(); cls.bind = cls.fixture.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.__exit__(None, None, None)

    def setUp(self):
        with self.bind.begin() as connection:
            tables = ", ".join('research."' + table.name + '"' for table in Base.metadata.sorted_tables)
            connection.execute(text("TRUNCATE " + tables + " RESTART IDENTITY"))
        self.hashes = set()
        self.repository = DocumentRepository()
        self.jobs = JobRepository()
        application = FastAPI(); application.include_router(router); application.add_middleware(UploadBodyLimit)
        self.client = TestClient(application)
        self.addCleanup(self.client.close)
        self.addCleanup(self.clear_own_objects)

    def clear_own_objects(self):
        with ObjectStore() as objects:
            for digest in self.hashes:
                prefix = f"documents/{digest}/"
                for page in objects.client.get_paginator("list_objects_v2").paginate(Bucket=objects.settings.s3_bucket, Prefix=prefix):
                    for item in page.get("Contents", []):
                        self.assertTrue(item["Key"].startswith(prefix))
                        objects.delete(item["Key"])

    def store(self, body=None, **metadata):
        body = body or synthetic_pdf()
        self.hashes.add(hashlib.sha256(body).hexdigest())
        return store_original(body, "test-report.pdf", UploadMetadata(title="Synthetic test report", **metadata))

    def test_upload_to_real_objects_process_preview_and_idempotent_redelivery(self):
        body = synthetic_pdf(2); self.hashes.add(hashlib.sha256(body).hexdigest())
        response = self.client.post("/research/documents/upload", files={"file": ("test.pdf", body, "application/pdf")},
                                    data={"metadata": json.dumps({"title": "Synthetic upload"})})
        self.assertEqual(response.status_code, 202, response.text)
        stored = response.json(); key, job = stored["document"]["id"], stored["job_id"]
        with transaction() as db:
            self.assertEqual(db.scalar(select(Outbox.topic).where(Outbox.aggregate_id == job)), "document.execute")
        self.assertEqual(asyncio.run(run_job(job))["status"], "complete")
        self.assertEqual(asyncio.run(run_job(job))["status"], "complete")
        page = self.client.get(f"/research/documents/{key}/pages/2").json()
        self.assertIn("SYNTHETIC TEST", page["text"])
        preview = self.client.get(f"/research/documents/{key}/preview/2")
        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview.content.startswith(b"\xff\xd8\xff"))
        self.assertEqual(hashlib.sha256(self.client.get(f"/research/documents/{key}/download").content).hexdigest(), hashlib.sha256(body).hexdigest())
        self.assertEqual(self.jobs.list_tasks(kind="manual"), [])
        self.assertEqual(self.jobs.list_tasks(kind="document")[0]["document_id"], key)
        self.assertNotIn("_operation", self.jobs.task_detail(job)["config"])
        with transaction() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(DocumentPage)), 2)
            self.assertEqual(db.scalar(select(func.count()).select_from(Report)), 0)

    def test_duplicate_does_not_overwrite_metadata_or_enqueue_again(self):
        body = synthetic_pdf(); first = self.store(body)
        again = self.store(body, issuer="Should not overwrite")
        self.assertTrue(again["duplicate"])
        self.assertEqual(first["document"]["id"], again["document"]["id"])
        self.assertEqual(self.repository.detail(first["document"]["id"])["issuer"], "")
        with transaction() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Job)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Outbox)), 1)

    def test_real_upload_auto_membership_duplicate_and_archived_collection_race(self):
        from src.knowledge.repository import CollectionRepository
        from src.knowledge.contracts import CollectionInput
        collections = CollectionRepository()
        collection = collections.create(CollectionInput(name="Synthetic upload target"))
        body = synthetic_pdf()
        stored = self.store(body, collection_id=collection["id"])
        self.assertEqual(stored["collection_assignment"]["status"], "added")
        again = self.store(body, collection_id=collection["id"])
        self.assertEqual(again["collection_assignment"]["status"], "already_member")
        self.assertEqual(collections.detail(collection["id"])["revision"], 2)
        collections.archive(collection["id"], 2)
        retained = self.store(collection_id=collection["id"])
        self.assertEqual(retained["collection_assignment"]["status"], "not_added")
        self.assertFalse(self.repository.detail(retained["document"]["id"])["archived"])

    def test_failed_import_can_be_retried_once_and_enters_same_document_lifecycle(self):
        from src.documents.network import SourceRejected
        url = "https://www.hkexnews.hk/synthetic-test.pdf"
        job = self.repository.create_import(url, UploadMetadata(title="Synthetic import"))
        with patch("src.documents.processing.download", side_effect=SourceRejected("Source resolved to a non-public address")):
            self.assertEqual(asyncio.run(run_job(job))["status"], "failed")
        self.assertIn("non-public", self.jobs.task_detail(job)["error"])
        self.assertEqual(self.repository.list()["total"], 0)
        retry = self.repository.retry_import(job)
        self.assertEqual(self.repository.retry_import(job)["id"], retry["id"])
        body = synthetic_pdf(); self.hashes.add(hashlib.sha256(body).hexdigest())
        with patch("src.documents.processing.download", return_value=(body, "test.pdf", url)):
            self.assertEqual(asyncio.run(run_job(retry["id"]))["status"], "complete")
        key = self.jobs.task_detail(retry["id"])["document_id"]
        self.assertEqual(self.repository.detail(key)["source_url"], url)

    def test_version_requires_latest_parent_and_metadata_compare_and_swap(self):
        first = self.store(); key = first["document"]["id"]
        second = self.store(previous_version_id=key)
        self.assertEqual(second["document"]["version"], 2)
        self.assertEqual(second["document"]["family_id"], first["document"]["family_id"])
        with self.assertRaises(StateConflict): self.store(previous_version_id=key)
        update = MetadataUpdate(title="Reviewed title", published_on="2026-10-31", publication_basis="Manual source verification", expected_revision=1, reason="Verified original")
        self.repository.update_metadata(key, update)
        with self.assertRaises(StateConflict): self.repository.update_metadata(key, update)
        self.assertEqual([item["revision"] for item in self.repository.history(key)], [2, 1])

    def test_archive_cancels_fences_late_writer_retains_reference_and_restore(self):
        stored = self.store(); key, job = stored["document"]["id"], stored["job_id"]
        token = str(uuid4()); self.jobs.claim(job, token)
        with transaction() as db:
            db.add(DocumentReference(id=str(uuid4()), document_id=key, owner_type="report", owner_id="synthetic-report", snapshot={"title": "Immutable citation"}))
        self.repository.archive(key)
        self.assertEqual(self.repository.list()["total"], 0)
        self.assertEqual(self.repository.list(archived=True)["total"], 1)
        self.assertEqual(self.jobs.task_detail(job)["status"], "cancelled")
        with self.assertRaises(StateConflict): self.repository.progress(job, token, "extract", "complete", document_id=key)
        self.assertEqual(self.repository.detail(key)["reference_count"], 1)
        self.assertEqual(self.client.get(f"/research/documents/{key}/download").status_code, 200)
        with self.assertRaises(StateConflict): self.repository.retry(key)
        self.repository.archive(key, False)
        retry = self.repository.retry(key)
        self.assertNotEqual(retry["id"], job)
        self.assertEqual(self.repository.retry(key)["id"], retry["id"])
        self.assertEqual(asyncio.run(run_job(retry["id"]))["status"], "complete")

    def test_image_only_is_partial_and_does_not_fabricate_text_or_semantic_index(self):
        image = io.BytesIO(); Image.new("RGB", (20, 20), color=(16, 42, 99)).save(image, "PNG")
        stored = self.store(image.getvalue(), kind="image")
        self.assertEqual(asyncio.run(run_job(stored["job_id"]))["status"], "partial")
        page = self.repository.page(stored["document"]["id"], 1)
        self.assertEqual((page["status"], page["text"]), ("needs_vision", ""))
        result = self.jobs.task_detail(stored["job_id"])["result"]
        self.assertEqual((result["semantic_index"], result["vision"]), ("not_built", "required"))

    def test_partial_page_failure_retry_reuses_good_page_and_repairs_missing_object(self):
        stored = self.store(synthetic_pdf(2)); key, job = stored["document"]["id"], stored["job_id"]
        from src.documents.parser import extract_page
        def flaky(body, number, media_type):
            if number == 2: raise RuntimeError("Synthetic page failure")
            return extract_page(body, number, media_type)
        with patch("src.documents.processing.extract_page", side_effect=flaky):
            self.assertEqual(asyncio.run(run_job(job))["status"], "partial")
        with transaction() as db:
            page_key = db.get(DocumentPage, (key, 1)).text_object_key
        with ObjectStore() as objects: objects.delete(page_key)
        retry = self.repository.retry(key)
        with patch("src.documents.processing.extract_page", wraps=extract_page) as extract:
            self.assertEqual(asyncio.run(run_job(retry["id"]))["status"], "complete")
            self.assertEqual(extract.call_count, 2)
        self.assertEqual(self.repository.detail(key)["page_states"], {"text_ready": 2})

    def test_date_company_type_and_escaped_search_filters_do_not_use_upload_time(self):
        self.store(issuer="Synthetic_100% issuer", symbols=["1211.HK"], kind="annual_report", published_on="2026-10-31", publication_basis="Fixture day")
        self.store(published_at="2026-11-01T00:10:00+08:00", publication_basis="Fixture instant")
        self.store()
        rows = self.repository.list(published_from=date(2026, 10, 31), published_to=date(2026, 10, 31))
        self.assertEqual(rows["total"], 1)
        self.assertEqual(self.repository.list(symbol="1211.HK", kind="annual_report", query="_100%")["total"], 1)
        self.assertEqual(self.repository.list(query="_100% missing")["total"], 0)
        self.assertEqual(self.repository.list(page=2, page_size=2)["total"], 3)
        self.assertEqual(len(self.repository.list(page=2, page_size=2)["documents"]), 1)
        self.assertNotIn("text", rows["documents"][0])
        self.assertNotIn("object_key", rows["documents"][0])

    def test_missing_original_fails_visibly_and_same_original_can_repair_it(self):
        body = synthetic_pdf(); stored = self.store(body); key = stored["document"]["id"]
        info = self.repository.object_info(key)
        with ObjectStore() as objects: objects.delete(info["key"])
        self.assertEqual(asyncio.run(run_job(stored["job_id"]))["status"], "failed")
        self.assertEqual(self.repository.detail(key)["status"], "failed")
        self.assertTrue(self.store(body)["duplicate"])
        retry = self.repository.retry(key)
        self.assertEqual(asyncio.run(run_job(retry["id"]))["status"], "complete")

    def test_retry_reuses_verified_successful_page_without_extracting_again(self):
        stored = self.store(synthetic_pdf(2)); key, job = stored["document"]["id"], stored["job_id"]
        from src.documents.parser import extract_page
        def flaky(body, number, media_type):
            if number == 2: raise RuntimeError("Synthetic page failure")
            return extract_page(body, number, media_type)
        with patch("src.documents.processing.extract_page", side_effect=flaky):
            self.assertEqual(asyncio.run(run_job(job))["status"], "partial")
        retry = self.repository.retry(key)
        with patch("src.documents.processing.extract_page", wraps=extract_page) as extract:
            self.assertEqual(asyncio.run(run_job(retry["id"]))["status"], "complete")
            self.assertEqual(extract.call_count, 1)
            self.assertEqual(extract.call_args.args[1], 2)

    def test_api_origin_invalid_files_dates_and_streamed_limit(self):
        response = self.client.post("/research/documents/upload", headers={"Origin": "https://untrusted.example"},
            files={"file": ("fake.pdf", b"fake")}, data={"metadata": '{"title":"Fake"}'})
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/research/documents/upload", files={"file": ("fake.pdf", b"fake")}, data={"metadata": '{"title":"Fake"}'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/research/documents?published_from=2026-11-01&published_to=2026-10-31").status_code, 422)
        with patch("src.documents.api.MAX_PDF_BYTES", 1024):
            response = self.client.post("/research/documents/upload", files={"file": ("large.pdf", b"x" * (2 * 1024 * 1024))}, data={"metadata": '{"title":"Large"}'})
            self.assertEqual(response.status_code, 413)
            boundary = "synthetic-upload-boundary"
            body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="test.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode()
                    + b"x" * (2 * 1024 * 1024) + f'\r\n--{boundary}--\r\n'.encode())
            response = self.client.post("/research/documents/upload", content=(body[index:index+65536] for index in range(0,len(body),65536)),
                                        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
            self.assertEqual(response.status_code, 413, response.text)


if __name__ == "__main__":
    unittest.main()

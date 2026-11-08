"""Leased, immutable index builds; publication never exposes half a rebuild."""
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, select, update

from src.documents.repository import existing_document, lease
from src.persistence.database import transaction
from src.persistence.jobs import JobRepository, MissingRecord, StateConflict
from src.persistence.models import DocumentPage, Job, KnowledgeChunk, KnowledgeIndex, RunEvent
from .chunks import CHUNK_VERSION, page_chunks, pages_fingerprint
from .embeddings import embed, fingerprint, public_settings, settings


def index_profile(mode):
    profile = {"mode": mode, "chunk_version": CHUNK_VERSION}
    if mode == "hybrid":
        config = settings()
        if not public_settings()["verified"]: raise StateConflict("Save and test the embedding configuration first")
        profile["embedding"] = config
    semantic = {**profile, **({"embedding": fingerprint(profile["embedding"])} if mode == "hybrid" else {})}
    key = hashlib.sha256(json.dumps(semantic, sort_keys=True).encode()).hexdigest()
    return profile, key


def serialize(row, job):
    return {"id": row.id, "document_id": row.document_id, "job_id": row.job_id, "status": job.status,
        "mode": row.profile["mode"], "profile_key": row.profile_key, "profile": row.profile,
        "published": row.published, "chunk_count": row.chunk_count, "text_pages": row.text_pages,
        "omitted_pages": row.omitted_pages, "created_at": row.created_at, "error": job.error,
        "progress": job.progress, "elapsed_seconds": job.elapsed_seconds}


class IndexRepository:
    def __init__(self, bind=None): self.bind = bind

    def list(self, document_ids):
        with transaction(self.bind) as db:
            rows = db.execute(select(KnowledgeIndex, Job).join(Job, Job.id == KnowledgeIndex.job_id)
                .where(KnowledgeIndex.document_id.in_(document_ids)).order_by(KnowledgeIndex.record_order.desc()).limit(200))
            return {"indices": [serialize(row, job) for row, job in rows]}

    def create(self, inputs):
        profile, profile_key = index_profile(inputs.mode)
        with transaction(self.bind) as db:
            # Deterministic document locks make overlapping batches safe.
            docs = [existing_document(db, key, lock=True) for key in sorted(inputs.document_ids)]
            if any(doc.archived or doc.status not in {"ready", "partial"} for doc in docs):
                raise StateConflict("Select active documents with completed page extraction")
            results = []
            for doc in docs:
                existing = db.execute(select(KnowledgeIndex, Job).join(Job, Job.id == KnowledgeIndex.job_id).where(
                    KnowledgeIndex.document_id == doc.id, KnowledgeIndex.profile_key == profile_key,
                    Job.status.in_(["queued", "running"]))).first()
                if existing:
                    results.append({**serialize(*existing), "existing": True}); continue
                pages = db.scalars(select(DocumentPage).where(DocumentPage.document_id == doc.id).order_by(DocumentPage.page_number)).all()
                source = pages_fingerprint(pages)
                current = db.execute(select(KnowledgeIndex, Job).join(Job, Job.id == KnowledgeIndex.job_id).where(
                    KnowledgeIndex.document_id == doc.id, KnowledgeIndex.profile_key == profile_key,
                    KnowledgeIndex.published.is_(True), KnowledgeIndex.source_fingerprint == source)).first()
                if current and not inputs.force:
                    results.append({**serialize(*current), "existing": True}); continue
                key = str(uuid4())
                job_id = JobRepository.enqueue(db, f"Index · {doc.title}",
                    {"_operation": "knowledge.index", "index_id": key, "document_id": doc.id}, kind="knowledge")
                row = KnowledgeIndex(id=key, document_id=doc.id, job_id=job_id, profile_key=profile_key,
                    profile=profile, chunk_version=CHUNK_VERSION)
                db.add(row); db.flush()
                results.append({**serialize(row, db.get(Job, job_id)), "existing": False})
            return {"indices": results}


def progress(job_id, token, stage, status, detail, result=None):
    with transaction() as db:
        job = lease(db, job_id, token)
        stages = [item for item in job.progress if item["id"] != stage]
        stages.append({"id": stage, "status": status, "detail": detail})
        job.progress = stages
        job.elapsed_seconds = (datetime.now(timezone.utc) - job.started_at).total_seconds()
        if result: job.result = {**job.result, **result}
        db.add(RunEvent(run_id=job_id, event_id=str(uuid4()), kind="knowledge.progress", payload={"stage": stage, "status": status}))


async def execute_index(payload, job_id, token):
    key = payload["index_id"]
    with transaction() as db:
        job = lease(db, job_id, token)
        row = db.get(KnowledgeIndex, key)
        if row is None or row.job_id != job.id: raise MissingRecord("Index build does not exist")
        if row.published: raise StateConflict("Published indices cannot run again")
        document = existing_document(db, row.document_id)
        if document.archived: raise ValueError("Document was archived before indexing")
        pages = db.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id).order_by(DocumentPage.page_number)).all()
        source = pages_fingerprint(pages); chunks = page_chunks(pages)
        profile, document_id = row.profile, row.document_id
        text_pages = sum(page.status == "text_ready" and bool(page.text.strip()) for page in pages)
        omitted_pages = document.page_count - text_pages
    if not chunks: raise ValueError("No readable text pages; process the document or use vision first")
    progress(job_id, token, "chunk", "complete", f"{len(chunks)} page-local chunks; {omitted_pages} pages not text-readable")
    vectors = [None] * len(chunks); usage = 0
    if profile["mode"] == "hybrid":
        progress(job_id, token, "embedding", "running", f"Embedding {len(chunks)} bounded chunks")
        # Lease check between batches; a cancelled build never publishes.
        for start in range(0, len(chunks), 2):
            with transaction() as db:
                lease(db, job_id, token)
                if existing_document(db, document_id).archived:
                    raise ValueError("Document archived; remaining embedding batches stopped")
            batch, tokens = await embed([item["text"] for item in chunks[start:start+2]], profile["embedding"])
            vectors[start:start+len(batch)] = batch; usage += tokens
            progress(job_id, token, "embedding", "running", f"{min(start+2,len(chunks))} / {len(chunks)} chunks", {"embedding_tokens": usage})
        progress(job_id, token, "embedding", "complete", f"{len(chunks)} vectors validated and generated")
    progress(job_id, token, "index", "running", "Publishing a complete version; previous index remains readable")
    with transaction() as db:
        job = lease(db, job_id, token)
        document = existing_document(db, document_id, lock=True)
        if document.archived: raise ValueError("Archived documents cannot publish a new index")
        current_pages = db.scalars(select(DocumentPage).where(DocumentPage.document_id == document_id).order_by(DocumentPage.page_number)).all()
        if pages_fingerprint(current_pages) != source: raise ValueError("Page extraction changed during indexing; rebuild from current pages")
        row = db.get(KnowledgeIndex, key)
        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.index_id == key))
        db.add_all(KnowledgeChunk(id=str(uuid4()), index_id=key, embedding=vector, **chunk) for chunk, vector in zip(chunks, vectors))
        db.execute(update(KnowledgeIndex).where(KnowledgeIndex.document_id == document_id,
            KnowledgeIndex.profile_key == row.profile_key, KnowledgeIndex.published.is_(True)).values(published=False))
        db.flush()
        row.source_fingerprint, row.published = source, True
        row.chunk_count, row.text_pages, row.omitted_pages = len(chunks), text_pages, omitted_pages
        job.result = {"index_id": key, "document_id": document_id, "chunk_count": len(chunks), "embedding_tokens": usage}
        job.progress = [*job.progress[:-1], {"id": "index", "status": "complete", "detail": f"Published {len(chunks)} chunks atomically"}]
        job.elapsed_seconds = (datetime.now(timezone.utc) - job.started_at).total_seconds()
        # Publication and terminal job status share the transaction so recovery
        # cannot report a published build as failed or charge it again.
        job.status, job.lease_token, job.lease_until = "complete", None, None
    return {"status": "complete", "_finished": True}

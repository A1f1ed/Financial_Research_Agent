"""Transactional document versions, metadata audit, processing and visibility."""
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from src.persistence.database import transaction
from src.persistence.jobs import JobRepository, MissingRecord, StateConflict, TERMINAL
from src.persistence.models import Document, DocumentPage, DocumentReference, DocumentRevision, Job, RunEvent
from .contracts import DocumentMetadata, MetadataUpdate, UploadMetadata
from src.knowledge.repository import attach_uploaded, collection
from src.persistence.models import CollectionMember

UTC = timezone.utc
METADATA_FIELDS = tuple(DocumentMetadata.model_fields)


def metadata(document):
    return {key: getattr(document, key) for key in METADATA_FIELDS}


def summary(document):
    return {"id": document.id, "title": document.title, "issuer": document.issuer, "symbols": document.symbols,
        "kind": document.kind, "filename": document.filename, "media_type": document.media_type,
        "byte_size": document.byte_size, "page_count": document.page_count,
        "family_id": document.family_id, "version": document.version, "metadata_revision": document.metadata_revision,
        "status": document.status, "archived": document.archived, "removed_at": document.removed_at,
        "created_at": document.created_at, "published_on": document.published_on, "published_at": document.published_at,
        "publication_precision": "second" if document.published_at else "day" if document.published_on else "unknown",
        "latest_job_id": document.active_job_id}


def existing_document(db, key, *, lock=False, allow_removed=False):
    query = select(Document).where(Document.id == key)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    document = db.scalar(query)
    if document is None or document.removed_at and not allow_removed:
        raise MissingRecord("Document does not exist or its original has been removed")
    return document


def lease(db, job_id, token):
    job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if (not job or job.status != "running" or job.cancel_requested or job.lease_token != token
            or job.lease_until is None or job.lease_until <= datetime.now(UTC)):
        raise StateConflict("Document processing was cancelled or its execution lease expired")
    return job


class DocumentRepository:
    def __init__(self, bind=None):
        self.bind = bind

    def register(self, sha256, object_key, info, filename, inputs: UploadMetadata, *, job_id=None, token=None):
        with transaction(self.bind) as db:
            job = lease(db, job_id, token) if job_id else None
            duplicate = db.scalar(select(Document).where(Document.sha256 == sha256))
            if duplicate:
                return {"document": summary(duplicate), "duplicate": True, "job_id": duplicate.active_job_id,
                        "collection_assignment": attach_uploaded(db, inputs.collection_id, duplicate)}
            key = str(uuid4())
            previous = None
            if inputs.previous_version_id:
                previous = existing_document(db, inputs.previous_version_id, lock=True)
                latest = db.scalar(select(func.max(Document.version)).where(Document.family_id == previous.family_id))
                if latest != previous.version:
                    raise StateConflict("A newer document version exists; choose the latest version before uploading")
            values = inputs.model_dump(exclude={"previous_version_id", "collection_id"})
            statement = insert(Document).values(id=key, sha256=sha256, object_key=object_key, filename=filename,
                byte_size=info["byte_size"], page_count=info["page_count"], media_type=info["media_type"],
                family_id=previous.family_id if previous else key, version=previous.version + 1 if previous else 1,
                previous_version_id=previous.id if previous else None, status="queued", **values)
            inserted = db.scalar(statement.on_conflict_do_nothing(index_elements=[Document.sha256]).returning(Document.id))
            if not inserted:
                duplicate = db.scalar(select(Document).where(Document.sha256 == sha256))
                return {"document": summary(duplicate), "duplicate": True, "job_id": duplicate.active_job_id,
                        "collection_assignment": attach_uploaded(db, inputs.collection_id, duplicate)}
            if job is None:
                job_id = JobRepository.enqueue(db, inputs.title,
                    {"_operation": "document.ingest", "document_id": key}, kind="document")
            else:
                job.config = {**job.config, "document_id": key}
            document = db.get(Document, key)
            document.active_job_id = job_id
            db.add(DocumentRevision(document_id=key, revision=1,
                body=DocumentMetadata.model_validate(values).model_dump(mode="json"), reason="Initial upload/import metadata"))
            db.flush()
            assignment = attach_uploaded(db, inputs.collection_id, document)
            current_job = job if job is not None else db.get(Job, job_id)
            current_job.result = {**current_job.result, "collection_assignment": assignment}
            return {"document": summary(document), "duplicate": False, "job_id": job_id, "collection_assignment": assignment}

    def create_import(self, url, inputs):
        with transaction(self.bind) as db:
            return JobRepository.enqueue(db, inputs.title,
                {"_operation": "document.import", "url": url, "metadata": inputs.model_dump(mode="json")}, kind="document")

    def retry_import(self, key):
        with transaction(self.bind) as db:
            job = db.scalar(select(Job).where(Job.id == key).with_for_update())
            if not job or job.kind != "document" or job.config.get("_operation") != "document.import":
                raise MissingRecord("Official import task does not exist")
            if job.status not in {"failed", "cancelled"} or job.config.get("document_id"):
                raise StateConflict("Use the retained document's processing task, or wait for this import to finish")
            if job.result.get("retry_job_id"):
                return {"id": job.result["retry_job_id"], "existing": True}
            new_id = JobRepository.enqueue(db, job.name, deepcopy(job.config), kind="document")
            job.result = {**job.result, "retry_job_id": new_id}
            return {"id": new_id, "existing": False}

    def list(self, *, query="", symbol="", kind=None, status=None, archived=False, page=1, page_size=20,
             published_from=None, published_to=None, collection_id=None, outside_collection=False):
        if not 1 <= page_size <= 100 or not 1 <= page <= 100000:
            raise ValueError("Invalid document page parameters")
        conditions = [Document.archived == archived, Document.removed_at.is_(None)]
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(Document.title.ilike("%" + escaped + "%", escape="\\") |
                              Document.issuer.ilike("%" + escaped + "%", escape="\\"))
        if symbol:
            conditions.append(Document.symbols.contains([symbol]))
        if kind:
            conditions.append(Document.kind == kind)
        if status:
            conditions.append(Document.status == status)
        # Date-only facts retain day precision; exact instants use the stated
        # filter zone. Never substitute upload time for unknown publication.
        zone = ZoneInfo("Asia/Shanghai")
        if published_from and published_to and published_from > published_to:
            raise ValueError("Publication start date must precede its end")
        if published_from:
            conditions.append((Document.published_on >= published_from) |
                (Document.published_at >= datetime.combine(published_from, time.min, zone)))
        if published_to:
            conditions.append((Document.published_on <= published_to) |
                (Document.published_at < datetime.combine(published_to + timedelta(days=1), time.min, zone)))
        with transaction(self.bind) as db:
            if collection_id:
                collection(db, collection_id)
                membership = select(CollectionMember.document_id).where(CollectionMember.collection_id == collection_id,
                    CollectionMember.document_id == Document.id).exists()
                conditions.append(~membership if outside_collection else membership)
            count = db.scalar(select(func.count()).select_from(Document).where(*conditions))
            items = db.scalars(select(Document).where(*conditions).order_by(Document.record_order.desc())
                .offset((page - 1) * page_size).limit(page_size)).all()
            return {"documents": [summary(document) for document in items], "total": count,
                    "page": page, "page_size": page_size}

    def detail(self, key):
        with transaction(self.bind) as db:
            document = existing_document(db, key, allow_removed=True)
            counts = dict(db.execute(select(DocumentPage.status, func.count()).where(DocumentPage.document_id == key)
                .group_by(DocumentPage.status)).all())
            refs = db.scalar(select(func.count()).select_from(DocumentReference).where(DocumentReference.document_id == key))
            versions = db.execute(select(Document.id, Document.version, Document.title, Document.archived).where(
                Document.family_id == document.family_id).order_by(Document.version.desc()).limit(100)).mappings().all()
            return {**summary(document), **metadata(document), "source_sha256": document.sha256,
                    "page_states": counts, "reference_count": refs, "versions": [dict(row) for row in versions]}

    def object_info(self, key):
        with transaction(self.bind) as db:
            document = existing_document(db, key)
            return {"key": document.object_key, "sha256": document.sha256, "media_type": document.media_type,
                    "filename": document.filename, "page_count": document.page_count}

    def page(self, key, number):
        with transaction(self.bind) as db:
            document = existing_document(db, key)
            if not 1 <= number <= document.page_count:
                raise MissingRecord("Page does not exist")
            page = db.get(DocumentPage, (key, number))
            return {"document_id": key, "page_number": number, "text": page.text if page else "",
                    "status": page.status if page else "pending", "width": page.width if page else None,
                    "height": page.height if page else None, "extraction_version": page.extraction_version if page else None,
                    "error_type": page.error_type if page else None}

    def history(self, key):
        with transaction(self.bind) as db:
            existing_document(db, key, allow_removed=True)
            return [{"revision": row.revision, "metadata": row.body, "reason": row.reason, "created_at": row.created_at}
                for row in db.scalars(select(DocumentRevision).where(DocumentRevision.document_id == key)
                    .order_by(DocumentRevision.revision.desc()))]

    def update_metadata(self, key, inputs: MetadataUpdate):
        with transaction(self.bind) as db:
            document = existing_document(db, key, lock=True)
            if document.metadata_revision != inputs.expected_revision:
                raise StateConflict("Document metadata changed elsewhere; reload before saving")
            body = inputs.model_dump(exclude={"expected_revision", "reason"})
            for name, value in body.items():
                setattr(document, name, value)
            document.metadata_revision += 1
            db.add(DocumentRevision(document_id=key, revision=document.metadata_revision,
                body=DocumentMetadata.model_validate(body).model_dump(mode="json"), reason=inputs.reason))
            return summary(document)

    def archive(self, key, value=True):
        # Lock order is always job then document, matching publishing/cancellation.
        with transaction(self.bind) as db:
            snapshot = existing_document(db, key)
            previous_job_id = snapshot.active_job_id
            job = db.scalar(select(Job).where(Job.id == previous_job_id).with_for_update()) if previous_job_id else None
            document = existing_document(db, key, lock=True)
            if document.active_job_id != previous_job_id:
                raise StateConflict("Document processing changed; refresh before archiving")
            document.archived = value
            if value and job and job.status not in TERMINAL:
                job.status, job.cancel_requested, job.lease_token, job.lease_until = "cancelled", True, None, None
                job.version += 1
                document.status = "cancelled"
                db.add(RunEvent(run_id=job.id, event_id=str(uuid4()), kind="task.cancelled", payload={"status": "cancelled"}))
            return summary(document)

    def retry(self, key):
        with transaction(self.bind) as db:
            snapshot = existing_document(db, key)
            previous_job_id = snapshot.active_job_id
            job = db.scalar(select(Job).where(Job.id == previous_job_id).with_for_update()) if previous_job_id else None
            document = existing_document(db, key, lock=True)
            if document.archived:
                raise StateConflict("Restore this document before processing it")
            if document.active_job_id != previous_job_id:
                return {"id": document.active_job_id, "existing": True}
            if job and job.status not in TERMINAL:
                return {"id": job.id, "existing": True}
            if document.status == "ready":
                raise StateConflict("Document text is already processed")
            job_id = JobRepository.enqueue(db, document.title,
                {"_operation": "document.ingest", "document_id": key}, kind="document")
            document.active_job_id, document.status = job_id, "queued"
            return {"id": job_id, "existing": False}

    def progress(self, job_id, token, stage, status, *, document_id=None, detail="", result=None):
        with transaction(self.bind) as db:
            job = lease(db, job_id, token)
            now = datetime.now(UTC)
            rows = deepcopy(job.progress)
            match = next((row for row in rows if row["id"] == stage), None)
            if match is None:
                match = {"id": stage}
                rows.append(match)
            match.update(status=status, detail=detail, updated_at=now.isoformat())
            job.progress = rows
            job.elapsed_seconds = round((now - (job.started_at or job.created_at)).total_seconds(), 3)
            if result is not None:
                job.result = result
            if document_id:
                document = existing_document(db, document_id, lock=True)
                if document.archived or document.active_job_id != job_id:
                    raise StateConflict("Document is archived or another processing run owns it")
                document.status = "processing"
            db.add(RunEvent(run_id=job_id, event_id=str(uuid4()), kind="document.progress", payload={
                "stage": stage, "status": status, "elapsed_seconds": job.elapsed_seconds}))

    def save_page(self, job_id, token, key, number, extracted, object_key, extraction_version):
        with transaction(self.bind) as db:
            lease(db, job_id, token)
            document = existing_document(db, key, lock=True)
            if document.archived or document.active_job_id != job_id:
                raise StateConflict("Document processing no longer owns this version")
            values = {"document_id": key, "page_number": number, "text": extracted["text"], "status": extracted["status"],
                "width": extracted["width"], "height": extracted["height"], "text_object_key": object_key,
                "extraction_version": extraction_version, "error_type": extracted.get("error_type")}
            statement = insert(DocumentPage).values(**values)
            db.execute(statement.on_conflict_do_update(index_elements=[DocumentPage.document_id, DocumentPage.page_number],
                set_={name: value for name, value in values.items() if name not in {"document_id", "page_number"}}))

    def complete(self, job_id, token, key):
        with transaction(self.bind) as db:
            job = lease(db, job_id, token)
            document = existing_document(db, key, lock=True)
            if document.archived or document.active_job_id != job_id:
                raise StateConflict("Document processing no longer owns this version")
            counts = dict(db.execute(select(DocumentPage.status, func.count()).where(DocumentPage.document_id == key)
                .group_by(DocumentPage.status)).all())
            if sum(counts.values()) != document.page_count:
                raise StateConflict("Cannot publish an incomplete set of page states")
            document.status = "ready" if counts.get("text_ready", 0) == document.page_count else (
                "failed" if counts.get("failed", 0) == document.page_count else "partial")
            job.result = {**job.result, "document_id": key, "page_states": counts, "text_extraction_ready": counts.get("text_ready", 0) > 0,
                          "semantic_index": "not_built", "vision": "required" if counts.get("needs_vision") else "not_required"}
            return {"status": "complete" if document.status == "ready" else document.status, "document_id": key}

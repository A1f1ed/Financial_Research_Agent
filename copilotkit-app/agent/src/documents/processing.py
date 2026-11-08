"""Real document ingestion, S3 integrity and per-page durable publication."""
import asyncio
import hashlib
import json
from botocore.exceptions import ClientError

from sqlalchemy import select

from src.infrastructure.objects import ObjectStore
from src.persistence.database import transaction
from src.persistence.jobs import StateConflict
from src.persistence.models import DocumentPage
from .contracts import EXTRACTION_VERSION, UploadMetadata, safe_filename
from .network import download
from .parser import InvalidDocument, extract_page, inspect_document
from .repository import DocumentRepository, lease


def store_original(body, filename, inputs, *, job_id=None, token=None):
    info = {**inspect_document(body), "byte_size": len(body)}
    digest = hashlib.sha256(body).hexdigest()
    key = "documents/" + digest + "/original"
    with ObjectStore() as objects:
        objects.put_verified(key, body, info["media_type"])
    # An object written before a DB failure is not marked usable. A bounded
    # orphan sweep can remove unreferenced document prefixes after a grace period.
    return DocumentRepository().register(digest, key, info, safe_filename(filename), inputs, job_id=job_id, token=token)


def process(payload, job_id, token):
    repository = DocumentRepository()

    def checkpoint():
        with transaction() as db:
            lease(db, job_id, token)

    key = payload.get("document_id")
    if payload["_operation"] == "document.import":
        repository.progress(job_id, token, "download", "running", detail="Downloading from a verified public official source")
        body, filename, final_url = download(payload["url"], checkpoint)
        checkpoint()
        metadata = UploadMetadata.model_validate(payload["metadata"])
        metadata.source_url = final_url
        stored = store_original(body, filename, metadata, job_id=job_id, token=token)
        key = stored["document"]["id"]
        repository.progress(job_id, token, "download", "complete", result={"document_id": key, "duplicate": stored["duplicate"],
                            "collection_assignment": stored.get("collection_assignment")})
        if stored["duplicate"]:
            # No model/index invocation or metadata overwrite on duplicate bytes.
            return {"status": "complete", "document_id": key}
    if not key:
        raise InvalidDocument("Document processing has no registered original")
    original = repository.object_info(key)
    repository.progress(job_id, token, "integrity", "running", document_id=key, detail="Verifying the retained original")
    with ObjectStore() as objects:
        body = objects.get(original["key"])
        if hashlib.sha256(body).hexdigest() != original["sha256"]:
            raise InvalidDocument("Original integrity verification failed; upload the original file again")
        repository.progress(job_id, token, "integrity", "complete", document_id=key)
        repository.progress(job_id, token, "extract", "running", document_id=key,
                            detail=f"0 / {original['page_count']} pages")
        for number in range(1, original["page_count"] + 1):
            checkpoint()
            with transaction() as db:
                prior = db.get(DocumentPage, (key, number))
                reusable = prior is not None and prior.extraction_version == EXTRACTION_VERSION and prior.status in {"text_ready", "needs_vision"}
                prior_key, prior_text = (prior.text_object_key, prior.text) if reusable else (None, None)
            if reusable:
                try:
                    stored_page = json.loads(objects.get(prior_key))
                    reusable = (stored_page.get("document_id") == key and stored_page.get("page_number") == number
                                and stored_page.get("text") == prior_text)
                except ClientError as error:
                    if error.response.get("Error", {}).get("Code") not in {"NoSuchKey", "404", "NotFound"}:
                        raise
                    reusable = False
                except (ValueError, TypeError, UnicodeDecodeError):
                    reusable = False
            if not reusable:
                try:
                    page = extract_page(body, number, original["media_type"])
                except StateConflict:
                    raise
                except (ValueError, RuntimeError, OSError) as error:
                    page = {"text": "", "width": 0, "height": 0, "blocks": [], "status": "failed",
                            "error_type": type(error).__name__}
                page_key = f"documents/{original['sha256']}/{EXTRACTION_VERSION}/page-{number:05d}.json"
                serialized = json.dumps({"document_id": key, "page_number": number, **page}, ensure_ascii=False, allow_nan=False).encode("utf-8")
                checkpoint()
                objects.put_verified(page_key, serialized, "application/json")
                repository.save_page(job_id, token, key, number, page, page_key, EXTRACTION_VERSION)
            repository.progress(job_id, token, "extract", "running", document_id=key,
                                detail=f"{number} / {original['page_count']} pages")
        repository.progress(job_id, token, "extract", "complete", document_id=key,
                            detail=f"{original['page_count']} pages processed; image-only pages require vision")
    return repository.complete(job_id, token, key)


async def execute_document(payload, job_id, token):
    if payload.get("_operation") not in {"document.ingest", "document.import"}:
        raise ValueError("Unknown document operation")
    return await asyncio.to_thread(process, payload, job_id, token)

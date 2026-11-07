"""Online document lifecycle. API never runs extraction or model jobs itself."""
import hashlib
import json
import os
from datetime import date
from typing import Annotated
from urllib.parse import quote

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.formparsers import MultiPartException

from src.infrastructure.objects import ObjectStore
from src.persistence.jobs import MissingRecord, StateConflict
from .contracts import DocumentKind, MAX_PDF_BYTES, MetadataUpdate, UploadMetadata, URLImport
from .network import OFFICIAL_DOMAINS, SourceRejected, validate_url
from .parser import InvalidDocument, render_page
from .processing import store_original
from .repository import DocumentRepository

router = APIRouter(prefix="/research/documents")


class UploadBodyLimit:
    """Limit multipart bodies before a client can fill the spool/temp disk."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/research/documents/upload":
            return await self.app(scope, receive, send)
        ceiling = MAX_PDF_BYTES + 1024 * 1024
        headers = dict(scope.get("headers", []))
        length = headers.get(b"content-length", b"")
        if length.isdigit() and int(length) > ceiling:
            return await JSONResponse({"detail": "Upload exceeds the 50 MB file limit"}, status_code=413)(scope, receive, send)
        consumed, exceeded = 0, False

        async def limited_receive():
            nonlocal consumed, exceeded
            message = await receive()
            consumed += len(message.get("body", b""))
            if consumed > ceiling:
                exceeded = True
                raise MultiPartException("Upload exceeds the 50 MB file limit")
            return message

        async def limited_send(message):
            if exceeded and message["type"] == "http.response.start":
                message = {**message, "status": 413}
            await send(message)

        await self.app(scope, limited_receive, limited_send)


def authorize_write(request):
    origin = request.headers.get("origin")
    allowed = os.getenv("APERTURE_BROWSER_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if origin and origin not in {value.strip() for value in allowed}:
        raise HTTPException(403, "This browser origin is not allowed to modify research documents")


def run(operation):
    try:
        return operation()
    except MissingRecord as error:
        raise HTTPException(404, str(error)) from None
    except StateConflict as error:
        raise HTTPException(409, str(error)) from None
    except (InvalidDocument, SourceRejected) as error:
        raise HTTPException(400, str(error)) from None
    except (BotoCoreError, ClientError):
        raise HTTPException(503, "Document object storage is unavailable; existing metadata has been preserved") from None


@router.get("/options")
def options():
    return {"pdf_max_bytes": MAX_PDF_BYTES, "image_max_bytes": 20 * 1024 * 1024, "max_files": 10,
            "max_pdf_pages": 500, "max_image_pixels": 30_000_000, "official_domains": OFFICIAL_DOMAINS}


@router.post("/upload")
def upload(request: Request, file: Annotated[UploadFile, File()], metadata: Annotated[str, Form(max_length=12000)]):
    authorize_write(request)
    try:
        inputs = UploadMetadata.model_validate_json(metadata)
    except ValidationError as error:
        raise HTTPException(422, [{"loc": item["loc"], "msg": item["msg"]} for item in error.errors()]) from None
    try:
        body = file.file.read(MAX_PDF_BYTES + 1)
        if len(body) > MAX_PDF_BYTES:
            raise HTTPException(413, "PDF exceeds 50 MB; images must not exceed 20 MB")
        result = run(lambda: store_original(body, file.filename or "document", inputs))
        return JSONResponse(jsonable_encoder(result), status_code=200 if result["duplicate"] else 202)
    finally:
        file.file.close()


@router.post("/import", status_code=202)
def import_url(request: Request, value: URLImport):
    authorize_write(request)
    run(lambda: validate_url(value.url))
    return {"id": DocumentRepository().create_import(value.url, value.metadata)}


@router.get("")
def list_documents(q: str = Query(default="", max_length=200), symbol: str = Query(default="", max_length=30),
                   kind: DocumentKind | None = None, status: str | None = Query(default=None, max_length=30),
                   archived: bool = False, page: int = Query(default=1, ge=1, le=100000),
                   page_size: int = Query(default=20, ge=1, le=100), published_from: date | None = None,
                   published_to: date | None = None, collection_id: str | None = Query(default=None, pattern=r"^[a-f0-9-]{36}$"),
                   outside_collection: bool = False):
    if published_from and published_to and published_from > published_to:
        raise HTTPException(422, "Publication start date must precede its end")
    if outside_collection and not collection_id:
        raise HTTPException(422, "Select a collection before filtering documents outside it")
    return run(lambda: DocumentRepository().list(query=q, symbol=symbol, kind=kind, status=status, archived=archived, page=page,
                                    page_size=page_size, published_from=published_from, published_to=published_to,
                                    collection_id=collection_id, outside_collection=outside_collection))


@router.post("/imports/{key}/retry", status_code=202)
def retry_import(key: str, request: Request):
    authorize_write(request)
    return run(lambda: DocumentRepository().retry_import(key))


@router.get("/{key}")
def detail(key: str):
    return run(lambda: DocumentRepository().detail(key))


@router.put("/{key}")
def edit(key: str, value: MetadataUpdate, request: Request):
    authorize_write(request)
    return run(lambda: DocumentRepository().update_metadata(key, value))


@router.post("/{key}/archive")
def archive(key: str, request: Request):
    authorize_write(request)
    return run(lambda: DocumentRepository().archive(key))


@router.post("/{key}/restore")
def restore(key: str, request: Request):
    authorize_write(request)
    return run(lambda: DocumentRepository().archive(key, False))


@router.post("/{key}/retry", status_code=202)
def retry(key: str, request: Request):
    authorize_write(request)
    return run(lambda: DocumentRepository().retry(key))


@router.get("/{key}/history")
def history(key: str):
    return {"revisions": run(lambda: DocumentRepository().history(key))}


@router.get("/{key}/pages/{number}")
def page(key: str, number: int):
    return run(lambda: DocumentRepository().page(key, number))


@router.get("/{key}/preview/{number}")
def preview(key: str, number: int):
    original = run(lambda: DocumentRepository().object_info(key))
    if not 1 <= number <= original["page_count"]:
        raise HTTPException(404, "Page does not exist")
    cache_key = f"documents/{original['sha256']}/preview-v1/page-{number:05d}.jpg"

    def render():
        with ObjectStore() as objects:
            try:
                return objects.get(cache_key, max_bytes=6 * 1024 * 1024)
            except ClientError as error:
                if error.response.get("Error", {}).get("Code") not in {"NoSuchKey", "404", "NotFound"}:
                    raise
            body = objects.get(original["key"])
            if hashlib.sha256(body).hexdigest() != original["sha256"]:
                raise InvalidDocument("Original integrity check failed; preview is unavailable")
            image = render_page(body, number, original["media_type"])
            objects.put_verified(cache_key, image, "image/jpeg")
            return image
    return Response(run(render), media_type="image/jpeg", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/{key}/download")
def original_file(key: str):
    original = run(lambda: DocumentRepository().object_info(key))
    def read():
        with ObjectStore() as objects:
            body = objects.get(original["key"])
        if hashlib.sha256(body).hexdigest() != original["sha256"]:
            raise InvalidDocument("Original integrity check failed; download is unavailable")
        return body
    return Response(run(read), media_type=original["media_type"], headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(original["filename"], safe=""),
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

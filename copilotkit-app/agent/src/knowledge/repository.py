"""Versioned collections and authoritative, date-bounded material scopes."""
from datetime import datetime, time, timedelta, timezone
import hashlib
import json
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, exists, func, select
from src.persistence.database import transaction
from src.persistence.jobs import MissingRecord, StateConflict
from src.persistence.models import CollectionMember, CollectionRevision, Document, DocumentPage, DocumentReference, KnowledgeCollection
from .contracts import CollectionInput, ScopeRequest

COLLECTION_FIELDS = tuple(CollectionInput.model_fields)
MAX_MEMBERS = 5000
MARKET_ZONES = {"HK": "Asia/Hong_Kong", "SH": "Asia/Shanghai", "SZ": "Asia/Shanghai", "US": "America/New_York", "SG": "Asia/Singapore"}


def collection(db, key, *, lock=False):
    query = select(KnowledgeCollection).where(KnowledgeCollection.id == key)
    if lock: query = query.with_for_update().execution_options(populate_existing=True)
    value = db.scalar(query)
    if value is None: raise MissingRecord("Knowledge collection does not exist")
    return value


def metadata(value):
    return {key: getattr(value, key) for key in COLLECTION_FIELDS}


def summary(value):
    return {"id": value.id, **metadata(value), "revision": value.revision, "archived": value.archived,
            "created_at": value.created_at, "updated_at": value.updated_at, "version_policy": "exact_document_versions"}


def audit(db, value, operation, reason, changes=None, *, initial=False):
    if not initial: value.revision += 1
    value.updated_at = datetime.now(timezone.utc)
    db.add(CollectionRevision(collection_id=value.id, revision=value.revision, operation=operation,
        body={**metadata(value), "archived": value.archived, "version_policy": "exact_document_versions", "changes": changes or {}}, reason=reason))


def statistics(db, keys):
    values = {key: {"documents": 0, "active_documents": 0, "archived_documents": 0, "removed_documents": 0,
                   "pages": 0, "text_pages": 0, "needs_vision_pages": 0, "failed_pages": 0, "pending_pages": 0,
                   "references": 0, "semantic_index": "not_checked"} for key in keys}
    if not keys: return values
    active = Document.archived.is_(False) & Document.removed_at.is_(None)
    rows = db.execute(select(CollectionMember.collection_id, func.count(Document.id), func.count(Document.id).filter(active),
        func.count(Document.id).filter(Document.archived.is_(True) & Document.removed_at.is_(None)),
        func.count(Document.id).filter(Document.removed_at.is_not(None)), func.coalesce(func.sum(Document.page_count).filter(active), 0))
        .join(Document, Document.id == CollectionMember.document_id).where(CollectionMember.collection_id.in_(keys))
        .group_by(CollectionMember.collection_id))
    for key, total, usable, archived, removed, pages in rows:
        values[key].update(documents=total, active_documents=usable, archived_documents=archived, removed_documents=removed, pages=pages)
    counts = db.execute(select(CollectionMember.collection_id, DocumentPage.status, func.count())
        .join(Document, Document.id == CollectionMember.document_id).join(DocumentPage, DocumentPage.document_id == Document.id)
        .where(CollectionMember.collection_id.in_(keys), active).group_by(CollectionMember.collection_id, DocumentPage.status))
    for key, state, count in counts:
        target = {"text_ready": "text_pages", "needs_vision": "needs_vision_pages", "failed": "failed_pages"}.get(state)
        if target: values[key][target] = count
    for counts in values.values():
        counts["pending_pages"] = max(0, counts["pages"] - counts["text_pages"] - counts["needs_vision_pages"] - counts["failed_pages"])
    for key, count in db.execute(select(CollectionMember.collection_id, func.count(DocumentReference.id))
        .join(DocumentReference, DocumentReference.document_id == CollectionMember.document_id)
        .where(CollectionMember.collection_id.in_(keys)).group_by(CollectionMember.collection_id)):
        values[key]["references"] = count
    return values


def material_revision(db, key):
    # Collection membership alone does not change when a source publication
    # date is corrected or the global original is archived. Version the live
    # material view as well, so an open scope check cannot appear current.
    rows = db.execute(select(Document.id, Document.metadata_revision, Document.archived, Document.removed_at, Document.status)
        .join(CollectionMember, CollectionMember.document_id == Document.id)
        .where(CollectionMember.collection_id == key).order_by(Document.id)).all()
    return hashlib.sha256(json.dumps([list(row) for row in rows], default=str).encode()).hexdigest()


def attach_uploaded(db, collection_id, document):
    """An additive upload action, idempotent under the collection row lock.

    A collection archived while an upload was in flight must not discard the
    globally retained original or claim that it was added to a usable scope.
    """
    if not collection_id: return None
    value = db.scalar(select(KnowledgeCollection).where(KnowledgeCollection.id == collection_id).with_for_update())
    reason = "collection_unavailable" if not value or value.archived else "document_unavailable" if document.archived or document.removed_at else None
    if reason: return {"collection_id": collection_id, "status": "not_added", "reason": reason}
    if db.get(CollectionMember, (collection_id, document.id)):
        return {"collection_id": collection_id, "status": "already_member", "revision": value.revision}
    count = db.scalar(select(func.count()).select_from(CollectionMember).where(CollectionMember.collection_id == collection_id))
    if count >= MAX_MEMBERS: return {"collection_id": collection_id, "status": "not_added", "reason": "collection_limit"}
    db.add(CollectionMember(collection_id=collection_id, document_id=document.id))
    audit(db, value, "upload_added", "Upload/import explicitly targeted this collection",
          {"added": [{"id": document.id, "version": document.version, "sha256": document.sha256}]})
    return {"collection_id": collection_id, "status": "added", "revision": value.revision}


class CollectionRepository:
    def __init__(self, bind=None): self.bind = bind

    def create(self, inputs):
        with transaction(self.bind) as db:
            value = KnowledgeCollection(id=str(uuid4()), revision=1, archived=False, **inputs.model_dump())
            db.add(value); db.flush()
            audit(db, value, "created", "Collection created by the user", initial=True)
            return summary(value)

    def list(self, query="", archived=False, page=1, page_size=20):
        if not 1 <= page <= 100000 or not 1 <= page_size <= 100: raise ValueError("Invalid collection page")
        conditions = [KnowledgeCollection.archived == archived]
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(KnowledgeCollection.name.ilike("%" + escaped + "%", escape="\\") |
                              KnowledgeCollection.description.ilike("%" + escaped + "%", escape="\\"))
        with transaction(self.bind) as db:
            total = db.scalar(select(func.count()).select_from(KnowledgeCollection).where(*conditions))
            items = db.scalars(select(KnowledgeCollection).where(*conditions).order_by(KnowledgeCollection.updated_at.desc(), KnowledgeCollection.record_order.desc())
                .offset((page-1)*page_size).limit(page_size)).all()
            counts = statistics(db, [item.id for item in items])
            return {"collections": [{**summary(item), "coverage": counts[item.id]} for item in items],
                    "total": total, "page": page, "page_size": page_size}

    def detail(self, key):
        with transaction(self.bind) as db:
            value = collection(db, key)
            return {**summary(value), "coverage": statistics(db, [key])[key], "material_revision": material_revision(db, key)}

    def edit(self, key, inputs):
        with transaction(self.bind) as db:
            value = collection(db, key, lock=True)
            self.check(value, inputs.expected_revision)
            for field in COLLECTION_FIELDS: setattr(value, field, getattr(inputs, field))
            audit(db, value, "metadata_edited", inputs.reason)
            return summary(value)

    @staticmethod
    def check(value, revision, *, allow_archived=False):
        if value.revision != revision: raise StateConflict("Collection changed elsewhere; reload before applying this action")
        if value.archived and not allow_archived: raise StateConflict("Restore this collection before changing its contents")

    def archive(self, key, expected_revision, archived=True):
        with transaction(self.bind) as db:
            value = collection(db, key, lock=True)
            self.check(value, expected_revision, allow_archived=True)
            if value.archived != archived:
                value.archived = archived
                audit(db, value, "archived" if archived else "restored", "User explicitly changed collection availability")
            return summary(value)

    def members(self, key, inputs):
        with transaction(self.bind) as db:
            value = collection(db, key, lock=True)
            self.check(value, inputs.expected_revision)
            documents = db.scalars(select(Document).where(Document.id.in_(inputs.document_ids))).all()
            if len(documents) != len(inputs.document_ids): raise MissingRecord("A selected document does not exist")
            if inputs.action == "add" and any(item.archived or item.removed_at for item in documents):
                raise StateConflict("Restore unavailable documents before adding them to a collection")
            existing = set(db.scalars(select(CollectionMember.document_id).where(CollectionMember.collection_id == key)))
            changed = [item for item in documents if (item.id not in existing if inputs.action == "add" else item.id in existing)]
            if inputs.action == "add" and len(existing) + len(changed) > MAX_MEMBERS:
                raise StateConflict("Collection exceeds 5000 document versions; use another collection")
            if changed:
                if inputs.action == "add": db.add_all(CollectionMember(collection_id=key, document_id=item.id) for item in changed)
                else: db.execute(delete(CollectionMember).where(CollectionMember.collection_id == key, CollectionMember.document_id.in_([item.id for item in changed])))
                audit(db, value, "members_added" if inputs.action == "add" else "members_removed", "User changed the explicitly selected document versions",
                      {"added" if inputs.action == "add" else "removed": [{"id": item.id, "version": item.version, "sha256": item.sha256} for item in changed]})
            return {**summary(value), "changed": len(changed)}

    def history(self, key, page=1, page_size=20):
        with transaction(self.bind) as db:
            collection(db, key)
            count = db.scalar(select(func.count()).select_from(CollectionRevision).where(CollectionRevision.collection_id == key))
            rows = db.scalars(select(CollectionRevision).where(CollectionRevision.collection_id == key)
                .order_by(CollectionRevision.revision.desc()).offset((page-1)*page_size).limit(page_size)).all()
            return {"revisions": [{"revision": row.revision, "operation": row.operation, "snapshot": row.body,
                                    "reason": row.reason, "actor": row.actor, "created_at": row.created_at} for row in rows], "total": count}

    def scope(self, inputs: ScopeRequest, *, session=None):
        from contextlib import nullcontext
        with (nullcontext(session) if session is not None else transaction(self.bind)) as db:
            collections = [collection(db, key) for key in inputs.collection_ids]
            if any(item.archived for item in collections): raise StateConflict("An archived collection cannot be used for new research")
            membership = exists(select(CollectionMember.document_id).where(CollectionMember.document_id == Document.id,
                CollectionMember.collection_id.in_(inputs.collection_ids)))
            rows = db.scalars(select(Document).where(membership | Document.id.in_(inputs.document_ids))
                .order_by(Document.id).limit(MAX_MEMBERS+1)).all()
            if len(rows) > MAX_MEMBERS: raise StateConflict("Selected scope exceeds 5000 document versions; narrow the collections")
            if set(inputs.document_ids) - {item.id for item in rows}: raise MissingRecord("An explicitly selected document does not exist")
            zone = ZoneInfo(MARKET_ZONES[inputs.market])
            local_day = inputs.as_of or inputs.as_of_at.astimezone(zone).date()
            boundary = inputs.as_of_at or datetime.combine(local_day + timedelta(days=1), time.min, zone)
            documents = []
            for item in rows:
                reason = "original_removed" if item.removed_at else "document_archived" if item.archived else None
                warning = None
                if reason is None:
                    if item.published_at:
                        if item.published_at > boundary or inputs.as_of and item.published_at == boundary: reason = "published_after_cutoff"
                    elif item.published_on:
                        if item.published_on > local_day: reason = "published_after_cutoff"
                        elif inputs.as_of_at and item.published_on == local_day: reason = "publication_precision_insufficient"
                    else:
                        reason = "publication_unknown" if inputs.mode == "strict" else None
                        warning = "publication_unknown" if inputs.mode == "explore" else None
                documents.append({"id": item.id, "version": item.version, "metadata_revision": item.metadata_revision,
                    "sha256": item.sha256, "title": item.title, "status": item.status,
                    "published_on": item.published_on.isoformat() if item.published_on else None,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                    "eligible": reason is None, "exclusion": reason, "warning": warning})
            result = {"collections": [{"id": item.id, "revision": item.revision, "name": item.name} for item in collections],
                      "cutoff": inputs.model_dump(mode="json", exclude={"collection_ids", "document_ids"}), "timezone": zone.key,
                      "documents": documents, "eligible_count": sum(item["eligible"] for item in documents),
                      "excluded_count": sum(not item["eligible"] for item in documents), "semantic_index": "not_checked"}
            result["scope_fingerprint"] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            return result

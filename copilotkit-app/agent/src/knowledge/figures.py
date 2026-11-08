"""Reviewed numeric evidence and immutable calculation records in PostgreSQL."""
from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import uuid4

from sqlalchemy import func, select
from src.persistence.database import transaction
from src.persistence.jobs import MissingRecord, StateConflict
from src.persistence.models import (CollectionMember, Document, DocumentPage, DocumentReference,
    KnowledgeCalculation, KnowledgeCollection, KnowledgeFigure, KnowledgeSearch)
from .calculations import arithmetic, check_unit, numeric_tokens, numeric_value, unit_spans
from .contracts import ScopeRequest
from .repository import CollectionRepository


def collection(db, key, *, lock=False, active=True):
    query = select(KnowledgeCollection).where(KnowledgeCollection.id == key)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None: raise MissingRecord("Knowledge collection does not exist")
    if active and row.archived: raise StateConflict("Restore the collection before reviewing or calculating figures")
    return row


def current_evidence(db, hit, *, lock=False):
    query = select(Document).where(Document.id == hit["document_id"])
    doc = db.scalar(query.with_for_update() if lock else query)
    page = db.get(DocumentPage, (hit["document_id"], hit["page_number"]))
    if (doc is None or doc.archived or doc.removed_at is not None or doc.sha256 != hit["document_sha256"]
            or doc.metadata_revision != hit["metadata_revision"] or page is None or page.status != "text_ready"
            or page.extraction_version != hit["extraction_version"]
            or page.text[hit["start_offset"]:hit["end_offset"]] != hit["quote"]):
        raise StateConflict("Source changed or is unavailable; search and review the current original again")
    return doc, page


def source_hit(db, key, search_id, citation_id, *, lock=False):
    if key: collection(db, key, lock=lock)
    saved = db.get(KnowledgeSearch, str(search_id))
    if saved is None: raise MissingRecord("Saved search does not exist")
    hit = next((item for item in saved.result["hits"] if item["citation_id"] == citation_id), None)
    if hit is None: raise MissingRecord("Citation does not exist in this search")
    if key and db.get(CollectionMember, (key, hit["document_id"])) is None:
        raise StateConflict("This original version is not in the selected collection")
    scope = ScopeRequest.model_validate(saved.scope)
    allowed = {d["id"] for d in CollectionRepository(db.bind).scope(scope, session=db)["documents"] if d["eligible"]}
    if hit["document_id"] not in allowed: raise StateConflict("The original no longer meets this search's cutoff and scope")
    doc, page = current_evidence(db, hit, lock=lock)
    return {**hit, "search_id": saved.id,
            "citation_markdown": f"[{citation_id}](/evidence/{saved.id}/{citation_id})"}, doc, page


def quote_snapshot(doc, page, start, end):
    quote = page.text[start:end]
    return {"document_id": doc.id, "document_version": doc.version, "document_sha256": doc.sha256,
        "metadata_revision": doc.metadata_revision, "title": doc.title, "page_number": page.page_number,
        "extraction_version": page.extraction_version, "start_offset": start, "end_offset": end,
        "quote": quote, "quote_sha256": hashlib.sha256(quote.encode()).hexdigest()}


def figure_json(row):
    return {"id": row.id, "collection_id": row.collection_id, "revision": row.revision,
            "archived": row.archived, "created_at": row.created_at, "audit": row.audit, **row.body}


def calc_json(row):
    return {"id": row.id, "collection_id": row.collection_id, "request": row.request,
            "created_at": row.created_at, "thread_id": row.thread_id, **row.result}


class FigureRepository:
    def __init__(self, bind=None): self.bind = bind

    def context(self, key, search_id, citation_id):
        with transaction(self.bind) as db:
            hit, doc, page = source_hit(db, key, search_id, citation_id)
            start = max(0, hit["start_offset"]-1500)
            spans = [(page, 0, min(len(page.text), 1800)), (page, start, min(len(page.text), start+5000))]
            units = []
            for number in range(max(1, page.page_number-1), min(doc.page_count, page.page_number+1)+1):
                item = db.get(DocumentPage, (doc.id, number))
                if item is None or item.status != "text_ready": continue
                for candidate in unit_spans(item.text):
                    units.append({"page_number":number,**candidate})
                    if len(units)>=100:break
                if len(units) >= 100: break
            return {"source": hit, "subject": doc.issuer, "numbers": numeric_tokens(hit["quote"]), "unit_candidates": units,
                "period_start": doc.period_start, "period_end": doc.period_end,
                "context": [quote_snapshot(doc, p, a, b) for p, a, b in spans],
                "notice": "Exact text context; table columns, period and consolidation basis require explicit user review. Not visual/table reconstruction."}

    def create(self, key, inputs):
        with transaction(self.bind) as db:
            hit, doc, page = source_hit(db, key, inputs.search_id, inputs.citation_id, lock=True)
            if not doc.published_on and not doc.published_at: raise StateConflict("Verify the original's public release date before reviewing financial inputs")
            if not doc.issuer.strip(): raise StateConflict("Confirm the issuer in document metadata first")
            if {"start": inputs.value_start, "text": inputs.value_text} not in numeric_tokens(hit["quote"]):
                raise StateConflict("Choose a complete value at the exact source-token position")
            if inputs.value_text.endswith("%") and inputs.unit != "percent": raise StateConflict("A percentage source token is not a monetary amount")
            if abs(inputs.unit_page_number-page.page_number) > 1: raise StateConflict("Unit evidence must be on this or an adjacent page")
            unit_page = db.get(DocumentPage, (doc.id, inputs.unit_page_number))
            if (unit_page is None or unit_page.status != "text_ready" or
                    unit_page.text[inputs.unit_start:inputs.unit_start+len(inputs.unit_quote)] != inputs.unit_quote):
                raise StateConflict("The unit header does not match the exact retained source span")
            check_unit(inputs.unit_quote, inputs.currency, inputs.unit)
            if {"start":inputs.unit_start,"quote":inputs.unit_quote,"currency":inputs.currency,"unit":inputs.unit} not in unit_spans(unit_page.text):
                raise StateConflict("Select the complete unit expression; a substring can change the financial scale")
            body = {k: v for k, v in inputs.model_dump(mode="json").items() if k not in {"search_id", "citation_id", "confirmation", "reason", "unit_start", "unit_page_number", "unit_quote"}}
            body.update(value=str(numeric_value(inputs.value_text)), subject=doc.issuer, source=hit,
                unit_source=quote_snapshot(doc, unit_page, inputs.unit_start, inputs.unit_start+len(inputs.unit_quote)),
                review="user_confirmed_column_period_basis", reviewer_note=inputs.reason)
            semantic={name:body[name] for name in ("unit","currency","period_type","period_start","period_end")}
            semantic.update(document_id=doc.id,metadata_revision=doc.metadata_revision,page_number=hit["page_number"],
                value_position=hit["start_offset"]+inputs.value_start,metric=inputs.metric.casefold(),basis=inputs.basis.casefold())
            fingerprint=hashlib.sha256(json.dumps(semantic,sort_keys=True).encode()).hexdigest()
            existing=db.scalar(select(KnowledgeFigure).where(KnowledgeFigure.collection_id==key,KnowledgeFigure.fingerprint==fingerprint))
            if existing:
                if existing.archived:raise StateConflict("An identical reviewed input is archived; restore it rather than silently recreating it")
                return {**figure_json(existing),"duplicate":True}
            row = KnowledgeFigure(id=str(uuid4()), collection_id=key, document_id=doc.id, fingerprint=fingerprint, revision=1, archived=False, body=body,
                audit=[{"operation": "confirmed", "reason": inputs.reason, "at": datetime.now(timezone.utc).isoformat()}])
            db.add(row)
            for evidence in (hit, body["unit_source"]):
                db.add(DocumentReference(id=str(uuid4()), document_id=doc.id, owner_type="knowledge_figure", owner_id=row.id, snapshot=evidence))
            db.flush(); return figure_json(row)

    def list(self, key, *, q="", archived=False, page=1, page_size=20):
        with transaction(self.bind) as db:
            collection(db, key, active=False)
            conditions = [KnowledgeFigure.collection_id == key, KnowledgeFigure.archived == archived]
            if q:
                escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                conditions.append(KnowledgeFigure.body["metric"].astext.ilike("%"+escaped+"%", escape="\\"))
            rows = db.scalars(select(KnowledgeFigure).where(*conditions).order_by(KnowledgeFigure.record_order.desc()).offset((page-1)*page_size).limit(page_size)).all()
            values=[]
            for row in rows:
                state="archived" if row.archived else "current"
                if not row.archived:
                    if db.get(CollectionMember,(key,row.document_id)) is None:state="removed_from_collection"
                    else:
                        try:current_evidence(db,row.body["source"]);current_evidence(db,row.body["unit_source"])
                        except StateConflict:state="source_changed"
                values.append({**figure_json(row),"availability":state})
            return {"figures": values, "total": db.scalar(select(func.count()).select_from(KnowledgeFigure).where(*conditions))}

    def archive(self, key, figure_id, inputs, archived=True):
        with transaction(self.bind) as db:
            collection(db, key, lock=True, active=False)
            row = db.scalar(select(KnowledgeFigure).where(KnowledgeFigure.id == figure_id, KnowledgeFigure.collection_id == key).with_for_update())
            if row is None: raise MissingRecord("Reviewed figure does not exist")
            if row.revision != inputs.expected_revision: raise StateConflict("This figure changed; refresh before deciding")
            if row.archived != archived:
                row.archived = archived; row.revision += 1
                row.audit = [*row.audit, {"operation": "archived" if archived else "restored", "reason": inputs.reason, "at": datetime.now(timezone.utc).isoformat()}]
            return figure_json(row)

    def calculate(self, key, inputs, *, thread_id=None, turn_id=None, eligible=None):
        with transaction(self.bind) as db:
            collection(db, key, lock=True)
            rows = {row.id: row for row in db.scalars(select(KnowledgeFigure).where(KnowledgeFigure.id.in_([str(x) for x in inputs.figure_ids])).order_by(KnowledgeFigure.id).with_for_update())}
            figures = []
            for figure_id in inputs.figure_ids:
                row = rows.get(str(figure_id))
                if row is None or row.collection_id != key or row.archived: raise StateConflict("Choose active reviewed inputs from this collection")
                if db.get(CollectionMember, (key, row.document_id)) is None: raise StateConflict("A reviewed input was removed from this collection")
                if eligible is not None and row.document_id not in eligible: raise StateConflict("A figure falls outside the conversation's current document cutoff")
                current_evidence(db, row.body["source"], lock=True); current_evidence(db, row.body["unit_source"])
                figures.append({"id": row.id, "revision": row.revision, **row.body})
            result = {**arithmetic(inputs, figures), "inputs": figures,
                "references": [item["source"] for item in figures], "status": "calculated"}
            row = KnowledgeCalculation(id=str(uuid4()), collection_id=key, thread_id=thread_id, turn_id=turn_id,
                request=inputs.model_dump(mode="json"), result=result)
            db.add(row)
            for item in figures:
                db.add(DocumentReference(id=str(uuid4()), document_id=item["source"]["document_id"], owner_type="knowledge_calculation", owner_id=row.id, snapshot=item["source"]))
            db.flush(); return calc_json(row)

    def calculations(self, key=None, *, thread_id=None, turn_id=None, page=1, page_size=20):
        with transaction(self.bind) as db:
            conditions = []
            if key: collection(db, key, active=False); conditions.append(KnowledgeCalculation.collection_id == key)
            if thread_id: conditions.append(KnowledgeCalculation.thread_id == thread_id)
            if turn_id: conditions.append(KnowledgeCalculation.turn_id == turn_id)
            if not conditions: raise ValueError("A calculation scope is required")
            rows = db.scalars(select(KnowledgeCalculation).where(*conditions).order_by(KnowledgeCalculation.record_order.desc()).offset((page-1)*page_size).limit(page_size)).all()
            return {"calculations": [calc_json(row) for row in rows], "total": db.scalar(select(func.count()).select_from(KnowledgeCalculation).where(*conditions))}

    def in_scope(self, eligible, query=""):
        with transaction(self.bind) as db:
            conditions = [KnowledgeFigure.document_id.in_(eligible), KnowledgeFigure.archived.is_(False), KnowledgeCollection.archived.is_(False)]
            if query:
                escaped=query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                conditions.append(KnowledgeFigure.body["metric"].astext.ilike("%"+escaped+"%", escape="\\"))
            rows=db.scalars(select(KnowledgeFigure).join(KnowledgeCollection, KnowledgeCollection.id==KnowledgeFigure.collection_id)
                .where(*conditions).order_by(KnowledgeFigure.record_order.desc()).limit(21)).all()
            available=[]; stale=0
            for row in rows[:20]:
                if db.get(CollectionMember,(row.collection_id,row.document_id)) is None: stale+=1;continue
                try: current_evidence(db,row.body["source"]);current_evidence(db,row.body["unit_source"])
                except StateConflict: stale+=1;continue
                available.append(figure_json(row))
            return {"figures":available,"truncated":len(rows)>20,"stale_excluded":stale}

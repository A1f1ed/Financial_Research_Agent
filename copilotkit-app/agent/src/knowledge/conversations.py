"""Immutable server-owned document-chat scopes and real retrieval references."""
import json
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from src.persistence.database import transaction
from src.persistence.jobs import MissingRecord, StateConflict
from src.persistence.models import ConversationSearch, KnowledgeConversation, KnowledgeSearch, Report
from .contracts import ScopeRequest, SearchRequest
from .repository import CollectionRepository


def serialize(row):
    return {"thread_id": row.thread_id, "scope": row.scope, "snapshot": row.snapshot,
            "search_mode": row.search_mode, "created_at": row.created_at}


class ConversationRepository:
    def __init__(self, bind=None): self.bind = bind

    def create(self, inputs):
        key = str(inputs.thread_id)
        scope = ScopeRequest.model_validate(inputs.model_dump(exclude={"thread_id", "search_mode"}))
        with transaction(self.bind) as db:
            existing = db.get(KnowledgeConversation, key)
            if existing:
                if existing.scope != scope.model_dump(mode="json") or existing.search_mode != inputs.search_mode:
                    raise StateConflict("This conversation has a fixed scope; create a new conversation to change it")
                return serialize(existing)
            if db.get(Report, key): raise StateConflict("Report conversations cannot be rebound to document research")
            if db.scalar(text("SELECT to_regclass('agent.checkpoints') IS NOT NULL")) and db.scalar(
                    text("SELECT EXISTS (SELECT 1 FROM agent.checkpoints WHERE thread_id=:key)"), {"key": key}):
                raise StateConflict("Existing chat history cannot be rebound; start a new document conversation")
            snapshot = CollectionRepository(self.bind).scope(scope, session=db)
            if not snapshot["documents"]: raise StateConflict("This scope has no document versions")
            if len(snapshot["documents"]) > 50: raise StateConflict("Select at most 50 exact document versions for a conversation")
            values = {"thread_id": key, "scope": scope.model_dump(mode="json"), "snapshot": snapshot, "search_mode": inputs.search_mode}
            db.execute(insert(KnowledgeConversation).values(**values).on_conflict_do_nothing())
            row = db.get(KnowledgeConversation, key)
            if row.scope != values["scope"] or row.search_mode != inputs.search_mode:
                raise StateConflict("This conversation already has a fixed scope; create a new conversation to change it")
            return serialize(row)

    def get(self, key):
        with transaction(self.bind) as db:
            row = db.get(KnowledgeConversation, key)
            return serialize(row) if row else None

    def current_scope(self, key):
        binding = self.get(key)
        if not binding: raise MissingRecord("Choose a document scope before asking about research material")
        for item in binding["snapshot"]["collections"]:
            if CollectionRepository(self.bind).detail(item["id"])["archived"]:
                raise StateConflict("The bound collection is archived; restore it or start a new scoped conversation")
        # Membership is pinned at creation. Current publication corrections and
        # global archives still apply, so old metadata never authorizes leakage.
        return ScopeRequest(**{**binding["scope"], "collection_ids": [],
            "document_ids": [item["id"] for item in binding["snapshot"]["documents"]]})

    def link(self, thread_id, turn_id, result):
        with transaction(self.bind) as db:
            binding = db.get(KnowledgeConversation, thread_id)
            stored = db.get(KnowledgeSearch, result["id"])
            if binding is None or stored is None: raise MissingRecord("Document conversation or search is missing")
            frozen = {item["id"] for item in binding.snapshot["documents"]}
            if (set(stored.scope.get("document_ids", [])) != frozen or stored.scope.get("collection_ids")
                    or stored.scope.get("search_mode") != binding.search_mode
                    or any(stored.scope.get(key) != binding.scope.get(key) for key in ("as_of", "as_of_at", "market", "mode"))
                    or any(hit["document_id"] not in frozen for hit in stored.result["hits"])):
                raise StateConflict("A retrieval from another scope cannot be attached to this conversation")
            db.execute(insert(ConversationSearch).values(thread_id=thread_id, turn_id=turn_id, search_id=result["id"]).on_conflict_do_nothing())

    def searches(self, thread_id, *, turn_id=None, limit=20):
        with transaction(self.bind) as db:
            query = select(KnowledgeSearch).join(ConversationSearch, ConversationSearch.search_id == KnowledgeSearch.id).where(ConversationSearch.thread_id == thread_id)
            if turn_id is not None: query = query.where(ConversationSearch.turn_id == turn_id)
            rows = db.scalars(query.order_by(KnowledgeSearch.record_order.desc()).limit(limit)).all()
            return [row.result for row in rows]

    def search_count(self, thread_id):
        with transaction(self.bind) as db:
            return db.scalar(select(func.count()).select_from(ConversationSearch).where(ConversationSearch.thread_id == thread_id))


def turn_id(messages):
    for message in reversed(messages):
        if getattr(message, "type", None) == "human": return str(message.id or "unidentified-turn")[:160]
    return "unidentified-turn"


def references(result):
    return [{**hit, "reference": f"{result['id']}:{hit['citation_id']}",
             "citation_markdown": f"[{hit['citation_id']}](/evidence/{result['id']}/{hit['citation_id']})"} for hit in result["hits"]]

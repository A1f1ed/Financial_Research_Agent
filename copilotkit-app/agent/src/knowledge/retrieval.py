"""Scope-first PostgreSQL keyword/pgvector search with durable citations."""
from datetime import datetime, timezone
import re
from time import perf_counter
from uuid import uuid4

from sqlalchemy import case, func, literal_column, or_, select, text
from src.persistence.database import transaction
from src.persistence.jobs import MissingRecord, StateConflict
from src.persistence.models import Document, DocumentReference, Job, KnowledgeChunk, KnowledgeIndex, KnowledgeSearch
from .embeddings import embed
from .indexing import index_profile
from .repository import CollectionRepository


def keyword_terms(query):
    terms = re.findall(r"[A-Za-z0-9][A-Za-z0-9._%-]*|[\u3400-\u9fff]+", query)
    result = []
    for term in terms:
        if re.fullmatch(r"[\u3400-\u9fff]+", term) and len(term) > 4:
            result.extend(term[i:i+2] for i in range(len(term)-1))
        else: result.append(term)
    return list(dict.fromkeys(result))[:24]


async def search(inputs, *, bind=None):
    began = perf_counter(); vector = None; usage = 0
    initial_scope = CollectionRepository(bind).scope(inputs)
    if inputs.search_mode == "hybrid":
        profile, profile_key = index_profile("hybrid")
        # Do not send a query to a model when scope has no eligible originals.
        if initial_scope["eligible_count"]:
            vectors, usage = await embed([inputs.query], profile["embedding"])
            vector = vectors[0]
    else: profile_key = None
    with transaction(bind) as db:
        # Snapshot membership, current publication metadata, indices and citations
        # within one consistent read. Slow embedding responses cannot overwrite a
        # newer range or use a document archived while the request was in flight.
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        scope = CollectionRepository(bind).scope(inputs, session=db)
        if scope["scope_fingerprint"] != initial_scope["scope_fingerprint"]:
            raise StateConflict("Research scope changed during search; review the current range and retry")
        eligible = {item["id"]: item for item in scope["documents"] if item["eligible"]}
        query = select(KnowledgeIndex).join(Job, Job.id == KnowledgeIndex.job_id).where(
            KnowledgeIndex.document_id.in_(eligible), KnowledgeIndex.published.is_(True), Job.status == "complete")
        if profile_key: query = query.where(KnowledgeIndex.profile_key == profile_key)
        indices = db.scalars(query.order_by(KnowledgeIndex.document_id, KnowledgeIndex.record_order.desc())
            .distinct(KnowledgeIndex.document_id)).all()
        by_index = {item.id: item for item in indices}
        ids = list(by_index)
        tsv = func.to_tsvector(literal_column("'simple'::regconfig"), KnowledgeChunk.text)
        tsq = func.websearch_to_tsquery(literal_column("'simple'::regconfig"), inputs.query)
        predicates = [KnowledgeChunk.text.ilike("%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%", escape="\\") for term in keyword_terms(inputs.query)]
        trigram = func.word_similarity(inputs.query, KnowledgeChunk.text)
        exact = sum((case((predicate, 1), else_=0) for predicate in predicates), 0)
        rank = func.ts_rank_cd(tsv, tsq) + exact + trigram
        keyword_rows = db.execute(select(KnowledgeChunk, rank.label("rank")).where(
            KnowledgeChunk.index_id.in_(ids), or_(tsv.op("@@")(tsq), trigram >= .18, *predicates))
            .order_by(rank.desc(), KnowledgeChunk.id).limit(50)).all() if ids else []
        vector_rows = db.execute(select(KnowledgeChunk, KnowledgeChunk.embedding.cosine_distance(vector).label("distance"))
            .where(KnowledgeChunk.index_id.in_(ids), KnowledgeChunk.embedding.is_not(None))
            .order_by(KnowledgeChunk.embedding.cosine_distance(vector), KnowledgeChunk.id).limit(50)).all() if ids and vector is not None else []
        scores = {}; chunks = {}; ranks = {}
        for channel, rows in (("keyword", keyword_rows), ("semantic", vector_rows)):
            for position, (chunk, value) in enumerate(rows, 1):
                chunks[chunk.id] = chunk
                scores[chunk.id] = scores.get(chunk.id, 0) + 1 / (60 + position)
                ranks.setdefault(chunk.id, {})[channel] = {"rank": position, "value": float(value)}
        chosen = sorted(scores, key=lambda key: (-scores[key], key))[:inputs.limit]
        search_id = str(uuid4()); hits = []
        documents = {item.id: item for item in db.scalars(select(Document).where(Document.id.in_(eligible)))} if eligible else {}
        for number, key in enumerate(chosen, 1):
            chunk = chunks[key]; index = by_index[chunk.index_id]; doc = documents[index.document_id]
            snapshot = {"citation_id": f"K{number}", "document_id": doc.id, "document_version": doc.version,
                "document_sha256": doc.sha256, "metadata_revision": doc.metadata_revision, "title": doc.title,
                "source_url": doc.source_url, "published_on": doc.published_on.isoformat() if doc.published_on else None,
                "published_at": doc.published_at.isoformat() if doc.published_at else None, "publication_warning": eligible[doc.id]["warning"],
                "index_id": index.id, "chunk_id": chunk.id, "page_number": chunk.page_number,
                "start_offset": chunk.start_offset, "end_offset": chunk.end_offset,
                "quote": chunk.text, "quote_sha256": chunk.text_sha256, "extraction_version": chunk.extraction_version,
                "score": scores[key], "channels": ranks[key]}
            hits.append(snapshot)
            db.add(DocumentReference(id=str(uuid4()), document_id=doc.id, owner_type="knowledge_search", owner_id=search_id, snapshot=snapshot))
        indexed = {row.document_id for row in indices}
        gaps = [{"document_id": key, "title": item["title"], "reason": "matching_index_missing"} for key, item in eligible.items() if key not in indexed]
        gaps.extend({"document_id": row.document_id, "reason": "pages_not_text_readable", "pages": row.omitted_pages} for row in indices if row.omitted_pages)
        result = {"id": search_id, "query": inputs.query, "search_mode": inputs.search_mode,
            "ranking": "reciprocal_rank_fusion_k60", "scope": scope, "hits": hits, "gaps": gaps,
            "profile_key": profile_key, "embedding_tokens": usage, "elapsed_ms": round((perf_counter()-began)*1000, 3),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "notice": "Retrieved source excerpts are evidence candidates, not a generated or verified financial answer."}
        db.add(KnowledgeSearch(id=search_id, query=inputs.query, scope=inputs.model_dump(mode="json"), result=result))
        return result


def search_detail(key, *, bind=None):
    with transaction(bind) as db:
        row = db.get(KnowledgeSearch, key)
        if row is None: raise MissingRecord("Search record does not exist")
        return row.result

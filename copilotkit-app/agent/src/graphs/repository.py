"""PostgreSQL authority for graph identities, evidence, reviews and versions.

Names never imply identity. Every change is serialized by the graph row lock;
Neo4j is a rebuildable projection, never the authority for review decisions.
"""
from datetime import datetime, timezone
from contextlib import nullcontext
import hashlib
import json
from uuid import uuid4

from sqlalchemy import func, select
from src.knowledge.contracts import ScopeRequest
from src.knowledge.repository import CollectionRepository
from src.persistence.database import transaction
from src.persistence.jobs import MissingRecord, StateConflict
from src.persistence.models import (Document, DocumentPage, DocumentReference, GraphAudit, GraphEntity,
    GraphProjection, GraphQuery, GraphRelation, GraphExtractionCandidate, Job, ResearchGraph)

MAX_ENTITIES = 2000
MAX_RELATIONS = 5000


def graph_row(db, key, *, lock=False, active=False):
    query = select(ResearchGraph).where(ResearchGraph.id == key)
    if lock: query = query.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(query)
    if row is None: raise MissingRecord("Research graph does not exist")
    if active and row.archived: raise StateConflict("Restore the graph before changing or querying it")
    return row


def owned(db, model, key, graph_id):
    row = db.get(model, key)
    if row is None or row.graph_id != graph_id: raise MissingRecord("Graph object does not exist in this graph")
    return row


def check_revision(row, expected):
    if row.revision != expected: raise StateConflict("This object changed; reload it before applying your decision")


def entity_json(row):
    return {"id": row.id, "graph_id": row.graph_id, "revision": row.revision, "archived": row.archived, **row.body}


def relation_json(row):
    return {"id": row.id, "graph_id": row.graph_id, "revision": row.revision, "status": row.status,
        "source_id": row.source_id, "target_id": row.target_id, **row.body}


def graph_json(row):
    return {"id": row.id, "name": row.name, "description": row.description, "scope": row.scope,
        "snapshot": row.snapshot, "relation_types": row.relation_types, "revision": row.revision,
        "archived": row.archived, "projection_id": row.projection_id, "projected_revision": row.projected_revision,
        "projection_current": row.projected_revision == row.revision, "created_at": row.created_at, "updated_at": row.updated_at}


def audit(db, graph, object_type, row, operation, reason, snapshot, *, initial=False):
    from fastapi.encoders import jsonable_encoder
    if not initial: graph.revision += 1
    graph.updated_at = datetime.now(timezone.utc)
    db.add(GraphAudit(id=str(uuid4()), graph_id=graph.id, graph_revision=graph.revision,
        object_type=object_type, object_id=row.id, object_revision=row.revision, operation=operation,
        reason=reason, snapshot=jsonable_encoder(snapshot)))


def current_scope(db, graph, *, as_of=None):
    for item in graph.snapshot["collections"]:
        if CollectionRepository(db.bind).detail(item["id"])["archived"]:
            raise StateConflict("A source collection is archived; restore it or explicitly revise the graph scope")
    data = {**graph.scope, "collection_ids": [], "document_ids": [item["id"] for item in graph.snapshot["documents"]]}
    if as_of is not None: data.update(as_of=str(as_of), as_of_at=None)
    return CollectionRepository(db.bind).scope(ScopeRequest(**data), session=db)


def evidence_snapshots(db, graph, values):
    scope = current_scope(db, graph)
    eligible = {item["id"] for item in scope["documents"] if item["eligible"]}
    result = []
    for item in values:
        key = str(item.document_id)
        if key not in eligible: raise StateConflict("Evidence must be an eligible version in the graph's fixed material scope")
        doc = db.get(Document, key)
        page = db.get(DocumentPage, (key, item.page_number))
        if (page is None or page.status != "text_ready" or item.end_offset > len(page.text)
                or page.text[item.start_offset:item.end_offset] != item.quote):
            raise StateConflict("Evidence must match the exact retained text and offsets on the selected page")
        result.append({**item.model_dump(mode="json"), "document_version": doc.version, "document_sha256": doc.sha256,
            "metadata_revision": doc.metadata_revision, "title": doc.title, "source_url": doc.source_url,
            "published_on": doc.published_on.isoformat() if doc.published_on else None,
            "published_at": doc.published_at.isoformat() if doc.published_at else None,
            "extraction_version": page.extraction_version, "quote_sha256": hashlib.sha256(item.quote.encode()).hexdigest()})
    return result


def evidence_current(db, evidence, eligible):
    if not evidence: return False
    for item in evidence:
        if item["document_id"] not in eligible: return False
        doc = db.get(Document, item["document_id"])
        page = db.get(DocumentPage, (item["document_id"], item["page_number"]))
        if (doc is None or doc.metadata_revision != item["metadata_revision"] or doc.sha256 != item["document_sha256"]
                or page is None or page.status != "text_ready" or page.extraction_version != item["extraction_version"]
                or page.text[item["start_offset"]:item["end_offset"]] != item["quote"]): return False
    return True


def retain_references(db, owner_type, row):
    for item in row.body["evidence"]:
        db.add(DocumentReference(id=str(uuid4()), document_id=item["document_id"], owner_type=owner_type,
            owner_id=row.id, snapshot={**item, "graph_id": row.graph_id, "object_revision": row.revision}))


def pinned_scope(db, scope):
    snapshot = CollectionRepository(db.bind).scope(scope, session=db)
    if not snapshot["documents"]: raise StateConflict("Select at least one document version")
    if len(snapshot["documents"]) > 50: raise StateConflict("A research graph supports at most 50 exact document versions")
    return snapshot


class GraphRepository:
    def __init__(self, bind=None): self.bind = bind

    def create(self, inputs):
        with transaction(self.bind) as db:
            row = ResearchGraph(id=str(uuid4()), name=inputs.name, description=inputs.description,
                scope=inputs.scope.model_dump(mode="json"), snapshot=pinned_scope(db, inputs.scope),
                relation_types=list(dict.fromkeys(inputs.relation_types)), revision=1, archived=False, projected_revision=0)
            db.add(row); db.flush()
            audit(db,row,"graph",row,"created","User selected an explicit material scope",graph_json(row),initial=True)
            return graph_json(row)

    def list(self, q="", archived=False, page=1, page_size=20):
        with transaction(self.bind) as db:
            conditions = [ResearchGraph.archived == archived]
            if q.strip(): conditions.append(ResearchGraph.name.icontains(q.strip(), autoescape=True))
            rows = db.scalars(select(ResearchGraph).where(*conditions).order_by(ResearchGraph.record_order.desc())
                .offset((page-1)*page_size).limit(page_size)).all()
            count = db.scalar(select(func.count()).select_from(ResearchGraph).where(*conditions))
            return {"graphs": [graph_json(row) for row in rows], "total": count}

    def detail(self, key):
        with transaction(self.bind) as db:
            row = graph_row(db,key)
            counts = dict(db.execute(select(GraphRelation.status,func.count()).where(GraphRelation.graph_id==key).group_by(GraphRelation.status)).all())
            entity_count = db.scalar(select(func.count()).select_from(GraphEntity).where(GraphEntity.graph_id==key,GraphEntity.archived.is_(False)))
            latest = db.execute(select(GraphProjection,Job).join(Job,Job.id==GraphProjection.job_id).where(GraphProjection.graph_id==key)
                .order_by(GraphProjection.record_order.desc()).limit(1)).first()
            return {**graph_json(row), "entity_count":entity_count,"relation_counts":counts,
                "extracted_candidate_count":db.scalar(select(func.count()).select_from(GraphExtractionCandidate).where(GraphExtractionCandidate.graph_id==key,GraphExtractionCandidate.status=="pending")),
                "latest_projection": {"id":latest[0].id,"graph_revision":latest[0].graph_revision,"job_id":latest[1].id,
                    "status":latest[1].status,"error":latest[1].error,"published":latest[0].published} if latest else None}

    def edit(self, key, inputs):
        with transaction(self.bind) as db:
            row = graph_row(db,key,lock=True,active=True); check_revision(row,inputs.expected_revision)
            snapshot = pinned_scope(db, inputs.scope)
            row.name, row.description = inputs.name, inputs.description
            row.scope, row.snapshot, row.relation_types = inputs.scope.model_dump(mode="json"), snapshot, list(dict.fromkeys(inputs.relation_types))
            audit(db,row,"graph",row,"scope_revised",inputs.reason,{**graph_json(row),"revision":row.revision+1})
            return graph_json(row)

    def archive(self, key, inputs, archived=True):
        with transaction(self.bind) as db:
            row = graph_row(db,key,lock=True); check_revision(row,inputs.expected_revision)
            if row.archived != archived:
                row.archived = archived
                audit(db,row,"graph",row,"archived" if archived else "restored",inputs.reason,{**graph_json(row),"revision":row.revision+1})
            return graph_json(row)

    def entities(self, key, q="", archived=False, page=1, page_size=20):
        with transaction(self.bind) as db:
            graph_row(db,key)
            conditions = [GraphEntity.graph_id==key,GraphEntity.archived==archived]
            if q.strip():
                from sqlalchemy import or_
                conditions.append(or_(GraphEntity.body["name"].astext.icontains(q.strip(),autoescape=True),
                    GraphEntity.body["aliases"].astext.icontains(q.strip(),autoescape=True)))
            rows = db.scalars(select(GraphEntity).where(*conditions).order_by(GraphEntity.record_order).offset((page-1)*page_size).limit(page_size)).all()
            return {"entities":[entity_json(row) for row in rows],"total":db.scalar(select(func.count()).select_from(GraphEntity).where(*conditions))}

    def entity(self, key, entity_id):
        with transaction(self.bind) as db:
            graph_row(db,key); row=owned(db,GraphEntity,entity_id,key)
            impact=db.scalar(select(func.count()).select_from(GraphRelation).where(GraphRelation.graph_id==key,
                (GraphRelation.source_id==entity_id)|(GraphRelation.target_id==entity_id),GraphRelation.status=="accepted"))
            return {**entity_json(row),"accepted_relation_count":impact}

    def save_entity(self, key, inputs, entity_id=None, *, session=None):
        with (nullcontext(session) if session is not None else transaction(self.bind)) as db:
            graph=graph_row(db,key,lock=True,active=True)
            body=inputs.model_dump(mode="json",exclude={"expected_revision","reason"})
            body["evidence"]=evidence_snapshots(db,graph,inputs.evidence)
            if entity_id:
                row=owned(db,GraphEntity,entity_id,key); check_revision(row,inputs.expected_revision)
                if row.archived: raise StateConflict("Restore this entity before editing it")
                row.revision+=1; row.body=body
                affected=db.scalars(select(GraphRelation).where(GraphRelation.graph_id==key,GraphRelation.status=="accepted",
                    (GraphRelation.source_id==entity_id)|(GraphRelation.target_id==entity_id))).all()
                for edge in affected:
                    edge.status="candidate"; edge.revision+=1
                    audit(db,graph,"relation",edge,"identity_changed_requires_review",
                        "Endpoint identity revised; the relationship must be explicitly reviewed again",relation_json(edge))
            else:
                if db.scalar(select(func.count()).select_from(GraphEntity).where(GraphEntity.graph_id==key))>=MAX_ENTITIES:
                    raise StateConflict("Narrow the graph; it has reached its entity limit")
                # Same names remain separate stable IDs, including across kinds.
                row=GraphEntity(id=str(uuid4()),graph_id=key,revision=1,body=body,archived=False); db.add(row)
            db.flush(); retain_references(db,"graph_entity",row)
            audit(db,graph,"entity",row,"revised" if entity_id else "created",getattr(inputs,"reason","User added an evidenced identity"),entity_json(row))
            return entity_json(row)

    def archive_entity(self, key, entity_id, inputs, archived=True):
        with transaction(self.bind) as db:
            graph=graph_row(db,key,lock=True,active=True); row=owned(db,GraphEntity,entity_id,key); check_revision(row,inputs.expected_revision)
            if row.archived != archived:
                row.revision+=1; row.archived=archived
                audit(db,graph,"entity",row,"archived" if archived else "restored",inputs.reason,entity_json(row))
            return entity_json(row)

    def relations(self, key, status=None, entity_id=None, page=1, page_size=20, relation_id=None):
        with transaction(self.bind) as db:
            graph_row(db,key); conditions=[GraphRelation.graph_id==key]
            if status: conditions.append(GraphRelation.status==status)
            if entity_id: conditions.append((GraphRelation.source_id==entity_id)|(GraphRelation.target_id==entity_id))
            if relation_id: conditions.append(GraphRelation.id==relation_id)
            rows=db.scalars(select(GraphRelation).where(*conditions).order_by(GraphRelation.record_order.desc()).offset((page-1)*page_size).limit(page_size)).all()
            endpoint_ids={value for row in rows for value in (row.source_id,row.target_id)}
            names={row.id:row.body["name"] for row in db.scalars(select(GraphEntity).where(GraphEntity.graph_id==key,GraphEntity.id.in_(endpoint_ids)))}
            return {"relations":[{**relation_json(row),"source_name":names.get(row.source_id),"target_name":names.get(row.target_id)} for row in rows],
                "total":db.scalar(select(func.count()).select_from(GraphRelation).where(*conditions))}

    def relation(self, key, relation_id):
        with transaction(self.bind) as db:
            graph_row(db,key); return relation_json(owned(db,GraphRelation,relation_id,key))

    def save_relation(self, key, inputs, relation_id=None, *, session=None):
        with (nullcontext(session) if session is not None else transaction(self.bind)) as db:
            graph=graph_row(db,key,lock=True,active=True)
            for entity_id in (str(inputs.source_id),str(inputs.target_id)):
                if owned(db,GraphEntity,entity_id,key).archived: raise StateConflict("Restore both endpoint entities first")
            if inputs.relation_type not in graph.relation_types: raise StateConflict("This relationship type is outside the graph configuration")
            body=inputs.model_dump(mode="json",exclude={"source_id","target_id","expected_revision","reason"})
            body["evidence"]=evidence_snapshots(db,graph,inputs.evidence)
            signature={"source_id":str(inputs.source_id),"target_id":str(inputs.target_id),**{k:v for k,v in body.items() if k not in {"explanation","extraction_version","evidence"}},
                "evidence":[{k:item[k] for k in ("document_id","page_number","start_offset","end_offset","quote_sha256")} for item in body["evidence"]]}
            body["fingerprint"]=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()
            duplicate=db.scalar(select(GraphRelation).where(GraphRelation.graph_id==key,GraphRelation.body["fingerprint"].astext==body["fingerprint"],GraphRelation.id!=(relation_id or "")))
            if duplicate:
                if relation_id: raise StateConflict("This candidate already exists; review the retained object")
                return {**relation_json(duplicate),"existing":True}
            if relation_id:
                row=owned(db,GraphRelation,relation_id,key); check_revision(row,inputs.expected_revision)
                if row.body["assertion"]=="inferred" and inputs.assertion=="disclosed":
                    raise StateConflict("Inference cannot be relabeled as disclosure; create a separately evidenced candidate")
                row.revision+=1; row.source_id=str(inputs.source_id); row.target_id=str(inputs.target_id); row.body=body; row.status="candidate"
            else:
                if db.scalar(select(func.count()).select_from(GraphRelation).where(GraphRelation.graph_id==key))>=MAX_RELATIONS:
                    raise StateConflict("Narrow the graph; it has reached its relationship limit")
                row=GraphRelation(id=str(uuid4()),graph_id=key,source_id=str(inputs.source_id),target_id=str(inputs.target_id),revision=1,status="candidate",body=body); db.add(row)
            db.flush(); retain_references(db,"graph_relation",row)
            audit(db,graph,"relation",row,"revised_for_review" if relation_id else "proposed",getattr(inputs,"reason","User proposed an evidenced relationship"),relation_json(row))
            return relation_json(row)

    def review(self, key, relation_id, inputs):
        with transaction(self.bind) as db:
            graph=graph_row(db,key,lock=True,active=True); row=owned(db,GraphRelation,relation_id,key); check_revision(row,inputs.expected_revision)
            allowed={"accept":({"candidate"},"accepted"),"reject":({"candidate"},"rejected"),"revoke":({"accepted"},"revoked")}
            previous, target=allowed[inputs.action]
            if row.status not in previous: raise StateConflict("This decision is not valid for the current review state")
            if inputs.action=="accept":
                scope=current_scope(db,graph); eligible={item["id"] for item in scope["documents"] if item["eligible"]}
                if not row.body["valid_from"]: raise StateConflict("Resolve the missing applicability date before accepting")
                if row.body["relation_type"] not in graph.relation_types or not evidence_current(db,row.body["evidence"],eligible):
                    raise StateConflict("Evidence or graph scope changed; revise and re-review this candidate")
                for entity_id in (row.source_id,row.target_id):
                    entity=owned(db,GraphEntity,entity_id,key)
                    if entity.archived or not evidence_current(db,entity.body["evidence"],eligible):
                        raise StateConflict("Resolve the endpoint identity and its source evidence before accepting")
            row.status=target; row.revision+=1
            audit(db,graph,"relation",row,target,inputs.reason,relation_json(row))
            return relation_json(row)

    def history(self, key, object_id=None, page=1, page_size=20):
        with transaction(self.bind) as db:
            graph_row(db,key); conditions=[GraphAudit.graph_id==key]
            if object_id: conditions.append(GraphAudit.object_id==object_id)
            rows=db.scalars(select(GraphAudit).where(*conditions).order_by(GraphAudit.record_order.desc()).offset((page-1)*page_size).limit(page_size)).all()
            return {"revisions":[{"id":row.id,"graph_revision":row.graph_revision,"object_type":row.object_type,"object_id":row.object_id,
                "object_revision":row.object_revision,"operation":row.operation,"reason":row.reason,"snapshot":row.snapshot,"created_at":row.created_at} for row in rows],
                "total":db.scalar(select(func.count()).select_from(GraphAudit).where(*conditions))}

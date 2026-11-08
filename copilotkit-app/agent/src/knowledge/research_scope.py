"""Pin explicit knowledge versions at submission; never recapture a live collection in a worker."""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, exists
from src.persistence.models import CollectionMember, Document, DocumentReference
from src.persistence.database import transaction
from src.persistence.jobs import StateConflict
from .contracts import ScopeRequest, SearchRequest
from .repository import CollectionRepository, collection


def pin_research_scope(config, db):
    keys=config.knowledge_collection_ids
    if not keys:return None
    for key in sorted(keys):
        if collection(db,key,lock=True).archived:raise StateConflict("An archived collection cannot be used for new research")
    membership=exists(select(CollectionMember.document_id).where(CollectionMember.document_id==Document.id,CollectionMember.collection_id.in_(keys)))
    documents=db.scalars(select(Document).where(membership).order_by(Document.id).limit(51).with_for_update().execution_options(populate_existing=True)).all()
    if not documents:raise StateConflict("Selected research collections contain no document versions")
    if len(documents)>50:raise StateConflict("Select at most 50 exact document versions for research")
    snapshot=CollectionRepository().scope(ScopeRequest(collection_ids=keys,as_of=config.as_of,market=config.market),session=db)
    return jsonable_encoder({**snapshot,"search_mode":config.knowledge_search_mode,"pinned_at":datetime.now(timezone.utc)})


def prepare_job_config(raw,db):
    # Internal snapshots are derived exclusively from validated selection, even
    # when another server call supplies a pre-existing raw config dictionary.
    config=dict(raw);config.pop("_knowledge_snapshot",None)
    if config.get("knowledge_collection_ids"):
        if config.get("_brief"):raise StateConflict("Knowledge collections are currently supported on single-stock research tasks")
        from src.research_models import ResearchConfig
        config["_knowledge_snapshot"]=pin_research_scope(ResearchConfig.model_validate(config),db)
    return config


async def collect_research_documents(config,snapshot,report_id):
    from .retrieval import search
    if snapshot is None:raise StateConflict("Research document versions were not pinned at submission")
    if snapshot["cutoff"]["as_of"]!=str(config.as_of) or snapshot["cutoff"]["market"]!=config.market:
        raise StateConflict("Pinned research cutoff does not match the task")
    pinned={d["id"]:d for d in snapshot["documents"]}
    gaps=[];eligible=[]
    if pinned:
        live=CollectionRepository().scope(ScopeRequest(document_ids=list(pinned),as_of=config.as_of,market=config.market))
        for item in live["documents"]:
            before=pinned[item["id"]]
            if not before["eligible"]:gaps.append(f"Knowledge document {item['id']}: excluded at submission ({before['exclusion']})");continue
            if not item["eligible"]:gaps.append(f"Knowledge document {item['id']}: unavailable ({item['exclusion']})");continue
            if any(item[field]!=before[field] for field in ("version","metadata_revision","sha256")):
                gaps.append(f"Knowledge document {item['id']}: source metadata/version changed after submission; start a new task to use it");continue
            eligible.append(item["id"])
    if not eligible:return {"hits":[],"gaps":[*gaps,"No pinned document evidence is currently eligible"],"search_id":None,"snapshot":snapshot}
    request=SearchRequest(document_ids=eligible,as_of=config.as_of,market=config.market,query=config.question[:500],search_mode=snapshot["search_mode"],limit=8)
    result=await search(request)
    # Retain a report-specific reference in addition to the search's own exact
    # page snapshot. This makes original retention independent of collection edits.
    with transaction() as db:
        retained=[]
        for hit in result["hits"]:
            doc=db.scalar(select(Document).where(Document.id==hit["document_id"]).with_for_update().execution_options(populate_existing=True))
            before=pinned[hit["document_id"]]
            if not doc or doc.archived or doc.removed_at or any(getattr(doc,field)!=before[field] for field in ("version","metadata_revision","sha256")):
                gaps.append(f"Knowledge document {hit['document_id']}: source changed during retrieval; excerpt excluded")
                continue
            retained.append(hit)
            db.add(DocumentReference(id=str(uuid4()),document_id=hit["document_id"],owner_type="research_report",owner_id=report_id,
                snapshot={"search_id":result["id"],**hit}))
    return {"hits":retained,"gaps":[*gaps,*[str(gap) for gap in result["gaps"]]],"search_id":result["id"],"snapshot":snapshot}


def merge_document_evidence(evidence,result):
    sources=evidence["sources"]
    for hit in result["hits"]:
        sources.append({"id":f"S{len(sources)+1}","title":hit["title"],"kind":"filings","provider":"Knowledge library",
            "content":hit["quote"],"published_at":hit.get("published_at") or hit.get("published_on"),"excerpt_only":True,
            "url":hit.get("source_url") or f"/evidence/{result['search_id']}/{hit['citation_id']}","document_id":hit["document_id"],"page_number":hit["page_number"],
            "document_version":hit["document_version"],"metadata_revision":hit["metadata_revision"],"document_sha256":hit["document_sha256"],
            "knowledge_search_id":result["search_id"],"knowledge_citation_id":hit["citation_id"]})
    evidence["gaps"].extend(result["gaps"])
    evidence["knowledge_scope"]=result["snapshot"]
    evidence["knowledge_search_id"]=result["search_id"]
    return evidence

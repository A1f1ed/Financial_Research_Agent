"""Bounded graph operations; no browser access to credentials or raw Cypher."""
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from src.documents.api import authorize_write, run
from .contracts import EntityEdit, EntityInput, GraphEdit, GraphInput, GraphQueryInput, RelationEdit, RelationInput, ReviewInput, RevisionInput
from .projection import GraphUnavailable, query_graph, queue_projection, saved_queries
from .repository import GraphRepository
from .contracts import ExtractionOptions, ExtractionStart, ResolveCandidate
from .extraction import ExtractionRepository

router=APIRouter(prefix="/research/graphs")


@router.get("")
def graphs(q: str=Query(default="",max_length=200),archived: bool=False,page: int=Query(default=1,ge=1,le=100000),page_size: int=Query(default=20,ge=1,le=100)):
    return GraphRepository().list(q,archived,page,page_size)


@router.post("",status_code=201)
def create(inputs:GraphInput,request:Request):
    authorize_write(request); return run(lambda:GraphRepository().create(inputs))


@router.get("/{key}")
def detail(key:UUID): return run(lambda:GraphRepository().detail(str(key)))


@router.put("/{key}")
def edit(key:UUID,inputs:GraphEdit,request:Request):
    authorize_write(request); return run(lambda:GraphRepository().edit(str(key),inputs))


@router.post("/{key}/archive")
def archive(key:UUID,inputs:RevisionInput,request:Request):
    authorize_write(request); return run(lambda:GraphRepository().archive(str(key),inputs))


@router.post("/{key}/restore")
def restore(key:UUID,inputs:RevisionInput,request:Request):
    authorize_write(request); return run(lambda:GraphRepository().archive(str(key),inputs,False))


@router.get("/{key}/entities")
def entities(key:UUID,q:str=Query(default="",max_length=200),archived:bool=False,page:int=Query(default=1,ge=1,le=100000),page_size:int=Query(default=20,ge=1,le=100)):
    return run(lambda:GraphRepository().entities(str(key),q,archived,page,page_size))


@router.post("/{key}/entities",status_code=201)
def create_entity(key:UUID,inputs:EntityInput,request:Request):
    authorize_write(request); return run(lambda:GraphRepository().save_entity(str(key),inputs))


@router.get("/{key}/entities/{entity_id}")
def entity(key:UUID,entity_id:UUID): return run(lambda:GraphRepository().entity(str(key),str(entity_id)))


@router.put("/{key}/entities/{entity_id}")
def edit_entity(key:UUID,entity_id:UUID,inputs:EntityEdit,request:Request):
    authorize_write(request); return run(lambda:GraphRepository().save_entity(str(key),inputs,str(entity_id)))


@router.post("/{key}/entities/{entity_id}/archive")
def archive_entity(key:UUID,entity_id:UUID,inputs:RevisionInput,request:Request):
    authorize_write(request); return run(lambda:GraphRepository().archive_entity(str(key),str(entity_id),inputs))


@router.post("/{key}/entities/{entity_id}/restore")
def restore_entity(key:UUID,entity_id:UUID,inputs:RevisionInput,request:Request):
    authorize_write(request); return run(lambda:GraphRepository().archive_entity(str(key),str(entity_id),inputs,False))


@router.get("/{key}/relations")
def relations(key:UUID,status:Literal["candidate","accepted","rejected","revoked"]|None=None,entity_id:UUID|None=None,relation_id:UUID|None=None,
              page:int=Query(default=1,ge=1,le=100000),page_size:int=Query(default=20,ge=1,le=100)):
    return run(lambda:GraphRepository().relations(str(key),status,str(entity_id) if entity_id else None,page,page_size,str(relation_id) if relation_id else None))


@router.post("/{key}/relations",status_code=201)
def create_relation(key:UUID,inputs:RelationInput,request:Request):
    authorize_write(request); return run(lambda:GraphRepository().save_relation(str(key),inputs))


@router.get("/{key}/relations/{relation_id}")
def relation(key:UUID,relation_id:UUID): return run(lambda:GraphRepository().relation(str(key),str(relation_id)))


@router.put("/{key}/relations/{relation_id}")
def edit_relation(key:UUID,relation_id:UUID,inputs:RelationEdit,request:Request):
    authorize_write(request); return run(lambda:GraphRepository().save_relation(str(key),inputs,str(relation_id)))


@router.post("/{key}/relations/{relation_id}/review")
def review(key:UUID,relation_id:UUID,inputs:ReviewInput,request:Request):
    authorize_write(request); return run(lambda:GraphRepository().review(str(key),str(relation_id),inputs))


@router.get("/{key}/history")
def history(key:UUID,object_id:UUID|None=None,page:int=Query(default=1,ge=1,le=100000),page_size:int=Query(default=20,ge=1,le=100)):
    return run(lambda:GraphRepository().history(str(key),str(object_id) if object_id else None,page,page_size))


@router.post("/{key}/sync")
def sync(key:UUID,request:Request,force:bool=False):
    authorize_write(request); return run(lambda:queue_projection(str(key),force=force))


@router.post("/{key}/query")
def query(key:UUID,inputs:GraphQueryInput,request:Request):
    authorize_write(request)
    try: return run(lambda:query_graph(str(key),inputs))
    except GraphUnavailable as error: raise HTTPException(503,str(error)) from None


@router.get("/{key}/queries")
def queries(key:UUID,page:int=Query(default=1,ge=1,le=100000),page_size:int=Query(default=20,ge=1,le=100)):
    return run(lambda:saved_queries(str(key),page=page,page_size=page_size))


@router.get("/{key}/queries/{query_id}")
def stored_query(key:UUID,query_id:UUID): return run(lambda:saved_queries(str(key),query_id=str(query_id)))


@router.post("/{key}/extractions/preview")
def preview_extraction(key:UUID,inputs:ExtractionOptions,request:Request):
    authorize_write(request); return run(lambda:ExtractionRepository().preview(str(key),inputs))


@router.post("/{key}/extractions",status_code=201)
def start_extraction(key:UUID,inputs:ExtractionStart,request:Request):
    authorize_write(request); return run(lambda:ExtractionRepository().create(str(key),inputs))


@router.get("/{key}/extractions")
def extraction_runs(key:UUID,page:int=Query(default=1,ge=1,le=100000),page_size:int=Query(default=20,ge=1,le=100)):
    return run(lambda:ExtractionRepository().list(str(key),page,page_size))


@router.get("/{key}/extractions/{run_id}")
def extraction_run(key:UUID,run_id:UUID):return run(lambda:ExtractionRepository().detail(str(key),str(run_id)))


@router.get("/{key}/extracted-candidates")
def extraction_candidates(key:UUID,status:Literal["pending","resolved","rejected"]|None="pending",run_id:UUID|None=None,
    page:int=Query(default=1,ge=1,le=100000),page_size:int=Query(default=20,ge=1,le=100)):
    return run(lambda:ExtractionRepository().candidates(str(key),status,page,page_size,str(run_id) if run_id else None))


@router.get("/{key}/extracted-candidates/{candidate_id}")
def extraction_candidate(key:UUID,candidate_id:UUID):return run(lambda:ExtractionRepository().candidate(str(key),str(candidate_id)))


@router.post("/{key}/extracted-candidates/{candidate_id}/reject")
def reject_extraction_candidate(key:UUID,candidate_id:UUID,inputs:RevisionInput,request:Request):
    authorize_write(request);return run(lambda:ExtractionRepository().reject(str(key),str(candidate_id),inputs))


@router.post("/{key}/extracted-candidates/{candidate_id}/resolve")
def resolve_extraction_candidate(key:UUID,candidate_id:UUID,inputs:ResolveCandidate,request:Request):
    authorize_write(request);return run(lambda:ExtractionRepository().resolve(str(key),str(candidate_id),inputs))

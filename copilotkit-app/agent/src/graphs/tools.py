"""Read-only graph discovery/traversal within a server-bound document conversation."""
import hashlib
from datetime import datetime,timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from langchain.tools import tool,ToolRuntime
from src.persistence.database import transaction
from src.persistence.models import ResearchGraph,GraphEntity,KnowledgeSearch,DocumentReference
from src.persistence.jobs import StateConflict,MissingRecord
from src.knowledge.conversations import ConversationRepository,references
from src.knowledge.repository import CollectionRepository,MARKET_ZONES
from src.knowledge.tools import document_runtime_scope,numeric_reply
from .contracts import GraphQueryInput
from .repository import current_scope,evidence_current,graph_row
from .projection import query_graph,GraphUnavailable


def bound_scope(runtime):
    key,eligible,turn=document_runtime_scope(runtime)
    scope=ConversationRepository().current_scope(key)
    day=scope.as_of or scope.as_of_at.astimezone(ZoneInfo(MARKET_ZONES[scope.market])).date()
    return key,eligible,turn,scope,day


@tool
async def find_research_graph_entities(query:str,runtime:ToolRuntime):
    """Find up to 20 published graph identities in this conversation's fixed documents.

    Use a short company/institution/policy name, or empty for recent eligible
    identities. Returns IDs for read_research_graph_paths. No extraction,
    approval, synchronization or graph editing is permitted by this tool.
    """
    try:
        if len(query)>120:raise ValueError("Use a graph identity query of at most 120 characters")
        _,eligible,_,scope,day=bound_scope(runtime);found=[]
        with transaction() as db:
            graphs=db.scalars(select(ResearchGraph).where(ResearchGraph.archived.is_(False),ResearchGraph.projection_id.is_not(None)).order_by(ResearchGraph.record_order.desc()).limit(50)).all()
            for graph in graphs:
                if graph.scope["market"]!=scope.market or graph.projected_revision!=graph.revision:continue
                try:allowed=eligible&{d["id"] for d in current_scope(db,graph,as_of=day)["documents"] if d["eligible"]}
                except StateConflict:continue
                if not allowed:continue
                rows=db.scalars(select(GraphEntity).where(GraphEntity.graph_id==graph.id,GraphEntity.archived.is_(False)).order_by(GraphEntity.record_order.desc()).limit(200)).all()
                for row in rows:
                    if query and query.casefold() not in " ".join([row.body["name"],*row.body.get("aliases",[])]).casefold():continue
                    if evidence_current(db,row.body["evidence"],allowed):
                        found.append({"graph_id":graph.id,"graph_name":graph.name,"entity_id":row.id,"name":row.body["name"],"kind":row.body["kind"]})
                    if len(found)>=20:break
                if len(found)>=20:break
        output={"entities":found,"limits":{"graphs_scanned":50,"identities_per_graph":200,"returned":20},"notice":"Only current published graphs with original evidence in this conversation; no result is not proof that no economic relationship exists."}
    except (MissingRecord,StateConflict,ValueError) as error:output={"entities":[],"status":"graph_scope_unavailable","error":str(error)}
    except Exception as error:output={"entities":[],"status":"graph_service_failed","error":f"Graph discovery unavailable ({type(error).__name__})"}
    return numeric_reply(output,runtime,"find_research_graph_entities")


@tool
async def read_research_graph_paths(graph_id:str,entity_id:str,runtime:ToolRuntime,valid_on:str|None=None,include_inferred:bool=False):
    """Read accepted paths, at most two hops, within the fixed document cutoff.

    Use actual IDs from find_research_graph_entities. valid_on optionally asks
    about an earlier applicability date using knowledge available at the fixed
    cutoff. Inferred edges require an explicit include_inferred choice and must
    stay labeled inference. Cite exact returned original-page markdown links;
    path existence is not measured financial impact or a trading signal.
    """
    try:
        key,eligible,turn,scope,day=bound_scope(runtime)
        repository=ConversationRepository()
        if len(repository.searches(key,turn_id=turn,limit=8))>=8:raise StateConflict("This turn reached its eight-search limit")
        with transaction() as db:
            graph=graph_row(db,graph_id,active=True)
            if graph.scope["market"]!=scope.market:raise StateConflict("Graph market timezone differs from the bound document scope")
        result=query_graph(graph_id,GraphQueryInput(entity_id=entity_id,as_of=day,valid_on=valid_on,max_hops=2,include_inferred=include_inferred,name="Document conversation query"),allowed_document_ids=eligible)
        paths=result["paths"][:3];edge_ids={edge for path in paths for edge in path["edges"]};node_ids={entity_id}|{node for path in paths for node in path["nodes"]}
        nodes=[node for node in result["nodes"] if node["id"] in node_ids];edges=[edge for edge in result["edges"] if edge["id"] in edge_ids]
        hits=[];known={}
        def citations(item):
            labels=[]
            # The complete graph audit retains all evidence. Native chat sends
            # one bounded source excerpt per identity/relationship, explicitly.
            for source in item["evidence"][:1]:
                marker=(source["document_id"],source["page_number"],source["start_offset"])
                if marker not in known:
                    hit={**source,"quote":source["quote"][:600]};hit["end_offset"]=hit["start_offset"]+len(hit["quote"])
                    hit["quote_sha256"]=hashlib.sha256(hit["quote"].encode()).hexdigest();hit["citation_id"]=f"K{len(hits)+1}"
                    known[marker]=hit["citation_id"];hits.append(hit)
                labels.append(known[marker])
            return labels
        node_output=[{"id":node["id"],"name":node["name"],"kind":node["kind"],"source_citations":citations(node)} for node in nodes]
        edge_output=[{**{field:edge[field] for field in ("id","source_id","target_id","relation_type","assertion","valid_from","valid_until")},"explanation":edge["explanation"][:600],"source_citations":citations(edge)} for edge in edges]
        repository.current_scope(key)
        live=CollectionRepository().scope(scope)
        allowed={item["id"] for item in live["documents"] if item["eligible"]}
        with transaction() as db:
            if any(not evidence_current(db,[hit],allowed) for hit in hits):raise StateConflict("Original graph evidence changed during query")
            search_id=str(uuid4());query=f"Graph paths: {graph_id} / {entity_id}"
            saved={"id":search_id,"query":query,"search_mode":"graph","graph_query_id":result["id"],"scope":live,"hits":hits,"gaps":[],"created_at":datetime.now(timezone.utc).isoformat(),"elapsed_ms":result["elapsed_ms"]}
            binding=repository.get(key)
            db.add(KnowledgeSearch(id=search_id,query=query,scope={**scope.model_dump(mode="json"),"search_mode":binding["search_mode"]},result=saved))
            for hit in hits:db.add(DocumentReference(id=str(uuid4()),document_id=hit["document_id"],owner_type="knowledge_graph_chat",owner_id=search_id,snapshot=hit))
        repository.link(key,turn,saved)
        output={"graph_query_id":result["id"],"graph_revision":result["graph_revision"],"known_by":str(day),"valid_on":valid_on or str(day),"nodes":node_output,"edges":edge_output,"paths":paths,"citations":references(saved),"truncated":result["truncated"] or len(result["paths"])>3,"notice":"Read-only accepted paths, fixed original documents; inferred influence is not a quantified effect. At most three paths and one excerpt per identity/relationship are sent; use the saved graph query in GraphRAG to inspect the complete retained evidence."}
    except (MissingRecord,StateConflict,ValueError) as error:output={"status":"graph_scope_unavailable","error":str(error),"paths":[]}
    except GraphUnavailable as error:output={"status":"graph_service_failed","error":str(error),"paths":[]}
    except Exception as error:output={"status":"graph_service_failed","error":f"Graph traversal unavailable ({type(error).__name__})","paths":[]}
    return numeric_reply(output,runtime,"read_research_graph_paths")

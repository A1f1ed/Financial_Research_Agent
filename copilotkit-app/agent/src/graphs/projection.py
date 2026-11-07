"""Versioned Neo4j projection, leased publication and bounded real traversal."""
from datetime import date, datetime, timezone
from time import perf_counter
from uuid import uuid4

from neo4j import GraphDatabase, Query
from sqlalchemy import select
from src.documents.repository import lease
from src.infrastructure.config import Infrastructure
from src.knowledge.indexing import progress
from src.persistence.database import transaction
from src.persistence.jobs import JobRepository, MissingRecord, StateConflict
from src.persistence.models import GraphEntity, GraphProjection, GraphQuery, GraphRelation, Job
from .repository import (current_scope, entity_json, evidence_current, graph_row, owned, relation_json)


class GraphUnavailable(RuntimeError): pass


def driver():
    config=Infrastructure.read()
    return GraphDatabase.driver(config.neo4j_uri,auth=(config.neo4j_user,config.neo4j_password),
        connection_timeout=5,max_connection_pool_size=5,max_transaction_retry_time=5)


def write_projection(snapshot, projection_id):
    # Stable projection keys make a redelivered build idempotent. No user input
    # is used as a Cypher identifier or expression; type is a property.
    with driver() as client, client.session(database="neo4j") as session:
        def write(tx):
            tx.run("MATCH (n:ApertureEntity {projection_id:$projection}) DETACH DELETE n",projection=projection_id).consume()
            tx.run("UNWIND $nodes AS node CREATE (:ApertureEntity {projection_id:$projection, id:node.id, revision:node.revision})",
                projection=projection_id,nodes=snapshot["nodes"]).consume()
            tx.run("""UNWIND $edges AS edge
                MATCH (a:ApertureEntity {projection_id:$projection,id:edge.source_id})
                MATCH (b:ApertureEntity {projection_id:$projection,id:edge.target_id})
                CREATE (a)-[:APERTURE_RELATION {projection_id:$projection,id:edge.id,revision:edge.revision}]->(b)""",
                projection=projection_id,edges=snapshot["edges"]).consume()
        # Transaction timeout covers the whole bounded projection, including commit.
        from neo4j import unit_of_work
        session.execute_write(unit_of_work(timeout=20)(write))


def traverse(projection_id, entity_id, allowed_edges, hops):
    if hops not in (1,2): raise ValueError("Only one or two graph hops are supported")
    with driver() as client:
        records,_,_=client.execute_query(Query("""MATCH p=(a:ApertureEntity {projection_id:$projection,id:$entity})
            -[:APERTURE_RELATION*1..%d]-(b:ApertureEntity)
            WHERE all(r IN relationships(p) WHERE r.projection_id=$projection AND r.id IN $allowed)
            RETURN [n IN nodes(p) | n.id] AS nodes,[r IN relationships(p) | r.id] AS edges
            ORDER BY length(p),nodes,edges LIMIT 1001""" % hops, timeout=8),
            projection=projection_id,entity=entity_id,allowed=allowed_edges,database_="neo4j",routing_="r")
        return [record.data() for record in records]


def queue_projection(key, *, force=False, bind=None):
    with transaction(bind) as db:
        graph=graph_row(db,key,lock=True,active=True)
        current_scope(db,graph)  # An archived parent cannot authorize a rebuild.
        running=db.execute(select(GraphProjection,Job).join(Job,Job.id==GraphProjection.job_id).where(
            GraphProjection.graph_id==key,Job.status.in_(["queued","running"])).order_by(GraphProjection.record_order.desc()).limit(1)).first()
        if running: return {"id":running[0].id,"job_id":running[1].id,"existing":True,"graph_revision":running[0].graph_revision}
        if graph.projected_revision==graph.revision and not force:
            row=db.get(GraphProjection,graph.projection_id)
            return {"id":row.id,"job_id":row.job_id,"existing":True,"graph_revision":row.graph_revision}
        nodes=db.scalars(select(GraphEntity).where(GraphEntity.graph_id==key,GraphEntity.archived.is_(False)).order_by(GraphEntity.id)).all()
        node_ids={row.id for row in nodes}
        edges=db.scalars(select(GraphRelation).where(GraphRelation.graph_id==key,GraphRelation.status=="accepted",
            GraphRelation.source_id.in_(node_ids),GraphRelation.target_id.in_(node_ids)).order_by(GraphRelation.id)).all()
        projection_id=str(uuid4())
        job_id=JobRepository.enqueue(db,f"Graph sync · {graph.name}",{"_operation":"knowledge.graph.sync","projection_id":projection_id,"graph_id":key},kind="knowledge")
        row=GraphProjection(id=projection_id,graph_id=key,graph_revision=graph.revision,job_id=job_id,
            snapshot={"nodes":[entity_json(node) for node in nodes],"edges":[relation_json(edge) for edge in edges]},published=False)
        db.add(row)
        return {"id":row.id,"job_id":job_id,"existing":False,"graph_revision":row.graph_revision}


async def execute_projection(payload,job_id,token):
    with transaction() as db:
        lease(db,job_id,token); row=db.get(GraphProjection,payload["projection_id"])
        if row is None or row.job_id!=job_id: raise MissingRecord("Graph projection does not exist")
        graph=graph_row(db,row.graph_id)
        if row.published or graph.archived or graph.revision!=row.graph_revision: raise ValueError("Graph changed; sync its current revision")
        try: current_scope(db,graph)
        except StateConflict: raise ValueError("Graph source scope is no longer available") from None
        snapshot,projection_id,graph_id,revision=row.snapshot,row.id,graph.id,row.graph_revision
    progress(job_id,token,"projection","running",f"Projecting {len(snapshot['nodes'])} identities and {len(snapshot['edges'])} reviewed relationships")
    # Celery isolates this synchronous driver work; API never executes it inline.
    write_projection(snapshot,projection_id)
    with transaction() as db:
        job=lease(db,job_id,token); graph=graph_row(db,graph_id,lock=True)
        try: current_scope(db,graph)
        except StateConflict: raise ValueError("Graph source scope is no longer available") from None
        if graph.archived or graph.revision!=revision: raise ValueError("Graph changed during projection; current facts were not replaced")
        row=db.get(GraphProjection,projection_id); row.published=True
        graph.projection_id,graph.projected_revision=projection_id,revision
        job.status="complete"; job.finished_at=datetime.now(timezone.utc); job.lease_token=None; job.lease_until=None
        job.result={"graph_id":graph_id,"projection_id":projection_id,"graph_revision":revision,
            "nodes":len(snapshot["nodes"]),"edges":len(snapshot["edges"])}
        job.progress=[{"id":"projection","status":"complete","detail":"Complete graph version published"}]
        job.elapsed_seconds=(job.finished_at-job.started_at).total_seconds()
    return {"status":"complete","_finished":True}


def query_graph(key,inputs,*,bind=None):
    began=perf_counter()
    with transaction(bind) as db:
        graph=graph_row(db,key,active=True)
        if graph.projected_revision!=graph.revision or not graph.projection_id:
            raise StateConflict("Graph changes are not yet projected; synchronize before querying")
        projection=db.get(GraphProjection,graph.projection_id)
        if projection is None or not projection.published: raise StateConflict("No published graph projection is available")
        scope=current_scope(db,graph,as_of=inputs.as_of)
        eligible={item["id"] for item in scope["documents"] if item["eligible"]}
        current_nodes={row.id:row for row in db.scalars(select(GraphEntity).where(GraphEntity.graph_id==key,GraphEntity.archived.is_(False)))}
        origin=owned(db,GraphEntity,str(inputs.entity_id),key)
        nodes={item["id"]:item for item in projection.snapshot["nodes"] if item["id"] in current_nodes
            and current_nodes[item["id"]].revision==item["revision"] and evidence_current(db,item["evidence"],eligible)}
        if origin.id not in nodes: raise StateConflict("The selected identity has no currently eligible source evidence")
        current_edges={row.id:row for row in db.scalars(select(GraphRelation).where(GraphRelation.graph_id==key,GraphRelation.status=="accepted"))}
        valid_day=inputs.valid_on or inputs.as_of
        types=set(inputs.relation_types or graph.relation_types)
        if not types.issubset(set(graph.relation_types)): raise StateConflict("A requested relationship type is outside this graph")
        edges={}
        for item in projection.snapshot["edges"]:
            row=current_edges.get(item["id"])
            if (row is None or row.revision!=item["revision"] or item["source_id"] not in nodes or item["target_id"] not in nodes
                    or item["relation_type"] not in types or not item["valid_from"]
                    or date.fromisoformat(item["valid_from"])>valid_day
                    or item["valid_until"] and date.fromisoformat(item["valid_until"])<valid_day
                    or item["assertion"]=="inferred" and not inputs.include_inferred
                    or not evidence_current(db,item["evidence"],eligible)): continue
            edges[item["id"]]=item
        revision,projection_id=graph.revision,graph.projection_id
    try: paths=traverse(projection_id,str(inputs.entity_id),list(edges),inputs.max_hops)
    except Exception: raise GraphUnavailable("Graph query service is temporarily unavailable; retry after checking projection health") from None
    selected_nodes={str(inputs.entity_id)}; selected_edges=set(); bounded=[]; truncated=len(paths)>=1001
    for path in paths[:1000]:
        # Treat the projection as untrusted: an out-of-scope edge/path never
        # becomes a source merely because Neo4j returned it.
        if any(n not in nodes for n in path["nodes"]) or any(e not in edges for e in path["edges"]):
            raise GraphUnavailable("Projection consistency check failed; rebuild the graph")
        if len(selected_nodes|set(path["nodes"]))>100 or len(selected_edges|set(path["edges"]))>200:
            truncated=True; continue
        selected_nodes.update(path["nodes"]); selected_edges.update(path["edges"]); bounded.append(path)
    with transaction(bind) as db:
        graph=graph_row(db,key,lock=True,active=True)
        if graph.revision!=revision or graph.projection_id!=projection_id or current_scope(db,graph,as_of=inputs.as_of)["scope_fingerprint"]!=scope["scope_fingerprint"]:
            raise StateConflict("Graph or source scope changed while querying; retry with the current version")
        if any(not evidence_current(db,nodes[n]["evidence"],eligible) for n in selected_nodes) or any(not evidence_current(db,edges[e]["evidence"],eligible) for e in selected_edges):
            raise StateConflict("Source page extraction changed while querying; review the evidence again")
        result={"id":str(uuid4()),"graph_id":key,"graph_revision":revision,"projection_id":projection_id,
            "scope":scope,"nodes":[nodes[n] for n in sorted(selected_nodes)],"edges":[edges[e] for e in sorted(selected_edges)],"paths":bounded,
            "truncated":truncated,"limits":{"nodes":100,"edges":200,"hops":2,"paths":1000},
            "elapsed_ms":round((perf_counter()-began)*1000,3),"notice":"Disclosed relationships and inferred influence paths remain distinct; inclusion is not numerical impact verification."}
        db.add(GraphQuery(id=result["id"],graph_id=key,inputs=inputs.model_dump(mode="json"),snapshot=result,name=inputs.name))
        return result


def saved_queries(key,*,query_id=None,page=1,page_size=20,bind=None):
    with transaction(bind) as db:
        graph_row(db,key)
        if query_id:
            row=owned(db,GraphQuery,query_id,key)
            return {"id":row.id,"name":row.name,"inputs":row.inputs,"snapshot":row.snapshot,"created_at":row.created_at,
                "historical":True,"notice":"Stored path snapshot; current publication and review state may differ."}
        from sqlalchemy import func
        rows=db.scalars(select(GraphQuery).where(GraphQuery.graph_id==key).order_by(GraphQuery.record_order.desc()).offset((page-1)*page_size).limit(page_size)).all()
        return {"queries":[{"id":row.id,"name":row.name,"inputs":row.inputs,"created_at":row.created_at} for row in rows],
            "total":db.scalar(select(func.count()).select_from(GraphQuery).where(GraphQuery.graph_id==key))}

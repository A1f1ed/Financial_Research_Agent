"""Fenced execution with pre-call reservation and no replay of unknown outcomes."""
import asyncio
from datetime import datetime, timezone
import json
import os
from time import perf_counter
from uuid import uuid4

from langchain.agents.middleware import wrap_model_call
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from sqlalchemy import select
from src.documents.repository import lease
from src.persistence.database import transaction
from src.persistence.models import EvaluationRun, EvaluationAttempt, KnowledgeIndex, KnowledgeFigure, ResearchGraph, RunEvent
from src.persistence.jobs import StateConflict, JobRepository
from src.infrastructure.telemetry import operation, trace_details
from src.knowledge.contracts import ScopeRequest, SearchRequest, ConversationRequest
from src.knowledge.repository import CollectionRepository
from src.knowledge.retrieval import search
from .contracts import RunOptions
from .repository import required, digest
from .scoring import assess, aggregate


class BudgetExceeded(ValueError): pass


async def task_list():
    import httpx
    # Deployment-owned internal API address; never accept a destination from a case or tool.
    base = os.getenv("APERTURE_EVALUATION_API_URL", "http://127.0.0.1:8123").rstrip("/")
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
        response = await client.get(base+"/research/tasks", params={"limit":20})
        response.raise_for_status()
        if len(response.content)>512000: raise ValueError("task_list_response_too_large")
        return response.json()["tasks"]


def reserve(run_id, attempt_id, token, tokens):
    with transaction() as db:
        lease(db, run_id, token); run = required(db, EvaluationRun, run_id, True)
        attempt = required(db, EvaluationAttempt, attempt_id, True)
        limits = run.config; counters = dict(run.counters)
        if not limits["allow_model"]: raise BudgetExceeded("Model calls were not enabled")
        if counters["reserved_calls"] >= limits["max_calls"] or counters["reserved_tokens"]+tokens > limits["max_tokens"]:
            raise BudgetExceeded("Reserved provider call/token ceiling reached")
        counters["reserved_calls"] += 1; counters["reserved_tokens"] += tokens; run.counters = counters
        attempt.result = {**attempt.result, "model_calls": attempt.result.get("model_calls", 0)+1,
            "reserved_tokens": attempt.result.get("reserved_tokens", 0)+tokens}


def validate_sources(case):
    if not case.get("scope"): return
    live = CollectionRepository().scope(ScopeRequest.model_validate(case["scope"]))
    before = {d["id"]: d for d in case["snapshot"]["documents"]}
    for item in live["documents"]:
        old = before[item["id"]]
        if any(item[k] != old[k] for k in ("version", "metadata_revision", "sha256", "eligible", "exclusion")):
            raise StateConflict("Published source state changed; publish a new dataset version")
    with transaction() as db:
        current = [{"id": r.id, "document_id": r.document_id, "profile_key": r.profile_key,
            "profile": {k: v for k, v in r.profile.items() if k != "embedding"}, "published": r.published}
            for r in db.scalars(select(KnowledgeIndex).where(KnowledgeIndex.document_id.in_(before), KnowledgeIndex.published.is_(True)))]
        if digest(sorted(current, key=lambda x:x["id"])) != digest(sorted(case.get("indices", []), key=lambda x:x["id"])):
            raise StateConflict("Published index state changed; publish a new dataset version")
        for figure in case.get("figures", []):
            row = required(db, KnowledgeFigure, figure["id"])
            if row.archived or row.revision != figure["revision"]: raise StateConflict("Reviewed figure revision changed")
        if case.get("graph_id"):
            graph = required(db, ResearchGraph, case["graph_id"])
            if graph.archived or graph.revision != case["graph_revision"] or graph.projection_id != case["projection_id"]:
                raise StateConflict("Published graph/projection changed; publish a new dataset version")


def citation_checks(case, hits):
    from src.graphs.repository import evidence_current
    allowed = {d["id"] for d in case["snapshot"]["documents"] if d["eligible"]}
    with transaction() as db:
        invalid = sum(not evidence_current(db, [hit], allowed) for hit in hits)
    return {"citations": [{k: h[k] for k in ("document_id", "page_number", "document_version", "metadata_revision", "document_sha256", "citation_id") if k in h} for h in hits],
        "invalid_citations": invalid, "date_leaks": sum(h["document_id"] not in allowed for h in hits)}


async def execute_case(case, run, attempt_id, token):
    options = RunOptions.model_validate(run.config)
    if case["target"] in {"vision", "wiki", "manual_review"}: return {"status": "unsupported", "reason": "Capability/rule adapter not implemented; explicit manual configuration required; no model call"}
    validate_sources(case)
    if case["target"] == "task_list":
        rows = await task_list()
        return {"list_count": len(rows), "list_valid": len(rows) <= 20 and all(x.get("id") and x.get("status") for x in rows),
            "cache": "HTTP client has no response cache; server/database caches not controlled", "measurement": "fixed internal task-list HTTP endpoint including API/database/network/JSON parsing; excludes browser"}
    if case["target"] == "retrieval":
        if options.search_mode == "hybrid":
            from src.knowledge.indexing import index_profile
            if index_profile("hybrid")[1] != run.manifest.get("embedding_profile_key"):
                raise StateConflict("Embedding configuration changed after run submission")
        if options.search_mode == "hybrid" and case["snapshot"]["eligible_count"]:
            reserve(run.id, attempt_id, token, len(case["question"].encode())+512)
        began = perf_counter()
        result = await search(SearchRequest(**case["scope"], query=case["question"], search_mode=options.search_mode, limit=5))
        return {**citation_checks(case, result["hits"]), "search_id": result["id"], "retrieval_ms": round((perf_counter()-began)*1000, 3),
            "gaps": result["gaps"], "usage": {"total_tokens": result["embedding_tokens"]} if options.search_mode == "hybrid" else {},
            "reported_calls": 1 if options.search_mode == "hybrid" and case["snapshot"]["eligible_count"] else 0,
            "cache": "warm/cold not controlled; retained indices, no search-result cache", "measurement": "retrieval including database and embedding network when enabled; excludes browser/HTTP"}
    if case["target"] == "graph":
        from src.graphs.contracts import GraphQueryInput
        from src.graphs.projection import query_graph
        query = GraphQueryInput.model_validate(case["graph_query"])
        cutoff = case["snapshot"]["cutoff"]
        from zoneinfo import ZoneInfo
        known_day = cutoff.get("as_of") or datetime.fromisoformat(cutoff["as_of_at"]).astimezone(ZoneInfo(case["snapshot"]["timezone"])).date().isoformat()
        if str(query.as_of) != known_day: raise StateConflict("Graph cutoff must match the case's knowledge cutoff")
        result = await asyncio.to_thread(query_graph, case["graph_id"], query, allowed_document_ids={d["id"] for d in case["snapshot"]["documents"] if d["eligible"]})
        hits = [e for item in [*result["nodes"], *result["edges"]] for e in item["evidence"]]
        return {**citation_checks(case, hits), "graph_query_id": result["id"], "edge_count": len(result["edges"]), "path_count": len(result["paths"])}
    if case["target"] == "calculation":
        from src.knowledge.figures import FigureRepository
        from src.knowledge.calculations import CalculationInput
        result = FigureRepository().calculate(case["collection_id"], CalculationInput.model_validate(case["calculation"]),
            eligible={d["id"] for d in case["snapshot"]["documents"] if d["eligible"]})
        period = {k: result["inputs"][0][k] for k in ("period_start", "period_end")}
        return {"calculation_id": result["id"], "calculation": {**{k: v for k, v in result.items() if k not in {"inputs", "references", "request"}}, **period}}
    return await execute_agent(case, run, attempt_id, token, options)


async def execute_agent(case, run, attempt_id, token, options):
    from src.agent import build_graph
    from src.model import compatible_model
    from src.preferences import provider_key
    from src.knowledge.conversations import ConversationRepository, turn_id
    from src.knowledge.embeddings import fingerprint, settings
    if not options.allow_model: raise BudgetExceeded("Full Agent evaluation requires explicit model permission")
    profile = {**run.manifest["model"], "timeout": min(options.timeout_seconds, run.manifest["model"]["timeout"])}
    if not provider_key(profile["provider"]): raise ValueError("model_not_configured")
    if options.search_mode == "hybrid":
        # Tool-driven repeated embeddings cannot be reserved per call by the current adapter.
        raise ValueError("Agent evaluation currently requires keyword retrieval; hybrid is supported in retrieval evaluations")
    totals = {}; calls = 0; model_ms = 0; reported_calls = 0
    @wrap_model_call
    async def guard(request, handler):
        nonlocal calls, model_ms, reported_calls
        if calls >= 4: raise BudgetExceeded("Agent reached four model calls per attempt")
        # UTF-8 bytes plus schema allowance is a conservative pre-call upper bound,
        # not an observed tokenizer/cost measurement. Reservation is never refunded.
        payload = json.dumps([m.model_dump(mode="json") for m in request.messages], ensure_ascii=False)
        if request.system_message: payload += str(request.system_message.content)
        schema = json.dumps([convert_to_openai_tool(t) for t in request.tools], ensure_ascii=False)
        reserve(run.id, attempt_id, token, len(payload.encode())+len(schema.encode())+options.max_output_tokens+2048)
        calls += 1; began = perf_counter(); response = await handler(request); model_ms += (perf_counter()-began)*1000
        for message in response.result:
            usage = getattr(message, "usage_metadata", None)
            if usage:
                reported_calls += 1
                for key in ("input_tokens", "output_tokens", "total_tokens"): totals[key] = totals.get(key, 0)+usage.get(key, 0)
        with transaction() as db:
            lease(db, run.id, token); attempt = required(db, EvaluationAttempt, attempt_id, True)
            attempt.result = {**attempt.result, "usage": totals, "reported_calls": reported_calls, "model_ms": round(model_ms,3)}
        return response
    thread_id = str(uuid4())
    ConversationRepository().create(ConversationRequest(**case["scope"], thread_id=thread_id, search_mode="keyword"))
    model = compatible_model(profile, enable_thinking=False, max_tokens=options.max_output_tokens, max_retries=0)
    graph = build_graph(None, evaluation_model=model, evaluation_middleware=guard)
    question = HumanMessage(content=case["question"], id=str(uuid4()))
    state = await graph.ainvoke({"messages": [question]}, {"configurable": {"thread_id": thread_id}, "recursion_limit": 16})
    searches = ConversationRepository().searches(thread_id, turn_id=turn_id([question]), limit=8)
    answer = next((m.text for m in reversed(state["messages"]) if isinstance(m, AIMessage) and not m.tool_calls), "")
    if any(r.get("status") in {"retrieval_failed", "evidence_unavailable"} for r in searches): raise ValueError("agent_retrieval_failed")
    from src.knowledge.agent_scope import LINK
    returned = {(result["id"], hit["citation_id"]): hit for result in searches for hit in result.get("hits", [])}
    emitted = list(LINK.finditer(answer)); keys = {(m.group(3), m.group(4)) for m in emitted}
    hits = [returned[key] for key in keys if key in returned]
    checked = citation_checks(case, hits)
    checked["invalid_citations"] += sum(key not in returned for key in keys)
    if not answer.strip(): raise ValueError("agent_final_answer_missing")
    return {**checked, "answer": answer[:12000], "model_ms": round(model_ms, 3), "usage": totals, "reported_calls": reported_calls,
        "source_links": [{"search_id": key[0], "citation_id": key[1], "document_id": returned[key]["document_id"], "page_number": returned[key]["page_number"]} for key in keys if key in returned],
        "conversation_id": thread_id, "search_ids": [x["id"] for x in searches], "cache": "new conversation; model/network included",
        "measurement": "actual existing LangGraph document agent, bounded four model calls; no CopilotKit network/UI delivery time"}


def save_result(run_id, attempt_id, token, status, output, elapsed):
    with transaction() as db:
        job = lease(db, run_id, token); attempt = required(db, EvaluationAttempt, attempt_id, True)
        if attempt.status != "in_flight": raise StateConflict("Attempt has already finished")
        attempt.status = status; attempt.completed_at = datetime.now(timezone.utc)
        attempt.result = {**attempt.result, **output, "elapsed_ms": round(elapsed*1000, 3)}
        statuses = db.scalars(select(EvaluationAttempt).where(EvaluationAttempt.run_id == run_id)).all()
        completed = sum(x.status not in {"pending", "in_flight"} for x in statuses)
        job.result = {"evaluation_run_id": run_id, "completed": completed, "total": len(statuses)}
        job.progress = [{"id": "evaluation", "label": "Evaluation cases", "status": "running", "detail": f"{completed}/{len(statuses)}", "case_id": attempt.case_id}]
        db.add(RunEvent(run_id=run_id, event_id=str(uuid4()), kind="evaluation.attempt.finished", payload={"case_id": attempt.case_id, "attempt_id": attempt.id, "status": status}))


async def execute_evaluation(job_id, token):
    with transaction() as db:
        lease(db, job_id, token); run = required(db, EvaluationRun, job_id)
        # Persisted in-flight attempts have unknown outcomes after worker loss.
        attempts = db.scalars(select(EvaluationAttempt).where(EvaluationAttempt.run_id == job_id).order_by(EvaluationAttempt.record_order).with_for_update()).all()
        for attempt in attempts:
            if attempt.status == "in_flight":
                attempt.status = "interrupted"; attempt.completed_at = datetime.now(timezone.utc)
                attempt.result = {**attempt.result, "error_type": "unknown_outcome_after_worker_loss", "notice": "Not automatically replayed; retry creates a new run"}
        ids = [a.id for a in attempts if a.status == "pending"]
        cases = {c["id"]: c for c in run.manifest["cases"]}
        # Detached immutable runtime data; credentials are resolved only in the adapter.
        class Snapshot: pass
        snapshot = Snapshot(); snapshot.id = run.id; snapshot.config = run.config; snapshot.manifest = run.manifest
    for attempt_id in ids:
        with transaction() as db:
            lease(db, job_id, token); attempt = required(db, EvaluationAttempt, attempt_id, True)
            if attempt.status != "pending": continue
            attempt.status = "in_flight"; attempt.requested_at = datetime.now(timezone.utc); case = cases[attempt.case_id]
        began = perf_counter(); status = "error"; output = {}
        with operation("evaluation.attempt", kind="chain", run_id=job_id, case_id=case["id"], attempt_id=attempt_id):
            try:
                async with asyncio.timeout(snapshot.config["timeout_seconds"]):
                    output = await execute_case(case, snapshot, attempt_id, token)
                # Existing services return dates/UUIDs/Decimals as Python values.
                # Preserve exact decimal text and normalize before scoring and JSONB persistence.
                output = json.loads(json.dumps(output, ensure_ascii=False, default=str))
                validate_sources(case)
                if output.get("status") == "unsupported": status = "unsupported"
                else:
                    score = assess(case, output); output.update(score)
                    status = "passed" if score["passed"] else "failed" if score["scored"] else "unscored"
                output["trace_id"] = (trace_details() or {}).get("trace_id")
                # Store only bounded result metadata/generated answer, not source pages or reasoning.
                encoded = json.dumps(output, ensure_ascii=False, default=str).encode()
                if len(encoded) > 4096:
                    from src.infrastructure.objects import ObjectStore
                    key = f"evaluations/{job_id}/{attempt_id}.json"
                    with ObjectStore() as store: sha = store.put_verified(key, encoded, "application/json")
                    output["artifact"] = {"key": key, "sha256": sha, "bytes": len(encoded)}
            except BudgetExceeded: status = "budget_exceeded"; output = {"error_type": "budget_exceeded", "notice": "No further provider request was sent after the reservation ceiling"}
            except TimeoutError: status = "timeout"; output = {"error_type": "timeout", "notice": "Provider outcome/usage may be unknown; reserved budget retained"}
            except StateConflict as error: status = "error"; output = {"error_type": "source_or_configuration_changed", "notice": str(error)}
            except asyncio.CancelledError: raise
            except Exception as error: status = "error"; output = {"error_type": type(error).__name__, "notice": "Execution failed; inspect source/configuration and explicitly retry. This is not evidence of a missing answer."}
        save_result(job_id, attempt_id, token, status, output, perf_counter()-began)
    with transaction() as db:
        job = lease(db, job_id, token)
        rows = db.scalars(select(EvaluationAttempt).where(EvaluationAttempt.run_id == job_id)).all()
        summary = aggregate([{"status": a.status, **a.result} for a in rows])
        job.result = {"evaluation_run_id": job_id, **summary}
        job.progress = [{"id": "evaluation", "label": "Evaluation cases", "status": "complete", "detail": f"{summary['finished']}/{summary['total']}"}]
        job.elapsed_seconds = (datetime.now(timezone.utc)-job.started_at).total_seconds()
    # Execution completeness is distinct from whether quality assertions passed.
    operational = sum(summary["counts"][s] for s in ("error", "timeout", "budget_exceeded", "interrupted"))
    return {"status": "partial" if operational else "complete"}

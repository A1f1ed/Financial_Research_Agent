"""Immutable releases, server-owned manifests and atomic evaluation dispatch."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from src.persistence.database import transaction
from src.persistence.jobs import JobRepository, MissingRecord, StateConflict
from src.persistence.models import (EvaluationDataset, EvaluationVersion, EvaluationRun,
    EvaluationAttempt, Job, KnowledgeIndex, KnowledgeFigure, ResearchGraph, Document, RunEvent, DocumentReference)
from src.knowledge.repository import CollectionRepository
from src.preferences import profile_settings
from .contracts import DatasetInput, RunOptions, SCORER_VERSION


def digest(value):
    return hashlib.sha256(json.dumps(jsonable_encoder(value), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def required(db, model, key, lock=False):
    row = db.scalar(select(model).where(model.id == str(key)).with_for_update()) if lock else db.get(model, str(key))
    if row is None: raise MissingRecord("Evaluation record not found")
    return row


def dataset_json(row, include_cases=True):
    body = deepcopy(row.body)
    if not include_cases: body.pop("cases", None)
    return {"id": row.id, "revision": row.revision, "archived": row.archived,
        "created_at": row.created_at, "case_count": len(row.body["cases"]), **body}


def pin_case(db, case):
    body = case.model_dump(mode="json")
    if case.scope:
        scope = CollectionRepository().scope(case.scope, session=db)
        if len(scope["documents"]) > 50: raise StateConflict("At most 50 exact documents per case")
        body["snapshot"] = scope
        body["source_pages"] = sum(db.get(Document, d["id"]).page_count or 0 for d in scope["documents"])
        body["scope"] = {**body["scope"], "collection_ids": [], "document_ids": [d["id"] for d in scope["documents"]]}
        if not body["scope"]["document_ids"]: raise StateConflict("Choose a nonempty document scope")
        body["indices"] = [{"id": r.id, "document_id": r.document_id, "profile_key": r.profile_key,
            "profile": {k: v for k, v in r.profile.items() if k != "embedding"}, "published": r.published}
            for r in db.scalars(select(KnowledgeIndex).where(KnowledgeIndex.document_id.in_(body["scope"]["document_ids"]), KnowledgeIndex.published.is_(True)))]
        allowed = set(body["scope"]["document_ids"])
        if any(str(page.document_id) not in allowed for page in case.expected.pages):
            raise StateConflict("Expected pages must belong to the exact case scope")
        if any(page.page_number > (db.get(Document,str(page.document_id)).page_count or 0) for page in case.expected.pages):
            raise StateConflict("An expected page does not exist in the selected original")
    if case.calculation:
        body["figures"] = [{"id": row.id, "revision": row.revision, "fingerprint": row.fingerprint}
            for row in db.scalars(select(KnowledgeFigure).where(KnowledgeFigure.id.in_([str(x) for x in case.calculation.figure_ids])))]
        if len(body["figures"]) != len(case.calculation.figure_ids): raise StateConflict("A calculation input is missing")
    if case.graph_id:
        graph = required(db, ResearchGraph, case.graph_id)
        if graph.archived: raise StateConflict("Choose an active graph")
        body["graph_revision"] = graph.revision
        body["projection_id"] = graph.projection_id
    return body


class EvaluationRepository:
    def __init__(self, bind=None): self.bind = bind

    def datasets(self, archived=False, page=1, page_size=20):
        with transaction(self.bind) as db:
            query = select(EvaluationDataset).where(EvaluationDataset.archived == archived)
            rows = db.scalars(query.order_by(EvaluationDataset.record_order.desc()).offset((page-1)*page_size).limit(page_size))
            return {"items": [dataset_json(row, False) for row in rows],
                "total": db.scalar(select(func.count()).select_from(EvaluationDataset).where(EvaluationDataset.archived == archived))}

    def dataset(self, key):
        with transaction(self.bind) as db:
            row = required(db, EvaluationDataset, key)
            versions = db.scalars(select(EvaluationVersion).where(EvaluationVersion.dataset_id == row.id).order_by(EvaluationVersion.number.desc()))
            return {**dataset_json(row), "versions": [{"id": v.id, "number": v.number, "fingerprint": v.fingerprint,
                "created_at": v.created_at, "counts": {p: sum(c["partition"] == p for c in v.body["cases"]) for p in ("development", "acceptance")}} for v in versions]}

    def save(self, inputs, key=None):
        body = DatasetInput.model_validate(inputs.model_dump(exclude={"expected_revision"})).model_dump(mode="json")
        with transaction(self.bind) as db:
            if key:
                row = required(db, EvaluationDataset, key, True)
                if row.archived or row.revision != inputs.expected_revision: raise StateConflict("Dataset changed or is archived; refresh before editing")
                row.body = body; row.revision += 1
            else:
                row = EvaluationDataset(id=str(uuid4()), body=body); db.add(row); db.flush()
            return dataset_json(row)

    def archive(self, key, revision, archived):
        with transaction(self.bind) as db:
            row = required(db, EvaluationDataset, key, True)
            if row.revision != revision: raise StateConflict("Dataset changed; refresh before archiving")
            row.archived = archived; row.revision += 1
            return dataset_json(row, False)

    def publish(self, key, revision):
        with transaction(self.bind) as db:
            row = required(db, EvaluationDataset, key, True)
            if row.archived or row.revision != revision: raise StateConflict("Dataset changed or is archived")
            inputs = DatasetInput.model_validate(row.body)
            if not inputs.cases: raise StateConflict("Add at least one case before publishing")
            body = {**row.body, "cases": [pin_case(db, case) for case in inputs.cases], "scorer_version": SCORER_VERSION}
            number = (db.scalar(select(func.max(EvaluationVersion.number)).where(EvaluationVersion.dataset_id == row.id)) or 0) + 1
            version = EvaluationVersion(id=str(uuid4()), dataset_id=row.id, number=number, body=body, fingerprint=digest(body))
            db.add(version); row.revision += 1; db.flush()
            for case in body["cases"]:
                for source in case.get("snapshot", {}).get("documents", []):
                    db.add(DocumentReference(id=str(uuid4()),document_id=source["id"],owner_type="evaluation_version",owner_id=version.id,snapshot=source))
            return {"id": version.id, "number": number, "fingerprint": version.fingerprint}

    def start(self, options: RunOptions):
        with transaction(self.bind) as db:
            version = required(db, EvaluationVersion, options.version_id)
            dataset = required(db, EvaluationDataset, version.dataset_id, True)
            if dataset.archived: raise StateConflict("Restore this dataset before starting another run")
            if options.parent_run_id:
                parent = required(db, EvaluationRun, options.parent_run_id)
                parent_job = required(db, Job, parent.id)
                if parent.dataset_id != dataset.id or parent_job.status in {"queued", "running"}:
                    raise StateConflict("Retry a terminal run from the same dataset")
            cases = [c for c in version.body["cases"] if c["partition"] == options.partition]
            if not cases: raise StateConflict("This published version has no cases in the chosen partition")
            targets = {"retrieval_benchmark": {"retrieval"}, "list_benchmark": {"task_list"}, "agent_performance": {"agent"}}
            if options.mode in targets and any(c["target"] not in targets[options.mode] for c in cases):
                raise StateConflict("Benchmark mode must contain only the matching target type; use a separate dataset/partition")
            if len(cases)*options.repetitions > 500: raise StateConflict("A run supports at most 500 attempts")
            pages = sum(c.get("source_pages", 0) for c in cases)
            if pages > options.max_pages: raise StateConflict("The published source scope exceeds the page budget")
            settings = profile_settings()
            profile = {k: settings[k] for k in ("provider", "model", "base_url", "temperature", "timeout")}
            manifest = {"version_fingerprint": version.fingerprint, "scorer_version": SCORER_VERSION,
                "cases": cases, "model": profile, "pages": pages, "environment": {"execution": "Celery/PostgreSQL", "concurrency": 1}}
            if options.search_mode == "hybrid":
                from src.knowledge.indexing import index_profile
                manifest["embedding_profile_key"] = index_profile("hybrid")[1]
            key = JobRepository.enqueue(db, f"Evaluation · {dataset.body['name']}", {"_operation": "evaluation.run"}, kind="evaluation")
            config = options.model_dump(mode="json")
            run = EvaluationRun(id=key, dataset_id=dataset.id, version_id=version.id, parent_run_id=config["parent_run_id"],
                config=config, manifest=manifest, counters={"reserved_calls": 0, "reserved_tokens": 0})
            db.add(run); db.flush()
            for case in cases:
                for repetition in range(options.repetitions):
                    db.add(EvaluationAttempt(id=str(uuid4()), run_id=key, case_id=case["id"], repetition=repetition, status="pending", result={}))
            return {"id": key, "url": f"/?evaluationRun={key}", "attempts": len(cases)*options.repetitions}

    def runs(self, dataset_id=None, page=1, page_size=20):
        with transaction(self.bind) as db:
            query = select(EvaluationRun, Job, EvaluationVersion).join(Job, Job.id == EvaluationRun.id).join(EvaluationVersion, EvaluationVersion.id == EvaluationRun.version_id)
            if dataset_id: query = query.where(EvaluationRun.dataset_id == str(dataset_id))
            rows = db.execute(query.order_by(EvaluationRun.record_order.desc()).offset((page-1)*page_size).limit(page_size)).all()
            return {"items": [{"id": r.id, "dataset_id": r.dataset_id, "version_id": r.version_id, "partition": r.config["partition"],
                "dataset_name": v.body["name"], "version_number": v.number,
                "mode": r.config["mode"], "status": j.status, "summary": j.result, "created_at": r.created_at} for r, j, v in rows]}

    def detail(self, key, page=1, page_size=50, status=""):
        from .scoring import aggregate
        with transaction(self.bind) as db:
            run = required(db, EvaluationRun, key); job = required(db, Job, key)
            case_names = {c["id"]:c["name"] for c in run.manifest["cases"]}
            attempts = db.scalars(select(EvaluationAttempt).where(EvaluationAttempt.run_id == run.id).order_by(EvaluationAttempt.record_order)).all()
            items = [{"id": a.id, "case_id": a.case_id, "case_name":case_names[a.case_id], "repetition": a.repetition, "status": "cancelled" if job.status == "cancelled" and a.status in {"pending", "in_flight"} else "interrupted" if job.status=="failed" and a.status=="in_flight" else "error" if job.status=="failed" and a.status=="pending" else a.status,
                "requested_at": a.requested_at, "completed_at": a.completed_at, **a.result} for a in attempts]
            filtered = [item for item in items if not status or item["status"] == status]
            events = db.scalars(select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.created_at.desc()).limit(100)).all()
            return {"id": run.id, "dataset_id": run.dataset_id, "version_id": run.version_id, "parent_run_id": run.parent_run_id,
                "status": job.status, "created_at": run.created_at, "started_at": job.started_at, "config": run.config,
                "manifest": {k: v for k, v in run.manifest.items() if k != "cases"}, "counters": run.counters,
                "summary": aggregate(items), "attempts": filtered[(page-1)*page_size:page*page_size], "total": len(filtered),
                "queue_wait_ms": round((job.started_at-job.created_at).total_seconds()*1000,3) if job.started_at else None,
                "events": [{"kind": e.kind, "at": e.created_at, "metadata": e.payload} for e in reversed(events)],
                "progress": job.progress, "error": job.error}

    def attempt(self, key, attempt_id, *, agent=False):
        with transaction(self.bind) as db:
            run = required(db, EvaluationRun, key); attempt = required(db, EvaluationAttempt, attempt_id)
            if attempt.run_id != run.id: raise MissingRecord("Attempt is not part of this run")
            case = next(c for c in run.manifest["cases"] if c["id"] == attempt.case_id)
            if agent and case["partition"] == "acceptance":
                return {"id": attempt.id, "case_id": attempt.case_id, "status": attempt.status,
                    "error_type": attempt.result.get("error_type"), "notice": "Frozen acceptance answers, outputs and scoring details are not exposed to Agent tools. Inspect them explicitly in Evaluation center."}
            return {"id": attempt.id, "case": case, "status": attempt.status, "result": attempt.result}

    def compare(self, left, right, *, agent=False):
        a, b = self.detail(left, page_size=500), self.detail(right, page_size=500)
        equal = {k: a["manifest"].get(k) == b["manifest"].get(k) for k in ("version_fingerprint", "scorer_version", "model", "embedding_profile_key")}
        equal["partition"] = a["config"]["partition"] == b["config"]["partition"]
        equal["search_mode"] = a["config"]["search_mode"] == b["config"]["search_mode"]
        equal["mode"] = a["config"]["mode"] == b["config"]["mode"]
        equal["limits_and_samples"] = all(a["config"][k] == b["config"][k] for k in ("allow_model","repetitions","max_calls","max_tokens","max_output_tokens","timeout_seconds","max_pages"))
        left_cases = {(x["case_id"], x["repetition"]): x for x in a["attempts"]}
        right_cases = {(x["case_id"], x["repetition"]): x for x in b["attempts"]}
        differences = []
        for case_id, repetition in sorted(left_cases.keys() | right_cases.keys()):
            x, y = left_cases.get((case_id, repetition), {}), right_cases.get((case_id, repetition), {})
            differences.append({"case_id": case_id, "case_name": x.get("case_name") or y.get("case_name"),
                "repetition": repetition, "left_status": x.get("status", "missing"), "right_status": y.get("status", "missing"),
                "left_ms": x.get("elapsed_ms"), "right_ms": y.get("elapsed_ms")})
        return {"left": {"id": left, "summary": a["summary"]}, "right": {"id": right, "summary": b["summary"]},
            "comparable": all(equal.values()), "same_configuration": equal, "differences": differences,
            "notice": "Differences in dataset/source/model/scorer/partition/mode limit direct comparison; same-source rephrasing is not independent generalization."}

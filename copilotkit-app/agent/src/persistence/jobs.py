"""Transactional task/plan lifecycle and outbox; no worker runs in this module."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from copy import deepcopy
from sqlalchemy import exists, select, update
from sqlalchemy.dialects.postgresql import insert

from src.persistence.database import transaction
from src.persistence.models import Document, HiddenTask, Job, Outbox, Report, RunEvent, Schedule

UTC = timezone.utc
TERMINAL = frozenset({"complete", "partial", "failed", "cancelled"})


class MissingRecord(LookupError):
    pass


class StateConflict(RuntimeError):
    pass


def iso(value):
    return value.astimezone(UTC).isoformat() if value is not None else None


def fail_execution(db, job, error):
    """Keep an interrupted report's evidence but end its visible progress state."""
    job.status, job.error = "failed", error
    if job.kind in {"document", "knowledge"}:
        document = db.get(Document, job.config.get("document_id")) if job.config.get("document_id") else None
        if job.kind == "document" and document and document.active_job_id == job.id:
            document.status = "failed"
        job.progress = [{**stage, "status": "failed" if stage.get("status") == "running" else stage.get("status")} for stage in job.progress]
    report = db.scalar(select(Report).where(Report.id == job.id).with_for_update())
    if report is not None:
        body = deepcopy(report.body)
        body["status"], body["error"] = "failed", error
        for stage in body.get("stages", []):
            if stage.get("status") == "running":
                stage["status"] = "failed"
        report.body = body
    db.add(RunEvent(run_id=job.id, event_id=str(uuid4()), kind="task.failed", payload={"status": "failed", "error": error}))


class JobRepository:
    def __init__(self, bind=None):
        self.bind = bind

    @staticmethod
    def enqueue(db, name, config, schedule_id=None, *, deduplication_key=None, kind="research"):
        if kind not in {"research", "document", "knowledge"}:
            raise ValueError("Unknown job kind")
        key = str(uuid4())
        now = datetime.now(UTC)
        db.add(Job(id=key, name=name, config=config, kind=kind, schedule_id=schedule_id, status="queued", created_at=now))
        db.add(Outbox(id=str(uuid4()), topic="knowledge.execute" if kind == "knowledge" else "document.execute" if kind == "document" else "research.execute", aggregate_id=key, payload={"job_id": key},
                      deduplication_key=deduplication_key or f"research.execute:{key}"))
        db.flush()
        return key

    def create_job(self, name, config):
        with transaction(self.bind) as db:
            return self.enqueue(db, name, config)

    def list_tasks(self, schedule_id=None, kind=None, limit=None):
        if limit is not None and (isinstance(limit, bool) or not 1 <= limit <= 100):
            raise ValueError("Task limit must be between 1 and 100")
        if kind not in (None, "manual", "scheduled", "document", "knowledge"):
            raise ValueError("Unknown task kind")
        with transaction(self.bind) as db:
            query = select(Job, Report.id.label("report_id"), Report.body["assessment"]["summary"].astext.label("summary")).outerjoin(
                Report, (Report.id == Job.id) & Report.archived.is_(False))
            if schedule_id:
                query = query.where(Job.schedule_id == schedule_id)
            else:
                query = query.where(~exists(select(HiddenTask.id).where(HiddenTask.id == Job.id)))
            if kind:
                if kind in {"document", "knowledge"}:
                    query = query.where(Job.kind == kind)
                else:
                    query = query.where(Job.kind == "research", Job.schedule_id.is_(None) if kind == "manual" else Job.schedule_id.is_not(None))
            query = query.order_by(Job.created_at.desc(), Job.record_order.desc())
            if limit is not None:
                query = query.limit(limit)
            result = [{"id": job.id, "name": job.name, "symbol": job.config.get("symbol", ""), "kind": job.kind if job.kind in {"document", "knowledge"} else "scheduled" if job.schedule_id else "manual",
                       "document_id": job.result.get("document_id") or job.config.get("document_id"),
                       "schedule_id": job.schedule_id, "trigger": job.config.get("_trigger"), "managed": True, "summary": summary,
                       "status": job.status, "created_at": iso(job.created_at), "error": job.error, "report_id": report_id}
                      for job, report_id, summary in db.execute(query)]
            if schedule_id is None and kind in (None, "manual"):
                legacy = select(Report.id, Report.body["symbol"].astext, Report.body["status"].astext,
                                Report.body["created_at"].astext).where(
                    Report.archived.is_(False), ~exists(select(Job.id).where(Job.id == Report.id)),
                    ~exists(select(HiddenTask.id).where(HiddenTask.id == Report.id))).order_by(Report.record_order.desc())
                if limit is not None:
                    legacy = legacy.limit(limit)
                result.extend({"id": key, "name": f"{symbol} 单股分析", "symbol": symbol, "kind": "manual", "status": status,
                               "created_at": created_at, "report_id": key} for key, symbol, status, created_at in db.execute(legacy))
            result.sort(key=lambda item: item["created_at"], reverse=True)
            return result[:limit]

    def task_detail(self, key):
        with transaction(self.bind) as db:
            job = db.get(Job, key)
            report = db.scalar(select(Report.body).where(Report.id == key, Report.archived.is_(False)))
            if job is None and report is None:
                raise MissingRecord("Task does not exist")
            payload = job.config if job is not None else report["config"]
            if job is not None and job.kind in {"document", "knowledge"}:
                return {"id": key, "name": job.name, "kind": job.kind, "status": job.status, "error": job.error,
                        "document_id": job.result.get("document_id") or job.config.get("document_id"), "config": {},
                        "result": job.result, "stages": job.progress, "elapsed_seconds": job.elapsed_seconds,
                        "report_id": None, "has_assessment": False}
            return {"id": key, "name": job.name if job else f"{report['symbol']} 单股分析",
                    "status": job.status if job else report["status"], "error": job.error if job else None,
                    "config": payload, "workflow": (payload.get("_brief") or {}).get("workflow"),
                    "report_id": report["id"] if report else None, "stages": report.get("stages", []) if report else [],
                    "elapsed_seconds": report.get("elapsed_seconds", 0) if report else 0,
                    "has_assessment": bool(report and report.get("assessment")),
                    "observability": report.get("observability") if report else None}

    def hide_task(self, key):
        with transaction(self.bind) as db:
            job = db.scalar(select(Job).where(Job.id == key).with_for_update())
            report = db.scalar(select(Report).where(Report.id == key, Report.archived.is_(False)).with_for_update())
            if job is None and report is None:
                raise MissingRecord("Task does not exist")
            if (job.status if job else report.body["status"]) not in TERMINAL:
                raise StateConflict("Wait for this task to finish before deleting its execution record")
            db.execute(insert(HiddenTask).values(id=key).on_conflict_do_nothing())

    def create_schedule(self, body, next_run):
        key = str(uuid4())
        with transaction(self.bind) as db:
            db.add(Schedule(id=key, body=body, next_run=next_run))
        return key

    def list_schedules(self):
        with transaction(self.bind) as db:
            return [{"id": item.id, **item.body, "next_run": iso(item.next_run), "version": item.version}
                    for item in db.scalars(select(Schedule).where(Schedule.archived.is_(False)).order_by(Schedule.record_order.desc()))]

    def update_schedule(self, key, body, next_run):
        with transaction(self.bind) as db:
            result = db.execute(update(Schedule).where(Schedule.id == key, Schedule.archived.is_(False)).values(
                body=body, next_run=next_run, version=Schedule.version + 1))
            if not result.rowcount:
                raise MissingRecord("Schedule does not exist")

    def archive_schedule(self, key):
        with transaction(self.bind) as db:
            result = db.execute(update(Schedule).where(Schedule.id == key, Schedule.archived.is_(False)).values(
                archived=True, next_run=None, version=Schedule.version + 1))
            if not result.rowcount:
                raise MissingRecord("Schedule does not exist")

    def run_schedule(self, key, build_payload, *, trigger="manual"):
        with transaction(self.bind) as db:
            plan = db.scalar(select(Schedule).where(Schedule.id == key, Schedule.archived.is_(False)).with_for_update())
            if plan is None:
                raise MissingRecord("Schedule does not exist")
            active = db.scalar(select(Job.id).where(Job.schedule_id == key, Job.status.in_(["queued", "running"])))
            if active:
                return {"id": active, "existing": True}
            payload = build_payload(plan.body)
            payload["_trigger"] = trigger
            return {"id": self.enqueue(db, plan.body["name"], payload, key), "existing": False}

    def claim(self, key, token, *, now=None, lease_seconds=90):
        now = now or datetime.now(UTC)
        with transaction(self.bind) as db:
            job = db.scalar(select(Job).where(Job.id == key).with_for_update())
            if job is None or job.status in TERMINAL:
                return {"state": "finished", "status": job.status if job else "missing"}
            if job.cancel_requested:
                job.status, job.error = "cancelled", None
                return {"state": "finished", "status": "cancelled"}
            if job.status == "running" and job.lease_until and job.lease_until > now:
                return {"state": "leased", "retry_after": max(1, int((job.lease_until - now).total_seconds()))}
            job.status, job.lease_token, job.lease_until = "running", token, now + timedelta(seconds=lease_seconds)
            job.started_at = job.started_at or now
            job.version += 1
            return {"state": "claimed", "config": job.config, "version": job.version}

    def heartbeat(self, key, token, *, now=None, lease_seconds=90):
        now = now or datetime.now(UTC)
        with transaction(self.bind) as db:
            result = db.execute(update(Job).where(Job.id == key, Job.status == "running", Job.lease_token == token,
                                                  Job.cancel_requested.is_(False), Job.lease_until > now).values(
                lease_until=now + timedelta(seconds=lease_seconds)))
            return bool(result.rowcount)

    def finish(self, key, token, status, *, error=None, now=None):
        if status not in TERMINAL:
            raise ValueError("Completion requires a terminal status")
        now = now or datetime.now(UTC)
        with transaction(self.bind) as db:
            result = db.execute(update(Job).where(Job.id == key, Job.status == "running", Job.lease_token == token,
                                                  Job.lease_until > now, Job.cancel_requested.is_(False)).values(
                status=status, error=error, lease_token=None, lease_until=None, version=Job.version + 1))
            if result.rowcount and status == "failed":
                job = db.get(Job, key)
                fail_execution(db, job, error or ("Document processing could not complete." if job.kind == "document" else "Research could not complete."))
            return bool(result.rowcount)

    def save_report(self, key, token, report, *, now=None):
        if report["id"] != key:
            raise StateConflict("A task cannot publish a report under another ID")
        now = now or datetime.now(UTC)
        with transaction(self.bind) as db:
            job = db.scalar(select(Job).where(Job.id == key).with_for_update())
            if (job is None or job.status != "running" or job.lease_token != token or job.cancel_requested
                    or job.lease_until is None or job.lease_until <= now):
                raise StateConflict("The execution lease is no longer valid")
            statement = insert(Report).values(id=key, body=deepcopy(report))
            db.execute(statement.on_conflict_do_update(index_elements=[Report.id], set_={"body": statement.excluded.body}))
            db.add(RunEvent(run_id=key, event_id=str(uuid4()), kind="research.progress", payload={
                "status": report["status"], "stages": report.get("stages", []), "elapsed_seconds": report.get("elapsed_seconds", 0),
            }))

    def cancel(self, key):
        with transaction(self.bind) as db:
            job = db.scalar(select(Job).where(Job.id == key).with_for_update())
            if job is None:
                raise MissingRecord("Task does not exist")
            if job.status not in TERMINAL:
                job.cancel_requested, job.status = True, "cancelled"
                job.lease_token, job.lease_until = None, None
                job.version += 1
                report = db.get(Report, key)
                if report is not None:
                    body = deepcopy(report.body)
                    body["status"] = "cancelled"
                    for stage in body.get("stages", []):
                        if stage.get("status") == "running":
                            stage["status"] = "cancelled"
                    report.body = body
                if job.kind in {"document", "knowledge"}:
                    document = db.get(Document, job.config.get("document_id")) if job.config.get("document_id") else None
                    if job.kind == "document" and document and document.active_job_id == key:
                        document.status = "cancelled"
                    job.progress = [{**stage, "status": "cancelled" if stage.get("status") == "running" else stage.get("status")} for stage in job.progress]
                db.add(RunEvent(run_id=key, event_id=str(uuid4()), kind="task.cancelled", payload={"status": "cancelled"}))
            return job.status

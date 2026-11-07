"""Real worker entry points. Importing this file never executes saved schedules."""
import asyncio
from datetime import datetime, timezone
import json
import os

from redis import Redis
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from src.infrastructure.config import Infrastructure, environment
from src.infrastructure.loops import loop_factory
from src.jobs.celery_app import app
from src.jobs.runner import ExecutionBusy, run_job
from src.persistence.database import engine
from src.persistence.jobs import StateConflict


def execute_job(self, job_id):
    try:
        with asyncio.Runner(loop_factory=loop_factory) as runner:
            return runner.run(run_job(job_id))
    except ExecutionBusy as error:
        raise self.retry(countdown=error.retry_after) from None
    except (OperationalError, StateConflict):
        # Existing lease or infrastructure outage is recoverable, not a fake report.
        raise self.retry(countdown=15) from None


@app.task(name="aperture.research", bind=True, max_retries=20)
def research(self, job_id):
    return execute_job(self, job_id)


@app.task(name="aperture.document", bind=True, max_retries=20)
def document(self, job_id):
    return execute_job(self, job_id)


@app.task(name="aperture.knowledge", bind=True, max_retries=20)
def knowledge(self, job_id):
    return execute_job(self, job_id)


def scheduling_enabled():
    return str(environment().get("RESEARCH_SCHEDULER_ENABLED", "false")).lower() == "true"


@app.task(name="aperture.schedule")
def scan_schedules():
    if not scheduling_enabled():
        return {"status": "maintenance_paused"}
    from src.workbench import dispatch_due_schedules, sync_trading_schedules
    with engine().connect() as connection:
        locked = connection.execute(text("SELECT pg_try_advisory_lock(19384721)")).scalar_one()
        connection.commit()
        if not locked:
            return {"status": "already_scanning"}
        try:
            now = datetime.now(timezone.utc)
            count = dispatch_due_schedules(now)
            with asyncio.Runner(loop_factory=loop_factory) as runner:
                runner.run(sync_trading_schedules(now, {}))
            return {"clock_plans": count}
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(19384721)"))
            connection.commit()


@app.task(name="aperture.checks")
def scan_checks():
    if not scheduling_enabled():
        return {"status": "maintenance_paused"}
    from src.review_checks import run_due_checks, SHANGHAI
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(run_due_checks(datetime.now(SHANGHAI)))


@app.task(name="aperture.heartbeat")
def heartbeat():
    settings = Infrastructure.read()
    with Redis.from_url(settings.redis_url, socket_connect_timeout=5, socket_timeout=5) as client:
        client.set("aperture:maintenance:heartbeat", json.dumps({"time": datetime.now(timezone.utc).isoformat(),
                   "pid": os.getpid(), "scheduler_enabled": scheduling_enabled()}), ex=90)
    return {"status": "ready"}

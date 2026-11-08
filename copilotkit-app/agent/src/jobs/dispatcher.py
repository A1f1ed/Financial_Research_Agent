"""Independent transactional-outbox publisher; remains active during broker outages."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import time

from uuid import uuid4
from sqlalchemy import exists, or_, select
from src.persistence.database import transaction
from src.persistence.models import Job, Outbox
from src.persistence.jobs import fail_execution

UTC = timezone.utc


def dispatch(publish, *, bind=None, now=None, limit=10, max_attempts=10):
    now = now or datetime.now(UTC)
    sent, failed = 0, 0
    with transaction(bind) as db:
        rows = db.scalars(select(Outbox).where(Outbox.delivered_at.is_(None), Outbox.failed_at.is_(None),
            Outbox.available_at <= now).order_by(Outbox.created_at).with_for_update(skip_locked=True).limit(limit)).all()
        for row in rows:
            try:
                publish(row.topic, row.payload, row.id)
            except Exception as error:
                row.attempts += 1
                row.error_type = type(error).__name__[:100]
                row.available_at = now + timedelta(seconds=min(300, 2 ** min(row.attempts, 8)))
                if row.attempts >= max_attempts:
                    row.failed_at = now
                    job = db.get(Job, row.aggregate_id)
                    if job and job.status == "queued":
                        fail_execution(db, job, "Task dispatch failed; retry creates a new execution.")
                failed += 1
                break  # Do not hold database locks across repeated broker connection timeouts.
            row.delivered_at, row.error_type = now, None
            row.attempts += 1
            sent += 1
    return {"sent": sent, "failed": failed}


def recover(*, bind=None, now=None, max_recoveries=3):
    """Recover lost workers/abandoned deliveries, with a bounded business retry budget."""
    now = now or datetime.now(UTC)
    pending = exists(select(Outbox.id).where(Outbox.aggregate_id == Job.id, Outbox.delivered_at.is_(None), Outbox.failed_at.is_(None)))
    old_delivery = exists(select(Outbox.id).where(Outbox.aggregate_id == Job.id, Outbox.delivered_at < now - timedelta(minutes=30)))
    with transaction(bind) as db:
        rows = db.scalars(select(Job).where(Job.cancel_requested.is_(False), or_(
            (Job.status == "running") & (Job.lease_until <= now),
            (Job.status == "queued") & old_delivery & ~pending)).with_for_update(skip_locked=True).limit(20)).all()
        for job in rows:
            job.version += 1
            job.lease_token, job.lease_until = None, None
            if job.recovery_attempts >= max_recoveries:
                fail_execution(db, job, "Execution recovery limit reached; completed evidence is retained.")
                continue
            job.recovery_attempts += 1
            job.status = "queued"
            db.add(Outbox(id=str(uuid4()), topic="evaluation.execute" if job.kind == "evaluation" else "knowledge.execute" if job.kind == "knowledge" else "document.execute" if job.kind == "document" else "research.execute", aggregate_id=job.id, payload={"job_id": job.id},
                          deduplication_key=f"research.recovery:{job.id}:{job.version}"))
        return len(rows)


def publish(topic, payload, delivery_id):
    from src.jobs.celery_app import app
    routes = {"research.execute": ("aperture.research", "research"), "document.execute": ("aperture.document", "documents"),
              "knowledge.execute": ("aperture.knowledge", "knowledge"), "evaluation.execute": ("aperture.evaluation", "evaluation")}
    if topic not in routes or set(payload) != {"job_id"}:
        raise ValueError("Unregistered outbox message")
    task, queue = routes[topic]
    app.send_task(task, kwargs=payload, task_id=delivery_id, queue=queue, retry=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        try:
            recover()
            result = dispatch(publish)
            if result["sent"] or result["failed"] or args.once:
                print(json.dumps({"component": "outbox", **result}), flush=True)
        except Exception as error:
            print(json.dumps({"component": "outbox", "error_type": type(error).__name__}), flush=True)
            if args.once:
                raise SystemExit(1) from None
        if args.once:
            return
        time.sleep(1)


if __name__ == "__main__":
    main()

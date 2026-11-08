"""Independent Celery execution; durable state lives in PostgreSQL, not results."""
from pathlib import Path
from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
from dotenv import load_dotenv
from src.infrastructure.config import Infrastructure
from src.persistence.database import dispose_engines

load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)
settings = Infrastructure.read()
app = Celery("aperture", broker=settings.broker_url, include=["src.jobs.tasks"])
app.conf.update(
    task_serializer="json", accept_content=["json"], result_serializer="json", task_ignore_result=True,
    task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
    broker_connection_timeout=5, broker_connection_retry_on_startup=True, task_publish_retry=False,
    broker_transport_options={"confirm_publish": True}, timezone="UTC", enable_utc=True,
    task_routes={"aperture.research": {"queue": "research"}, "aperture.schedule": {"queue": "maintenance"},
                 "aperture.evaluation": {"queue": "evaluation"},
                 "aperture.document": {"queue": "documents"},
                 "aperture.knowledge": {"queue": "knowledge"},
                 "aperture.checks": {"queue": "maintenance"}, "aperture.heartbeat": {"queue": "maintenance"}},
    beat_schedule={
        "schedules": {"task": "aperture.schedule", "schedule": 10.0},
        "checks": {"task": "aperture.checks", "schedule": 30.0},
        "maintenance-heartbeat": {"task": "aperture.heartbeat", "schedule": 20.0},
    },
)


@worker_process_init.connect
def reset_pools(**_kwargs):
    dispose_engines()


@worker_process_shutdown.connect
def close_pools(**_kwargs):
    dispose_engines()
    from src.infrastructure.telemetry import shutdown
    shutdown()

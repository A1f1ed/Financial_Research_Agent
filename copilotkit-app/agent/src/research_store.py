"""PostgreSQL report storage; provider credentials never enter this database."""
import os
from pathlib import Path
from src.persistence.business import BusinessRepository
from src.persistence.database import transaction
from src.persistence.execution import current_execution
from src.persistence.jobs import JobRepository

DATA_DIR = Path(os.getenv("RESEARCH_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
connect = transaction  # SQLAlchemy sessions; no string-SQL compatibility layer.


def save_report(report):
    execution = current_execution.get()
    if execution is not None:
        return JobRepository().save_report(execution[0], execution[1], report)
    return BusinessRepository().save_report(report)


def get_report(report_id):
    return BusinessRepository().get_report(report_id)


def list_reports(limit=None):
    return BusinessRepository().list_reports(limit)


def archive_report(report_id):
    return BusinessRepository().archive_report(report_id)

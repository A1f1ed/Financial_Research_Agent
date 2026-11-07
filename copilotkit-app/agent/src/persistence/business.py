"""PostgreSQL repositories for reports, settings, bounded cache and follow-ups."""
from copy import deepcopy

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from src.persistence.database import transaction
from src.persistence.models import Followup, Preference, Report
from src.infrastructure.cache import MarketCache


class BusinessRepository:
    def __init__(self, bind=None):
        self.bind = bind

    def save_report(self, report):
        statement = insert(Report).values(id=report["id"], body=deepcopy(report))
        with transaction(self.bind) as db:
            db.execute(statement.on_conflict_do_update(index_elements=[Report.id], set_={"body": statement.excluded.body}))

    def get_report(self, report_id, *, include_archived=False):
        query = select(Report.body).where(Report.id == report_id)
        if not include_archived:
            query = query.where(Report.archived.is_(False))
        with transaction(self.bind) as db:
            return db.scalar(query)

    def list_reports(self, limit=None):
        if limit is not None and (isinstance(limit, bool) or not 1 <= limit <= 1000):
            raise ValueError("Report limit must be between 1 and 1000")
        fields = ("id", "symbol", "as_of", "created_at", "status", "config", "assessment", "elapsed_seconds", "workflow")
        # Project the API's requested fields inside PostgreSQL, not after loading
        # every complete report/evidence body into the Python process.
        query = select(*(Report.body[field].label(field) for field in fields)).where(
            Report.archived.is_(False)).order_by(Report.record_order.desc())
        if limit is not None:
            query = query.limit(limit)
        with transaction(self.bind) as db:
            return [dict(row) for row in db.execute(query).mappings()]

    def archive_report(self, report_id):
        with transaction(self.bind) as db:
            return db.execute(update(Report).where(Report.id == report_id).values(archived=True)).rowcount > 0

    def read_setting(self, key, default=None):
        with transaction(self.bind) as db:
            row = db.execute(select(Preference.body).where(Preference.key == key)).one_or_none()
            return row[0] if row is not None else deepcopy(default)

    def write_settings(self, values):
        if not values:
            return
        statement = insert(Preference)
        with transaction(self.bind) as db:
            db.execute(statement.on_conflict_do_update(index_elements=[Preference.key],
                                                       set_={"body": statement.excluded.body}),
                       [{"key": key, "body": deepcopy(value)} for key, value in values.items()])

    def cached(self, key, ttl_seconds, *, now=None):
        return MarketCache(self.bind).get(key, ttl_seconds, now=now)

    def put_cache(self, key, value, *, fetched=None):
        return MarketCache(self.bind).put(key, value, fetched=fetched)

    def followups(self, thread_id, message_id, report_id=""):
        with transaction(self.bind) as db:
            return db.scalar(select(Followup.questions).where(Followup.thread_id == thread_id,
                                                               Followup.message_id == message_id, Followup.report_id == report_id))

    def save_followups(self, thread_id, message_id, questions, report_id=""):
        # A replay or duplicate request cannot replace the first completed result.
        with transaction(self.bind) as db:
            db.execute(insert(Followup).values(thread_id=thread_id, message_id=message_id, report_id=report_id,
                                               questions=list(questions)).on_conflict_do_nothing())

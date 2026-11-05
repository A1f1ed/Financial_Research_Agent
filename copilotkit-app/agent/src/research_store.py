"""Single-user local report library. Provider credentials never enter this database."""
import json
import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

DATA_DIR = Path(os.getenv("RESEARCH_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB = DATA_DIR / "research.sqlite3"


@contextmanager
def connect():
    with closing(sqlite3.connect(DB, timeout=20)) as connection, connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, body TEXT NOT NULL, archived INTEGER DEFAULT 0)")
        connection.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, body TEXT NOT NULL, fetched REAL NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, body TEXT NOT NULL)")
        yield connection


def save_report(report):
    with connect() as db:
        db.execute("INSERT INTO reports(id,body) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                   (report["id"], json.dumps(report, ensure_ascii=False)))


def get_report(report_id):
    with connect() as db:
        row = db.execute("SELECT body FROM reports WHERE id=? AND archived=0", (report_id,)).fetchone()
    return json.loads(row[0]) if row else None


def list_reports(limit=None):
    with connect() as db:
        rows = db.execute("SELECT body FROM reports WHERE archived=0 ORDER BY rowid DESC LIMIT ?", (limit or -1,)).fetchall()
    return [{k: r.get(k) for k in ("id", "symbol", "as_of", "created_at", "status", "config", "assessment", "elapsed_seconds", "workflow")}
            for row in rows for r in [json.loads(row[0])]]


def archive_report(report_id):
    with connect() as db:
        db.execute("UPDATE reports SET archived=1 WHERE id=?", (report_id,))

"""Offline, read-only legacy import. Never runs agents, schedules or model calls.

The source databases are snapshotted with SQLite's backup API. Business import is
one PostgreSQL transaction; existing differing rows abort rather than overwrite.
Checkpoints are decoded/encoded through official savers, not copied as SQL rows.
"""
import argparse
import base64
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Send
from psycopg import connect as pg_connect, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, func, select, text
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.engine import make_url

from src.infrastructure.config import Infrastructure, ROOT
from src.persistence.database import engine_for
from src.persistence.models import LEGACY_MODELS

AGENT_ROOT = Path(__file__).resolve().parents[2]


def canonical(value):
    def encode(item):
        if isinstance(item, BaseModel):
            return {"__model__": type(item).__name__, "value": item.model_dump(mode="python")}
        if isinstance(item, Send):
            return {"__send__": item.node, "arg": item.arg}
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        if isinstance(item, bytes):
            return {"__bytes__": base64.b64encode(item).decode("ascii")}
        if isinstance(item, (set, frozenset)):
            return sorted(item, key=repr)
        raise TypeError(f"Unsupported verification type: {type(item).__name__}")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=encode)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


@contextmanager
def readonly(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        yield connection


def snapshot(source, destination):
    if not source.is_file():
        raise FileNotFoundError(source.name)
    with readonly(source) as incoming, closing(sqlite3.connect(destination)) as outgoing:
        incoming.backup(outgoing)
    return {"name": source.name, "snapshot_sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}


def upgrade(bind):
    config = Config(str(AGENT_ROOT / "alembic.ini"))
    with bind.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def legacy_rows(connection, model):
    table = model.__table__
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table.name,)).fetchone()
    if not exists:
        return []
    connection.row_factory = sqlite3.Row
    incoming = []
    for row in connection.execute(f'SELECT rowid AS _legacy_order, * FROM "{table.name}" ORDER BY rowid'):
        converted = {}
        for key in row.keys():
            if key == "_legacy_order":
                if "record_order" in table.c:
                    converted["record_order"] = row[key]
                continue
            value, column = row[key], table.c[key]
            if isinstance(column.type, JSONB):
                value = json.loads(value)
            elif isinstance(column.type, Boolean):
                value = bool(value)
            elif isinstance(column.type, DateTime) and value is not None:
                value = datetime.fromisoformat(value)
                if value.tzinfo is None:
                    raise ValueError(f"Naive legacy timestamp in {table.name}.{key}")
                value = value.astimezone(timezone.utc)
            converted[key] = value
        canonical(converted)
        incoming.append(converted)
    return incoming


def verify_business_rows(target, table, incoming):
    actual_count = target.execute(select(func.count()).select_from(table)).scalar_one()
    if actual_count != len(incoming):
        raise ValueError(f"Row count mismatch or nonempty target: {table.name}")
    primary = list(table.primary_key.columns)
    actual = {tuple(row[column.name] for column in primary): row for row in target.execute(select(table)).mappings()}
    for row in incoming:
        key = tuple(row[column.name] for column in primary)
        existing = actual[key]
        if canonical({name: existing[name] for name in row}) != canonical(row):
            raise ValueError(f"Existing row differs from source: {table.name}")
    return {"count": actual_count, "semantic_sha256": digest(incoming)}


def import_business(source, bind):
    counts = {}
    with readonly(source) as legacy, bind.begin() as target:
        legacy.row_factory = sqlite3.Row
        available = {row[0] for row in legacy.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        unexpected = available - set(LEGACY_MODELS) - {"sqlite_sequence"}
        if unexpected:
            raise ValueError("Unmapped source tables: " + ", ".join(sorted(unexpected)))
        for name, model in LEGACY_MODELS.items():
            table = model.__table__
            incoming = legacy_rows(legacy, model)
            if incoming:
                target.execute(insert(table).on_conflict_do_nothing(), incoming)
            counts[name] = verify_business_rows(target, table, incoming)
            if "record_order" in table.c:
                # Explicit legacy insertion order must not collide with future identities.
                target.execute(text("SELECT setval(pg_get_serial_sequence(:table, 'record_order'), :next, false)"),
                               {"table": f"research.{name}", "next": max((r["record_order"] for r in incoming), default=0) + 1})
    return counts


def import_checkpoints(source, conninfo):
    with readonly(source) as connection, pg_connect(conninfo, autocommit=True, prepare_threshold=0, row_factory=dict_row) as target:
        serde = JsonPlusSerializer(allowed_msgpack_modules=[("ag_ui.core.types", "Context")])
        legacy = SqliteSaver(connection, serde=serde)
        # The validated read-only snapshot already has the source schema. Do not
        # let SqliteSaver issue CREATE/ALTER/PRAGMA writes against it.
        legacy.is_setup = True
        tuples = list(legacy.list(None))
        saver = PostgresSaver(target, serde=serde)
        saver.setup()
        expected_keys = {(item.config["configurable"]["thread_id"], item.config["configurable"].get("checkpoint_ns", ""),
                          item.checkpoint["id"]) for item in tuples}
        actual_keys = {tuple(row[key] for key in ("thread_id", "checkpoint_ns", "checkpoint_id")) for row in
                       target.execute("SELECT thread_id,checkpoint_ns,checkpoint_id FROM checkpoints")}
        if not actual_keys.issubset(expected_keys):
            raise ValueError("Checkpoint target contains a different history")
        for item in sorted(tuples, key=lambda entry: (entry.config["configurable"]["thread_id"],
                                                     entry.config["configurable"].get("checkpoint_ns", ""), entry.checkpoint["id"])):
            existing = saver.get_tuple(item.config)
            if existing is not None:
                if digest(existing.checkpoint) != digest(item.checkpoint):
                    raise ValueError("Existing checkpoint differs; refusing overwrite")
                if Counter(canonical(write) for write in existing.pending_writes or []) - Counter(
                        canonical(write) for write in item.pending_writes or []):
                    raise ValueError("Existing pending writes differ; refusing overwrite")
                continue
            parent = item.parent_config or {"configurable": {**item.config["configurable"], "checkpoint_id": None}}
            saver.put(parent, item.checkpoint, item.metadata, item.checkpoint["channel_versions"])
        groups = defaultdict(list)
        for thread, namespace, checkpoint, task, path, channel, kind, value in connection.execute(
                "SELECT thread_id,checkpoint_ns,checkpoint_id,task_id,task_path,channel,type,value FROM writes "
                "ORDER BY thread_id,checkpoint_ns,checkpoint_id,task_id,idx"):
            groups[(thread, namespace, checkpoint, task, path)].append((channel, legacy.serde.loads_typed((kind, value))))
        for (thread, namespace, checkpoint, task, path), writes in groups.items():
            saver.put_writes({"configurable": {"thread_id": thread, "checkpoint_ns": namespace, "checkpoint_id": checkpoint}},
                             writes, task, path)
        verified = []
        for item in tuples:
            restored = saver.get_tuple(item.config)
            if restored is None or digest(restored.checkpoint) != digest(item.checkpoint):
                raise ValueError("Checkpoint round-trip mismatch")
            if digest(restored.parent_config) != digest(item.parent_config):
                raise ValueError("Checkpoint parent mismatch")
            if digest(restored.pending_writes) != digest(item.pending_writes):
                raise ValueError("Checkpoint pending-write mismatch")
            if any(digest(restored.metadata.get(key)) != digest(value) for key, value in item.metadata.items()):
                raise ValueError("Checkpoint metadata mismatch")
            verified.append({"config": item.config, "hash": digest(item.checkpoint)})
        actual = target.execute("SELECT count(*) AS count FROM checkpoints").fetchone()["count"]
        writes = target.execute("SELECT count(*) AS count FROM checkpoint_writes").fetchone()["count"]
        expected_writes = connection.execute("SELECT count(*) FROM writes").fetchone()[0]
        if actual != len(tuples) or writes != expected_writes:
            raise ValueError("Checkpoint or pending-write count mismatch")
        return {"count": actual, "writes": writes, "semantic_sha256": digest(verified)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=AGENT_ROOT / "data")
    parser.add_argument("--database", required=True, help="Isolated aperture_rehearsal_* target database")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"aperture_rehearsal_[a-z0-9_]+", args.database):
        parser.error("Rehearsal command requires an isolated aperture_rehearsal_* database; runtime cutover is separate")
    settings = Infrastructure.read()
    destination = args.backup_dir or ROOT / "local-data/migrations" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination.mkdir(parents=True, exist_ok=False)
    report = {"target_database": args.database, "started_at": datetime.now(timezone.utc).isoformat(), "status": "running"}
    try:
        report["snapshots"] = [snapshot(args.source_dir / name, destination / name)
                               for name in ("research.sqlite3", "checkpoints.sqlite3")]
        params = conninfo_to_dict(settings.checkpoint_url)
        with pg_connect(make_conninfo(**params), autocommit=True) as admin:
            exists = admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (args.database,)).fetchone()
            if exists is None:
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(args.database)))
        url = make_url(settings.database_url).set(database=args.database).render_as_string(hide_password=False)
        bind = engine_for(url)
        upgrade(bind)
        report["business"] = import_business(destination / "research.sqlite3", bind)
        params.update(dbname=args.database, options="-c search_path=agent,public", connect_timeout="5")
        report["checkpoints"] = import_checkpoints(destination / "checkpoints.sqlite3", make_conninfo(**params))
        report["status"] = "verified"
        print(json.dumps({"status": "verified", "business_rows": {key: value["count"] for key, value in report["business"].items()},
                          "checkpoints": report["checkpoints"]["count"], "pending_writes": report["checkpoints"]["writes"]}))
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__)
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        raise SystemExit(1) from None
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        (destination / "migration-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

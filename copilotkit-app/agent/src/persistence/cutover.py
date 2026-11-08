"""Controlled import into the configured application PostgreSQL database.

Requires an offline API, paused scheduler and verified immutable rehearsal input.
It never edits/deletes original databases, changes plan enable flags or runs jobs.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket

from psycopg.conninfo import conninfo_to_dict, make_conninfo

from src.infrastructure.config import Infrastructure, environment
from src.persistence.database import engine
from src.persistence.migrate_legacy import AGENT_ROOT, digest, import_business, import_checkpoints, readonly, upgrade


def source_fingerprint(path):
    """Compare logical SQLite rows/schema, including WAL-visible data, without writes."""
    with readonly(path) as connection:
        tables = connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        result = {}
        for name, schema in tables:
            if not name.replace("_", "").isalnum():
                raise ValueError("Unexpected legacy table name")
            rows = connection.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
            result[name] = {"schema": schema, "rows": digest(rows)}
        return digest(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", required=True, type=Path)
    parser.add_argument("--source-dir", type=Path, default=AGENT_ROOT / "data")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        parser.error("Use --apply after the rehearsal and backup/restore verification")
    if str(environment().get("RESEARCH_SCHEDULER_ENABLED", "false")).lower() == "true":
        parser.error("Pause independent scheduling during cutover")
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(("127.0.0.1", 8123)) == 0:
            parser.error("Stop the API before cutover; it must not write during migration")
    root = args.snapshot_dir.resolve()
    report = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}
    try:
        manifest = json.loads((root / "migration-report.json").read_text(encoding="utf-8"))
        if manifest["status"] != "verified":
            raise ValueError("Rehearsal is not verified")
        recovery = json.loads((root / "recovery-report.json").read_text(encoding="utf-8"))
        if recovery["status"] != "verified_read_only":
            raise ValueError("Backup restore is not verified")
        for item in manifest["snapshots"]:
            if hashlib.sha256((root / item["name"]).read_bytes()).hexdigest() != item["snapshot_sha256"]:
                raise ValueError("Snapshot contents changed")
            if source_fingerprint(root / item["name"]) != source_fingerprint(args.source_dir / item["name"]):
                raise ValueError("Source changed since rehearsal; take a fresh snapshot and rehearsal first")
        bind = engine()
        upgrade(bind)
        report["business"] = import_business(root / "research.sqlite3", bind)
        params = conninfo_to_dict(Infrastructure.read().checkpoint_url)
        params.update(options="-c search_path=agent,public", connect_timeout="5")
        report["checkpoints"] = import_checkpoints(root / "checkpoints.sqlite3", make_conninfo(**params))
        if report["business"] != manifest["business"] or report["checkpoints"] != manifest["checkpoints"]:
            raise ValueError("Cutover differs from verified rehearsal")
        report["status"] = "verified"
        print(json.dumps({"status": "verified", "reports": report["business"]["reports"]["count"],
                          "checkpoints": report["checkpoints"]["count"], "pending_writes": report["checkpoints"]["writes"],
                          "scheduler": "maintenance_paused"}))
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__)
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        raise SystemExit(1) from None
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        (root / "cutover-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

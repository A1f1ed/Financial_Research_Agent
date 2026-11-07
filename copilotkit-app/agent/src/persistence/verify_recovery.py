"""Read-only verification of a pg_restore against an immutable migration snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from psycopg import connect
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from sqlalchemy import text
from sqlalchemy.engine import make_url

from src.infrastructure.config import Infrastructure
from src.persistence.database import engine_for
from src.persistence.migrate_legacy import digest, legacy_rows, readonly, verify_business_rows
from src.persistence.models import LEGACY_MODELS


def verify(snapshot_dir, database):
    if not re.fullmatch(r"aperture_recovery_[a-z0-9_]+", database):
        raise ValueError("Recovery verification requires an isolated aperture_recovery_* database")
    manifest = json.loads((snapshot_dir / "migration-report.json").read_text(encoding="utf-8"))
    if manifest["status"] != "verified":
        raise ValueError("Use a successfully verified migration snapshot")
    for row in manifest["snapshots"]:
        if hashlib.sha256((snapshot_dir / row["name"]).read_bytes()).hexdigest() != row["snapshot_sha256"]:
            raise ValueError("Snapshot hash mismatch")
    settings = Infrastructure.read()
    url = make_url(settings.database_url).set(database=database).render_as_string(hide_password=False)
    with engine_for(url).connect() as target, target.begin():
        target.execute(text("SET TRANSACTION READ ONLY"))
        with readonly(snapshot_dir / "research.sqlite3") as source:
            business = {name: verify_business_rows(target, model.__table__, legacy_rows(source, model))
                        for name, model in LEGACY_MODELS.items()}
    if business != manifest["business"]:
        raise ValueError("Restored business manifest differs")
    params = conninfo_to_dict(settings.checkpoint_url)
    params.update(dbname=database, options="-c search_path=agent,public -c default_transaction_read_only=on")
    serde = JsonPlusSerializer(allowed_msgpack_modules=[("ag_ui.core.types", "Context")])
    verified = []
    with readonly(snapshot_dir / "checkpoints.sqlite3") as source, connect(
            make_conninfo(**params), autocommit=True, prepare_threshold=0, row_factory=dict_row) as target:
        legacy = SqliteSaver(source, serde=serde)
        legacy.is_setup = True
        saver = PostgresSaver(target, serde=serde)
        for original in legacy.list(None):
            recovered = saver.get_tuple(original.config)
            if recovered is None:
                raise ValueError("Restored checkpoint missing")
            for key in ("checkpoint", "pending_writes", "parent_config"):
                if digest(getattr(recovered, key)) != digest(getattr(original, key)):
                    raise ValueError("Restored checkpoint content differs")
            if any(digest(recovered.metadata.get(key)) != digest(value) for key, value in original.metadata.items()):
                raise ValueError("Restored checkpoint metadata differs")
            verified.append({"config": original.config, "hash": digest(original.checkpoint)})
        count = target.execute("SELECT count(*) AS count FROM checkpoints").fetchone()["count"]
        writes = target.execute("SELECT count(*) AS count FROM checkpoint_writes").fetchone()["count"]
    expected = manifest["checkpoints"]
    if (count, writes, digest(verified)) != (expected["count"], expected["writes"], expected["semantic_sha256"]):
        raise ValueError("Restored checkpoint manifest differs")
    return {"status": "verified_read_only", "business_counts": {name: row["count"] for name, row in business.items()},
            "checkpoints": count, "pending_writes": writes}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    try:
        result = verify(args.snapshot_dir.resolve(), args.database)
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        raise SystemExit(1) from None
    print(json.dumps(result))
    (args.snapshot_dir / "recovery-report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

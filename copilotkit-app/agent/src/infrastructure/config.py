"""Server-only infrastructure configuration. Repr and diagnostics never expose URLs/keys."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[4]


def environment():
    path = Path(os.getenv("RESEARCH_INFRA_ENV", ROOT / "infra/.env"))
    return {**dotenv_values(path), **os.environ}


@dataclass(frozen=True, repr=False)
class Infrastructure:
    database_url: str = field(repr=False)
    checkpoint_url: str = field(repr=False)
    broker_url: str = field(repr=False)
    redis_url: str = field(repr=False)
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str = field(repr=False)
    s3_endpoint: str
    s3_access_key: str = field(repr=False)
    s3_secret_key: str = field(repr=False)
    s3_bucket: str
    s3_region: str

    @classmethod
    def read(cls):
        env = environment()
        required = ["DATABASE_URL", "CHECKPOINT_DATABASE_URL", "CELERY_BROKER_URL", "REDIS_URL",
                    "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "S3_ENDPOINT_URL", "S3_ACCESS_KEY", "S3_SECRET_KEY"]
        missing = [name for name in required if not env.get(name)]
        if missing:
            raise RuntimeError("Infrastructure configuration missing: " + ", ".join(missing))
        if make_url(env["DATABASE_URL"]).drivername != "postgresql+psycopg":
            raise ValueError("DATABASE_URL must use postgresql+psycopg; no local database fallback is supported")
        if make_url(env["CHECKPOINT_DATABASE_URL"]).get_backend_name() != "postgresql":
            raise ValueError("CHECKPOINT_DATABASE_URL must use PostgreSQL")
        return cls(env["DATABASE_URL"], env["CHECKPOINT_DATABASE_URL"], env["CELERY_BROKER_URL"], env["REDIS_URL"],
                   env["NEO4J_URI"], env["NEO4J_USER"], env["NEO4J_PASSWORD"], env["S3_ENDPOINT_URL"],
                   env["S3_ACCESS_KEY"], env["S3_SECRET_KEY"], env.get("S3_BUCKET", "aperture-research"),
                   env.get("S3_REGION", "us-east-1"))

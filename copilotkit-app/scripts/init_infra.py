"""Create local-only service credentials once, without printing or replacing secrets."""
import argparse
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "infra/.env")
    args = parser.parse_args()
    target = args.output.resolve()
    if target.exists():
        print("Configuration already exists; no credentials changed.")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    pg, rabbit, redis, neo4j, s3 = (secrets.token_hex(24) for _ in range(5))
    access = "aperture" + secrets.token_hex(8)
    values = {
        "POSTGRES_USER": "aperture", "POSTGRES_DB": "aperture", "POSTGRES_PASSWORD": pg,
        "RABBITMQ_USER": "aperture", "RABBITMQ_PASSWORD": rabbit,
        "REDIS_PASSWORD": redis, "NEO4J_PASSWORD": neo4j,
        "S3_ACCESS_KEY": access, "S3_SECRET_KEY": s3, "S3_BUCKET": "aperture-research",
        "DATABASE_URL": f"postgresql+psycopg://aperture:{pg}@127.0.0.1:15432/aperture",
        "CHECKPOINT_DATABASE_URL": f"postgresql://aperture:{pg}@127.0.0.1:15432/aperture",
        "CELERY_BROKER_URL": f"amqp://aperture:{rabbit}@127.0.0.1:15673/aperture",
        "REDIS_URL": f"redis://:{redis}@127.0.0.1:16379/0",
        "NEO4J_URI": "bolt://127.0.0.1:17687", "NEO4J_USER": "neo4j",
        "S3_ENDPOINT_URL": "http://127.0.0.1:18333", "S3_REGION": "us-east-1",
    }
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Generated local service credentials. Never commit this file.\n")
        stream.writelines(f"{key}={value}\n" for key, value in values.items())
    print("Created local infrastructure configuration. Credentials were not printed.")


if __name__ == "__main__":
    main()

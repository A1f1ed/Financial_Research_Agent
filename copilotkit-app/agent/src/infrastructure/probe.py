"""Real connection/round-trip checks with secret-free output, independent of the app."""
import argparse
import hashlib
import json
import time
from uuid import uuid4

import boto3
from botocore.config import Config
from kombu import Connection, Exchange, Queue
from neo4j import GraphDatabase
from redis import Redis
from sqlalchemy import text

from src.infrastructure.config import Infrastructure
from src.persistence.database import engine_for


def s3_client(settings):
    return boto3.client("s3", endpoint_url=settings.s3_endpoint, region_name=settings.s3_region,
                        aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key,
                        config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=10,
                                      retries={"max_attempts": 1}, s3={"addressing_style": "path"}))


def probe(exercise=False):
    settings = Infrastructure.read()
    results = {}

    def run(name, callback):
        started = time.perf_counter()
        try:
            details = callback()
            results[name] = {"status": "ok", "elapsed_ms": round((time.perf_counter() - started) * 1000, 2), **(details or {})}
        except Exception as error:
            # Exception messages may contain authenticated URLs or vendor payloads.
            results[name] = {"status": "failed", "error_type": type(error).__name__}

    def postgres():
        with engine_for(settings.database_url).connect() as db:
            version = db.execute(text("SELECT version()")).scalar_one().split(" on ")[0]
            extension = db.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'")).scalar_one_or_none()
            if exercise:
                assert extension, "vector extension is not installed"
                distance = db.execute(text("SELECT '[1,0,0]'::vector <=> '[1,0,0]'::vector")).scalar_one()
                assert distance == 0
            return {"version": version, "vector": extension}

    def redis():
        with Redis.from_url(settings.redis_url, socket_timeout=5, socket_connect_timeout=5) as client:
            assert client.ping()
            if exercise:
                key = f"aperture:probe:{uuid4()}"
                try:
                    client.set(key, "probe", ex=15, nx=True)
                    assert client.get(key) == b"probe"
                finally:
                    client.delete(key)

    def graph():
        with GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password),
                                  connection_timeout=5, max_connection_pool_size=2) as driver:
            driver.verify_connectivity()
            records, _, _ = driver.execute_query("RETURN 1 AS ready", database_="neo4j")
            assert records[0]["ready"] == 1

    def broker():
        with Connection(settings.broker_url, connect_timeout=5, transport_options={"confirm_publish": True}) as connection:
            connection.ensure_connection(max_retries=0)
            if exercise:
                queue = Queue(f"aperture.probe.{uuid4()}", exchange=Exchange("", type="direct"),
                              exclusive=True, auto_delete=True, durable=False)(connection)
                queue.declare()
                with connection.Producer() as producer:
                    producer.publish({"probe": True}, exchange="", routing_key=queue.name, serializer="json", retry=False)
                message = queue.get(no_ack=False)
                assert message is not None and message.payload == {"probe": True}
                message.ack()
                queue.delete()

    def objects():
        client = s3_client(settings)
        try:
            client.head_bucket(Bucket=settings.s3_bucket)
            if exercise:
                key, body = f"health/{uuid4()}.txt", b"Aperture S3 authenticated round-trip"
                try:
                    client.put_object(Bucket=settings.s3_bucket, Key=key, Body=body, ContentType="text/plain")
                    response = client.get_object(Bucket=settings.s3_bucket, Key=key)
                    with response["Body"] as stream:
                        retrieved = stream.read()
                    assert hashlib.sha256(retrieved).digest() == hashlib.sha256(body).digest()
                finally:
                    client.delete_object(Bucket=settings.s3_bucket, Key=key)
        finally:
            client.close()

    for name, callback in [("postgres", postgres), ("redis", redis), ("neo4j", graph), ("rabbitmq", broker), ("s3", objects)]:
        run(name, callback)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise", action="store_true", help="Verify vector, Redis, queue and S3 round-trips, then clean probe records")
    args = parser.parse_args()
    results = probe(args.exercise)
    print(json.dumps(results, indent=2))
    if any(result["status"] != "ok" for result in results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

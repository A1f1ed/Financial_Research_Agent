"""Disposable Redis market-data cache. PostgreSQL remains authoritative."""
import hashlib
import json
import time

from redis import Redis
from redis.exceptions import RedisError

from src.infrastructure.config import Infrastructure
from src.persistence.database import engine

MAX_AGE = 86400
MAX_BYTES = 2 * 1024 * 1024


class MarketCache:
    def __init__(self, bind=None):
        self.namespace = "aperture:market:" + (bind if bind is not None else engine()).url.database + ":"

    def client(self):
        return Redis.from_url(Infrastructure.read().redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)

    def key(self, key):
        return self.namespace + hashlib.sha256(key.encode("utf-8")).hexdigest()

    def get(self, key, ttl, *, now=None):
        if ttl <= 0:
            return None
        try:
            with self.client() as client:
                raw = client.get(self.key(key))
            if raw is None or len(raw) > MAX_BYTES:
                return None
            item = json.loads(raw)
            now = time.time() if now is None else now
            if now - min(ttl, MAX_AGE) < item["fetched"] <= now:
                return item["value"]
        except (RedisError, ValueError, TypeError, KeyError):
            # A failed cache never blocks live source retrieval or returns old
            # data as fresh. Credentials/errors are not exposed to consumers.
            return None

    def put(self, key, value, *, fetched=None):
        raw = json.dumps({"fetched": time.time() if fetched is None else fetched, "value": value}, allow_nan=False).encode()
        if len(raw) > MAX_BYTES:
            return False
        try:
            with self.client() as client:
                client.set(self.key(key), raw, ex=MAX_AGE)
            return True
        except RedisError:
            return False

    def clear_test_namespace(self):
        if not self.namespace.startswith("aperture:market:aperture_test_"):
            raise ValueError("Only an isolated test cache namespace may be cleared")
        with self.client() as client:
            for key in client.scan_iter(match=self.namespace + "*", count=100):
                client.delete(key)

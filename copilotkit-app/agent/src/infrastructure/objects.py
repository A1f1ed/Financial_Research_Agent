"""Controlled S3 access; callers use persisted keys, never user-supplied paths."""
import hashlib
import io

import boto3
from botocore.config import Config
from src.infrastructure.config import Infrastructure


def s3_client(settings):
    return boto3.client("s3", endpoint_url=settings.s3_endpoint, region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key,
        config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=15,
                      retries={"max_attempts": 1}, s3={"addressing_style": "path"}))


class ObjectStore:
    def __init__(self, settings=None):
        self.settings = settings or Infrastructure.read()
        self.client = s3_client(self.settings)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def get(self, key, *, max_bytes=50 * 1024 * 1024):
        response = self.client.get_object(Bucket=self.settings.s3_bucket, Key=key)
        with response["Body"] as stream:
            if response["ContentLength"] > max_bytes:
                raise ValueError("Stored object exceeds its allowed size")
            body = stream.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError("Stored object exceeds its allowed size")
        return body

    def put_verified(self, key, body, media_type):
        digest = hashlib.sha256(body).hexdigest()
        self.client.put_object(Bucket=self.settings.s3_bucket, Key=key, Body=io.BytesIO(body),
                               ContentType=media_type, Metadata={"sha256": digest})
        # Confirm actual bytes, not merely the metadata supplied by this client.
        readback = self.get(key, max_bytes=len(body))
        if hashlib.sha256(readback).hexdigest() != digest:
            raise RuntimeError("Object storage integrity check failed")
        return digest

    def delete(self, key):
        self.client.delete_object(Bucket=self.settings.s3_bucket, Key=key)

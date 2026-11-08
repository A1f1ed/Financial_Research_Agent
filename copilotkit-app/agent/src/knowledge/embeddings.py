"""Explicit embedding capability, independent from the chat model profile."""
import hashlib
import json
import math
import os
from datetime import datetime, timezone

from dotenv import dotenv_values, set_key
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, SecretStr, field_validator

from src.preferences import AISettings, ENV_FILE, Provider, profile_settings, provider_key, read_setting, _lock
from src.persistence.business import BusinessRepository
from src.persistence.jobs import StateConflict


class EmbeddingSettings(BaseModel):
    provider: Provider = "dashscope"
    model: str = Field(default="text-embedding-v4", min_length=1, max_length=150, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    base_url: str = Field(default="https://dashscope.aliyuncs.com/compatible-mode/v1", max_length=500)
    dimensions: int = Field(default=1024, ge=64, le=4096)
    timeout: int = Field(default=30, ge=5, le=60)
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)

    @field_validator("base_url")
    @classmethod
    def url(cls, value):
        result = AISettings.valid_url(value)
        if not result or result.endswith("/embeddings"):
            raise ValueError("Enter an HTTPS API base URL without /embeddings")
        return result


def settings():
    return read_setting("embedding", EmbeddingSettings(base_url=profile_settings("dashscope")["base_url"]).model_dump())


def credential(config):
    saved = dotenv_values(ENV_FILE) if ENV_FILE.is_file() else {}
    name = f"APERTURE_EMBEDDING_{config['provider'].upper()}_API_KEY"
    return (saved.get(name) or os.getenv(name) or saved.get("APERTURE_EMBEDDING_API_KEY")
            or os.getenv("APERTURE_EMBEDDING_API_KEY") or provider_key(config["provider"])).strip()


def fingerprint(config):
    # Timeout/key changes do not change the semantic vector space.
    return hashlib.sha256(json.dumps({key: config[key] for key in ("provider", "model", "base_url", "dimensions")}, sort_keys=True).encode()).hexdigest()


def verification_key(config):
    return hashlib.sha256((fingerprint(config) + credential(config)).encode()).hexdigest()


def public_settings():
    config = settings(); test = read_setting("embedding:test", {})
    verified = test.get("verification_key") == verification_key(config) and test.get("status") == "success"
    return {**config, "credential_configured": bool(credential(config)), "verified": verified,
            "test": {key: test.get(key) for key in ("status", "checked_at", "dimensions", "error_type")}}


def save_settings(value):
    with _lock:
        if value.api_key and value.api_key.get_secret_value().strip():
            ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
            set_key(str(ENV_FILE), f"APERTURE_EMBEDDING_{value.provider.upper()}_API_KEY", value.api_key.get_secret_value().strip())
            ENV_FILE.chmod(0o600)
        BusinessRepository().write_settings({"embedding": value.model_dump()})
    return public_settings()


def validate_vectors(response, count, dimensions):
    rows = sorted(response.data, key=lambda item: item.index)
    if [item.index for item in rows] != list(range(count)):
        raise ValueError("Embedding response has missing or duplicate positions")
    vectors = [item.embedding for item in rows]
    for vector in vectors:
        if (len(vector) != dimensions or any(not math.isfinite(value) or abs(value) > 3.4028235e38 for value in vector)
                or sum(value * value for value in vector) <= 0):
            raise ValueError("Embedding response contains an invalid vector or dimension")
    return vectors


async def embed(texts, config, *, require_verified=True):
    if require_verified:
        test = read_setting("embedding:test", {})
        if test.get("verification_key") != verification_key(config) or test.get("status") != "success":
            raise StateConflict("Save and successfully test this embedding configuration before semantic indexing/search")
    key = credential(config)
    if not key: raise StateConflict("Configure an embedding key or a saved provider key first")
    # Two <=900-character chunks fit the documented 8192-token batch limit
    # even under the conservative UTF-8-byte bound. No automatic retries.
    vectors = []; tokens = 0
    async with AsyncOpenAI(api_key=key, base_url=config["base_url"], timeout=config["timeout"], max_retries=0) as client:
        for start in range(0, len(texts), 2):
            batch = texts[start:start+2]
            result = await client.embeddings.create(model=config["model"], input=batch,
                dimensions=config["dimensions"], encoding_format="float")
            vectors.extend(validate_vectors(result, len(batch), config["dimensions"]))
            tokens += getattr(result.usage, "total_tokens", 0) or 0
    return vectors, tokens


async def test_settings():
    config = settings(); result = {"checked_at": datetime.now(timezone.utc).isoformat(), "verification_key": verification_key(config)}
    try:
        vectors, _ = await embed(["Revenue and operating cash flow", "收入与经营现金流"], config, require_verified=False)
        result.update(status="success", dimensions=len(vectors[0]))
    except Exception as error:
        # Provider exception messages can contain URLs, request bodies or keys.
        result.update(status="failed", error_type=type(error).__name__)
    BusinessRepository().write_settings({"embedding:test": result})
    return public_settings()

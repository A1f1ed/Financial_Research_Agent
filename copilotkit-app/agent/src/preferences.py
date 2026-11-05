"""Local runtime preferences. Credentials continue to come from the environment."""
import json
import os

from pydantic import BaseModel, Field

from .research_store import connect


class AISettings(BaseModel):
    model: str = Field(pattern=r"^qwen[A-Za-z0-9._-]*$", max_length=100)
    temperature: float = Field(default=0, ge=0, le=2)
    timeout: int = Field(default=100, ge=10, le=600)


class DataSettings(BaseModel):
    cache_minutes: int = Field(default=15, ge=0, le=120)


def read_setting(key, default=None):
    with connect() as db:
        row = db.execute("SELECT body FROM preferences WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def write_setting(key, value):
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO preferences VALUES (?,?)", (key, value.model_dump_json()))


def public_ai_settings():
    spec = os.getenv("COPILOTKIT_AGENT_MODEL") or "openai:qwen3.8-max"
    return {
        **read_setting("ai", {"model": spec.replace("/", ":", 1).partition(":")[2], "temperature": 0, "timeout": 100}),
        "provider": "DashScope / Qwen",
        "credential_configured": bool(os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")),
    }

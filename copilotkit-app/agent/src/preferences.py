"""Local provider profiles; secrets stay in the server's ignored .env file."""
import json
import os
from pathlib import Path
from threading import RLock
from typing import Literal
from urllib.parse import urlsplit

from dotenv import dotenv_values, set_key
from pydantic import BaseModel, Field, SecretStr, field_validator
from .persistence.business import BusinessRepository

Provider = Literal["dashscope", "deepseek", "glm"]
ENV_FILE = Path(os.getenv("APERTURE_ENV_FILE", Path(__file__).resolve().parents[2] / ".env"))
_lock = RLock()
PROVIDERS = {
    "dashscope": {"label": "DashScope Qwen", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                  "model": "qwen3.8-flash", "models": ["qwen3.8-flash", "qwen3.8-max"],
                  "key_env": "DASHSCOPE_API_KEY", "url_env": "DASHSCOPE_BASE_URL"},
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
                 "model": "deepseek-flash", "models": ["deepseek-flash", "deepseek-v4-pro"],
                 "key_env": "DEEPSEEK_API_KEY", "url_env": "DEEPSEEK_BASE_URL"},
    "glm": {"label": "GLM / Zhipu AI", "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-5.3", "models": ["glm-5.3", "glm-4.7", "glm-4.7-FlashX"],
            "key_env": "ZHIPU_API_KEY", "url_env": "ZHIPU_BASE_URL"},
}


class AISettings(BaseModel):
    provider: Provider = "dashscope"
    model: str = Field(min_length=1, max_length=150, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    base_url: str | None = Field(default=None, max_length=500)
    temperature: float = Field(default=0, ge=0, le=2)
    timeout: int = Field(default=100, ge=10, le=600)
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)

    @field_validator("model", mode="before")
    @classmethod
    def trim_model(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value):
        if not value:
            return None
        value = value.strip().rstrip("/")
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Use an HTTPS API base URL without credentials, query or fragment.")
        if url.path.endswith("/chat/completions"):
            raise ValueError("Enter the API base URL, without /chat/completions.")
        return value


class DataSettings(BaseModel):
    cache_minutes: int = Field(default=15, ge=0, le=120)


def read_setting(key, default=None):
    return BusinessRepository().read_setting(key, default)


def write_setting(key, value):
    BusinessRepository().write_settings({key: value.model_dump(mode="json")})


def profile_settings(provider=None):
    """Read selected profile, including pre-multi-provider Qwen settings."""
    active = read_setting("ai", {})
    spec = os.getenv("COPILOTKIT_AGENT_MODEL", "openai:qwen3.8-max").replace("/", ":", 1)
    env_model = spec.partition(":")[2] or "qwen3.8-max"
    inferred = "deepseek" if env_model.startswith("deepseek") else "glm" if env_model.startswith("glm") else "dashscope"
    selected = active.get("provider", inferred)
    if selected not in PROVIDERS:
        selected = "dashscope"
    provider = provider or selected
    defaults = PROVIDERS[provider]
    saved = read_setting(f"ai:{provider}")
    if saved is None and provider == selected:
        saved = active or {"model": env_model}
    base_url = os.getenv(defaults["url_env"])
    if provider == "glm":
        base_url = base_url or os.getenv("GLM_BASE_URL") or os.getenv("ZAI_BASE_URL")
    result = {"provider": provider, "model": defaults["model"], "temperature": 0, "timeout": 100,
              "base_url": base_url or defaults["base_url"], **(saved or {})}
    # A previously explicit UI address wins; fresh profiles use the user's .env.
    result["provider"] = provider
    result["base_url"] = result.get("base_url") or base_url or defaults["base_url"]
    return result


def provider_key(provider):
    # Saved server-side overrides are shared with independent workers. Reading
    # only os.environ would retain their pre-update credentials indefinitely.
    saved = dotenv_values(ENV_FILE) if ENV_FILE.is_file() else {}
    def value(name):
        return saved.get(name) or os.getenv(name, "")
    key = value(PROVIDERS[provider]["key_env"])
    if provider == "dashscope":
        key = key or value("OPENAI_API_KEY")
    elif provider == "glm":
        key = key or value("GLM_API_KEY") or value("ZAI_API_KEY") or value("ZHIPUAI_API_KEY")
    return key.strip()


def public_ai_settings(provider=None):
    profile = profile_settings(provider)
    return {**profile, "label": PROVIDERS[profile["provider"]]["label"],
            "credential_configured": bool(provider_key(profile["provider"])),
            "suggested_models": PROVIDERS[profile["provider"]]["models"]}


def save_ai_profile(value: AISettings):
    with _lock:
        profile = value.model_dump()
        profile["base_url"] = value.base_url or profile_settings(value.provider)["base_url"]
        key = value.api_key.get_secret_value().strip() if value.api_key else ""
        if key:
            # dotenv rewrites atomically and preserves unrelated environment entries.
            ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
            set_key(str(ENV_FILE), PROVIDERS[value.provider]["key_env"], key)
            ENV_FILE.chmod(0o600)
            os.environ[PROVIDERS[value.provider]["key_env"]] = key
        BusinessRepository().write_settings({f"ai:{value.provider}": profile, "ai": profile})
    return public_ai_settings(value.provider)

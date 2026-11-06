"""Provider connection checks never save settings or start a research run."""
import asyncio
from time import perf_counter

from fastapi import APIRouter, HTTPException
from openai import APIConnectionError, APIStatusError, APITimeoutError

from .model import compatible_model
from .preferences import AISettings, profile_settings, provider_key, save_ai_profile

router = APIRouter(prefix="/research/settings/ai")


@router.put("")
def save_settings(value: AISettings):
    try:
        return save_ai_profile(value)
    except OSError:
        raise HTTPException(500, "Could not write the local configuration. Check file permissions.") from None


@router.post("/test")
async def test_connection(value: AISettings):
    start = perf_counter()
    key = value.api_key.get_secret_value().strip() if value.api_key else ""
    key = key or provider_key(value.provider)
    if not key:
        return {"ok": False, "code": "missing_key"}
    config = {**profile_settings(value.provider), **value.model_dump(exclude_none=True)}
    config["timeout"] = min(value.timeout, 20)
    try:
        async with asyncio.timeout(config["timeout"]):
            model = compatible_model(config, api_key=key, enable_thinking=False, max_retries=0,
                                     max_tokens=1024 if value.provider == "glm" else 256)
            result = await model.ainvoke([{"role": "user", "content": "你好，请用一句话回复。"}])
        reply = result.text.strip()
        if not reply:
            return {"ok": False, "code": "empty_reply"}
        return {"ok": True, "reply": reply[:300], "elapsed_ms": round((perf_counter() - start) * 1000)}
    except (TimeoutError, APITimeoutError):
        code = "timeout"
    except APIConnectionError:
        code = "connection"
    except APIStatusError as error:
        code = {401: "authentication", 403: "permission", 404: "model_not_found", 429: "rate_limit"}.get(
            error.status_code, "provider_error" if error.status_code >= 500 else "invalid_request")
    except Exception:
        # Provider exceptions can embed credentials or full response bodies.
        code = "unexpected"
    return {"ok": False, "code": code, "elapsed_ms": round((perf_counter() - start) * 1000)}

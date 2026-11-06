"""Build models from the active UI profile or initial environment configuration.

Saved Qwen/DeepSeek/GLM profiles take precedence over COPILOTKIT_AGENT_MODEL.
All use OpenAI-compatible Chat Completions with server-side credentials. The
legacy <provider>:<model> parser remains available for non-UI integrations.
"""

import os
import re

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from .preferences import profile_settings, provider_key, read_setting


class QwenChatOpenAI(ChatOpenAI):
    """Preserve compatible providers' reasoning deltas for native AG-UI.

    Pinned langchain-openai drops DashScope's nonstandard reasoning_content.
    This adapter forwards that actual field; it never generates a reasoning log.
    """
    def _convert_chunk_to_generation_chunk(self, chunk, default_chunk_class, base_generation_info):
        result = super()._convert_chunk_to_generation_chunk(chunk, default_chunk_class, base_generation_info)
        choices = chunk.get("choices", [])
        reasoning = (choices[0].get("delta") or {}).get("reasoning_content") if choices else None
        if result is not None and reasoning:
            result.message.additional_kwargs["reasoning_content"] = reasoning
        return result

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        payload = response if isinstance(response, dict) else response.model_dump()
        for generation, choice in zip(result.generations, payload.get("choices", [])):
            if reasoning := choice.get("message", {}).get("reasoning_content"):
                generation.message.additional_kwargs["reasoning_content"] = reasoning
        return result

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        messages = self._convert_input(input_).to_messages()
        for wire, message in zip(payload.get("messages", []), messages):
            if wire.get("role") == "assistant" and message.additional_kwargs.get("reasoning_content"):
                wire["reasoning_content"] = message.additional_kwargs["reasoning_content"]
        return payload

_PROVIDER_ALIASES = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google",
    "gemini": "google",
    "google-gemini": "google",
}
# Our provider ids -> LangChain's init_chat_model provider ids.
_LANGCHAIN_PROVIDERS = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google_genai",
}
_SPEC = re.compile(r"^([A-Za-z0-9-]+)[:/](.+)$")


def parse_agent_model(value: str) -> tuple[str, str]:
    """Split ``<provider>:<model>`` into (provider, model); the model id is kept unchanged."""
    match = _SPEC.match(value.strip())
    provider = match and _PROVIDER_ALIASES.get(match.group(1).lower())
    if not match or not provider:
        raise ValueError(
            f'COPILOTKIT_AGENT_MODEL="{value}" is not <provider>:<model> '
            "with provider openai, anthropic or google"
        )
    return provider, match.group(2)


def compatible_model(settings: dict, api_key=None, **options) -> BaseChatModel:
    provider = settings["provider"]
    thinking = options.pop("enable_thinking", None)
    options.update(temperature=settings["temperature"], timeout=settings["timeout"],
                   # Let a fresh app start so its Settings page can accept a key.
                   api_key=api_key or provider_key(provider) or "not-configured", base_url=settings["base_url"],
                   use_responses_api=False)
    if provider == "dashscope":
        options["extra_body"] = {"enable_thinking": thinking if thinking is not None else
                                 os.getenv("QWEN_ENABLE_THINKING", "true").lower() == "true"}
    elif provider == "glm" and settings["model"].lower().startswith("glm-5.3"):
        # GLM-5.3 rejects thinking=disabled; use its lowest supported effort.
        options["reasoning_effort"] = "low" if thinking is False else "high"
    else:
        enabled = thinking if thinking is not None else True
        options["extra_body"] = {"thinking": {"type": "enabled" if enabled else "disabled"}}
    return QwenChatOpenAI(model=settings["model"], **options)


def create_chat_model(default_spec: str, **openai_kwargs) -> BaseChatModel:
    """Build this site's chat model.

    Args:
        default_spec: This site's default, e.g. ``"openai:gpt-5.4"``.
        **openai_kwargs: Extra ChatOpenAI options, applied only for OpenAI.
    """
    settings = read_setting("ai")
    spec = f"openai:{settings['model']}" if settings else (os.getenv("COPILOTKIT_AGENT_MODEL") or "").strip() or default_spec
    provider, model = parse_agent_model(spec)
    if settings or (provider == "openai" and model.startswith(("qwen", "deepseek", "glm"))):
        return compatible_model(profile_settings(), **openai_kwargs)
    kwargs = dict(openai_kwargs) if provider == "openai" else {}
    if settings:
        kwargs.update(temperature=settings["temperature"], timeout=settings["timeout"])
    kwargs.pop("enable_thinking", None)
    return init_chat_model(
        model, model_provider=_LANGCHAIN_PROVIDERS[provider], **kwargs
    )

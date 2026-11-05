"""Build the agent's chat model from ``COPILOTKIT_AGENT_MODEL``.

``COPILOTKIT_AGENT_MODEL=<provider>:<model>`` (or ``<provider>/<model>``)
overrides EVERY model site in this agent. When it is unset, each site falls
back to its own default. Providers: ``openai``, ``anthropic``, ``google``
(``gemini`` and ``google-gemini`` are aliases of ``google``). An
OpenAI-compatible provider is ``openai:<its model id>`` plus
``OPENAI_BASE_URL``, which the OpenAI client reads itself.
"""

import os
import re

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from .preferences import read_setting


class QwenChatOpenAI(ChatOpenAI):
    """Preserve provider-supplied reasoning deltas for the native AG-UI renderer.

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


def create_chat_model(default_spec: str, **openai_kwargs) -> BaseChatModel:
    """Build this site's chat model.

    Args:
        default_spec: This site's default, e.g. ``"openai:gpt-5.4"``.
        **openai_kwargs: Extra ChatOpenAI options, applied only for OpenAI.
    """
    settings = read_setting("ai")
    spec = f"openai:{settings['model']}" if settings else (os.getenv("COPILOTKIT_AGENT_MODEL") or "").strip() or default_spec
    provider, model = parse_agent_model(spec)
    kwargs = dict(openai_kwargs) if provider == "openai" else {}
    if settings:
        kwargs.update(temperature=settings["temperature"], timeout=settings["timeout"])
    thinking_override = kwargs.pop("enable_thinking", None)
    if provider == "openai" and model.startswith("qwen"):
        kwargs.setdefault("temperature", 0)
        kwargs.setdefault("timeout", 100)
        # DashScope speaks Chat Completions. Keep credentials on the server and
        # disable thinking for responsive UI/tool calls with standard messages.
        kwargs.update(
            api_key=os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("DASHSCOPE_BASE_URL") or os.getenv("OPENAI_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            extra_body={"enable_thinking": thinking_override if thinking_override is not None else
                        os.getenv("QWEN_ENABLE_THINKING", "true").lower() == "true"},
            use_responses_api=False,
        )
        return QwenChatOpenAI(model=model, **kwargs)
    return init_chat_model(
        model, model_provider=_LANGCHAIN_PROVIDERS[provider], **kwargs
    )

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage, message_chunk_to_message
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field


def to_model_messages(messages):
    converted = []
    tool_names = {}
    for message in messages:
        if isinstance(message, AIMessage):
            content = [{"type": "text", "text": message.content}] if isinstance(message.content, str) and message.content else []
            for call in message.tool_calls:
                tool_names[call["id"]] = call["name"]
                content.append({"type": "tool-call", "toolCallId": call["id"], "toolName": call["name"], "input": call["args"]})
            if content:
                converted.append({"role": "assistant", "content": content})
        elif isinstance(message, ToolMessage):
            try:
                output = {"type": "json", "value": json.loads(message.content)}
            except (ValueError, TypeError):
                output = {"type": "text", "value": str(message.content)}
            converted.append({"role": "tool", "content": [{"type": "tool-result", "toolCallId": message.tool_call_id, "toolName": message.name or tool_names.get(message.tool_call_id, "unknown"), "output": output}]})
        else:
            role = "system" if isinstance(message, SystemMessage) else "user"
            converted.append({"role": role, "content": str(message.content)})
    return converted


class GatewayChatModel(BaseChatModel):
    tool_specs: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "vercel-ai-sdk-gateway-bridge"

    def bind_tools(self, tools, **kwargs):
        specs = []
        for value in tools:
            spec = convert_to_openai_tool(value)["function"]
            specs.append({"name": spec["name"], "description": spec.get("description", ""), "parameters": spec["parameters"]})
        return self.model_copy(update={"tool_specs": specs})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError("Use async invocation for the streaming Gateway model.")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        full = None
        async for chunk in self._astream(messages, stop, run_manager, **kwargs):
            full = chunk if full is None else full + chunk
        if full is None:
            raise RuntimeError("The model returned no content.")
        return ChatResult(generations=[ChatGeneration(message=message_chunk_to_message(full.message))])

    async def _astream(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> AsyncIterator[ChatGenerationChunk]:
        url = os.environ.get("FOLIO_FRONTEND_URL", "http://localhost:3000").rstrip("/")
        secret = os.environ.get("FOLIO_INTERNAL_SECRET")
        if not secret:
            raise RuntimeError("The internal model bridge credential is missing.")
        payload = {"messages": to_model_messages(messages), "tools": self.tool_specs}
        index = 0
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10)) as client:
            async with client.stream("POST", f"{url}/api/agent/model", json=payload, headers={"Authorization": f"Bearer {secret}"}) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    if event["type"] == "error":
                        raise RuntimeError(event["message"])
                    if event["type"] == "text":
                        yield ChatGenerationChunk(message=AIMessageChunk(content=event["text"]))
                    if event["type"] == "tool_call":
                        yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=[{
                            "id": event["id"], "name": event["name"], "args": json.dumps(event["args"], ensure_ascii=False), "index": index,
                        }]))
                        index += 1

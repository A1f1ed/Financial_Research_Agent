"""Live integration checks. Requires npm run dev; calls the configured model.

Run from the app root: agent/.venv/Scripts/python.exe scripts/smoke.py
Only checks local endpoints; it never reads or prints credentials.
"""

import asyncio
import json
from uuid import uuid4

import httpx


def payload(prompt, tools=None):
    return {
        "threadId": str(uuid4()), "runId": str(uuid4()),
        "state": {"todos": []},
        "messages": [{"id": str(uuid4()), "role": "user", "content": prompt}],
        "tools": tools or [], "context": [], "forwardedProps": {},
    }


async def stream(client, data):
    events = []
    async with client.stream("POST", "http://127.0.0.1:8123/", json=data,
                             headers={"Accept": "text/event-stream"}) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    errors = [e for e in events if e["type"] == "RUN_ERROR"]
    assert not errors, f"Agent run failed: {errors}"
    assert any(e["type"] == "RUN_FINISHED" for e in events), "Stream did not finish"
    return events


async def main():
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        for url in ["http://127.0.0.1:8123/health", "http://localhost:3000/",
                    "http://localhost:3000/api/copilotkit/info",
                    "http://localhost:3000/api/copilotkit/threads?agentId=default"]:
            result = await client.get(url)
            result.raise_for_status()
            print(f"PASS {url}", flush=True)

        events = await stream(client, payload("Reply with exactly: Qwen connection OK"))
        assert any(e["type"] == "TEXT_MESSAGE_CONTENT" and e.get("delta") for e in events)
        print("PASS Qwen chat over AG-UI SSE", flush=True)

        for name, prompt, properties, required in [
            ("toggleTheme", "Call toggleTheme exactly once to change my theme.", {}, []),
            ("scheduleTime", "Call scheduleTime to let me choose a 30 minute meeting. Wait for my choice.",
             {"reasonForScheduling": {"type": "string"}, "meetingDuration": {"type": "number"}},
             ["reasonForScheduling", "meetingDuration"]),
            ("pieChart", "Call pieChart with two sample categories A=60 and B=40. Label it Sample data.",
             {"title": {"type": "string"}, "description": {"type": "string"},
              "data": {"type": "array", "items": {"type": "object", "properties": {
                  "label": {"type": "string"}, "value": {"type": "number"}}, "required": ["label", "value"]}}},
             ["title", "description", "data"]),
        ]:
            tool_input = payload(prompt, [{"name": name, "description": prompt,
                "parameters": {"type": "object", "properties": properties, "required": required}}])
            events = await stream(client, tool_input)
            assert any(e["type"] == "TOOL_CALL_START" and e.get("toolCallName") == name for e in events), name
            print(f"PASS frontend tool dispatch: {name}", flush=True)
            if name == "scheduleTime":
                call = next(e for e in events if e["type"] == "TOOL_CALL_START" and e.get("toolCallName") == name)
                call_id = call["toolCallId"]
                arguments = "".join(e.get("delta", "") for e in events
                                    if e["type"] == "TOOL_CALL_ARGS" and e.get("toolCallId") == call_id)
                tool_input["messages"].extend([
                    {"id": str(uuid4()), "role": "assistant", "toolCalls": [{"id": call_id,
                     "type": "function", "function": {"name": name, "arguments": arguments}}]},
                    {"id": str(uuid4()), "role": "tool", "toolCallId": call_id,
                     "content": "The user declined. Do not schedule anything or offer times again. Acknowledge the decision."},
                ])
                tool_input["runId"] = str(uuid4())
                resumed = await stream(client, tool_input)
                assert any(e["type"] == "TEXT_MESSAGE_CONTENT" for e in resumed)
                assert not any(e["type"] == "TOOL_CALL_START" and e.get("toolCallName") == name for e in resumed)
                print("PASS human-input decline and agent continuation", flush=True)

        events = await stream(client, payload("Use manage_todos to add exactly one pending task titled Verify shared state, with description Test and emoji ✅. Do not call any other tool."))
        assert any(e["type"] == "STATE_SNAPSHOT" and e.get("snapshot", {}).get("todos")
                   or e["type"] == "STATE_DELTA" and any("todos" in d.get("path", "") for d in e.get("delta", [])) for e in events)
        print("PASS shared todo state streaming", flush=True)

        data = payload("Reply with exactly: Durable Qwen smoke test OK")
        response = await client.post("http://localhost:3000/api/copilotkit/agent/default/run", json=data)
        response.raise_for_status()
        thread = response.json()["threadId"]
        for _ in range(45):
            response = await client.get(f"http://localhost:3000/api/copilotkit/threads/{thread}/events?agentId=default")
            response.raise_for_status()
            body = response.json()
            encoded = json.dumps(body)
            assert '"RUN_ERROR"' not in encoded, "Durable runtime run failed"
            if '"RUN_FINISHED"' in encoded:
                print(f"PASS Intelligence persisted completed AG-UI stream: {thread}", flush=True)
                return
            await asyncio.sleep(2)
        raise AssertionError("Durable run did not finish within 90 seconds")


if __name__ == "__main__":
    asyncio.run(main())

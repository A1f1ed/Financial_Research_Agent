"""Opt-in live metadata-only trace plus greeting; checks remote ingestion."""
import argparse
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from src.infrastructure import telemetry
from src.infrastructure.config import ROOT
from src.infrastructure.loops import loop_factory
from src.model import create_chat_model


async def verify():
    status, config = telemetry.configuration()
    if status != "configured":
        raise RuntimeError("Langfuse credentials/base URL are not configured")
    base, public, secret = config
    run_id = str(uuid4())
    started = datetime.now(timezone.utc)
    with telemetry.operation("connection.verify", kind="agent", run_id=run_id) as span:
        trace_id = format(span.get_span_context().trace_id, "032x")
        model = create_chat_model("openai:qwen3.8-flash", enable_thinking=False, max_retries=0, max_tokens=1024)
        result = await model.ainvoke([{"role": "user", "content": "你好，请用一句话回复。"}])
        if not result.text.strip():
            raise ValueError("Greeting returned no final text")
    flushed = telemetry.get_provider().force_flush(timeout_millis=10000)
    headers = {"Authorization": "Basic " + base64.b64encode((public + ":" + secret).encode()).decode()}
    query = urlencode({"traceId": trace_id, "fields": "core,basic,usage,io,metadata", "limit": 10,
        "fromStartTime": (started - timedelta(minutes=1)).isoformat(), "toStartTime": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()})
    observations = []
    for attempt in range(12):
        with urlopen(Request(base + "/api/public/v2/observations?" + query, headers=headers), timeout=15) as response:
            observations = json.load(response).get("data", [])
        if len(observations) >= 2:
            break
        await asyncio.sleep(2)
    # The query is bounded to this newly created metadata-only trace. Do not
    # print raw response objects or any existing project observations.
    assert len(observations) >= 2, "Remote trace ingestion not observed"
    assert all(row.get("traceId") == trace_id for row in observations)
    assert {row.get("type", "").lower() for row in observations} >= {"agent", "generation"}
    assert all(not row.get("input") and not row.get("output") for row in observations)
    evidence = {"run_id": run_id, "trace_id": trace_id, "export_flushed": flushed,
                "observations": len(observations), "remote_ingestion_verified": True,
                "greeting_succeeded": True, "content_exported": False}
    directory = ROOT / "local-data/validation"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "langfuse-connection.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", required=True)
    parser.parse_args()
    try:
        with asyncio.Runner(loop_factory=loop_factory) as runner:
            runner.run(verify())
    finally:
        telemetry.shutdown()

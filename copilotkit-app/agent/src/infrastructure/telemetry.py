"""Owned OpenTelemetry provider; export only explicitly selected metadata.

No automatic HTTP/LLM instrumentation: prompts, outputs, retrieved documents,
reasoning, exception messages and authentication headers never enter these spans.
This provider is separate from CopilotKit's native tracing configuration.
"""
import base64
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit

from dotenv import dotenv_values
from langchain_core.callbacks import BaseCallbackHandler
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

_lock = RLock()
_provider = None
_provider_pid = None
_run_id = ContextVar("telemetry_run_id", default=None)
_trace_id = ContextVar("telemetry_trace_id", default=None)
ALLOWED = {"run_id", "stage", "provider", "model", "status", "error_type", "source_count", "case_id", "attempt_id", "index_version"}


def configuration():
    values = {**dotenv_values(Path(__file__).resolve().parents[3] / ".env"), **os.environ}
    base = (values.get("LANGFUSE_BASE_URL") or values.get("LANGFUSE_HOST") or "").rstrip("/")
    public, secret = values.get("LANGFUSE_PUBLIC_KEY", ""), values.get("LANGFUSE_SECRET_KEY", "")
    if str(values.get("APERTURE_TRACING_ENABLED", "true")).lower() != "true":
        return "disabled", None
    if not any((base, public, secret)):
        return "not_configured", None
    if not all((base, public, secret)):
        return "incomplete", None
    try:
        url = urlsplit(base)
        _ = url.port
    except ValueError:
        return "invalid_configuration", None
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}:
        return "invalid_configuration", None
    return "configured", (base, public, secret)


def get_provider():
    global _provider, _provider_pid
    with _lock:
        if _provider_pid != os.getpid():
            # Never reuse a parent's exporter thread/queue in a forked worker.
            _provider, _provider_pid = None, os.getpid()
        if _provider is None:
            _, credentials = configuration()
            if credentials is None:
                return None
            base, public, secret = credentials
            auth = base64.b64encode((public + ":" + secret).encode()).decode()
            exporter = OTLPSpanExporter(endpoint=base + "/api/public/otel/v1/traces", timeout=5,
                headers={"Authorization": "Basic " + auth, "x-langfuse-ingestion-version": "4"})
            _provider = TracerProvider(resource=Resource({"service.name": "aperture-agent", "deployment.environment.name": "local"}))
            _provider.add_span_processor(BatchSpanProcessor(exporter, max_queue_size=512, max_export_batch_size=64, schedule_delay_millis=1000))
        return _provider


def attributes(kind, metadata):
    safe = {key: value for key, value in metadata.items() if key in ALLOWED and isinstance(value, (str, int, float, bool))}
    if _run_id.get():
        safe["run_id"] = _run_id.get()
    result = {"langfuse.observation.type": kind, "langfuse.observation.metadata": json.dumps(safe)}
    if safe.get("run_id"):
        result["langfuse.session.id"] = safe["run_id"]
    if safe.get("model"):
        result["langfuse.observation.model.name"] = safe["model"]
    return result


@contextmanager
def operation(name, *, kind="span", **metadata):
    provider = get_provider()
    token = _run_id.set(metadata["run_id"]) if metadata.get("run_id") else None
    try:
        if provider is None:
            yield None
            return
        with provider.get_tracer("aperture").start_as_current_span(name, attributes=attributes(kind, metadata),
                record_exception=False, set_status_on_exception=False) as span:
            trace_token = _trace_id.set(format(span.get_span_context().trace_id, "032x"))
            try:
                yield span
            except BaseException as error:
                span.set_attribute("error.type", type(error).__name__)
                span.set_status(Status(StatusCode.ERROR, type(error).__name__))
                raise
            finally:
                _trace_id.reset(trace_token)
    finally:
        if token is not None:
            _run_id.reset(token)


def shutdown():
    global _provider
    with _lock:
        if _provider is not None and _provider_pid == os.getpid():
            _provider.shutdown()
        _provider = None


def trace_details():
    identifier = _trace_id.get()
    return {"trace_id": identifier, "backend": "langfuse", "export": "async_metadata_only"} if identifier else None


class ModelObserver(BaseCallbackHandler):
    run_inline = True

    def __init__(self, model, provider):
        self.model, self.provider = model, provider
        self.spans = {}
        self.lock = RLock()

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        provider = get_provider()
        if provider is None:
            return
        span = provider.get_tracer("aperture").start_span("model.generate", attributes=attributes("generation", {
            "model": self.model, "provider": self.provider}))
        with self.lock:
            self.spans[run_id] = span

    def on_llm_end(self, response, *, run_id, **kwargs):
        with self.lock:
            span = self.spans.pop(run_id, None)
        if span is None:
            return
        usage = (response.llm_output or {}).get("token_usage", {})
        details = {key: usage[source] for key, source in (("input", "prompt_tokens"), ("output", "completion_tokens"))
                   if isinstance(usage.get(source), int) and usage[source] >= 0}
        if not details:
            for batch in response.generations:
                for generation in batch:
                    data = getattr(getattr(generation, "message", None), "usage_metadata", None) or {}
                    details = {key: data[source] for key, source in (("input", "input_tokens"), ("output", "output_tokens"))
                               if isinstance(data.get(source), int) and data[source] >= 0}
                    if details:
                        break
        if details:
            span.set_attribute("langfuse.observation.usage_details", json.dumps(details))
        span.end()

    def on_llm_error(self, error, *, run_id, **kwargs):
        with self.lock:
            span = self.spans.pop(run_id, None)
        if span is not None:
            span.set_attribute("error.type", type(error).__name__)
            span.set_status(Status(StatusCode.ERROR, type(error).__name__))
            span.end()

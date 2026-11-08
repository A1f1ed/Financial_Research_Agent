"""Privacy and correlation tests use an in-memory exporter, never user credentials."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from src.infrastructure import telemetry


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.addCleanup(self.provider.shutdown)
        self.enterContext(patch.object(telemetry, "get_provider", return_value=self.provider))

    def test_parent_usage_and_content_privacy(self):
        callback = telemetry.ModelObserver("fixture-model", "fixture-provider")
        model_run = uuid4()
        with telemetry.operation("research.run", kind="agent", run_id="fixture-run", prompt="private-input", api_key="private-key") as parent:
            self.assertEqual(telemetry.trace_details()["trace_id"], format(parent.get_span_context().trace_id, "032x"))
            callback.on_chat_model_start({"api_key": "private-key"}, [["private-input"]], run_id=model_run)
            callback.on_llm_end(SimpleNamespace(llm_output={"token_usage": {"prompt_tokens": 12, "completion_tokens": 7}},
                generations=[[SimpleNamespace(message=SimpleNamespace(content="private-output", additional_kwargs={"reasoning_content": "private-reasoning"}))]]), run_id=model_run)
        self.assertIsNone(telemetry.trace_details())
        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 2)
        generation = spans[0]
        self.assertEqual(generation.context.trace_id, parent.get_span_context().trace_id)
        self.assertEqual(generation.parent.span_id, parent.get_span_context().span_id)
        self.assertEqual(json.loads(generation.attributes["langfuse.observation.usage_details"]), {"input": 12, "output": 7})
        for span in spans:
            self.assertEqual(span.attributes["langfuse.session.id"], "fixture-run")
            self.assertNotIn("private-", str(span.attributes))
            self.assertEqual(len(span.events), 0)

    def test_error_records_type_without_exception_or_reasoning_text(self):
        callback = telemetry.ModelObserver("fixture-model", "fixture-provider")
        key = uuid4()
        with self.assertRaises(RuntimeError):
            with telemetry.operation("failed.operation"):
                callback.on_chat_model_start({}, [["private-input"]], run_id=key)
                error = RuntimeError("private-key and private-document")
                callback.on_llm_error(error, run_id=key)
                raise error
        for span in self.exporter.get_finished_spans():
            self.assertEqual(span.status.description, "RuntimeError")
            self.assertNotIn("private-", str(span.attributes))
            self.assertEqual(len(span.events), 0)
        self.assertEqual(callback.spans, {})

    def test_missing_backend_does_not_break_research(self):
        with patch.object(telemetry, "get_provider", return_value=None):
            with telemetry.operation("research.run", run_id="fixture") as span:
                self.assertIsNone(span)
            callback = telemetry.ModelObserver("fixture-model", "fixture-provider")
            key = uuid4()
            callback.on_chat_model_start({}, [], run_id=key)
            callback.on_llm_error(RuntimeError("private"), run_id=key)
            self.assertEqual(callback.spans, {})


if __name__ == "__main__":
    unittest.main()

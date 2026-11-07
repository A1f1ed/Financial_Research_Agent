"""Context-local execution fence propagated into research/report tools."""
from contextlib import contextmanager
from contextvars import ContextVar

current_execution: ContextVar[tuple[str, str] | None] = ContextVar("research_execution", default=None)


@contextmanager
def execution_context(job_id, lease_token):
    token = current_execution.set((job_id, lease_token))
    try:
        yield
    finally:
        current_execution.reset(token)

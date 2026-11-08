"""Async research execution with database leases and cooperative cancellation."""
import asyncio
from uuid import uuid4

from src.persistence.execution import execution_context
from src.persistence.jobs import JobRepository, StateConflict
from src.research_models import ResearchConfig
from src.infrastructure.telemetry import operation


class ExecutionBusy(RuntimeError):
    def __init__(self, retry_after):
        super().__init__("Another execution holds the lease")
        self.retry_after = retry_after


async def run_job(job_id, raw_config=None):
    repository = JobRepository()
    token = str(uuid4())
    claimed = repository.claim(job_id, token)
    if claimed["state"] == "finished":
        return {"status": claimed["status"]}
    if claimed["state"] == "leased":
        raise ExecutionBusy(min(30, claimed["retry_after"]))

    async def execute():
        payload = claimed["config"]
        if payload.get("_operation") == "knowledge.graph.extract":
            from src.graphs.extraction import execute_extraction
            with operation("knowledge.graph.extract", kind="chain", run_id=job_id):
                return await execute_extraction(payload, job_id, token)
        if payload.get("_operation") == "knowledge.graph.sync":
            from src.graphs.projection import execute_projection
            with operation("knowledge.graph.sync", kind="chain", run_id=job_id):
                return await execute_projection(payload, job_id, token)
        if payload.get("_operation") == "knowledge.index":
            from src.knowledge.indexing import execute_index
            with operation("knowledge.index", kind="chain", run_id=job_id):
                return await execute_index(payload, job_id, token)
        if payload.get("_operation", "").startswith("document."):
            from src.documents.processing import execute_document
            with operation("document.run", kind="chain", run_id=job_id):
                return await execute_document(payload, job_id, token)
        from src.research_workflow import execute_research
        from src.scheduled_briefs import BriefOptions, execute_brief
        config = ResearchConfig.model_validate(payload)
        if config.knowledge_collection_ids and not payload.get("_knowledge_snapshot"):
            raise StateConflict("Research document versions were not pinned at submission")
        with execution_context(job_id, token), operation("research.run", kind="agent", run_id=job_id):
            if payload.get("_brief"):
                return await execute_brief(config, BriefOptions.model_validate(payload["_brief"]), job_id)
            return await execute_research(config, report_id=job_id, knowledge_snapshot=payload.get("_knowledge_snapshot"))

    async def heartbeat():
        while True:
            await asyncio.sleep(15)
            if not repository.heartbeat(job_id, token):
                raise StateConflict("Execution cancelled or lease lost")

    execution = asyncio.create_task(execute())
    monitor = asyncio.create_task(heartbeat())
    try:
        done, _ = await asyncio.wait([execution, monitor], return_when=asyncio.FIRST_COMPLETED)
        if monitor in done:
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
            monitor.result()
        report = await execution
        if not report.get("_finished") and not repository.finish(job_id, token, report["status"]):
            raise StateConflict("Late completion rejected")
        return {"status": report["status"]}
    except StateConflict:
        if repository.task_detail(job_id)["status"] == "cancelled":
            return {"status": "cancelled"}
        raise
    except asyncio.CancelledError:
        # Worker loss must leave recoverable lease state; it is not a user cancel.
        execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)
        raise
    except Exception as error:
        from sqlalchemy.exc import OperationalError
        if isinstance(error, OperationalError):
            raise  # Durable broker retry, not a fabricated financial failure result.
        from src.documents.parser import InvalidDocument
        from src.documents.network import SourceRejected
        document_job = claimed["config"].get("_operation", "").startswith("document.")
        knowledge_job = claimed["config"].get("_operation", "").startswith("knowledge.")
        extraction_message=None
        if claimed["config"].get("_operation") == "knowledge.graph.extract":
            from src.graphs.extraction import ExtractionStopped, stopped_result
            stopped_result(claimed["config"]["extraction_id"],job_id,token)
            if isinstance(error,ExtractionStopped):extraction_message=str(error)
        message = str(error) if document_job and isinstance(error, (InvalidDocument, SourceRejected)) else (
            "Document download timed out; retry later or upload the original file" if document_job and isinstance(error, TimeoutError)
            else f"{'Knowledge operation' if knowledge_job else 'Document processing' if document_job else 'Research'} failed ({type(error).__name__})")
        repository.finish(job_id, token, "failed", error=extraction_message or message)
        return {"status": "failed"}
    finally:
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)

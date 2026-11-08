"""Read-only, frozen-answer-safe tools; paid starts require frontend HITL."""
from langchain.tools import tool
from uuid import UUID
from .repository import EvaluationRepository


@tool
async def list_evaluation_records(dataset_id:str|None=None):
    """List real evaluation datasets/published version IDs and recent runs. No frozen cases or answers are exposed. Start an explicitly requested run with frontend startEvaluationRun for human review."""
    repo=EvaluationRepository()
    if dataset_id:
        UUID(dataset_id); data=repo.dataset(dataset_id);data.pop("cases",None)
        return {"dataset":data,"runs":repo.runs(dataset_id)}
    return {"datasets":repo.datasets(),"runs":repo.runs()}


@tool
async def read_evaluation_run(run_id:str):
    """Read actual progress, aggregate metrics and attempt IDs, without generated or frozen answers. No scores are invented; incomplete results are labeled."""
    UUID(run_id);data=EvaluationRepository().detail(run_id)
    data["attempts"]=[{k:a[k] for k in ("id","case_id","repetition","status","elapsed_ms","error_type") if k in a} for a in data["attempts"]]
    return data


@tool
async def read_evaluation_failure(run_id:str,attempt_id:str):
    """Inspect a development failure; frozen acceptance outputs, expected values and check details are withheld to prevent tuning leakage. Use Evaluation center for explicit human inspection."""
    UUID(run_id);UUID(attempt_id)
    return EvaluationRepository().attempt(run_id,attempt_id,agent=True)


@tool
async def compare_evaluation_runs(left_run_id:str,right_run_id:str):
    """Compare two real evaluation runs, configurations and per-case status/latency. Configuration differences limit direct comparison. No frozen answers are exposed."""
    UUID(left_run_id);UUID(right_run_id)
    return EvaluationRepository().compare(left_run_id,right_run_id,agent=True)


evaluation_tools=[list_evaluation_records,read_evaluation_run,read_evaluation_failure,compare_evaluation_runs]

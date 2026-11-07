import os
import asyncio
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the demo project root (one level up from agent/) BEFORE
# importing src.agent — that import constructs the chat model at module load,
# which needs COPILOTKIT_AGENT_MODEL and the provider key in the environment already.
_demo_root = Path(__file__).parent.parent
for env_path in (_demo_root / ".env", Path(".env")):
    if env_path.is_file():
        load_dotenv(env_path)
        break
else:
    load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from urllib.parse import quote
import uvicorn
from src.agent import build_graph
from src.persistence.checkpoints import checkpoint_saver
from src.persistence.database import dispose_engines
from src.learning import skills
from src.research_store import list_reports, get_report, archive_report
from src.research_data import cli_path
from src.research_exports import markdown, pdf
from src.workbench import router as workbench_router, initialize_queue
from src.followups import router as followups_router
from src.market_review import router as market_review_router
from src.review_checks import router as review_checks_router
from src.review_candidates import initialize_candidates, router as review_candidates_router
from src.a_share_events import router as a_share_events_router
from src.market_sentiment import router as market_sentiment_router
from src.report_comparison import router as report_comparison_router
from src.preferences import DataSettings, public_ai_settings, read_setting, write_setting
from src.preferences import PROVIDERS
from src.ai_settings import router as ai_settings_router
import json
from copilotkit import LangGraphAGUIAgent
from ag_ui_langgraph import add_langgraph_fastapi_endpoint

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with checkpoint_saver() as checkpoint:
        try:
            if skills is not None:
                await skills.initialize()
            graph = build_graph(checkpoint)
            add_langgraph_fastapi_endpoint(app=app, agent=LangGraphAGUIAgent(
                name="finance_research", description="有日期边界和证据引用的多分析师金融研究 Agent。", graph=graph), path="/")
            initialize_queue()
            initialize_candidates()
            try:
                yield
            finally:
                dispose_engines()
                from src.infrastructure.telemetry import shutdown
                await asyncio.to_thread(shutdown)
        finally:
            if skills is not None:
                await skills.aclose()


app = FastAPI(title="CopilotKit LangGraph Agent", lifespan=lifespan)
from src.documents.api import router as documents_router, UploadBodyLimit
from src.knowledge.api import router as knowledge_router
from src.graphs.api import router as graphs_router
app.add_middleware(UploadBodyLimit)
app.include_router(documents_router)
app.include_router(knowledge_router)
app.include_router(graphs_router)
app.include_router(workbench_router)
app.include_router(followups_router)
app.include_router(market_review_router)
app.include_router(review_checks_router)
app.include_router(review_candidates_router)
app.include_router(a_share_events_router)
app.include_router(market_sentiment_router)
app.include_router(report_comparison_router)
app.include_router(ai_settings_router)


@app.get("/research/settings")
def settings():
    return {"ai": public_ai_settings(), "profiles": {key: public_ai_settings(key) for key in PROVIDERS},
            "data": read_setting("data", {"cache_minutes": 15}),
            "cli_available": bool(cli_path())}


@app.put("/research/settings/data")
def save_data_settings(value: DataSettings):
    write_setting("data", value)
    return value


@app.get("/health")
def health():
    from src.infrastructure.telemetry import configuration
    from sqlalchemy import text
    from src.persistence.database import engine
    with engine().connect() as connection:
        connection.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "learning": "ready" if skills is not None and skills.status.initialized else "disabled",
        "langfuse": configuration()[0],
    }


@app.get("/research/status")
async def research_status():
    return {"provider": "Longbridge", "cli_available": bool(cli_path()),
            "model": public_ai_settings()["model"],
            "learning": bool(skills), "storage": "postgresql", "mode": "single-user-local",
            "historical_policy": "date-filtered; missing or unverifiable publication dates are excluded"}


@app.get("/research/reports")
async def reports():
    return {"reports": list_reports()}


@app.get("/research/reports/{report_id}")
async def report_detail(report_id: str):
    report = get_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    return report


@app.delete("/research/reports/{report_id}")
async def report_archive(report_id: str):
    archive_report(report_id)
    return {"archived": True}


@app.get("/research/reports/{report_id}/export/{format}")
async def export_report(report_id: str, format: str):
    report = get_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    if format not in ("md", "json", "pdf"):
        raise HTTPException(400, "Unsupported export format")
    data = pdf(report) if format == "pdf" else json.dumps(report, ensure_ascii=False, indent=2) if format == "json" else markdown(report)
    filename = quote(f"{report['symbol']}_研究报告_{report['as_of']}.{format}")
    return Response(content=data, media_type={"md": "text/markdown", "json": "application/json", "pdf": "application/pdf"}[format],
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


def main():
    """Run the uvicorn server."""
    port = int(os.getenv("PORT", "8123"))
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=port,
        loop="src.infrastructure.loops:loop_factory",
        # Windows reload signals can terminate sibling Next.js processes.
        reload=os.getenv("AGENT_RELOAD", "false" if os.name == "nt" else "true").lower() == "true",
    )


warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
if __name__ == "__main__":
    main()

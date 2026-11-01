from contextlib import asynccontextmanager
import hmac
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from ag_ui_langgraph import LangGraphAgent, add_langgraph_fastapi_endpoint

load_dotenv(Path(__file__).resolve().parents[1] / ".env.local")
from backend.agent import graph
from backend.financial_data import financial_data


@asynccontextmanager
async def lifespan(app):
    async with financial_data.connect():
        yield


app = FastAPI(title="Folio Python Research Agent", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def protect_agent(request: Request, call_next):
    if request.url.path != "/health":
        secret = os.environ.get("FOLIO_INTERNAL_SECRET", "")
        if len(secret) < 32 or not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {secret}"):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        if int(request.headers.get("content-length", "0")) > 512000:
            return JSONResponse({"error": "Request too large"}, status_code=413)
    return await call_next(request)


@app.get("/health")
async def health():
    return {"agent": "folio_research", "framework": "langgraph-python", "protocol": "ag-ui", "modelBridgeConfigured": bool(os.environ.get("FOLIO_INTERNAL_SECRET")), "financialData": financial_data.status == "connected", "financialTools": [tool.name for tool in financial_data.tools]}


add_langgraph_fastapi_endpoint(app, LangGraphAgent(name="folio_research", description="Folio Python 金融研究助手", graph=graph, config={"recursion_limit": 12}, emit_raw_events=False), path="/agent")

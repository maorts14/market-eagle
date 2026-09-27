from contextlib import asynccontextmanager
from datetime import date, timedelta
import json
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from temporalio.client import Client
from .config import settings
from .database import SessionLocal, init_database
from .lakehouse import trino_query
from .lakehouse import ensure_lakehouse
from .models import AgentStep, AnalysisRun, Instrument, PipelineRun, ResearchSession
from .universe import SECTOR_ETFS
from .workflows import DailyCollectionWorkflow, HistoricalBackfillWorkflow, ResearchAgentWorkflow


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database()
    ensure_lakehouse()
    yield


app = FastAPI(title="Market Eagle API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class ResearchRequest(BaseModel):
    question: str = Field(min_length=4, max_length=1000)


async def temporal_client() -> Client:
    return await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "market-eagle-api", "agent_configured": bool(settings.openrouter_api_key), "agent_model": settings.openrouter_model}


@app.get("/api/overview")
def overview() -> dict:
    with SessionLocal() as session:
        latest_run = session.scalars(select(AnalysisRun).where(AnalysisRun.status == "completed").order_by(desc(AnalysisRun.created_at)).limit(1)).first()
        runs = session.scalars(select(PipelineRun).order_by(desc(PipelineRun.started_at)).limit(5)).all()
    metrics = trino_query("SELECT max(trading_date) AS as_of_date, count(*) AS bar_count FROM silver.daily_bars")
    latest_date, bar_count = metrics[0]["as_of_date"], metrics[0]["bar_count"]
    relationship_count = 0 if not latest_run else trino_query(f"SELECT count(*) AS total FROM gold.sector_relationships WHERE analysis_run_id = '{latest_run.id}'")[0]["total"]
    brief_rows = trino_query("SELECT headline, body, evidence, as_of_date FROM gold.daily_briefs ORDER BY created_at DESC LIMIT 1")
    brief = None if not brief_rows else {**brief_rows[0], "evidence": json.loads(brief_rows[0]["evidence"]), "as_of_date": str(brief_rows[0]["as_of_date"])}
    return {"as_of_date": str(latest_date) if latest_date else None, "bar_count": bar_count, "relationship_count": relationship_count,
            "latest_brief": brief, "runs": [{"id": run.id, "type": run.workflow_type, "status": run.status, "started_at": run.started_at.isoformat()} for run in runs]}


@app.get("/api/sectors")
def sectors() -> list[dict]:
    symbols = ", ".join(f"'{symbol}'" for symbol, _, _ in SECTOR_ETFS)
    return _performance_rows(symbols)


@app.get("/api/stocks")
def stocks() -> list[dict]:
    with SessionLocal() as session:
        instruments = {item.symbol: item for item in session.scalars(select(Instrument).where(Instrument.instrument_type == "stock")).all()}
    if not instruments:
        return []
    symbols = ", ".join(f"'{symbol}'" for symbol in instruments)
    return [{**row, "name": instruments[row["symbol"]].name, "sector": instruments[row["symbol"]].sector} for row in _performance_rows(symbols)]


def _performance_rows(symbols: str) -> list[dict]:
    rows = trino_query(f"""
        WITH ranked AS (
          SELECT symbol, trading_date, close, row_number() OVER (PARTITION BY symbol ORDER BY trading_date DESC) AS position
          FROM silver.daily_bars WHERE symbol IN ({symbols})
        )
        SELECT latest.symbol, latest.trading_date AS as_of, latest.close,
               round((latest.close / prior.close - 1) * 100, 2) AS return_5d
        FROM ranked latest JOIN ranked prior ON latest.symbol = prior.symbol
        WHERE latest.position = 1 AND prior.position = 6 ORDER BY return_5d DESC
    """)
    return [{**row, "as_of": str(row["as_of"]), "close": float(row["close"]), "return_5d": float(row["return_5d"])} for row in rows]


@app.get("/api/relationships")
def relationships() -> list[dict]:
    with SessionLocal() as session:
        run = session.scalars(select(AnalysisRun).where(AnalysisRun.status == "completed").order_by(desc(AnalysisRun.created_at)).limit(1)).first()
        if not run:
            return []
    edges = trino_query(f"SELECT leader_symbol, follower_symbol, lag_days, correlation, sample_size, window_start, window_end FROM gold.sector_relationships WHERE analysis_run_id = '{run.id}' ORDER BY correlation DESC LIMIT 30")
    return [{"leader": edge["leader_symbol"], "follower": edge["follower_symbol"], "lag_days": edge["lag_days"], "correlation": edge["correlation"],
             "sample_size": edge["sample_size"], "window_start": str(edge["window_start"]), "window_end": str(edge["window_end"])} for edge in edges]


@app.get("/api/event-links")
def event_links() -> list[dict]:
    with SessionLocal() as session:
        run = session.scalars(select(AnalysisRun).where(AnalysisRun.status == "completed").order_by(desc(AnalysisRun.created_at)).limit(1)).first()
        if not run:
            return []
    rows = trino_query(f"SELECT leader_symbol, follower_symbol, title, url, domain, seen_at FROM gold.event_market_links WHERE analysis_run_id = '{run.id}' ORDER BY seen_at DESC LIMIT 8")
    return [{"leader": row["leader_symbol"], "follower": row["follower_symbol"], "title": row["title"], "url": row["url"], "domain": row["domain"], "seen_at": row["seen_at"].isoformat()} for row in rows]


@app.post("/api/pipelines/backfill", status_code=202)
async def start_backfill() -> dict:
    run_id = f"backfill-{uuid4().hex[:12]}"
    client = await temporal_client()
    request = {"run_id": run_id, "start": (date.today() - timedelta(days=365)).isoformat(), "end": date.today().isoformat()}
    await client.start_workflow(HistoricalBackfillWorkflow.run, request, id=run_id, task_queue=settings.task_queue)
    return {"workflow_id": run_id, "status": "started"}


@app.post("/api/pipelines/daily", status_code=202)
async def start_daily_collection() -> dict:
    run_id = f"daily-{uuid4().hex[:12]}"
    client = await temporal_client()
    request = {"run_id": run_id, "start": (date.today() - timedelta(days=7)).isoformat(), "end": date.today().isoformat()}
    await client.start_workflow(DailyCollectionWorkflow.run, request, id=run_id, task_queue=settings.task_queue)
    return {"workflow_id": run_id, "status": "started"}


@app.post("/api/research", status_code=202)
async def research(request: ResearchRequest) -> dict:
    session_id = f"research-{uuid4().hex[:12]}"
    client = await temporal_client()
    await client.start_workflow(ResearchAgentWorkflow.run, {"session_id": session_id, "question": request.question}, id=session_id, task_queue=settings.task_queue)
    return {"session_id": session_id, "status": "started"}


@app.get("/api/research/{session_id}")
def research_status(session_id: str) -> dict:
    with SessionLocal() as session:
        result = session.get(ResearchSession, session_id)
        if not result:
            raise HTTPException(status_code=404, detail="Research session not found")
        steps = session.scalars(select(AgentStep).where(AgentStep.session_id == session_id).order_by(AgentStep.step_index, AgentStep.id)).all()
    decision_steps = [step for step in steps if step.kind == "decision"]
    final_step = next((step for step in reversed(steps) if step.kind == "final"), None)
    metrics = {
        "model_calls": len(decision_steps), "tool_calls": len([step for step in steps if step.kind == "tool"]),
        "guard_rejections": len([step for step in decision_steps if step.status == "guarded"]),
        "model_latency_ms": sum(step.latency_ms for step in decision_steps),
        "prompt_tokens": sum(step.prompt_tokens for step in decision_steps),
        "completion_tokens": sum(step.completion_tokens for step in decision_steps),
        "quality": final_step.payload if final_step else None,
    }
    return {"id": result.id, "question": result.question, "status": result.status, "plan": result.plan, "observations": result.observations, "answer": result.answer,
            "metrics": metrics, "steps": [{"index": step.step_index, "kind": step.kind, "status": step.status, "model": step.model, "tool": step.tool, "latency_ms": step.latency_ms} for step in steps]}

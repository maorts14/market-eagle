from datetime import date, datetime, timezone
import json
import statistics
import time
from hashlib import sha256
from temporalio import activity
from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from .config import settings
from .database import SessionLocal
from .market_data import fetch_daily_bars
from .event_research import EventResearchRateLimited, fetch_event_articles
from .lakehouse import append_brief, append_raw_bars, append_relationships, ensure_lakehouse, load_daily_bars, trino_query, upsert_daily_bars, upsert_event_articles, upsert_event_links
from .agent import decide_with_openrouter, evaluate_research_quality
from .models import AgentStep, AnalysisRun, Instrument, PipelineRun, ResearchSession
from .universe import TRACKED_INSTRUMENTS, UNIVERSE


def _start_run(run_id: str, workflow_type: str) -> None:
    with SessionLocal.begin() as session:
        session.execute(insert(PipelineRun).values(id=run_id, workflow_type=workflow_type, status="running", detail={}).on_conflict_do_nothing())


@activity.defn
def register_universe() -> int:
    """Cold-path setup: one write statement for all canonical instruments."""
    ensure_lakehouse()
    with SessionLocal.begin() as session:
        session.execute(insert(Instrument).values([
            {"symbol": symbol, "name": name, "sector": sector, "instrument_type": "etf" if symbol in {item[0] for item in UNIVERSE} else "stock"}
            for symbol, name, sector in TRACKED_INSTRUMENTS
        ]).on_conflict_do_nothing(index_elements=["symbol"]))
    return len(TRACKED_INSTRUMENTS)


@activity.defn
def collect_symbol(payload: dict) -> dict:
    """Worker-triggered ingestion; one source read, then one bulk upsert write."""
    symbol, start, end, run_id = payload["symbol"], date.fromisoformat(payload["start"]), date.fromisoformat(payload["end"]), payload["run_id"]
    _start_run(run_id, payload["workflow_type"])
    bars = fetch_daily_bars(symbol, start, end, settings.data_mode)
    if not bars:
        return {"symbol": symbol, "rows": 0}
    # Bronze retains each provider payload; Silver is an Iceberg upsert keyed by symbol/date.
    append_raw_bars(run_id, symbol, bars)
    upsert_daily_bars(run_id, symbol, bars)
    return {"symbol": symbol, "rows": len(bars)}


@activity.defn
def complete_pipeline_run(payload: dict) -> None:
    with SessionLocal.begin() as session:
        session.execute(
            PipelineRun.__table__.update().where(PipelineRun.id == payload["run_id"]).values(
                status=payload["status"], completed_at=datetime.now(timezone.utc), detail=payload.get("detail", {}),
            )
        )


def _returns_for_symbol(rows: list[dict], symbol: str, window_days: int) -> list[tuple[date, float]]:
    bars = sorted((row for row in rows if row["symbol"] == symbol), key=lambda row: row["trading_date"])[-(window_days + 1):]
    return [(bars[index]["trading_date"], (bars[index]["close"] / bars[index - 1]["close"]) - 1) for index in range(1, len(bars))]


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) < 15 or len(left) != len(right):
        return None
    left_dev = [value - statistics.mean(left) for value in left]
    right_dev = [value - statistics.mean(right) for value in right]
    divisor = (sum(value * value for value in left_dev) * sum(value * value for value in right_dev)) ** 0.5
    return sum(a * b for a, b in zip(left_dev, right_dev)) / divisor if divisor else None


@activity.defn
def calculate_relationships(payload: dict) -> dict:
    """Analysis worker: 12 reads (one per sector) and batched writes for an analysis snapshot."""
    run_id, window_days = payload["run_id"], payload.get("window_days", 60)
    lake_rows = load_daily_bars()
    with SessionLocal.begin() as session:
        return_series = {symbol: _returns_for_symbol(lake_rows, symbol, window_days) for symbol, _, _ in UNIVERSE}
        latest_dates = [series[-1][0] for series in return_series.values() if series]
        if not latest_dates:
            raise ValueError("No daily bars are available; run historical collection first.")
        as_of = min(latest_dates)
        session.merge(AnalysisRun(id=run_id, as_of_date=as_of, window_days=window_days, status="running"))
        edges: list[dict] = []
        for leader, _, _ in UNIVERSE:
            for follower, _, _ in UNIVERSE:
                if leader == follower:
                    continue
                leader_values = [value for _, value in return_series[leader]]
                follower_values = [value for _, value in return_series[follower]]
                for lag in range(1, 6):
                    coefficient = _correlation(leader_values[:-lag], follower_values[lag:])
                    if coefficient is not None and abs(coefficient) >= 0.22:
                        dates = return_series[follower][lag:]
                        edges.append({"analysis_run_id": run_id, "as_of_date": as_of, "leader_symbol": leader, "follower_symbol": follower, "lag_days": lag,
                                      "correlation": round(coefficient, 4), "sample_size": len(dates), "window_start": dates[0][0], "window_end": dates[-1][0]})
        session.execute(AnalysisRun.__table__.update().where(AnalysisRun.id == run_id).values(status="completed"))
    append_relationships(edges)
    return {"analysis_run_id": run_id, "as_of_date": as_of.isoformat(), "relationship_count": len(edges)}


@activity.defn
def write_daily_brief(payload: dict) -> dict:
    analysis_run_id = payload["analysis_run_id"]
    with SessionLocal() as session:
        run = session.get(AnalysisRun, analysis_run_id)
        as_of_date = run.as_of_date
    relationships = trino_query(f"SELECT leader_symbol, follower_symbol, lag_days, correlation, sample_size, window_start, window_end FROM gold.sector_relationships WHERE analysis_run_id = '{analysis_run_id}' ORDER BY correlation DESC LIMIT 3")
    if relationships:
        strongest = relationships[0]
        headline = f"{strongest['leader_symbol']} led {strongest['follower_symbol']} in the latest relationship scan"
        body = (f"Across {strongest['sample_size']} daily return observations ending {strongest['window_end']}, "
                f"{strongest['leader_symbol']} returns preceded {strongest['follower_symbol']} by {strongest['lag_days']} trading day(s) "
                f"with a correlation of {strongest['correlation']:.2f}. This is a historical association, not a forecast.")
        evidence = {"analysis_run_id": analysis_run_id, "leader": strongest["leader_symbol"], "follower": strongest["follower_symbol"],
                    "lag_days": strongest["lag_days"], "correlation": strongest["correlation"], "window": [str(strongest["window_start"]), str(strongest["window_end"])]}
    else:
        headline, body, evidence = "No strong sector relationships in this scan", "The current window did not meet the relationship threshold.", {"analysis_run_id": analysis_run_id}
    insight_id = f"brief-{as_of_date.isoformat()}"
    append_brief({"insight_id": insight_id, "analysis_run_id": analysis_run_id, "as_of_date": as_of_date, "headline": headline, "body": body,
                  "evidence": json.dumps(evidence), "created_at": datetime.now(timezone.utc).replace(tzinfo=None)})
    return {"insight_id": insight_id, "headline": headline}


@activity.defn
def create_research_session(payload: dict) -> None:
    with SessionLocal.begin() as session:
        session.merge(ResearchSession(id=payload["session_id"], question=payload["question"], status="running", plan=[], observations=[]))


def _record_agent_step(payload: dict) -> None:
    with SessionLocal.begin() as session:
        statement = insert(AgentStep).values(payload).on_conflict_do_update(
            constraint="uq_agent_step_session_index_kind",
            set_={key: payload[key] for key in ("status", "model", "tool", "latency_ms", "prompt_tokens", "completion_tokens", "payload")},
        )
        session.execute(statement)


def _claim_agent_decision(payload: dict) -> tuple[AgentStep, bool]:
    """Claim one provider call before it is issued, making retries safe and inspectable."""
    values = {
        "session_id": payload["session_id"], "step_index": payload["step_index"], "kind": "decision", "status": "running",
        "model": None, "tool": None, "latency_ms": 0, "prompt_tokens": 0, "completion_tokens": 0, "payload": {},
    }
    with SessionLocal.begin() as session:
        step_id = session.execute(
            insert(AgentStep).values(values).on_conflict_do_nothing(
                constraint="uq_agent_step_session_index_kind"
            ).returning(AgentStep.id)
        ).scalar_one_or_none()
        if step_id is not None:
            return session.get(AgentStep, step_id), True
        step = session.scalars(select(AgentStep).where(
            AgentStep.session_id == payload["session_id"], AgentStep.step_index == payload["step_index"], AgentStep.kind == "decision",
        )).one()
        return step, False


def _finish_claimed_decision(step_id: int, status: str, model: str | None, tool: str | None, latency_ms: int, prompt_tokens: int, completion_tokens: int, detail: dict) -> bool:
    """Only the active claim may resolve a decision; a late worker cannot overwrite a safe terminal result."""
    with SessionLocal.begin() as session:
        result = session.execute(
            AgentStep.__table__.update().where(AgentStep.id == step_id, AgentStep.status == "running").values(
                status=status, model=model, tool=tool, latency_ms=latency_ms, prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens, payload=detail,
            )
        )
        return result.rowcount == 1


@activity.defn
def decide_agent_action(payload: dict) -> dict:
    """One model turn. Its decision is persisted before Temporal advances the agent loop."""
    step, claimed = _claim_agent_decision(payload)
    if not claimed:
        action = step.payload.get("action")
        if step.status != "running" and isinstance(action, dict):
            return action
        interrupted = {"action": "final", "tool": None, "answer": "A prior model request was interrupted before it could be verified, so no market conclusion was produced."}
        _finish_claimed_decision(step.id, "failed", None, None, step.latency_ms, step.prompt_tokens, step.completion_tokens,
                                 {"action": interrupted, "error": "Unverified prior provider request was not retried."})
        return interrupted
    started = time.perf_counter()
    try:
        decision = decide_with_openrouter(payload["question"], payload["observations"], payload["used_tools"], payload["session_id"])
    except Exception as error:
        action = {"action": "final", "tool": None, "answer": "The model provider was unavailable, so no market conclusion was produced."}
        _finish_claimed_decision(step.id, "failed", None, None, round((time.perf_counter() - started) * 1000), 0, 0,
                                 {"action": action, "error": type(error).__name__})
        return action
    provider_action = decision.action.model_dump()
    action = provider_action
    status = "guarded" if decision.guard_reason else "completed"
    if decision.guard_reason:
        if decision.model != "unconfigured":
            action = {"action": "final", "tool": None, "answer": "The model produced an unsafe or invalid research action, so no market conclusion was produced."}
    if not _finish_claimed_decision(step.id, status, decision.model, decision.action.tool, decision.latency_ms, decision.prompt_tokens,
                                    decision.completion_tokens, {"action": action, "provider_action": provider_action, "guard_reason": decision.guard_reason}):
        with SessionLocal() as session:
            persisted = session.get(AgentStep, step.id)
        if persisted and isinstance(persisted.payload.get("action"), dict):
            return persisted.payload["action"]
        return {"action": "final", "tool": None, "answer": "The model provider was unavailable, so no market conclusion was produced."}
    return action


@activity.defn
def execute_agent_tool(payload: dict) -> dict:
    """One allowlisted read-only tool turn, measured and recorded separately from planning."""
    started = time.perf_counter()
    try:
        result = use_research_tool({"tool": payload["tool"]})
        status, detail = "completed", result
    except Exception as error:
        result = {"tool": payload["tool"], "result": "The research tool was unavailable for this turn."}
        status, detail = "failed", {"result": result, "error": type(error).__name__}
    _record_agent_step({"session_id": payload["session_id"], "step_index": payload["step_index"], "kind": "tool", "status": status, "model": None, "tool": payload["tool"],
                        "latency_ms": round((time.perf_counter() - started) * 1000), "prompt_tokens": 0, "completion_tokens": 0, "payload": detail})
    return result


@activity.defn
def use_research_tool(payload: dict) -> dict:
    tool = payload["tool"]
    if tool == "sector_relationships":
        with SessionLocal() as session:
            run = session.scalars(select(AnalysisRun).where(AnalysisRun.status == "completed").order_by(desc(AnalysisRun.created_at)).limit(1)).first()
        if not run:
            return {"tool": tool, "result": "No completed analysis run is available."}
        rows = trino_query(f"SELECT leader_symbol, follower_symbol, lag_days, correlation, window_end FROM gold.sector_relationships WHERE analysis_run_id = '{run.id}' ORDER BY correlation DESC LIMIT 5")
        return {"tool": tool, "analysis_run_id": run.id, "result": [{"leader": row["leader_symbol"], "follower": row["follower_symbol"], "lag_days": row["lag_days"], "correlation": row["correlation"], "window_end": str(row["window_end"])} for row in rows]}
    if tool == "recent_performance":
        rows = trino_query("""
            WITH ranked AS (
              SELECT symbol, trading_date, close, row_number() OVER (PARTITION BY symbol ORDER BY trading_date DESC) AS position
              FROM silver.daily_bars
            )
            SELECT latest.symbol, latest.trading_date AS as_of, round((latest.close / prior.close - 1) * 100, 2) AS return_5d
            FROM ranked latest JOIN ranked prior ON latest.symbol = prior.symbol
            WHERE latest.position = 1 AND prior.position = 6 ORDER BY return_5d DESC
        """)
        sectors = {symbol: sector for symbol, _, sector in TRACKED_INSTRUMENTS}
        return {"tool": tool, "result": [{"symbol": row["symbol"], "sector": sectors[row["symbol"]], "return_5d": float(row["return_5d"]), "as_of": str(row["as_of"])} for row in rows]}
    if tool == "event_context":
        with SessionLocal() as session:
            run = session.scalars(select(AnalysisRun).where(AnalysisRun.status == "completed").order_by(desc(AnalysisRun.created_at)).limit(1)).first()
        if not run:
            return {"tool": tool, "result": "No completed relationship scan is available."}
        relationships = trino_query(f"SELECT leader_symbol, follower_symbol FROM gold.sector_relationships WHERE analysis_run_id = '{run.id}' ORDER BY correlation DESC LIMIT 1")
        sectors = {symbol: sector for symbol, _, sector in TRACKED_INSTRUMENTS}
        articles: list[dict] = []
        links: list[dict] = []
        for relationship in relationships:
            leader, follower = relationship["leader_symbol"], relationship["follower_symbol"]
            query = f'"{sectors[leader]}" "{sectors[follower]}"'
            try:
                matched_articles = fetch_event_articles(query, max_records=4)
            except EventResearchRateLimited as error:
                return {"tool": tool, "analysis_run_id": run.id, "result": str(error)}
            articles.extend(matched_articles)
            links.extend({
                "link_id": sha256(f"{run.id}:{leader}:{follower}:{article['event_id']}".encode()).hexdigest(),
                "analysis_run_id": run.id, "leader_symbol": leader, "follower_symbol": follower,
                "event_id": article["event_id"], "title": article["title"], "url": article["url"],
                "domain": article["domain"], "seen_at": article["seen_at"], "link_type": "news_context",
            } for article in matched_articles)
        distinct_articles = list({article["event_id"]: article for article in articles}.values())
        distinct_links = list({link["link_id"]: link for link in links}.values())
        upsert_event_articles(distinct_articles)
        upsert_event_links(distinct_links)
        return {"tool": tool, "analysis_run_id": run.id, "result": [{"leader": item["leader_symbol"], "follower": item["follower_symbol"], "title": item["title"], "url": item["url"], "domain": item["domain"], "seen_at": item["seen_at"].isoformat()} for item in distinct_links[:6]]}
    return {"tool": tool, "result": "Instrument-specific history is available in the lakehouse but this research plan did not select a symbol."}


@activity.defn
def complete_research_session(payload: dict) -> str:
    observations = payload["observations"]
    answer = payload["answer"]
    if "not causation" not in answer.lower():
        answer += " Historical association is not causation, prediction, or investment advice."
    quality = evaluate_research_quality(answer, observations)
    with SessionLocal.begin() as session:
        session.execute(ResearchSession.__table__.update().where(ResearchSession.id == payload["session_id"]).values(status="completed", plan=payload["plan"], observations=observations, answer=answer))
        session.execute(insert(AgentStep).values(
            session_id=payload["session_id"], step_index=payload["step_index"], kind="final", status="completed", model=payload.get("model"), tool=None,
            latency_ms=0, prompt_tokens=0, completion_tokens=0, payload=quality,
        ).on_conflict_do_update(
            constraint="uq_agent_step_session_index_kind",
            set_={"status": "completed", "model": payload.get("model"), "tool": None, "latency_ms": 0, "prompt_tokens": 0,
                  "completion_tokens": 0, "payload": quality},
        ))
    return answer

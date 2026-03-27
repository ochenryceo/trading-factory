"""Trading Factory — FastAPI application entry point."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session, init_db
from core.enums import EventType, PipelineStage, STAGE_ORDER
from core.models import (
    AuditLog,
    Override,
    ResearchSource,
    Strategy,
    StrategyHistory,
    StrategyMetric,
    TradeExplanation,
)
from core.schemas import (
    AuditResponse,
    KillFeedEvent,
    LiveOpsResponse,
    MetricsSummary,
    OverrideResponse,
    PipelineGroup,
    ResearchSourceResponse,
    RiskStateResponse,
    StrategyResponse,
    StrategyWithMetrics,
    TradeExplanationResponse,
)
from services.risk.kill_switches import get_system_risk_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB tables. Shutdown: cleanup."""
    await init_db()
    yield


app = FastAPI(
    title="Trading Factory API",
    description="Multi-agent strategy factory and trading operations backend",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Health                                                                      #
# --------------------------------------------------------------------------- #

@app.get("/health")
async def health():
    return {"status": "ok", "service": "trading-factory"}


# --------------------------------------------------------------------------- #
# GET /strategies                                                             #
# --------------------------------------------------------------------------- #

@app.get("/strategies", response_model=list[StrategyWithMetrics])
async def list_strategies(
    stage: str | None = None,
    style: str | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """All strategies with current stage, status, and latest metrics."""
    query = select(Strategy).order_by(Strategy.current_rank.nulls_last(), Strategy.created_at)

    if stage:
        query = query.where(Strategy.current_stage == stage)
    if style:
        query = query.where(Strategy.style == style)
    if status:
        query = query.where(Strategy.status == status)

    result = await session.execute(query)
    strategies = result.scalars().all()

    response = []
    for s in strategies:
        # Get latest metrics
        m_result = await session.execute(
            select(StrategyMetric)
            .where(StrategyMetric.strategy_id == s.id)
            .order_by(StrategyMetric.timestamp.desc())
            .limit(1)
        )
        m = m_result.scalar_one_or_none()

        item = StrategyWithMetrics.model_validate(s)
        if m:
            item.latest_pnl = m.pnl
            item.latest_sharpe = m.sharpe
            item.latest_drawdown = m.drawdown
            item.latest_win_rate = m.win_rate
            item.latest_trade_count = m.trade_count
        response.append(item)

    return response


# --------------------------------------------------------------------------- #
# GET /strategies/{id}                                                        #
# --------------------------------------------------------------------------- #

@app.get("/strategies/{strategy_id}")
async def get_strategy(
    strategy_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Full strategy detail including metrics, history, trade explanations."""
    strategy = await session.get(Strategy, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # Metrics history
    m_result = await session.execute(
        select(StrategyMetric)
        .where(StrategyMetric.strategy_id == strategy_id)
        .order_by(StrategyMetric.timestamp.desc())
    )
    metrics = [m.__dict__ for m in m_result.scalars().all()]

    # Stage history
    h_result = await session.execute(
        select(StrategyHistory)
        .where(StrategyHistory.strategy_id == strategy_id)
        .order_by(StrategyHistory.created_at)
    )
    history = [HistoryResponse.model_validate(h) for h in h_result.scalars().all()]

    # Trade explanations
    te_result = await session.execute(
        select(TradeExplanation)
        .where(TradeExplanation.strategy_id == strategy_id)
        .order_by(TradeExplanation.created_at.desc())
        .limit(50)
    )
    explanations = [TradeExplanationResponse.model_validate(t) for t in te_result.scalars().all()]

    return {
        "strategy": StrategyResponse.model_validate(strategy),
        "metrics": metrics,
        "history": history,
        "trade_explanations": explanations,
    }


# --------------------------------------------------------------------------- #
# GET /pipeline                                                               #
# --------------------------------------------------------------------------- #

@app.get("/pipeline", response_model=list[PipelineGroup])
async def get_pipeline(session: AsyncSession = Depends(get_session)):
    """Strategies grouped by pipeline stage — for the Kanban board."""
    groups = []
    for stage in STAGE_ORDER:
        result = await session.execute(
            select(Strategy).where(Strategy.current_stage == stage.value)
        )
        strategies = result.scalars().all()

        items = []
        for s in strategies:
            m_result = await session.execute(
                select(StrategyMetric)
                .where(StrategyMetric.strategy_id == s.id)
                .order_by(StrategyMetric.timestamp.desc())
                .limit(1)
            )
            m = m_result.scalar_one_or_none()
            item = StrategyWithMetrics.model_validate(s)
            if m:
                item.latest_pnl = m.pnl
                item.latest_sharpe = m.sharpe
                item.latest_drawdown = m.drawdown
                item.latest_win_rate = m.win_rate
                item.latest_trade_count = m.trade_count
            items.append(item)

        groups.append(PipelineGroup(stage=stage.value, strategies=items, count=len(items)))

    return groups


# --------------------------------------------------------------------------- #
# GET /metrics/summary                                                        #
# --------------------------------------------------------------------------- #

@app.get("/metrics/summary", response_model=MetricsSummary)
async def get_metrics_summary(session: AsyncSession = Depends(get_session)):
    """Dashboard-level aggregate metrics."""
    # Count by status
    total = (await session.execute(select(func.count(Strategy.id)))).scalar() or 0
    active = (await session.execute(
        select(func.count(Strategy.id)).where(Strategy.status == "ACTIVE")
    )).scalar() or 0
    killed = (await session.execute(
        select(func.count(Strategy.id)).where(Strategy.status == "KILLED")
    )).scalar() or 0
    retired = (await session.execute(
        select(func.count(Strategy.id)).where(Strategy.status == "RETIRED")
    )).scalar() or 0

    # Aggregate from latest metrics per strategy (subquery)
    from sqlalchemy import distinct
    latest_metrics = await session.execute(
        select(StrategyMetric)
        .distinct(StrategyMetric.strategy_id)
        .order_by(StrategyMetric.strategy_id, StrategyMetric.timestamp.desc())
    )
    all_metrics = latest_metrics.scalars().all()

    total_pnl = sum(m.pnl for m in all_metrics)
    avg_sharpe = (sum(m.sharpe for m in all_metrics) / len(all_metrics)) if all_metrics else 0
    avg_wr = (sum(m.win_rate for m in all_metrics) / len(all_metrics)) if all_metrics else 0

    # Count by stage
    stage_counts: dict[str, int] = {}
    for stage in STAGE_ORDER:
        cnt = (await session.execute(
            select(func.count(Strategy.id)).where(Strategy.current_stage == stage.value)
        )).scalar() or 0
        stage_counts[stage.value] = cnt

    # Count by style
    style_result = await session.execute(
        select(Strategy.style, func.count(Strategy.id)).group_by(Strategy.style)
    )
    style_counts = {row[0]: row[1] for row in style_result.all()}

    return MetricsSummary(
        total_strategies=total,
        active_strategies=active,
        killed_strategies=killed,
        retired_strategies=retired,
        total_pnl=round(total_pnl, 2),
        avg_sharpe=round(avg_sharpe, 3),
        avg_win_rate=round(avg_wr, 3),
        strategies_by_stage=stage_counts,
        strategies_by_style=style_counts,
    )


# --------------------------------------------------------------------------- #
# GET /events/kill-feed                                                       #
# --------------------------------------------------------------------------- #

KILL_FEED_EVENTS = {
    EventType.STRATEGY_KILLED.value,
    EventType.STRATEGY_DEMOTED.value,
    EventType.STRATEGY_RETIRED.value,
    EventType.STAGE_REJECTED.value,
    EventType.RISK_LIMIT_HIT.value,
    EventType.OVERRIDE_ATTEMPTED.value,
    EventType.OVERRIDE_REJECTED.value,
    EventType.FAST_VALIDATION_FAILED.value,
}


@app.get("/events/kill-feed", response_model=list[KillFeedEvent])
async def get_kill_feed(
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Scrolling feed of kills, failures, risk events, override attempts."""
    result = await session.execute(
        select(AuditLog)
        .where(AuditLog.event_type.in_(KILL_FEED_EVENTS))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    events = result.scalars().all()

    feed = []
    for e in events:
        # Lookup strategy code if available
        code = None
        if e.strategy_id:
            s = await session.get(Strategy, e.strategy_id)
            code = s.strategy_code if s else None

        feed.append(KillFeedEvent(
            id=e.id,
            strategy_id=e.strategy_id,
            strategy_code=code,
            event_type=e.event_type,
            source_service=e.source_service,
            payload_json=e.payload_json,
            created_at=e.created_at,
        ))
    return feed


# --------------------------------------------------------------------------- #
# GET /risk/state                                                             #
# --------------------------------------------------------------------------- #

@app.get("/risk/state", response_model=RiskStateResponse)
async def get_risk_state():
    """Current global risk posture."""
    state = get_system_risk_state()
    return RiskStateResponse(
        mode=state.mode.value,
        daily_loss=state.daily_loss,
        total_drawdown=state.total_drawdown,
        active_positions=state.active_positions,
        capital_at_risk=state.capital_at_risk,
        kill_switches_triggered=state.kill_switches_triggered,
        strategies_under_warning=state.strategies_under_warning,
    )


# --------------------------------------------------------------------------- #
# GET /research/styles                                                        #
# --------------------------------------------------------------------------- #

@app.get("/research/styles")
async def get_research_styles(session: AsyncSession = Depends(get_session)):
    """Per-style research sources and trader inspirations."""
    result = await session.execute(
        select(ResearchSource).order_by(ResearchSource.strategy_style, ResearchSource.trader_name)
    )
    sources = result.scalars().all()

    by_style: dict[str, list] = {}
    for src in sources:
        style = src.strategy_style
        if style not in by_style:
            by_style[style] = []
        by_style[style].append(ResearchSourceResponse.model_validate(src))

    return by_style


# --------------------------------------------------------------------------- #
# GET /audit                                                                  #
# --------------------------------------------------------------------------- #

@app.get("/audit", response_model=list[AuditResponse])
async def get_audit(
    strategy_id: uuid.UUID | None = None,
    event_type: str | None = None,
    source_service: str | None = None,
    limit: int = Query(100, le=500),
    session: AsyncSession = Depends(get_session),
):
    """Filtered audit event history."""
    query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)

    if strategy_id:
        query = query.where(AuditLog.strategy_id == strategy_id)
    if event_type:
        query = query.where(AuditLog.event_type == event_type)
    if source_service:
        query = query.where(AuditLog.source_service == source_service)

    result = await session.execute(query)
    return [AuditResponse.model_validate(a) for a in result.scalars().all()]


# --------------------------------------------------------------------------- #
# GET /live-ops                                                               #
# --------------------------------------------------------------------------- #

@app.get("/live-ops", response_model=LiveOpsResponse)
async def get_live_ops(session: AsyncSession = Depends(get_session)):
    """Active signals, approvals, live activity."""
    # Count strategies in live stages
    paper_cnt = (await session.execute(
        select(func.count(Strategy.id)).where(
            Strategy.current_stage == PipelineStage.PAPER.value,
            Strategy.is_active == True,
        )
    )).scalar() or 0
    micro_cnt = (await session.execute(
        select(func.count(Strategy.id)).where(
            Strategy.current_stage == PipelineStage.MICRO_LIVE.value,
            Strategy.is_active == True,
        )
    )).scalar() or 0
    full_cnt = (await session.execute(
        select(func.count(Strategy.id)).where(
            Strategy.current_stage == PipelineStage.FULL_LIVE.value,
            Strategy.is_active == True,
        )
    )).scalar() or 0

    # Recent trade explanations
    te_result = await session.execute(
        select(TradeExplanation)
        .order_by(TradeExplanation.created_at.desc())
        .limit(20)
    )
    recent_trades = [
        TradeExplanationResponse.model_validate(t) for t in te_result.scalars().all()
    ]

    risk_state = get_system_risk_state()

    return LiveOpsResponse(
        active_signals=[],  # populated when execution engine is live
        recent_trades=recent_trades,
        current_mode=risk_state.mode.value,
        strategies_in_paper=paper_cnt,
        strategies_in_micro=micro_cnt,
        strategies_in_full=full_cnt,
    )


# Import needed for strategy detail endpoint
from core.schemas import HistoryResponse  # noqa: E402


# --------------------------------------------------------------------------- #
# Fast validation data (read from file)                                       #
# --------------------------------------------------------------------------- #

import json as _json
from pathlib import Path as _Path

_FV_PATH = _Path(__file__).parent / "data" / "mock" / "fast_validation_results.json"


def _load_fv_results():
    if _FV_PATH.exists():
        with open(_FV_PATH) as f:
            return _json.load(f)
    return []


@app.get("/fast-validation/results")
async def get_fv_results():
    """All fast validation results."""
    return _load_fv_results()


@app.get("/fast-validation/results/{strategy_id}")
async def get_fv_result(strategy_id: str):
    """Fast validation result for one strategy."""
    results = _load_fv_results()
    for r in results:
        if r["strategy_id"] == strategy_id:
            return r
    raise HTTPException(status_code=404, detail=f"No FV result for {strategy_id}")


@app.get("/fast-validation/stats")
async def get_fv_stats():
    """Fast validation summary stats."""
    results = _load_fv_results()
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = total - passed
    return {
        "total_run": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
    }


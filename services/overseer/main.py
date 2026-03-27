"""
Overseer FastAPI Service — Meta-Orchestrator / Head Trader.

Port 8004:
  POST /evaluate       — evaluate a trade signal
  POST /approve        — approve/reject a trade
  GET  /portfolio      — current portfolio state
  GET  /active-strategies — which strategies are enabled
  POST /activate       — activate/deactivate a strategy agent
  GET  /health
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from services.overseer.approvals import ApprovalPipeline, GlobalRiskLimits, RiskState
from services.overseer.decision_engine import (
    Decision,
    DecisionEngine,
    Direction,
    MarketContext,
    PerformanceRanking,
    RiskLevel,
    Timeframe,
    TradeSignal,
)
from services.overseer.portfolio_manager import PortfolioManager, Position

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("overseer")

# --------------------------------------------------------------------------- #
# App & Shared State                                                          #
# --------------------------------------------------------------------------- #

app = FastAPI(title="Overseer — Meta-Orchestrator", version="1.0.0")

engine = DecisionEngine()
pipeline = ApprovalPipeline()
portfolio = PortfolioManager()

# Active strategy registry
active_strategies: dict[str, bool] = {
    "momentum": True,
    "mean_reversion": True,
    "scalp": True,
    "trend": True,
    "news_reaction": True,
    "volume_flow": True,
}


# --------------------------------------------------------------------------- #
# Request / Response Models                                                   #
# --------------------------------------------------------------------------- #

class SignalRequest(BaseModel):
    strategy_id: str
    strategy_name: str
    asset: str
    direction: str  # LONG / SHORT / FLAT
    confidence: float = Field(ge=0.0, le=1.0)
    risk_level: str = "MEDIUM"  # LOW / MEDIUM / HIGH / EXTREME
    timeframes: dict[str, str] = Field(default_factory=dict)  # "5m": "LONG", etc.
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_reward_ratio: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApproveRequest(BaseModel):
    strategy_id: str
    strategy_name: str
    asset: str
    direction: str
    confidence: float = Field(ge=0.0, le=1.0)
    risk_level: str = "MEDIUM"
    timeframes: dict[str, str] = Field(default_factory=dict)
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_reward_ratio: float | None = None


class ActivateRequest(BaseModel):
    strategy_name: str
    active: bool


class MarketContextUpdate(BaseModel):
    regime: str = "normal"
    vix_level: float = 15.0
    market_direction: str = "FLAT"
    sentiment_score: float = 0.0


class RankingUpdate(BaseModel):
    strategy_id: str
    rank: int
    win_rate: float
    sharpe: float
    pnl_30d: float


# --------------------------------------------------------------------------- #
# Helper: parse request → domain objects                                      #
# --------------------------------------------------------------------------- #

def _parse_signal(req: SignalRequest | ApproveRequest) -> TradeSignal:
    tf_map: dict[Timeframe, Direction] = {}
    for k, v in req.timeframes.items():
        try:
            tf = Timeframe(k)
            dr = Direction(v)
            tf_map[tf] = dr
        except ValueError:
            pass  # skip unknown TF/direction

    return TradeSignal(
        strategy_id=req.strategy_id,
        strategy_name=req.strategy_name,
        asset=req.asset,
        direction=Direction(req.direction),
        confidence=req.confidence,
        risk_level=RiskLevel(req.risk_level),
        timeframes=tf_map,
        entry_price=getattr(req, "entry_price", None),
        stop_loss=getattr(req, "stop_loss", None),
        take_profit=getattr(req, "take_profit", None),
        risk_reward_ratio=getattr(req, "risk_reward_ratio", None),
        metadata=getattr(req, "metadata", {}),
    )


# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #

@app.post("/evaluate")
async def evaluate_signal(req: SignalRequest) -> dict[str, Any]:
    """Evaluate a trade signal through the decision engine."""
    if not active_strategies.get(req.strategy_name, False):
        return {
            "decision": "REJECT",
            "reason": f"Strategy '{req.strategy_name}' is not active",
            "score": 0.0,
        }

    signal = _parse_signal(req)
    decision = engine.evaluate(signal)
    return decision.to_dict()


@app.post("/approve")
async def approve_trade(req: ApproveRequest) -> dict[str, Any]:
    """Run a signal through full decision engine + approval pipeline."""
    if not active_strategies.get(req.strategy_name, False):
        return {
            "approved": False,
            "decision": "REJECT",
            "reason": f"Strategy '{req.strategy_name}' is not active",
        }

    signal = _parse_signal(req)

    # Check portfolio can take the position
    can_open, open_reason = portfolio.can_open_position(signal.asset)
    if not can_open:
        return {
            "approved": False,
            "decision": "REJECT_PORTFOLIO",
            "reason": open_reason,
        }

    # Evaluate
    decision = engine.evaluate(signal)

    # Sync risk state to pipeline
    pipeline.state = RiskState(
        daily_pnl=portfolio.net_daily_pnl,
        open_positions=portfolio.open_position_count,
        total_exposure=portfolio.total_exposure,
        capital=portfolio.capital,
        positions_by_asset=portfolio.positions_by_asset(),
    )

    # Approve
    result = pipeline.process(decision)
    return result


@app.get("/portfolio")
async def get_portfolio() -> dict[str, Any]:
    """Current portfolio state."""
    return portfolio.get_state()


@app.get("/active-strategies")
async def get_active_strategies() -> dict[str, Any]:
    """Which strategy agents are currently enabled."""
    return {
        "strategies": active_strategies,
        "active_count": sum(1 for v in active_strategies.values() if v),
        "total_count": len(active_strategies),
    }


@app.post("/activate")
async def activate_strategy(req: ActivateRequest) -> dict[str, Any]:
    """Activate or deactivate a strategy agent."""
    if req.strategy_name not in active_strategies:
        raise HTTPException(404, f"Unknown strategy: {req.strategy_name}")

    old = active_strategies[req.strategy_name]
    active_strategies[req.strategy_name] = req.active
    action = "activated" if req.active else "deactivated"
    logger.info("Strategy '%s' %s (was %s)", req.strategy_name, action, old)
    return {
        "strategy": req.strategy_name,
        "active": req.active,
        "previous": old,
    }


@app.post("/market-context")
async def update_market_context(req: MarketContextUpdate) -> dict[str, str]:
    """Update market context from Pulse/Feed."""
    engine.update_market_context(MarketContext(
        regime=req.regime,
        vix_level=req.vix_level,
        market_direction=Direction(req.market_direction),
        sentiment_score=req.sentiment_score,
    ))
    return {"status": "updated"}


@app.post("/rankings")
async def update_rankings(rankings: list[RankingUpdate]) -> dict[str, Any]:
    """Update Darwin performance rankings."""
    parsed = [
        PerformanceRanking(
            strategy_id=r.strategy_id,
            rank=r.rank,
            win_rate=r.win_rate,
            sharpe=r.sharpe,
            pnl_30d=r.pnl_30d,
        )
        for r in rankings
    ]
    engine.update_rankings(parsed)
    return {"updated": len(parsed)}


@app.get("/audit-trail")
async def get_audit_trail(limit: int = 50) -> list[dict[str, Any]]:
    """Recent audit trail entries."""
    return pipeline.get_audit_trail(limit)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "service": "overseer",
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_strategies": sum(1 for v in active_strategies.values() if v),
        "open_positions": portfolio.open_position_count,
        "daily_pnl": portfolio.net_daily_pnl,
    }


# --------------------------------------------------------------------------- #
# Entrypoint                                                                  #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)

"""
Strategy Executor Service — FastAPI on port 8002.

Runs 6 executor agents against market data, routes signals through Overseer.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .base_executor import MarketContext
from .signal_router import SignalRouter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("executor_service")

# ── Load Strategy DNAs ───────────────────────────────────────────────────────

DNA_PATH = os.getenv(
    "STRATEGY_DNA_PATH",
    str(Path(__file__).resolve().parents[2] / "data" / "mock" / "strategy_dnas.json"),
)


def load_dnas() -> list[dict[str, Any]]:
    with open(DNA_PATH) as f:
        return json.load(f)


# ── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Trading Factory — Strategy Executors",
    description="6 executor agents: Alpha (Momentum), Bravo (Mean Reversion), "
                "Charlie (Scalping), Delta (Trend), Echo (News), Foxtrot (Volume/OF)",
    version="1.0.0",
)

router: SignalRouter | None = None


@app.on_event("startup")
async def startup():
    global router
    dnas = load_dnas()
    account_size = float(os.getenv("ACCOUNT_SIZE", "100000"))
    router = SignalRouter(dnas, account_size)
    logger.info(f"Executor service started — {len(router.agents)} agents loaded")


# ── Request/Response Models ──────────────────────────────────────────────────

class MarketContextRequest(BaseModel):
    """Market context input — matches feed service output."""
    instrument: str = "NQ"
    timestamp: str = ""
    # Timeframe data as nested dicts
    tf_4h: dict[str, Any] = {}
    tf_1h: dict[str, Any] = {}
    tf_15m: dict[str, Any] = {}
    tf_5m: dict[str, Any] = {}
    news_events: list[dict[str, Any]] = []
    session_info: dict[str, Any] = {}

    def to_market_context_dict(self) -> dict[str, Any]:
        """Convert to the dict format MarketContext.from_dict expects."""
        return {
            "instrument": self.instrument,
            "timestamp": self.timestamp,
            "4h": self.tf_4h,
            "1h": self.tf_1h,
            "15m": self.tf_15m,
            "5m": self.tf_5m,
            "news_events": self.news_events,
            "session_info": self.session_info,
        }


class RunRequest(BaseModel):
    """Request to run all agents."""
    market_context: MarketContextRequest
    auto_approve: bool = False


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "executor",
        "agents_loaded": len(router.agents) if router else 0,
    }


@app.post("/run")
async def run_agents(request: RunRequest):
    """Run all 6 agents against current market state."""
    if not router:
        raise HTTPException(status_code=503, detail="Router not initialized")

    ctx = MarketContext.from_dict(request.market_context.to_market_context_dict())
    result = router.run_all(ctx, auto_approve=request.auto_approve)

    return {
        "timestamp": result.timestamp,
        "instrument": result.instrument,
        "signals_generated": len(result.signals_generated),
        "signals_approved": len(result.signals_approved),
        "signals_rejected": len(result.signals_rejected),
        "errors": len(result.errors),
        "details": {
            "generated": result.signals_generated,
            "approved": result.signals_approved,
            "rejected": result.signals_rejected,
            "errors": result.errors,
        },
    }


@app.get("/agents")
async def list_agents():
    """List all agents and their current status."""
    if not router:
        raise HTTPException(status_code=503, detail="Router not initialized")

    return {
        "agents": router.get_all_agents_status(),
        "total": len(router.agents),
    }


@app.get("/agents/{agent_id}/trades")
async def agent_trades(agent_id: str):
    """Get trade history for a specific agent."""
    if not router:
        raise HTTPException(status_code=503, detail="Router not initialized")

    agent = router.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    return {
        "agent_id": agent_id,
        "trades": router.get_agent_trades(agent_id),
        "status": agent.get_status(),
    }


@app.get("/runs")
async def list_runs():
    """List recent run results."""
    if not router:
        raise HTTPException(status_code=503, detail="Router not initialized")

    return {
        "total_runs": len(router.run_history),
        "recent": [
            {
                "timestamp": r.timestamp,
                "instrument": r.instrument,
                "generated": len(r.signals_generated),
                "approved": len(r.signals_approved),
                "rejected": len(r.signals_rejected),
            }
            for r in router.run_history[-20:]  # last 20 runs
        ],
    }


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("EXECUTOR_PORT", "8002"))
    uvicorn.run(app, host="0.0.0.0", port=port)

"""
Darwin FastAPI Service — Validation engine endpoints.

POST /backtest   — run backtest on a strategy DNA
POST /validate   — run regime testing
POST /degrade    — run multi-axis degradation
POST /dependency — run dependency test
GET  /rankings   — get current strategy rankings
GET  /health     — health check
"""

from __future__ import annotations
import json
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pandas as pd

from .backtester import run_backtest, generate_synthetic_ohlcv, BacktestResult
from .validator import validate_strategy
from .degradation import run_degradation
from .dependency_test import run_dependency_test
from .ranking import rank_strategies, compute_composite_score

app = FastAPI(title="Darwin — Validation Engine", version="1.0.0")

# In-memory store for rankings
_rankings_store: List[Dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class StrategyDNARequest(BaseModel):
    dna: Dict[str, Any]
    n_bars: int = 2000
    regime: str = "mixed"
    seed: int = 42


class BacktestResponse(BaseModel):
    result: Dict[str, Any]


class ValidationResponse(BaseModel):
    result: Dict[str, Any]


class DegradationResponse(BaseModel):
    result: Dict[str, Any]


class DependencyResponse(BaseModel):
    result: Dict[str, Any]


class RankingsResponse(BaseModel):
    rankings: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_data(req: StrategyDNARequest) -> pd.DataFrame:
    """Generate synthetic data for the request."""
    return generate_synthetic_ohlcv(
        n_bars=req.n_bars,
        regime=req.regime,
        seed=req.seed,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "darwin", "version": "1.0.0"}


@app.post("/backtest", response_model=BacktestResponse)
async def backtest_endpoint(req: StrategyDNARequest):
    try:
        df = _get_data(req)
        result = run_backtest(req.dna, df)
        return BacktestResponse(result=result.to_dict())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/validate", response_model=ValidationResponse)
async def validate_endpoint(req: StrategyDNARequest):
    try:
        df = _get_data(req)
        result = validate_strategy(req.dna, df)
        return ValidationResponse(result=result.to_dict())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/degrade", response_model=DegradationResponse)
async def degrade_endpoint(req: StrategyDNARequest):
    try:
        df = _get_data(req)
        result = run_degradation(req.dna, df)
        return DegradationResponse(result=result.to_dict())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/dependency", response_model=DependencyResponse)
async def dependency_endpoint(req: StrategyDNARequest):
    try:
        df = _get_data(req)
        result = run_dependency_test(req.dna, df)
        return DependencyResponse(result=result.to_dict())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/rankings", response_model=RankingsResponse)
async def rankings_endpoint():
    """Return the latest computed rankings."""
    return RankingsResponse(rankings=_rankings_store)


@app.post("/rankings/compute")
async def compute_rankings(dnas: List[Dict[str, Any]], n_bars: int = 2000, seed: int = 42):
    """Compute rankings for a list of strategy DNAs."""
    global _rankings_store
    try:
        df = generate_synthetic_ohlcv(n_bars=n_bars, seed=seed)
        results = []
        for dna in dnas:
            bt = run_backtest(dna, df)
            results.append(bt)

        ranked = rank_strategies(results)
        _rankings_store = [r.to_dict() for r in ranked]
        return {"rankings": _rankings_store}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("DARWIN_PORT", 8003))
    uvicorn.run(app, host="0.0.0.0", port=port)

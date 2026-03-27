"""
Fast Validation FastAPI Service — Port 8005

Pre-gate filter: run vectorbt fast validation on strategy DNAs before
they enter the formal 8-stage pipeline.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Ensure project root is on sys.path for core imports
_project_root = str(Path(__file__).resolve().parents[2])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from services.fast_validation.vectorbt_runner import run_fast_validation
from services.fast_validation.schemas import FastValidationResult
from services.fast_validation.queue_manager import get_queue_state

app = FastAPI(title="Fast Validation Service", version="1.0.0")

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------
_results: Dict[str, Dict[str, Any]] = {}
_audit_trail: List[Dict[str, Any]] = []


def _log_event(event_type: str, strategy_id: str, payload: dict | None = None):
    _audit_trail.append({
        "event_type": event_type,
        "strategy_id": strategy_id,
        "payload": payload or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class StrategyDNAInput(BaseModel):
    dna: Dict[str, Any]
    asset: str = "NQ"
    last_n_days: int = 30


class BatchInput(BaseModel):
    strategies: List[StrategyDNAInput]


class ValidationResultResponse(BaseModel):
    strategy_id: str
    status: str
    reason: Optional[str]
    metrics: Dict[str, Any]
    tested_window: str
    confidence: float = 0.0
    queue_priority: str = ""
    fail_reasons: List[str] = []


class StatsResponse(BaseModel):
    total_run: int
    passed: int
    failed: int
    pass_rate: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "fast-validation", "version": "1.0.0"}


@app.post("/validate", response_model=ValidationResultResponse)
async def validate(req: StrategyDNAInput):
    """Run fast validation on a single strategy DNA."""
    strategy_id = req.dna.get("strategy_code", "UNKNOWN")
    _log_event("FAST_VALIDATION_STARTED", strategy_id)

    result = run_fast_validation(
        dna=req.dna,
        asset=req.asset,
        last_n_days=req.last_n_days,
    )

    # Store
    _results[result.strategy_id] = result.to_dict()

    # Audit
    if result.status == "PASS":
        _log_event("FAST_VALIDATION_PASSED", result.strategy_id, result.metrics)
    else:
        _log_event("FAST_VALIDATION_FAILED", result.strategy_id, {
            "reason": result.reason,
            "metrics": result.metrics,
        })

    return ValidationResultResponse(**result.to_dict())


@app.post("/validate/batch", response_model=List[ValidationResultResponse])
async def validate_batch(req: BatchInput):
    """Run fast validation on multiple DNAs."""
    responses = []
    for item in req.strategies:
        strategy_id = item.dna.get("strategy_code", "UNKNOWN")
        _log_event("FAST_VALIDATION_STARTED", strategy_id)

        result = run_fast_validation(
            dna=item.dna,
            asset=item.asset,
            last_n_days=item.last_n_days,
        )
        _results[result.strategy_id] = result.to_dict()

        if result.status == "PASS":
            _log_event("FAST_VALIDATION_PASSED", result.strategy_id, result.metrics)
        else:
            _log_event("FAST_VALIDATION_FAILED", result.strategy_id, {
                "reason": result.reason,
                "metrics": result.metrics,
            })

        responses.append(ValidationResultResponse(**result.to_dict()))

    return responses


@app.get("/results", response_model=List[ValidationResultResponse])
async def get_all_results():
    """All fast validation results."""
    return [ValidationResultResponse(**v) for v in _results.values()]


@app.get("/results/{strategy_id}", response_model=ValidationResultResponse)
async def get_result(strategy_id: str):
    """Result for one strategy."""
    if strategy_id not in _results:
        raise HTTPException(status_code=404, detail=f"No result for {strategy_id}")
    return ValidationResultResponse(**_results[strategy_id])


@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Summary stats: total run, passed, failed, pass rate."""
    total = len(_results)
    passed = sum(1 for v in _results.values() if v["status"] == "PASS")
    failed = total - passed
    return StatsResponse(
        total_run=total,
        passed=passed,
        failed=failed,
        pass_rate=round(passed / total, 4) if total > 0 else 0.0,
    )


@app.get("/audit")
async def get_audit():
    """Return audit trail events."""
    return _audit_trail


@app.get("/queue")
async def get_queue():
    """Return current queue state — strategies categorized by priority."""
    return get_queue_state(list(_results.values()))


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("FAST_VALIDATION_PORT", 8005))
    uvicorn.run(app, host="0.0.0.0", port=port)

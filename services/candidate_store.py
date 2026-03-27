"""
Candidate Store — Full Artifact Persistence for Production Gate
================================================================
Stores complete strategy artifacts (params, trades, equity curve, metadata)
for any strategy that passes quality thresholds. This bridges the gap between
backtester discovery and production gate validation.

Persistence trigger:
  - Darwin tier = "production" or "exploration"
  - OR fitness > 0.50
  - OR sharpe > 2.0

Storage: data/candidates/{strategy_code}.json
Dedup: by strategy hash (params + data_range)

Author: Henry (autonomous build)
Date: 2026-03-26
"""

import hashlib
import json
import logging
import gc
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("candidate_store")

CANDIDATE_DIR = Path("Path(__file__).resolve().parents[1]/data/candidates")
CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)

# Persistence thresholds — only store what matters
PERSIST_MIN_SHARPE = 2.0
PERSIST_MIN_FITNESS = 0.50
PERSIST_TIERS = {"production", "exploration"}

# Dedup index
INDEX_FILE = CANDIDATE_DIR / "_index.json"


def strategy_hash(params: dict, asset: str, timeframe: str) -> str:
    """Deterministic hash for dedup. Same params + data = same hash."""
    key = json.dumps({"params": params, "asset": asset, "tf": timeframe}, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def should_persist(
    tier: str,
    fitness: float = 0.0,
    sharpe: float = 0.0,
) -> bool:
    """Check if this strategy should be persisted."""
    if tier in PERSIST_TIERS:
        return True
    if fitness >= PERSIST_MIN_FITNESS:
        return True
    if sharpe >= PERSIST_MIN_SHARPE:
        return True
    return False


def extract_trades(close: np.ndarray, position: np.ndarray) -> list[dict]:
    """Extract per-trade details from position array.
    
    Returns list of:
      {bar_entry, bar_exit, entry_price, exit_price, return_pct, pnl_pct, bars_held}
    """
    trades = []
    in_pos = False
    entry_bar = 0
    entry_price = 0.0

    for i in range(len(close)):
        if not in_pos and position[i] > 0.5:
            in_pos = True
            entry_bar = i
            entry_price = float(close[i])
        elif in_pos and position[i] < 0.5:
            in_pos = False
            exit_price = float(close[i])
            if entry_price > 0:
                ret = (exit_price - entry_price) / entry_price
                trades.append({
                    "bar_entry": int(entry_bar),
                    "bar_exit": int(i),
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(exit_price, 4),
                    "return_pct": round(ret, 6),
                    "bars_held": int(i - entry_bar),
                })

    # Close open position at end
    if in_pos and entry_price > 0:
        exit_price = float(close[-1])
        ret = (exit_price - entry_price) / entry_price
        trades.append({
            "bar_entry": int(entry_bar),
            "bar_exit": int(len(close) - 1),
            "entry_price": round(entry_price, 4),
            "exit_price": round(exit_price, 4),
            "return_pct": round(ret, 6),
            "bars_held": int(len(close) - 1 - entry_bar),
            "open": True,
        })

    return trades


def compute_equity_curve(close: np.ndarray, position: np.ndarray) -> list[float]:
    """Compute cumulative equity curve (returns series).
    
    Downsampled to max 500 points to keep file size reasonable.
    """
    returns = np.diff(close) / close[:-1] * position[:-1]
    equity = np.cumprod(1 + returns)
    
    # Downsample if too long
    if len(equity) > 500:
        step = len(equity) // 500
        equity = equity[::step]
    
    return [round(float(e), 6) for e in equity]


def persist_candidate(
    strategy_code: str,
    style: str,
    params: dict,
    asset: str,
    timeframe: str,
    generation: int,
    metrics: dict,
    mc: dict,
    wf: dict,
    fitness: float,
    tier: str,
    close: np.ndarray,
    position: np.ndarray,
    parent_id: str = "",
    lineage_id: str = "",
    data_bars: int = 0,
) -> Optional[str]:
    """
    Persist full strategy artifact to disk.
    
    Returns: filepath if saved, None if skipped (dedup or threshold).
    """
    # Dedup check
    shash = strategy_hash(params, asset, timeframe)
    filepath = CANDIDATE_DIR / f"{strategy_code}.json"
    
    # Skip if already stored with same hash
    if filepath.exists():
        try:
            existing = json.load(open(filepath))
            if existing.get("hash") == shash:
                log.debug(f"Candidate {strategy_code} already stored (same hash)")
                return None
        except Exception:
            pass  # overwrite corrupt files
    
    # Extract trades
    trades = extract_trades(close, position)
    trade_returns = [t["return_pct"] for t in trades]
    
    # Equity curve
    equity = compute_equity_curve(close, position)
    
    # Build artifact
    artifact = {
        "strategy_code": strategy_code,
        "hash": shash,
        "generation": generation,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        
        # Identity
        "style": style,
        "asset": asset,
        "timeframe": timeframe,
        "parent_id": parent_id,
        "lineage_id": lineage_id,
        
        # Full parameters (reproducibility)
        "parameters": {k: v for k, v in params.items() if not k.startswith("_")},
        
        # Data reference
        "data": {
            "bars": data_bars or int(len(close)),
            "first_close": round(float(close[0]), 4),
            "last_close": round(float(close[-1]), 4),
        },
        
        # Performance summary
        "performance": {
            "sharpe_ratio": metrics.get("sharpe_ratio", 0),
            "max_drawdown": metrics.get("max_drawdown", 0),
            "win_rate": metrics.get("win_rate", 0),
            "profit_factor": metrics.get("profit_factor", 0),
            "total_return_pct": metrics.get("total_return_pct", 0),
            "trade_count": metrics.get("trade_count", 0),
            "avg_profit_capture_pct": metrics.get("avg_profit_capture_pct", 0),
            "target_hit_rate": metrics.get("target_hit_rate", 0),
        },
        
        # Monte Carlo
        "monte_carlo": {
            "mc_mean_return": mc.get("mc_mean_return", 0),
            "mc_worst_dd": mc.get("mc_worst_dd", 0),
        },
        
        # Walk-forward
        "walk_forward": {
            "wf_mean_sharpe": wf.get("wf_mean_sharpe", 0),
            "wf_degradation": wf.get("wf_degradation", 0),
        },
        
        # Scoring
        "fitness": fitness,
        "darwin_tier": tier,
        
        # Full trade log (for production gate MC + prop sim)
        "trades": trades,
        "trade_returns": trade_returns,
        
        # Equity curve (for visualization + regime analysis)
        "equity_curve": equity,
    }
    
    # Write atomically
    tmp = filepath.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(artifact, f, indent=2, default=str)
    tmp.rename(filepath)
    
    # Update index
    _update_index(strategy_code, shash, tier, fitness, metrics.get("sharpe_ratio", 0))
    
    log.info(f"💾 Persisted candidate {strategy_code} ({tier}, fitness={fitness:.3f}, {len(trades)} trades)")
    
    # Free memory
    del trades, trade_returns, equity, artifact
    gc.collect()
    
    return str(filepath)


def _update_index(code: str, shash: str, tier: str, fitness: float, sharpe: float):
    """Update the dedup/lookup index."""
    index = {}
    if INDEX_FILE.exists():
        try:
            index = json.load(open(INDEX_FILE))
        except Exception:
            index = {}
    
    index[code] = {
        "hash": shash,
        "tier": tier,
        "fitness": round(fitness, 4),
        "sharpe": round(sharpe, 4),
        "stored_at": datetime.now(timezone.utc).isoformat(),
    }
    
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f, indent=2)


def load_candidate(strategy_code: str) -> Optional[dict]:
    """Load a persisted candidate artifact."""
    filepath = CANDIDATE_DIR / f"{strategy_code}.json"
    if not filepath.exists():
        return None
    return json.load(open(filepath))


def list_candidates(tier: Optional[str] = None) -> list[dict]:
    """List all persisted candidates, optionally filtered by tier."""
    if not INDEX_FILE.exists():
        return []
    index = json.load(open(INDEX_FILE))
    results = []
    for code, meta in index.items():
        if tier and meta.get("tier") != tier:
            continue
        results.append({"strategy_code": code, **meta})
    return sorted(results, key=lambda x: x.get("fitness", 0), reverse=True)

#!/usr/bin/env python3
"""
Experimental Lane — CL Sandbox

Cheap, fast, high-volume idea testing for CL (Crude Oil).
No full backtests. Quick validation only. Winners get promoted to main backtest lane.

Architecture:
  Experimental Lane (CL) → Validation Gate → Candidate Pool → Backtest Lane

Uses 20% of compute. Never slows the core NQ/GC system.

Owner: Strategist + Scheduler
"""

import json
import copy
import time
import random
import signal
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import sys
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from services.darwin.backtester import load_parquet, run_backtest, BacktestResult

log = logging.getLogger("experimental_lane")
if not log.handlers:
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [🧪 EXPERIMENTAL] %(message)s")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    fh = logging.FileHandler(PROJECT / "data" / "experimental_lane.log")
    fh.setFormatter(fmt)
    log.addHandler(sh)
    log.addHandler(fh)
    log.propagate = False

DATA = PROJECT / "data"
CANDIDATE_DIR = DATA / "candidates" / "cl"
EXPERIMENT_LOG = DATA / "experimental_results.jsonl"
DNA_PATH = PROJECT / "data" / "strategy_dnas_v3.json"

# Promotion criteria
PROMOTION_GATE = {
    "min_sharpe": 1.0,
    "min_trades": 50,
    "max_drawdown": 0.15,
    "min_stability": 0.65,
}

STYLES = ["volume_orderflow", "scalping", "mean_reversion", "momentum_breakout"]
STYLE_WEIGHTS = [40, 30, 20, 10]

BATCH_SIZE = 15  # More ideas per batch (cheap)
SLEEP_BETWEEN = 10  # Faster cycles (lightweight)


def generate_cl_dna(generation: int) -> dict:
    """Generate a CL-specific strategy DNA."""
    style = random.choices(STYLES, weights=STYLE_WEIGHTS, k=1)[0]
    code = f"CL-EXP-G{generation}-{random.randint(10000, 99999)}"
    
    templates = {
        "volume_orderflow": {"parameter_ranges": {"z_score_threshold": [round(random.uniform(1.5, 2.5), 2), round(random.uniform(2.5, 3.5), 2)], "volume_multiplier": [round(random.uniform(1.0, 1.8), 2), round(random.uniform(1.8, 3.0), 2)], "lookback": [random.randint(20, 50), random.randint(50, 100)]}},
        "scalping": {"parameter_ranges": {"rsi_period": [random.randint(3, 7), random.randint(7, 14)], "volume_multiplier": [round(random.uniform(1.0, 1.5), 2), round(random.uniform(1.5, 2.5), 2)], "bb_period": [random.randint(12, 20), random.randint(20, 30)]}},
        "mean_reversion": {"parameter_ranges": {"rsi_threshold": [random.randint(15, 25), random.randint(25, 40)], "rsi_period": [random.randint(5, 10), random.randint(10, 20)], "bb_period": [random.randint(15, 20), random.randint(20, 30)]}},
        "momentum_breakout": {"parameter_ranges": {"fast_ema": [random.randint(5, 15), random.randint(15, 25)], "slow_ema": [random.randint(25, 40), random.randint(40, 60)], "adx_threshold": [random.randint(15, 25), random.randint(25, 40)], "volume_multiplier": [round(random.uniform(1.0, 1.5), 2), round(random.uniform(1.5, 2.5), 2)]}},
    }
    
    base = templates.get(style, templates["volume_orderflow"])
    return {
        "strategy_code": code, "generation": generation, "style": style,
        "regime_filter": {"trend_strength_min": random.randint(18, 28)},
        "risk_reward": {"min_rr": round(random.uniform(1.5, 3.0), 1)},
        "exit_rules": {"partial_tp_1": {"at_r": 1.0, "close_pct": 0.33}, "runner": {"trailing_atr": round(random.uniform(1.5, 3.0), 1)}, "time_limit_bars": random.randint(8, 25)},
        "confidence": 0,
        **base,
    }


def quick_validate(dna: dict, df: pd.DataFrame, n_slices: int = 3) -> Dict:
    """
    Quick validation — run on random data slices, compute stability.
    Cheap and fast. No full backtest.
    """
    total_bars = len(df)
    slice_size = min(total_bars // 4, 5000)  # ~1 week of 5m data per slice
    
    if slice_size < 500:
        return {"passed": False, "reason": "insufficient_data"}
    
    slice_results = []
    
    for i in range(n_slices):
        start = random.randint(0, total_bars - slice_size - 1)
        slice_df = df.iloc[start:start + slice_size]
        
        try:
            result = run_backtest(dna, slice_df)
            slice_results.append({
                "sharpe": result.sharpe_ratio,
                "win_rate": result.win_rate,
                "max_dd": result.max_drawdown,
                "trades": result.trade_count,
                "return_pct": result.total_return_pct,
            })
        except:
            slice_results.append({"sharpe": 0, "win_rate": 0, "max_dd": 1, "trades": 0, "return_pct": 0})
    
    if not slice_results:
        return {"passed": False, "reason": "no_results"}
    
    # Aggregate
    sharpes = [s["sharpe"] for s in slice_results]
    avg_sharpe = np.mean(sharpes)
    total_trades = sum(s["trades"] for s in slice_results)
    max_dd = max(s["max_dd"] for s in slice_results)
    avg_wr = np.mean([s["win_rate"] for s in slice_results])
    
    # Stability score: 1 - variance of sharpe across slices
    if len(sharpes) > 1 and np.std(sharpes) < 10:
        stability = max(0, 1 - np.std(sharpes) / max(abs(avg_sharpe), 0.01))
    else:
        stability = 0
    stability = round(min(stability, 1.0), 3)
    
    # Promotion check
    passed = (
        avg_sharpe >= PROMOTION_GATE["min_sharpe"] and
        total_trades >= PROMOTION_GATE["min_trades"] and
        max_dd <= PROMOTION_GATE["max_drawdown"] and
        stability >= PROMOTION_GATE["min_stability"]
    )
    
    return {
        "passed": passed,
        "sharpe_estimate": round(avg_sharpe, 3),
        "win_rate": round(avg_wr, 3),
        "drawdown": round(max_dd, 4),
        "trade_count": total_trades,
        "stability_score": stability,
        "slice_sharpes": [round(s, 3) for s in sharpes],
    }


def save_candidate(dna: dict, validation: Dict):
    """Save promoted candidate to candidate pool."""
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    candidate = {
        "dna": dna,
        "validation": validation,
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "status": "CANDIDATE",
    }
    path = CANDIDATE_DIR / f"{dna['strategy_code']}.json"
    with open(path, "w") as f:
        json.dump(candidate, f, indent=2, default=str)


def log_result(dna: dict, validation: Dict):
    """Log experimental result."""
    EXPERIMENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "strategy_code": dna["strategy_code"],
        "style": dna.get("style", ""),
        "generation": dna.get("generation", 0),
        **validation,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(EXPERIMENT_LOG, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def run_experimental_cycle(df_5m: pd.DataFrame, df_15m: pd.DataFrame, generation: int) -> Dict:
    """One cycle of the experimental lane."""
    batch_tested = 0
    batch_promoted = 0
    
    for _ in range(BATCH_SIZE):
        dna = generate_cl_dna(generation)
        
        # Pick timeframe randomly
        df = random.choice([df_5m, df_15m])
        
        validation = quick_validate(dna, df)
        batch_tested += 1
        
        log_result(dna, validation)
        
        if validation.get("passed"):
            batch_promoted += 1
            save_candidate(dna, validation)
            log.info(
                f"  🎯 PROMOTED: {dna['strategy_code']} | "
                f"S={validation['sharpe_estimate']:.2f} WR={validation['win_rate']:.0%} "
                f"DD={validation['drawdown']:.1%} Stab={validation['stability_score']:.2f}"
            )
    
    return {"tested": batch_tested, "promoted": batch_promoted}


def main():
    running = True
    def shutdown(signum, frame):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    
    log.info("🧪 EXPERIMENTAL LANE (CL) ONLINE — cheap, fast, high-volume")
    
    # Load CL data
    try:
        df_5m = load_parquet("CL", "5m")
        df_15m = load_parquet("CL", "15m")
        log.info(f"Data loaded: 5m={len(df_5m):,} bars, 15m={len(df_15m):,} bars")
    except Exception as e:
        log.error(f"Failed to load CL data: {e}")
        return
    
    generation = 0
    total_tested = 0
    total_promoted = 0
    
    while running:
        generation += 1
        
        result = run_experimental_cycle(df_5m, df_15m, generation)
        total_tested += result["tested"]
        total_promoted += result["promoted"]
        
        log.info(
            f"Gen {generation}: {result['promoted']}/{result['tested']} promoted | "
            f"Total: {total_tested} tested, {total_promoted} promoted"
        )
        
        for _ in range(SLEEP_BETWEEN):
            if not running:
                break
            time.sleep(1)
    
    log.info(f"🧪 EXPERIMENTAL LANE OFFLINE — {total_tested} tested, {total_promoted} promoted")


if __name__ == "__main__":
    main()

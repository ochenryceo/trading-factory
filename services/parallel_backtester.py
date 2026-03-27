#!/usr/bin/env python3
"""
Parallel Backtester Worker — One of 6 agents (Alpha-Foxtrot)

Each worker focuses on a specific asset/timeframe pair.
All share the same DNA generation, validation pipeline, and output files.
File locking ensures no write conflicts.

Usage: python3 -m services.parallel_backtester --agent alpha
"""

import json
import copy
import time
import random
import signal
import sys
import os
import fcntl
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from services.darwin.backtester import load_parquet, run_backtest, BacktestResult
from services.final_validation import validate_strategy, ValidationTag
from services.deep_inspect import deep_inspect
from services.failure_intelligence import (
    record_darwin_failure, record_validation_failure,
    analyze_failure_patterns, get_avoidance_rules
)
from services.orchestrator import get_orchestrator, EarlyTerminator

# ── Agent Assignments ──────────────────────────────────────────────────────

AGENT_CONFIG = {
    "alpha":   {"asset": "NQ", "timeframes": ["5m", "15m"], "emoji": "🅰️"},
    "bravo":   {"asset": "NQ", "timeframes": ["1h", "4h"],  "emoji": "🅱️"},
    "charlie": {"asset": "GC", "timeframes": ["5m", "15m"], "emoji": "🅲"},
    "delta":   {"asset": "GC", "timeframes": ["1h", "4h"],  "emoji": "🅳"},
    "echo":    {"asset": "CL", "timeframes": ["5m", "15m"], "emoji": "🅴"},
    "foxtrot": {"asset": "CL", "timeframes": ["1h", "4h"],  "emoji": "🅵"},
    "golf":    {"asset": "NQ", "timeframes": ["daily"],      "emoji": "🅶"},
    "hotel":   {"asset": "GC", "timeframes": ["daily"],      "emoji": "🅷"},
    "india":   {"asset": "CL", "timeframes": ["daily"],      "emoji": "🅸"},
    # Scaled agents — duplicates for high-priority assets
    "alpha2":  {"asset": "NQ", "timeframes": ["5m", "15m"], "emoji": "🅰️"},
    "alpha3":  {"asset": "NQ", "timeframes": ["5m", "15m"], "emoji": "🅰️"},
    "bravo2":  {"asset": "NQ", "timeframes": ["1h", "4h"],  "emoji": "🅱️"},
    "charlie2":{"asset": "GC", "timeframes": ["5m", "15m"], "emoji": "🅲"},
    "charlie3":{"asset": "GC", "timeframes": ["5m", "15m"], "emoji": "🅲"},
    "delta2":  {"asset": "GC", "timeframes": ["1h", "4h"],  "emoji": "🅳"},
}

# ── Shared Paths ───────────────────────────────────────────────────────────

DNA_PATH = PROJECT / "data" / "strategy_dnas_v3.json"
RUN_LOG_PATH = PROJECT / "data" / "continuous_run_log.jsonl"
LEADERBOARD_PATH = PROJECT / "data" / "continuous_leaderboard.json"
DNA_ARCHIVE_PATH = PROJECT / "data" / "dna_archive.jsonl"

BATCH_SIZE = 10
SLEEP_BETWEEN_BATCHES = 15  # Faster per-worker since they're specialized

DARWIN_CRITERIA = {
    "min_win_rate": 0.40,
    "min_sharpe": 0.5,
    "max_drawdown": 0.10,
    "min_trades": 20,
    "min_profit_factor": 1.1,
}

MIN_BARS = {"5m": 5000, "15m": 2000, "1h": 500, "4h": 200, "daily": 100}

# Style weights — CEO Policy (2026-03-23)
# Volume orderflow and scalping dominate. Trend/news reduced but alive.
STYLE_WEIGHTS = {
    "volume_orderflow": 40,
    "scalping": 30,
    "mean_reversion": 15,
    "momentum_breakout": 10,
    "trend_following": 3,
    "news_reaction": 2,
}
STYLES_POOL = []
for s, w in STYLE_WEIGHTS.items():
    STYLES_POOL.extend([s] * w)
STYLES = list(STYLE_WEIGHTS.keys())  # keep full list for reference

FINAL_VALIDATION_ENABLED = True


# ── File-safe append ───────────────────────────────────────────────────────

def safe_append(path: Path, line: str):
    """Append a line to a file with file locking."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)


def safe_write_json(path: Path, data: dict):
    """Write JSON with file locking."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(data, f, indent=2, default=str)
        fcntl.flock(f, fcntl.LOCK_UN)


# ── DNA Generation (same as continuous_backtester) ─────────────────────────

def _mid(range_or_val):
    if isinstance(range_or_val, (list, tuple)) and len(range_or_val) == 2:
        return (float(range_or_val[0]) + float(range_or_val[1])) / 2
    return float(range_or_val) if range_or_val else 0.0


def mutate_dna(dna: dict, generation: int) -> dict:
    mutant = copy.deepcopy(dna)
    base_code = dna["strategy_code"].split("-mut")[0]
    mutant["strategy_code"] = f"{base_code}-mut{generation}-{random.randint(1000, 9999)}"
    mutant["generation"] = generation
    mutant["parent"] = dna["strategy_code"]
    
    params = mutant.get("parameter_ranges", {})
    for key, value in params.items():
        if random.random() < 0.3:
            if isinstance(value, (list, tuple)) and len(value) == 2:
                lo, hi = float(value[0]), float(value[1])
                delta = random.uniform(-0.20, 0.20)
                params[key] = [max(1, lo * (1 + delta)), max(lo * (1 + delta) + 1, hi * (1 + delta))]
            elif isinstance(value, (int, float)):
                params[key] = max(1, value * (1 + random.uniform(-0.20, 0.20)))
    return mutant


def generate_random_dna(generation: int) -> dict:
    style = random.choice(STYLES_POOL)  # weighted selection per CEO policy
    code = f"RND-G{generation}-{random.randint(10000, 99999)}"
    
    templates = {
        "momentum_breakout": {"parameter_ranges": {"fast_ema": [random.randint(8, 20), random.randint(20, 35)], "slow_ema": [random.randint(30, 50), random.randint(50, 80)], "adx_threshold": [random.randint(15, 25), random.randint(25, 40)], "volume_multiplier": [round(random.uniform(1.0, 1.5), 2), round(random.uniform(1.5, 2.5), 2)]}},
        "mean_reversion": {"parameter_ranges": {"rsi_threshold": [random.randint(15, 25), random.randint(25, 40)], "rsi_period": [random.randint(7, 14), random.randint(14, 21)], "bb_period": [random.randint(15, 20), random.randint(20, 30)]}},
        "trend_following": {"parameter_ranges": {"fast_ema": [random.randint(10, 20), random.randint(20, 30)], "slow_ema": [random.randint(35, 50), random.randint(50, 70)], "adx_threshold": [random.randint(15, 22), random.randint(22, 35)]}},
        "scalping": {"parameter_ranges": {"rsi_period": [5, 10], "volume_multiplier": [round(random.uniform(1.0, 1.5), 2), round(random.uniform(1.5, 2.5), 2)], "bb_period": [random.randint(15, 20), random.randint(20, 25)]}},
        "volume_orderflow": {"parameter_ranges": {"z_score_threshold": [round(random.uniform(1.5, 2.0), 2), round(random.uniform(2.0, 3.0), 2)], "volume_multiplier": [round(random.uniform(1.0, 1.5), 2), round(random.uniform(1.5, 2.5), 2)], "lookback": [random.randint(30, 50), random.randint(50, 80)]}},
    }
    
    base = templates.get(style, templates["momentum_breakout"])
    return {
        "strategy_code": code, "generation": generation, "style": style,
        "regime_filter": {"trend_strength_min": random.randint(20, 30)},
        "risk_reward": {"min_rr": round(random.uniform(1.5, 3.0), 1)},
        "exit_rules": {"partial_tp_1": {"at_r": 1.0, "close_pct": 0.33}, "runner": {"trailing_atr": round(random.uniform(1.5, 3.0), 1)}, "time_limit_bars": random.randint(10, 30)},
        "confidence": 0,
        **base,
    }


# ── Worker Main Loop ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", required=True, choices=AGENT_CONFIG.keys())
    args = parser.parse_args()
    
    agent_name = args.agent
    config = AGENT_CONFIG[agent_name]
    asset = config["asset"]
    timeframes = config["timeframes"]
    emoji = config["emoji"]
    
    # Setup logging
    log = logging.getLogger(f"agent_{agent_name}")
    if not log.handlers:
        log.setLevel(logging.INFO)
        fmt = logging.Formatter(f"%(asctime)s [{agent_name.upper()}] %(message)s")
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        fh = logging.FileHandler(PROJECT / "data" / f"agent_{agent_name}.log")
        fh.setFormatter(fmt)
        log.addHandler(sh)
        log.addHandler(fh)
        log.propagate = False
    
    running = True
    def shutdown(signum, frame):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    
    # Load base DNAs
    with open(DNA_PATH) as f:
        base_dnas = json.load(f)
    
    log.info(f"{emoji} Agent {agent_name.upper()} started — {asset} {timeframes}")
    
    # Initialize orchestrator
    try:
        orch = get_orchestrator()
    except:
        orch = None
    
    generation = 0
    total_tested = 0
    total_passed = 0
    early_killed = 0
    
    while running:
        generation += 1
        
        # Generate batch
        batch = []
        for _ in range(int(BATCH_SIZE * 0.6)):
            batch.append(mutate_dna(random.choice(base_dnas), generation))
        for _ in range(BATCH_SIZE - len(batch)):
            batch.append(generate_random_dna(generation))
        
        batch_passed = 0
        
        for dna in batch:
            if not running:
                break
            
            # Archive DNA
            safe_append(DNA_ARCHIVE_PATH, json.dumps(dna, default=str))
            
            for tf in timeframes:
                if not running:
                    break
                
                try:
                    df = load_parquet(asset, tf)
                    if len(df) < MIN_BARS.get(tf, 100):
                        continue
                    
                    result = run_backtest(dna, df)
                    total_tested += 1
                    
                    # Early termination — kill weak strategies fast
                    early_metrics = {
                        "trade_count": result.trade_count,
                        "sharpe_ratio": result.sharpe_ratio,
                        "win_rate": result.win_rate,
                        "max_drawdown": result.max_drawdown,
                        "expectancy": result.expectancy,
                    }
                    if EarlyTerminator.should_terminate(early_metrics):
                        early_killed += 1
                        continue  # Skip — conserve compute
                    
                    metrics = {
                        "strategy_code": dna["strategy_code"],
                        "asset": asset, "timeframe": tf,
                        "style": dna.get("style", ""),
                        "generation": generation,
                        "parent": dna.get("parent", ""),
                        "trade_count": result.trade_count,
                        "win_rate": result.win_rate,
                        "sharpe_ratio": result.sharpe_ratio,
                        "max_drawdown": result.max_drawdown,
                        "profit_factor": result.profit_factor,
                        "total_return_pct": result.total_return_pct,
                        "expectancy": result.expectancy,
                        "avg_rr": result.avg_rr,
                        "wins": result.wins,
                        "losses": result.losses,
                        "agent": agent_name,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    
                    # Darwin check
                    passed = (
                        result.trade_count >= DARWIN_CRITERIA["min_trades"] and
                        result.win_rate >= DARWIN_CRITERIA["min_win_rate"] and
                        result.sharpe_ratio >= DARWIN_CRITERIA["min_sharpe"] and
                        result.max_drawdown <= DARWIN_CRITERIA["max_drawdown"] and
                        result.profit_factor >= DARWIN_CRITERIA["min_profit_factor"]
                    )
                    
                    metrics["passed_darwin"] = passed
                    safe_append(RUN_LOG_PATH, json.dumps(metrics, default=str))
                    
                    if passed:
                        batch_passed += 1
                        total_passed += 1
                        log.info(
                            f"🏆 DARWIN: {dna['strategy_code'][:30]} {asset}/{tf} "
                            f"S={result.sharpe_ratio:.2f} WR={result.win_rate:.0%} DD={result.max_drawdown:.1%}"
                        )
                        
                        # Final validation
                        if FINAL_VALIDATION_ENABLED:
                            try:
                                fv = validate_strategy(dna, asset, tf)
                                if fv.tag == ValidationTag.READY_FOR_PAPER:
                                    log.info(f"  🟢 READY_FOR_PAPER")
                                elif fv.tag == "READY_FOR_PAPER_SUSPICIOUS":
                                    log.info(f"  🟡 SUSPICIOUS — needs review")
                                else:
                                    log.info(f"  🔴 {fv.tag}")
                                    try:
                                        record_validation_failure(dna, asset, fv)
                                    except:
                                        pass
                            except Exception as e:
                                log.debug(f"  FV error: {e}")
                    else:
                        try:
                            record_darwin_failure(dna, asset, metrics)
                        except:
                            pass
                            
                except Exception as e:
                    log.debug(f"Backtest error {dna['strategy_code']} {asset}/{tf}: {e}")
        
        log.info(
            f"Gen {generation}: {batch_passed} passed, {early_killed} early-killed | "
            f"Total: {total_tested} tested, {total_passed} Darwin pass"
        )
        
        # Save orchestrator state periodically
        if orch and generation % 5 == 0:
            try:
                orch.save()
            except:
                pass
        
        # Sleep between batches with jitter to prevent synchronized CPU spikes
        jitter = random.uniform(0, 15)  # 0-15s random offset
        sleep_total = SLEEP_BETWEEN_BATCHES + jitter
        for _ in range(int(sleep_total)):
            if not running:
                break
            time.sleep(1)
    
    log.info(f"{emoji} Agent {agent_name.upper()} stopped — {total_tested} tested, {total_passed} passed")


if __name__ == "__main__":
    main()

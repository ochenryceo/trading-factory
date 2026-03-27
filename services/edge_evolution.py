#!/usr/bin/env python3
"""
Edge Evolution System — Automatic Winning Strategy Mutation

Takes strategies that passed the full pipeline, creates mutations,
re-tests them, keeps the best variants. Turns 1 edge → 10 improved versions.

Flow: Winning Strategy → Clone → Mutate → Re-test → Keep best

Runs as a daemon on Machine A. Reads winners, generates evolved variants,
dispatches to Machine B for testing.

Owner: Strategist + Scheduler + Darwin
"""

import json
import copy
import time
import random
import signal
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any

import sys
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from services.darwin.backtester import run_backtest, load_parquet
from services.final_validation import validate_strategy, ValidationTag

log = logging.getLogger("edge_evolution")
if not log.handlers:
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [🧬 EVOLUTION] %(message)s")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    fh = logging.FileHandler(PROJECT / "data" / "edge_evolution.log")
    fh.setFormatter(fmt)
    log.addHandler(sh)
    log.addHandler(fh)
    log.propagate = False

DATA = PROJECT / "data"
EVOLUTION_LOG = DATA / "evolution_results.jsonl"
EVOLVED_STRATEGIES = DATA / "evolved_strategies.json"

# Evolution parameters
MUTATIONS_PER_WINNER = 10
PARAM_MUTATION_RANGE = 0.08  # ±8% — tighter than discovery (precision refinement)
CYCLE_INTERVAL = 600  # 10 minutes between evolution cycles


def get_winners() -> List[Dict]:
    """Get strategies that passed READY_FOR_PAPER with realistic metrics."""
    winners = []
    seen = set()
    
    fv_path = DATA / "final_validation_log.jsonl"
    if not fv_path.exists():
        return winners
    
    with open(fv_path) as f:
        for line in f:
            try:
                d = json.loads(line.strip())
                if d.get("tag") != "READY_FOR_PAPER":
                    continue
                code = d.get("strategy_code", "")
                if code in seen:
                    continue
                
                sr = d.get("baseline_sharpe", 0)
                wr = d.get("baseline_win_rate", 0)
                dd = d.get("baseline_max_dd", 0)
                
                # Only evolve realistic strategies
                if 0.8 <= sr <= 3.0 and 0.45 <= wr <= 0.75 and 0.02 <= dd <= 0.12:
                    seen.add(code)
                    winners.append(d)
            except:
                continue
    
    # Sort by sharpe, take top 20
    winners.sort(key=lambda x: -x.get("baseline_sharpe", 0))
    return winners[:20]


def find_dna(strategy_code: str) -> Dict:
    """Find the DNA for a strategy from the archive."""
    archive_path = DATA / "dna_archive.jsonl"
    if not archive_path.exists():
        return {}
    
    with open(archive_path) as f:
        for line in f:
            try:
                d = json.loads(line.strip())
                if d.get("strategy_code") == strategy_code:
                    return d
            except:
                continue
    return {}


def evolve_dna(dna: Dict, evolution_id: int) -> Dict:
    """Create a precision mutation — tighter than discovery mutations."""
    evolved = copy.deepcopy(dna)
    parent_code = dna.get("strategy_code", "UNKNOWN")
    evolved["strategy_code"] = f"{parent_code}-evo{evolution_id}"
    evolved["parent"] = parent_code
    evolved["evolution_generation"] = evolution_id
    evolved["evolved_at"] = datetime.now(timezone.utc).isoformat()
    
    params = evolved.get("parameter_ranges", {})
    for key, val in params.items():
        if random.random() < 0.5:  # mutate 50% of params
            if isinstance(val, (list, tuple)) and len(val) == 2:
                try:
                    lo, hi = float(val[0]), float(val[1])
                    shift = random.uniform(-PARAM_MUTATION_RANGE, PARAM_MUTATION_RANGE)
                    params[key] = [round(lo * (1 + shift), 4), round(hi * (1 + shift), 4)]
                except:
                    pass
            elif isinstance(val, (int, float)):
                try:
                    shift = random.uniform(-PARAM_MUTATION_RANGE, PARAM_MUTATION_RANGE)
                    new_val = val * (1 + shift)
                    params[key] = int(round(new_val)) if isinstance(val, int) else round(new_val, 4)
                except:
                    pass
    
    # Occasionally mutate exit rules too
    exit_rules = evolved.get("exit_rules", {})
    if random.random() < 0.3:
        runner = exit_rules.get("runner", {})
        if "trailing_atr" in runner:
            runner["trailing_atr"] = round(runner["trailing_atr"] * (1 + random.uniform(-0.05, 0.05)), 2)
        if "time_limit_bars" in exit_rules:
            exit_rules["time_limit_bars"] = max(5, exit_rules["time_limit_bars"] + random.choice([-1, 0, 1]))
    
    return evolved


def run_evolution_cycle():
    """One cycle: find winners, evolve, test, keep best."""
    log.info("━━━ EVOLUTION CYCLE START ━━━")
    
    winners = get_winners()
    if not winners:
        log.info("No winners to evolve yet")
        return
    
    log.info(f"Found {len(winners)} winners to evolve")
    
    total_evolved = 0
    total_improved = 0
    
    for winner in winners[:5]:  # Evolve top 5 per cycle
        code = winner.get("strategy_code", "?")
        asset = winner.get("asset", "NQ")
        baseline_sharpe = winner.get("baseline_sharpe", 0)
        
        # Find original DNA
        dna = find_dna(code)
        if not dna:
            # Try to find parent DNA
            parent = code.rsplit("-clone", 1)[0] if "-clone" in code else code
            dna = find_dna(parent)
        if not dna:
            continue
        
        log.info(f"  Evolving {code} (S={baseline_sharpe:.2f})...")
        
        best_evolved = None
        best_sharpe = baseline_sharpe
        
        for i in range(MUTATIONS_PER_WINNER):
            evolved = evolve_dna(dna, i + 1)
            total_evolved += 1
            
            try:
                # Quick backtest
                df = load_parquet(asset, "daily")
                result = run_backtest(evolved, df)
                
                if result.sharpe_ratio > best_sharpe and result.win_rate >= 0.40 and result.max_drawdown <= 0.12:
                    best_sharpe = result.sharpe_ratio
                    best_evolved = {
                        "strategy_code": evolved["strategy_code"],
                        "parent": code,
                        "asset": asset,
                        "sharpe": result.sharpe_ratio,
                        "win_rate": result.win_rate,
                        "max_dd": result.max_drawdown,
                        "return_pct": result.total_return_pct,
                        "improvement": round(result.sharpe_ratio - baseline_sharpe, 3),
                    }
            except:
                continue
        
        if best_evolved and best_evolved["improvement"] > 0:
            total_improved += 1
            log.info(f"    🔥 IMPROVED: {best_evolved['strategy_code']} S={best_evolved['sharpe']:.2f} (+{best_evolved['improvement']:.3f})")
            
            # Log evolution result
            EVOLUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(EVOLUTION_LOG, "a") as f:
                f.write(json.dumps({**best_evolved, "timestamp": datetime.now(timezone.utc).isoformat()}, default=str) + "\n")
        else:
            log.info(f"    No improvement found for {code}")
    
    log.info(f"  Cycle: {total_evolved} variants tested, {total_improved} improved")
    log.info("━━━ EVOLUTION CYCLE COMPLETE ━━━")


def main():
    running = True
    def shutdown(signum, frame):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    
    log.info("🧬 EDGE EVOLUTION SYSTEM ONLINE")
    
    while running:
        try:
            run_evolution_cycle()
        except Exception as e:
            log.error(f"Evolution cycle error: {e}")
        
        for _ in range(CYCLE_INTERVAL):
            if not running:
                break
            time.sleep(1)
    
    log.info("🧬 EDGE EVOLUTION SYSTEM OFFLINE")


if __name__ == "__main__":
    main()

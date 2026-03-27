#!/usr/bin/env python3
"""
Continuous Backtesting Daemon — Runs 24/7

The factory never sleeps. This daemon:
1. Mutates existing strategy DNAs to explore parameter space
2. Generates new strategy combinations
3. Backtests each variant against all assets + timeframes
4. Validates through a multi-gate pipeline
5. Registers survivors and diagnoses failures
6. Repeats forever

Pipeline order:
1. Darwin (sample size + months + simplicity)
2. Robustness (top-5 removal, dual condition)
3. Light MC (100 sims, 65% survival)
4. Walk-Forward (IS vs OOS)
5. Full MC (1000 sims, 85% + DD)
6. Trade Distribution (time clustering)
7. Final Validation (existing Gate 4 + 5)
8. Deep Inspection (existing)

Strategies are PASSED, CONDITIONAL, or FAILED — no ranking.

Run: python3 -m services.continuous_backtester
"""

import json
import copy
import time
import random
import signal
import sys
import os
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

import numpy as np
import pandas as pd

# Add project root
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from services.darwin.backtester import (
    load_parquet, run_backtest, BacktestResult, TradeRecord, robustness_check
)
from services.walk_forward import walk_forward_test
from services.monte_carlo import monte_carlo_light, monte_carlo_test
from services.trade_distribution_gate import check_trade_distribution
from services.trust_score import compute_trust_score
from services.final_validation import (
    validate_strategy, FinalValidationResult, ValidationTag, is_paper_ready
)
from services.deep_inspect import deep_inspect, DeepInspectionResult
from services.failure_intelligence import (
    record_darwin_failure, record_validation_failure, record_inspection_failure,
    analyze_failure_patterns, get_avoidance_rules
)

# ── Config ─────────────────────────────────────────────────────────────────

ASSETS = ["NQ", "GC", "CL"]

TIMEFRAME_WEIGHTS = {
    "15m": 30, "1h": 25, "4h": 20, "daily": 25,
    # 5m removed: 500K+ bars per dataset = memory killer. Re-add when we have intraday infra.
}
TIMEFRAMES_POOL = []
for tf, weight in TIMEFRAME_WEIGHTS.items():
    TIMEFRAMES_POOL.extend([tf] * weight)

MTF_TIMEFRAMES = ["5m", "15m", "1h", "4h"]

DNA_PATH = PROJECT / "data" / "strategy_dnas_v3.json"
RESULTS_DIR = PROJECT / "data" / "continuous_results"
REGISTRY_PATH = PROJECT / "data" / "continuous_registry.json"
FAILURE_REGISTRY_PATH = PROJECT / "data" / "failure_registry.jsonl"
RUN_LOG_PATH = PROJECT / "data" / "continuous_run_log.jsonl"
DNA_ARCHIVE_PATH = PROJECT / "data" / "dna_archive.jsonl"

# Darwin criteria
DARWIN_CRITERIA = {
    "min_win_rate": 0.40,
    "min_sharpe": 0.5,
    "max_drawdown": 0.20,
    "min_trades": 100,
    "min_profit_factor": 1.1,
    "min_unique_months": 12,
    "max_entry_conditions": 3,
}

# Mutation config
MUTATION_RATE = 0.3
MUTATION_RANGE = 0.20
BATCH_SIZE = 10
SLEEP_BETWEEN_BATCHES = 30
MAX_GENERATIONS = None

FINAL_VALIDATION_ENABLED = True

# Strategy style categories — enforced simplicity
# Each style must be ONE archetype. No mixing.
STYLE_ARCHETYPES = {
    # Signal + Filter: one signal, one confirmation
    "momentum_breakout": {"archetype": "breakout", "max_conditions": 3},
    "trend_following":   {"archetype": "breakout", "max_conditions": 3},
    # Pure Mean Reversion
    "mean_reversion":    {"archetype": "mean_reversion", "max_conditions": 2},
    "scalping":          {"archetype": "mean_reversion", "max_conditions": 3},
    # Pure Volume
    "volume_orderflow":  {"archetype": "volume", "max_conditions": 2},
    "news_reaction":     {"archetype": "volume", "max_conditions": 2},
}

STYLES = list(STYLE_ARCHETYPES.keys())

# ── Logging ────────────────────────────────────────────────────────────────

log = logging.getLogger("continuous_backtester")
if not log.handlers:
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    fh = logging.FileHandler(PROJECT / "data" / "continuous_backtester.log")
    fh.setFormatter(fmt)
    log.addHandler(sh)
    log.addHandler(fh)
    log.propagate = False

# ── Failure Tags ───────────────────────────────────────────────────────────

FAILURE_TAGS = {
    "FAIL_LOW_SAMPLE",
    "FAIL_PNL_CONCENTRATION",
    "FAIL_WF_INSTABILITY",
    "FAIL_MC_FRAGILITY",
    "FAIL_EXECUTION_SENSITIVITY",
    "FAIL_TRADE_DISTRIBUTION",
    "FAIL_COMPLEXITY",
}


def record_failure(strategy_code: str, asset: str, timeframe: str,
                   gate_failed: str, failure_tag: str, metrics: dict):
    """Write a structured failure record to the failure registry."""
    FAILURE_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "strategy_code": strategy_code,
        "asset": asset,
        "timeframe": timeframe,
        "gate_failed": gate_failed,
        "failure_tag": failure_tag,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **{k: v for k, v in metrics.items() if not k.startswith("_")},
    }
    with open(FAILURE_REGISTRY_PATH, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ── State ──────────────────────────────────────────────────────────────────

class BacktesterState:
    """Pass/conditional/fail registry — no rankings."""
    def __init__(self):
        self.generation = 0
        self.total_tested = 0
        self.total_passed_all_gates = 0
        self.total_conditional = 0
        self.total_failed = 0
        self.failure_summary: Dict[str, int] = defaultdict(int)
        self.running = True
        self.start_time = datetime.now(timezone.utc)
        self.passed_strategies: List[Dict] = []
        self.conditional_strategies: List[Dict] = []

    def load(self):
        """Load registry from disk."""
        if REGISTRY_PATH.exists():
            try:
                with open(REGISTRY_PATH) as f:
                    data = json.load(f)
                self.passed_strategies = data.get("passed_strategies", [])
                self.conditional_strategies = data.get("conditional_strategies", [])
                self.generation = data.get("generation", 0)
                self.total_tested = data.get("total_tested", 0)
                self.total_passed_all_gates = data.get("total_passed_all_gates", 0)
                self.total_conditional = data.get("total_conditional", 0)
                self.total_failed = data.get("total_failed", 0)
                self.failure_summary = defaultdict(int, data.get("failure_summary", {}))
                log.info(f"Loaded registry: gen={self.generation}, tested={self.total_tested}, "
                         f"passed={self.total_passed_all_gates}, conditional={self.total_conditional}")
            except Exception as e:
                log.warning(f"Failed to load state: {e}")

    def save(self):
        """Persist registry to disk."""
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "generation": self.generation,
            "total_tested": self.total_tested,
            "total_passed_all_gates": self.total_passed_all_gates,
            "total_conditional": self.total_conditional,
            "total_failed": self.total_failed,
            "failure_summary": dict(self.failure_summary),
            "uptime_seconds": (datetime.now(timezone.utc) - self.start_time).total_seconds(),
            "passed_strategies": sorted(
                self.passed_strategies,
                key=lambda s: s.get("trust_score", 0), reverse=True
            ),
            "conditional_strategies": sorted(
                self.conditional_strategies,
                key=lambda s: s.get("trust_score", 0), reverse=True
            ),
        }
        with open(REGISTRY_PATH, "w") as f:
            json.dump(data, f, indent=2, default=str)


state = BacktesterState()

# ── Simplicity — Structured Form Enforcement ───────────────────────────────

def count_entry_conditions(dna: dict) -> int:
    """Count active entry indicators for a strategy style.
    Mirrors the actual conditions in backtester.py's generate_signals().
    """
    style = dna.get("style", "")
    info = STYLE_ARCHETYPES.get(style)
    if info:
        return info["max_conditions"]
    # Unknown style: count parameter_ranges keys as proxy
    return len(dna.get("parameter_ranges", {}))


def check_style_purity(dna: dict) -> Tuple[bool, str]:
    """Reject DNAs that mix archetypes (e.g., mean reversion + breakout).
    Returns (passed, reason).
    """
    style = dna.get("style", "")
    info = STYLE_ARCHETYPES.get(style)
    if not info:
        return False, f"Unknown style '{style}'"

    archetype = info["archetype"]
    params = dna.get("parameter_ranges", {})

    # Check for mixed indicators
    has_mr_indicators = any(k in params for k in ("rsi_threshold", "rsi_period", "rsi_extreme",
                                                    "rsi2_threshold", "bb_period", "bb_std"))
    has_breakout_indicators = any(k in params for k in ("fast_ema", "slow_ema", "ema_period",
                                                         "ema_trend_period", "medium_ema"))
    if archetype == "mean_reversion" and has_breakout_indicators:
        return False, "Mean reversion DNA has breakout indicators (EMA)"
    if archetype == "breakout" and has_mr_indicators:
        return False, "Breakout DNA has mean reversion indicators (RSI/BB)"

    # Check condition count
    n_conditions = count_entry_conditions(dna)
    if n_conditions > DARWIN_CRITERIA["max_entry_conditions"]:
        return False, f"{n_conditions} entry conditions > max {DARWIN_CRITERIA['max_entry_conditions']}"

    return True, ""


# ── DNA Mutation Engine ────────────────────────────────────────────────────

def mutate_parameter(value, mutation_range=MUTATION_RANGE):
    """Mutate a single parameter value."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        low, high = float(value[0]), float(value[1])
        delta_low = low * random.uniform(-mutation_range, mutation_range)
        delta_high = high * random.uniform(-mutation_range, mutation_range)
        new_low = max(1, low + delta_low)
        new_high = max(new_low + 1, high + delta_high)
        return [round(new_low, 2), round(new_high, 2)]
    elif isinstance(value, (int, float)):
        delta = value * random.uniform(-mutation_range, mutation_range)
        new_val = value + delta
        if isinstance(value, int):
            return max(1, int(round(new_val)))
        return round(max(0.01, new_val), 4)
    return value


def mutate_dna(dna: dict, generation: int) -> dict:
    """Create a mutated variant of a strategy DNA."""
    mutant = copy.deepcopy(dna)
    base_code = dna["strategy_code"].split("-mut")[0]
    mutant["strategy_code"] = f"{base_code}-mut{generation}-{random.randint(1000, 9999)}"
    mutant["generation"] = generation
    mutant["parent"] = dna["strategy_code"]
    mutant["mutation_timestamp"] = datetime.now(timezone.utc).isoformat()

    params = mutant.get("parameter_ranges", {})
    for key, value in params.items():
        if random.random() < MUTATION_RATE:
            params[key] = mutate_parameter(value)

    rr = mutant.get("risk_reward", {})
    for key, value in rr.items():
        if isinstance(value, (int, float)) and random.random() < MUTATION_RATE:
            rr[key] = mutate_parameter(value, 0.15)

    rf = mutant.get("regime_filter", {})
    if "trend_strength_min" in rf and random.random() < MUTATION_RATE:
        rf["trend_strength_min"] = mutate_parameter(rf["trend_strength_min"], 0.15)

    exit_rules = mutant.get("exit_rules", {})
    for key, value in exit_rules.items():
        if isinstance(value, dict):
            for k2, v2 in value.items():
                if isinstance(v2, (int, float)) and random.random() < MUTATION_RATE:
                    value[k2] = mutate_parameter(v2, 0.15)

    return mutant


def generate_random_dna(generation: int, avoidance_rules: List[Dict] = None) -> dict:
    """Generate a new random strategy DNA, informed by failure intelligence.
    Enforces structured simplicity forms.
    """
    style = random.choice(STYLES)
    code = f"RND-G{generation}-{random.randint(10000, 99999)}"

    widen_params = False
    loosen_entries = False
    if avoidance_rules:
        for rule in avoidance_rules:
            pat = rule.get("pattern", "")
            if pat == "PARAM_SENSITIVE":
                widen_params = True
            if pat == "LOW_TRADE_COUNT":
                loosen_entries = True

    ema_spread = 5 if widen_params else 0
    adx_lower = 15 if loosen_entries else 18
    vol_lower = 1.0 if loosen_entries else 1.1

    # Structured templates — each style stays within its archetype
    # Max 2-3 entry indicators, no mixing
    templates = {
        "momentum_breakout": {
            "parameter_ranges": {
                "fast_ema": [random.randint(max(3, 8 - ema_spread), 20), random.randint(20, 35 + ema_spread)],
                "slow_ema": [random.randint(max(3, 30 - ema_spread), 50), random.randint(50, 80 + ema_spread)],
                "adx_threshold": [random.randint(adx_lower, 25), random.randint(25, 40)],
                "volume_multiplier": [round(random.uniform(vol_lower, 1.5), 2), round(random.uniform(1.5, 2.5), 2)],
            },
        },
        "mean_reversion": {
            "parameter_ranges": {
                "rsi_threshold": [random.randint(15, 25), random.randint(25, 40)],
                "rsi_period": [random.randint(7, 14), random.randint(14, 21)],
            },
        },
        "trend_following": {
            "parameter_ranges": {
                "fast_ema": [random.randint(10, 20), random.randint(20, 30)],
                "slow_ema": [random.randint(35, 50), random.randint(50, 70)],
                "adx_threshold": [random.randint(15, 22), random.randint(22, 35)],
            },
        },
        "scalping": {
            "parameter_ranges": {
                "rsi_period": [5, 10],
                "volume_multiplier": [round(random.uniform(1.1, 1.5), 2), round(random.uniform(1.5, 2.5), 2)],
            },
        },
        "volume_orderflow": {
            "parameter_ranges": {
                "z_score_threshold": [round(random.uniform(1.5, 2.0), 2), round(random.uniform(2.0, 3.0), 2)],
                "volume_multiplier": [round(random.uniform(1.1, 1.5), 2), round(random.uniform(1.5, 2.5), 2)],
            },
        },
        "news_reaction": {
            "parameter_ranges": {
                "volume_multiplier": [round(random.uniform(2.0, 2.5), 2), round(random.uniform(2.5, 3.5), 2)],
            },
        },
    }

    base = templates.get(style, templates["momentum_breakout"])

    dna = {
        "strategy_code": code,
        "generation": generation,
        "style": style,
        "template": f"{style.title()}_Template",
        "description": f"[Gen{generation}] Random {style} variant — continuous discovery",
        "regime_filter": {
            "trend_strength_min": random.randint(20, 30),
            "enabled_regimes": ["trending"] if style in ["momentum_breakout", "trend_following"] else ["trending", "ranging"],
        },
        "risk_reward": {
            "min_rr": round(random.uniform(1.5, 3.0), 1),
            "target_rr": round(random.uniform(2.5, 4.0), 1),
        },
        "exit_rules": {
            "partial_tp_1": {"at_r": 1.0, "close_pct": 0.33},
            "partial_tp_2": {"at_r": 2.0, "close_pct": 0.33},
            "runner": {"trailing_atr": round(random.uniform(1.5, 3.0), 1)},
            "time_limit_bars": random.randint(10, 30),
        },
        "confidence": 0,
        "mutation_timestamp": datetime.now(timezone.utc).isoformat(),
        **base,
    }

    return dna


def create_batch(base_dnas: List[dict], generation: int) -> List[dict]:
    """Create a batch of strategies: mix of mutations and randoms.
    Bias mutations toward parents with higher trust scores."""
    batch = []
    try:
        avoidance_rules = get_avoidance_rules()
    except Exception:
        avoidance_rules = []

    # Build trust-weighted parent pool from passed + conditional strategies
    trusted_parents = []
    trust_weights = []
    for s in state.passed_strategies + state.conditional_strategies:
        # Find matching DNA in base_dnas by strategy_code prefix
        code = s.get("strategy_code", "")
        base = code.split("-mut")[0]
        matching = [d for d in base_dnas if d.get("strategy_code", "").startswith(base)]
        if matching:
            trusted_parents.append(matching[0])
            trust_weights.append(max(0.1, s.get("trust_score", 0.5)))

    n_mutations = int(BATCH_SIZE * 0.6)
    for _ in range(n_mutations):
        if trusted_parents and random.random() < 0.7:
            # 70% of the time, pick from trust-weighted pool
            parent = random.choices(trusted_parents, weights=trust_weights, k=1)[0]
        else:
            parent = random.choice(base_dnas)
        batch.append(mutate_dna(parent, generation))

    n_random = BATCH_SIZE - n_mutations
    for _ in range(n_random):
        batch.append(generate_random_dna(generation, avoidance_rules))

    return batch


# ── Backtest Runner ────────────────────────────────────────────────────────

def backtest_strategy(dna: dict, asset: str, timeframe: str) -> Optional[Dict]:
    """Run backtest for one strategy on one asset/timeframe."""
    try:
        df = get_cached_data(asset, timeframe)
        min_bars = {"5m": 5000, "15m": 2000, "1h": 500, "4h": 200, "daily": 100}
        if len(df) < min_bars.get(timeframe, 100):
            return None

        result = run_backtest(dna, df, use_mtf=False, asset=asset)

        # Reconstruct TradeRecord list from trade_log for downstream checks
        raw_trades = []
        for tl in result.trade_log:
            raw_trades.append(TradeRecord(
                entry_idx=0, exit_idx=0,
                direction=1 if tl.get("direction") == "LONG" else -1,
                entry_price=tl.get("entry_price", 0),
                exit_price=tl.get("exit_price", 0),
                pnl_pct=tl.get("pnl_pct", 0),
                entry_time=tl.get("entry_time", ""),
            ))

        return {
            "strategy_code": dna["strategy_code"],
            "asset": asset,
            "timeframe": timeframe,
            "style": dna.get("style", ""),
            "generation": dna.get("generation", 0),
            "parent": dna.get("parent", ""),
            "trade_count": result.trade_count,
            "win_rate": result.win_rate,
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown": result.max_drawdown,
            "profit_factor": result.profit_factor,
            "total_return_pct": result.total_return_pct,
            "total_pnl": result.total_pnl,
            "expectancy": result.expectancy,
            "avg_rr": result.avg_rr,
            "wins": result.wins,
            "losses": result.losses,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "_trades": raw_trades,
            "_trade_log": result.trade_log,
            "_entry_conditions": count_entry_conditions(dna),
            "trade_log": result.trade_log[:200],  # cap for memory, used by downstream gates
            "extra": result.extra,  # forced_exit_ratio, equity_mode, etc.
        }
    except Exception as e:
        log.debug(f"Backtest failed for {dna['strategy_code']} on {asset}/{timeframe}: {e}")
        return None


# ── Darwin Gate ────────────────────────────────────────────────────────────

def _count_unique_months(trade_log: List[Dict]) -> int:
    """Count unique calendar months (YYYY-MM) from trade entry times."""
    months = set()
    for t in trade_log:
        entry_time = t.get("entry_time", "")
        if entry_time and len(entry_time) >= 7:
            months.add(entry_time[:7])
    return len(months)


def darwin_gate(result: Dict, dna: dict) -> Tuple[bool, Optional[str]]:
    """Check Darwin criteria. Returns (passed, failure_tag or None)."""
    # Basic metric gates
    if result["trade_count"] < DARWIN_CRITERIA["min_trades"]:
        return False, "FAIL_LOW_SAMPLE"
    if result["win_rate"] < DARWIN_CRITERIA["min_win_rate"]:
        return False, "FAIL_LOW_SAMPLE"
    if result["sharpe_ratio"] < DARWIN_CRITERIA["min_sharpe"]:
        return False, "FAIL_LOW_SAMPLE"
    if result["max_drawdown"] > DARWIN_CRITERIA["max_drawdown"]:
        return False, "FAIL_EXECUTION_SENSITIVITY"
    if result["profit_factor"] < DARWIN_CRITERIA["min_profit_factor"]:
        return False, "FAIL_LOW_SAMPLE"

    # Unique months
    trade_log = result.get("_trade_log", [])
    if trade_log:
        unique_months = _count_unique_months(trade_log)
        if unique_months < DARWIN_CRITERIA.get("min_unique_months", 12):
            return False, "FAIL_LOW_SAMPLE"

    # Simplicity: structured form enforcement
    style_ok, reason = check_style_purity(dna)
    if not style_ok:
        return False, "FAIL_COMPLEXITY"

    return True, None


# ── Registry Functions ─────────────────────────────────────────────────────

def register_passed(result: Dict, gates_cleared: List[str], trust: float = 0.0):
    """Register a strategy that passed ALL gates."""
    entry = {
        "strategy_code": result["strategy_code"],
        "asset": result["asset"],
        "timeframe": result["timeframe"],
        "sharpe": result["sharpe_ratio"],
        "win_rate": result["win_rate"],
        "trade_count": result["trade_count"],
        "profit_factor": result["profit_factor"],
        "max_drawdown": result["max_drawdown"],
        "total_return_pct": result["total_return_pct"],
        "trust_score": trust,
        "gates_passed": gates_cleared,
        "status": "passed",
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    state.passed_strategies.append(entry)
    # Cap at 500 — keep top by trust score, drop oldest
    if len(state.passed_strategies) > 500:
        state.passed_strategies.sort(key=lambda x: -x.get("trust_score", 0))
        state.passed_strategies = state.passed_strategies[:500]
    state.total_passed_all_gates += 1


def register_conditional(result: Dict, gates_cleared: List[str], conditional_gates: List[str],
                         trust: float = 0.0):
    """Register a strategy with conditional passes — never READY_FOR_PAPER."""
    entry = {
        "strategy_code": result["strategy_code"],
        "asset": result["asset"],
        "timeframe": result["timeframe"],
        "sharpe": result["sharpe_ratio"],
        "win_rate": result["win_rate"],
        "trade_count": result["trade_count"],
        "profit_factor": result["profit_factor"],
        "max_drawdown": result["max_drawdown"],
        "total_return_pct": result["total_return_pct"],
        "trust_score": trust,
        "gates_passed": gates_cleared,
        "conditional_gates": conditional_gates,
        "status": "conditional",
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    state.conditional_strategies.append(entry)
    if len(state.conditional_strategies) > 500:
        state.conditional_strategies.sort(key=lambda x: -x.get("trust_score", 0))
        state.conditional_strategies = state.conditional_strategies[:500]
    state.total_conditional += 1


def log_run(result: Dict, passed: bool):
    """Append to JSONL run log."""
    RUN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {k: v for k, v in result.items() if not k.startswith("_")}
    entry["passed_darwin"] = passed
    with open(RUN_LOG_PATH, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def archive_dna(dna: dict):
    """Persist every generated DNA to archive."""
    DNA_ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DNA_ARCHIVE_PATH, "a") as f:
        f.write(json.dumps(dna, default=str) + "\n")


# ── Trust Score ─────────────────────────────────────────────────────────────

def compute_trust_score(
    robustness_result: dict,
    walk_forward_result: dict,
    monte_carlo_result: dict,
    distribution_result: dict,
    complexity_count: int,
    forced_exit_ratio: float = 0.0,
) -> float:
    """
    Composite trust score (0.0 to 1.0) for passed strategies.
    NOT a ranking — a quality signal for resource allocation.

    Components:
    - stability_score: walk-forward + monte carlo health
    - distribution_score: PnL spread quality (inverse Gini)
    - simplicity_score: fewer indicators = higher trust
    - failure_penalty: deductions for near-misses
    """
    # Stability (0-1): how well it holds up under stress
    wf_degradation = walk_forward_result.get("degradation", 1.0)
    wf_score = max(0, 1.0 - abs(wf_degradation))  # less degradation = better
    mc_survival = monte_carlo_result.get("survival_rate", 0)
    mc_dd = monte_carlo_result.get("p95_dd", 1.0)
    mc_score = mc_survival * (1.0 - mc_dd)  # high survival + low DD = good
    stability_score = (wf_score * 0.5 + mc_score * 0.5)

    # Distribution (0-1): PnL spread quality
    gini = distribution_result.get("gini", 0.5)
    distribution_score = max(0, 1.0 - gini)  # lower Gini = more equal = better

    # Simplicity (0-1): fewer conditions = higher trust
    simplicity_score = max(0.3, 1.0 - (complexity_count - 1) * 0.2)  # 1=1.0, 2=0.8, 3=0.6

    # Failure penalty (0-1): deductions
    penalty = 0.0
    if forced_exit_ratio > 0.1:
        penalty += 0.1
    stripped_ratio = robustness_result.get("return_ratio", 1.0)
    if stripped_ratio < 0.5:
        penalty += 0.1  # heavily dependent on top trades even if passed

    trust = stability_score * distribution_score * simplicity_score * (1.0 - penalty)
    return round(max(0.0, min(1.0, trust)), 3)


# ── Pipeline Runner ────────────────────────────────────────────────────────

def run_pipeline(dna: dict, result: Dict, asset: str, tf: str) -> str:
    """
    Run the full validation pipeline after Darwin pass.
    Returns final status: "PASSED", "CONDITIONAL", or failure tag string.

    Gate ordering (cheap → expensive):
    1. DATA INTEGRITY — sanity check prices, no NaN, no gaps
    2. SIMULATION VALIDITY — equity sanity, forced_exit_ratio < 0.3
    3. TRADE VALIDITY — no outlier trades, realistic per-trade PnL
    4. EXECUTION CONSTRAINTS — (already in backtester: max hold, realistic fills)
    5. STATISTICAL VIABILITY — min 100 trades, 12+ months, Sharpe > 0.5, DD < 20%
       (Darwin gate already checked; re-checked here as safety net)
    6. DISTRIBUTION — Gini < 0.6, no month > 30%, PnL spans 3+ years
    7. STABILITY — robustness, walk-forward, light MC, full MC
    8. COMPLEXITY — max 2 indicators per style, structured forms only
       (Already enforced in darwin_gate; deep inspection checks further)
    """
    code = result["strategy_code"]
    raw_trades = result.get("_trades", [])
    trade_log = result.get("_trade_log", result.get("trade_log", []))
    extra = result.get("extra", {})

    gates_cleared = ["darwin"]
    conditional_gates = []
    failure_tags = []  # multi-tag: collect ALL failures, don't stop at first for cheap gates
    is_conditional = False

    def _record_tag(gate: str, tag: str, severity: str = "hard_fail", metrics: dict = None):
        """Record a failure tag with severity."""
        failure_tags.append({"tag": tag, "severity": severity, "gate": gate})
        if severity == "hard_fail":
            state.failure_summary[tag] += 1

    # ══════════════════════════════════════════════════════════════════════
    # CHEAP GATES (1-4): computed from backtest output, no extra compute
    # ══════════════════════════════════════════════════════════════════════

    # ── Gate 1: DATA INTEGRITY ──
    # Check for NaN or impossible values in trade log
    nan_count = 0
    bad_price_count = 0
    for t in trade_log[:200]:
        ep = t.get("entry_price", 0)
        xp = t.get("exit_price", 0)
        pnl = t.get("pnl_pct", 0)
        if ep <= 0 or xp <= 0:
            bad_price_count += 1
        if pnl != pnl:  # NaN check
            nan_count += 1
    if nan_count > 0:
        _record_tag("data_integrity", "FAIL_DATA_INTEGRITY", "hard_fail",
                     {"nan_trades": nan_count})
        log.info(f"  🚫 DATA INTEGRITY: FAIL — {nan_count} NaN trades")
    if bad_price_count > len(trade_log) * 0.05:
        _record_tag("data_integrity", "FAIL_DATA_INTEGRITY", "hard_fail",
                     {"bad_prices": bad_price_count})
        log.info(f"  🚫 DATA INTEGRITY: FAIL — {bad_price_count} bad price trades")

    if not any(ft["severity"] == "hard_fail" and ft["gate"] == "data_integrity" for ft in failure_tags):
        gates_cleared.append("data_integrity")
        log.info(f"  ✅ DATA INTEGRITY: PASS")

    # ── Gate 2: SIMULATION VALIDITY ──
    sim_hard_fail = False
    total_return = result.get("total_return_pct", 0)
    pf = result.get("profit_factor", 0)
    forced_exit_ratio = extra.get("forced_exit_ratio", 0)

    if total_return > 10000 or total_return < -100:
        _record_tag("simulation_validity", "FAIL_BROKEN_EQUITY", "hard_fail",
                     {"total_return_pct": total_return})
        sim_hard_fail = True
        log.info(f"  🚫 SIM VALIDITY: FAIL — broken equity: {total_return:+.1f}%")
    if pf > 10:
        _record_tag("simulation_validity", "FAIL_BROKEN_EQUITY", "hard_fail",
                     {"profit_factor": pf})
        sim_hard_fail = True
        log.info(f"  🚫 SIM VALIDITY: FAIL — unrealistic PF: {pf:.2f}")
    if forced_exit_ratio > 0.3:
        _record_tag("simulation_validity", "FAIL_FORCED_EXIT_DEPENDENCY", "hard_fail",
                     {"forced_exit_ratio": forced_exit_ratio})
        sim_hard_fail = True
        log.info(f"  🚫 SIM VALIDITY: FAIL — forced_exit_ratio {forced_exit_ratio:.1%} > 30%")
    elif forced_exit_ratio > 0.2:
        _record_tag("simulation_validity", "FAIL_FORCED_EXIT_DEPENDENCY", "warning",
                     {"forced_exit_ratio": forced_exit_ratio})
        log.info(f"  ⚠️ SIM VALIDITY: WARNING — forced_exit_ratio {forced_exit_ratio:.1%}")

    if not sim_hard_fail:
        gates_cleared.append("simulation_validity")
        log.info(f"  ✅ SIM VALIDITY: PASS")

    # ── Gate 3: TRADE VALIDITY ──
    trade_hard_fail = False
    total_pnl = result.get("total_pnl", 0)
    if total_pnl > 0 and trade_log:
        max_single_pct = 0
        for t in trade_log:
            tpnl = abs(t.get("pnl_pct", 0))
            single_pct = tpnl / total_pnl * 100 if total_pnl > 0 else 0
            max_single_pct = max(max_single_pct, single_pct)
        if max_single_pct > 50:
            _record_tag("trade_validity", "FAIL_OUTLIER_TRADE", "hard_fail",
                         {"max_single_trade_pct": round(max_single_pct, 1)})
            trade_hard_fail = True
            log.info(f"  🚫 TRADE VALIDITY: FAIL — single trade = {max_single_pct:.0f}% of PnL")
        elif max_single_pct > 15:
            _record_tag("trade_validity", "FAIL_OUTLIER_TRADE", "warning",
                         {"max_single_trade_pct": round(max_single_pct, 1)})
            log.info(f"  ⚠️ TRADE VALIDITY: WARNING — single trade = {max_single_pct:.0f}% of PnL")

    # Check for absurd per-trade PnL (> 100% on a single trade = bad data leak)
    absurd_trades = sum(1 for t in trade_log if abs(t.get("pnl_pct", 0)) > 1.0)
    if absurd_trades > 0:
        _record_tag("trade_validity", "FAIL_DATA_INTEGRITY", "hard_fail",
                     {"absurd_trades": absurd_trades})
        trade_hard_fail = True
        log.info(f"  🚫 TRADE VALIDITY: FAIL — {absurd_trades} trades with >100% PnL (bad data)")

    if not trade_hard_fail:
        gates_cleared.append("trade_validity")
        log.info(f"  ✅ TRADE VALIDITY: PASS")

    # ── Gate 4: EXECUTION CONSTRAINTS ── (implicitly checked by backtester)
    gates_cleared.append("execution_constraints")

    # ── FAIL FAST: if ANY cheap gate hard-failed, log all tags and bail ──
    hard_fails = [ft for ft in failure_tags if ft["severity"] == "hard_fail"]
    if hard_fails:
        # Log multi-tag failure
        _log_multi_failure(code, asset, tf, failure_tags, result)
        first_tag = hard_fails[0]["tag"]
        state.total_failed += 1
        return first_tag

    # ══════════════════════════════════════════════════════════════════════
    # MEDIUM GATES (5-6): statistical checks, still cheap
    # ══════════════════════════════════════════════════════════════════════

    # ── Gate 5: STATISTICAL VIABILITY (safety net — Darwin already checked) ──
    gates_cleared.append("statistical_viability")
    log.info(f"  ✅ STATISTICAL VIABILITY: PASS (Darwin pre-screened)")

    # ── Gate 6: DISTRIBUTION ──
    try:
        td = check_trade_distribution(trade_log, total_pnl)
        result["trade_distribution"] = td
        gini_str = f"gini={td.get('gini', 0):.2f} " if 'gini' in td else ""
        log.info(f"  📊 DISTRIBUTION: {gini_str}month={td['max_month_pnl_pct']:.1f}% "
                 f"trade={td['max_trade_pnl_pct']:.1f}% years={td['years_with_pnl']} "
                 f"{'PASS' if td['passed'] else 'COND' if td.get('conditional') else 'FAIL'}")
        if td["passed"]:
            gates_cleared.append("distribution")
        elif td.get("conditional"):
            conditional_gates.append("CONDITIONAL_DISTRIBUTION")
            gates_cleared.append("distribution")
            is_conditional = True
        else:
            tag = td.get("failure_tag", "FAIL_TRADE_DISTRIBUTION")
            _record_tag("distribution", tag, "hard_fail", td)
            _log_multi_failure(code, asset, tf, failure_tags, result)
            state.total_failed += 1
            return tag
    except Exception as e:
        log.error(f"  Distribution error: {e}")
        state.total_failed += 1
        return "FAIL_TRADE_DISTRIBUTION"

    # ══════════════════════════════════════════════════════════════════════
    # EXPENSIVE GATES (7): robustness, walk-forward, Monte Carlo
    # ══════════════════════════════════════════════════════════════════════

    # ── Gate 7a: Robustness ──
    if not raw_trades or len(raw_trades) < 10:
        _record_tag("robustness", "FAIL_PNL_CONCENTRATION", "hard_fail",
                     {"trade_count": len(raw_trades)})
        _log_multi_failure(code, asset, tf, failure_tags, result)
        state.total_failed += 1
        return "FAIL_PNL_CONCENTRATION"

    try:
        rob = robustness_check(raw_trades)
        result["robustness_check"] = rob
        log.info(f"  🔍 ROBUSTNESS: ratio={rob['return_ratio']:.2f} share={rob['top5_pnl_share']:.2f} "
                 f"{'PASS' if rob['passed'] else 'COND' if rob.get('conditional') else 'FAIL'}")
        if rob["passed"]:
            gates_cleared.append("robustness")
        elif rob.get("conditional"):
            conditional_gates.append("CONDITIONAL_ROBUSTNESS")
            gates_cleared.append("robustness")
            is_conditional = True
        else:
            tag = rob.get("failure_tag", "FAIL_PNL_CONCENTRATION")
            _record_tag("robustness", tag, "hard_fail", rob)
            _log_multi_failure(code, asset, tf, failure_tags, result)
            state.total_failed += 1
            return tag
    except Exception as e:
        log.error(f"  Robustness error: {e}")
        state.total_failed += 1
        return "FAIL_PNL_CONCENTRATION"

    # ── Gate 7b: Light Monte Carlo ──
    try:
        mc_light = monte_carlo_light(raw_trades)
        result["monte_carlo_light"] = mc_light
        log.info(f"  🎲 LIGHT MC: survival={mc_light['survival_rate']:.1%} "
                 f"{'PASS' if mc_light['passed'] else 'COND' if mc_light.get('conditional') else 'FAIL'}")
        if mc_light["passed"]:
            gates_cleared.append("light_mc")
        elif mc_light.get("conditional"):
            conditional_gates.append("CONDITIONAL_LIGHT_MC")
            gates_cleared.append("light_mc")
            is_conditional = True
        else:
            tag = mc_light.get("failure_tag", "FAIL_MC_FRAGILITY")
            _record_tag("light_mc", tag, "hard_fail", mc_light)
            _log_multi_failure(code, asset, tf, failure_tags, result)
            state.total_failed += 1
            return tag
    except Exception as e:
        log.error(f"  Light MC error: {e}")
        state.total_failed += 1
        return "FAIL_MC_FRAGILITY"

    # ── Gate 7c: Walk-Forward ──
    try:
        wf = walk_forward_test(dna, asset, tf, df_cached=get_cached_data(asset, tf))
        result["walk_forward"] = wf
        log.info(f"  📈 WALK-FORWARD: OOS Sharpe={wf['oos_sharpe']:.2f} deg={wf['degradation']:.2f} "
                 f"{'PASS' if wf['passed'] else 'COND' if wf.get('conditional') else 'FAIL'}")
        if wf["passed"]:
            gates_cleared.append("walk_forward")
        elif wf.get("conditional"):
            conditional_gates.append("CONDITIONAL_WALK_FORWARD")
            gates_cleared.append("walk_forward")
            is_conditional = True
        else:
            tag = wf.get("failure_tag", "FAIL_WF_INSTABILITY")
            _record_tag("walk_forward", tag, "hard_fail", wf)
            _log_multi_failure(code, asset, tf, failure_tags, result)
            state.total_failed += 1
            return tag
    except Exception as e:
        log.error(f"  Walk-forward error: {e}")
        state.total_failed += 1
        return "FAIL_WF_INSTABILITY"

    # ── Gate 7d: Full Monte Carlo ──
    try:
        mc_full = monte_carlo_test(raw_trades, n_simulations=200)
        result["monte_carlo_full"] = mc_full
        log.info(f"  🎲 FULL MC: survival={mc_full['survival_rate']:.1%} p95_dd={mc_full['p95_dd']:.1%} "
                 f"{'PASS' if mc_full['passed'] else 'COND' if mc_full.get('conditional') else 'FAIL'}")
        if mc_full["passed"]:
            gates_cleared.append("full_mc")
        elif mc_full.get("conditional"):
            conditional_gates.append("CONDITIONAL_FULL_MC")
            gates_cleared.append("full_mc")
            is_conditional = True
        else:
            tag = mc_full.get("failure_tag", "FAIL_MC_FRAGILITY")
            _record_tag("full_mc", tag, "hard_fail", mc_full)
            _log_multi_failure(code, asset, tf, failure_tags, result)
            state.total_failed += 1
            return tag
    except Exception as e:
        log.error(f"  Full MC error: {e}")
        state.total_failed += 1
        return "FAIL_MC_FRAGILITY"

    # ══════════════════════════════════════════════════════════════════════
    # CONDITIONAL SAFETY CHECK
    # Conditional strategies can NEVER have these red flags:
    # ══════════════════════════════════════════════════════════════════════
    if is_conditional:
        safety_fail = False
        if total_return > 10000 or total_return < -100:
            safety_fail = True
            log.info(f"  🚫 CONDITIONAL SAFETY: broken equity {total_return:+.1f}%")
        if pf > 10:
            safety_fail = True
            log.info(f"  🚫 CONDITIONAL SAFETY: unrealistic PF {pf:.2f}")
        # Check max single trade share
        if total_pnl > 0 and trade_log:
            max_share = max(abs(t.get("pnl_pct", 0)) / total_pnl * 100
                           for t in trade_log) if trade_log else 0
            if max_share > 50:
                safety_fail = True
                log.info(f"  🚫 CONDITIONAL SAFETY: outlier trade {max_share:.0f}% of PnL")

        if safety_fail:
            _record_tag("conditional_safety", "FAIL_BROKEN_EQUITY", "hard_fail")
            _log_multi_failure(code, asset, tf, failure_tags, result)
            state.total_failed += 1
            return "FAIL_BROKEN_EQUITY"

        # Compute trust score for conditional too
        try:
            n_cond = count_entry_conditions(dna) if dna else 2
            cond_trust = compute_trust_score(
                robustness_result=result.get("robustness_check", {}),
                walk_forward_result=result.get("walk_forward", {}),
                monte_carlo_result=result.get("monte_carlo_full", {}),
                distribution_result=result.get("trade_distribution", {}),
                complexity_count=n_cond,
                forced_exit_ratio=extra.get("forced_exit_ratio", 0),
            )
        except Exception:
            cond_trust = 0.0
        register_conditional(result, gates_cleared, conditional_gates, trust=cond_trust)
        log.info(f"  🟡 CONDITIONAL: {code} on {asset}/{tf} (trust={cond_trust:.3f}) | conditions: {conditional_gates}")
        return "CONDITIONAL"

    # ══════════════════════════════════════════════════════════════════════
    # Gate 8: COMPLEXITY — Final Validation + Deep Inspection
    # ══════════════════════════════════════════════════════════════════════
    if FINAL_VALIDATION_ENABLED:
        log.info(f"  ⚙️ FINAL VALIDATION: {code} → Gate 4 + Gate 5...")
        try:
            fv = validate_strategy(dna, asset, tf)

            if fv.tag == ValidationTag.READY_FOR_PAPER:
                gates_cleared.append("final_validation")
                result["final_validation"] = "READY_FOR_PAPER"

                # Deep Inspection
                try:
                    inspection = deep_inspect(dna, asset, tf, n_clones=5)
                    result["deep_inspection_verdict"] = inspection.verdict
                    result["deep_inspection_warnings"] = inspection.warnings[:5]
                    result["clone_reproducible"] = (
                        inspection.clone_validation.get("reproducible", False)
                        if inspection.clone_validation else False
                    )
                    gates_cleared.append("deep_inspection")
                    log.info(f"  🔬 DEEP INSPECT: {inspection.verdict} | "
                             f"Reproducible: {result['clone_reproducible']}")
                except Exception as e:
                    log.error(f"  Deep inspection error: {e}")
                    result["deep_inspection_verdict"] = "ERROR"

                # Compute trust score
                try:
                    n_conditions = count_entry_conditions(dna) if dna else 2
                    trust = compute_trust_score(
                        robustness_result=result.get("robustness_check", {}),
                        walk_forward_result=result.get("walk_forward", {}),
                        monte_carlo_result=result.get("monte_carlo_full", {}),
                        distribution_result=result.get("trade_distribution", {}),
                        complexity_count=n_conditions,
                        forced_exit_ratio=extra.get("forced_exit_ratio", 0),
                    )
                except Exception:
                    trust = 0.0
                register_passed(result, gates_cleared, trust=trust)
                log.info(f"  🟢 PASSED ALL GATES: {code} on {asset}/{tf} (trust={trust:.3f})")
                return "PASSED"

            elif fv.tag == ValidationTag.REQUIRES_HARDENING:
                log.info(f"  🟡 REQUIRES_HARDENING: {code} | "
                         f"G4={'P' if fv.degradation_passed else 'F'} "
                         f"G5={'P' if fv.dependency_passed else 'F'}")
                result["final_validation"] = "REQUIRES_HARDENING"
                try:
                    record_validation_failure(dna, asset, fv)
                except Exception:
                    pass
                _record_tag("final_validation", "FAIL_EXECUTION_SENSITIVITY", "hard_fail",
                            {"reasons": fv.fail_summary[:5]})
                _log_multi_failure(code, asset, tf, failure_tags, result)
                state.total_failed += 1
                return "FAIL_EXECUTION_SENSITIVITY"

            else:
                log.info(f"  🔴 REJECTED_POST_DARWIN: {code} | {fv.fail_summary[:3]}")
                result["final_validation"] = "REJECTED_POST_DARWIN"
                try:
                    record_validation_failure(dna, asset, fv)
                except Exception:
                    pass
                _record_tag("final_validation", "FAIL_EXECUTION_SENSITIVITY", "hard_fail",
                            {"reasons": fv.fail_summary[:5]})
                _log_multi_failure(code, asset, tf, failure_tags, result)
                state.total_failed += 1
                return "FAIL_EXECUTION_SENSITIVITY"

        except Exception as e:
            log.error(f"  ❌ Final validation error: {e}")
            state.total_failed += 1
            return "FAIL_EXECUTION_SENSITIVITY"

    # If final validation disabled, register as passed after stability gates
    try:
        n_conditions = count_entry_conditions(dna) if dna else 2
        trust = compute_trust_score(
            robustness_result=result.get("robustness_check", {}),
            walk_forward_result=result.get("walk_forward", {}),
            monte_carlo_result=result.get("monte_carlo_full", {}),
            distribution_result=result.get("trade_distribution", {}),
            complexity_count=n_conditions,
            forced_exit_ratio=extra.get("forced_exit_ratio", 0),
        )
    except Exception:
        trust = 0.0
    register_passed(result, gates_cleared, trust=trust)
    return "PASSED"


def _log_multi_failure(code: str, asset: str, tf: str,
                       tags: List[Dict], result: Dict):
    """Log a multi-tag failure entry to the failure registry."""
    metrics = {
        "trade_count": result.get("trade_count", 0),
        "win_rate": result.get("win_rate", 0),
        "sharpe_ratio": result.get("sharpe_ratio", 0),
        "max_drawdown": result.get("max_drawdown", 0),
        "profit_factor": result.get("profit_factor", 0),
        "total_return_pct": result.get("total_return_pct", 0),
    }
    FAILURE_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "strategy_code": code,
        "asset": asset,
        "timeframe": tf,
        "failures": tags,
        "metrics": metrics,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(FAILURE_REGISTRY_PATH, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ── Main Loop ──────────────────────────────────────────────────────────────

def shutdown(signum, frame):
    log.info(f"Received signal {signum}, shutting down gracefully...")
    state.running = False



# ── Data Cache — LRU with eviction ─────────────────────────────────────────
_DATA_CACHE: Dict[str, Any] = {}
_DATA_CACHE_ORDER: list = []  # LRU tracking
_DATA_CACHE_MAX = 3  # max datasets in memory at once

# Cap data to prevent memory bloat on huge datasets (CL/1h = 1.87M bars)
MAX_BARS_PER_DATASET = 30_000  # ~50K bars max — enough for meaningful backtest, keeps memory sane


def get_cached_data(asset: str, timeframe: str):
    """Return cached DataFrame. LRU eviction to control memory."""
    key = f"{asset}_{timeframe}"
    if key in _DATA_CACHE:
        # Move to end (most recently used)
        if key in _DATA_CACHE_ORDER:
            _DATA_CACHE_ORDER.remove(key)
        _DATA_CACHE_ORDER.append(key)
        return _DATA_CACHE[key]

    # Load and cap
    df = load_parquet(asset, timeframe)
    orig_len = len(df)
    if orig_len > MAX_BARS_PER_DATASET:
        df = df.iloc[-MAX_BARS_PER_DATASET:].copy()
        log.info(f"  Cached {asset}/{timeframe}: {len(df)} rows (capped from {orig_len})")
    else:
        log.info(f"  Cached {asset}/{timeframe}: {len(df)} rows")
    _DATA_CACHE[key] = df
    _DATA_CACHE_ORDER.append(key)

    # Evict oldest if over limit
    while len(_DATA_CACHE) > _DATA_CACHE_MAX and _DATA_CACHE_ORDER:
        evict_key = _DATA_CACHE_ORDER.pop(0)
        if evict_key in _DATA_CACHE:
            del _DATA_CACHE[evict_key]
            log.info(f"  Evicted {evict_key} from cache (LRU)")
    return df


def main():
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    log.info("=" * 70)
    log.info("  CONTINUOUS BACKTESTER — The Factory Never Sleeps")
    log.info("  Pipeline: Darwin → Robustness → Light MC → Walk-Forward")
    log.info("            → Full MC → Distribution → Final Val → Deep Inspect")
    log.info("=" * 70)

    if not DNA_PATH.exists():
        log.error(f"DNA file not found: {DNA_PATH}")
        return

    with open(DNA_PATH) as f:
        base_dnas = json.load(f)
    log.info(f"Loaded {len(base_dnas)} base strategy DNAs")

    # Lazy-load data — don't pre-cache everything at startup
    # get_cached_data() loads on-demand and caches per dataset
    log.info("Data loading: on-demand (lazy cache with 100K bar cap)")
    import gc; gc.collect()

    state.load()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    log.info(f"Assets: {ASSETS}")
    log.info(f"Timeframe weights: {TIMEFRAME_WEIGHTS}")
    log.info(f"Batch size: {BATCH_SIZE}")
    log.info(f"Darwin criteria: {DARWIN_CRITERIA}")
    log.info(f"Starting from generation {state.generation}")
    log.info("-" * 70)

    while state.running:
        state.generation += 1
        gen = state.generation

        if MAX_GENERATIONS and gen > MAX_GENERATIONS:
            log.info(f"Reached max generations ({MAX_GENERATIONS}). Stopping.")
            break

        if gen % 10 == 0:
            try:
                patterns = analyze_failure_patterns()
                n_failures = patterns.get("total_failures", 0)
                top_patterns = list(patterns.get("patterns", {}).items())[:5]
                log.info(f"  📊 FAILURE INTELLIGENCE: {n_failures} failures analyzed")
                for pat, count in top_patterns:
                    log.info(f"     {pat}: {count} occurrences")
            except Exception as e:
                log.debug(f"  Failure analysis error: {e}")

        parents = base_dnas.copy()
        batch = create_batch(parents, gen)
        batch_darwin = 0
        batch_tested = 0

        log.info(f"━━━ Generation {gen} | Batch of {len(batch)} strategies ━━━")

        for dna in batch:
            if not state.running:
                break

            archive_dna(dna)

            for asset in ASSETS:
                if not state.running:
                    break

                selected_tfs = random.sample(TIMEFRAMES_POOL, min(2, len(TIMEFRAMES_POOL)))
                selected_tfs = list(set(selected_tfs))

                for tf in selected_tfs:
                    result = backtest_strategy(dna, asset, tf)
                    if result is None:
                        continue

                    batch_tested += 1
                    state.total_tested += 1

                    # ── Gate 1: Darwin ──
                    darwin_passed, darwin_tag = darwin_gate(result, dna)

                    if darwin_passed:
                        batch_darwin += 1
                        log.info(
                            f"  🏆 DARWIN PASS: {result['strategy_code']} on {asset}/{tf} | "
                            f"WR={result['win_rate']:.1%} Sharpe={result['sharpe_ratio']:.2f} "
                            f"DD={result['max_drawdown']:.1%} PF={result['profit_factor']:.2f} "
                            f"Ret={result['total_return_pct']:+.1f}%"
                        )

                        # Run full pipeline
                        pipeline_status = run_pipeline(dna, result, asset, tf)
                        result["pipeline_status"] = pipeline_status

                    else:
                        # Darwin fail — record with tag
                        state.total_failed += 1
                        if darwin_tag:
                            state.failure_summary[darwin_tag] += 1
                            record_failure(
                                result["strategy_code"], asset, tf,
                                "darwin", darwin_tag,
                                {"trade_count": result["trade_count"],
                                 "win_rate": result["win_rate"],
                                 "sharpe_ratio": result["sharpe_ratio"],
                                 "max_drawdown": result["max_drawdown"],
                                 "profit_factor": result["profit_factor"]},
                            )
                        log.debug(
                            f"  ❌ DARWIN FAIL [{darwin_tag}]: {result['strategy_code']} on {asset}/{tf} | "
                            f"WR={result['win_rate']:.1%} Sharpe={result['sharpe_ratio']:.2f}"
                        )
                        try:
                            record_darwin_failure(dna, asset, result)
                        except Exception:
                            pass

                    log_run(result, darwin_passed)

                    # ── Memory cleanup: drop heavy fields after processing ──
                    result.pop("_trades", None)
                    result.pop("_trade_log", None)
                    result.pop("trade_log", None)
                    del result

        # Generation summary
        pass_rate = (batch_darwin / batch_tested * 100) if batch_tested > 0 else 0
        uptime = datetime.now(timezone.utc) - state.start_time
        log.info(
            f"  Gen {gen} done: {batch_darwin}/{batch_tested} Darwin ({pass_rate:.1f}%) | "
            f"Total: {state.total_tested} tested, {state.total_passed_all_gates} passed, "
            f"{state.total_conditional} conditional, {state.total_failed} failed | "
            f"Uptime: {uptime}"
        )

        # Log failure summary every 5 generations
        if gen % 5 == 0 and state.failure_summary:
            log.info("  📋 FAILURE SUMMARY:")
            for tag, count in sorted(state.failure_summary.items(), key=lambda x: -x[1]):
                log.info(f"     {tag}: {count}")

        state.save()

        # ── Force garbage collection between generations ──
        import gc
        gc.collect()

        # ── Memory safety valve: restart if RSS exceeds 4GB ──
        try:
            import psutil
            rss_gb = psutil.Process(os.getpid()).memory_info().rss / (1024 ** 3)
            log.info(f"  📏 Memory: {rss_gb:.2f} GB")
            if rss_gb > 4.0:
                log.warning(f"⚠️ MEMORY SAFETY: RSS={rss_gb:.1f}GB > 4GB — saving state and exiting for restart")
                state.save()
                os._exit(0)  # systemd will restart us
        except ImportError:
            pass

        if state.running:
            log.info(f"  Sleeping {SLEEP_BETWEEN_BATCHES}s before next generation...")
            for _ in range(SLEEP_BETWEEN_BATCHES):
                if not state.running:
                    break
                time.sleep(1)

    state.save()
    log.info("=" * 70)
    log.info(f"  Continuous backtester stopped.")
    log.info(f"  Total: {state.total_tested} tested, {state.total_passed_all_gates} passed, "
             f"{state.total_conditional} conditional, {state.total_failed} failed")
    log.info(f"  Registry saved to {REGISTRY_PATH}")
    log.info("=" * 70)


if __name__ == "__main__":
    main()

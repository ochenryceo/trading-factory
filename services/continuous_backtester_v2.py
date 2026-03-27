#!/usr/bin/env python3
"""
Continuous Backtester V2 — Supervisor + Worker Architecture
============================================================
Memory-efficient backtesting engine that uses subprocess workers to avoid
accumulating memory in a single process. The supervisor stays lightweight
(~150MB), spawning disposable workers that process batches of strategies,
write results to disk, and exit (freeing ALL memory).

Architecture:
  Supervisor (persistent) → spawns Worker subprocesses (disposable)
  - Supervisor: manages batch queue, generation counter, DNA generation
  - Worker: loads data, computes indicators, backtests, MC, WF, writes JSONL, exits

Usage:
  python continuous_backtester_v2.py                  # Run continuously
  python continuous_backtester_v2.py --generations 5  # Run N generations then stop
  python continuous_backtester_v2.py --worker <json>  # Internal: worker mode (called by supervisor)
"""

import argparse
import gc
import json
import logging
import math
import os
import random
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# =============================================================================
# CONFIGURATION
# =============================================================================

BASE_DIR = Path("Path(__file__).resolve().parents[1]")
DATA_DIR = BASE_DIR / "data" / "processed"
OUTPUT_JSONL = BASE_DIR / "data" / "continuous_run_log.jsonl"
STATE_FILE = BASE_DIR / "data" / "backtester_v2_state.json"
DNA_FILE = BASE_DIR / "data" / "mock" / "strategy_dnas.json"

ASSETS = ["NQ", "GC", "CL"]
TIMEFRAMES = ["15m", "1h", "4h", "daily"]

# Search expansion — lazy import to avoid circular deps
def _get_expansion():
    try:
        from services.search_expansion import (
            check_and_activate, load_expansion_state, get_active_timeframes,
            should_expand_strategy, expanded_random_params, ensure_30m_data,
            apply_session_filter, apply_atr_regime, apply_dynamic_thresholds,
            track_expanded_result, check_deactivation, get_expanded_timeframe_batches,
        )
        return {
            "check_and_activate": check_and_activate,
            "load_state": load_expansion_state,
            "get_active_timeframes": get_active_timeframes,
            "should_expand": should_expand_strategy,
            "expand_params": expanded_random_params,
            "ensure_30m": ensure_30m_data,
            "apply_session": apply_session_filter,
            "apply_atr": apply_atr_regime,
            "apply_dynamic": apply_dynamic_thresholds,
            "track_result": track_expanded_result,
            "check_deactivation": check_deactivation,
            "get_extra_batches": get_expanded_timeframe_batches,
        }
    except Exception as e:
        log.warning(f"Search expansion unavailable: {e}")
        return None

MAX_WORKERS = 2
BATCH_SIZE = 10  # strategies per worker

# Style weights for random DNA generation
STYLE_WEIGHTS = {
    "volume_orderflow": 0.40,
    "scalping": 0.30,
    "mean_reversion": 0.15,
    "momentum_breakout": 0.10,
    "trend_following": 0.03,
    "news": 0.02,
}

# Darwin criteria — adaptive trade minimum, two tiers
DARWIN_PRODUCTION = {
    "min_win_rate": 0.40,
    "min_sharpe": 0.5,
    "max_drawdown": 0.20,
    "min_trades": 100,        # hard floor for production tier
    "min_profit_factor": 1.1,
}
DARWIN_EXPLORATION = {
    "min_win_rate": 0.35,
    "min_sharpe": 0.3,
    "max_drawdown": 0.25,
    "min_trades": 30,         # hard floor for exploration tier
    "min_profit_factor": 1.0,
}
# Backward compat alias
DARWIN = DARWIN_PRODUCTION

# Adaptive trade minimum: max(30, 5% of dataset rows)
MIN_SIGNAL_DENSITY = 5        # skip strategy if < 5 raw signals generated

# Sanity filter thresholds (reject impossible results)
SANITY = {
    "max_win_rate_with_trades": (0.95, 50),   # WR >= 95% with 50+ trades
    "zero_dd_min_trades": 20,                  # Zero DD with 20+ trades
    "max_profit_factor": 50,
    "max_sharpe": 10,
    "max_return_pct": 10000,
}

# Monte Carlo config
MC_SIMS = 200

# Walk-forward config
WF_FOLDS = 5

# Evolution safeguards
MAX_EVOLUTION_RATIO = 0.30     # never let near-miss evolution exceed 30% of batch
MIN_RANDOM_RATIO = 0.30       # always keep at least 30% pure random (exploration floor)
CONVERGENCE_THRESHOLD = 0.15  # if param std < 15% of range → inject randomness
MUTATION_DECAY_GEN = 50       # after this generation, tighten mutations to ±3-5%

# Parameter ranges for DNA generation — WIDENED for signal density
# More signals → let Darwin/sanity filters kill bad ones
PARAM_RANGES = {
    "rsi_threshold": (20, 45),      # was 25-35 → wider to catch more entries
    "rsi_period": (5, 21),          # was 7-14 → include faster RSI
    "fast_ema": (8, 30),            # was 15-25 → include faster crossovers
    "slow_ema": (30, 80),           # was 40-60 → wider spread range
    "adx_threshold": (10, 30),      # was 20-30 → lower floor catches weaker trends
    "volume_multiplier": (1.0, 2.5), # was 1.2-2.0 → lower floor = more volume entries
    "bb_period": (10, 30),          # was 15-25 → include tighter/wider bands
    "z_score_threshold": (1.0, 3.0), # was 1.5-2.5 → lower floor = more z-score signals
}

# Adaptive bias config
BIAS_FILE = BASE_DIR / "data" / "adaptive_bias.json"
BIAS_BUCKETS = 5              # number of buckets per parameter
BIAS_ENTROPY_FLOOR = 0.5     # minimum entropy (0-1 scale) to prevent overconfidence
BIAS_MIN_SAMPLES = 10        # need this many data points before trusting bias

# Lineage config
LINEAGE_FILE = BASE_DIR / "data" / "lineage_scores.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("backtester_v2")


# =============================================================================
# DNA GENERATION
# =============================================================================

def weighted_style_choice() -> str:
    """Pick a style based on configured weights, with control layer + stabilizer caps."""
    styles = list(STYLE_WEIGHTS.keys())
    weights = list(STYLE_WEIGHTS.values())

    # Apply dominant style cap from control layer
    cs = _load_control_state()
    cap_style = cs.get("dominant_style_cap")
    if cap_style and cap_style in styles:
        cap_weight = cs.get("dominant_style_cap_weight", 0.5)
        idx = styles.index(cap_style)
        weights[idx] *= cap_weight

    # Apply diversity stabilizer adjustments
    try:
        from services.diversity_stabilizer import _load_state as _load_div_state
        div_state = _load_div_state()
        swa = div_state.get("style_weight_adjustments", {})
        for i, style in enumerate(styles):
            if style in swa:
                # Apply as multiplicative: -0.30 means reduce by 30%
                factor = max(0.1, 1.0 + swa[style])  # floor at 10% of original
                weights[i] *= factor
    except Exception:
        pass

    # Ensure no zero/negative weights
    weights = [max(0.01, w) for w in weights]

    return random.choices(styles, weights=weights, k=1)[0]


# =============================================================================
# ADAPTIVE BIAS ENGINE — Learn where edge lives, sample there more often
# =============================================================================

def _bucketize(value: float, lo: float, hi: float, n_buckets: int = BIAS_BUCKETS) -> int:
    """Map a value to a bucket index."""
    if hi <= lo:
        return 0
    normalized = (value - lo) / (hi - lo)
    return max(0, min(n_buckets - 1, int(normalized * n_buckets)))


def _bucket_center(bucket: int, lo: float, hi: float, n_buckets: int = BIAS_BUCKETS) -> float:
    """Get the center value of a bucket."""
    width = (hi - lo) / n_buckets
    return lo + width * (bucket + 0.5)


def load_bias() -> dict:
    """Load adaptive bias weights from disk."""
    if BIAS_FILE.exists():
        try:
            with open(BIAS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_bias(bias: dict):
    """Save adaptive bias weights."""
    BIAS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BIAS_FILE, "w") as f:
        json.dump(bias, f, indent=2)


def update_bias(style: str, params: dict, fitness: float):
    """
    Update bias weights from a strategy result.
    Higher fitness → higher weight for those parameter buckets.
    """
    bias = load_bias()
    key = style
    if key not in bias:
        bias[key] = {}

    for param_name, value in params.items():
        if param_name not in PARAM_RANGES:
            continue
        lo, hi = PARAM_RANGES[param_name]
        bucket = _bucketize(float(value), lo, hi)
        bucket_key = str(bucket)

        if param_name not in bias[key]:
            bias[key][param_name] = {}
        if bucket_key not in bias[key][param_name]:
            bias[key][param_name][bucket_key] = {"count": 0, "score_sum": 0.0}

        bias[key][param_name][bucket_key]["count"] += 1
        bias[key][param_name][bucket_key]["score_sum"] += fitness

    save_bias(bias)


def biased_sample(style: str, param_name: str) -> float:
    """
    Sample a parameter value using adaptive bias weights.
    Falls back to uniform random if insufficient data.
    """
    bias = load_bias()
    lo, hi = PARAM_RANGES.get(param_name, (0, 100))

    style_bias = bias.get(style, {}).get(param_name, {})
    total_samples = sum(b.get("count", 0) for b in style_bias.values())

    if total_samples < BIAS_MIN_SAMPLES:
        # Not enough data — fall back to uniform
        if isinstance(lo, float):
            return round(random.uniform(lo, hi), 2)
        return random.randint(lo, hi)

    # Compute weights per bucket
    weights = []
    for b in range(BIAS_BUCKETS):
        bk = str(b)
        if bk in style_bias and style_bias[bk]["count"] > 0:
            avg_score = style_bias[bk]["score_sum"] / style_bias[bk]["count"]
            weights.append(max(0.01, avg_score))  # floor to prevent zero weight
        else:
            weights.append(0.1)  # unexplored bucket gets small weight

    # Entropy floor — prevent overconfidence
    import numpy as np
    w_arr = np.array(weights)
    w_arr /= w_arr.sum()
    entropy = -np.sum(w_arr * np.log2(w_arr + 1e-10)) / np.log2(len(w_arr))
    if entropy < BIAS_ENTROPY_FLOOR:
        # Too peaked — flatten toward uniform
        w_arr = 0.5 * w_arr + 0.5 * np.ones(len(w_arr)) / len(w_arr)
        w_arr /= w_arr.sum()
        weights = w_arr.tolist()

    # Weighted bucket selection
    selected_bucket = random.choices(range(BIAS_BUCKETS), weights=weights, k=1)[0]
    center = _bucket_center(selected_bucket, lo, hi)

    # Add small noise within bucket
    bucket_width = (hi - lo) / BIAS_BUCKETS
    value = center + random.uniform(-bucket_width * 0.3, bucket_width * 0.3)

    if isinstance(lo, float):
        return round(max(lo, min(hi, value)), 2)
    return max(lo, min(hi, int(round(value))))


# =============================================================================
# UNIFIED FITNESS FUNCTION — Single score for all selection decisions
# =============================================================================

def compute_fitness(metrics: dict) -> float:
    """
    Unified fitness score (0-1) for evolution selection and bias weighting.
    Combines: Sharpe, return, walk-forward, Monte Carlo, drawdown, trade frequency.

    Trade frequency pressure: rewards strategies with more trades (up to 100).
    Ultra-low frequency penalty: strategies with < 30 trades get 0.7x multiplier.
    """
    sh = max(0, min(5, metrics.get("sharpe_ratio", 0))) / 5.0           # 0-1 (cap at 5)
    ret = max(0, min(100, metrics.get("total_return_pct", 0))) / 100.0  # 0-1 (cap at 100%)
    wf = max(0, min(2, metrics.get("wf_mean_sharpe", 0))) / 2.0         # 0-1 (cap at 2)
    mc = 1.0 - min(1.0, metrics.get("mc_worst_dd", 1.0))                # 0-1 (lower DD = better)
    dd = 1.0 - min(1.0, metrics.get("max_drawdown", 1.0))               # 0-1 (lower DD = better)

    # Trade frequency pressure — reward higher trade counts (cap at 100)
    trades = metrics.get("trade_count", 0)
    trade_score = min(trades / 100.0, 1.0)

    fitness = (
        0.25 * sh +
        0.15 * ret +
        0.15 * wf +
        0.15 * trade_score +     # NEW: frequency pressure
        0.15 * mc +
        0.15 * dd
    )

    # Ultra-low frequency penalty — discourage dead-end regions
    if trades < 30:
        fitness *= 0.7

    # Overtrading penalty — diminishing returns past 200 trades
    if trades > 200:
        fitness *= 0.95
    if trades > 250:
        fitness *= 0.90

    return round(max(0.0, min(1.0, fitness)), 4)


# =============================================================================
# LINEAGE SELECTION — Track family performance, not just individual
# =============================================================================

def update_lineage(strategy_code: str, parent_id: str, fitness: float):
    """Track lineage scores — average performance per family."""
    lineage = {}
    if LINEAGE_FILE.exists():
        try:
            with open(LINEAGE_FILE) as f:
                lineage = json.load(f)
        except Exception:
            lineage = {}

    # Get root ancestor
    root = parent_id.split("-mut")[0].split("-evo")[0] if parent_id else strategy_code

    if root not in lineage:
        lineage[root] = {"count": 0, "fitness_sum": 0.0, "best": 0.0, "generations": []}

    lineage[root]["count"] += 1
    lineage[root]["fitness_sum"] += fitness
    lineage[root]["best"] = max(lineage[root]["best"], fitness)
    gen_list = lineage[root]["generations"]
    if len(gen_list) < 50:  # cap history
        gen_list.append(round(fitness, 4))

    # Keep only top 200 families
    if len(lineage) > 200:
        sorted_families = sorted(lineage.items(), key=lambda x: -x[1].get("best", 0))
        lineage = dict(sorted_families[:200])

    with open(LINEAGE_FILE, "w") as f:
        json.dump(lineage, f, indent=2)


def get_top_families(n: int = 10) -> list:
    """Get top performing family roots for selection pressure."""
    if not LINEAGE_FILE.exists():
        return []
    try:
        with open(LINEAGE_FILE) as f:
            lineage = json.load(f)
        families = []
        for root, data in lineage.items():
            if data["count"] >= 3:  # need at least 3 descendants
                avg = data["fitness_sum"] / data["count"]
                families.append({"root": root, "avg_fitness": avg, "best": data["best"], "count": data["count"]})
        families.sort(key=lambda x: -x["avg_fitness"])
        return families[:n]
    except Exception:
        return []


def random_params(style: str = "", use_adaptive: bool = True) -> dict:
    """
    Generate parameters using adaptive bias when available, else gaussian bias.
    Adaptive bias learns from passed/near-miss strategies over time.
    """
    # Try adaptive bias first (if enough data collected and not penalized)
    adj = get_control_adjustments()
    bias_ok = adj.get("bias_penalty", 0) < 0.3  # disable adaptive if heavily penalized
    if use_adaptive and style and bias_ok:
        bias = load_bias()
        if style in bias:
            total = sum(
                b.get("count", 0)
                for param_data in bias[style].values()
                for b in param_data.values()
            )
            if total >= BIAS_MIN_SAMPLES:
                # Use learned bias
                params = {}
                for key in PARAM_RANGES:
                    params[key] = biased_sample(style, key)
                return params

    # Fall back to gaussian bias (hardcoded productive centers)
    def biased_int(lo, hi, center=None, sigma=None):
        """Sample from truncated normal centered on productive region."""
        c = center if center is not None else (lo + hi) / 2
        s = sigma if sigma is not None else (hi - lo) / 4
        val = random.gauss(c, s)
        return max(lo, min(hi, int(round(val))))

    def biased_float(lo, hi, center=None, sigma=None):
        c = center if center is not None else (lo + hi) / 2
        s = sigma if sigma is not None else (hi - lo) / 4
        val = random.gauss(c, s)
        return round(max(lo, min(hi, val)), 2)

    # Style-specific bias centers
    # Biased toward LOOSER entries (higher RSI, lower ADX, wider BB)
    # to increase signal density and trade frequency
    if style in ("mean_reversion", "scalping"):
        return {
            "rsi_threshold": biased_int(20, 45, center=38, sigma=5),   # higher = more entries
            "rsi_period": biased_int(5, 21, center=10, sigma=3),
            "fast_ema": biased_int(8, 30, center=12, sigma=4),         # faster = more crosses
            "slow_ema": biased_int(30, 80, center=45, sigma=10),       # tighter gap = more signals
            "adx_threshold": biased_int(10, 30, center=15, sigma=5),   # lower = more entries
            "volume_multiplier": biased_float(1.0, 2.5, center=1.2, sigma=0.3),  # lower = more signals
            "bb_period": biased_int(10, 30, center=15, sigma=4),       # shorter = more responsive
            "z_score_threshold": biased_float(1.0, 3.0, center=1.3, sigma=0.3),  # lower = more entries
        }
    elif style in ("trend_following", "momentum_breakout"):
        return {
            "rsi_threshold": biased_int(20, 45, center=35, sigma=5),   # higher = more entries
            "rsi_period": biased_int(5, 21, center=12, sigma=3),
            "fast_ema": biased_int(8, 30, center=12, sigma=4),         # faster crossovers
            "slow_ema": biased_int(30, 80, center=40, sigma=10),       # tighter gap
            "adx_threshold": biased_int(10, 30, center=13, sigma=4),   # lower = catch weaker trends
            "volume_multiplier": biased_float(1.0, 2.5, center=1.2, sigma=0.3),
            "bb_period": biased_int(10, 30, center=18, sigma=4),
            "z_score_threshold": biased_float(1.0, 3.0, center=1.8, sigma=0.4),
        }
    else:  # volume_orderflow, news, default
        return {
            "rsi_threshold": biased_int(20, 45, center=35, sigma=6),   # higher = more entries
            "rsi_period": biased_int(5, 21, center=10, sigma=4),
            "fast_ema": biased_int(8, 30, center=14, sigma=5),
            "slow_ema": biased_int(30, 80, center=45, sigma=12),
            "adx_threshold": biased_int(10, 30, center=15, sigma=5),   # lower = more entries
            "volume_multiplier": biased_float(1.0, 2.5, center=1.3, sigma=0.3),
            "bb_period": biased_int(10, 30, center=16, sigma=5),
            "z_score_threshold": biased_float(1.0, 3.0, center=1.3, sigma=0.3),
        }


def mutate_params(base_params: dict) -> dict:
    """Mutate existing parameters by ±10-20%."""
    mutated = {}
    for key, (lo, hi) in PARAM_RANGES.items():
        base_val = base_params.get(key, (lo + hi) / 2 if isinstance(lo, float) else (lo + hi) // 2)
        # Mutate by ±10-20%
        factor = random.uniform(0.80, 1.20)
        new_val = base_val * factor
        if isinstance(lo, float):
            new_val = round(max(lo, min(hi, new_val)), 2)
        else:
            new_val = int(max(lo, min(hi, round(new_val))))
        mutated[key] = new_val
    return mutated


def generate_batch_dnas(generation: int, batch_size: int = BATCH_SIZE) -> list[dict]:
    """
    Generate a batch of strategy DNAs.
    60% mutations of existing DNAs (if available), 40% random new.
    """
    # Try to load existing DNAs for mutation base
    base_dnas = []
    if DNA_FILE.exists():
        try:
            with open(DNA_FILE, "r") as f:
                base_dnas = json.load(f)
        except (json.JSONDecodeError, IOError):
            base_dnas = []

    # Micro-evolution: use near-misses as additional mutation seeds
    near_misses = load_near_misses(top_n=10)

    # Split with safeguards + adaptive control adjustments
    adj = get_control_adjustments()
    base_random = max(MIN_RANDOM_RATIO, 0.4) + adj.get("exploration_boost", 0)
    base_evolve = min(MAX_EVOLUTION_RATIO, 0.2) if near_misses else 0

    # If bias is penalized, reduce evolution (bias-driven) and boost random
    if adj.get("bias_penalty", 0) > 0:
        base_evolve = max(0, base_evolve - adj["bias_penalty"] * 0.3)

    evolve_ratio = base_evolve
    random_ratio = min(0.7, base_random)  # cap at 70% random
    mutate_ratio = max(0.1, 1.0 - evolve_ratio - random_ratio)  # at least 10% mutation

    n_mutate = int(batch_size * mutate_ratio) if base_dnas else 0
    n_evolve = int(batch_size * evolve_ratio)
    n_random = batch_size - n_mutate - n_evolve

    batch = []
    seq = 0

    # Mutations
    for i in range(n_mutate):
        base = random.choice(base_dnas)
        style = base.get("style", weighted_style_choice())
        base_p = base.get("parameter_ranges", base.get("parameters", {}))
        # Flatten ranges to midpoints if needed, only for keys we recognize
        flat = {}
        for k, v in base_p.items():
            if k not in PARAM_RANGES:
                continue
            if isinstance(v, list) and len(v) == 2:
                try:
                    flat[k] = (float(v[0]) + float(v[1])) / 2
                except (ValueError, TypeError):
                    continue
            elif isinstance(v, (int, float)):
                flat[k] = float(v)
        params = mutate_params(flat)
        seq += 1
        batch.append({
            "strategy_code": f"RND-G{generation}-{seq:05d}",
            "style": style,
            "parameters": params,
            "parent_id": base.get("strategy_code", "base_dna"),
            "lineage_generation": 0,
        })

    # Micro-evolution from near-misses (tighter mutations — these almost passed)
    # Mutation decay: early = ±10%, later = ±3-5% + control boost
    adj = get_control_adjustments()
    boost = adj.get("mutation_range_boost", 0)
    if generation > MUTATION_DECAY_GEN:
        mut_lo, mut_hi = 0.95 - boost, 1.05 + boost  # ±5% + boost
    else:
        mut_lo, mut_hi = 0.90 - boost, 1.10 + boost  # ±10% + boost

    for i in range(n_evolve):
        seed = random.choice(near_misses)
        seed_params = seed.get("parameters", {})
        evolved = {}
        for k, (lo, hi) in PARAM_RANGES.items():
            base_val = seed_params.get(k, (lo + hi) / 2 if isinstance(lo, float) else (lo + hi) // 2)
            factor = random.uniform(mut_lo, mut_hi)
            new_val = base_val * factor
            if isinstance(lo, float):
                evolved[k] = round(max(lo, min(hi, new_val)), 2)
            else:
                evolved[k] = int(max(lo, min(hi, round(new_val))))
        seq += 1
        batch.append({
            "strategy_code": f"EVO-G{generation}-{seq:05d}",
            "style": seed.get("style", weighted_style_choice()),
            "parameters": evolved,
            "parent_id": seed.get("strategy_code", "unknown"),  # lineage tracking
            "lineage_generation": seed.get("generation", 0),
        })

    # ── Lineage promotion: inject focused evolution strategies ──
    n_promoted = 0
    try:
        from services.lineage_promotion import get_promotion_budget, generate_promoted_strategies
        promo_budget = get_promotion_budget()
        if promo_budget > 0:
            n_promoted = max(1, int(batch_size * promo_budget))
            promo_strats = generate_promoted_strategies(generation, n_promoted)
            batch.extend(promo_strats)
            n_random = max(1, n_random - len(promo_strats))
            if promo_strats:
                log.info(f"  🏆 PROMOTION: {len(promo_strats)} focused evolution strategies injected")
    except Exception as e:
        log.debug(f"Lineage promotion unavailable: {e}")

    # Random new (with optional search expansion)
    exp = _get_expansion()
    for i in range(n_random):
        seq += 1
        style = weighted_style_choice()
        params = random_params(style)

        # If expansion is active, expand a portion of random strategies
        is_expanded = False
        if exp and exp["should_expand"](i, n_random):
            params = exp["expand_params"](style, params)
            is_expanded = True

        code_prefix = "EXP" if is_expanded else "RND"
        batch.append({
            "strategy_code": f"{code_prefix}-G{generation}-{seq:05d}",
            "style": style,
            "parameters": params,
            "expanded": is_expanded,
        })

    # Convergence detector — if params are too similar, inject diversity
    if len(batch) >= 5:
        import numpy as np
        for param_key in ("rsi_threshold", "adx_threshold", "fast_ema"):
            vals = [d["parameters"].get(param_key, 0) for d in batch if param_key in d.get("parameters", {})]
            if len(vals) >= 5:
                lo, hi = PARAM_RANGES.get(param_key, (0, 100))
                param_range = hi - lo
                if param_range > 0:
                    relative_std = np.std(vals) / param_range
                    if relative_std < CONVERGENCE_THRESHOLD:
                        for idx in random.sample(range(len(batch)), min(2, len(batch))):
                            s = weighted_style_choice()
                            batch[idx] = {
                                "strategy_code": f"DIV-G{generation}-{random.randint(10000,99999)}",
                                "style": s,
                                "parameters": random_params(s, use_adaptive=False),
                            }
                        log.info(f"  Convergence detected on {param_key} (std={relative_std:.2f}) — injected diversity")
                        break

    # Periodic shock injection — adaptive frequency (default every 50, control can increase)
    adj = get_control_adjustments()
    shock_freq = max(5, int(50 / adj.get("shock_frequency_mult", 1.0)))  # hard floor: every 5 gens minimum
    if generation % shock_freq == 0 and generation > 0:
        n_shocks = max(1, int(len(batch) * 0.15))  # 15% of batch = extreme random
        for idx in random.sample(range(len(batch)), min(n_shocks, len(batch))):
            s = random.choice(list(STYLE_WEIGHTS.keys()))  # truly random style, not weighted
            # Extreme params — edges of ranges
            extreme_params = {}
            for k, (lo, hi) in PARAM_RANGES.items():
                if isinstance(lo, float):
                    extreme_params[k] = round(random.choice([
                        random.uniform(lo, lo + (hi - lo) * 0.2),  # low extreme
                        random.uniform(hi - (hi - lo) * 0.2, hi),  # high extreme
                    ]), 2)
                else:
                    extreme_params[k] = random.choice([
                        random.randint(lo, lo + (hi - lo) // 5),
                        random.randint(hi - (hi - lo) // 5, hi),
                    ])
            batch[idx] = {
                "strategy_code": f"SHOCK-G{generation}-{random.randint(10000,99999)}",
                "style": s,
                "parameters": extreme_params,
            }
        log.info(f"  ⚡ SHOCK INJECTION: {n_shocks} extreme-param strategies injected (gen {generation})")

    # Forced diversity seeds — from control layer AND diversity stabilizer
    cs = _load_control_state()
    forced_seeds = cs.get("forced_diversity_seeds", 0)
    cap_style = cs.get("dominant_style_cap")

    # Also read from diversity stabilizer
    try:
        from services.diversity_stabilizer import _load_state as _load_div_state
        div_state = _load_div_state()
        forced_seeds = max(forced_seeds, div_state.get("forced_diversity_seeds", 0))
        if not cap_style:
            # Infer dominant style from stabilizer's adjustments
            swa = div_state.get("style_weight_adjustments", {})
            if swa:
                cap_style = min(swa, key=swa.get)  # most penalized = dominant
    except Exception:
        pass

    if forced_seeds > 0 and cap_style:
        non_dominant = [s for s in STYLE_WEIGHTS.keys() if s != cap_style]
        if non_dominant:
            for i in range(min(forced_seeds, len(batch))):
                s = random.choice(non_dominant)
                idx = random.randint(0, len(batch) - 1)
                batch[idx] = {
                    "strategy_code": f"DIV-G{generation}-{random.randint(10000,99999)}",
                    "style": s,
                    "parameters": random_params(s, use_adaptive=False),
                }
            log.info(f"  🌈 DIVERSITY INJECTION: {forced_seeds} forced non-{cap_style} seeds")

    return batch


# =============================================================================
# STATE MANAGEMENT
# =============================================================================

def load_state() -> dict:
    """Load generation counter from state file."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"generation": 0, "total_strategies_tested": 0, "total_passed": 0}


def save_state(state: dict):
    """Save state to disk."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    tmp.rename(STATE_FILE)


# =============================================================================
# WORKER CODE — Everything below runs in a subprocess
# =============================================================================

def _compute_rsi(close: "np.ndarray", period: int = 14) -> "np.ndarray":
    """Wilder's RSI using numpy."""
    import numpy as np
    close = close.astype(np.float64)  # float32 loses precision on large prices
    diff = np.diff(close, prepend=close[0])
    gain = np.where(diff > 0, diff, 0.0)
    loss = np.where(diff < 0, -diff, 0.0)

    # Wilder's smoothing (EMA with alpha = 1/period)
    alpha = 1.0 / period
    avg_gain = np.zeros_like(close)
    avg_loss = np.zeros_like(close)

    # Seed with SMA
    if len(close) > period:
        avg_gain[period] = np.mean(gain[1:period + 1])
        avg_loss[period] = np.mean(loss[1:period + 1])
        for i in range(period + 1, len(close)):
            avg_gain[i] = avg_gain[i - 1] * (1 - alpha) + gain[i] * alpha
            avg_loss[i] = avg_loss[i - 1] * (1 - alpha) + loss[i] * alpha

    rs = np.divide(avg_gain, avg_loss, out=np.ones_like(close) * 100.0,
                   where=avg_loss > 1e-10)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi[:period + 1] = 50.0  # Not enough data
    return rsi


def _compute_ema(data: "np.ndarray", period: int) -> "np.ndarray":
    """Exponential moving average."""
    import numpy as np
    data = data.astype(np.float64)
    alpha = 2.0 / (period + 1)
    ema = np.zeros(len(data), dtype=np.float64)
    ema[0] = data[0]
    for i in range(1, len(data)):
        ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
    return ema


def _compute_sma(data: "np.ndarray", period: int) -> "np.ndarray":
    """Simple moving average using cumsum trick."""
    import numpy as np
    cs = np.cumsum(data)
    sma = np.zeros_like(data)
    sma[:period] = cs[:period] / np.arange(1, period + 1)
    sma[period:] = (cs[period:] - cs[:-period]) / period
    return sma


def _compute_rolling_std(data: "np.ndarray", period: int) -> "np.ndarray":
    """Rolling standard deviation."""
    import numpy as np
    std = np.zeros_like(data)
    for i in range(period - 1, len(data)):
        std[i] = np.std(data[max(0, i - period + 1):i + 1])
    return std


def _compute_bb(close: "np.ndarray", period: int = 20, n_std: float = 2.0):
    """Bollinger Bands: returns (upper, mid, lower)."""
    mid = _compute_sma(close, period)
    std = _compute_rolling_std(close, period)
    upper = mid + n_std * std
    lower = mid - n_std * std
    return upper, mid, lower


def _compute_adx(high: "np.ndarray", low: "np.ndarray", close: "np.ndarray",
                 period: int = 14) -> "np.ndarray":
    """Standard ADX calculation."""
    import numpy as np
    high = high.astype(np.float64)
    low = low.astype(np.float64)
    close = close.astype(np.float64)
    n = len(close)
    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)

    for i in range(1, n):
        h_l = high[i] - low[i]
        h_pc = abs(high[i] - close[i - 1])
        l_pc = abs(low[i] - close[i - 1])
        tr[i] = max(h_l, h_pc, l_pc)

        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0

    # Wilder's smoothing
    alpha = 1.0 / period
    atr = np.zeros(n)
    atr[period] = np.mean(tr[1:period + 1])
    s_plus = np.zeros(n)
    s_plus[period] = np.mean(plus_dm[1:period + 1])
    s_minus = np.zeros(n)
    s_minus[period] = np.mean(minus_dm[1:period + 1])

    for i in range(period + 1, n):
        atr[i] = atr[i - 1] * (1 - alpha) + tr[i] * alpha
        s_plus[i] = s_plus[i - 1] * (1 - alpha) + plus_dm[i] * alpha
        s_minus[i] = s_minus[i - 1] * (1 - alpha) + minus_dm[i] * alpha

    di_plus = np.divide(s_plus, atr, out=np.zeros(n), where=atr > 1e-10) * 100
    di_minus = np.divide(s_minus, atr, out=np.zeros(n), where=atr > 1e-10) * 100
    di_sum = di_plus + di_minus
    dx = np.divide(np.abs(di_plus - di_minus), di_sum, out=np.zeros(n),
                   where=di_sum > 1e-10) * 100

    adx = np.zeros(n)
    start = 2 * period
    if start < n:
        adx[start] = np.mean(dx[period:start + 1]) if start > period else dx[start]
        for i in range(start + 1, n):
            adx[i] = adx[i - 1] * (1 - alpha) + dx[i] * alpha

    return adx


def _generate_signals(style: str, params: dict, close: "np.ndarray",
                      high: "np.ndarray", low: "np.ndarray",
                      volume: "np.ndarray") -> "np.ndarray":
    """
    Vectorized signal generation. Returns position array (1=long, 0=flat).
    NO Python for-loops over bars for signal logic — uses numpy boolean arrays.
    """
    import numpy as np

    n = len(close)
    rsi = _compute_rsi(close, params.get("rsi_period", 14))
    bb_upper, bb_mid, bb_lower = _compute_bb(close, params.get("bb_period", 20))
    ema_fast = _compute_ema(close, params.get("fast_ema", 20))
    ema_slow = _compute_ema(close, params.get("slow_ema", 50))
    adx = _compute_adx(high, low, close)
    vol_sma = _compute_sma(volume, 20)
    vol_mult = params.get("volume_multiplier", 1.5)
    z_thresh = params.get("z_score_threshold", 2.0)
    sma_20 = _compute_sma(close, 20)
    std_20 = _compute_rolling_std(close, 20)
    z_score = np.divide(close - sma_20, std_20, out=np.zeros(n), where=std_20 > 1e-10)

    rsi_thresh = params.get("rsi_threshold", 30)
    adx_thresh = params.get("adx_threshold", 25)

    # Entry and exit conditions (vectorized boolean arrays)
    # Each style has archetype constraints to prevent nonsense combos
    if style == "mean_reversion":
        # Archetype: RSI extreme + BB touch, LOW trend (ADX < 30 = ranging market)
        entry = (rsi < rsi_thresh) & (close < bb_lower) & (adx < 30)
        exit_sig = (rsi > 50) | (close > bb_mid)
    elif style == "scalping":
        # Archetype: tight BB + RSI extreme + volume, LOW ADX (range-bound)
        entry = (rsi < 30) & (close <= bb_lower) & (volume > vol_sma * vol_mult) & (adx < 30)
        exit_sig = (rsi > 50) | (close > bb_mid)
    elif style == "momentum_breakout":
        entry = (ema_fast > ema_slow) & (adx > adx_thresh) & (volume > vol_sma * vol_mult)
        exit_sig = (ema_fast < ema_slow) | (adx < adx_thresh * 0.7)
    elif style == "trend_following":
        entry = (ema_fast > ema_slow) & (adx > adx_thresh) & (close > ema_fast)
        exit_sig = (ema_fast < ema_slow) | (close < ema_slow)
    elif style == "volume_orderflow":
        entry = (z_score < -z_thresh) & (volume > vol_sma * vol_mult)
        exit_sig = (z_score > 0) | (rsi > 60)
    else:
        # News or unknown — use mean reversion as fallback
        entry = (rsi < rsi_thresh) & (close < bb_lower)
        exit_sig = (rsi > 50) | (close > bb_mid)

    # ── Search Expansion Filters (applied BEFORE state machine) ──
    # These reduce entry signals, never add them — safe by construction
    if params.get("expanded", False) or params.get("session_filter_enabled", 0) == 1:
        try:
            from services.search_expansion import apply_session_filter, apply_atr_regime, apply_dynamic_thresholds
            # Session filter needs timestamps — caller must provide via params["_timestamps"]
            timestamps = params.get("_timestamps")
            if timestamps is not None and params.get("session_filter_enabled", 0) == 1:
                entry = apply_session_filter(entry, timestamps, params)
            # ATR regime filter
            if params.get("atr_regime_enabled", 0) == 1:
                entry = apply_atr_regime(entry, high, low, close, params)
        except ImportError:
            pass

    # Convert entry/exit to position array using state machine
    # We need a loop here but it's on boolean arrays, not price data
    max_hold = params.get("max_hold_bars", 0) if params.get("max_hold_enabled", 0) == 1 else 0
    position = np.zeros(n, dtype=np.float32)
    in_trade = False
    bars_held = 0
    for i in range(1, n):
        if not in_trade and entry[i]:
            in_trade = True
            bars_held = 1
            position[i] = 1.0
        elif in_trade and (exit_sig[i] or (max_hold > 0 and bars_held >= max_hold)):
            in_trade = False
            bars_held = 0
            position[i] = 0.0
        elif in_trade:
            bars_held += 1
            position[i] = 1.0

    return position


def _backtest_vectorized(close: "np.ndarray", position: "np.ndarray") -> dict:
    """
    Backtest with unified exit engine integration.
    Uses ExitEngine for 5% profit trigger + adaptive trailing.
    """
    import numpy as np
    import sys as _sys
    if str(BASE_DIR) not in _sys.path:
        _sys.path.insert(0, str(BASE_DIR))
    from services.exit_engine import ExitEngine, EXIT_CONFIG

    n = len(close)
    exit_engine = ExitEngine(EXIT_CONFIG)

    # Walk through bars, apply exit engine on each trade
    trade_pnls = []
    trade_metrics = []
    equity_values = [1.0]
    current_equity = 1.0
    in_trade = False
    entry_price = 0.0

    for i in range(1, n):
        # Entry: position goes from 0 to 1
        if not in_trade and position[i] > 0.5 and (i == 0 or position[i-1] < 0.5):
            in_trade = True
            entry_price = close[i]
            exit_engine.on_entry(entry_price)

        # While in trade: check exit engine + signal exit
        elif in_trade:
            exit_reason = exit_engine.update(close[i])
            signal_exit = position[i] < 0.5  # strategy says exit

            if exit_reason or signal_exit:
                # Close trade
                exit_price = close[i]
                pnl_pct = (exit_price - entry_price) / entry_price if entry_price > 0 else 0
                trade_pnls.append(pnl_pct)
                trade_metrics.append(exit_engine.get_metrics(exit_price))

                current_equity *= (1 + pnl_pct)
                current_equity = max(current_equity, 0.001)
                in_trade = False

        equity_values.append(current_equity)

    # Close any open trade at end
    if in_trade and entry_price > 0:
        pnl_pct = (close[-1] - entry_price) / entry_price
        trade_pnls.append(pnl_pct)
        trade_metrics.append(exit_engine.get_metrics(close[-1]))
        current_equity *= (1 + pnl_pct)

    trade_pnls_arr = np.array(trade_pnls) if trade_pnls else np.array([0.0])
    trade_count = len(trade_pnls)

    if trade_count == 0:
        return {
            "trade_count": 0, "win_rate": 0.0, "sharpe_ratio": 0.0,
            "max_drawdown": 0.0, "profit_factor": 0.0, "total_return_pct": 0.0,
        }

    wins = int(np.sum(trade_pnls_arr > 0))
    win_rate = wins / trade_count if trade_count > 0 else 0.0
    gross_profit = float(np.sum(trade_pnls_arr[trade_pnls_arr > 0])) if np.any(trade_pnls_arr > 0) else 0.0
    gross_loss = float(np.abs(np.sum(trade_pnls_arr[trade_pnls_arr < 0]))) if np.any(trade_pnls_arr < 0) else 0.0

    # Sharpe ratio (annualized from trade returns)
    mean_ret = float(np.mean(trade_pnls_arr))
    std_ret = float(np.std(trade_pnls_arr))
    # Estimate trades per year from data
    trades_per_year = max(1, min(trade_count * 252 / max(n, 1), 10000))
    sharpe = float(mean_ret / std_ret * np.sqrt(trades_per_year)) if std_ret > 1e-10 else 0.0

    # Max drawdown from equity curve
    equity = np.array(equity_values)
    peak = np.maximum.accumulate(equity)
    dd = np.where(peak > 0, (equity - peak) / peak, 0)
    max_dd = float(np.abs(np.min(dd)))

    # Profit factor
    pf = float(gross_profit / gross_loss) if gross_loss > 1e-10 else (
        999.0 if gross_profit > 0 else 0.0)

    total_return = float((equity[-1] / equity[0] - 1.0) * 100) if len(equity) > 0 else 0.0

    # Exit metrics summary
    avg_capture = 0.0
    target_hit_count = 0
    if trade_metrics:
        captures = [m.get("profit_capture_pct", 0) for m in trade_metrics if m]
        avg_capture = sum(captures) / len(captures) if captures else 0
        target_hit_count = sum(1 for m in trade_metrics if m.get("target_hit"))

    return {
        "trade_count": trade_count,
        "win_rate": round(win_rate, 4),
        "sharpe_ratio": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
        "profit_factor": round(pf, 4),
        "total_return_pct": round(total_return, 4),
        "avg_profit_capture_pct": round(float(avg_capture), 1),
        "target_hit_count": int(target_hit_count),
        "target_hit_rate": round(float(target_hit_count / max(trade_count, 1)), 3),
        "trade_density": round(float(trade_count / max(n, 1)), 6),
    }


def _monte_carlo(close: "np.ndarray", position: "np.ndarray",
                 n_sims: int = MC_SIMS) -> dict:
    """
    Monte Carlo simulation with streaming aggregates.
    NEVER stores 200 equity curves — streams stats only.
    """
    import numpy as np

    returns = np.clip(np.diff(close) / close[:-1], -0.5, 0.5)
    strat_returns = returns * position[:-1]
    active = strat_returns[position[:-1] > 0.5]

    if len(active) < 10:
        return {"mc_mean_return": 0.0, "mc_worst_dd": 0.0}

    # Stream aggregates
    sum_returns = 0.0
    worst_dd = 0.0

    for _ in range(n_sims):
        # Shuffle trade returns
        shuffled = np.random.permutation(active)
        # Compute equity curve inline (overflow-safe)
        eq = np.exp(np.cumsum(np.log1p(np.clip(shuffled, -0.99, 10.0))))
        total_ret = float(eq[-1] - 1.0)
        sum_returns += total_ret

        # Max drawdown of this sim
        peak = np.maximum.accumulate(eq)
        dd = float(np.min((eq - peak) / np.where(peak > 1e-10, peak, 1.0)))
        worst_dd = min(worst_dd, dd)

        # Don't store eq — it's gone after this iteration
        del eq, shuffled, peak

    return {
        "mc_mean_return": round(sum_returns / n_sims * 100, 4),
        "mc_worst_dd": round(abs(worst_dd), 4),
    }


def _walk_forward(close: "np.ndarray", high: "np.ndarray", low: "np.ndarray",
                  volume: "np.ndarray", style: str, params: dict,
                  n_folds: int = WF_FOLDS) -> dict:
    """
    Walk-forward analysis with N folds.
    Each fold: train on 80%, test on 20%. Sequential, non-overlapping test sets.
    Returns mean Sharpe across folds and degradation metric.
    """
    import numpy as np

    n = len(close)
    fold_size = n // n_folds
    if fold_size < 100:
        return {"wf_mean_sharpe": 0.0, "wf_degradation": 1.0}

    sharpes = []
    for fold in range(n_folds):
        # Test set for this fold
        test_start = fold * fold_size
        test_end = min(test_start + fold_size, n)

        # Train set: everything before test
        if test_start < 50:
            continue

        test_close = close[test_start:test_end]
        test_high = high[test_start:test_end]
        test_low = low[test_start:test_end]
        test_vol = volume[test_start:test_end]

        if len(test_close) < 50:
            continue

        pos = _generate_signals(style, params, test_close, test_high, test_low, test_vol)
        metrics = _backtest_vectorized(test_close, pos)
        sharpes.append(metrics["sharpe_ratio"])

        del test_close, test_high, test_low, test_vol, pos, metrics

    if not sharpes:
        return {"wf_mean_sharpe": 0.0, "wf_degradation": 1.0}

    mean_sharpe = float(np.mean(sharpes))
    # Degradation: ratio of last fold Sharpe to first fold Sharpe
    if abs(sharpes[0]) > 1e-10:
        degradation = float(sharpes[-1] / sharpes[0])
    else:
        degradation = 0.0

    return {
        "wf_mean_sharpe": round(mean_sharpe, 4),
        "wf_degradation": round(degradation, 4),
    }


def _sanity_check(metrics: dict) -> bool:
    """Return True if results look plausible (pass sanity check)."""
    tc = metrics.get("trade_count", 0)
    wr = metrics.get("win_rate", 0)
    dd = metrics.get("max_drawdown", 0)
    pf = metrics.get("profit_factor", 0)
    sh = metrics.get("sharpe_ratio", 0)
    ret = metrics.get("total_return_pct", 0)

    # Reject impossible results
    if wr >= 0.95 and tc >= 50:
        return False
    if dd == 0 and tc >= 20:
        return False
    if pf > 50 or sh > 10:
        return False
    if ret > 10000:
        return False

    return True


def _darwin_check(metrics: dict, n_bars: int = 0) -> tuple[str, bool]:
    """
    Two-tier Darwin check with adaptive trade minimum.
    Returns (tier, passed) where tier is "production", "exploration", or "rejected".
    
    Adaptive min trades: max(30, int(n_bars * 0.05))
    - Production: trades >= max(100, adaptive) + strict criteria
    - Exploration: trades >= max(30, adaptive) + relaxed criteria (NOT tradable, for learning)
    """
    tc = metrics.get("trade_count", 0)
    adaptive_min = max(30, int(n_bars * 0.05)) if n_bars > 0 else 30
    
    # Production tier — strict
    prod_min = max(DARWIN_PRODUCTION["min_trades"], adaptive_min)
    if (tc >= prod_min
        and metrics.get("win_rate", 0) >= DARWIN_PRODUCTION["min_win_rate"]
        and metrics.get("sharpe_ratio", 0) >= DARWIN_PRODUCTION["min_sharpe"]
        and metrics.get("max_drawdown", 1.0) <= DARWIN_PRODUCTION["max_drawdown"]
        and metrics.get("profit_factor", 0) >= DARWIN_PRODUCTION["min_profit_factor"]):
        return "production", True
    
    # Exploration tier — relaxed, NOT tradable
    explore_min = max(DARWIN_EXPLORATION["min_trades"], min(adaptive_min, 50))
    if (tc >= explore_min
        and metrics.get("win_rate", 0) >= DARWIN_EXPLORATION["min_win_rate"]
        and metrics.get("sharpe_ratio", 0) >= DARWIN_EXPLORATION["min_sharpe"]
        and metrics.get("max_drawdown", 1.0) <= DARWIN_EXPLORATION["max_drawdown"]
        and metrics.get("profit_factor", 0) >= DARWIN_EXPLORATION["min_profit_factor"]):
        return "exploration", True
    
    return "rejected", False


def worker_process(batch_json: str):
    """
    WORKER ENTRY POINT — runs in a subprocess.
    Processes a batch of strategies, writes results to JSONL, then exits.
    This function IS the subprocess — when it returns, the process dies.
    """
    import numpy as np
    import pandas as pd

    batch = json.loads(batch_json)
    strategies = batch["strategies"]
    asset = batch["asset"]
    timeframe = batch["timeframe"]
    generation = batch["generation"]

    # Load data ONCE for this batch
    parquet_path = DATA_DIR / asset / f"{timeframe}.parquet"
    if not parquet_path.exists():
        log.warning(f"Worker: missing data file {parquet_path}")
        return

    df = pd.read_parquet(
        parquet_path,
        columns=["open", "high", "low", "close", "volume"],
    )
    # Cast to float32 for memory efficiency
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(np.float32)

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    volume = df["volume"].values
    open_px = df["open"].values
    timestamps = df.index  # keep index for session filters

    # Free the DataFrame — we only need numpy arrays
    del df
    gc.collect()

    # Rejection stats tracking
    rejection_stats = {
        "too_sparse": 0, "overtrading": 0, "always_in_market": 0,
        "negative_sharpe": 0, "extreme_dd": 0, "low_trades": 0,
        "sanity_filter": 0, "passed_production": 0, "passed_exploration": 0,
        "rejected_darwin": 0,
    }

    # Process each strategy in the batch
    for dna in strategies:
        strategy_code = dna["strategy_code"]
        style = dna["style"]
        params = dna["parameters"]

        try:
            # 1. Generate signals
            # Inject timestamps for expanded strategies with session filters
            if params.get("session_filter_enabled", 0) == 1:
                params["_timestamps"] = timestamps
                params["expanded"] = True
            # Apply dynamic thresholds if enabled
            if params.get("dynamic_threshold_enabled", 0) == 1:
                try:
                    from services.search_expansion import apply_dynamic_thresholds
                    params = apply_dynamic_thresholds(params)
                except ImportError:
                    pass
            position = _generate_signals(style, params, close, high, low, volume)
            # Clean up non-serializable reference
            params.pop("_timestamps", None)

            # 1b. Pre-filter heuristics — cheap rejection before expensive backtest
            n_signals = int(np.sum(np.diff(position) > 0.5))
            n_bars = len(close)
            time_in_market = float(np.sum(position > 0.5)) / max(n_bars, 1)

            signal_density = n_signals / max(n_bars, 1)

            if n_signals < MIN_SIGNAL_DENSITY:
                rejection_stats["too_sparse"] += 1
                del position
                continue
            if signal_density < 0.002:
                rejection_stats["too_sparse"] += 1
                del position
                continue
            if n_signals > n_bars * 0.5:
                rejection_stats["overtrading"] += 1
                del position
                continue
            if time_in_market > 0.70:
                rejection_stats["always_in_market"] += 1
                del position
                continue

            # 2. Backtest
            metrics = _backtest_vectorized(close, position)

            # 2b. Edge sanity — fast rejection before expensive MC/WF
            if metrics.get("sharpe_ratio", 0) < -1.0:
                rejection_stats["negative_sharpe"] += 1
                del position, metrics
                gc.collect()
                continue
            if metrics.get("max_drawdown", 1.0) > 0.80:
                rejection_stats["extreme_dd"] += 1
                del position, metrics
                gc.collect()
                continue
            if metrics.get("trade_count", 0) < 25:
                rejection_stats["low_trades"] += 1
                del position, metrics
                gc.collect()
                continue

            # 3. Sanity check
            if not _sanity_check(metrics):
                rejection_stats["sanity_filter"] += 1
                log.info(f"  {strategy_code}: REJECTED (sanity filter)")
                result = {
                    "strategy_code": strategy_code,
                    "asset": asset,
                    "timeframe": timeframe,
                    "style": style,
                    "generation": generation,
                    "trade_count": metrics["trade_count"],
                    "win_rate": metrics["win_rate"],
                    "sharpe_ratio": metrics["sharpe_ratio"],
                    "max_drawdown": metrics["max_drawdown"],
                    "profit_factor": metrics["profit_factor"],
                    "total_return_pct": metrics["total_return_pct"],
                    "passed_darwin": False,
                    "mc_mean_return": 0.0,
                    "mc_worst_dd": 0.0,
                    "wf_mean_sharpe": 0.0,
                    "wf_degradation": 0.0,
                    "avg_profit_capture_pct": metrics.get("avg_profit_capture_pct", 0),
                    "target_hit_count": metrics.get("target_hit_count", 0),
                    "target_hit_rate": metrics.get("target_hit_rate", 0),
                    "rejected_reason": "sanity_filter",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                _append_result(result)
                del position, metrics
                gc.collect()
                continue

            # 4. Monte Carlo (only if enough trades)
            if metrics["trade_count"] >= 20:
                mc = _monte_carlo(close, position)
            else:
                mc = {"mc_mean_return": 0.0, "mc_worst_dd": 0.0}

            # 5. Walk-forward
            wf = _walk_forward(close, high, low, volume, style, params)

            # 6. Darwin check — two tiers
            n_bars = len(close)
            tier, passed = _darwin_check(metrics, n_bars)

            # 7. Write result IMMEDIATELY
            result = {
                "strategy_code": strategy_code,
                "asset": asset,
                "timeframe": timeframe,
                "style": style,
                "generation": generation,
                "trade_count": metrics["trade_count"],
                "win_rate": metrics["win_rate"],
                "sharpe_ratio": metrics["sharpe_ratio"],
                "max_drawdown": metrics["max_drawdown"],
                "profit_factor": metrics["profit_factor"],
                "total_return_pct": metrics["total_return_pct"],
                "passed_darwin": tier == "production",
                "darwin_tier": tier,
                "mc_mean_return": mc["mc_mean_return"],
                "mc_worst_dd": mc["mc_worst_dd"],
                "wf_mean_sharpe": wf["wf_mean_sharpe"],
                "wf_degradation": wf["wf_degradation"],
            }

            # 7a. Exit engine metrics
            result["avg_profit_capture_pct"] = metrics.get("avg_profit_capture_pct", 0)
            result["target_hit_count"] = metrics.get("target_hit_count", 0)
            result["target_hit_rate"] = metrics.get("target_hit_rate", 0)

            # 7b. Tag expanded strategies
            if dna.get("expanded", False):
                result["expanded"] = True
                result["session_filter"] = params.get("session_name", "")
                result["atr_regime_enabled"] = params.get("atr_regime_enabled", 0)
                result["dynamic_threshold_enabled"] = params.get("dynamic_threshold_enabled", 0)

            # 7b. Compute unified fitness + update adaptive bias + lineage
            fitness = compute_fitness({**metrics, **mc, **wf})
            result["fitness"] = fitness
            result["parent_id"] = dna.get("parent_id", "")
            result["timestamp"] = datetime.now(timezone.utc).isoformat()

            _append_result(result)

            if tier in ("production", "exploration") or (metrics["trade_count"] >= 20 and fitness > 0.15):
                update_bias(style, params, fitness)
                parent = dna.get("parent_id", "")
                if parent:
                    update_lineage(strategy_code, parent, fitness)

            # 8. Near-miss retention — store promising candidates for future evolution
            if tier == "rejected" and metrics["trade_count"] >= 20:
                sh = metrics.get("sharpe_ratio", 0)
                dd = metrics.get("max_drawdown", 1)
                wr = metrics.get("win_rate", 0)
                if sh > 0.3 and dd < 0.40 and wr > 0.35:
                    # Near miss — save as evolution seed
                    _save_near_miss({
                        "strategy_code": strategy_code,
                        "style": style, "asset": asset, "timeframe": timeframe,
                        "parameters": params,
                        "sharpe": sh, "dd": dd, "wr": wr,
                        "trades": metrics["trade_count"],
                        "avg_profit_capture_pct": metrics.get("avg_profit_capture_pct", 0),
                        "target_hit_rate": metrics.get("target_hit_rate", 0),
                        "generation": generation,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    rejection_stats.setdefault("near_miss_saved", 0)
                    rejection_stats["near_miss_saved"] += 1

            # 9. Parameter cluster tracking — log productive regions
            if tier in ("production", "exploration"):
                _track_param_cluster(style, params, metrics)

            # ── CANDIDATE PERSISTENCE — store full artifact for production gate ──
            try:
                from services.candidate_store import should_persist, persist_candidate
                if should_persist(tier, fitness=fitness, sharpe=metrics.get("sharpe_ratio", 0)):
                    persist_candidate(
                        strategy_code=strategy_code,
                        style=style,
                        params=params,
                        asset=asset,
                        timeframe=timeframe,
                        generation=generation,
                        metrics=metrics,
                        mc=mc,
                        wf=wf,
                        fitness=fitness,
                        tier=tier,
                        close=close,
                        position=position,
                        parent_id=dna.get("parent_id", ""),
                        lineage_id=dna.get("lineage_id", ""),
                    )
            except Exception as e:
                log.debug(f"Candidate persistence skipped: {e}")

            if tier == "production":
                rejection_stats["passed_production"] += 1
                log.info(f"  {strategy_code} ({style}): 🟢 PRODUCTION | trades={metrics['trade_count']} wr={metrics['win_rate']:.2f} sharpe={metrics['sharpe_ratio']:.2f} dd={metrics['max_drawdown']:.2f}")
                try:
                    from services.central_alerts import alert_darwin_pass
                    alert_darwin_pass(strategy_code, "production", metrics)
                except Exception:
                    pass

                # Production Gate: evaluate promoted strategies with high fitness
                if dna.get("promoted", False) and fitness >= 0.90:
                    try:
                        from services.production_gate import evaluate as gate_evaluate, pre_filter, format_approval_alert
                        candidate = {
                            **metrics,
                            "strategy_code": strategy_code,
                            "style": style,
                            "parameters": params,
                            "fitness": fitness,
                            "lineage_id": dna.get("lineage_id", ""),
                            "survival_depth": dna.get("survival_depth", 0),
                            "stability_score": dna.get("stability_score", 0),
                        }
                        pf_ok, pf_reason = pre_filter(candidate)
                        if pf_ok:
                            # Compute per-trade returns for deep MC + prop sim
                            trade_returns = []
                            in_pos = False
                            entry_price = 0.0
                            for bi in range(len(close)):
                                if not in_pos and position[bi] > 0.5:
                                    in_pos = True
                                    entry_price = close[bi]
                                elif in_pos and position[bi] < 0.5:
                                    in_pos = False
                                    if entry_price > 0:
                                        trade_returns.append(float((close[bi] - entry_price) / entry_price))

                            gate_result = gate_evaluate(
                                candidate, returns=trade_returns,
                                close=close, high=high, low=low, volume=volume,
                                generation=generation,
                            )
                            log.info(f"  🚪 GATE: {strategy_code} → {gate_result['status']} (score={gate_result['production_score']:.2f})")
                    except Exception as e:
                        log.debug(f"Production gate skipped: {e}")
            elif tier == "exploration":
                rejection_stats["passed_exploration"] += 1
                log.info(f"  {strategy_code} ({style}): 🟡 EXPLORATION | trades={metrics['trade_count']} wr={metrics['win_rate']:.2f} sharpe={metrics['sharpe_ratio']:.2f} dd={metrics['max_drawdown']:.2f}")
                try:
                    from services.central_alerts import alert_darwin_pass
                    alert_darwin_pass(strategy_code, "exploration", metrics)
                except Exception:
                    pass
            else:
                rejection_stats["rejected_darwin"] += 1
                log.info(f"  {strategy_code} ({style}): ✗ rejected | trades={metrics['trade_count']} wr={metrics['win_rate']:.2f} sharpe={metrics['sharpe_ratio']:.2f} dd={metrics['max_drawdown']:.2f}")

            # Free per-strategy memory
            del position, metrics, mc, wf, result

        except Exception as e:
            log.error(f"  {strategy_code}: ERROR — {e}")

        gc.collect()

    # Worker is done — process will exit, freeing ALL memory
    # Rejection stats summary
    total = len(strategies)
    stats_str = " | ".join(f"{k}={v}" for k, v in rejection_stats.items() if v > 0)
    log.info(f"Worker done: {asset}/{timeframe} batch of {total} — {stats_str or 'all filtered'}")


# =============================================================================
# NEAR-MISS RETENTION — Evolution seeds from almost-passing strategies
# =============================================================================

NEAR_MISS_FILE = BASE_DIR / "data" / "near_misses.jsonl"
NEAR_MISS_MAX = 500  # keep top 500 near-misses

def _save_near_miss(entry: dict):
    """Append near-miss to JSONL (capped at NEAR_MISS_MAX lines)."""
    NEAR_MISS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(NEAR_MISS_FILE, "a") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def load_near_misses(top_n: int = 20) -> list:
    """Load top near-misses using composite seed score for micro-evolution.
    
    Seed score weights:
      50% fitness (overall quality)
      30% trade frequency (min(trades/100, 1.0))  
      20% sharpe (raw edge)
    
    This shifts evolution toward 'good + frequent' instead of 'perfect but rare'.
    """
    if not NEAR_MISS_FILE.exists():
        return []
    entries = []
    with open(NEAR_MISS_FILE) as f:
        for line in f:
            try:
                entries.append(json.loads(line.strip()))
            except Exception:
                pass

    # Compute seed score — prioritize mid-frequency strategies
    for e in entries:
        sharpe = min(5, e.get("sharpe", 0)) / 5.0
        trades = e.get("trades", 0)
        trade_score = min(trades / 100.0, 1.0)
        # Use sharpe as proxy for fitness if fitness not stored
        fitness = e.get("fitness", sharpe)
        e["_seed_score"] = 0.5 * fitness + 0.3 * trade_score + 0.2 * sharpe

    entries.sort(key=lambda x: -x.get("_seed_score", 0))

    # Near-miss diversity protection — ensure non-dominant styles in selection
    try:
        from services.diversity_stabilizer import _load_state as _load_div_state
        div_state = _load_div_state()
        if div_state.get("nm_protect_non_dominant"):
            swa = div_state.get("style_weight_adjustments", {})
            if swa:
                dominant = min(swa, key=swa.get)
                # Reserve 30% of slots for non-dominant styles
                n_protected = max(1, top_n // 3)
                non_dom_entries = [e for e in entries if e.get("style") != dominant]
                dom_entries = [e for e in entries if e.get("style") == dominant]
                # Mix: 70% best overall, 30% best non-dominant
                n_dom = top_n - n_protected
                result = dom_entries[:n_dom] + non_dom_entries[:n_protected]
                result.sort(key=lambda x: -x.get("_seed_score", 0))
                return result[:top_n]
    except Exception:
        pass

    return entries[:top_n]


# =============================================================================
# PARAMETER CLUSTER TRACKING — Where do good strategies cluster?
# =============================================================================

PARAM_CLUSTER_FILE = BASE_DIR / "data" / "param_clusters.json"

def _track_param_cluster(style: str, params: dict, metrics: dict):
    """Record parameter values from successful strategies for guided search."""
    clusters = {}
    if PARAM_CLUSTER_FILE.exists():
        try:
            with open(PARAM_CLUSTER_FILE) as f:
                clusters = json.load(f)
        except Exception:
            clusters = {}

    key = style
    if key not in clusters:
        clusters[key] = {"count": 0, "params_sum": {}, "params_min": {}, "params_max": {}}

    c = clusters[key]
    c["count"] += 1
    for p, v in params.items():
        if isinstance(v, (int, float)):
            c["params_sum"][p] = c["params_sum"].get(p, 0) + v
            c["params_min"][p] = min(c["params_min"].get(p, v), v)
            c["params_max"][p] = max(c["params_max"].get(p, v), v)

    # Write back (small file, OK to rewrite)
    with open(PARAM_CLUSTER_FILE, "w") as f:
        json.dump(clusters, f, indent=2)


def get_param_cluster_centers() -> dict:
    """Get average parameter values per style from successful strategies."""
    if not PARAM_CLUSTER_FILE.exists():
        return {}
    try:
        with open(PARAM_CLUSTER_FILE) as f:
            clusters = json.load(f)
        centers = {}
        for style, c in clusters.items():
            if c["count"] > 0:
                centers[style] = {
                    p: round(v / c["count"], 2)
                    for p, v in c["params_sum"].items()
                }
                centers[style]["_count"] = c["count"]
                centers[style]["_ranges"] = {
                    p: [c["params_min"].get(p, 0), c["params_max"].get(p, 0)]
                    for p in c["params_sum"]
                }
        return centers
    except Exception:
        return {}


# =============================================================================
# DISCOVERY RATE TRACKING
# =============================================================================

DISCOVERY_RATE_FILE = BASE_DIR / "data" / "discovery_rate.jsonl"

def _log_discovery_rate(generation: int, tested: int, passed: int):
    """Track discovery rate per generation with fitness distribution + bias influence."""
    import numpy as np

    rate = passed / max(tested, 1)

    # Style diversity
    clusters = get_param_cluster_centers()
    style_counts = {s: c.get("_count", 0) for s, c in clusters.items()} if clusters else {}
    total_passed = sum(style_counts.values())
    dominant_style = max(style_counts, key=style_counts.get) if style_counts else "none"
    dominance = style_counts.get(dominant_style, 0) / max(total_passed, 1)

    # Fitness distribution tracking — read last N results from JSONL
    fitness_values = []
    try:
        with open(OUTPUT_JSONL) as f:
            # Read last 200 lines efficiently
            lines = f.readlines()
            for line in lines[-200:]:
                try:
                    d = json.loads(line.strip())
                    fit = d.get("fitness", 0)
                    if isinstance(fit, (int, float)) and fit > 0:
                        fitness_values.append(fit)
                except Exception:
                    pass
    except Exception:
        pass

    fitness_stats = {}
    if fitness_values:
        arr = np.array(fitness_values)
        fitness_stats = {
            "mean_fitness": round(float(np.mean(arr)), 4),
            "top10_fitness": round(float(np.mean(np.sort(arr)[-max(1, len(arr)//10):])), 4),
            "fitness_std": round(float(np.std(arr)), 4),
        }
        # Convergence warning
        if fitness_stats["fitness_std"] < 0.02 and len(arr) > 50:
            log.warning(f"⚠️ Fitness std={fitness_stats['fitness_std']:.4f} — over-converging!")

    # Bias influence monitor — count adaptive vs random in recent batch
    bias = load_bias()
    bias_driven_styles = sum(
        1 for style_data in bias.values()
        for param_data in style_data.values()
        if sum(b.get("count", 0) for b in param_data.values()) >= BIAS_MIN_SAMPLES
    )
    total_param_slots = len(PARAM_RANGES) * len(STYLE_WEIGHTS)
    bias_influence = round(bias_driven_styles / max(total_param_slots, 1), 3)

    entry = {
        "generation": generation,
        "tested": tested,
        "passed": passed,
        "rate": round(rate, 6),
        "dominant_style": dominant_style,
        "style_dominance": round(dominance, 3),
        "style_distribution": style_counts,
        "bias_influence": bias_influence,
        **fitness_stats,
    }

    # Trade count bucket tracking — monitor frequency distribution shift
    trade_counts = []
    try:
        with open(OUTPUT_JSONL) as f:
            for line in f.readlines()[-200:]:
                try:
                    tc = json.loads(line.strip()).get("trade_count", 0)
                    if tc > 0:
                        trade_counts.append(tc)
                except Exception:
                    pass
    except Exception:
        pass

    if trade_counts:
        total_tc = len(trade_counts)
        entry["trade_buckets"] = {
            "0-20": round(sum(1 for t in trade_counts if t <= 20) / total_tc, 3),
            "20-50": round(sum(1 for t in trade_counts if 20 < t <= 50) / total_tc, 3),
            "50-100": round(sum(1 for t in trade_counts if 50 < t <= 100) / total_tc, 3),
            "100+": round(sum(1 for t in trade_counts if t > 100) / total_tc, 3),
        }

    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    DISCOVERY_RATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DISCOVERY_RATE_FILE, "a") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


# =============================================================================
# PROMOTION GATE — Exploration → Production
# =============================================================================

def check_promotion(result: dict) -> bool:
    """
    Systematic promotion gate: exploration → production.
    Requires passing ALL of these (no manual judgment):
    - 100+ trades
    - Sharpe > 1.2
    - Max DD < 25%
    - Walk-forward score > 0.3 (OOS sharpe)
    - Walk-forward degradation < 0.5
    - MC worst DD < 35%
    - Profit factor > 1.1
    - Stability check: WF variance not too high
    """
    tc = result.get("trade_count", 0)
    sh = result.get("sharpe_ratio", 0)
    dd = result.get("max_drawdown", 1)
    pf = result.get("profit_factor", 0)
    wf_sh = result.get("wf_mean_sharpe", 0)
    wf_deg = result.get("wf_degradation", 1)
    mc_dd = result.get("mc_worst_dd", 1)

    return (
        tc >= 100
        and sh > 1.2
        and dd < 0.25
        and pf > 1.1
        and wf_sh > 0.3
        and wf_deg < 0.5
        and mc_dd < 0.35
    )


def _validate_result(result: dict) -> bool:
    """Result integrity check — reject corrupted/incomplete results."""
    # No NaNs in critical fields
    for field in ("sharpe_ratio", "win_rate", "max_drawdown", "profit_factor", "total_return_pct"):
        val = result.get(field)
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return False
    # No zero-trade strategies
    if result.get("trade_count", 0) == 0:
        return False
    # No absurd returns (sanity filter should catch these, but double-check)
    if abs(result.get("total_return_pct", 0)) > 100000:
        return False
    # Must have strategy code
    if not result.get("strategy_code"):
        return False
    return True


def _append_result(result: dict):
    """Append a single result line to the JSONL output file (atomic-ish)."""
    if not _validate_result(result):
        log.warning(f"  Rejected invalid result: {result.get('strategy_code', '?')}")
        return
    OUTPUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSONL, "a") as f:
        f.write(json.dumps(result, separators=(",", ":")) + "\n")


# =============================================================================
# SUPERVISOR
# =============================================================================

# =============================================================================
# ADAPTIVE CONTROL LAYER — Self-regulating learning system
# =============================================================================

CONTROL_STATE_FILE = BASE_DIR / "data" / "control_state.json"

def _load_control_state() -> dict:
    """Load adaptive control state."""
    if CONTROL_STATE_FILE.exists():
        try:
            with open(CONTROL_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "exploration_boost": 0.0,     # extra random ratio (-0.2 to +0.2)
        "bias_penalty": 0.0,          # reduce bias influence (0 to 0.5)
        "mutation_range_boost": 0.0,  # widen mutations (-0.05 to +0.10)
        "shock_frequency_mult": 1.0,  # multiply shock frequency (0.5 to 3.0)
        "last_action": "stable",
        "stagnation_counter": 0,
        "last_discovery_rates": [],   # last 10 generation rates
    }


def _save_control_state(state: dict):
    CONTROL_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONTROL_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def adaptive_control(generation: int, tested: int, passed: int) -> str:
    """
    Self-regulation engine. Reads system metrics, adjusts parameters.
    Returns action taken: "stable", "diversify", "flatten_bias", "inject_variation".
    
    All adjustments are small (10-20%), gradual, and reversible.
    """
    import numpy as np

    cs = _load_control_state()

    # Track discovery rate trend (last 10 generations)
    rate = passed / max(tested, 1)
    rates = cs.get("last_discovery_rates", [])
    rates.append(rate)
    if len(rates) > 10:
        rates = rates[-10:]
    cs["last_discovery_rates"] = rates

    # Read latest fitness stats from discovery rate log
    fitness_std = 0.1
    bias_influence = 0.0
    try:
        if DISCOVERY_RATE_FILE.exists():
            with open(DISCOVERY_RATE_FILE) as f:
                lines = f.readlines()
                if lines:
                    last = json.loads(lines[-1].strip())
                    fitness_std = last.get("fitness_std", 0.1)
                    bias_influence = last.get("bias_influence", 0.0)
    except Exception:
        pass

    # Discovery trend: is rate improving?
    rate_improving = False
    rate_flat = False
    if len(rates) >= 5:
        first_half = np.mean(rates[:len(rates)//2])
        second_half = np.mean(rates[len(rates)//2:])
        if second_half > first_half * 1.1:
            rate_improving = True
        elif abs(second_half - first_half) < 0.001:
            rate_flat = True

    action = "stable"

    # ── Rule 1: Over-convergence (fitness std collapsing) ──
    if fitness_std < 0.02 and fitness_std > 0:
        cs["exploration_boost"] = min(0.15, cs.get("exploration_boost", 0) + 0.05)
        cs["bias_penalty"] = min(0.3, cs.get("bias_penalty", 0) + 0.10)
        cs["shock_frequency_mult"] = min(3.0, cs.get("shock_frequency_mult", 1.0) + 0.5)
        action = "diversify"
        log.warning(f"🔧 CONTROL: Over-convergence (std={fitness_std:.4f}) → diversify (+explore, -bias, +shock)")

    # ── Rule 2: Bias domination ──
    elif bias_influence > 0.7:
        cs["bias_penalty"] = min(0.4, cs.get("bias_penalty", 0) + 0.15)
        cs["exploration_boost"] = min(0.10, cs.get("exploration_boost", 0) + 0.05)
        action = "flatten_bias"
        log.warning(f"🔧 CONTROL: Bias domination ({bias_influence:.0%}) → flatten bias, boost random")

    # ── Rule 3: Stagnation (no improvement over 5+ gens) ──
    elif rate_flat and len(rates) >= 5:
        cs["stagnation_counter"] = cs.get("stagnation_counter", 0) + 1
        if cs["stagnation_counter"] >= 3:  # 3 consecutive flat checks
            cs["mutation_range_boost"] = min(0.10, cs.get("mutation_range_boost", 0) + 0.03)
            cs["shock_frequency_mult"] = min(2.0, cs.get("shock_frequency_mult", 1.0) + 0.3)
            action = "inject_variation"
            log.warning(f"🔧 CONTROL: Stagnation ({cs['stagnation_counter']} checks) → widen mutations, more shocks")

    # ── Rule 3b: Frequency adaptation — adjust trade frequency weight ──
    # Read trade buckets from latest discovery rate entry
    try:
        if DISCOVERY_RATE_FILE.exists():
            with open(DISCOVERY_RATE_FILE) as f:
                lines = f.readlines()
                if lines:
                    last_dr = json.loads(lines[-1].strip())
                    buckets = last_dr.get("trade_buckets", {})
                    pct_100plus = buckets.get("100+", 0)
                    pct_0_20 = buckets.get("0-20", 0)

                    # If stagnating and too many low-trade strategies, boost frequency weight
                    if rate_flat and pct_0_20 > 0.5:
                        cs["frequency_weight_boost"] = min(0.10, cs.get("frequency_weight_boost", 0) + 0.02)
                        log.info(f"🔧 CONTROL: Low trade density ({pct_0_20:.0%} under 20) → boosting frequency weight")

                    # If overtrading detected (avg > 200), reduce frequency weight
                    if pct_100plus > 0.5:
                        cs["frequency_weight_boost"] = max(-0.05, cs.get("frequency_weight_boost", 0) - 0.02)
                        log.info(f"🔧 CONTROL: High trade density ({pct_100plus:.0%} over 100) → reducing frequency weight")
    except Exception:
        pass

    # ── Rule 4a: CONVERGENCE TRIGGERS (style dominance + near-miss quality) ──
    # Read latest discovery rate entry for style dominance and trade buckets
    style_dominance = 0
    dominant_style = "none"
    avg_nm_sharpe = 0.5
    avg_nm_trades = 30
    avg_result_trades = 100
    try:
        if DISCOVERY_RATE_FILE.exists():
            with open(DISCOVERY_RATE_FILE) as f:
                dr_lines = f.readlines()
                if dr_lines:
                    last_entry = json.loads(dr_lines[-1].strip())
                    style_dominance = last_entry.get("style_dominance", 0)
                    dominant_style = last_entry.get("dominant_style", "none")

        # Compute recent near-miss quality (last 50)
        if NEAR_MISS_FILE.exists():
            nm_lines = open(NEAR_MISS_FILE).readlines()
            recent_nm = []
            for line in nm_lines[-50:]:
                try:
                    recent_nm.append(json.loads(line.strip()))
                except Exception:
                    pass
            if recent_nm:
                avg_nm_sharpe = sum(n.get("sharpe", 0) for n in recent_nm) / len(recent_nm)
                avg_nm_trades = sum(n.get("trades", 0) for n in recent_nm) / len(recent_nm)

        # Compute recent avg trade count from results
        if OUTPUT_JSONL.exists():
            result_lines = open(OUTPUT_JSONL).readlines()
            recent_trades = []
            for line in result_lines[-200:]:
                try:
                    tc = json.loads(line.strip()).get("trade_count", 0)
                    if tc > 0:
                        recent_trades.append(tc)
                except Exception:
                    pass
            if recent_trades:
                avg_result_trades = sum(recent_trades) / len(recent_trades)
    except Exception:
        pass

    # Track near-miss degradation over time
    nm_degrade_counter = cs.get("nm_degrade_counter", 0)
    if avg_nm_sharpe < 0.6:
        nm_degrade_counter += 1
    else:
        nm_degrade_counter = max(0, nm_degrade_counter - 1)
    cs["nm_degrade_counter"] = nm_degrade_counter

    # ── TRIGGER 1: HARD INTERVENTION ──
    # VoF >= 80% OR avg trades >= 250 OR near-miss Sharpe < 0.6 for 20+ gens
    hard_trigger = (
        style_dominance >= 0.80 or
        avg_result_trades >= 250 or
        nm_degrade_counter >= 20
    )
    if hard_trigger:
        cs["frequency_weight_boost"] = max(-0.05, cs.get("frequency_weight_boost", 0) - 0.05)
        cs["exploration_boost"] = min(0.20, cs.get("exploration_boost", 0) + 0.10)
        cs["dominant_style_cap"] = dominant_style
        cs["dominant_style_cap_weight"] = 0.5  # halve its selection weight
        log.warning(
            f"🚨 CONTROL HARD: VoF={style_dominance:.0%} trades={avg_result_trades:.0f} "
            f"nm_sharpe={avg_nm_sharpe:.2f} nm_degrade={nm_degrade_counter} → "
            f"reduce frequency, +10% exploration, cap {dominant_style}"
        )
        action = "hard_rebalance"

    # ── TRIGGER 2: SOFT INTERVENTION ──
    # Dominant style 70-80% AND near-misses degrading AND Sharpe still strong
    elif style_dominance >= 0.70 and avg_nm_sharpe < 0.8:
        cs["exploration_boost"] = min(0.15, cs.get("exploration_boost", 0) + 0.05)
        cs["forced_diversity_seeds"] = 2  # inject 2 non-dominant seeds per batch
        log.warning(
            f"⚠️ CONTROL SOFT: VoF={style_dominance:.0%} nm_sharpe={avg_nm_sharpe:.2f} → "
            f"+5% exploration, inject 2 non-{dominant_style} seeds"
        )
        action = "soft_rebalance"

    # ── Rule 4: Healthy learning → decay adjustments back to baseline ──
    else:
        # Gradually return to baseline (small steps)
        cs["exploration_boost"] = max(0, cs.get("exploration_boost", 0) - 0.02)
        cs["bias_penalty"] = max(0, cs.get("bias_penalty", 0) - 0.03)
        cs["mutation_range_boost"] = max(0, cs.get("mutation_range_boost", 0) - 0.01)
        cs["shock_frequency_mult"] = max(1.0, cs.get("shock_frequency_mult", 1.0) - 0.1)
        cs.pop("dominant_style_cap", None)
        cs.pop("forced_diversity_seeds", None)
        if cs.get("stagnation_counter", 0) > 0 and rate_improving:
            cs["stagnation_counter"] = 0  # reset on improvement
        action = "stable"

    # ── HARD SAFETY RAILS — outer limits, non-negotiable ──
    cs["exploration_boost"] = min(0.20, cs.get("exploration_boost", 0))
    cs["bias_penalty"] = min(0.50, cs.get("bias_penalty", 0))
    cs["mutation_range_boost"] = min(0.15, cs.get("mutation_range_boost", 0))
    cs["shock_frequency_mult"] = max(0.5, min(3.0, cs.get("shock_frequency_mult", 1.0)))
    # Hard floor: shock never more frequent than every 5 gens
    # (enforced in batch generation, not here)

    cs["last_action"] = action
    _save_control_state(cs)
    return action


def get_control_adjustments() -> dict:
    """Get current control adjustments — merges control layer + diversity stabilizer."""
    cs = _load_control_state()

    # Base from control layer
    adj = {
        "exploration_boost": cs.get("exploration_boost", 0),
        "bias_penalty": cs.get("bias_penalty", 0),
        "mutation_range_boost": cs.get("mutation_range_boost", 0),
        "shock_frequency_mult": cs.get("shock_frequency_mult", 1.0),
        "diversity_mode": "NORMAL",
    }

    # Merge in diversity stabilizer state
    try:
        from services.diversity_stabilizer import _load_state as _load_div_state
        div = _load_div_state()
        # Additive: stabilizer boost stacks on top of control layer
        adj["exploration_boost"] = min(0.25, adj["exploration_boost"] + div.get("exploration_boost", 0))
        adj["bias_penalty"] = min(0.50, adj["bias_penalty"] + div.get("bias_penalty_boost", 0))
        adj["diversity_mode"] = div.get("last_state", "healthy").upper()

        # Shock override — stabilizer can force higher shock frequency
        if div.get("shock_override"):
            adj["shock_frequency_mult"] = max(adj["shock_frequency_mult"], 3.0)
    except Exception:
        pass

    return adj


class Supervisor:
    """
    Lightweight supervisor that manages batch queue and spawns worker subprocesses.
    Stays persistent, stays under ~200MB.
    """

    def __init__(self, max_generations: Optional[int] = None):
        self.max_generations = max_generations
        self.state = load_state()
        log.info(f"Supervisor started | generation={self.state['generation']} | "
                 f"total_tested={self.state['total_strategies_tested']} | "
                 f"total_passed={self.state['total_passed']}")

    def run(self):
        """Main supervisor loop."""
        try:
            while True:
                self.state["generation"] += 1
                gen = self.state["generation"]
                log.info(f"{'='*60}")
                log.info(f"Generation {gen}")
                log.info(f"{'='*60}")

                # Check search expansion trigger
                exp = _get_expansion()
                if exp:
                    exp_state = exp["check_and_activate"](gen)
                    if exp_state.get("active"):
                        exp["ensure_30m"]()  # create 30m data if needed
                        exp["check_deactivation"]()  # auto-deactivate if recovered

                        # Evaluate lineage promotion (only when expansion is active)
                        try:
                            from services.search_expansion import get_expansion_stats
                            from services.lineage_promotion import promote
                            exp_stats = get_expansion_stats()
                            promote(gen, exp_stats)
                        except Exception as e:
                            log.debug(f"Lineage promotion check skipped: {e}")

                # Generate batches: one per (asset, timeframe) combo
                batches = self._create_batches(gen)
                log.info(f"Created {len(batches)} batches for generation {gen}")

                # Process batches with max concurrent workers
                tested, passed = self._run_batches(batches)
                self.state["total_strategies_tested"] += tested
                self.state["total_passed"] += passed

                save_state(self.state)

                # Track discovery rate
                _log_discovery_rate(gen, tested, passed)
                lifetime_rate = self.state["total_passed"] / max(self.state["total_strategies_tested"], 1)

                # Adaptive control — self-regulate learning
                control_action = adaptive_control(gen, tested, passed)

                # Diversity stabilizer — self-correcting diversity governor
                try:
                    from services.diversity_stabilizer import run_stabilizer
                    div_adj = run_stabilizer()
                except Exception as e:
                    log.warning(f"Diversity stabilizer error: {e}")
                    div_adj = {}

                adj = get_control_adjustments()

                adj = get_control_adjustments()
                div_mode = adj.get("diversity_mode", "?")

                log.info(
                    f"Generation {gen} complete: {tested} tested, {passed} passed | "
                    f"Lifetime: {self.state['total_strategies_tested']} tested, "
                    f"{self.state['total_passed']} passed (rate={lifetime_rate:.2%}) | "
                    f"control={control_action} | diversity={div_mode}"
                )

                if self.max_generations and gen >= self.max_generations:
                    log.info(f"Reached max generations ({self.max_generations}). Stopping.")
                    break

                # Brief pause between generations to avoid CPU saturation
                time.sleep(2)

        except KeyboardInterrupt:
            log.info("Supervisor interrupted. Saving state...")
            save_state(self.state)

    def _create_batches(self, generation: int) -> list[dict]:
        """Create batch descriptors for all asset/timeframe combos.
        
        Timeframe weighting biases toward higher-frequency timeframes:
          15m: 40%, 1h: 40%, 4h: 15%, daily: 5%
        This pushes evolution toward more frequent trading strategies.
        
        When search expansion is active, adds 5m and 30m timeframes.
        """
        # Timeframe batch multipliers — how many batches per TF
        # 15m/1h get 2 batches each, 4h gets 1, daily gets 1 but smaller
        TF_BATCHES = {"15m": 2, "1h": 2, "4h": 1, "daily": 1, "5m": 1, "30m": 1}
        TF_BATCH_SIZE = {"15m": BATCH_SIZE, "1h": BATCH_SIZE, "4h": BATCH_SIZE,
                         "daily": max(5, BATCH_SIZE // 2), "5m": BATCH_SIZE, "30m": BATCH_SIZE}

        # Get active timeframes (may include expanded ones)
        exp = _get_expansion()
        active_tfs = TIMEFRAMES
        if exp:
            active_tfs = exp["get_active_timeframes"](TIMEFRAMES)

        batches = []
        for asset in ASSETS:
            for tf in active_tfs:
                parquet_path = DATA_DIR / asset / f"{tf}.parquet"
                if not parquet_path.exists():
                    log.warning(f"Skipping {asset}/{tf} — no data file")
                    continue

                num_batches = TF_BATCHES.get(tf, 1)
                batch_size = TF_BATCH_SIZE.get(tf, BATCH_SIZE)
                for _ in range(num_batches):
                    dnas = generate_batch_dnas(generation, batch_size)
                    batches.append({
                        "asset": asset,
                        "timeframe": tf,
                        "generation": generation,
                        "strategies": dnas,
                    })
        return batches

    def _run_batches(self, batches: list[dict]) -> tuple[int, int]:
        """
        Run batches using subprocess workers (max MAX_WORKERS concurrent).
        Returns (total_tested, total_passed).
        """
        total_tested = 0
        total_passed_before = self._count_passed()

        # Use subprocess for true memory isolation
        active_procs: list[subprocess.Popen] = []
        MAX_QUEUE_SIZE = 24  # bounded queue — 3 assets × 4 TFs × 2 batches max
        batch_queue = list(batches)[:MAX_QUEUE_SIZE]
        if len(list(batches)) > MAX_QUEUE_SIZE:
            log.warning(f"  Backpressure: capped queue at {MAX_QUEUE_SIZE} (had {len(list(batches))})")

        while batch_queue or active_procs:
            # Launch workers up to MAX_WORKERS
            while batch_queue and len(active_procs) < MAX_WORKERS:
                batch = batch_queue.pop(0)
                batch_json = json.dumps(batch)
                total_tested += len(batch["strategies"])

                log.info(
                    f"  Spawning worker: {batch['asset']}/{batch['timeframe']} "
                    f"({len(batch['strategies'])} strategies)"
                )

                # Spawn worker as a subprocess running this same script in --worker mode
                batch_start = time.time()
                proc = subprocess.Popen(
                    [sys.executable, __file__, "--worker", batch_json],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                active_procs.append((proc, batch, batch_start))

            # Wait for any worker to finish — with watchdog timeout
            WORKER_TIMEOUT = 900  # 15 minutes max per worker
            still_active = []
            for proc, batch, batch_start in active_procs:
                ret = proc.poll()
                elapsed = time.time() - batch_start

                if ret is not None:
                    # Worker finished — log batch metrics
                    stdout, stderr = proc.communicate()
                    batch_id = f"{batch['asset']}/{batch['timeframe']}"
                    n_strats = len(batch['strategies'])
                    log.info(
                        f"  ✅ Batch {batch_id}: {n_strats} strategies in {elapsed:.1f}s "
                        f"({elapsed/max(1,n_strats):.1f}s/strategy) exit={ret}"
                    )
                    if stdout:
                        for line in stdout.decode(errors="replace").strip().split("\n"):
                            if line:
                                log.info(f"  [worker] {line}")
                    if stderr:
                        for line in stderr.decode(errors="replace").strip().split("\n"):
                            if line and "WARNING" not in line:
                                log.info(f"  [worker] {line}")
                    if ret != 0:
                        log.warning(f"  ⚠️ Worker {batch_id} exited with code {ret}")

                elif elapsed > WORKER_TIMEOUT:
                    # Watchdog: kill stuck worker
                    batch_id = f"{batch['asset']}/{batch['timeframe']}"
                    log.error(
                        f"  🔴 WATCHDOG: Worker {batch_id} stuck for {elapsed:.0f}s "
                        f"(>{WORKER_TIMEOUT}s) — killing"
                    )
                    proc.kill()
                    proc.wait()
                else:
                    still_active.append((proc, batch, batch_start))
            active_procs = still_active

            if active_procs:
                time.sleep(0.5)

        total_passed_after = self._count_passed()
        new_passed = total_passed_after - total_passed_before

        return total_tested, new_passed

    def _count_passed(self) -> int:
        """Count passed_darwin=True entries in the JSONL log."""
        if not OUTPUT_JSONL.exists():
            return 0
        count = 0
        try:
            with open(OUTPUT_JSONL, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get("passed_darwin"):
                            count += 1
                    except json.JSONDecodeError:
                        continue
        except IOError:
            pass
        return count


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Continuous Backtester V2")
    parser.add_argument("--generations", type=int, default=None,
                        help="Number of generations to run (default: infinite)")
    parser.add_argument("--worker", type=str, default=None,
                        help="Internal: run as worker with batch JSON")
    args = parser.parse_args()

    if args.worker:
        # Worker mode — process batch and exit
        worker_process(args.worker)
        return

    # Supervisor mode
    supervisor = Supervisor(max_generations=args.generations)
    supervisor.run()


if __name__ == "__main__":
    main()


# =============================================================================
# SYSTEMD SERVICE FILE
# =============================================================================
#
# Save as: /etc/systemd/system/continuous-backtester.service
#
# [Unit]
# Description=Trading Factory Continuous Backtester V2
# After=network.target
# Wants=network.target
#
# [Service]
# Type=simple
# User=ochenryceo
# Group=ochenryceo
# WorkingDirectory=Path(__file__).resolve().parents[1]
# ExecStart=/usr/bin/python3 Path(__file__).resolve().parents[1]/services/continuous_backtester_v2.py
# Restart=on-failure
# RestartSec=30
# TimeoutStopSec=60
#
# # Memory limits — supervisor should stay under 200MB, workers spawn separately
# MemoryMax=4G
# MemoryHigh=2G
#
# # Logging
# StandardOutput=journal
# StandardError=journal
# SyslogIdentifier=backtester-v2
#
# # Security hardening
# NoNewPrivileges=yes
# ProtectSystem=strict
# ProtectHome=read-only
# ReadWritePaths=Path(__file__).resolve().parents[1]/data
# PrivateTmp=yes
#
# # Resource limits
# LimitNOFILE=4096
# CPUQuota=80%
#
# [Install]
# WantedBy=multi-user.target
#
# Usage:
#   sudo systemctl daemon-reload
#   sudo systemctl enable continuous-backtester
#   sudo systemctl start continuous-backtester
#   journalctl -u continuous-backtester -f

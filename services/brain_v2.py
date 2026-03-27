#!/usr/bin/env python3
"""
🧠 Brain Engine V2 — Portfolio Decision Engine
================================================
Sits on top of the V2 backtester. Reads strategy results from the continuous
run log, applies quality gates, clusters correlated strategies, scores them,
detects market regimes, and outputs capital allocation decisions.

Running modes:
    python brain_v2.py            — one cycle, print report, exit
    python brain_v2.py --daemon   — run every 30 minutes continuously
    python brain_v2.py --report   — markdown report to stdout

Memory budget: < 500MB peak (streams JSONL, keeps only summaries).
"""

import argparse
import json
import logging
import math
import os
import signal
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RUN_LOG = DATA_DIR / "continuous_run_log.jsonl"
MARKET_DATA_DIR = DATA_DIR / "processed"
PORTFOLIO_OUT = DATA_DIR / "brain_portfolio.json"
DECISIONS_LOG = DATA_DIR / "brain_decisions.jsonl"

ASSETS = ["NQ", "GC", "CL"]
TIMEFRAMES = ["15m", "1h", "4h", "daily"]

# Quality gates
MIN_SHARPE = 1.2
MAX_DD = 0.25
MAX_MC_WORST_DD = 0.35
MAX_WF_DEGRADATION = 0.5
MIN_TRADE_COUNT = 100
MIN_PROFIT_FACTOR = 1.1

# Sanity caps — absurd values indicate overfitting / data bugs
MAX_SANE_SHARPE = 8.0
MAX_SANE_RETURN_PCT = 5000.0
MAX_SANE_PROFIT_FACTOR = 50.0

# Scoring weights
W_SHARPE = 0.30
W_RETURN = 0.20
W_WF = 0.20
W_MC = 0.15
W_DD = 0.15

# Allocation caps
MAX_PER_STRATEGY = 0.15
MAX_PER_CLUSTER = 0.30
MAX_PER_ASSET = 0.40          # Cross-asset diversification — no single asset > 40%
MAX_PORTFOLIO_DD = 0.25
MIN_WEIGHT = 0.03             # Floor — below this is noise, not worth allocating
EXPLORATION_BUDGET = 0.10

# Correlation clustering threshold
CORR_THRESHOLD = 0.80

# Regime style mapping — which styles work in which regimes
STYLE_REGIME_BOOST = {
    "trend_following":   {"bull": 1.3, "bear": 1.3, "high_vol": 0.7, "ranging": 0.5},
    "mean_reversion":    {"bull": 0.8, "bear": 0.7, "high_vol": 1.2, "ranging": 1.4},
    "momentum":          {"bull": 1.4, "bear": 1.0, "high_vol": 0.8, "ranging": 0.6},
    "breakout":          {"bull": 1.2, "bear": 1.1, "high_vol": 1.3, "ranging": 0.5},
    "volatility":        {"bull": 0.8, "bear": 1.0, "high_vol": 1.5, "ranging": 0.7},
}
DEFAULT_REGIME_BOOST = {"bull": 1.0, "bear": 1.0, "high_vol": 1.0, "ranging": 1.0}

DAEMON_INTERVAL_SEC = 1800  # 30 minutes

log = logging.getLogger("brain_v2")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StrategyRecord:
    """Deduplicated best result for a single strategy code."""
    strategy_code: str
    asset: str
    timeframe: str
    style: str
    generation: int = 0
    trade_count: int = 0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    total_return_pct: float = 0.0
    passed_darwin: bool = False
    mc_mean_return: Optional[float] = None
    mc_worst_dd: Optional[float] = None
    wf_mean_sharpe: Optional[float] = None
    wf_degradation: Optional[float] = None
    timestamp: str = ""
    # Computed later
    score: float = 0.0
    cluster_id: int = -1
    decay_flag: bool = False
    regime_boost: float = 1.0
    weight: float = 0.0


# ---------------------------------------------------------------------------
# Step 1: Load & Deduplicate Strategy Registry (streaming)
# ---------------------------------------------------------------------------

def load_strategy_registry(path: Path) -> dict[str, StrategyRecord]:
    """
    Stream the JSONL run log. Keep only the best result per strategy_code
    (best = highest sharpe_ratio). Never loads full file into memory.
    """
    registry: dict[str, StrategyRecord] = {}
    line_count = 0

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            line_count += 1
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue

            code = d.get("strategy_code", "")
            if not code:
                continue

            sharpe = d.get("sharpe_ratio", 0.0)

            # Keep best by sharpe per strategy_code
            if code in registry and registry[code].sharpe_ratio >= sharpe:
                continue

            registry[code] = StrategyRecord(
                strategy_code=code,
                asset=d.get("asset", ""),
                timeframe=d.get("timeframe", ""),
                style=d.get("style", ""),
                generation=d.get("generation", 0),
                trade_count=d.get("trade_count", 0),
                win_rate=d.get("win_rate", 0.0),
                sharpe_ratio=sharpe,
                max_drawdown=d.get("max_drawdown", 0.0),
                profit_factor=d.get("profit_factor", 0.0),
                total_return_pct=d.get("total_return_pct", 0.0),
                passed_darwin=d.get("passed_darwin", False),
                mc_mean_return=d.get("mc_mean_return"),
                mc_worst_dd=d.get("mc_worst_dd"),
                wf_mean_sharpe=d.get("wf_mean_sharpe"),
                wf_degradation=d.get("wf_degradation"),
                timestamp=d.get("timestamp", ""),
            )

    log.info(f"Loaded {line_count} lines → {len(registry)} unique strategies")
    return registry


# ---------------------------------------------------------------------------
# Step 2: Quality Filters
# ---------------------------------------------------------------------------

def apply_quality_filters(registry: dict[str, StrategyRecord]) -> list[StrategyRecord]:
    """Apply hard quality gates. Returns list of passing strategies."""
    passed = []
    for s in registry.values():
        # Hard gates
        if s.sharpe_ratio < MIN_SHARPE:
            continue
        if s.max_drawdown >= MAX_DD:
            continue
        if s.trade_count < MIN_TRADE_COUNT:
            continue
        if s.profit_factor < MIN_PROFIT_FACTOR:
            continue

        # Optional gates (only apply if data present and non-zero)
        if s.mc_worst_dd is not None and s.mc_worst_dd > 0:
            if s.mc_worst_dd >= MAX_MC_WORST_DD:
                continue
        if s.wf_degradation is not None and s.wf_degradation > 0:
            if s.wf_degradation >= MAX_WF_DEGRADATION:
                continue

        # Sanity caps — reject suspiciously good results (likely overfitting)
        if s.sharpe_ratio > MAX_SANE_SHARPE:
            log.debug(f"Sanity reject {s.strategy_code}: sharpe={s.sharpe_ratio:.2f}")
            continue
        if s.total_return_pct > MAX_SANE_RETURN_PCT:
            log.debug(f"Sanity reject {s.strategy_code}: return={s.total_return_pct:.1f}%")
            continue
        if s.profit_factor > MAX_SANE_PROFIT_FACTOR:
            log.debug(f"Sanity reject {s.strategy_code}: pf={s.profit_factor:.2f}")
            continue

        passed.append(s)

    log.info(f"Quality filter: {len(registry)} → {len(passed)} strategies")
    return passed


# ---------------------------------------------------------------------------
# Step 3: Correlation Clustering
# ---------------------------------------------------------------------------

def _strategy_feature_vector(s: StrategyRecord) -> np.ndarray:
    """
    Build a synthetic feature vector for correlation approximation.
    We can't reconstruct full equity curves from summary stats, so we use
    a feature-based proxy: asset, timeframe, style, sharpe, return, dd.
    Strategies with similar features on the same asset/tf are likely correlated.
    """
    # Asset encoding
    asset_map = {"NQ": 0, "GC": 1, "CL": 2}
    tf_map = {"5m": 0, "15m": 1, "1h": 2, "4h": 3, "daily": 4}
    style_map = {"trend_following": 0, "mean_reversion": 1, "momentum": 2,
                 "breakout": 3, "volatility": 4}

    return np.array([
        asset_map.get(s.asset, 0),
        tf_map.get(s.timeframe, 2),
        style_map.get(s.style, 0),
        min(s.sharpe_ratio, MAX_SANE_SHARPE),
        min(s.total_return_pct, MAX_SANE_RETURN_PCT) / 100.0,
        s.max_drawdown,
        s.win_rate,
        min(s.profit_factor, MAX_SANE_PROFIT_FACTOR),
    ], dtype=np.float64)


def cluster_strategies(strategies: list[StrategyRecord]) -> list[StrategyRecord]:
    """
    Group correlated strategies and keep top 1-2 per cluster.
    Uses feature-based similarity as a proxy for return correlation.
    """
    if len(strategies) <= 2:
        for i, s in enumerate(strategies):
            s.cluster_id = i
        return strategies

    # Build feature matrix
    features = np.array([_strategy_feature_vector(s) for s in strategies])

    # Normalize each feature to [0, 1]
    mins = features.min(axis=0)
    maxs = features.max(axis=0)
    ranges = maxs - mins
    ranges[ranges == 0] = 1.0
    normed = (features - mins) / ranges

    # Compute pairwise cosine similarity
    norms = np.linalg.norm(normed, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = normed / norms
    sim_matrix = unit @ unit.T

    # Simple greedy clustering
    n = len(strategies)
    cluster_ids = [-1] * n
    current_cluster = 0

    for i in range(n):
        if cluster_ids[i] >= 0:
            continue
        cluster_ids[i] = current_cluster
        for j in range(i + 1, n):
            if cluster_ids[j] >= 0:
                continue
            # Same asset+timeframe+style strategies get higher correlation
            same_context = (strategies[i].asset == strategies[j].asset and
                            strategies[i].timeframe == strategies[j].timeframe and
                            strategies[i].style == strategies[j].style)
            threshold = CORR_THRESHOLD if not same_context else CORR_THRESHOLD - 0.15
            if sim_matrix[i, j] >= threshold:
                cluster_ids[j] = current_cluster
        current_cluster += 1

    # Assign cluster IDs
    for i, s in enumerate(strategies):
        s.cluster_id = cluster_ids[i]

    # Keep top 2 per cluster by sharpe
    clusters: dict[int, list[StrategyRecord]] = defaultdict(list)
    for s in strategies:
        clusters[s.cluster_id].append(s)

    kept = []
    for cid, members in clusters.items():
        members.sort(key=lambda x: -x.sharpe_ratio)
        kept.extend(members[:2])

    log.info(f"Clustering: {len(strategies)} strategies → {current_cluster} clusters → {len(kept)} kept")
    return kept


# ---------------------------------------------------------------------------
# Step 4: Multi-Factor Scoring
# ---------------------------------------------------------------------------

def score_strategies(strategies: list[StrategyRecord]) -> list[StrategyRecord]:
    """Compute normalized composite score for each strategy."""
    if not strategies:
        return strategies

    # Collect raw values
    sharpes = [s.sharpe_ratio for s in strategies]
    returns = [s.total_return_pct for s in strategies]
    wf_sharpes = [s.wf_mean_sharpe if s.wf_mean_sharpe and s.wf_mean_sharpe > 0 else 0.0 for s in strategies]
    mc_dds = [s.mc_worst_dd if s.mc_worst_dd and s.mc_worst_dd > 0 else s.max_drawdown for s in strategies]
    dds = [s.max_drawdown for s in strategies]

    def _normalize(vals: list[float]) -> list[float]:
        mn, mx = min(vals), max(vals)
        rng = mx - mn
        if rng == 0:
            return [0.5] * len(vals)
        return [(v - mn) / rng for v in vals]

    n_sharpe = _normalize(sharpes)
    n_return = _normalize(returns)
    n_wf = _normalize(wf_sharpes)
    # For DD-based metrics, lower is better → invert
    n_mc_rob = _normalize([1.0 - d for d in mc_dds])
    n_dd = _normalize([1.0 - d for d in dds])

    for i, s in enumerate(strategies):
        s.score = (
            W_SHARPE * n_sharpe[i] +
            W_RETURN * n_return[i] +
            W_WF * n_wf[i] +
            W_MC * n_mc_rob[i] +
            W_DD * n_dd[i]
        )

    strategies.sort(key=lambda x: -x.score)
    log.info(f"Scored {len(strategies)} strategies. Top: {strategies[0].strategy_code} (score={strategies[0].score:.4f})")
    return strategies


# ---------------------------------------------------------------------------
# Step 5: Regime Detection
# ---------------------------------------------------------------------------

def detect_regime(asset: str) -> tuple[str, float]:
    """
    Detect current market regime for an asset using latest price data.
    Returns: (regime_label, regime_strength)
    - regime_label: "bull", "bear", "high_vol", "ranging"
    - regime_strength: 0.0 to 1.0 (how confident we are in the regime)
    """
    # Try daily first, fall back to 4h, then 1h
    for tf in ["daily", "4h", "1h"]:
        path = MARKET_DATA_DIR / asset / f"{tf}.parquet"
        if path.exists():
            try:
                df = pd.read_parquet(path, columns=["close"])
                break
            except Exception:
                continue
    else:
        log.warning(f"No market data for {asset}, defaulting to 'ranging'")
        return "ranging", 0.0

    if len(df) < 200:
        return "ranging", 0.0

    close = df["close"].values.astype(np.float64)

    # EMA 50 vs EMA 200
    ema50 = _ema(close, 50)
    ema200 = _ema(close, 200)
    trend_up = ema50[-1] > ema200[-1]

    # 50-bar rolling volatility (std of returns)
    returns = np.diff(close[-51:]) / close[-51:-1]
    current_vol = np.std(returns)

    # Historical vol for comparison (full series, sampled)
    sample_size = min(len(close), 2000)
    hist_returns = np.diff(close[-sample_size:]) / close[-sample_size:-1]
    # Rolling 50-bar vol across history
    if len(hist_returns) >= 50:
        vol_series = pd.Series(hist_returns).rolling(50).std().dropna()
        vol_median = vol_series.median()
        vol_p75 = vol_series.quantile(0.75)
    else:
        vol_median = current_vol
        vol_p75 = current_vol * 1.5

    # Classify with strength
    # Strength = how far from boundaries (0 = borderline, 1 = extreme)
    high_vol = current_vol > vol_p75
    ema_diff_pct = abs(ema50[-1] - ema200[-1]) / max(ema200[-1], 1)
    trend_strength = min(1.0, ema_diff_pct / 0.05)  # 5% EMA spread = full strength
    vol_strength = min(1.0, abs(current_vol - vol_median) / max(vol_median, 0.001))

    if high_vol:
        return "high_vol", min(1.0, vol_strength)
    elif trend_up and current_vol <= vol_median:
        return "bull", trend_strength
    elif not trend_up and current_vol > vol_median:
        return "bear", max(trend_strength, vol_strength)
    elif not trend_up and current_vol <= vol_median:
        if ema_diff_pct < 0.02:
            return "ranging", 1.0 - trend_strength
        return "bear", trend_strength
    else:
        return "bull", trend_strength


def _ema(data: np.ndarray, period: int) -> np.ndarray:
    """Compute exponential moving average."""
    alpha = 2.0 / (period + 1)
    ema = np.empty_like(data)
    ema[0] = data[0]
    for i in range(1, len(data)):
        ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
    return ema


def detect_all_regimes() -> dict[str, tuple[str, float]]:
    """Detect regime for each asset. Returns {asset: (label, strength)}."""
    regimes = {}
    for asset in ASSETS:
        label, strength = detect_regime(asset)
        regimes[asset] = (label, strength)
        log.info(f"Regime {asset}: {label} (strength={strength:.2f})")
    return regimes


# ---------------------------------------------------------------------------
# Step 6: Strategy-Regime Mapping (smooth, not binary)
# ---------------------------------------------------------------------------

def apply_regime_boost(strategies: list[StrategyRecord],
                       regimes: dict[str, tuple[str, float]]) -> list[StrategyRecord]:
    """
    Apply regime-based boost/penalty scaled by regime strength.
    Smooth: boost = 1.0 + (raw_boost - 1.0) * strength
    At strength=0: no boost. At strength=1: full boost.
    """
    for s in strategies:
        regime_label, regime_strength = regimes.get(s.asset, ("ranging", 0.0))
        style_boosts = STYLE_REGIME_BOOST.get(s.style, DEFAULT_REGIME_BOOST)
        raw_boost = style_boosts.get(regime_label, 1.0)
        # Smooth interpolation: at strength=0 → 1.0, at strength=1 → full boost
        s.regime_boost = 1.0 + (raw_boost - 1.0) * regime_strength
    return strategies


# ---------------------------------------------------------------------------
# Step 7: Capital Allocation
# ---------------------------------------------------------------------------

def allocate_capital(strategies: list[StrategyRecord],
                     regimes: dict[str, str]) -> list[StrategyRecord]:
    """
    Score-weighted allocation with risk caps:
    - weights = normalized_score * regime_boost
    - Hard caps per strategy (15%), per cluster (30%)
    - Risk parity: scale by inverse volatility (approx from max_dd)
    - Portfolio DD cap: scale down if simulated DD > 25%
    - Exploration budget: 10% for new (high generation) strategies
    """
    if not strategies:
        return strategies

    # Separate exploration candidates (high generation, not yet established)
    median_gen = np.median([s.generation for s in strategies])
    explore_candidates = [s for s in strategies if s.generation > median_gen]
    core_candidates = [s for s in strategies if s.generation <= median_gen]

    # If all strategies are same generation, treat all as core
    if not core_candidates:
        core_candidates = strategies
        explore_candidates = []

    # --- Core allocation (90% of capital) ---
    core_budget = 1.0 - EXPLORATION_BUDGET if explore_candidates else 1.0
    _allocate_group(core_candidates, core_budget)

    # --- Exploration allocation (10% of capital) ---
    if explore_candidates:
        explore_candidates.sort(key=lambda x: -x.score)
        top_explore = explore_candidates[:max(3, len(explore_candidates) // 3)]
        _allocate_group(top_explore, EXPLORATION_BUDGET)
        # Merge back
        explore_set = {s.strategy_code for s in top_explore}
        # Zero out non-selected explorers
        for s in explore_candidates:
            if s.strategy_code not in explore_set:
                s.weight = 0.0

    # --- Apply hard caps ---
    _apply_caps(strategies)

    # --- Portfolio DD check ---
    portfolio_dd = _estimate_portfolio_dd(strategies)
    if portfolio_dd > MAX_PORTFOLIO_DD:
        scale = 0.7
        log.warning(f"Portfolio DD {portfolio_dd:.3f} > {MAX_PORTFOLIO_DD}, scaling weights by {scale}")
        for s in strategies:
            s.weight *= scale

    # Renormalize so weights sum to ≤ 1.0
    total_weight = sum(s.weight for s in strategies)
    if total_weight > 1.0:
        for s in strategies:
            s.weight /= total_weight

    # Filter out zero-weight strategies
    allocated = [s for s in strategies if s.weight > 0.001]
    allocated.sort(key=lambda x: -x.weight)

    return allocated


def _allocate_group(group: list[StrategyRecord], budget: float):
    """Allocate within a group using score * regime_boost * risk_parity."""
    if not group:
        return

    # Risk parity: inverse volatility proxy (lower DD = higher allocation)
    inv_vol = []
    for s in group:
        dd = max(s.max_drawdown, 0.01)  # floor to avoid div by zero
        inv_vol.append(1.0 / dd)

    total_inv_vol = sum(inv_vol)
    risk_parity = [v / total_inv_vol for v in inv_vol]

    # Combined raw weight: score * regime_boost * risk_parity
    raw_weights = []
    for i, s in enumerate(group):
        raw_weights.append(s.score * s.regime_boost * risk_parity[i])

    total_raw = sum(raw_weights)
    if total_raw == 0:
        return

    for i, s in enumerate(group):
        s.weight = (raw_weights[i] / total_raw) * budget


def _apply_caps(strategies: list[StrategyRecord]):
    """Enforce per-strategy, per-cluster, per-asset caps and min weight floor."""
    # Per-strategy cap
    for s in strategies:
        if s.weight > MAX_PER_STRATEGY:
            s.weight = MAX_PER_STRATEGY

    # Per-cluster cap
    cluster_weights: dict[int, float] = defaultdict(float)
    for s in strategies:
        cluster_weights[s.cluster_id] += s.weight

    for cid, cw in cluster_weights.items():
        if cw > MAX_PER_CLUSTER:
            scale = MAX_PER_CLUSTER / cw
            for s in strategies:
                if s.cluster_id == cid:
                    s.weight *= scale

    # Per-asset cap — force cross-asset diversification
    asset_weights: dict[str, float] = defaultdict(float)
    for s in strategies:
        asset_weights[s.asset] += s.weight

    for asset, aw in asset_weights.items():
        if aw > MAX_PER_ASSET:
            scale = MAX_PER_ASSET / aw
            log.info(f"  Asset cap: {asset} at {aw:.1%} → scaling to {MAX_PER_ASSET:.0%}")
            for s in strategies:
                if s.asset == asset:
                    s.weight *= scale

    # Min weight floor — anything below MIN_WEIGHT is noise
    for s in strategies:
        if 0 < s.weight < MIN_WEIGHT:
            s.weight = 0.0


def _estimate_portfolio_dd(strategies: list[StrategyRecord]) -> float:
    """
    Estimate portfolio max drawdown from weighted individual DDs.
    Conservative: weighted average DD with diversification benefit (sqrt of n).
    """
    allocated = [s for s in strategies if s.weight > 0.001]
    if not allocated:
        return 0.0

    weighted_dd = sum(s.weight * s.max_drawdown for s in allocated)
    # Diversification benefit: reduce by sqrt(n) factor (capped)
    n = len(allocated)
    div_factor = max(1.0 / math.sqrt(n), 0.3)
    return weighted_dd * div_factor


# ---------------------------------------------------------------------------
# Step 8: Strategy Decay Detection
# ---------------------------------------------------------------------------

def detect_decay(strategies: list[StrategyRecord]) -> list[StrategyRecord]:
    """
    Flag strategies where recent performance degrades significantly.
    Uses walk-forward degradation as a proxy (wf_degradation > 0.3 = warning).
    Also flags if wf_mean_sharpe < 50% of full sharpe.
    """
    for s in strategies:
        s.decay_flag = False

        # Check WF degradation
        if s.wf_degradation is not None and s.wf_degradation > 0.3:
            s.decay_flag = True
            continue

        # Check if WF sharpe is much lower than full sharpe
        if (s.wf_mean_sharpe is not None and s.wf_mean_sharpe > 0 and
                s.sharpe_ratio > 0):
            if s.wf_mean_sharpe < 0.5 * s.sharpe_ratio:
                s.decay_flag = True

    decay_count = sum(1 for s in strategies if s.decay_flag)
    if decay_count:
        log.warning(f"Decay detected in {decay_count} strategies")

    return strategies


# ---------------------------------------------------------------------------
# Portfolio Statistics
# ---------------------------------------------------------------------------

def compute_portfolio_stats(allocated: list[StrategyRecord]) -> dict[str, Any]:
    """Compute portfolio-level expected metrics."""
    if not allocated:
        return {
            "portfolio_expected_sharpe": 0.0,
            "portfolio_expected_dd": 0.0,
        }

    # Weighted sharpe
    total_w = sum(s.weight for s in allocated)
    if total_w == 0:
        total_w = 1.0

    weighted_sharpe = sum(s.weight * s.sharpe_ratio for s in allocated) / total_w

    # Diversification-adjusted sharpe (sqrt(n) benefit, capped)
    n = len(allocated)
    div_sharpe_boost = min(math.sqrt(n) * 0.3, 1.5)
    portfolio_sharpe = weighted_sharpe * (1.0 + div_sharpe_boost * 0.1)

    portfolio_dd = _estimate_portfolio_dd(allocated)

    return {
        "portfolio_expected_sharpe": round(portfolio_sharpe, 4),
        "portfolio_expected_dd": round(portfolio_dd, 4),
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_outputs(allocated: list[StrategyRecord],
                  regimes: dict[str, str],
                  total_strategies: int,
                  total_filtered: int,
                  stats: dict[str, Any]):
    """Write portfolio JSON and append to decisions log."""
    now = datetime.now(timezone.utc).isoformat()
    n_clusters = len(set(s.cluster_id for s in allocated))

    portfolio = {
        "timestamp": now,
        "regime": {asset: {"label": label, "strength": round(strength, 3)} for asset, (label, strength) in regimes.items()},
        "allocations": [
            {
                "strategy_code": s.strategy_code,
                "asset": s.asset,
                "timeframe": s.timeframe,
                "style": s.style,
                "weight": round(s.weight, 6),
                "score": round(s.score, 6),
                "cluster_id": s.cluster_id,
                "decay_flag": s.decay_flag,
                "regime_boost": round(s.regime_boost, 3),
                "sharpe_ratio": round(s.sharpe_ratio, 4),
                "max_drawdown": round(s.max_drawdown, 4),
            }
            for s in allocated
        ],
        "total_strategies": total_strategies,
        "total_filtered": total_filtered,
        "total_allocated": len(allocated),
        "clusters": n_clusters,
        **stats,
    }

    # Write portfolio snapshot
    PORTFOLIO_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(PORTFOLIO_OUT, "w") as f:
        json.dump(portfolio, f, indent=2)
    log.info(f"Portfolio written to {PORTFOLIO_OUT}")

    # Append to decisions log
    with open(DECISIONS_LOG, "a") as f:
        f.write(json.dumps(portfolio) + "\n")
    log.info(f"Decision appended to {DECISIONS_LOG}")

    return portfolio


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

def generate_report(allocated: list[StrategyRecord],
                    regimes: dict[str, str],
                    total_strategies: int,
                    total_filtered: int,
                    stats: dict[str, Any]) -> str:
    """Generate human-readable markdown report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    n_clusters = len(set(s.cluster_id for s in allocated)) if allocated else 0

    regime_str = " | ".join(f"{a}={label}({strength:.0%})" for a, (label, strength) in regimes.items())

    lines = [
        f"🧠 Brain Engine Report — {now}",
        "",
        f"Regime: {regime_str}",
        "",
        "Top Allocated Strategies:",
    ]

    for i, s in enumerate(allocated[:20], 1):
        decay_marker = " ⚠️ DECAY" if s.decay_flag else ""
        lines.append(
            f"  {i:2d}. {s.strategy_code} — {s.style} on {s.asset}/{s.timeframe} "
            f"| Score: {s.score:.4f} | Weight: {s.weight * 100:.2f}% "
            f"| Sharpe: {s.sharpe_ratio:.2f} | DD: {s.max_drawdown:.3f}"
            f"{decay_marker}"
        )

    if len(allocated) > 20:
        lines.append(f"  ... and {len(allocated) - 20} more")

    lines.extend([
        "",
        "Portfolio Stats:",
        f"  - Expected Sharpe: {stats['portfolio_expected_sharpe']:.4f}",
        f"  - Expected Max DD: {stats['portfolio_expected_dd'] * 100:.2f}%",
        f"  - Strategies allocated: {len(allocated)} / {total_filtered} filtered / {total_strategies} total",
        f"  - Clusters: {n_clusters}",
    ])

    # Allocation by asset
    asset_weights: dict[str, float] = defaultdict(float)
    for s in allocated:
        asset_weights[s.asset] += s.weight
    lines.append("")
    lines.append("Allocation by Asset:")
    for a in ASSETS:
        w = asset_weights.get(a, 0)
        lines.append(f"  - {a}: {w * 100:.1f}%")

    # Allocation by style
    style_weights: dict[str, float] = defaultdict(float)
    for s in allocated:
        style_weights[s.style] += s.weight
    lines.append("")
    lines.append("Allocation by Style:")
    for st, w in sorted(style_weights.items(), key=lambda x: -x[1]):
        lines.append(f"  - {st}: {w * 100:.1f}%")

    # Alerts
    alerts = []
    decay_strats = [s for s in allocated if s.decay_flag]
    if decay_strats:
        alerts.append(f"⚠️  Decay detected in {len(decay_strats)} strategies: "
                       + ", ".join(s.strategy_code for s in decay_strats[:5]))

    # Concentration warnings
    for a, w in asset_weights.items():
        if w > 0.6:
            alerts.append(f"⚠️  High concentration in {a}: {w * 100:.1f}%")

    for cid in set(s.cluster_id for s in allocated):
        cw = sum(s.weight for s in allocated if s.cluster_id == cid)
        if cw > MAX_PER_CLUSTER:
            alerts.append(f"⚠️  Cluster {cid} exceeds cap: {cw * 100:.1f}%")

    if not alerts:
        alerts.append("✅ No alerts")

    lines.extend(["", "Alerts:"])
    for a in alerts:
        lines.append(f"  - {a}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def run_cycle(report_mode: bool = False) -> Optional[str]:
    """Execute one full brain engine cycle."""
    log.info("=" * 60)
    log.info("🧠 Brain Engine V2 — Starting cycle")
    log.info("=" * 60)

    t0 = time.time()

    # Step 1: Load registry
    if not RUN_LOG.exists():
        log.error(f"Run log not found: {RUN_LOG}")
        return None
    registry = load_strategy_registry(RUN_LOG)
    total_strategies = len(registry)

    if total_strategies == 0:
        log.warning("No strategies found in run log")
        return None

    # Step 2: Quality filter
    filtered = apply_quality_filters(registry)
    total_filtered = len(filtered)

    if not filtered:
        log.warning("No strategies passed quality filters")
        regimes = detect_all_regimes()
        stats = compute_portfolio_stats([])
        portfolio = write_outputs([], regimes, total_strategies, 0, stats)
        if report_mode:
            return generate_report([], regimes, total_strategies, 0, stats)
        return None

    # Step 3: Cluster
    clustered = cluster_strategies(filtered)

    # Step 4: Score
    scored = score_strategies(clustered)

    # Step 5: Regime detection
    regimes = detect_all_regimes()

    # Step 6: Regime boost
    boosted = apply_regime_boost(scored, regimes)

    # Step 7: Decay detection
    decayed = detect_decay(boosted)

    # Step 8: Capital allocation
    allocated = allocate_capital(decayed, regimes)

    # Step 9: Portfolio stats
    stats = compute_portfolio_stats(allocated)

    # Step 10: Output
    write_outputs(allocated, regimes, total_strategies, total_filtered, stats)

    elapsed = time.time() - t0
    log.info(f"Cycle complete in {elapsed:.2f}s — {len(allocated)} strategies allocated")

    if report_mode:
        return generate_report(allocated, regimes, total_strategies, total_filtered, stats)

    # Print brief summary
    report = generate_report(allocated, regimes, total_strategies, total_filtered, stats)
    print(report)
    return report


# ---------------------------------------------------------------------------
# Daemon Mode
# ---------------------------------------------------------------------------

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    log.info(f"Received signal {signum}, shutting down...")
    _shutdown = True


def run_daemon():
    """Run brain engine every DAEMON_INTERVAL_SEC seconds."""
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info(f"🧠 Brain Engine daemon started (interval={DAEMON_INTERVAL_SEC}s)")

    while not _shutdown:
        try:
            run_cycle(report_mode=False)
        except Exception:
            log.exception("Cycle failed")

        # Sleep in small increments to check shutdown flag
        for _ in range(DAEMON_INTERVAL_SEC):
            if _shutdown:
                break
            time.sleep(1)

    log.info("🧠 Brain Engine daemon stopped")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="🧠 Brain Engine V2 — Portfolio Decision Engine")
    parser.add_argument("--daemon", action="store_true", help="Run continuously every 30 minutes")
    parser.add_argument("--report", action="store_true", help="Generate markdown report to stdout")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.daemon:
        run_daemon()
    elif args.report:
        report = run_cycle(report_mode=True)
        if report:
            print(report)
        else:
            print("🧠 Brain Engine: No data to report")
    else:
        run_cycle(report_mode=False)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# systemd service configuration
# ---------------------------------------------------------------------------
#
# Save as: /etc/systemd/system/brain-engine.service
#
# [Unit]
# Description=Brain Engine V2 — Trading Portfolio Decision Engine
# After=network.target
# Wants=network-online.target
#
# [Service]
# Type=simple
# User=ochenryceo
# Group=ochenryceo
# WorkingDirectory=Path(__file__).resolve().parents[1]
# ExecStart=/usr/bin/python3 Path(__file__).resolve().parents[1]/services/brain_v2.py --daemon
# Restart=on-failure
# RestartSec=30
# StandardOutput=journal
# StandardError=journal
# Environment=PYTHONUNBUFFERED=1
# MemoryMax=512M
# CPUQuota=50%
#
# [Install]
# WantedBy=multi-user.target
#
# Commands:
#   sudo systemctl daemon-reload
#   sudo systemctl enable brain-engine
#   sudo systemctl start brain-engine
#   sudo journalctl -u brain-engine -f
# ---------------------------------------------------------------------------

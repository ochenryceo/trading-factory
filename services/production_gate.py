"""
Production Gate — Final Validation Before Paper/Live Trading
=============================================================
Only allows strategies into paper trading if they pass ALL checks:
  - Performance (Sharpe, PF, WR)
  - Drawdown control (max DD, avg DD)
  - Trade robustness (count, density)
  - Monte Carlo stability (200 runs)
  - Walk-forward stability (5 periods)
  - Lineage stability (descendant consistency)
  - Prop constraint simulation ($50K account)

Pipeline position:
  Promotion → Candidate Pool → [PRODUCTION GATE] → Paper Trading

Scoring:
  >= 0.85 → APPROVED → paper trading + Discord alert
  0.75-0.85 → WATCHLIST → re-test after 10 gens
  < 0.75 → REJECTED → back to evolution pool with failure reason

Author: Henry (autonomous build)
Date: 2026-03-26
"""

import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("production_gate")

BASE_DIR = Path("Path(__file__).resolve().parents[1]")
DATA_DIR = BASE_DIR / "data" / "processed"
GATE_STATE_FILE = BASE_DIR / "data" / "production_gate_state.json"
GATE_LOG_FILE = BASE_DIR / "data" / "production_gate_log.jsonl"
LINEAGE_FILE = BASE_DIR / "data" / "lineage_scores.json"
NEAR_MISS_FILE = BASE_DIR / "data" / "near_misses.jsonl"

# ─── Pre-Filter (must meet ALL to even evaluate) ───────────────────────────

PRE_FILTER = {
    "min_fitness": 0.90,
    "min_stability": 0.90,
    "min_trades": 80,
    "min_lineage_depth": 20,
}

# ─── Core Validation Thresholds ────────────────────────────────────────────

# A. Performance
PERF_MIN_SHARPE = 1.2
PERF_MIN_PF = 1.2
PERF_MIN_WR = 0.45

# B. Drawdown
DD_MAX = 0.25
DD_AVG_MAX = 0.15

# C. Trade Robustness
ROBUST_MIN_TRADES = 100
ROBUST_MIN_DENSITY = 0.002

# D. Monte Carlo
MC_RUNS = 200
MC_MIN_SHARPE_MEAN = 1.0
MC_MAX_DD_P95 = 0.35
MC_MIN_CONSISTENCY = 0.70  # % of runs profitable

# E. Walk-Forward
WF_PERIODS = 5
WF_MIN_SHARPE_MEAN = 0.8
WF_MAX_DEGRADATION = 0.50
WF_MIN_CONSISTENCY = 0.60

# F. Lineage
LINEAGE_MIN_STABILITY = 0.90

# G. Prop Simulation
PROP_BALANCE = 50_000
PROP_TARGET_PCT = 0.10        # 10% profit target
PROP_MAX_DD_PCT = 0.10        # 10% max drawdown
PROP_DAILY_DD_PCT = 0.05      # 5% daily drawdown
PROP_MIN_PROFIT_PCT = 0.08    # must reach 8% before any failure
PROP_MAX_SINGLE_DAY_SHARE = 0.40  # no single day > 40% of total profit

# H. Failure Density (tail risk)
MC_WORST_5PCT_DD_MAX = 0.40   # worst 5% of MC runs must have DD < 40%

# I. Trade Distribution
TRADE_CONCENTRATION_LIMIT = 0.80  # top 20% of trades can't hold > 80% of profit

# J. Regime Dependency
REGIME_MIN_CONSISTENCY = 0.50  # must be profitable in >= 50% of regime splits

# ─── Scoring Weights ───────────────────────────────────────────────────────

SCORE_WEIGHTS = {
    "sharpe": 0.25,
    "return": 0.15,
    "mc": 0.15,
    "wf": 0.15,
    "stability": 0.15,
    "dd": 0.15,
}

# Decision thresholds
APPROVE_THRESHOLD = 0.85
WATCHLIST_THRESHOLD = 0.75

# Watchlist re-test interval
WATCHLIST_RETEST_GENS = 10


# ─── State Management ──────────────────────────────────────────────────────

def load_gate_state() -> dict:
    if GATE_STATE_FILE.exists():
        try:
            with open(GATE_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "approved": {},      # strategy_id -> approval data
        "watchlist": {},     # strategy_id -> watchlist data
        "rejected": {},      # strategy_id -> rejection data (recent only)
        "total_evaluated": 0,
        "total_approved": 0,
        "total_rejected": 0,
        "total_watchlisted": 0,
    }


def save_gate_state(state: dict):
    GATE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(GATE_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _log_gate_event(event: str, details: dict = None):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **(details or {}),
    }
    GATE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(GATE_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    log.info(f"🚪 GATE: {event} | {details or ''}")


# ─── Monte Carlo (Deep) ────────────────────────────────────────────────────

def _deep_monte_carlo(returns: list[float], n_sims: int = MC_RUNS) -> dict:
    """
    Full Monte Carlo simulation on trade returns.
    Shuffles trade order, measures Sharpe/DD distribution.
    """
    import numpy as np

    if not returns or len(returns) < 20:
        return {
            "mc_sharpe_mean": 0.0,
            "mc_dd_p95": 1.0,
            "mc_consistency": 0.0,
            "mc_passed": False,
        }

    arr = np.array(returns, dtype=np.float64)
    sharpes = []
    max_dds = []
    profitable = 0

    early_exit_checkpoint = min(50, n_sims // 4)  # check after 25% of runs

    for sim_i in range(n_sims):
        shuffled = np.random.permutation(arr)
        equity = np.cumsum(shuffled)

        # Sharpe
        if np.std(shuffled) > 1e-10:
            sh = float(np.mean(shuffled) / np.std(shuffled) * np.sqrt(252))
        else:
            sh = 0.0
        sharpes.append(sh)

        # Max drawdown
        peak = np.maximum.accumulate(equity)
        dd = np.where(peak > 0, (peak - equity) / peak, 0)
        max_dds.append(float(np.max(dd)) if len(dd) > 0 else 0.0)

        # Profitable?
        if equity[-1] > 0:
            profitable += 1

        # Early exit: if after checkpoint the numbers are hopeless, stop
        if sim_i == early_exit_checkpoint and early_exit_checkpoint > 10:
            interim_sharpe = float(np.mean(sharpes))
            interim_consistency = profitable / (sim_i + 1)
            if interim_sharpe < MC_MIN_SHARPE_MEAN * 0.5 or interim_consistency < MC_MIN_CONSISTENCY * 0.5:
                log.debug(f"MC early exit at {sim_i+1}/{n_sims}: sharpe={interim_sharpe:.2f}, consistency={interim_consistency:.0%}")
                break

    actual_sims = len(sharpes)
    mc_sharpe_mean = float(np.mean(sharpes))
    mc_dd_p95 = float(np.percentile(max_dds, 95))
    mc_consistency = profitable / max(actual_sims, 1)

    return {
        "mc_sharpe_mean": round(mc_sharpe_mean, 4),
        "mc_dd_p95": round(mc_dd_p95, 4),
        "mc_consistency": round(mc_consistency, 4),
        "mc_dd_list": max_dds,  # full list for failure density check
        "mc_passed": (
            mc_sharpe_mean >= MC_MIN_SHARPE_MEAN
            and mc_dd_p95 <= MC_MAX_DD_P95
            and mc_consistency >= MC_MIN_CONSISTENCY
        ),
    }


# ─── Walk-Forward (Deep) ───────────────────────────────────────────────────

def _deep_walk_forward(
    close: "np.ndarray", high: "np.ndarray", low: "np.ndarray",
    volume: "np.ndarray", style: str, params: dict,
    n_periods: int = WF_PERIODS,
) -> dict:
    """
    Anchored walk-forward with N periods.
    60% in-sample / 40% out-of-sample per fold.
    """
    import numpy as np

    n = len(close)
    if n < 500:
        return {
            "wf_sharpe_mean": 0.0,
            "wf_degradation": 1.0,
            "wf_consistency": 0.0,
            "wf_passed": False,
        }

    # Import signal generator from backtester
    try:
        from services.continuous_backtester_v2 import (
            _generate_signals, _backtest_vectorized,
        )
    except ImportError:
        return {
            "wf_sharpe_mean": 0.0,
            "wf_degradation": 1.0,
            "wf_consistency": 0.0,
            "wf_passed": False,
        }

    fold_size = n // n_periods
    is_sharpes = []
    oos_sharpes = []

    for i in range(n_periods):
        fold_start = i * fold_size
        fold_end = min((i + 1) * fold_size, n)
        split = fold_start + int((fold_end - fold_start) * 0.6)

        # In-sample
        is_pos = _generate_signals(
            style, params,
            close[fold_start:split], high[fold_start:split],
            low[fold_start:split], volume[fold_start:split],
        )
        is_metrics = _backtest_vectorized(close[fold_start:split], is_pos)
        is_sharpes.append(is_metrics.get("sharpe_ratio", 0))

        # Out-of-sample
        oos_pos = _generate_signals(
            style, params,
            close[split:fold_end], high[split:fold_end],
            low[split:fold_end], volume[split:fold_end],
        )
        oos_metrics = _backtest_vectorized(close[split:fold_end], oos_pos)
        oos_sharpes.append(oos_metrics.get("sharpe_ratio", 0))

    wf_sharpe_mean = np.mean(oos_sharpes) if oos_sharpes else 0.0
    is_mean = np.mean(is_sharpes) if is_sharpes else 0.001

    # Degradation = how much OOS drops from IS
    wf_degradation = max(0, 1.0 - (wf_sharpe_mean / max(is_mean, 0.001)))
    wf_consistency = sum(1 for s in oos_sharpes if s > 0) / max(len(oos_sharpes), 1)

    return {
        "wf_sharpe_mean": round(float(wf_sharpe_mean), 4),
        "wf_degradation": round(float(wf_degradation), 4),
        "wf_consistency": round(float(wf_consistency), 4),
        "wf_passed": (
            wf_sharpe_mean >= WF_MIN_SHARPE_MEAN
            and wf_degradation <= WF_MAX_DEGRADATION
            and wf_consistency >= WF_MIN_CONSISTENCY
        ),
    }


# ─── Prop Simulation ───────────────────────────────────────────────────────

def _simulate_prop(returns: list[float]) -> dict:
    """
    Simulate strategy on a prop account.
    Checks daily DD, total DD, and profit target.
    """
    balance = PROP_BALANCE
    peak = balance
    daily_start = balance
    max_profit_pct = 0.0
    breached_daily = False
    breached_total = False
    target_reached = False
    day_count = 0

    for i, ret in enumerate(returns):
        # Apply return as percentage of current balance
        pnl = balance * ret
        balance += pnl

        # Track peak
        peak = max(peak, balance)

        # Daily DD check (reset every ~8 trades as proxy for a day)
        if i % 8 == 0 and i > 0:
            daily_start = balance
            day_count += 1
        daily_dd = (daily_start - balance) / PROP_BALANCE if balance < daily_start else 0
        if daily_dd > PROP_DAILY_DD_PCT:
            breached_daily = True

        # Total DD check
        total_dd = (peak - balance) / PROP_BALANCE
        if total_dd > PROP_MAX_DD_PCT:
            breached_total = True

        # Profit tracking
        profit_pct = (balance - PROP_BALANCE) / PROP_BALANCE
        max_profit_pct = max(max_profit_pct, profit_pct)

        # Target check
        if profit_pct >= PROP_TARGET_PCT:
            target_reached = True

    final_profit = (balance - PROP_BALANCE) / PROP_BALANCE
    reached_min = max_profit_pct >= PROP_MIN_PROFIT_PCT

    # Single-day profit concentration check
    # Track daily PnL (proxy: every 8 trades = 1 day)
    daily_pnls = []
    day_pnl = 0.0
    for i, ret in enumerate(returns):
        day_pnl += PROP_BALANCE * ret
        if (i + 1) % 8 == 0 or i == len(returns) - 1:
            daily_pnls.append(day_pnl)
            day_pnl = 0.0

    total_profit_abs = sum(p for p in daily_pnls if p > 0)
    max_single_day = max(daily_pnls) if daily_pnls else 0
    single_day_share = max_single_day / max(total_profit_abs, 1)
    single_day_ok = single_day_share <= PROP_MAX_SINGLE_DAY_SHARE

    return {
        "prop_balance_final": round(balance, 2),
        "prop_profit_pct": round(final_profit, 4),
        "prop_max_profit_pct": round(max_profit_pct, 4),
        "prop_breached_daily": breached_daily,
        "prop_breached_total": breached_total,
        "prop_target_reached": target_reached,
        "prop_reached_min_profit": reached_min,
        "prop_single_day_share": round(single_day_share, 4),
        "prop_single_day_ok": single_day_ok,
        "prop_passed": not breached_daily and not breached_total and reached_min and single_day_ok,
    }


# ─── Failure Density (Tail Risk) ────────────────────────────────────────────

def _check_failure_density(mc_dds: list[float]) -> dict:
    """
    Check the worst 5% of MC drawdowns.
    If even rare scenarios blow up, reject.
    """
    import numpy as np
    if not mc_dds or len(mc_dds) < 20:
        return {"worst_5pct_dd": 1.0, "passed": False}

    p95_dd = float(np.percentile(mc_dds, 95))
    return {
        "worst_5pct_dd": round(p95_dd, 4),
        "passed": p95_dd <= MC_WORST_5PCT_DD_MAX,
    }


# ─── Trade Distribution Stability ──────────────────────────────────────────

def _check_trade_distribution(returns: list[float]) -> dict:
    """
    Check if profits are evenly distributed or clustered.
    Top 20% of trades shouldn't hold > 80% of total profit.
    """
    if not returns or len(returns) < 10:
        return {"top20_share": 1.0, "passed": False}

    # Only look at profitable trades
    profits = sorted([r for r in returns if r > 0], reverse=True)
    if not profits:
        return {"top20_share": 1.0, "passed": False}

    total_profit = sum(profits)
    if total_profit <= 0:
        return {"top20_share": 1.0, "passed": False}

    top_20_count = max(1, len(profits) // 5)
    top_20_profit = sum(profits[:top_20_count])
    top20_share = top_20_profit / total_profit

    return {
        "top20_share": round(top20_share, 4),
        "profitable_trades": len(profits),
        "passed": top20_share <= TRADE_CONCENTRATION_LIMIT,
    }


# ─── Regime Dependency Check ───────────────────────────────────────────────

def _check_regime_dependency(
    close: "np.ndarray", returns: list[float],
) -> dict:
    """
    Split data into trending vs ranging regimes.
    Strategy must be profitable in >= 50% of regime splits.
    
    Simple regime detection: 50-bar EMA slope.
    Positive slope = trending, negative/flat = ranging.
    """
    import numpy as np

    if close is None or len(close) < 200 or len(returns) < 20:
        return {"regime_consistency": 0.0, "passed": False}

    # Compute 50-bar EMA slope as regime indicator
    n = len(close)
    ema = np.zeros(n)
    ema[0] = close[0]
    alpha = 2 / 51
    for i in range(1, n):
        ema[i] = alpha * close[i] + (1 - alpha) * ema[i - 1]

    # Slope over 10 bars (smoothed direction)
    slope = np.zeros(n)
    for i in range(10, n):
        slope[i] = ema[i] - ema[i - 10]

    # Split into 4 chunks, classify each as trending or ranging
    chunk_size = n // 4
    regime_results = []
    trade_idx = 0
    returns_per_chunk = max(1, len(returns) // 4)

    for c in range(4):
        start = c * chunk_size
        end = min((c + 1) * chunk_size, n)
        chunk_slope = slope[start:end]

        # Classify: if mean absolute slope is above median, it's trending
        abs_slope_mean = float(np.mean(np.abs(chunk_slope)))
        overall_abs_mean = float(np.mean(np.abs(slope[50:])))
        is_trending = abs_slope_mean > overall_abs_mean

        # Get returns for this chunk
        chunk_start = c * returns_per_chunk
        chunk_end = min((c + 1) * returns_per_chunk, len(returns))
        chunk_returns = returns[chunk_start:chunk_end]

        if chunk_returns:
            chunk_profitable = sum(chunk_returns) > 0
        else:
            chunk_profitable = False

        regime_results.append({
            "regime": "trending" if is_trending else "ranging",
            "profitable": chunk_profitable,
        })

    profitable_regimes = sum(1 for r in regime_results if r["profitable"])
    regime_consistency = profitable_regimes / max(len(regime_results), 1)

    return {
        "regime_consistency": round(regime_consistency, 4),
        "regime_splits": regime_results,
        "passed": regime_consistency >= REGIME_MIN_CONSISTENCY,
    }


# ─── Lineage Stability ─────────────────────────────────────────────────────

def _get_lineage_stability(lineage_id: str) -> float:
    """
    Get stability score for a lineage from promotion state.
    Falls back to computing from lineage_scores.json.
    """
    # Try promotion state first
    try:
        from services.lineage_promotion import load_promotion_state
        ps = load_promotion_state()
        promoted = ps.get("promoted", {})
        if lineage_id in promoted:
            stab = promoted[lineage_id].get("stability_score")
            if stab is not None:
                return stab
    except Exception:
        pass

    # Fallback: compute from lineage scores
    if LINEAGE_FILE.exists():
        try:
            with open(LINEAGE_FILE) as f:
                lineages = json.load(f)
            ldata = lineages.get(lineage_id, {})
            if isinstance(ldata, dict):
                gens = ldata.get("generations", [])
                if len(gens) >= 5:
                    top5 = sorted(gens, reverse=True)[:5]
                    mean_f = sum(top5) / 5
                    if mean_f > 0:
                        std_f = (sum((x - mean_f) ** 2 for x in top5) / 5) ** 0.5
                        return round(1.0 - min(1.0, std_f / mean_f), 3)
        except Exception:
            pass

    return 0.0


# ─── Production Score ──────────────────────────────────────────────────────

def _compute_score(metrics: dict, mc: dict, wf: dict, stability: float, prop: dict) -> float:
    """
    Weighted production score. Higher = more production-ready.
    """
    # Normalize components to 0-1 scale
    sharpe_score = min(1.0, max(0, metrics.get("sharpe_ratio", 0)) / 3.0)
    return_score = min(1.0, max(0, metrics.get("total_return_pct", 0)) / 500.0)
    mc_score = (
        min(1.0, max(0, mc["mc_sharpe_mean"]) / 2.0) * 0.4
        + (1.0 - min(1.0, mc["mc_dd_p95"] / 0.5)) * 0.3
        + mc["mc_consistency"] * 0.3
    )
    wf_score = (
        min(1.0, max(0, wf["wf_sharpe_mean"]) / 2.0) * 0.4
        + (1.0 - min(1.0, wf["wf_degradation"])) * 0.3
        + wf["wf_consistency"] * 0.3
    )
    stability_score = stability
    dd_score = 1.0 - min(1.0, metrics.get("max_drawdown", 1.0) / 0.30)

    score = (
        SCORE_WEIGHTS["sharpe"] * sharpe_score
        + SCORE_WEIGHTS["return"] * return_score
        + SCORE_WEIGHTS["mc"] * mc_score
        + SCORE_WEIGHTS["wf"] * wf_score
        + SCORE_WEIGHTS["stability"] * stability_score
        + SCORE_WEIGHTS["dd"] * dd_score
    )
    return round(score, 4)


# ─── Main Evaluation ───────────────────────────────────────────────────────

def pre_filter(candidate: dict) -> tuple[bool, str]:
    """
    Quick pre-filter. Returns (passed, reason).
    Prevents wasting compute on weak candidates.
    """
    fitness = candidate.get("fitness", 0)
    stability = candidate.get("stability_score", 0)
    trades = candidate.get("trade_count", 0)
    lineage_depth = candidate.get("survival_depth", 0)

    if fitness < PRE_FILTER["min_fitness"]:
        return False, f"fitness {fitness:.2f} < {PRE_FILTER['min_fitness']}"
    if stability and stability < PRE_FILTER["min_stability"]:
        return False, f"stability {stability:.2f} < {PRE_FILTER['min_stability']}"
    if trades < PRE_FILTER["min_trades"]:
        return False, f"trades {trades} < {PRE_FILTER['min_trades']}"
    if lineage_depth < PRE_FILTER["min_lineage_depth"]:
        return False, f"lineage_depth {lineage_depth} < {PRE_FILTER['min_lineage_depth']}"

    return True, "passed"


def evaluate(
    candidate: dict,
    returns: Optional[list[float]] = None,
    close: Optional["np.ndarray"] = None,
    high: Optional["np.ndarray"] = None,
    low: Optional["np.ndarray"] = None,
    volume: Optional["np.ndarray"] = None,
    generation: int = 0,
) -> dict:
    """
    Full production gate evaluation.
    
    Args:
        candidate: Strategy dict with metrics, params, style, lineage info
        returns: List of per-trade returns (for MC + prop sim)
        close/high/low/volume: Price arrays (for deep WF)
        generation: Current generation number
    
    Returns:
        Result dict with status (APPROVED/WATCHLIST/REJECTED), score, all checks
    """
    strategy_id = candidate.get("strategy_code", candidate.get("id", "unknown"))
    style = candidate.get("style", "unknown")
    params = candidate.get("parameters", {})
    lineage_id = candidate.get("lineage_id", "")

    result = {
        "strategy_id": strategy_id,
        "style": style,
        "lineage_id": lineage_id,
        "generation": generation,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {},
        "status": "REJECTED",
        "production_score": 0.0,
        "failure_reasons": [],
    }

    # ══════════════════════════════════════════════════════════════
    # STAGE 1 — Fast Filter (cheap, run on all candidates)
    # Rejects ~70-80% immediately before any expensive compute
    # ══════════════════════════════════════════════════════════════

    # ── A. Performance ──
    sharpe = candidate.get("sharpe_ratio", candidate.get("sharpe", 0))
    pf = candidate.get("profit_factor", 0)
    wr = candidate.get("win_rate", 0)
    perf_pass = sharpe >= PERF_MIN_SHARPE and pf >= PERF_MIN_PF and wr >= PERF_MIN_WR
    result["checks"]["performance"] = {
        "sharpe": sharpe, "profit_factor": pf, "win_rate": wr,
        "passed": perf_pass,
    }
    if not perf_pass:
        reasons = []
        if sharpe < PERF_MIN_SHARPE: reasons.append(f"sharpe {sharpe:.2f} < {PERF_MIN_SHARPE}")
        if pf < PERF_MIN_PF: reasons.append(f"PF {pf:.2f} < {PERF_MIN_PF}")
        if wr < PERF_MIN_WR: reasons.append(f"WR {wr:.2f} < {PERF_MIN_WR}")
        result["failure_reasons"].extend(reasons)

    # ── B. Drawdown ──
    max_dd = candidate.get("max_drawdown", 1.0)
    avg_dd = candidate.get("avg_drawdown", max_dd * 0.6)  # estimate if not available
    dd_pass = max_dd <= DD_MAX and avg_dd <= DD_AVG_MAX
    result["checks"]["drawdown"] = {
        "max_dd": max_dd, "avg_dd": avg_dd, "passed": dd_pass,
    }
    if not dd_pass:
        if max_dd > DD_MAX: result["failure_reasons"].append(f"max_dd {max_dd:.2%} > {DD_MAX:.0%}")
        if avg_dd > DD_AVG_MAX: result["failure_reasons"].append(f"avg_dd {avg_dd:.2%} > {DD_AVG_MAX:.0%}")

    # ── C. Trade Robustness ──
    trades = candidate.get("trade_count", candidate.get("trades", 0))
    density = candidate.get("trade_density", 0)
    if density == 0 and trades > 0:
        # Estimate density from trade count and typical bar count
        density = trades / 10000  # rough estimate
    robust_pass = trades >= ROBUST_MIN_TRADES and density >= ROBUST_MIN_DENSITY
    result["checks"]["robustness"] = {
        "trades": trades, "density": round(density, 5), "passed": robust_pass,
    }
    if not robust_pass:
        if trades < ROBUST_MIN_TRADES: result["failure_reasons"].append(f"trades {trades} < {ROBUST_MIN_TRADES}")
        if density < ROBUST_MIN_DENSITY: result["failure_reasons"].append(f"density {density:.5f} < {ROBUST_MIN_DENSITY}")

    # ── STAGE 1 GATE — reject early if any fast check failed ──
    stage1_passed = perf_pass and dd_pass and robust_pass
    result["checks"]["stage1_passed"] = stage1_passed
    if not stage1_passed:
        result["status"] = "REJECTED"
        result["production_score"] = 0.0
        result["failure_reasons"].append("STAGE 1 REJECT (fast filter)")
        _log_gate_event("REJECTED_STAGE1", {
            "strategy_id": strategy_id, "failure_reasons": result["failure_reasons"],
        })
        state = load_gate_state()
        state["total_evaluated"] = state.get("total_evaluated", 0) + 1
        state["total_rejected"] = state.get("total_rejected", 0) + 1
        rejected = state.get("rejected", {})
        rejected[strategy_id] = {
            "score": 0.0, "rejected_at": datetime.now(timezone.utc).isoformat(),
            "failure_reasons": result["failure_reasons"], "stage": 1,
        }
        if len(rejected) > 50:
            oldest = sorted(rejected, key=lambda k: rejected[k].get("rejected_at", ""))[:len(rejected) - 50]
            for k in oldest: del rejected[k]
        state["rejected"] = rejected
        save_gate_state(state)
        feed_rejection_back(result, candidate)
        return result

    # ══════════════════════════════════════════════════════════════
    # STAGE 2 — Robustness Layer (moderate cost, ~20-30% of candidates)
    # ══════════════════════════════════════════════════════════════

    # ── D. Monte Carlo ──
    if returns and len(returns) >= 20:
        mc = _deep_monte_carlo(returns, MC_RUNS)
    else:
        mc = {
            "mc_sharpe_mean": candidate.get("mc_mean_return", 0),
            "mc_dd_p95": candidate.get("mc_worst_dd", 1.0),
            "mc_consistency": 0.0,
            "mc_passed": False,
        }
    result["checks"]["monte_carlo"] = mc
    if not mc.get("mc_passed", False):
        result["failure_reasons"].append(f"MC failed (sharpe={mc['mc_sharpe_mean']:.2f}, dd_p95={mc['mc_dd_p95']:.2%}, consistency={mc['mc_consistency']:.0%})")

    # ── E. Walk-Forward ──
    if close is not None and len(close) >= 500:
        wf = _deep_walk_forward(close, high, low, volume, style, params, WF_PERIODS)
    else:
        wf = {
            "wf_sharpe_mean": candidate.get("wf_mean_sharpe", 0),
            "wf_degradation": candidate.get("wf_degradation", 1.0),
            "wf_consistency": 0.0,
            "wf_passed": False,
        }
    result["checks"]["walk_forward"] = wf
    if not wf.get("wf_passed", False):
        result["failure_reasons"].append(f"WF failed (sharpe={wf['wf_sharpe_mean']:.2f}, degrad={wf['wf_degradation']:.2f}, consistency={wf['wf_consistency']:.0%})")

    # ── F. Lineage Stability ──
    lineage_stab = _get_lineage_stability(lineage_id)
    lineage_pass = lineage_stab >= LINEAGE_MIN_STABILITY
    result["checks"]["lineage_stability"] = {
        "stability": lineage_stab, "passed": lineage_pass,
    }
    if not lineage_pass:
        result["failure_reasons"].append(f"lineage stability {lineage_stab:.2f} < {LINEAGE_MIN_STABILITY}")

    # ── G. Prop Simulation ──
    if returns and len(returns) >= 20:
        prop = _simulate_prop(returns)
    else:
        prop = {"prop_passed": False, "prop_profit_pct": 0, "prop_breached_daily": True,
                "prop_breached_total": True, "prop_reached_min_profit": False,
                "prop_max_profit_pct": 0, "prop_target_reached": False,
                "prop_balance_final": PROP_BALANCE}
    result["checks"]["prop_simulation"] = prop
    if not prop.get("prop_passed", False):
        reasons = []
        if prop.get("prop_breached_daily"): reasons.append("daily DD breach")
        if prop.get("prop_breached_total"): reasons.append("total DD breach")
        if not prop.get("prop_reached_min_profit"): reasons.append(f"max profit {prop.get('prop_max_profit_pct',0):.1%} < {PROP_MIN_PROFIT_PCT:.0%}")
        result["failure_reasons"].extend(reasons)

    # ── STAGE 2 GATE — reject before expensive stage 3 ──
    stage2_passed = mc.get("mc_passed", False) and wf.get("wf_passed", False) and lineage_pass
    result["checks"]["stage2_passed"] = stage2_passed
    if not stage2_passed:
        # Still compute score for watchlist potential
        metrics_for_score = {
            "sharpe_ratio": sharpe, "total_return_pct": candidate.get("total_return_pct", 0),
            "max_drawdown": max_dd,
        }
        score = _compute_score(metrics_for_score, mc, wf, lineage_stab, 
                               {"prop_passed": False})
        result["production_score"] = score
        result["failure_reasons"].append("STAGE 2 REJECT (robustness)")

        if score >= WATCHLIST_THRESHOLD:
            result["status"] = "WATCHLIST"
        else:
            result["status"] = "REJECTED"

        _log_gate_event(f"{result['status']}_STAGE2", {
            "strategy_id": strategy_id, "score": score,
            "failure_reasons": result["failure_reasons"],
        })

        state = load_gate_state()
        state["total_evaluated"] = state.get("total_evaluated", 0) + 1
        if result["status"] == "WATCHLIST":
            state["watchlist"][strategy_id] = {
                "score": score, "added_at": datetime.now(timezone.utc).isoformat(),
                "generation": generation, "retest_at_gen": generation + WATCHLIST_RETEST_GENS,
                "lineage_id": lineage_id, "failure_reasons": result["failure_reasons"],
            }
            state["total_watchlisted"] = state.get("total_watchlisted", 0) + 1
            log.info(f"👀 WATCHLIST (stage 2): {strategy_id} (score={score:.2f})")
        else:
            state["total_rejected"] = state.get("total_rejected", 0) + 1
            rejected = state.get("rejected", {})
            rejected[strategy_id] = {
                "score": score, "rejected_at": datetime.now(timezone.utc).isoformat(),
                "failure_reasons": result["failure_reasons"], "stage": 2,
            }
            if len(rejected) > 50:
                oldest = sorted(rejected, key=lambda k: rejected[k].get("rejected_at", ""))[:len(rejected) - 50]
                for k in oldest: del rejected[k]
            state["rejected"] = rejected
        save_gate_state(state)
        feed_rejection_back(result, candidate)
        return result

    # ══════════════════════════════════════════════════════════════
    # STAGE 3 — Final Deployment Check (expensive, ~5% of candidates)
    # ══════════════════════════════════════════════════════════════

    # ── H. Failure Density (tail risk from MC) ──
    failure_density = _check_failure_density(mc.get("mc_dd_list", []))
    result["checks"]["failure_density"] = failure_density
    if not failure_density.get("passed", False):
        result["failure_reasons"].append(f"tail risk: worst 5% DD {failure_density.get('worst_5pct_dd', 0):.1%} > {MC_WORST_5PCT_DD_MAX:.0%}")

    # ── I. Trade Distribution ──
    if returns and len(returns) >= 10:
        trade_dist = _check_trade_distribution(returns)
    else:
        trade_dist = {"top20_share": 1.0, "passed": False}
    result["checks"]["trade_distribution"] = trade_dist
    if not trade_dist.get("passed", False):
        result["failure_reasons"].append(f"trade clustering: top 20% holds {trade_dist.get('top20_share', 0):.0%} of profit")

    # ── J. Regime Dependency ──
    if close is not None and returns and len(returns) >= 20:
        regime = _check_regime_dependency(close, returns)
    else:
        regime = {"regime_consistency": 0.0, "passed": False}
    result["checks"]["regime_dependency"] = regime
    if not regime.get("passed", False):
        result["failure_reasons"].append(f"regime dependent: consistency {regime.get('regime_consistency', 0):.0%} < {REGIME_MIN_CONSISTENCY:.0%}")

    # ── Compute production score ──
    metrics_for_score = {
        "sharpe_ratio": sharpe,
        "total_return_pct": candidate.get("total_return_pct", 0),
        "max_drawdown": max_dd,
    }
    score = _compute_score(metrics_for_score, mc, wf, lineage_stab, prop)
    result["production_score"] = score

    # ── STAGE 3 Decision — all stage 1+2 already passed ──
    stage3_checks = [
        prop.get("prop_passed", False),
        failure_density.get("passed", False),
        trade_dist.get("passed", False),
        regime.get("passed", False),
    ]
    stage3_passed = all(stage3_checks)
    result["checks"]["stage3_passed"] = stage3_passed

    if score >= APPROVE_THRESHOLD and stage3_passed:
        result["status"] = "APPROVED"
    elif score >= WATCHLIST_THRESHOLD:
        result["status"] = "WATCHLIST"
        if not stage3_passed:
            result["failure_reasons"].append("STAGE 3 partial fail")
    else:
        result["status"] = "REJECTED"

    # ── Log ──
    _log_gate_event(result["status"], {
        "strategy_id": strategy_id,
        "production_score": score,
        "sharpe": sharpe,
        "profit_factor": pf,
        "max_dd": max_dd,
        "trades": trades,
        "mc_sharpe": mc.get("mc_sharpe_mean", 0),
        "mc_dd_p95": mc.get("mc_dd_p95", 0),
        "wf_sharpe": wf.get("wf_sharpe_mean", 0),
        "wf_degradation": wf.get("wf_degradation", 0),
        "lineage_stability": lineage_stab,
        "prop_passed": prop.get("prop_passed", False),
        "failure_reasons": result["failure_reasons"],
    })

    # ── Update state ──
    state = load_gate_state()
    state["total_evaluated"] = state.get("total_evaluated", 0) + 1

    if result["status"] == "APPROVED":
        state["approved"][strategy_id] = {
            "score": score,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "generation": generation,
            "lineage_id": lineage_id,
            "style": style,
        }
        state["total_approved"] = state.get("total_approved", 0) + 1
        log.warning(f"🏆 PRODUCTION APPROVED: {strategy_id} (score={score:.2f}, sharpe={sharpe:.2f})")

    elif result["status"] == "WATCHLIST":
        state["watchlist"][strategy_id] = {
            "score": score,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "generation": generation,
            "retest_at_gen": generation + WATCHLIST_RETEST_GENS,
            "lineage_id": lineage_id,
            "failure_reasons": result["failure_reasons"],
        }
        state["total_watchlisted"] = state.get("total_watchlisted", 0) + 1
        log.info(f"👀 WATCHLIST: {strategy_id} (score={score:.2f}, retest at gen {generation + WATCHLIST_RETEST_GENS})")

    else:
        # Keep only last 50 rejections
        rejected = state.get("rejected", {})
        rejected[strategy_id] = {
            "score": score,
            "rejected_at": datetime.now(timezone.utc).isoformat(),
            "failure_reasons": result["failure_reasons"],
        }
        if len(rejected) > 50:
            oldest = sorted(rejected, key=lambda k: rejected[k].get("rejected_at", ""))[:len(rejected) - 50]
            for k in oldest:
                del rejected[k]
        state["rejected"] = rejected
        state["total_rejected"] = state.get("total_rejected", 0) + 1

    save_gate_state(state)

    # Feed rejections and watchlist back into evolutionary system
    if result["status"] != "APPROVED":
        feed_rejection_back(result, candidate)

    return result


# ─── Watchlist Re-test ──────────────────────────────────────────────────────

def get_watchlist_retests(current_gen: int) -> list[str]:
    """Return strategy IDs that are due for re-testing."""
    state = load_gate_state()
    due = []
    for sid, wdata in state.get("watchlist", {}).items():
        if current_gen >= wdata.get("retest_at_gen", 0):
            due.append(sid)
    return due


def remove_from_watchlist(strategy_id: str):
    """Remove a strategy from watchlist (after re-test or promotion)."""
    state = load_gate_state()
    state.get("watchlist", {}).pop(strategy_id, None)
    save_gate_state(state)


# ─── Discord Alert Formatter ───────────────────────────────────────────────

def format_approval_alert(result: dict) -> str:
    """Format a Discord alert for an approved strategy."""
    checks = result.get("checks", {})
    mc = checks.get("monte_carlo", {})
    wf = checks.get("walk_forward", {})
    prop = checks.get("prop_simulation", {})
    perf = checks.get("performance", {})
    lineage = checks.get("lineage_stability", {})

    return (
        f"🏆 **PRODUCTION READY**\n"
        f"**Strategy:** `{result['strategy_id']}`\n"
        f"**Style:** {result['style']} | **Lineage:** {result.get('lineage_id', 'N/A')}\n"
        f"**Score:** {result['production_score']:.2f}\n"
        f"\n"
        f"**Performance**\n"
        f"Sharpe: {perf.get('sharpe', 0):.2f} | PF: {perf.get('profit_factor', 0):.2f} | "
        f"WR: {perf.get('win_rate', 0):.0%}\n"
        f"Max DD: {checks.get('drawdown', {}).get('max_dd', 0):.1%}\n"
        f"\n"
        f"**Validation**\n"
        f"MC: {'✅' if mc.get('mc_passed') else '❌'} "
        f"(sharpe={mc.get('mc_sharpe_mean', 0):.2f}, dd_p95={mc.get('mc_dd_p95', 0):.1%}, "
        f"consistency={mc.get('mc_consistency', 0):.0%})\n"
        f"WF: {'✅' if wf.get('wf_passed') else '❌'} "
        f"(sharpe={wf.get('wf_sharpe_mean', 0):.2f}, degrad={wf.get('wf_degradation', 0):.2f})\n"
        f"Stability: {'✅' if lineage.get('passed') else '❌'} ({lineage.get('stability', 0):.2f})\n"
        f"Prop: {'✅ PASS' if prop.get('prop_passed') else '❌ FAIL'} "
        f"(profit={prop.get('prop_max_profit_pct', 0):.1%})"
    )


# ─── Status Report ──────────────────────────────────────────────────────────

def status_report() -> str:
    state = load_gate_state()
    approved = state.get("approved", {})
    watchlist = state.get("watchlist", {})

    lines = [
        f"🚪 PRODUCTION GATE | Evaluated: {state.get('total_evaluated', 0)} | "
        f"Approved: {state.get('total_approved', 0)} | "
        f"Watchlist: {len(watchlist)} | "
        f"Rejected: {state.get('total_rejected', 0)}"
    ]

    if approved:
        lines.append("  ✅ Approved:")
        for sid, adata in approved.items():
            lines.append(f"    {sid} [{adata.get('style', '?')}] score={adata.get('score', 0):.2f}")

    if watchlist:
        lines.append("  👀 Watchlist:")
        for sid, wdata in watchlist.items():
            lines.append(
                f"    {sid} score={wdata.get('score', 0):.2f} "
                f"retest@gen{wdata.get('retest_at_gen', '?')}"
            )

    return "\n".join(lines)


def get_approved_strategies() -> list[str]:
    """Return list of approved strategy IDs."""
    state = load_gate_state()
    return list(state.get("approved", {}).keys())


# ─── Failure Feedback ───────────────────────────────────────────────────────

def feed_rejection_back(result: dict, candidate: dict):
    """
    Feed gate rejection reasons back into the evolutionary system.
    
    - Tags near-miss with specific failure reasons (MC, WF, prop, etc.)
    - Updates bias engine to avoid parameter regions that fail specific checks
    - Boosts near-miss priority if close to passing (WATCHLIST)
    """
    if result["status"] == "APPROVED":
        return  # nothing to feed back

    strategy_id = result["strategy_id"]
    failure_reasons = result.get("failure_reasons", [])
    score = result.get("production_score", 0)
    style = candidate.get("style", "unknown")
    params = candidate.get("parameters", {})

    # 1. Tag near-miss with gate failure reasons
    try:
        nm_entry = {
            "strategy_code": strategy_id,
            "style": style,
            "parameters": params,
            "sharpe": candidate.get("sharpe_ratio", candidate.get("sharpe", 0)),
            "dd": candidate.get("max_drawdown", 0),
            "wr": candidate.get("win_rate", 0),
            "trades": candidate.get("trade_count", 0),
            "gate_score": score,
            "gate_status": result["status"],
            "gate_failures": failure_reasons,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # If WATCHLIST, boost priority by marking as gate_near_miss
        if result["status"] == "WATCHLIST":
            nm_entry["gate_near_miss"] = True
            nm_entry["priority_boost"] = 1.5  # 50% higher mutation priority

        NEAR_MISS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(NEAR_MISS_FILE, "a") as f:
            f.write(json.dumps(nm_entry) + "\n")

    except Exception as e:
        log.debug(f"Failed to feed near-miss: {e}")

    # 2. Update bias engine — penalize parameter regions that fail specific checks
    try:
        from services.continuous_backtester_v2 import update_bias
        # Negative fitness signal for gate failures
        # Stronger penalty for stage 1 fails, lighter for stage 3
        if "STAGE 1" in str(failure_reasons):
            penalty_fitness = -0.2
        elif "STAGE 2" in str(failure_reasons):
            penalty_fitness = -0.1
        else:
            penalty_fitness = -0.05  # stage 3 fail = almost good, light penalty
        update_bias(style, params, penalty_fitness)
    except Exception as e:
        log.debug(f"Failed to update bias: {e}")

    _log_gate_event("FEEDBACK", {
        "strategy_id": strategy_id,
        "score": score,
        "status": result["status"],
        "failure_count": len(failure_reasons),
        "fed_to": ["near_miss", "bias_engine"],
    })

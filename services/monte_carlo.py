"""
Monte Carlo Shuffle Test — Light + Full

Shuffle trade order randomly N times, compute equity curve and max drawdown
for each permutation. Tests whether the strategy's performance is robust
to trade ordering or if it relies on a lucky sequence.

Two modes:
- Light MC: 100 sims, 65% survival, no DD constraint (cheap early filter)
- Full MC:  1000 sims, 85% survival, p95 DD < 25% (definitive test)
"""

from __future__ import annotations
from typing import List

import numpy as np

from services.darwin.backtester import TradeRecord


def _run_mc_core(
    pnls: np.ndarray,
    n_simulations: int,
    initial_capital: float,
    risk_frac: float,
    seed: int = 42,
) -> dict:
    """Core MC engine — returns raw stats without pass/fail logic."""
    rng = np.random.default_rng(seed)
    max_drawdowns = np.zeros(n_simulations)
    final_equities = np.zeros(n_simulations)

    for sim in range(n_simulations):
        shuffled = rng.permutation(pnls)
        equity = initial_capital
        peak = initial_capital
        worst_dd = 0.0

        for pnl in shuffled:
            equity += equity * risk_frac * pnl
            equity = max(equity, 0.01)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0
            if dd > worst_dd:
                worst_dd = dd

        max_drawdowns[sim] = worst_dd
        final_equities[sim] = equity

    profitable_sims = int(np.sum(final_equities > initial_capital))
    survival_rate = profitable_sims / n_simulations

    return {
        "median_dd": float(np.median(max_drawdowns)),
        "p95_dd": float(np.percentile(max_drawdowns, 95)),
        "p99_dd": float(np.percentile(max_drawdowns, 99)),
        "survival_rate": survival_rate,
        "n_simulations": n_simulations,
        "median_final_equity": float(np.median(final_equities)),
        "p5_final_equity": float(np.percentile(final_equities, 5)),
    }


def monte_carlo_light(
    trades: List[TradeRecord],
    n_simulations: int = 100,
    initial_capital: float = 100_000,
    risk_per_trade_pct: float = 1.0,
) -> dict:
    """
    Light Monte Carlo — cheap early filter.
    100 sims, survival threshold 65%, no DD constraint.
    """
    if len(trades) < 10:
        return {
            "passed": False,
            "conditional": False,
            "survival_rate": 0.0,
            "failure_tag": "FAIL_MC_FRAGILITY",
            "reason": f"Too few trades ({len(trades)})",
        }

    pnls = np.array([t.pnl_pct for t in trades])
    risk_frac = risk_per_trade_pct / 100.0
    stats = _run_mc_core(pnls, n_simulations, initial_capital, risk_frac, seed=42)

    survival = stats["survival_rate"]

    # Light MC: pass at 65%, conditional 50-65%, hard fail below 50%
    if survival >= 0.65:
        passed = True
        conditional = False
        failure_tag = None
    elif survival >= 0.50:
        passed = False
        conditional = True
        failure_tag = None
    else:
        passed = False
        conditional = False
        failure_tag = "FAIL_MC_FRAGILITY"

    return {
        **{k: round(v, 4) if isinstance(v, float) else v for k, v in stats.items()},
        "passed": passed,
        "conditional": conditional,
        "failure_tag": failure_tag,
        "mode": "light",
    }


def monte_carlo_test(
    trades: List[TradeRecord],
    n_simulations: int = 1000,
    initial_capital: float = 100_000,
    risk_per_trade_pct: float = 1.0,
) -> dict:
    """
    Full Monte Carlo — definitive fragility test.
    1000 sims, survival > 85%, p95 DD < 25%.

    Conditional: survival 70-85% or p95_dd 25-35%.
    Hard fail: survival < 70% or p95_dd > 35%.
    """
    if len(trades) < 10:
        return {
            "passed": False,
            "conditional": False,
            "survival_rate": 0.0,
            "median_dd": 1.0,
            "p95_dd": 1.0,
            "p99_dd": 1.0,
            "failure_tag": "FAIL_MC_FRAGILITY",
            "reason": f"Too few trades ({len(trades)})",
        }

    pnls = np.array([t.pnl_pct for t in trades])
    risk_frac = risk_per_trade_pct / 100.0
    stats = _run_mc_core(pnls, n_simulations, initial_capital, risk_frac, seed=42)

    survival = stats["survival_rate"]
    p95_dd = stats["p95_dd"]

    # Full MC thresholds
    survival_pass = survival >= 0.85
    dd_pass = p95_dd < 0.25

    survival_conditional = survival >= 0.70
    dd_conditional = p95_dd < 0.35

    if survival_pass and dd_pass:
        passed = True
        conditional = False
        failure_tag = None
    elif survival_conditional and dd_conditional:
        passed = False
        conditional = True
        failure_tag = None
    else:
        passed = False
        conditional = False
        failure_tag = "FAIL_MC_FRAGILITY"

    return {
        **{k: round(v, 4) if isinstance(v, float) else v for k, v in stats.items()},
        "passed": passed,
        "conditional": conditional,
        "failure_tag": failure_tag,
        "mode": "full",
    }

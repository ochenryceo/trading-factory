"""
Trust Score — Composite quality signal for passed strategies.

NOT a leaderboard. A quality signal for:
- Mutation priority (higher trust = more offspring)
- Resource allocation (which DNAs deserve more compute)

Score range: 0.0 to 1.0
"""

from __future__ import annotations
from typing import Dict, Optional


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

    Components:
    - stability_score: walk-forward + monte carlo health
    - distribution_score: PnL spread quality (inverse Gini)
    - simplicity_score: fewer indicators = higher trust
    - failure_penalty: deductions for near-misses

    Parameters
    ----------
    robustness_result : dict
        From robustness_check() — needs 'return_ratio'
    walk_forward_result : dict
        From walk_forward_test() — needs 'degradation'
    monte_carlo_result : dict
        From monte_carlo_test() — needs 'survival_rate', 'p95_dd'
    distribution_result : dict
        From check_trade_distribution() — needs 'gini'
    complexity_count : int
        Number of entry conditions (from count_entry_conditions)
    forced_exit_ratio : float
        Fraction of trades that hit max hold period

    Returns
    -------
    float: trust score 0.0 to 1.0
    """
    # ── Stability (0-1): how well it holds up under stress ──
    wf_degradation = walk_forward_result.get("degradation", 1.0)
    wf_score = max(0.0, 1.0 - abs(wf_degradation))

    mc_survival = monte_carlo_result.get("survival_rate", 0.0)
    mc_dd = monte_carlo_result.get("p95_dd", 1.0)
    mc_score = mc_survival * (1.0 - mc_dd)

    stability_score = wf_score * 0.5 + mc_score * 0.5

    # ── Distribution (0-1): PnL spread quality ──
    gini = distribution_result.get("gini", 0.5)
    distribution_score = max(0.0, 1.0 - gini)

    # ── Simplicity (0-1): fewer conditions = higher trust ──
    # 1 indicator = 1.0, 2 = 0.8, 3 = 0.6
    simplicity_score = max(0.3, 1.0 - (complexity_count - 1) * 0.2)

    # ── Failure penalty (0-1): deductions for near-misses ──
    penalty = 0.0
    if forced_exit_ratio > 0.1:
        penalty += 0.1
    stripped_ratio = robustness_result.get("return_ratio", 1.0)
    if stripped_ratio < 0.5:
        penalty += 0.1  # heavily dependent on top trades even if passed

    # ── Composite ──
    trust = stability_score * distribution_score * simplicity_score * (1.0 - penalty)
    return round(max(0.0, min(1.0, trust)), 3)

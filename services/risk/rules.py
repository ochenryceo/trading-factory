"""Kill switch rules — strategy-level and system-level."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class KillRule:
    """A single kill condition."""
    name: str
    description: str
    field: str
    operator: str  # ">" | "<" | ">="  | "<="
    threshold: float


# --------------------------------------------------------------------------- #
# Strategy-level kill switches                                                #
# --------------------------------------------------------------------------- #

STRATEGY_KILL_RULES: list[KillRule] = [
    KillRule(
        name="max_drawdown",
        description="Drawdown exceeds 5%",
        field="drawdown",
        operator=">",
        threshold=0.05,
    ),
    KillRule(
        name="consecutive_losses",
        description="5 or more consecutive losses",
        field="consecutive_losses",
        operator=">=",
        threshold=5,
    ),
    KillRule(
        name="low_win_rate_30d",
        description="30-day win rate below 35%",
        field="win_rate",
        operator="<",
        threshold=0.35,
    ),
    KillRule(
        name="low_sharpe",
        description="Sharpe ratio below 0.5",
        field="sharpe",
        operator="<",
        threshold=0.5,
    ),
]


# --------------------------------------------------------------------------- #
# System-level kill switches                                                  #
# --------------------------------------------------------------------------- #

SYSTEM_KILL_RULES: list[KillRule] = [
    KillRule(
        name="daily_loss_limit",
        description="Daily portfolio loss exceeds 3%",
        field="daily_loss",
        operator=">",
        threshold=0.03,
    ),
    KillRule(
        name="total_drawdown_limit",
        description="Total portfolio drawdown exceeds 10%",
        field="total_drawdown",
        operator=">",
        threshold=0.10,
    ),
    KillRule(
        name="correlation_breach",
        description="Too many correlated positions open",
        field="correlated_positions",
        operator=">",
        threshold=3,
    ),
    KillRule(
        name="stale_data_feed",
        description="Data feed stale for more than 60 seconds",
        field="data_staleness_seconds",
        operator=">",
        threshold=60,
    ),
]


def evaluate_rule(rule: KillRule, value: float) -> bool:
    """Return True if the kill condition is TRIGGERED (bad)."""
    ops = {
        ">": lambda v, t: v > t,
        "<": lambda v, t: v < t,
        ">=": lambda v, t: v >= t,
        "<=": lambda v, t: v <= t,
    }
    op_fn = ops.get(rule.operator)
    if op_fn is None:
        raise ValueError(f"Unknown operator: {rule.operator}")
    return op_fn(value, rule.threshold)


def check_strategy_kill(metrics: dict[str, Any]) -> list[KillRule]:
    """Return list of triggered strategy-level kill rules."""
    triggered: list[KillRule] = []
    for rule in STRATEGY_KILL_RULES:
        val = metrics.get(rule.field)
        if val is not None and evaluate_rule(rule, float(val)):
            triggered.append(rule)
    return triggered


def check_system_kill(state: dict[str, Any]) -> list[KillRule]:
    """Return list of triggered system-level kill rules."""
    triggered: list[KillRule] = []
    for rule in SYSTEM_KILL_RULES:
        val = state.get(rule.field)
        if val is not None and evaluate_rule(rule, float(val)):
            triggered.append(rule)
    return triggered

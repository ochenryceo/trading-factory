"""
Darwin Dependency Test — Component fragility analysis.

For each filter/indicator in the strategy, remove it and re-run backtest.
If removing any single component causes >50% performance drop → flag as fragile.
Returns list of critical dependencies.
"""

from __future__ import annotations
import copy
from dataclasses import dataclass, field, asdict
from typing import Dict, List

import numpy as np
import pandas as pd

from .backtester import BacktestResult, run_backtest


@dataclass
class ComponentDependency:
    component: str
    component_type: str  # "filter" or "parameter"
    baseline_pnl: float = 0.0
    degraded_pnl: float = 0.0
    pnl_change_pct: float = 0.0
    is_critical: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DependencyResult:
    strategy_code: str
    is_fragile: bool = False
    critical_dependencies: List[str] = field(default_factory=list)
    components: List[ComponentDependency] = field(default_factory=list)
    baseline: BacktestResult = field(default_factory=lambda: BacktestResult(strategy_code=""))

    def to_dict(self) -> dict:
        return {
            "strategy_code": self.strategy_code,
            "is_fragile": self.is_fragile,
            "critical_dependencies": self.critical_dependencies,
            "components": [c.to_dict() for c in self.components],
            "baseline": self.baseline.to_dict(),
        }


def run_dependency_test(
    dna: dict,
    df: pd.DataFrame,
    *,
    critical_threshold_pct: float = 50.0,
) -> DependencyResult:
    """
    Test each filter and key parameter for dependency.

    Process:
    1. Run baseline backtest
    2. For each filter: remove it and re-run
    3. For each numeric parameter: set to neutral/zero and re-run
    4. If any removal causes >threshold% PnL drop → critical dependency
    """
    code = dna.get("strategy_code", "UNKNOWN")

    # Baseline
    baseline = run_backtest(dna, df)
    baseline_pnl = baseline.total_pnl if baseline.total_pnl != 0 else 0.0001

    components: List[ComponentDependency] = []
    critical: List[str] = []

    # --- Test filter removal ---
    filters = dna.get("filters", [])
    for i, filt in enumerate(filters):
        modified = copy.deepcopy(dna)
        modified["filters"] = [f for j, f in enumerate(filters) if j != i]

        # Filters are textual — they influence signal gen indirectly via
        # parameter_ranges.  We simulate filter removal by relaxing the
        # corresponding parameter thresholds.
        _relax_filter_params(modified, filt)

        result = run_backtest(modified, df)
        pnl_change = _pnl_change_pct(baseline_pnl, result.total_pnl)
        is_crit = pnl_change < -critical_threshold_pct

        comp = ComponentDependency(
            component=filt[:80],
            component_type="filter",
            baseline_pnl=baseline.total_pnl,
            degraded_pnl=result.total_pnl,
            pnl_change_pct=round(pnl_change, 2),
            is_critical=is_crit,
        )
        components.append(comp)
        if is_crit:
            critical.append(filt[:80])

    # --- Test parameter removal ---
    params = dna.get("parameter_ranges", {})
    for key, val in params.items():
        if not isinstance(val, (list, tuple)):
            continue
        try:
            float(val[0])
        except (ValueError, TypeError):
            continue

        modified = copy.deepcopy(dna)
        # "Remove" by widening range dramatically (makes filter useless)
        modified["parameter_ranges"][key] = [0, 0]

        result = run_backtest(modified, df)
        pnl_change = _pnl_change_pct(baseline_pnl, result.total_pnl)
        is_crit = pnl_change < -critical_threshold_pct

        comp = ComponentDependency(
            component=key,
            component_type="parameter",
            baseline_pnl=baseline.total_pnl,
            degraded_pnl=result.total_pnl,
            pnl_change_pct=round(pnl_change, 2),
            is_critical=is_crit,
        )
        components.append(comp)
        if is_crit:
            critical.append(key)

    is_fragile = len(critical) > 0

    return DependencyResult(
        strategy_code=code,
        is_fragile=is_fragile,
        critical_dependencies=critical,
        components=components,
        baseline=baseline,
    )


def _pnl_change_pct(baseline: float, degraded: float) -> float:
    if abs(baseline) < 1e-10:
        return 0.0
    return ((degraded - baseline) / abs(baseline)) * 100


def _relax_filter_params(dna: dict, filter_text: str):
    """
    Attempt to relax parameter_ranges that correspond to a removed filter.
    This is heuristic — we look for keyword matches.
    """
    params = dna.get("parameter_ranges", {})
    filter_lower = filter_text.lower()

    # ADX filters
    if "adx" in filter_lower:
        for key in ("adx_threshold", "adx_min", "adx_max"):
            if key in params:
                params[key] = [0, 100]

    # Volume filters
    if "volume" in filter_lower:
        for key in ("volume_multiplier", "volume_breakout_multiplier", "volume_ignition_multiplier"):
            if key in params:
                params[key] = [0, 0.1]  # essentially no volume filter

    # RSI filters
    if "rsi" in filter_lower:
        for key in ("rsi_threshold", "rsi_extreme", "rsi2_threshold", "rsi_max", "rsi_pullback_zone"):
            if key in params:
                params[key] = [0, 100]

    dna["parameter_ranges"] = params

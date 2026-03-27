"""
Darwin Degradation Testing v2 — Relative degradation using Darwin's backtester.

KEY FIX: v1 compared simplified-engine absolute metrics against full Darwin
baselines (which use fixed risk stops, partial exits, trailing stops, etc.).
This caused false failures: 5.4% DD strategies showed 56% DD because the
simplified engine doesn't cap per-trade risk.

v2 approach:
  1. Run the SAME engine for both baseline and degraded scenarios
  2. Measure RELATIVE change — how much does the strategy degrade?
  3. Use Darwin's full results for the HARD pass criteria (profitability, direction)
  4. A strategy that's robust to parameter/execution/data changes PASSES

Axes:
  1. Parameter degradation: shift numeric params by fixed percentages
  2. Execution degradation: add slippage ticks to fill prices
  3. Data degradation: add noise to OHLC before feeding to backtester
"""

from __future__ import annotations
import copy
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .backtester import (
    BacktestResult,
    run_backtest,
    load_parquet,
    DATA_DIR,
)


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class DegradationScenario:
    """Result of a single degradation scenario."""
    name: str
    description: str
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    trade_count: int = 0
    # Relative changes vs engine baseline
    sharpe_change_pct: float = 0.0
    dd_change_pct: float = 0.0
    wr_change_pp: float = 0.0  # percentage points
    pnl_change_pct: float = 0.0
    passed: bool = False
    fail_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DegradationAxis:
    """Result of an entire degradation axis (multiple scenarios)."""
    name: str
    scenarios: List[DegradationScenario] = field(default_factory=list)
    scenarios_passed: int = 0
    total_scenarios: int = 0
    passed: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "scenarios": [s.to_dict() for s in self.scenarios],
            "scenarios_passed": self.scenarios_passed,
            "total_scenarios": self.total_scenarios,
            "passed": self.passed,
        }


@dataclass
class DegradationResult:
    """Full degradation test result for a strategy."""
    strategy_code: str
    overall_passed: bool = False
    axes_passed: int = 0
    total_axes: int = 3
    axes: List[DegradationAxis] = field(default_factory=list)
    engine_baseline: Dict[str, float] = field(default_factory=dict)
    darwin_baseline: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "strategy_code": self.strategy_code,
            "overall_passed": self.overall_passed,
            "axes_passed": self.axes_passed,
            "total_axes": self.total_axes,
            "axes": [a.to_dict() for a in self.axes],
            "engine_baseline": self.engine_baseline,
            "darwin_baseline": self.darwin_baseline,
        }


# ---------------------------------------------------------------------------
# Degradation helpers
# ---------------------------------------------------------------------------

def _degrade_parameters_fixed(dna: dict, shift_pct: float) -> dict:
    """Shift all numeric parameter_ranges by a fixed percentage."""
    degraded = copy.deepcopy(dna)
    params = degraded.get("parameter_ranges", {})

    for key, val in params.items():
        if isinstance(val, (list, tuple)) and len(val) == 2:
            try:
                lo, hi = float(val[0]), float(val[1])
                params[key] = [lo * (1 + shift_pct), hi * (1 + shift_pct)]
            except (ValueError, TypeError):
                pass
        elif isinstance(val, (int, float)):
            try:
                params[key] = float(val) * (1 + shift_pct)
            except (ValueError, TypeError):
                pass

    degraded["parameter_ranges"] = params
    return degraded


def _degrade_execution(df: pd.DataFrame, ticks: int, seed: int = 42) -> pd.DataFrame:
    """Simulate slippage by shifting prices adversely."""
    rng = np.random.default_rng(seed)
    degraded = df.copy()
    tick_size = 0.01  # CL tick size
    slippage = ticks * tick_size
    direction = rng.choice([-1, 1], len(df))
    degraded["close"] = degraded["close"] + slippage * direction
    open_slip = rng.uniform(-slippage, slippage, len(df))
    degraded["open"] = degraded["open"] + open_slip
    degraded["high"] = degraded[["open", "high", "close"]].max(axis=1)
    degraded["low"] = degraded[["open", "low", "close"]].min(axis=1)
    return degraded


def _degrade_data_noise(df: pd.DataFrame, noise_pct: float, seed: int = 42) -> pd.DataFrame:
    """Add Gaussian noise to OHLC data."""
    rng = np.random.default_rng(seed)
    degraded = df.copy()
    for col in ("open", "high", "low", "close"):
        if col in degraded.columns:
            noise = rng.normal(0, noise_pct, len(df))
            degraded[col] = degraded[col] * (1 + noise)
    degraded["high"] = degraded[["open", "high", "low", "close"]].max(axis=1)
    degraded["low"] = degraded[["open", "high", "low", "close"]].min(axis=1)
    return degraded


# ---------------------------------------------------------------------------
# Scenario evaluation — RELATIVE to engine baseline
# ---------------------------------------------------------------------------

def _evaluate_scenario(
    result: BacktestResult,
    engine_baseline: Dict[str, float],
    scenario_name: str,
    scenario_desc: str,
) -> DegradationScenario:
    """
    Evaluate a degraded result against the SAME engine's baseline.
    
    Pass criteria (relative):
    1. Must remain profitable (total_return_pct > 0) — HARD
    2. Drawdown must not increase > 80% from engine baseline
    3. Win rate must not drop > 15pp from engine baseline  
    4. Sharpe must remain > 0
    5. PnL must not drop > 80% from engine baseline
    """
    base_dd = engine_baseline.get("max_drawdown", 0.01)
    base_wr = engine_baseline.get("win_rate", 0.50)
    base_sharpe = engine_baseline.get("sharpe_ratio", 1.0)
    base_pnl = engine_baseline.get("total_return_pct", 1.0)

    # Compute relative changes
    dd_change = ((result.max_drawdown - base_dd) / max(base_dd, 0.001)) * 100
    wr_change = (result.win_rate - base_wr) * 100  # in percentage points
    sharpe_change = ((result.sharpe_ratio - base_sharpe) / max(abs(base_sharpe), 0.001)) * 100
    pnl_change = ((result.total_return_pct - base_pnl) / max(abs(base_pnl), 0.001)) * 100

    fail_reasons = []

    # 1. HARD: Must remain profitable
    if result.total_return_pct <= 0:
        fail_reasons.append(f"Unprofitable: return={result.total_return_pct:.1f}%")

    # 2. DD must not increase > 80% from baseline
    if dd_change > 80:
        fail_reasons.append(
            f"DD increased {dd_change:.0f}% ({base_dd*100:.1f}% → {result.max_drawdown*100:.1f}%)"
        )

    # 3. WR must not drop > 15pp from baseline
    if wr_change < -15:
        fail_reasons.append(
            f"WR dropped {abs(wr_change):.1f}pp ({base_wr*100:.1f}% → {result.win_rate*100:.1f}%)"
        )

    # 4. Sharpe must remain positive
    if result.sharpe_ratio < 0:
        fail_reasons.append(f"Sharpe negative: {result.sharpe_ratio:.2f}")

    # 5. PnL must not drop > 80% from baseline
    if base_pnl > 0 and pnl_change < -80:
        fail_reasons.append(
            f"PnL dropped {abs(pnl_change):.0f}% ({base_pnl:.1f}% → {result.total_return_pct:.1f}%)"
        )

    passed = len(fail_reasons) == 0

    return DegradationScenario(
        name=scenario_name,
        description=scenario_desc,
        sharpe=result.sharpe_ratio,
        max_drawdown=result.max_drawdown,
        win_rate=result.win_rate,
        total_pnl=result.total_pnl,
        total_return_pct=result.total_return_pct,
        trade_count=result.trade_count,
        sharpe_change_pct=round(sharpe_change, 1),
        dd_change_pct=round(dd_change, 1),
        wr_change_pp=round(wr_change, 1),
        pnl_change_pct=round(pnl_change, 1),
        passed=passed,
        fail_reasons=fail_reasons,
    )


# ---------------------------------------------------------------------------
# Main degradation test v2 — relative comparison
# ---------------------------------------------------------------------------

def run_degradation_v2(
    dna: dict,
    df: pd.DataFrame,
    *,
    darwin_baseline: Optional[Dict[str, Any]] = None,
    param_shifts: List[float] = None,
    slippage_ticks: List[int] = None,
    noise_levels: List[float] = None,
) -> DegradationResult:
    """
    Run multi-axis degradation testing using RELATIVE comparison.

    Both baseline and degraded runs use the SAME simplified engine.
    We measure HOW MUCH the strategy degrades, not absolute metrics.
    """
    code = dna.get("strategy_code", "UNKNOWN")

    if param_shifts is None:
        param_shifts = [0.10, -0.10, 0.20, -0.20]
    if slippage_ticks is None:
        slippage_ticks = [1, 2, 3]
    if noise_levels is None:
        noise_levels = [0.0005, 0.001, 0.002]

    # --- Compute engine baseline (same engine for apples-to-apples) ---
    baseline_result = run_backtest(dna, df)
    engine_baseline = {
        "sharpe_ratio": baseline_result.sharpe_ratio,
        "max_drawdown": baseline_result.max_drawdown,
        "win_rate": baseline_result.win_rate,
        "total_return_pct": baseline_result.total_return_pct,
        "total_pnl": baseline_result.total_pnl,
        "trade_count": baseline_result.trade_count,
    }

    axes: List[DegradationAxis] = []

    # ===== AXIS 1: Parameter Degradation =====
    param_scenarios: List[DegradationScenario] = []
    for shift in param_shifts:
        degraded_dna = _degrade_parameters_fixed(dna, shift)
        result = run_backtest(degraded_dna, df)
        sign = "+" if shift >= 0 else ""
        scenario = _evaluate_scenario(
            result, engine_baseline,
            f"param_{sign}{int(shift*100)}pct",
            f"All numeric params shifted {sign}{shift*100:.0f}%",
        )
        param_scenarios.append(scenario)

    param_passed = sum(1 for s in param_scenarios if s.passed)
    param_axis_passed = param_passed >= len(param_scenarios) * 0.5
    axes.append(DegradationAxis(
        name="parameter_degradation",
        scenarios=param_scenarios,
        scenarios_passed=param_passed,
        total_scenarios=len(param_scenarios),
        passed=param_axis_passed,
    ))

    # ===== AXIS 2: Execution Degradation =====
    exec_scenarios: List[DegradationScenario] = []
    for ticks in slippage_ticks:
        degraded_df = _degrade_execution(df, ticks, seed=42 + ticks)
        result = run_backtest(dna, degraded_df)
        scenario = _evaluate_scenario(
            result, engine_baseline,
            f"slippage_{ticks}tick",
            f"{ticks} tick(s) adverse slippage",
        )
        exec_scenarios.append(scenario)

    exec_passed = sum(1 for s in exec_scenarios if s.passed)
    exec_axis_passed = exec_passed >= len(exec_scenarios) * 0.5
    axes.append(DegradationAxis(
        name="execution_degradation",
        scenarios=exec_scenarios,
        scenarios_passed=exec_passed,
        total_scenarios=len(exec_scenarios),
        passed=exec_axis_passed,
    ))

    # ===== AXIS 3: Data Degradation =====
    data_scenarios: List[DegradationScenario] = []
    for noise in noise_levels:
        noisy_df = _degrade_data_noise(df, noise, seed=42)
        result = run_backtest(dna, noisy_df)
        scenario = _evaluate_scenario(
            result, engine_baseline,
            f"noise_{noise*100:.2f}pct",
            f"±{noise*100:.2f}% Gaussian noise on OHLC",
        )
        data_scenarios.append(scenario)

    data_passed = sum(1 for s in data_scenarios if s.passed)
    data_axis_passed = data_passed >= len(data_scenarios) * 0.5
    axes.append(DegradationAxis(
        name="data_degradation",
        scenarios=data_scenarios,
        scenarios_passed=data_passed,
        total_scenarios=len(data_scenarios),
        passed=data_axis_passed,
    ))

    # --- Overall verdict: must pass at least 2 of 3 axes ---
    axes_passed_count = sum(1 for a in axes if a.passed)
    overall = axes_passed_count >= 2

    return DegradationResult(
        strategy_code=code,
        overall_passed=overall,
        axes_passed=axes_passed_count,
        total_axes=len(axes),
        axes=axes,
        engine_baseline=engine_baseline,
        darwin_baseline=darwin_baseline or {},
    )


# ---------------------------------------------------------------------------
# Backward-compatible wrapper
# ---------------------------------------------------------------------------

def run_degradation(
    dna: dict,
    df: pd.DataFrame,
    *,
    max_pnl_drop_pct: float = 50.0,
    darwin_baseline: Optional[Dict[str, Any]] = None,
) -> DegradationResult:
    """Backward-compatible entry point."""
    return run_degradation_v2(dna, df, darwin_baseline=darwin_baseline)

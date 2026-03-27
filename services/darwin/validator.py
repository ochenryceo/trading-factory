"""
Darwin Validator — Regime testing.

Splits market data into trending / ranging / volatile periods,
runs backtests on each regime independently.
Strategy must be profitable in at least 2 of 3 regimes to pass.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, List

import numpy as np
import pandas as pd

from .backtester import (
    BacktestResult,
    run_backtest,
    adx,
    atr,
    generate_synthetic_ohlcv,
)


# ---------------------------------------------------------------------------
# Regime detection
# ---------------------------------------------------------------------------

@dataclass
class RegimeResult:
    regime: str
    result: BacktestResult
    n_bars: int = 0
    passed: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class ValidationResult:
    strategy_code: str
    overall_passed: bool = False
    regimes_passed: int = 0
    regime_results: List[RegimeResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy_code": self.strategy_code,
            "overall_passed": self.overall_passed,
            "regimes_passed": self.regimes_passed,
            "regime_results": [r.to_dict() for r in self.regime_results],
        }


def classify_regimes(df: pd.DataFrame, window: int = 50) -> pd.Series:
    """
    Classify each bar into a regime: 'trending', 'ranging', or 'volatile'.

    Uses ADX for trend strength and ATR percentile for volatility.
    """
    _adx = adx(df["high"], df["low"], df["close"], 14)
    _atr = atr(df["high"], df["low"], df["close"], 14)
    atr_pctile = _atr.rolling(window).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
    )

    regime = pd.Series("ranging", index=df.index)
    regime[_adx > 25] = "trending"
    regime[(atr_pctile > 0.75) & (_adx <= 25)] = "volatile"

    return regime


def split_by_regime(df: pd.DataFrame, min_bars: int = 100) -> Dict[str, pd.DataFrame]:
    """Split DataFrame into regime-specific subsets."""
    regimes = classify_regimes(df)
    result = {}

    for regime_name in ("trending", "ranging", "volatile"):
        mask = regimes == regime_name
        subset = df[mask].copy()
        if len(subset) >= min_bars:
            result[regime_name] = subset
        else:
            # If not enough bars, generate synthetic data for that regime
            result[regime_name] = generate_synthetic_ohlcv(
                n_bars=500, regime=regime_name, seed=hash(regime_name) % 2**31
            )

    return result


# ---------------------------------------------------------------------------
# Validation runner
# ---------------------------------------------------------------------------

def validate_strategy(
    dna: dict,
    df: pd.DataFrame,
    *,
    min_bars: int = 100,
) -> ValidationResult:
    """
    Run regime-based validation on a strategy DNA.

    Strategy must be profitable in at least 2 of 3 regimes to pass.
    """
    code = dna.get("strategy_code", "UNKNOWN")
    regime_dfs = split_by_regime(df, min_bars=min_bars)

    regime_results: List[RegimeResult] = []
    passed_count = 0

    for regime_name, regime_df in regime_dfs.items():
        bt_result = run_backtest(dna, regime_df)
        is_profitable = bt_result.total_pnl > 0 and bt_result.trade_count >= 5
        if is_profitable:
            passed_count += 1

        regime_results.append(RegimeResult(
            regime=regime_name,
            result=bt_result,
            n_bars=len(regime_df),
            passed=is_profitable,
        ))

    overall = passed_count >= 2

    return ValidationResult(
        strategy_code=code,
        overall_passed=overall,
        regimes_passed=passed_count,
        regime_results=regime_results,
    )

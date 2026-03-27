"""
Walk-Forward Test — Step 4

Anchored walk-forward validation for non-ML strategies.
Splits data chronologically, runs backtest on each segment with same DNA params,
then compares in-sample (first 60%) vs out-of-sample (last 40%) performance.

A strategy with a real edge should perform similarly OOS vs IS.
Large degradation = curve-fit.
"""

from __future__ import annotations
import sys
from pathlib import Path
from typing import Dict, Any

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from services.darwin.backtester import load_parquet, run_backtest


def walk_forward_test(
    dna: dict,
    asset: str,
    timeframe: str,
    n_splits: int = 5,
    initial_capital: float = 100_000,
    df_cached=None,
) -> dict:
    """
    Anchored walk-forward test.

    Split data into n_splits chronological segments. Run backtest on each.
    Compare in-sample (first 60% of splits) vs out-of-sample (last 40%).

    Parameters
    ----------
    dna : dict
        Strategy DNA.
    asset : str
        Asset symbol (NQ, GC, CL).
    timeframe : str
        Timeframe string (5m, 15m, 1h, 4h, daily).
    n_splits : int
        Number of chronological segments.
    initial_capital : float
        Starting capital for each segment backtest.

    Returns
    -------
    dict with oos_sharpe, oos_return, is_sharpe, degradation, passed
    """
    try:
        df = df_cached if df_cached is not None else load_parquet(asset, timeframe)
    except FileNotFoundError:
        return {
            "oos_sharpe": 0.0,
            "oos_return": 0.0,
            "is_sharpe": 0.0,
            "degradation": 1.0,
            "passed": False,
            "conditional": False,
            "failure_tag": "FAIL_WF_INSTABILITY",
            "reason": f"No data for {asset}/{timeframe}",
        }

    n_bars = len(df)
    if n_bars < n_splits * 60:
        return {
            "oos_sharpe": 0.0,
            "oos_return": 0.0,
            "is_sharpe": 0.0,
            "degradation": 1.0,
            "passed": False,
            "conditional": False,
            "failure_tag": "FAIL_WF_INSTABILITY",
            "reason": f"Insufficient data ({n_bars} bars) for {n_splits}-split walk-forward",
        }

    # Split into n_splits equal chunks
    split_size = n_bars // n_splits
    split_results = []

    for s in range(n_splits):
        start = s * split_size
        end = (s + 1) * split_size if s < n_splits - 1 else n_bars
        chunk = df.iloc[start:end]

        if len(chunk) < 60:
            continue

        result = run_backtest(
            dna, chunk,
            initial_capital=initial_capital,
            use_mtf=False,
            asset=asset,
        )
        split_results.append({
            "split": s,
            "sharpe": result.sharpe_ratio,
            "return_pct": result.total_return_pct,
            "trades": result.trade_count,
            "win_rate": result.win_rate,
        })

    if len(split_results) < n_splits:
        return {
            "oos_sharpe": 0.0,
            "oos_return": 0.0,
            "is_sharpe": 0.0,
            "degradation": 1.0,
            "passed": False,
            "conditional": False,
            "failure_tag": "FAIL_WF_INSTABILITY",
            "reason": f"Only {len(split_results)}/{n_splits} splits had enough data",
        }

    # In-sample = first 60% of splits, OOS = last 40%
    is_count = max(1, int(n_splits * 0.6))
    oos_count = n_splits - is_count

    is_splits = split_results[:is_count]
    oos_splits = split_results[is_count:]

    is_sharpe = np.mean([s["sharpe"] for s in is_splits])
    is_return = np.mean([s["return_pct"] for s in is_splits])
    oos_sharpe = np.mean([s["sharpe"] for s in oos_splits])
    oos_return = np.mean([s["return_pct"] for s in oos_splits])

    # Degradation: how much worse is OOS vs IS
    if abs(is_sharpe) > 0.001:
        degradation = (is_sharpe - oos_sharpe) / abs(is_sharpe)
    else:
        degradation = 1.0 if oos_sharpe <= 0 else 0.0

    # Pass: OOS Sharpe > 0.3 AND OOS profitable
    # Conditional: OOS Sharpe 0.15-0.3 AND OOS profitable
    # Hard fail: OOS Sharpe < 0.15 or OOS not profitable
    if oos_sharpe > 0.3 and oos_return > 0:
        passed = True
        conditional = False
        failure_tag = None
    elif oos_sharpe > 0.15 and oos_return > 0:
        passed = False
        conditional = True
        failure_tag = None
    else:
        passed = False
        conditional = False
        failure_tag = "FAIL_WF_INSTABILITY"

    return {
        "oos_sharpe": round(float(oos_sharpe), 4),
        "oos_return": round(float(oos_return), 4),
        "is_sharpe": round(float(is_sharpe), 4),
        "is_return": round(float(is_return), 4),
        "degradation": round(float(degradation), 4),
        "passed": passed,
        "conditional": conditional,
        "failure_tag": failure_tag,
        "n_splits": n_splits,
        "is_splits": is_count,
        "oos_splits": oos_count,
        "split_details": split_results,
    }

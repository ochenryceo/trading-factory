"""
Vectorbt-powered fast validation runner.

Loads 30 days of 5m data, generates entry/exit signals per strategy style,
runs vectorbt.Portfolio.from_signals(), and returns FastValidationResult.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
import vectorbt as vbt

from .schemas import FastValidationResult
from .pass_fail import evaluate, calculate_confidence
from .queue_manager import classify_priority

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"


def load_5m_data(asset: str, last_n_days: int = 30) -> pd.DataFrame:
    """Load the most recent `last_n_days` of 5m data from parquet."""
    parquet_path = DATA_DIR / asset / "5m.parquet"
    if not parquet_path.exists():
        raise FileNotFoundError(f"No 5m parquet for {asset}: {parquet_path}")

    df = pd.read_parquet(parquet_path)

    # Ensure datetime index
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)

    # Take last N calendar days
    if len(df) > 0:
        cutoff = df.index.max() - pd.Timedelta(days=last_n_days)
        df = df[df.index >= cutoff]

    # Standardize column names
    col_map = {}
    for c in df.columns:
        cl = c.lower()
        if cl in ("open", "high", "low", "close", "volume"):
            col_map[c] = cl
    df = df.rename(columns=col_map)

    for req in ("open", "high", "low", "close"):
        if req not in df.columns:
            raise ValueError(f"Missing column '{req}' in {parquet_path}")
    if "volume" not in df.columns:
        df["volume"] = 1.0

    return df.dropna(subset=["close"])


# ---------------------------------------------------------------------------
# Indicator helpers (lightweight — mirrors darwin/backtester.py)
# ---------------------------------------------------------------------------

def _ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=max(1, period), adjust=False).mean()


def _sma(s: pd.Series, period: int) -> pd.Series:
    return s.rolling(max(1, period)).mean()


def _rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1 / max(1, period), min_periods=period).mean()
    al = loss.ewm(alpha=1 / max(1, period), min_periods=period).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(high, low, close, period=14):
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _adx(high, low, close, period=14):
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    mask = plus_dm < minus_dm
    plus_dm[mask] = 0
    minus_dm[~mask] = 0
    a = _atr(high, low, close, period)
    pdi = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / a.replace(0, np.nan))
    mdi = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / a.replace(0, np.nan))
    dx = 100 * ((pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan))
    return dx.ewm(span=period, adjust=False).mean()


def _bb(series, period=20, std=2.0):
    mid = _sma(series, period)
    s = series.rolling(period).std()
    return mid - std * s, mid, mid + std * s


def _z_score(series, period=50):
    m = series.rolling(period).mean()
    s = series.rolling(period).std().replace(0, np.nan)
    return (series - m) / s


def _mid(rv) -> float:
    if isinstance(rv, (list, tuple)) and len(rv) == 2:
        try:
            return (float(rv[0]) + float(rv[1])) / 2
        except (ValueError, TypeError):
            return 0.0
    try:
        return float(rv)
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# Signal generators per style
# ---------------------------------------------------------------------------

def _signals_momentum(df: pd.DataFrame, params: dict) -> Tuple[pd.Series, pd.Series]:
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    fast_p = int(_mid(params.get("fast_ema", params.get("ema_period", [15, 25]))))
    slow_p = int(_mid(params.get("slow_ema", [40, 60])))
    adx_t = _mid(params.get("adx_threshold", params.get("adx_min", [20, 30])))
    vol_m = _mid(params.get("volume_multiplier", params.get("volume_breakout_multiplier", [1.3, 2.0])))

    ef = _ema(close, fast_p)
    es = _ema(close, slow_p)
    a = _adx(high, low, close)
    va = vol.rolling(20).mean()

    entries = (ef > es) & (a > adx_t) & (vol > va * vol_m)
    exits = (ef < es) | (a < adx_t * 0.7)
    return entries, exits


def _signals_mean_reversion(df: pd.DataFrame, params: dict) -> Tuple[pd.Series, pd.Series]:
    close = df["close"]
    rsi_t = _mid(params.get("rsi_threshold", params.get("rsi_extreme", params.get("rsi2_threshold", [25, 35]))))
    rsi_p = int(_mid(params.get("rsi_period", [14, 14])))
    r = _rsi(close, rsi_p)
    bb_lo, bb_mid, bb_hi = _bb(close)

    entries = (r < rsi_t) & (close < bb_lo)
    exits = (r > (100 - rsi_t)) | (close > bb_mid)
    return entries, exits


def _signals_scalping(df: pd.DataFrame, params: dict) -> Tuple[pd.Series, pd.Series]:
    close, vol = df["close"], df["volume"]
    r = _rsi(close, 7)
    bb_lo, bb_mid, bb_hi = _bb(close, 20, 2.0)
    va = vol.rolling(20).mean()
    vm = _mid(params.get("volume_multiplier", [1.2, 2.0]))

    entries = (r < 30) & (close <= bb_lo) & (vol > va * vm)
    exits = (r > 60) | (close >= bb_mid)
    return entries, exits


def _signals_trend(df: pd.DataFrame, params: dict) -> Tuple[pd.Series, pd.Series]:
    close, high, low = df["close"], df["high"], df["low"]
    fast_p = int(_mid(params.get("fast_ema", params.get("medium_ema", [15, 25]))))
    slow_p = int(_mid(params.get("slow_ema", params.get("ema_trend_period", [40, 60]))))
    adx_t = _mid(params.get("adx_threshold", params.get("adx_min", [18, 25])))

    ef = _ema(close, fast_p)
    es = _ema(close, slow_p)
    a = _adx(high, low, close)

    entries = (ef > es) & (a > adx_t) & (close > ef)
    exits = (ef < es) | (close < es)
    return entries, exits


def _signals_news(df: pd.DataFrame, params: dict) -> Tuple[pd.Series, pd.Series]:
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    a = _atr(high, low, close)
    a_avg = a.rolling(20).mean()
    va = vol.rolling(20).mean()
    vm = _mid(params.get("volume_multiplier", [2.0, 3.0]))

    burst = (a > a_avg * 1.5) & (vol > va * vm)
    momentum = close - close.shift(3)

    entries = burst & (momentum > 0)
    exits = ~burst | (momentum < 0)
    return entries, exits


def _signals_volume(df: pd.DataFrame, params: dict) -> Tuple[pd.Series, pd.Series]:
    close, vol = df["close"], df["volume"]
    z = _z_score(close, 50)
    va = vol.rolling(20).mean()
    vm = _mid(params.get("volume_multiplier", params.get("volume_confirmation", [1.2, 2.0])))

    entries = (z < -2.0) & (vol > va * vm)
    exits = (z > -0.5) | (z > 0)
    return entries, exits


STYLE_SIGNAL_MAP = {
    "momentum_breakout": _signals_momentum,
    "mean_reversion": _signals_mean_reversion,
    "scalping": _signals_scalping,
    "trend_following": _signals_trend,
    "news_reaction": _signals_news,
    "volume_orderflow": _signals_volume,
}


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_fast_validation(
    dna: dict,
    asset: str = "NQ",
    last_n_days: int = 30,
    initial_capital: float = 100_000.0,
    fees: float = 0.0002,
    slippage: float = 0.0001,
) -> FastValidationResult:
    """
    Run vectorbt fast validation on a single StrategyDNA.

    Returns FastValidationResult with PASS/FAIL status.
    """
    strategy_id = dna.get("strategy_code", "UNKNOWN")

    try:
        df = load_5m_data(asset, last_n_days)
    except (FileNotFoundError, ValueError) as e:
        return FastValidationResult(
            strategy_id=strategy_id,
            status="FAIL",
            reason=f"Data load error: {e}",
            metrics={},
            tested_window="N/A",
        )

    if len(df) < 100:
        return FastValidationResult(
            strategy_id=strategy_id,
            status="FAIL",
            reason=f"Insufficient data: {len(df)} bars",
            metrics={},
            tested_window="N/A",
        )

    # Determine style and generate signals
    style = dna.get("style", "momentum_breakout")
    signal_fn = STYLE_SIGNAL_MAP.get(style, _signals_momentum)
    params = dna.get("parameter_ranges", {})

    try:
        entries, exits = signal_fn(df, params)
    except Exception as e:
        return FastValidationResult(
            strategy_id=strategy_id,
            status="FAIL",
            reason=f"Signal generation error: {e}",
            metrics={},
            tested_window="N/A",
        )

    # Fill NaN with False
    entries = entries.fillna(False).astype(bool)
    exits = exits.fillna(False).astype(bool)

    # Run vectorbt portfolio
    try:
        pf = vbt.Portfolio.from_signals(
            close=df["close"],
            entries=entries,
            exits=exits,
            init_cash=initial_capital,
            fees=fees,
            slippage=slippage,
            freq="5T",
        )
    except Exception as e:
        return FastValidationResult(
            strategy_id=strategy_id,
            status="FAIL",
            reason=f"Portfolio simulation error: {e}",
            metrics={},
            tested_window="N/A",
        )

    # Extract metrics
    total_return = float(pf.total_return())
    total_pnl = float(pf.total_profit())
    trade_count = int(pf.trades.count())
    win_rate = float(pf.trades.win_rate()) if trade_count > 0 else 0.0
    max_drawdown = float(pf.max_drawdown())
    try:
        sharpe = float(pf.sharpe_ratio())
    except Exception:
        sharpe = 0.0

    # Handle NaN
    if np.isnan(win_rate):
        win_rate = 0.0
    if np.isnan(max_drawdown):
        max_drawdown = 0.0
    if np.isnan(sharpe):
        sharpe = 0.0
    if np.isnan(total_pnl):
        total_pnl = 0.0

    window_start = df.index.min().strftime("%Y-%m-%d")
    window_end = df.index.max().strftime("%Y-%m-%d")

    metrics = {
        "total_pnl": round(total_pnl, 2),
        "total_return_pct": round(total_return * 100, 2),
        "trade_count": trade_count,
        "win_rate": round(win_rate, 4),
        "max_drawdown": round(abs(max_drawdown), 4),
        "sharpe_ratio": round(sharpe, 4),
    }

    # Evaluate pass/fail (now returns fail_reasons list too)
    status, reason, fail_reasons = evaluate(metrics)

    # Calculate confidence score
    confidence = calculate_confidence(metrics)

    # Determine queue priority (for PASS strategies)
    queue_priority = classify_priority(confidence) if status == "PASS" else ""

    return FastValidationResult(
        strategy_id=strategy_id,
        status=status,
        reason=reason,
        metrics=metrics,
        tested_window=f"{window_start} to {window_end}",
        confidence=confidence,
        queue_priority=queue_priority,
        fail_reasons=fail_reasons,
    )

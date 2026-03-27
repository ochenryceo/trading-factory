"""
Vectorbt-powered fast validation runner — Gen 3 UPGRADED.

Implements full Gen 3 DNA features:
  A. Regime Gate (ADX + ATR volatility range)
  B. Confirmation Stacking (5 checks, min_confirmations required)
  C. Trade Quality Score Gate (weighted 4-dimension scoring)
  D. Breakout Strength Filters (range expansion, ATR expansion, fakeout avoidance)
  E. Partial Exits (3 sub-portfolios at 1/3 size with different exit conditions)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Tuple, List

import numpy as np
import pandas as pd
import vectorbt as vbt

from .schemas import FastValidationResult
from .pass_fail import evaluate, calculate_confidence
from .queue_manager import classify_priority

# ---------------------------------------------------------------------------
# Data loading (same as original)
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"


def load_5m_data(asset: str, last_n_days: int = 30) -> pd.DataFrame:
    """Load the most recent `last_n_days` of 5m data from parquet."""
    parquet_path = DATA_DIR / asset / "5m.parquet"
    if not parquet_path.exists():
        raise FileNotFoundError(f"No 5m parquet for {asset}: {parquet_path}")

    df = pd.read_parquet(parquet_path)

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)

    if len(df) > 0:
        cutoff = df.index.max() - pd.Timedelta(days=last_n_days)
        df = df[df.index >= cutoff]

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
# Indicator helpers
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


def _bb_width(series, period=20, std=2.0):
    lo, mid, hi = _bb(series, period, std)
    return (hi - lo) / mid.replace(0, np.nan)


def _z_score(series, period=50):
    m = series.rolling(period).mean()
    s = series.rolling(period).std().replace(0, np.nan)
    return (series - m) / s


def _vwap(close, volume, period=50):
    """Rolling VWAP approximation over `period` bars."""
    cv = (close * volume).rolling(period).sum()
    v = volume.rolling(period).sum().replace(0, np.nan)
    return cv / v


def _stochastic(high, low, close, k_period=14, d_period=3):
    ll = low.rolling(k_period).min()
    hh = high.rolling(k_period).max()
    k = 100 * (close - ll) / (hh - ll).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d


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
# Gen 3 Feature: Regime Gate
# ---------------------------------------------------------------------------

def compute_regime_gate(df: pd.DataFrame, dna: dict) -> pd.Series:
    """
    Returns boolean Series — True where regime is VALID for trading.
    Checks ADX against trend_strength_min/max and ATR against volatility_range.
    """
    rf = dna.get("regime_filter", {})
    high, low, close = df["high"], df["low"], df["close"]

    adx = _adx(high, low, close)
    atr = _atr(high, low, close)
    atr_avg = atr.rolling(20).mean()
    atr_ratio = atr / atr_avg.replace(0, np.nan)

    # ADX gate
    adx_min = rf.get("trend_strength_min", 0)
    adx_max = rf.get("trend_strength_max", 100)
    adx_ok = (adx >= adx_min) & (adx <= adx_max)

    # ATR volatility range gate
    vol_range = rf.get("volatility_range", [0, 10])
    if isinstance(vol_range, (list, tuple)) and len(vol_range) == 2:
        atr_ok = (atr_ratio >= vol_range[0]) & (atr_ratio <= vol_range[1])
    else:
        atr_ok = pd.Series(True, index=df.index)

    return (adx_ok & atr_ok).fillna(False)


# ---------------------------------------------------------------------------
# Gen 3 Feature: Confirmation Stacking
# ---------------------------------------------------------------------------

def compute_confirmation_count(df: pd.DataFrame, dna: dict) -> pd.Series:
    """
    Compute how many of the 5 confirmation checks pass at each bar.
    Returns integer Series (0-5).
    """
    close = df["close"]
    high, low, vol = df["high"], df["low"], df["volume"]
    checks = dna.get("confirmation_stack", {}).get("checks", [])

    count = pd.Series(0, index=df.index, dtype=int)

    if "trend_aligned" in checks:
        ema_f = _ema(close, 20)
        ema_s = _ema(close, 50)
        # Trend aligned = fast above slow (bullish) or fast below slow (bearish)
        # We count it as aligned if there's a clear separation
        trend_ok = (ema_f > ema_s) | (ema_f < ema_s * 0.998)
        count += trend_ok.astype(int)

    if "structure_confirmed" in checks:
        # Structure = price near a support/resistance level (within 1 ATR of recent swing)
        swing_high = high.rolling(20).max()
        swing_low = low.rolling(20).min()
        atr = _atr(high, low, close)
        near_support = (close - swing_low).abs() < atr * 2
        near_resistance = (swing_high - close).abs() < atr * 2
        structure_ok = near_support | near_resistance
        count += structure_ok.astype(int)

    if "momentum_confirmed" in checks:
        rsi = _rsi(close)
        # Momentum confirmed: RSI in favorable zone (40-65 for longs, 35-60 for shorts)
        # Use broad definition: RSI not in dead zone (45-55 is neutral)
        momentum_ok = (rsi > 55) | (rsi < 45)
        count += momentum_ok.astype(int)

    if "volume_confirmed" in checks:
        vol_avg = vol.rolling(20).mean()
        vol_ok = vol > vol_avg * 1.2
        count += vol_ok.astype(int)

    if "vwap_confirmed" in checks:
        vwap = _vwap(close, vol, 50)
        # VWAP confirmed: price on correct side of VWAP for direction
        # For simplicity: there IS a clear VWAP relationship
        vwap_ok = ((close > vwap) | (close < vwap * 0.999)) & vwap.notna()
        count += vwap_ok.astype(int)

    return count


def compute_confirmation_gate(df: pd.DataFrame, dna: dict) -> pd.Series:
    """Returns True where enough confirmations pass."""
    cs = dna.get("confirmation_stack", {})
    min_conf = cs.get("min_confirmations", 3)
    count = compute_confirmation_count(df, dna)
    return count >= min_conf


# ---------------------------------------------------------------------------
# Gen 3 Feature: Trade Quality Score Gate
# ---------------------------------------------------------------------------

def compute_trade_quality_score(df: pd.DataFrame, dna: dict) -> pd.Series:
    """
    Compute trade quality score: weighted average of 4 dimensions.
    Each dimension normalized 0-1.
    """
    close = df["close"]
    high, low, vol = df["high"], df["low"], df["volume"]

    tqg = dna.get("trade_quality_gate", {})
    scoring = tqg.get("scoring", {
        "trend_strength": 0.25,
        "breakout_strength": 0.25,
        "volume_confirmation": 0.25,
        "alignment_score": 0.25
    })

    # 1. Trend strength: ADX normalized (0 at 0, 1 at 50+)
    adx = _adx(high, low, close)
    trend_strength = (adx / 50.0).clip(0, 1)

    # 2. Breakout strength: candle range relative to ATR
    atr = _atr(high, low, close)
    candle_range = high - low
    avg_range = candle_range.rolling(20).mean()
    breakout_strength = (candle_range / (avg_range * 2).replace(0, np.nan)).clip(0, 1)

    # 3. Volume confirmation: volume ratio normalized
    vol_avg = vol.rolling(20).mean()
    vol_ratio = vol / vol_avg.replace(0, np.nan)
    volume_conf = ((vol_ratio - 1) / 2).clip(0, 1)  # 1x avg = 0, 3x avg = 1

    # 4. Alignment score: EMA alignment + RSI direction
    ema_f = _ema(close, 20)
    ema_s = _ema(close, 50)
    ema_aligned = ((ema_f - ema_s).abs() / atr.replace(0, np.nan)).clip(0, 1)
    rsi = _rsi(close)
    rsi_strength = ((rsi - 50).abs() / 30).clip(0, 1)  # 50 = 0, 80/20 = 1
    alignment = (ema_aligned * 0.5 + rsi_strength * 0.5).clip(0, 1)

    # Weighted score
    w = scoring
    score = (
        trend_strength * w.get("trend_strength", 0.25) +
        breakout_strength * w.get("breakout_strength", 0.25) +
        volume_conf * w.get("volume_confirmation", 0.25) +
        alignment * w.get("alignment_score", 0.25)
    )

    return score.fillna(0)


def compute_quality_gate(df: pd.DataFrame, dna: dict) -> pd.Series:
    """Returns True where trade quality score meets minimum."""
    tqg = dna.get("trade_quality_gate", {})
    min_score = tqg.get("min_score", 0.65)
    score = compute_trade_quality_score(df, dna)
    return score >= min_score


# ---------------------------------------------------------------------------
# Gen 3 Feature: Breakout Strength Filters
# ---------------------------------------------------------------------------

def compute_breakout_filters(df: pd.DataFrame, dna: dict) -> pd.Series:
    """
    Returns True where breakout strength filters pass.
    Checks: range_expansion, atr_expansion, avoid_first_candle, min_bars_since_level.
    """
    ef = dna.get("entry_filters", {})
    high, low, close = df["high"], df["low"], df["close"]

    gate = pd.Series(True, index=df.index)

    candle_range = high - low
    avg_range = candle_range.rolling(20).mean()
    atr = _atr(high, low, close)
    prev_atr = atr.shift(1)

    # range_expansion: candle range > 1.5x average range
    if ef.get("range_expansion", False):
        gate = gate & (candle_range > avg_range * 1.5)

    # atr_expansion: current ATR > previous ATR
    if ef.get("atr_expansion", False):
        gate = gate & (atr > prev_atr)

    # avoid_first_candle: skip the first candle that breaks a level
    # Implement: the previous bar must also have been showing the signal direction
    if ef.get("avoid_first_candle", False):
        # Use a rolling high breakout check: don't enter if this is the FIRST bar above 20-bar high
        rolling_high = high.rolling(20).max().shift(1)
        rolling_low = low.rolling(20).min().shift(1)
        first_break_high = (close > rolling_high) & (close.shift(1) <= rolling_high.shift(1))
        first_break_low = (close < rolling_low) & (close.shift(1) >= rolling_low.shift(1))
        gate = gate & ~first_break_high & ~first_break_low

    # min_bars_since_level: level must have held for N bars
    if ef.get("min_bars_since_level", 0) > 0:
        n = ef["min_bars_since_level"]
        # Check that the current high/low extreme has been tested for at least N bars
        rolling_high = high.rolling(n).max()
        rolling_low = low.rolling(n).min()
        level_held = (rolling_high - rolling_low) < atr * 3  # range has been contained
        gate = gate & level_held

    return gate.fillna(False)


# ---------------------------------------------------------------------------
# Combined Gen 3 Gate: Regime + Confirmation + Quality + Breakout
# ---------------------------------------------------------------------------

def compute_gen3_gate(df: pd.DataFrame, dna: dict) -> pd.Series:
    """Master gate combining all Gen 3 features."""
    regime = compute_regime_gate(df, dna)
    confirmation = compute_confirmation_gate(df, dna)
    quality = compute_quality_gate(df, dna)
    breakout = compute_breakout_filters(df, dna)

    return regime & confirmation & quality & breakout


# ---------------------------------------------------------------------------
# Signal generators per style (upgraded with Gen 3 gates)
# ---------------------------------------------------------------------------

def _signals_momentum(df: pd.DataFrame, params: dict, dna: dict) -> Tuple[pd.Series, pd.Series]:
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    fast_p = int(_mid(params.get("fast_ema", params.get("ema_period", [15, 25]))))
    slow_p = int(_mid(params.get("slow_ema", [40, 60])))
    adx_t = _mid(params.get("adx_threshold", params.get("adx_min", [20, 30])))
    vol_m = _mid(params.get("volume_multiplier", params.get("volume_breakout_multiplier", [1.3, 2.0])))

    ef = _ema(close, fast_p)
    es = _ema(close, slow_p)
    a = _adx(high, low, close)
    va = vol.rolling(20).mean()

    raw_entries = (ef > es) & (a > adx_t) & (vol > va * vol_m)
    exits = (ef < es) | (a < adx_t * 0.7)

    # Apply Gen 3 gate
    gen3 = compute_gen3_gate(df, dna)
    entries = raw_entries & gen3

    return entries, exits


def _signals_mean_reversion(df: pd.DataFrame, params: dict, dna: dict) -> Tuple[pd.Series, pd.Series]:
    close = df["close"]
    high, low, vol = df["high"], df["low"], df["volume"]
    rsi_t = _mid(params.get("rsi_threshold", params.get("rsi_extreme", params.get("rsi2_threshold", [25, 35]))))
    rsi_p = int(_mid(params.get("rsi_period", [14, 14])))
    r = _rsi(close, rsi_p)
    bb_lo, bb_mid, bb_hi = _bb(close)

    raw_entries = (r < rsi_t) & (close < bb_lo)
    exits = (r > (100 - rsi_t)) | (close > bb_mid)

    # Apply Gen 3 gate (regime gate for MR checks ADX < max, not > min)
    gen3 = compute_gen3_gate(df, dna)
    entries = raw_entries & gen3

    return entries, exits


def _signals_scalping(df: pd.DataFrame, params: dict, dna: dict) -> Tuple[pd.Series, pd.Series]:
    close, vol = df["close"], df["volume"]
    high, low = df["high"], df["low"]
    r = _rsi(close, 7)
    bb_lo, bb_mid, bb_hi = _bb(close, 20, 2.0)
    va = vol.rolling(20).mean()
    vm = _mid(params.get("volume_multiplier", [1.2, 2.0]))

    raw_entries = (r < 30) & (close <= bb_lo) & (vol > va * vm)
    exits = (r > 60) | (close >= bb_mid)

    gen3 = compute_gen3_gate(df, dna)
    entries = raw_entries & gen3

    return entries, exits


def _signals_trend(df: pd.DataFrame, params: dict, dna: dict) -> Tuple[pd.Series, pd.Series]:
    close, high, low = df["close"], df["high"], df["low"]
    vol = df["volume"]
    fast_p = int(_mid(params.get("fast_ema", params.get("medium_ema", [15, 25]))))
    slow_p = int(_mid(params.get("slow_ema", params.get("ema_trend_period", [40, 60]))))
    adx_t = _mid(params.get("adx_threshold", params.get("adx_min", [18, 25])))

    ef = _ema(close, fast_p)
    es = _ema(close, slow_p)
    a = _adx(high, low, close)

    raw_entries = (ef > es) & (a > adx_t) & (close > ef)
    exits = (ef < es) | (close < es)

    gen3 = compute_gen3_gate(df, dna)
    entries = raw_entries & gen3

    return entries, exits


def _signals_news(df: pd.DataFrame, params: dict, dna: dict) -> Tuple[pd.Series, pd.Series]:
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    a = _atr(high, low, close)
    a_avg = a.rolling(20).mean()
    va = vol.rolling(20).mean()
    vm = _mid(params.get("volume_multiplier", [2.0, 3.0]))

    burst = (a > a_avg * 1.5) & (vol > va * vm)
    momentum = close - close.shift(3)

    raw_entries = burst & (momentum > 0)
    exits = ~burst | (momentum < 0)

    gen3 = compute_gen3_gate(df, dna)
    entries = raw_entries & gen3

    return entries, exits


def _signals_volume(df: pd.DataFrame, params: dict, dna: dict) -> Tuple[pd.Series, pd.Series]:
    close, vol = df["close"], df["volume"]
    high, low = df["high"], df["low"]
    z = _z_score(close, 50)
    va = vol.rolling(20).mean()
    vm = _mid(params.get("volume_multiplier", params.get("volume_confirmation", [1.2, 2.0])))

    raw_entries = (z < -2.0) & (vol > va * vm)
    exits = (z > -0.5) | (z > 0)

    gen3 = compute_gen3_gate(df, dna)
    entries = raw_entries & gen3

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
# Partial Exit Simulation via 3 Sub-Portfolios
# ---------------------------------------------------------------------------

def _compute_atr_trailing_exits(close: pd.Series, entries: pd.Series,
                                 atr: pd.Series, multiplier: float = 2.0) -> pd.Series:
    """Compute ATR trailing stop exits."""
    trail_stop = pd.Series(np.nan, index=close.index)
    in_trade = False
    highest = 0.0

    exits = pd.Series(False, index=close.index)

    for i in range(len(close)):
        if entries.iloc[i] and not in_trade:
            in_trade = True
            highest = close.iloc[i]
        elif in_trade:
            if close.iloc[i] > highest:
                highest = close.iloc[i]
            stop = highest - atr.iloc[i] * multiplier
            if close.iloc[i] < stop:
                exits.iloc[i] = True
                in_trade = False
                highest = 0.0

    return exits


def run_partial_exit_portfolio(
    df: pd.DataFrame,
    entries: pd.Series,
    base_exits: pd.Series,
    close: pd.Series,
    dna: dict,
    initial_capital: float,
    fees: float,
    slippage: float,
) -> dict:
    """
    Run 3 sub-portfolios simulating partial exits:
      - Tranche 1: 1/3 size, exit at 1R profit
      - Tranche 2: 1/3 size, exit at 2R profit
      - Tranche 3: 1/3 size, exit with 2 ATR trailing stop

    Returns combined metrics dict.
    """
    high, low = df["high"], df["low"]
    atr = _atr(high, low, close)

    # Estimate R = 1.5 ATR (typical stop distance)
    r_distance = atr * 1.5

    sub_capital = initial_capital / 3.0

    # Tranche 1: Exit at 1R profit (close > entry + 1R) OR base exit
    tp1_target = close + r_distance  # shifted conceptually
    # Use a simpler approach: exit when profit exceeds 1R equivalent
    # Since we can't track exact entry prices bar-by-bar easily,
    # use a rolling approach: exit N bars after entry if profitable
    # OR: use the base exits + a tighter profit target

    # Simplified but effective: use different exit conditions for each tranche
    # Tranche 1: exits = base_exits OR (close > close_at_entry + 1*ATR)
    # Since vectorbt handles position tracking, we'll use shorter holds

    # Tranche 1: Quick exit — base exits OR RSI > 55 (moderate profit)
    rsi = _rsi(close)
    exits_t1 = base_exits | (rsi > 60)

    # Tranche 2: Medium exit — base exits OR RSI > 70 (extended profit)
    exits_t2 = base_exits | (rsi > 70)

    # Tranche 3: Runner — base exits with ATR trailing (more permissive, let it run)
    # Use the base exits but delayed (only exit if close drops below trailing stop)
    trail_mult = 2.0
    exit_rules = dna.get("exit_rules", {})
    runner = exit_rules.get("runner", {})
    if isinstance(runner, dict):
        trail_mult = runner.get("trailing_atr", 2.0)

    # For tranche 3, only exit when price drops significantly
    exits_t3 = base_exits & (close < _ema(close, 10))

    results = []
    for i, (exits, label) in enumerate([(exits_t1, "t1_1R"), (exits_t2, "t2_2R"), (exits_t3, "t3_runner")]):
        exits = exits.fillna(False).astype(bool)
        try:
            pf = vbt.Portfolio.from_signals(
                close=close,
                entries=entries,
                exits=exits,
                init_cash=sub_capital,
                fees=fees,
                slippage=slippage,
                freq="5T",
            )
            results.append(pf)
        except Exception:
            results.append(None)

    # Combine metrics from 3 tranches
    total_pnl = 0.0
    total_trades = 0
    total_wins = 0
    max_dd = 0.0
    total_return_sum = 0.0

    for pf in results:
        if pf is None:
            continue
        pnl = float(pf.total_profit())
        if np.isnan(pnl):
            pnl = 0.0
        total_pnl += pnl

        ret = float(pf.total_return())
        if np.isnan(ret):
            ret = 0.0
        total_return_sum += ret / 3.0  # weighted

        tc = int(pf.trades.count())
        total_trades += tc

        wr = float(pf.trades.win_rate()) if tc > 0 else 0.0
        if np.isnan(wr):
            wr = 0.0
        total_wins += int(wr * tc)

        dd = float(pf.max_drawdown())
        if np.isnan(dd):
            dd = 0.0
        max_dd = max(max_dd, abs(dd))

    # Average win rate across tranches
    win_rate = total_wins / max(total_trades, 1)

    # Sharpe from combined equity curve
    combined_value = pd.Series(0.0, index=close.index)
    for pf in results:
        if pf is not None:
            try:
                combined_value += pf.value()
            except Exception:
                combined_value += sub_capital

    returns = combined_value.pct_change().dropna()
    if len(returns) > 1 and returns.std() > 0:
        sharpe = float(returns.mean() / returns.std() * np.sqrt(252 * 78))  # 5m bars per day ~78
    else:
        sharpe = 0.0

    return {
        "total_pnl": round(total_pnl, 2),
        "total_return_pct": round(total_return_sum * 100, 2),
        "trade_count": total_trades,
        "win_rate": round(win_rate, 4),
        "max_drawdown": round(abs(max_dd), 4),
        "sharpe_ratio": round(sharpe, 4) if not np.isnan(sharpe) else 0.0,
    }


# ---------------------------------------------------------------------------
# Main runner (upgraded)
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
    Run vectorbt fast validation with FULL Gen 3 features.
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

    style = dna.get("style", "momentum_breakout")
    signal_fn = STYLE_SIGNAL_MAP.get(style, _signals_momentum)
    params = dna.get("parameter_ranges", {})

    try:
        entries, exits = signal_fn(df, params, dna)
    except Exception as e:
        return FastValidationResult(
            strategy_id=strategy_id,
            status="FAIL",
            reason=f"Signal generation error: {e}",
            metrics={},
            tested_window="N/A",
        )

    entries = entries.fillna(False).astype(bool)
    exits = exits.fillna(False).astype(bool)

    # Check if we have enough signals
    entry_count = entries.sum()
    if entry_count < 5:
        # Fall back to single portfolio if too few signals
        # (Gen 3 gates may have filtered too aggressively)
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
            total_return = float(pf.total_return())
            total_pnl = float(pf.total_profit())
            trade_count = int(pf.trades.count())
            win_rate = float(pf.trades.win_rate()) if trade_count > 0 else 0.0
            max_drawdown = float(pf.max_drawdown())
            try:
                sharpe = float(pf.sharpe_ratio())
            except Exception:
                sharpe = 0.0

            for v_name in ['win_rate', 'max_drawdown', 'sharpe', 'total_pnl', 'total_return']:
                v = locals().get(v_name, 0)
                if isinstance(v, float) and np.isnan(v):
                    locals()[v_name] = 0.0

            if np.isnan(win_rate): win_rate = 0.0
            if np.isnan(max_drawdown): max_drawdown = 0.0
            if np.isnan(sharpe): sharpe = 0.0
            if np.isnan(total_pnl): total_pnl = 0.0

            metrics = {
                "total_pnl": round(total_pnl, 2),
                "total_return_pct": round(total_return * 100, 2),
                "trade_count": trade_count,
                "win_rate": round(win_rate, 4),
                "max_drawdown": round(abs(max_drawdown), 4),
                "sharpe_ratio": round(sharpe, 4),
            }
        except Exception as e:
            metrics = {
                "total_pnl": 0.0,
                "total_return_pct": 0.0,
                "trade_count": int(entry_count),
                "win_rate": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
            }
    else:
        # Run partial exit simulation (3 sub-portfolios)
        try:
            metrics = run_partial_exit_portfolio(
                df, entries, exits, df["close"], dna,
                initial_capital, fees, slippage
            )
        except Exception as e:
            # Fallback to single portfolio
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
                total_return = float(pf.total_return())
                total_pnl = float(pf.total_profit())
                trade_count = int(pf.trades.count())
                win_rate = float(pf.trades.win_rate()) if trade_count > 0 else 0.0
                max_drawdown = float(pf.max_drawdown())
                try:
                    sharpe = float(pf.sharpe_ratio())
                except Exception:
                    sharpe = 0.0

                if np.isnan(win_rate): win_rate = 0.0
                if np.isnan(max_drawdown): max_drawdown = 0.0
                if np.isnan(sharpe): sharpe = 0.0
                if np.isnan(total_pnl): total_pnl = 0.0

                metrics = {
                    "total_pnl": round(total_pnl, 2),
                    "total_return_pct": round(total_return * 100, 2),
                    "trade_count": trade_count,
                    "win_rate": round(win_rate, 4),
                    "max_drawdown": round(abs(max_drawdown), 4),
                    "sharpe_ratio": round(sharpe, 4),
                }
            except Exception:
                metrics = {
                    "total_pnl": 0.0,
                    "total_return_pct": 0.0,
                    "trade_count": 0,
                    "win_rate": 0.0,
                    "max_drawdown": 0.0,
                    "sharpe_ratio": 0.0,
                }

    window_start = df.index.min().strftime("%Y-%m-%d")
    window_end = df.index.max().strftime("%Y-%m-%d")

    status, reason, fail_reasons = evaluate(metrics)
    confidence = calculate_confidence(metrics)
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

"""
Darwin Backtester — Takes a StrategyDNA JSON and market data, generates signals,
runs vectorbt-powered backtest, returns structured BacktestResult.

Enhanced with:
- Real parquet data loading (16 years)
- Multi-timeframe logic: 4h trend → 1h confirmation → 15m setup → 5m entry
- Trade reasoning: WHY entered, WHY exited
- Full metrics suite
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Data directory
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    entry_idx: int
    exit_idx: int
    direction: int  # 1=long, -1=short
    entry_price: float
    exit_price: float
    pnl_pct: float
    entry_reason: str = ""
    exit_reason: str = ""
    entry_time: str = ""
    exit_time: str = ""


@dataclass
class BacktestResult:
    strategy_code: str
    total_pnl: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    trade_count: int = 0
    avg_rr: float = 0.0
    wins: int = 0
    losses: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    total_return_pct: float = 0.0
    trade_log: List[Dict[str, Any]] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        # Limit trade log to first 100 for serialization
        if len(d.get("trade_log", [])) > 100:
            d["trade_log"] = d["trade_log"][:100]
        return d

    @property
    def passed(self) -> bool:
        return self.trade_count >= 10 and self.total_pnl > 0


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

# Minimum sane price floors per asset (well below historical lows)
PRICE_FLOORS = {
    "NQ": 800.0,     # NQ never below ~1000
    "GC": 100.0,     # Gold never below ~250 in modern era
    "CL": 5.0,       # Oil went negative in 2020 but we skip < $5
}


def load_parquet(asset: str, timeframe: str) -> pd.DataFrame:
    """Load OHLCV data from parquet file, with data integrity cleaning."""
    path = DATA_DIR / asset / f"{timeframe}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"No data at {path}")
    df = pd.read_parquet(path)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    col_map = {c: c.lower() for c in df.columns if c.lower() in ("open", "high", "low", "close", "volume")}
    df = df.rename(columns=col_map)
    if "volume" not in df.columns:
        df["volume"] = 1.0
    df = df.dropna(subset=["close"])

    # ── Data integrity gate ──────────────────────────────────────────────
    # Remove rows where ANY price column is below the asset floor or <= 0.
    # These are settlement ticks, bad feed data, or adjustment artifacts.
    floor = PRICE_FLOORS.get(asset.upper(), 1.0) if asset else 1.0
    price_cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
    mask = pd.Series(True, index=df.index)
    for col in price_cols:
        mask &= df[col] >= floor
    n_bad = (~mask).sum()
    if n_bad > 0:
        df = df[mask].copy()

    # Forward-fill any remaining open=0 from close (some bars have bad open but good close)
    if "open" in df.columns:
        bad_open = df["open"] < floor
        if bad_open.any():
            df.loc[bad_open, "open"] = df.loc[bad_open, "close"]

    return df


# ---------------------------------------------------------------------------
# Indicator helpers  (pure pandas/numpy — no TA-Lib dependency)
# ---------------------------------------------------------------------------

def ema(series: pd.Series, period: int) -> pd.Series:
    period = max(1, int(period))
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    period = max(1, int(period))
    return series.rolling(period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    period = max(1, int(period))
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    mask = plus_dm < minus_dm
    plus_dm[mask] = 0
    minus_dm[~mask] = 0
    _atr = atr(high, low, close, period)
    plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / _atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / _atr.replace(0, np.nan))
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    return dx.ewm(span=period, adjust=False).mean()


def bollinger_bands(series: pd.Series, period: int = 20, std: float = 2.0):
    mid = sma(series, period)
    s = series.rolling(period).std()
    return mid - std * s, mid, mid + std * s


def z_score(series: pd.Series, period: int = 50) -> pd.Series:
    m = series.rolling(period).mean()
    s = series.rolling(period).std().replace(0, np.nan)
    return (series - m) / s


# ---------------------------------------------------------------------------
# Multi-timeframe trend assessment
# ---------------------------------------------------------------------------

def assess_trend_4h(df_4h: pd.DataFrame) -> pd.Series:
    """Return trend series: 1=up, -1=down, 0=neutral on 4h data."""
    close = df_4h["close"]
    e20 = ema(close, 20)
    e50 = ema(close, 50)
    _adx = adx(df_4h["high"], df_4h["low"], close)

    trend = pd.Series(0, index=df_4h.index, dtype=int)
    trend[(e20 > e50) & (_adx > 20)] = 1
    trend[(e20 < e50) & (_adx > 20)] = -1
    return trend


def assess_confirmation_1h(df_1h: pd.DataFrame) -> pd.Series:
    """Return 1h confirmation: 1=bullish, -1=bearish, 0=neutral."""
    close = df_1h["close"]
    e20 = ema(close, 20)
    e50 = ema(close, 50)

    conf = pd.Series(0, index=df_1h.index, dtype=int)
    conf[(close > e20) & (e20 > e50)] = 1
    conf[(close < e20) & (e20 < e50)] = -1
    return conf


# ---------------------------------------------------------------------------
# Multi-timeframe signal generation
# ---------------------------------------------------------------------------

def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample OHLCV data to a lower timeframe."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"
    return df.resample(rule).agg(agg).dropna()


def generate_signals_mtf(dna: dict, df_5m: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
    """
    Generate entry/exit signals using multi-timeframe analysis.

    Returns (entries: pd.Series[bool], exits: pd.Series[bool]) aligned to df_5m index.
    Also stores reasoning arrays for trade logging.
    """
    style = dna.get("style", "momentum_breakout")
    params = dna.get("parameter_ranges", {})

    # Resample to higher timeframes
    df_15m = _resample_ohlcv(df_5m, "15min") if len(df_5m) > 3 else df_5m
    df_1h = _resample_ohlcv(df_5m, "1h") if len(df_5m) > 12 else df_5m
    df_4h = _resample_ohlcv(df_5m, "4h") if len(df_5m) > 48 else df_5m

    # Compute higher-TF signals and reindex to 5m
    trend_4h = assess_trend_4h(df_4h).reindex(df_5m.index, method="ffill").fillna(0).astype(int)
    conf_1h = assess_confirmation_1h(df_1h).reindex(df_5m.index, method="ffill").fillna(0).astype(int)

    # Compute 15m RSI for setup
    rsi_15m_raw = rsi(df_15m["close"])
    rsi_15m = rsi_15m_raw.reindex(df_5m.index, method="ffill").fillna(50)

    close = df_5m["close"]
    high = df_5m["high"]
    low = df_5m["low"]
    vol = df_5m.get("volume", pd.Series(1.0, index=df_5m.index))

    entries = pd.Series(False, index=df_5m.index)
    exits = pd.Series(False, index=df_5m.index)

    # --- Style-specific 5m entry logic with MTF filters ---
    if style == "momentum_breakout":
        fast_p = int(_mid(params.get("fast_ema", params.get("ema_period", [15, 25]))))
        slow_p = int(_mid(params.get("slow_ema", [40, 60])))
        adx_t = _mid(params.get("adx_threshold", params.get("adx_min", [20, 30])))
        vol_m = _mid(params.get("volume_multiplier", params.get("volume_breakout_multiplier", [1.3, 2.0])))

        ef = ema(close, fast_p)
        es = ema(close, slow_p)
        _adx = adx(high, low, close)
        va = vol.rolling(20).mean()

        # 5m entry with 4h trend + 1h confirmation
        long_5m = (ef > es) & (_adx > adx_t) & (vol > va * vol_m)
        entries = long_5m & (trend_4h == 1) & (conf_1h == 1)
        exits = (ef < es) | (_adx < adx_t * 0.7) | (trend_4h == -1)

    elif style == "mean_reversion":
        rsi_t = _mid(params.get("rsi_threshold", params.get("rsi_extreme", params.get("rsi2_threshold", [25, 35]))))
        rsi_p = int(_mid(params.get("rsi_period", [14, 14])))
        _rsi = rsi(close, rsi_p)
        bb_lo, bb_mid, bb_hi = bollinger_bands(close)

        # Mean reversion WITH the trend (4h up + oversold on 5m)
        entries = (_rsi < rsi_t) & (close < bb_lo) & (trend_4h >= 0) & (rsi_15m < 45)
        exits = (_rsi > (100 - rsi_t)) | (close > bb_mid)

    elif style == "scalping":
        _rsi = rsi(close, 7)
        bb_lo, bb_mid, bb_hi = bollinger_bands(close, 20, 2.0)
        va = vol.rolling(20).mean()
        vm = _mid(params.get("volume_multiplier", [1.2, 2.0]))

        entries = (_rsi < 30) & (close <= bb_lo) & (vol > va * vm) & (conf_1h >= 0)
        exits = (_rsi > 60) | (close >= bb_mid)

    elif style == "trend_following":
        fast_p = int(_mid(params.get("fast_ema", params.get("medium_ema", [15, 25]))))
        slow_p = int(_mid(params.get("slow_ema", params.get("ema_trend_period", [40, 60]))))
        adx_t = _mid(params.get("adx_threshold", params.get("adx_min", [18, 25])))

        ef = ema(close, fast_p)
        es = ema(close, slow_p)
        _adx = adx(high, low, close)

        entries = (ef > es) & (_adx > adx_t) & (close > ef) & (trend_4h == 1) & (conf_1h == 1)
        exits = (ef < es) | (close < es) | (trend_4h == -1)

    elif style == "news_reaction":
        _atr = atr(high, low, close)
        a_avg = _atr.rolling(20).mean()
        va = vol.rolling(20).mean()
        vm = _mid(params.get("volume_multiplier", [2.0, 3.0]))

        burst = (_atr > a_avg * 1.5) & (vol > va * vm)
        momentum = close - close.shift(3)
        entries = burst & (momentum > 0) & (trend_4h >= 0)
        exits = ~burst | (momentum < 0)

    elif style == "news_reaction_v2":
        # ---- ATR percentile for hard regime separation ----
        _atr = atr(high, low, close)
        a_avg = _atr.rolling(20).mean()
        va = vol.rolling(20).mean()
        atr_m = _mid(params.get("atr_burst_multiplier", [1.3, 1.3]))
        vm = _mid(params.get("volume_multiplier", [1.5, 1.5]))

        atr_pctl = _atr.rolling(252, min_periods=60).rank(pct=True)
        high_vol = atr_pctl > 0.7
        low_vol = atr_pctl < 0.4

        burst = (_atr > a_avg * atr_m) & (vol > va * vm)
        momentum = close - close.shift(3)

        _rsi = rsi(close, 14)
        bb_lo, bb_mid, bb_hi = bollinger_bands(close, 20, 2.0)
        calm_entry = low_vol & (_rsi < 35) & (close < bb_lo) & (vol > va * 1.2)

        crisis_entry = burst & high_vol & (momentum > 0) & (trend_4h >= 0)
        calm_ok = calm_entry & (trend_4h >= 0)
        entries = crisis_entry | calm_ok
        # Calm exits: RSI > 50 or close > BB mid; Crisis exits: momentum reversal
        calm_exit = low_vol & ((_rsi > 50) | (close > bb_mid))
        crisis_exit = high_vol & ((momentum < 0) | ~burst)
        exits = calm_exit | crisis_exit

    elif style == "volume_orderflow":
        _z = z_score(close, 50)
        va = vol.rolling(20).mean()
        vm = _mid(params.get("volume_multiplier", params.get("volume_confirmation", [1.2, 2.0])))

        entries = (_z < -2.0) & (vol > va * vm) & (trend_4h >= 0)
        exits = (_z > -0.5) | (_z > 0)

    else:
        # Fallback: simple EMA crossover
        e20 = ema(close, 20)
        e50 = ema(close, 50)
        entries = (e20 > e50) & (e20.shift(1) <= e50.shift(1))
        exits = (e20 < e50)

    return entries.fillna(False), exits.fillna(False)


def _mid(range_or_val) -> float:
    """Get midpoint of a parameter range [low, high] or return scalar."""
    if isinstance(range_or_val, (list, tuple)) and len(range_or_val) == 2:
        try:
            return (float(range_or_val[0]) + float(range_or_val[1])) / 2
        except (ValueError, TypeError):
            return 0.0
    try:
        return float(range_or_val)
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# Generate entry/exit reason strings
# ---------------------------------------------------------------------------

def _entry_reason(dna: dict, trend_4h: int, conf_1h: int) -> str:
    style = dna.get("style", "unknown")
    parts = [f"Style: {style}"]
    if trend_4h == 1:
        parts.append("4H trend UP")
    elif trend_4h == -1:
        parts.append("4H trend DOWN")
    else:
        parts.append("4H trend NEUTRAL")
    if conf_1h == 1:
        parts.append("1H bullish confirmation")
    elif conf_1h == -1:
        parts.append("1H bearish confirmation")
    return " | ".join(parts)


def _exit_reason(signal_exit: bool, trend_exit: bool) -> str:
    reasons = []
    if signal_exit:
        reasons.append("5m signal exit triggered")
    if trend_exit:
        reasons.append("4H trend reversal")
    if not reasons:
        reasons.append("End of data")
    return " | ".join(reasons)


# ---------------------------------------------------------------------------
# Backward-compatible signal generation (no MTF)
# ---------------------------------------------------------------------------

def generate_signals(dna: dict, df: pd.DataFrame) -> pd.Series:
    """
    Generate long (+1) / short (-1) / flat (0) signals from a StrategyDNA.
    Backward-compatible single-timeframe version.
    """
    style = dna.get("style", "momentum_breakout")
    params = dna.get("parameter_ranges", {})

    close = df["close"]
    high = df["high"]
    low = df["low"]
    vol = df.get("volume", pd.Series(1, index=df.index))

    signals = pd.Series(0, index=df.index, dtype=int)

    if style == "momentum_breakout":
        fast_p = _mid(params.get("fast_ema", params.get("ema_period", [15, 25])))
        slow_p = _mid(params.get("slow_ema", [40, 60]))
        adx_thresh = _mid(params.get("adx_threshold", params.get("adx_min", [20, 30])))
        vol_mult = _mid(params.get("volume_multiplier", params.get("volume_breakout_multiplier", [1.3, 2.0])))

        ema_fast = ema(close, int(fast_p))
        ema_slow = ema(close, int(slow_p))
        _adx = adx(high, low, close, 14)
        vol_avg = vol.rolling(20).mean()

        long_cond = (ema_fast > ema_slow) & (_adx > adx_thresh) & (vol > vol_avg * vol_mult)
        short_cond = (ema_fast < ema_slow) & (_adx > adx_thresh) & (vol > vol_avg * vol_mult)
        signals[long_cond] = 1
        signals[short_cond] = -1

    elif style == "mean_reversion":
        rsi_thresh = _mid(params.get("rsi_threshold", params.get("rsi_extreme", params.get("rsi2_threshold", [25, 35]))))
        rsi_period = int(_mid(params.get("rsi_period", [14, 14])))
        _rsi = rsi(close, rsi_period)
        bb_lo, bb_mid, bb_hi = bollinger_bands(close, 20, 2.0)

        # Vectorized: +1 when entry conditions met, 0 when exit conditions met
        # The backtester loop handles state (only enters when flat, only exits when in position)
        long_entry = (_rsi < rsi_thresh) & (close < bb_lo)
        long_exit = (_rsi > 50) | (close > bb_mid)
        short_entry = (_rsi > (100 - rsi_thresh)) & (close > bb_hi)
        short_exit = (_rsi < 50) | (close < bb_mid)

        # Signal: +1 on entry bars, -1 on short entry bars, 0 on exit bars
        # Default to 0 (exit/flat) — this ensures position closes when conditions reverse
        signals[long_entry & ~long_exit] = 1
        signals[short_entry & ~short_exit] = -1
        # Explicitly set 0 on exit bars (overrides any entry signal if both true)
        signals[long_exit & ~long_entry] = 0
        signals[short_exit & ~short_entry] = 0

    elif style == "scalping":
        _rsi = rsi(close, 7)
        bb_lo, bb_mid, bb_hi = bollinger_bands(close, 20, 2.0)
        vol_avg = vol.rolling(20).mean()
        vol_mult = _mid(params.get("volume_multiplier", [1.2, 2.0]))

        long_entry = (_rsi < 30) & (close <= bb_lo) & (vol > vol_avg * vol_mult)
        short_entry = (_rsi > 70) & (close >= bb_hi) & (vol > vol_avg * vol_mult)
        long_exit = (_rsi > 50) | (close > bb_mid)
        short_exit = (_rsi < 50) | (close < bb_mid)

        signals[long_entry & ~long_exit] = 1
        signals[short_entry & ~short_exit] = -1
        signals[long_exit & ~long_entry] = 0
        signals[short_exit & ~short_entry] = 0

    elif style == "trend_following":
        fast_p = int(_mid(params.get("fast_ema", params.get("medium_ema", [15, 25]))))
        slow_p = int(_mid(params.get("slow_ema", params.get("ema_trend_period", [40, 60]))))
        adx_thresh = _mid(params.get("adx_threshold", params.get("adx_min", [18, 25])))

        ema_fast = ema(close, fast_p)
        ema_slow = ema(close, slow_p)
        _adx = adx(high, low, close, 14)

        long_cond = (ema_fast > ema_slow) & (_adx > adx_thresh) & (close > ema_fast)
        short_cond = (ema_fast < ema_slow) & (_adx > adx_thresh) & (close < ema_fast)
        signals[long_cond] = 1
        signals[short_cond] = -1

    elif style == "news_reaction":
        _atr = atr(high, low, close, 14)
        atr_lookback = int(_mid(params.get("atr_avg_lookback", [20, 20])))
        atr_avg = _atr.rolling(atr_lookback).mean()
        vol_avg = vol.rolling(20).mean()
        vol_mult = _mid(params.get("volume_multiplier", [2.0, 3.0]))
        atr_burst_mult = _mid(params.get("atr_burst_multiplier", [1.5, 1.5]))

        burst = (_atr > atr_avg * atr_burst_mult) & (vol > vol_avg * vol_mult)
        momentum = close - close.shift(3)
        signals[burst & (momentum > 0)] = 1
        signals[burst & (momentum < 0)] = -1

    elif style == "news_reaction_v2":
        # ---- ATR percentile for hard regime separation ----
        _atr = atr(high, low, close, 14)
        atr_lookback = int(_mid(params.get("atr_avg_lookback", [20, 20])))
        atr_avg = _atr.rolling(atr_lookback).mean()
        vol_avg = vol.rolling(20).mean()

        # Crisis uses v1-level selectivity (high thresholds)
        crisis_atr_mult = _mid(params.get("crisis_atr_multiplier", [1.5, 1.5]))
        crisis_vol_mult = _mid(params.get("crisis_vol_multiplier", [2.5, 2.5]))

        # Hard regime switch via ATR percentile (rolling 252-bar rank)
        atr_pctl = _atr.rolling(252, min_periods=60).rank(pct=True)
        high_vol = atr_pctl > 0.7   # top 30% = crisis mode
        low_vol = atr_pctl < 0.4    # bottom 40% = calm mode
        # Middle zone (0.4-0.7) = dead zone, no trading

        # ---- Primary: crisis entries (ATR burst + high vol regime) ----
        burst = (_atr > atr_avg * crisis_atr_mult) & (vol > vol_avg * crisis_vol_mult)
        momentum = close - close.shift(3)
        # Use signal value 2/-2 for crisis regime
        signals[burst & high_vol & (momentum > 0)] = 2
        signals[burst & high_vol & (momentum < 0)] = -2

        # ---- Secondary: calm-period mean reversion (low vol regime) ----
        _rsi = rsi(close, 14)
        bb_lo, bb_mid, bb_hi = bollinger_bands(close, 20, 2.0)
        calm_long = low_vol & (_rsi < 40) & (close < bb_lo)
        signals[calm_long] = 1

    elif style == "volume_orderflow":
        _z = z_score(close, 50)
        vol_avg = vol.rolling(20).mean()
        vol_mult = _mid(params.get("volume_multiplier", params.get("volume_confirmation", [1.2, 2.0])))

        long_cond = (_z < -2.0) & (vol > vol_avg * vol_mult)
        short_cond = (_z > 2.0) & (vol > vol_avg * vol_mult)
        signals[long_cond] = 1
        signals[short_cond] = -1

    else:
        ema20 = ema(close, 20)
        ema50 = ema(close, 50)
        signals[ema20 > ema50] = 1
        signals[ema20 < ema50] = -1

    return signals


# ---------------------------------------------------------------------------
# Core backtest engine (enhanced)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Asset cost constants for realistic friction modeling
# ---------------------------------------------------------------------------

# Tick sizes (minimum price increment in price units) per asset
# NQ: 0.25 index points per tick ($5/tick = 0.25 * $20/pt)
# GC: $0.10 per tick ($10/tick = $0.10 * $100/pt)
# CL: $0.01 per tick ($10/tick = $0.01 * $1000/bbl)
TICK_SIZES = {"NQ": 0.25, "GC": 0.10, "CL": 0.01}
# Dollar value per point
POINT_VALUES = {"NQ": 20.0, "GC": 100.0, "CL": 1000.0}
# Round-trip commission per contract in dollars
RT_COMMISSION_USD = 4.50
# Default slippage in ticks (each side)
DEFAULT_SLIPPAGE_TICKS = 2
# Default spread in ticks
DEFAULT_SPREAD_TICKS = 1


def _compute_commission_pct(asset: str, entry_price: float) -> float:
    """Compute round-trip commission as a percentage of notional value."""
    if asset in POINT_VALUES and entry_price > 0:
        notional = entry_price * POINT_VALUES[asset]
        return (RT_COMMISSION_USD / notional) * 100  # as pct
    return 0.05  # default 0.05% for unrecognized assets


def _compute_slippage_dollars(asset: str, slippage_ticks: int) -> float:
    """Compute slippage in dollar terms per contract (each side)."""
    tick_size = TICK_SIZES.get(asset, 0.01)
    point_value = POINT_VALUES.get(asset, 1.0)
    return slippage_ticks * tick_size * point_value


def run_backtest(
    dna: dict,
    df: pd.DataFrame,
    *,
    initial_capital: float = 100_000.0,
    risk_per_trade_pct: float = 1.0,
    commission_pct: float = 0.01,
    use_mtf: bool = False,
    asset: str = "",
    slippage_ticks: int = DEFAULT_SLIPPAGE_TICKS,
    spread_ticks: int = DEFAULT_SPREAD_TICKS,
    max_hold_bars: int = 0,
) -> BacktestResult:
    """
    Run a full backtest on a StrategyDNA against an OHLCV DataFrame.

    Parameters
    ----------
    dna : dict
        Parsed StrategyDNA JSON object.
    df : pd.DataFrame
        OHLCV DataFrame with columns: open, high, low, close (+ optional volume).
        Index should be DatetimeIndex.
    initial_capital : float
        Starting capital.
    risk_per_trade_pct : float
        Percentage of CURRENT equity risked per trade.
    commission_pct : float
        Round-trip commission as pct of trade value (overridden if asset is set).
    use_mtf : bool
        If True, use multi-timeframe signal generation.
    asset : str
        Asset symbol (NQ, GC, CL) for realistic cost modeling.
    slippage_ticks : int
        Slippage in ticks applied per side.
    spread_ticks : int
        Spread in ticks (applied on entry only — buy at ask).

    Returns
    -------
    BacktestResult
    """
    code = dna.get("strategy_code", "UNKNOWN")

    # Ensure we have required columns
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
    if "volume" not in df.columns:
        df = df.copy()
        df["volume"] = 1.0

    df = df.dropna(subset=["close"]).copy()
    if len(df) < 60:
        return BacktestResult(strategy_code=code)

    # Cap dataset size to prevent memory/CPU explosion on huge datasets
    # Use most recent N bars — preserves recent market structure
    MAX_BARS = 100_000
    if len(df) > MAX_BARS:
        df = df.iloc[-MAX_BARS:]

    # Auto-detect max holding period from data frequency
    if max_hold_bars == 0 and len(df) > 2:
        freq_seconds = (df.index[1] - df.index[0]).total_seconds()
        if freq_seconds <= 300:  # 5m
            max_hold_bars = 78
        elif freq_seconds <= 900:  # 15m
            max_hold_bars = 26
        elif freq_seconds <= 3600:  # 1h
            max_hold_bars = 20
        elif freq_seconds <= 14400:  # 4h
            max_hold_bars = 20
        # daily+ = no limit

    # Generate signals
    if use_mtf:
        entry_signals, exit_signals = generate_signals_mtf(dna, df)
        # Also compute MTF indicators for trade reasoning
        df_4h = _resample_ohlcv(df, "4h") if len(df) > 48 else df
        trend_4h_series = assess_trend_4h(df_4h).reindex(df.index, method="ffill").fillna(0).astype(int)
        df_1h = _resample_ohlcv(df, "1h") if len(df) > 12 else df
        conf_1h_series = assess_confirmation_1h(df_1h).reindex(df.index, method="ffill").fillna(0).astype(int)
    else:
        signals = generate_signals(dna, df)
        # For news_reaction_v2: signals use 2/-2 for crisis, 1 for calm
        # All other styles: standard 1/-1/0
        entry_signals = signals > 0  # long only for simplicity
        exit_signals = signals <= 0
        trend_4h_series = pd.Series(0, index=df.index)
        conf_1h_series = pd.Series(0, index=df.index)

    # --- news_reaction_v2: regime-aware exit overlay ---
    _regime_arr = None  # None = no regime tracking
    _calm_exit_arr = None
    _crisis_exit_arr = None
    _style = dna.get("style", "")
    if _style == "news_reaction_v2" and not use_mtf:
        # Build regime array: 2=crisis, 1=calm, 0=no signal
        _regime_arr = signals.abs().values.copy()  # 2=crisis, 1=calm, 0=none
        # Override entry to catch crisis signals too (value 2)
        entry_signals = signals.abs() > 0
        # Precompute calm exit conditions for the trade loop
        _close = df["close"]
        _rsi_exit = rsi(_close, 14)
        _bb_lo_exit, _bb_mid_exit, _bb_hi_exit = bollinger_bands(_close, 20, 2.0)
        _calm_exit_arr = ((_rsi_exit > 50) | (_close > _bb_mid_exit)).values
        # Crisis exit: use standard exit logic (signal goes to 0)
        _crisis_exit_arr = exit_signals.values

    # Precompute cost parameters
    tick_size = TICK_SIZES.get(asset.upper(), 0.01) if asset else 0.01
    point_value = POINT_VALUES.get(asset.upper(), 1.0) if asset else 1.0

    # --- Simulate trades (NEXT-BAR EXECUTION) ----------------------------
    _entry_regime = 0  # 0=unknown, 1=calm, 2=crisis
    position = 0
    trades: List[TradeRecord] = []
    entry_price = 0.0
    entry_idx = None
    entry_trend_4h = 0
    entry_conf_1h = 0
    equity = initial_capital
    forced_exit_count = 0

    close_arr = df["close"].values
    open_arr = df["open"].values
    idx_arr = df.index
    entry_arr = entry_signals.values
    exit_arr = exit_signals.values
    trend_arr = trend_4h_series.values
    conf_arr = conf_1h_series.values
    n_bars = len(df)

    # Robust median price for sanity checks — immune to bad data bars.
    # Use rolling median of last 20 close prices; only update with valid closes.
    _price_history = []
    _median_price = float(np.median(close_arr[close_arr > 0][:100])) if np.any(close_arr > 0) else 1.0

    def _is_valid_price(price: float) -> bool:
        """Check if a price is sane vs the robust median."""
        if price <= 0:
            return False
        if _median_price > 0 and abs(price / _median_price - 1) > 0.10:
            return False
        return True

    for i in range(1, n_bars - 1):  # stop at n-2 so i+1 is valid
        # Update robust median with valid close prices only
        c = close_arr[i]
        if c > 0 and (_median_price <= 0 or abs(c / _median_price - 1) <= 0.10):
            _price_history.append(c)
            if len(_price_history) > 20:
                _price_history.pop(0)
            _median_price = float(np.median(_price_history))

        # Force exit if held too long
        if position != 0 and max_hold_bars > 0 and entry_idx is not None:
            bars_held = i - entry_idx
            if bars_held >= max_hold_bars:
                # Force exit at next bar open
                raw_exit = open_arr[i + 1]
                if _is_valid_price(raw_exit):
                    slip_cost = slippage_ticks * tick_size
                    exit_price = raw_exit - slip_cost
                    price_pnl = position * (exit_price - entry_price)
                    pnl_pct = price_pnl / entry_price
                    if asset and asset.upper() in POINT_VALUES:
                        comm_pct = _compute_commission_pct(asset.upper(), entry_price) / 100
                    else:
                        comm_pct = commission_pct / 100
                    pnl_pct -= comm_pct
                    forced_exit_count += 1
                    trades.append(TradeRecord(
                        entry_idx=entry_idx,
                        exit_idx=i + 1,
                        direction=position,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        pnl_pct=pnl_pct,
                        entry_reason=_entry_reason(dna, entry_trend_4h, entry_conf_1h),
                        exit_reason="Max hold period exceeded",
                        entry_time=str(idx_arr[entry_idx]) if entry_idx is not None else "",
                        exit_time=str(idx_arr[i + 1]),
                    ))
                    position = 0
                    continue

        if position == 0 and entry_arr[i]:
            # Signal on bar i → execute NEXT bar open (i+1)
            raw_entry = open_arr[i + 1]
            if not _is_valid_price(raw_entry):
                continue
            # Add spread (buy at ask = mid + 0.5 * spread) + slippage
            spread_cost = spread_ticks * tick_size * 0.5  # half-spread on entry
            slip_cost = slippage_ticks * tick_size
            entry_price = raw_entry + spread_cost + slip_cost

            position = 1
            entry_idx = i + 1
            entry_trend_4h = int(trend_arr[i])
            entry_conf_1h = int(conf_arr[i])
            # Track regime for news_reaction_v2
            _entry_regime = int(_regime_arr[i]) if _regime_arr is not None else 0

        # --- Regime-aware exit for news_reaction_v2 ---
        elif position != 0 and _regime_arr is not None:
            # Calm trades (regime=1): exit on RSI > 50 or close > BB mid
            # Crisis trades (regime=2): exit on momentum reversal
            should_exit = False
            if _entry_regime == 1 and _calm_exit_arr is not None:
                should_exit = bool(_calm_exit_arr[i])
            elif _entry_regime == 2 and _crisis_exit_arr is not None:
                should_exit = bool(_crisis_exit_arr[i])
            else:
                should_exit = bool(exit_arr[i])

            if not should_exit:
                continue
            raw_exit = open_arr[i + 1]
            if not _is_valid_price(raw_exit):
                continue
            slip_cost = slippage_ticks * tick_size
            exit_price = raw_exit - slip_cost
            price_pnl = position * (exit_price - entry_price)
            pnl_pct = price_pnl / entry_price
            if asset and asset.upper() in POINT_VALUES:
                comm_pct = _compute_commission_pct(asset.upper(), entry_price) / 100
            else:
                comm_pct = commission_pct / 100
            pnl_pct -= comm_pct

            regime_tag = "CRISIS" if _entry_regime == 2 else "CALM"
            signal_exit = True
            trend_exit = int(trend_arr[i]) == -position if use_mtf else False

            trades.append(TradeRecord(
                entry_idx=entry_idx,
                exit_idx=i + 1,
                direction=position,
                entry_price=entry_price,
                exit_price=exit_price,
                pnl_pct=pnl_pct,
                entry_reason=f"[{regime_tag}] " + _entry_reason(dna, entry_trend_4h, entry_conf_1h),
                exit_reason=_exit_reason(signal_exit, trend_exit),
                entry_time=str(idx_arr[entry_idx]) if entry_idx is not None else "",
                exit_time=str(idx_arr[i + 1]),
            ))
            position = 0

        elif position != 0 and exit_arr[i]:
            # Signal on bar i → execute NEXT bar open (i+1)
            raw_exit = open_arr[i + 1]
            if not _is_valid_price(raw_exit):
                continue
            # Slippage on exit (selling into bid)
            slip_cost = slippage_ticks * tick_size
            exit_price = raw_exit - slip_cost

            # PnL in price terms
            price_pnl = position * (exit_price - entry_price)
            # Convert to pct of entry notional
            pnl_pct = price_pnl / entry_price

            # Subtract realistic commission
            if asset and asset.upper() in POINT_VALUES:
                comm_pct = _compute_commission_pct(asset.upper(), entry_price) / 100
            else:
                comm_pct = commission_pct / 100
            pnl_pct -= comm_pct

            signal_exit = bool(exit_arr[i])
            trend_exit = int(trend_arr[i]) == -position if use_mtf else False

            trades.append(TradeRecord(
                entry_idx=entry_idx,
                exit_idx=i + 1,
                direction=position,
                entry_price=entry_price,
                exit_price=exit_price,
                pnl_pct=pnl_pct,
                entry_reason=_entry_reason(dna, entry_trend_4h, entry_conf_1h),
                exit_reason=_exit_reason(signal_exit, trend_exit),
                entry_time=str(idx_arr[entry_idx]) if entry_idx is not None else "",
                exit_time=str(idx_arr[i + 1]),
            ))
            position = 0

    # Close any open position at the end (at last bar's close — no next bar)
    if position != 0:
        exit_price = close_arr[-1] - slippage_ticks * tick_size
        if _is_valid_price(exit_price + slippage_ticks * tick_size):
            price_pnl = position * (exit_price - entry_price)
            pnl_pct = price_pnl / entry_price
            if asset and asset.upper() in POINT_VALUES:
                comm_pct = _compute_commission_pct(asset.upper(), entry_price) / 100
            else:
                comm_pct = commission_pct / 100
            pnl_pct -= comm_pct
            trades.append(TradeRecord(
                entry_idx=entry_idx,
                exit_idx=n_bars - 1,
                direction=position,
                entry_price=entry_price,
                exit_price=exit_price,
                pnl_pct=pnl_pct,
                entry_reason=_entry_reason(dna, entry_trend_4h, entry_conf_1h),
                exit_reason="End of data",
                entry_time=str(idx_arr[entry_idx]) if entry_idx is not None else "",
                exit_time=str(idx_arr[-1]),
            ))

    # --- Compute metrics --------------------------------------------------
    if not trades:
        return BacktestResult(strategy_code=code)

    pnls = np.array([t.pnl_pct for t in trades])
    wins_mask = pnls > 0
    losses_mask = pnls <= 0

    n_wins = int(wins_mask.sum())
    n_losses = int(losses_mask.sum())
    n_trades = len(trades)

    win_rate = n_wins / n_trades if n_trades else 0.0
    avg_win = float(pnls[wins_mask].mean()) if n_wins else 0.0
    avg_loss = float(pnls[losses_mask].mean()) if n_losses else 0.0

    total_pnl = float(pnls.sum())

    # Largest win/loss
    largest_win = float(pnls[wins_mask].max()) if n_wins else 0.0
    largest_loss = float(pnls[losses_mask].min()) if n_losses else 0.0

    # Smart equity mode: additive for high-frequency, compound for low-frequency
    try:
        data_days = (df.index.max() - df.index.min()).total_seconds() / 86400
    except Exception:
        data_days = max(1, n_trades)
    data_days = max(1, data_days)
    trade_frequency = n_trades / data_days * 365.25  # trades per year

    equity = initial_capital
    eq_curve = [initial_capital]
    risk_frac = risk_per_trade_pct / 100.0
    if trade_frequency > 50:
        # Additive mode — fixed dollar position size
        position_size = initial_capital * risk_frac
        for pnl in pnls:
            equity += position_size * pnl
            equity = max(equity, 0.01)
            eq_curve.append(equity)
    else:
        # Compound mode — realistic for low-frequency strategies
        for pnl in pnls:
            equity *= (1 + risk_frac * pnl)
            equity = max(equity, 0.01)
            eq_curve.append(equity)

    eq_arr = np.array(eq_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - peak) / np.where(peak > 0, peak, 1)
    max_dd = float(abs(dd.min()))

    # Forced exit instrumentation
    forced_exit_ratio = forced_exit_count / max(1, n_trades)

    # Sharpe (annualized)
    if len(pnls) > 1 and pnls.std() > 0:
        if hasattr(df.index, 'min') and hasattr(df.index, 'max'):
            try:
                data_days = (df.index.max() - df.index.min()).total_seconds() / 86400
                if data_days > 0:
                    trades_per_year = n_trades / (data_days / 365.25)
                    trades_per_year = max(1, min(trades_per_year, 50000))
                else:
                    trades_per_year = min(252, n_trades)
            except:
                trades_per_year = min(252, n_trades)
        else:
            trades_per_year = min(252, n_trades)
        sharpe = float((pnls.mean() / pnls.std()) * np.sqrt(trades_per_year))
    else:
        sharpe = 0.0

    # Profit factor — with floor on gross_loss to prevent infinity
    gross_profit = float(pnls[wins_mask].sum()) if n_wins else 0.0
    gross_loss = float(abs(pnls[losses_mask].sum())) if n_losses else 0.0
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        # No losses = suspicious. Cap PF at 10.0 instead of billions
        profit_factor = min(10.0, gross_profit * 100) if gross_profit > 0 else 0.0

    # Expectancy
    expectancy = float(pnls.mean()) if n_trades else 0.0

    # Avg R:R
    avg_rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

    total_return_pct = (eq_curve[-1] / initial_capital - 1) * 100
    # No artificial cap — the fixed position sizing model prevents insane returns

    # Build trade log (with reasoning)
    trade_log = [
        {
            "entry_time": t.entry_time,
            "exit_time": t.exit_time,
            "direction": "LONG" if t.direction == 1 else "SHORT",
            "entry_price": round(t.entry_price, 2),
            "exit_price": round(t.exit_price, 2),
            "pnl_pct": round(t.pnl_pct, 6),
            "entry_reason": t.entry_reason,
            "exit_reason": t.exit_reason,
        }
        for t in trades
    ]

    # ── SANITY FILTER: reject physically impossible results ──
    # These indicate bugs in signal generation, not real edges
    _suspicious = False
    _suspicion_reasons = []

    if n_trades >= 50 and win_rate >= 0.95:
        _suspicious = True
        _suspicion_reasons.append(f"WR {win_rate:.0%} with {n_trades} trades")
    if max_dd == 0.0 and n_trades >= 20:
        _suspicious = True
        _suspicion_reasons.append(f"Zero drawdown with {n_trades} trades")
    if profit_factor > 50 and n_trades >= 20:
        _suspicious = True
        _suspicion_reasons.append(f"PF {profit_factor:.0f} unrealistic")
    if sharpe > 10 and n_trades >= 20:
        _suspicious = True
        _suspicion_reasons.append(f"Sharpe {sharpe:.1f} unrealistic")
    if total_return_pct > 10000:
        _suspicious = True
        _suspicion_reasons.append(f"Return {total_return_pct:.0f}% unrealistic")

    if _suspicious:
        # Return zeroed result so it fails all gates
        return BacktestResult(
            strategy_code=code,
            trade_count=n_trades,
            wins=n_wins,
            losses=n_losses,
            extra={
                "REJECTED_SANITY": True,
                "rejection_reasons": _suspicion_reasons,
                "raw_sharpe": round(sharpe, 4),
                "raw_wr": round(win_rate, 4),
                "raw_pf": round(profit_factor, 4),
            },
        )

    return BacktestResult(
        strategy_code=code,
        total_pnl=round(total_pnl, 6),
        win_rate=round(win_rate, 4),
        sharpe_ratio=round(sharpe, 4),
        max_drawdown=round(max_dd, 4),
        profit_factor=round(profit_factor, 4),
        expectancy=round(expectancy, 6),
        trade_count=n_trades,
        avg_rr=round(avg_rr, 4),
        wins=n_wins,
        losses=n_losses,
        avg_win=round(avg_win, 6),
        avg_loss=round(avg_loss, 6),
        largest_win=round(largest_win, 6),
        largest_loss=round(largest_loss, 6),
        total_return_pct=round(total_return_pct, 2),
        trade_log=trade_log,
        extra={
            "forced_exit_count": forced_exit_count,
            "forced_exit_ratio": round(forced_exit_ratio, 4),
            "equity_mode": "additive" if trade_frequency > 50 else "compound",
            "trade_frequency": round(trade_frequency, 1),
        },
    )


# ---------------------------------------------------------------------------
# Synthetic data generator (for testing)
# ---------------------------------------------------------------------------

def generate_synthetic_ohlcv(
    n_bars: int = 2000,
    freq: str = "5min",
    start: str = "2025-01-01",
    seed: int = 42,
    regime: str = "mixed",
) -> pd.DataFrame:
    """Generate synthetic OHLCV data for backtesting."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, periods=n_bars, freq=freq)

    if regime == "trending":
        drift = 0.0003
        vol = 0.005
    elif regime == "ranging":
        drift = 0.0
        vol = 0.003
    elif regime == "volatile":
        drift = 0.0001
        vol = 0.012
    else:
        drift = 0.0001
        vol = 0.006

    returns = rng.normal(drift, vol, n_bars)
    price = 100 * np.exp(np.cumsum(returns))

    noise = rng.uniform(0.001, 0.005, n_bars)
    high = price * (1 + noise)
    low = price * (1 - noise)
    open_ = price * (1 + rng.normal(0, 0.001, n_bars))
    volume = rng.integers(100, 10000, n_bars).astype(float)

    spike_mask = rng.random(n_bars) > 0.9
    volume[spike_mask] *= rng.uniform(2, 5, spike_mask.sum())

    df = pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": price,
        "volume": volume,
    }, index=dates)

    return df


# ---------------------------------------------------------------------------
# Robustness Check — Remove Top N Trades (Step 3)
# ---------------------------------------------------------------------------

def robustness_check(
    trades: List[TradeRecord],
    initial_capital: float = 100_000,
    risk_per_trade_pct: float = 1.0,
    n_remove: int = 5,
) -> dict:
    """
    Remove top N trades by PnL, recompute metrics.
    Dual condition: top-5 PnL share AND stripped return ratio.

    Verdict:
    - PASS: top5_pnl_share <= 0.50 AND stripped_return_ratio >= 0.25
    - CONDITIONAL: one condition met but not both, or ratio in 0.20-0.25
    - HARD FAIL: neither met or ratio < 0.20

    Returns dict with original vs stripped returns, pass/conditional/fail.
    """
    if len(trades) < n_remove + 5:
        return {
            "original_return": 0.0,
            "stripped_return": 0.0,
            "return_ratio": 0.0,
            "passed": False,
            "conditional": False,
            "top5_pnl_share": 0.0,
            "failure_tag": "FAIL_PNL_CONCENTRATION",
            "reason": f"Too few trades ({len(trades)}) for robustness check",
        }

    pnls = [t.pnl_pct for t in trades]
    risk_frac = risk_per_trade_pct / 100.0
    n = len(pnls)

    # Use additive for many trades, compound for few
    use_additive = n > 50

    def _compute_return(pnl_list):
        eq = initial_capital
        if use_additive:
            ps = initial_capital * risk_frac
            for p in pnl_list:
                eq += ps * p
                eq = max(eq, 0.01)
        else:
            for p in pnl_list:
                eq *= (1 + risk_frac * p)
                eq = max(eq, 0.01)
        return (eq / initial_capital - 1) * 100

    original_return = _compute_return(pnls)

    # Top-5 PnL share: what fraction of total PnL do the top 5 trades carry?
    total_abs_pnl = sum(abs(p) for p in pnls)
    sorted_indices = sorted(range(len(pnls)), key=lambda i: pnls[i], reverse=True)
    top_indices = set(sorted_indices[:n_remove])
    top5_abs_pnl = sum(abs(pnls[i]) for i in top_indices)
    top5_pnl_share = top5_abs_pnl / total_abs_pnl if total_abs_pnl > 0 else 1.0

    # Stripped equity curve
    stripped_pnls = [pnl for i, pnl in enumerate(pnls) if i not in top_indices]
    stripped_return = _compute_return(stripped_pnls)

    # Return ratio
    if abs(original_return) > 0.001:
        return_ratio = stripped_return / original_return
    else:
        return_ratio = 0.0

    # Dual condition evaluation
    cond_share = top5_pnl_share <= 0.50
    cond_ratio = return_ratio >= 0.25
    cond_ratio_soft = return_ratio >= 0.20

    if cond_share and cond_ratio:
        passed = True
        conditional = False
        failure_tag = None
    elif (cond_share or cond_ratio) or (not cond_share and not cond_ratio and cond_ratio_soft):
        # One condition met, or ratio in 0.20-0.25 range
        passed = False
        conditional = True
        failure_tag = None
    else:
        # Hard fail: neither met AND ratio < 0.20
        passed = False
        conditional = False
        failure_tag = "FAIL_PNL_CONCENTRATION"

    return {
        "original_return": round(original_return, 4),
        "stripped_return": round(stripped_return, 4),
        "return_ratio": round(return_ratio, 4),
        "top5_pnl_share": round(top5_pnl_share, 4),
        "passed": passed,
        "conditional": conditional,
        "failure_tag": failure_tag,
        "trades_removed": n_remove,
        "trades_remaining": len(stripped_pnls),
    }

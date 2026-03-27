#!/usr/bin/env python3
"""
Darwin Full 16-Year Backtest — 6 Gen3 Strategies on CL
Implements: MTF logic, regime gating, confirmation stacking, trade quality gate,
partial exits, regime testing, full metrics, trade logging with reasoning.
"""

import json
import sys
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Tuple, Optional

import numpy as np
import pandas as pd

# Add project root
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from services.darwin.backtester import (
    load_parquet, ema, sma, rsi, atr, adx, bollinger_bands, z_score,
    _resample_ohlcv, _mid
)

# ── Config ─────────────────────────────────────────────────────────────────
STRATEGIES_TO_TEST = [
    "TF-G3-001", "TF-G3-002", "TF-G3-003", "TF-G3-004",
    "MOM-G3-001", "MOM-G3-003"
]

INITIAL_CAPITAL = 100_000.0
RISK_PER_TRADE = 0.01  # 1% risk
COMMISSION_PCT = 0.01  # 0.01% round trip
POINT_VALUE = 1000     # CL crude oil $1000/point

DARWIN_CRITERIA = {
    "min_win_rate": 0.40,
    "min_sharpe": 0.5,
    "max_drawdown": 0.10,
    "min_regimes_profitable": 2,
}

OUTPUT_PATH = PROJECT / "data" / "darwin_full_backtest_results.json"
DNA_PATH = PROJECT / "data" / "strategy_dnas_v3.json"

# ── Indicator Helpers ──────────────────────────────────────────────────────

def macd(series, fast=12, slow=26, signal=9):
    ef = ema(series, fast)
    es = ema(series, slow)
    macd_line = ef - es
    sig_line = ema(macd_line, signal)
    hist = macd_line - sig_line
    return macd_line, sig_line, hist

def donchian(high, low, period=20):
    upper = high.rolling(period).max()
    lower = low.rolling(period).min()
    return upper, lower

def fibonacci_levels(swing_high, swing_low):
    """Return key fib levels from a swing."""
    diff = swing_high - swing_low
    return {
        0.236: swing_high - 0.236 * diff,
        0.382: swing_high - 0.382 * diff,
        0.500: swing_high - 0.500 * diff,
        0.618: swing_high - 0.618 * diff,
        0.786: swing_high - 0.786 * diff,
    }

def stochastic(close, high, low, k_period=14, d_period=3):
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d

# ── Regime Classification ─────────────────────────────────────────────────

def classify_regimes(df: pd.DataFrame, adx_period=14, atr_period=14) -> pd.Series:
    """
    Classify each bar into: 'trending', 'ranging', 'volatile'
    Using ADX for trend strength and ATR percentile for volatility.
    """
    _adx = adx(df["high"], df["low"], df["close"], adx_period)
    _atr = atr(df["high"], df["low"], df["close"], atr_period)
    atr_pct = _atr.rolling(50).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)
    
    regime = pd.Series("ranging", index=df.index)
    
    # Trending: ADX > 25
    regime[_adx > 25] = "trending"
    
    # Volatile: ATR in top 25th percentile AND ADX < 25 (chaotic, not trending)
    volatile_mask = (atr_pct > 0.75) & (_adx < 25)
    regime[volatile_mask] = "volatile"
    
    # Override: very strong ADX always trending
    regime[_adx > 35] = "trending"
    
    return regime

# ── Confirmation Stacking ─────────────────────────────────────────────────

def compute_confirmation_score(
    close, high, low, volume,
    ema20, ema50, _adx, _rsi, _atr,
    direction=1  # 1=long, -1=short
) -> pd.Series:
    """
    5-check confirmation stacking:
    1. trend_aligned (EMA20 vs EMA50)
    2. structure_confirmed (HH/HL for long)
    3. momentum_confirmed (RSI alignment)
    4. volume_confirmed (above average)
    5. vwap_confirmed (approx: price vs rolling VWAP proxy)
    Returns score 0-5 per bar.
    """
    score = pd.Series(0.0, index=close.index)
    
    # 1. Trend aligned
    if direction == 1:
        score += (ema20 > ema50).astype(float)
    else:
        score += (ema20 < ema50).astype(float)
    
    # 2. Structure confirmed (higher high in last 10 bars for long)
    hh = high.rolling(10).max()
    ll = low.rolling(10).min()
    prev_hh = high.shift(10).rolling(10).max()
    prev_ll = low.shift(10).rolling(10).min()
    if direction == 1:
        score += ((hh > prev_hh) & (ll > prev_ll)).astype(float)
    else:
        score += ((ll < prev_ll) & (hh < prev_hh)).astype(float)
    
    # 3. Momentum confirmed
    if direction == 1:
        score += (_rsi > 50).astype(float)
    else:
        score += (_rsi < 50).astype(float)
    
    # 4. Volume confirmed
    vol_avg = volume.rolling(20).mean()
    score += (volume > vol_avg).astype(float)
    
    # 5. VWAP proxy (typical price * volume cumulative)
    tp = (high + low + close) / 3
    cum_tpv = (tp * volume).rolling(20).sum()
    cum_v = volume.rolling(20).sum().replace(0, np.nan)
    vwap_proxy = cum_tpv / cum_v
    if direction == 1:
        score += (close > vwap_proxy).astype(float)
    else:
        score += (close < vwap_proxy).astype(float)
    
    return score

# ── Trade Quality Gate ────────────────────────────────────────────────────

def compute_trade_quality(
    _adx, close, ema20, volume, _atr, direction=1
) -> pd.Series:
    """
    Trade quality score 0-1 based on 4 dimensions:
    - trend_strength (0.25): ADX normalized
    - breakout_strength (0.25): price distance from EMA
    - volume_confirmation (0.25): volume vs average
    - alignment_score (0.25): directional consistency
    """
    # Trend strength: ADX / 50 capped at 1
    trend_s = (_adx / 50).clip(0, 1) * 0.25
    
    # Breakout strength: distance from EMA20 normalized by ATR
    dist = ((close - ema20) / _atr.replace(0, np.nan)).abs()
    breakout_s = dist.clip(0, 2) / 2 * 0.25
    
    # Volume confirmation
    vol_ratio = volume / volume.rolling(20).mean().replace(0, np.nan)
    vol_s = vol_ratio.clip(0, 3) / 3 * 0.25
    
    # Alignment: how many of last 5 bars moved in direction
    if direction == 1:
        aligned = (close.diff() > 0).rolling(5).mean()
    else:
        aligned = (close.diff() < 0).rolling(5).mean()
    align_s = aligned * 0.25
    
    return (trend_s + breakout_s + vol_s + align_s).fillna(0)

# ── Partial Exit P&L Calculator ───────────────────────────────────────────

def calc_partial_exit_pnl(
    entry_price: float, 
    direction: int,
    subsequent_prices: np.ndarray,
    subsequent_highs: np.ndarray,
    subsequent_lows: np.ndarray,
    stop_distance: float,
    exit_rules: dict,
    time_limit: int = 15,
) -> Tuple[float, int, str]:
    """
    Simulate partial exits: 1/3 at 1R, 1/3 at 2R, 1/3 runner with 2 ATR trail.
    Returns (total_pnl_pct, bars_held, exit_reason)
    """
    if len(subsequent_prices) == 0:
        return 0.0, 0, "no_data"
    
    R = stop_distance  # 1R = stop distance in price
    if R <= 0:
        R = entry_price * 0.015  # fallback 1.5%
    
    # Partial sizes
    p1_size = 1/3
    p2_size = 1/3
    runner_size = 1/3
    
    total_pnl = 0.0
    p1_closed = False
    p2_closed = False
    runner_closed = False
    
    # Trailing stop for runner
    if direction == 1:
        trail_stop = entry_price - R  # initial stop
        best_price = entry_price
    else:
        trail_stop = entry_price + R
        best_price = entry_price
    
    trail_atr_mult = exit_rules.get("runner", {}).get("trailing_atr", 2.0)
    breakeven_r = exit_rules.get("breakeven_at_r", 0.75)
    
    exit_reason_parts = []
    bars_held = 0
    
    for i in range(min(len(subsequent_prices), time_limit)):
        price = subsequent_prices[i]
        hi = subsequent_highs[i]
        lo = subsequent_lows[i]
        bars_held = i + 1
        
        if direction == 1:
            current_r = (price - entry_price) / R if R > 0 else 0
            max_r = (hi - entry_price) / R if R > 0 else 0
            
            # Check stop loss first
            if lo <= entry_price - R and not p1_closed:
                # Full stop out
                total_pnl = -R / entry_price
                return total_pnl, bars_held, "stop_loss_hit"
            
            # Update best price for trailing
            if hi > best_price:
                best_price = hi
                trail_stop = best_price - trail_atr_mult * R
            
            # Partial 1: 1R hit
            if not p1_closed and max_r >= 1.0:
                total_pnl += p1_size * (1.0 * R) / entry_price
                p1_closed = True
                exit_reason_parts.append("P1@1R")
                # Move stop to breakeven
                trail_stop = max(trail_stop, entry_price)
            
            # Partial 2: 2R hit
            if not p2_closed and max_r >= 2.0:
                total_pnl += p2_size * (2.0 * R) / entry_price
                p2_closed = True
                exit_reason_parts.append("P2@2R")
            
            # Runner: trail stop hit
            if p1_closed and not runner_closed:
                if lo <= trail_stop:
                    runner_pnl = (trail_stop - entry_price) / entry_price
                    if not p2_closed:
                        total_pnl += (p2_size + runner_size) * runner_pnl
                    else:
                        total_pnl += runner_size * runner_pnl
                    runner_closed = True
                    exit_reason_parts.append(f"trail@{trail_stop:.2f}")
                    return total_pnl, bars_held, " | ".join(exit_reason_parts)
            
            # Breakeven stop
            if not p1_closed and current_r >= breakeven_r:
                trail_stop = max(trail_stop, entry_price)
                
        else:  # short
            current_r = (entry_price - price) / R if R > 0 else 0
            max_r = (entry_price - lo) / R if R > 0 else 0
            
            if hi >= entry_price + R and not p1_closed:
                total_pnl = -R / entry_price
                return total_pnl, bars_held, "stop_loss_hit"
            
            if lo < best_price:
                best_price = lo
                trail_stop = best_price + trail_atr_mult * R
            
            if not p1_closed and max_r >= 1.0:
                total_pnl += p1_size * (1.0 * R) / entry_price
                p1_closed = True
                exit_reason_parts.append("P1@1R")
                trail_stop = min(trail_stop, entry_price)
            
            if not p2_closed and max_r >= 2.0:
                total_pnl += p2_size * (2.0 * R) / entry_price
                p2_closed = True
                exit_reason_parts.append("P2@2R")
            
            if p1_closed and not runner_closed:
                if hi >= trail_stop:
                    runner_pnl = (entry_price - trail_stop) / entry_price
                    if not p2_closed:
                        total_pnl += (p2_size + runner_size) * runner_pnl
                    else:
                        total_pnl += runner_size * runner_pnl
                    runner_closed = True
                    exit_reason_parts.append(f"trail@{trail_stop:.2f}")
                    return total_pnl, bars_held, " | ".join(exit_reason_parts)
    
    # Time limit or end of data — close remaining at current price
    if not runner_closed:
        remaining_size = 0
        if not p1_closed:
            remaining_size = 1.0
        elif not p2_closed:
            remaining_size = p2_size + runner_size
        else:
            remaining_size = runner_size
        
        if remaining_size > 0:
            last_price = subsequent_prices[min(bars_held - 1, len(subsequent_prices) - 1)]
            if direction == 1:
                pnl = (last_price - entry_price) / entry_price
            else:
                pnl = (entry_price - last_price) / entry_price
            total_pnl += remaining_size * pnl
        
        exit_reason_parts.append(f"time_limit_{bars_held}bars")
    
    return total_pnl, bars_held, " | ".join(exit_reason_parts) if exit_reason_parts else "time_limit"


# ── Strategy-Specific Signal Generation ───────────────────────────────────

def gen_signals_tf001(df, dna):
    """TF-G3-001: EMA pullback in strong trends (ADX > 30)"""
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    
    e20 = ema(close, 20)
    e50 = ema(close, 50)
    _adx = adx(high, low, close, 14)
    _rsi = rsi(close, 14)
    _atr = atr(high, low, close, 14)
    
    # ADX > 30 regime gate
    regime_ok = _adx > 30
    
    # EMA alignment (uptrend)
    trend_up = (e20 > e50)
    
    # Pullback to 20 EMA (within 1.0 ATR for daily bars)
    near_ema = (close - e20).abs() < (_atr * 1.0)
    
    # RSI not overbought (35-60 zone — pullback zone for daily)
    rsi_ok = (_rsi > 35) & (_rsi < 60)
    
    # Volume declining on pullback (vol < 20-period avg)
    vol_avg = vol.rolling(20).mean()
    vol_declining = vol < vol_avg
    
    # Confirmation stack
    conf_score = compute_confirmation_score(close, high, low, vol, e20, e50, _adx, _rsi, _atr, direction=1)
    conf_ok = conf_score >= 3
    
    # Trade quality gate
    tq = compute_trade_quality(_adx, close, e20, vol, _atr, direction=1)
    tq_ok = tq >= 0.65
    
    # Entry: all conditions met (daily bars = looser confirmation for TF approximation)
    entries_long = regime_ok & trend_up & near_ema & rsi_ok & (conf_score >= 2) & (tq >= 0.45)
    
    # Short signals (mirror)
    trend_dn = (e20 < e50)
    near_ema_s = (e20 - close).abs() < (_atr * 0.5)
    rsi_ok_s = (_rsi > 45) & (_rsi < 60)
    conf_s = compute_confirmation_score(close, high, low, vol, e20, e50, _adx, _rsi, _atr, direction=-1)
    tq_s = compute_trade_quality(_adx, close, e20, vol, _atr, direction=-1)
    entries_short = regime_ok & trend_dn & near_ema_s & (conf_s >= 2) & (tq_s >= 0.45)
    
    direction = pd.Series(0, index=df.index)
    direction[entries_long] = 1
    direction[entries_short] = -1
    
    return direction, _atr, _adx, e20


def gen_signals_tf002(df, dna):
    """TF-G3-002: Donchian breakout with Chandelier trailing — ADX > 25"""
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    
    e50 = ema(close, 50)
    _adx = adx(high, low, close, 14)
    _rsi = rsi(close, 14)
    _atr = atr(high, low, close, 14)
    e20 = ema(close, 20)
    
    don_upper, don_lower = donchian(high, low, 20)
    
    regime_ok = _adx > 25
    
    # Donchian breakout
    breakout_long = (close > don_upper.shift(1)) & (close > e50)
    breakout_short = (close < don_lower.shift(1)) & (close < e50)
    
    # Volume expanding (relaxed for daily)
    vol_avg = vol.rolling(20).mean()
    vol_ok = vol > vol_avg * 1.0  # any above-average volume on daily
    
    conf_score = compute_confirmation_score(close, high, low, vol, e20, e50, _adx, _rsi, _atr, direction=1)
    tq = compute_trade_quality(_adx, close, e20, vol, _atr, direction=1)
    
    entries_long = regime_ok & breakout_long & vol_ok & (conf_score >= 2) & (tq >= 0.40)
    
    conf_s = compute_confirmation_score(close, high, low, vol, e20, e50, _adx, _rsi, _atr, direction=-1)
    tq_s = compute_trade_quality(_adx, close, e20, vol, _atr, direction=-1)
    entries_short = regime_ok & breakout_short & vol_ok & (conf_s >= 2) & (tq_s >= 0.40)
    
    direction = pd.Series(0, index=df.index)
    direction[entries_long] = 1
    direction[entries_short] = -1
    
    return direction, _atr, _adx, e20


def gen_signals_tf003(df, dna):
    """TF-G3-003: Fibonacci pullback continuation — ADX > 25, 2+ impulse legs"""
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    
    e20 = ema(close, 20)
    e50 = ema(close, 50)
    _adx = adx(high, low, close, 14)
    _rsi = rsi(close, 14)
    _atr = atr(high, low, close, 14)
    
    regime_ok = _adx > 25
    
    # Identify swing highs/lows (simplified: 20-bar rolling)
    swing_high = high.rolling(20).max()
    swing_low = low.rolling(20).min()
    prev_swing_high = high.shift(20).rolling(20).max()
    prev_swing_low = low.shift(20).rolling(20).min()
    
    # Fib retracement zone (38.2%-61.8% of prior impulse)
    impulse_range = swing_high - swing_low
    fib_382 = swing_high - 0.382 * impulse_range
    fib_618 = swing_high - 0.618 * impulse_range
    
    # Price in fib zone (long)
    in_fib_long = (close >= fib_618) & (close <= fib_382) & (e20 > e50)
    
    # 2+ impulse legs (simplified: higher highs)
    two_legs = swing_high > prev_swing_high
    
    # RSI not extended
    rsi_ok = (_rsi > 40) & (_rsi < 60)
    
    conf_score = compute_confirmation_score(close, high, low, vol, e20, e50, _adx, _rsi, _atr, direction=1)
    tq = compute_trade_quality(_adx, close, e20, vol, _atr, direction=1)
    
    entries_long = regime_ok & in_fib_long & two_legs & rsi_ok & (conf_score >= 2) & (tq >= 0.40)
    
    # Short mirror
    fib_382_s = swing_low + 0.382 * impulse_range
    fib_618_s = swing_low + 0.618 * impulse_range
    in_fib_short = (close <= fib_618_s) & (close >= fib_382_s) & (e20 < e50)
    two_legs_s = swing_low < prev_swing_low
    
    conf_s = compute_confirmation_score(close, high, low, vol, e20, e50, _adx, _rsi, _atr, direction=-1)
    tq_s = compute_trade_quality(_adx, close, e20, vol, _atr, direction=-1)
    entries_short = regime_ok & in_fib_short & two_legs_s & (conf_s >= 2) & (tq_s >= 0.40)
    
    direction = pd.Series(0, index=df.index)
    direction[entries_long] = 1
    direction[entries_short] = -1
    
    return direction, _atr, _adx, e20


def gen_signals_tf004(df, dna):
    """TF-G3-004: Multi-TF composite momentum — ADX > 25, weighted score > 0.75"""
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    
    e10 = ema(close, 10)
    e20 = ema(close, 20)
    e50 = ema(close, 50)
    _adx = adx(high, low, close, 14)
    _rsi = rsi(close, 14)
    _atr = atr(high, low, close, 14)
    
    # MACD components
    macd_line, macd_sig, macd_hist = macd(close, 12, 26, 9)
    macd_slow_line, macd_slow_sig, macd_slow_hist = macd(close, 26, 52, 9)
    
    # Composite score (simulate MTF with different periods)
    # 4h weight (slow) = 0.40
    score_4h = pd.Series(0.0, index=df.index)
    score_4h[e50 > e50.shift(1)] += 0.5  # EMA direction
    score_4h[macd_slow_hist > 0] += 0.5
    
    # 1h weight (medium) = 0.35
    score_1h = pd.Series(0.0, index=df.index)
    score_1h[e20 > e20.shift(1)] += 0.5
    score_1h[macd_hist > 0] += 0.5
    
    # 15m weight (fast) = 0.15
    score_15m = pd.Series(0.0, index=df.index)
    score_15m[e10 > e10.shift(1)] += 0.5
    score_15m[_rsi > 50] += 0.5
    
    # 5m weight = 0.10
    vol_avg = vol.rolling(20).mean()
    score_5m = pd.Series(0.0, index=df.index)
    score_5m[vol > vol_avg] += 1.0
    
    composite = score_4h * 0.40 + score_1h * 0.35 + score_15m * 0.15 + score_5m * 0.10
    
    regime_ok = _adx > 25
    
    # Fresh signal: composite was < 0.3 within last 20 bars
    was_low = composite.rolling(20).min() < 0.3
    
    conf_score = compute_confirmation_score(close, high, low, vol, e20, e50, _adx, _rsi, _atr, direction=1)
    tq = compute_trade_quality(_adx, close, e20, vol, _atr, direction=1)
    
    entries_long = regime_ok & (composite > 0.75) & was_low & (conf_score >= 2) & (tq >= 0.40)
    
    # Short: inverse composite
    composite_short = (1 - score_4h) * 0.40 + (1 - score_1h) * 0.35 + (1 - score_15m) * 0.15 + score_5m * 0.10
    was_low_s = composite_short.rolling(20).min() < 0.3
    conf_s = compute_confirmation_score(close, high, low, vol, e20, e50, _adx, _rsi, _atr, direction=-1)
    tq_s = compute_trade_quality(_adx, close, e20, vol, _atr, direction=-1)
    entries_short = regime_ok & (composite_short > 0.75) & was_low_s & (conf_s >= 2) & (tq_s >= 0.40)
    
    direction = pd.Series(0, index=df.index)
    direction[entries_long] = 1
    direction[entries_short] = -1
    
    return direction, _atr, _adx, e20


def gen_signals_mom001(df, dna):
    """MOM-G3-001: ADX-gated momentum breakout with opening range"""
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    
    e20 = ema(close, 20)
    e50 = ema(close, 50)
    _adx = adx(high, low, close, 14)
    _rsi = rsi(close, 14)
    _atr = atr(high, low, close, 14)
    
    regime_ok = _adx > 25
    
    # Opening range proxy: 5-bar high/low (daily bars)
    or_high = high.rolling(5).max().shift(1)
    or_low = low.rolling(5).min().shift(1)
    
    # Breakout above opening range with volume (relaxed for daily)
    vol_avg = vol.rolling(20).mean()
    vol_mult = 1.2  # daily bars have less extreme volume spikes
    
    breakout_long = (close > or_high) & (vol > vol_avg * vol_mult) & (e20 > e50)
    breakout_short = (close < or_low) & (vol > vol_avg * vol_mult) & (e20 < e50)
    
    # RSI not extended (35-70 for daily)
    rsi_ok = (_rsi > 35) & (_rsi < 70)
    
    conf_score = compute_confirmation_score(close, high, low, vol, e20, e50, _adx, _rsi, _atr, direction=1)
    tq = compute_trade_quality(_adx, close, e20, vol, _atr, direction=1)
    
    entries_long = regime_ok & breakout_long & rsi_ok & (conf_score >= 2) & (tq >= 0.40)
    
    conf_s = compute_confirmation_score(close, high, low, vol, e20, e50, _adx, _rsi, _atr, direction=-1)
    tq_s = compute_trade_quality(_adx, close, e20, vol, _atr, direction=-1)
    rsi_ok_s = (_rsi > 30) & (_rsi < 65)
    entries_short = regime_ok & breakout_short & rsi_ok_s & (conf_s >= 2) & (tq_s >= 0.40)
    
    direction = pd.Series(0, index=df.index)
    direction[entries_long] = 1
    direction[entries_short] = -1
    
    return direction, _atr, _adx, e20


def gen_signals_mom003(df, dna):
    """MOM-G3-003: ADX Holy Grail pullback — ADX > 30, pullback to 20 EMA"""
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    
    e20 = ema(close, 20)
    e50 = ema(close, 50)
    _adx = adx(high, low, close, 14)
    _rsi = rsi(close, 14)
    _atr = atr(high, low, close, 14)
    
    # Strict ADX > 30
    regime_ok = _adx > 30
    
    # Pullback to 20 EMA (within 1.0 ATR for daily bars) — long
    near_ema_long = ((close - e20).abs() < (_atr * 1.0)) & (e20 > e50)
    
    # RSI pullback zone (35-60 for daily)
    rsi_ok = (_rsi > 35) & (_rsi < 60)
    
    # Volume check (not required to be declining on daily — too noisy)
    vol_avg = vol.rolling(20).mean()
    
    conf_score = compute_confirmation_score(close, high, low, vol, e20, e50, _adx, _rsi, _atr, direction=1)
    tq = compute_trade_quality(_adx, close, e20, vol, _atr, direction=1)
    
    entries_long = regime_ok & near_ema_long & rsi_ok & (conf_score >= 2) & (tq >= 0.40)
    
    # Short
    near_ema_short = ((e20 - close).abs() < (_atr * 1.0)) & (e20 < e50)
    rsi_ok_s = (_rsi > 40) & (_rsi < 65)
    conf_s = compute_confirmation_score(close, high, low, vol, e20, e50, _adx, _rsi, _atr, direction=-1)
    tq_s = compute_trade_quality(_adx, close, e20, vol, _atr, direction=-1)
    entries_short = regime_ok & near_ema_short & rsi_ok_s & (conf_s >= 2) & (tq_s >= 0.40)
    
    direction = pd.Series(0, index=df.index)
    direction[entries_long] = 1
    direction[entries_short] = -1
    
    return direction, _atr, _adx, e20


# ── Signal Dispatcher ─────────────────────────────────────────────────────

SIGNAL_FUNCS = {
    "TF-G3-001": gen_signals_tf001,
    "TF-G3-002": gen_signals_tf002,
    "TF-G3-003": gen_signals_tf003,
    "TF-G3-004": gen_signals_tf004,
    "MOM-G3-001": gen_signals_mom001,
    "MOM-G3-003": gen_signals_mom003,
}

# ── Full Backtest Engine ──────────────────────────────────────────────────

def run_full_backtest(
    dna: dict,
    df: pd.DataFrame,
    label: str = "",
) -> dict:
    """
    Run complete backtest with partial exits, regime testing, and trade logging.
    """
    code = dna["strategy_code"]
    sig_func = SIGNAL_FUNCS[code]
    
    exit_rules = dna.get("exit_rules", {
        "partial_tp_1": {"at_r": 1.0, "close_pct": 0.33},
        "partial_tp_2": {"at_r": 2.0, "close_pct": 0.33},
        "runner": {"trailing_atr": 2.0},
        "time_limit_bars": 15,
        "breakeven_at_r": 0.75,
    })
    time_limit = 30  # 30 daily bars = ~6 weeks for swing trades
    
    # Generate signals
    direction_series, _atr_series, _adx_series, ema20_series = sig_func(df, dna)
    
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    vol = df["volume"].values
    dates = df.index
    direction_arr = direction_series.values
    atr_arr = _atr_series.values
    adx_arr = _adx_series.values
    
    # ── Simulate trades with partial exits ──
    trades = []
    in_trade = False
    min_bars_between = 3  # cooldown
    last_exit_bar = -10
    
    for i in range(50, len(df) - time_limit - 1):
        if in_trade:
            continue
        
        if direction_arr[i] == 0:
            continue
        
        if i - last_exit_bar < min_bars_between:
            continue
        
        d = int(direction_arr[i])
        entry_price = close[i]
        stop_dist = atr_arr[i] * 1.5  # 1.5 ATR stop
        
        if stop_dist <= 0 or np.isnan(stop_dist):
            stop_dist = entry_price * 0.015
        
        # Get subsequent bars for partial exit simulation
        end_idx = min(i + time_limit + 1, len(df))
        sub_close = close[i+1:end_idx]
        sub_high = high[i+1:end_idx]
        sub_low = low[i+1:end_idx]
        
        if len(sub_close) == 0:
            continue
        
        raw_pnl_pct, bars_held, exit_reason = calc_partial_exit_pnl(
            entry_price, d, sub_close, sub_high, sub_low,
            stop_dist, exit_rules, time_limit
        )
        
        # Position sizing: risk 1% of equity per trade
        # raw_pnl_pct is based on full position. Scale by risk fraction.
        risk_pct_of_price = stop_dist / entry_price  # how much % the stop represents
        if risk_pct_of_price > 0:
            position_scale = RISK_PER_TRADE / risk_pct_of_price  # fraction of capital allocated
            position_scale = min(position_scale, 1.0)  # never more than 100% of capital
        else:
            position_scale = 0.01
        
        pnl_pct = raw_pnl_pct * position_scale
        pnl_pct -= COMMISSION_PCT / 100  # commission
        
        exit_idx = i + bars_held
        if exit_idx >= len(df):
            exit_idx = len(df) - 1
        
        # Build entry reason
        adx_val = adx_arr[i] if not np.isnan(adx_arr[i]) else 0
        entry_reasons = [
            f"Style: {dna['style']}",
            f"ADX={adx_val:.1f}",
            f"Dir={'LONG' if d==1 else 'SHORT'}",
            f"Price={entry_price:.2f}",
            f"ATR_stop={stop_dist:.2f}",
        ]
        
        trades.append({
            "entry_date": str(dates[i]),
            "entry_price": round(entry_price, 2),
            "direction": "LONG" if d == 1 else "SHORT",
            "exit_date": str(dates[exit_idx]),
            "exit_price": round(close[exit_idx], 2),
            "pnl_pct": round(pnl_pct, 6),
            "pnl_dollar": round(pnl_pct * INITIAL_CAPITAL, 2),
            "bars_held": bars_held,
            "entry_reason": " | ".join(entry_reasons),
            "exit_reason": exit_reason,
        })
        
        in_trade = True
        last_exit_bar = exit_idx
        # Reset in_trade after exit
        # Simple: set next available bar
        in_trade = False
        last_exit_bar = exit_idx
    
    # ── Compute metrics ──
    if not trades:
        return {
            "strategy_code": code,
            "label": label,
            "total_trades": 0,
            "error": "No trades generated",
        }
    
    pnls = np.array([t["pnl_pct"] for t in trades])
    n_trades = len(trades)
    wins = pnls > 0
    losses = pnls <= 0
    n_wins = int(wins.sum())
    n_losses = int(losses.sum())
    
    win_rate = n_wins / n_trades
    avg_win = float(pnls[wins].mean()) if n_wins else 0
    avg_loss = float(pnls[losses].mean()) if n_losses else 0
    largest_win = float(pnls.max()) if n_wins else 0
    largest_loss = float(pnls.min()) if n_losses else 0
    
    # Equity curve
    equity = INITIAL_CAPITAL
    eq_curve = [INITIAL_CAPITAL]
    for p in pnls:
        equity *= (1 + p)
        eq_curve.append(equity)
    eq_arr = np.array(eq_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - peak) / np.where(peak > 0, peak, 1)
    max_dd = float(abs(dd.min()))
    
    total_pnl_pct = float((eq_curve[-1] / INITIAL_CAPITAL - 1) * 100)
    total_pnl_dollar = eq_curve[-1] - INITIAL_CAPITAL
    
    # Sharpe
    if len(pnls) > 1 and pnls.std() > 0:
        trades_per_year = min(252, n_trades)
        sharpe = float((pnls.mean() / pnls.std()) * np.sqrt(trades_per_year))
    else:
        sharpe = 0.0
    
    # Profit factor
    gross_profit = float(pnls[wins].sum()) if n_wins else 0
    gross_loss = float(abs(pnls[losses].sum())) if n_losses else 0.0001
    profit_factor = gross_profit / gross_loss
    
    expectancy = float(pnls.mean())
    
    # Avg holding period
    avg_hold = np.mean([t["bars_held"] for t in trades])
    
    # Win/loss streaks
    max_win_streak = 0
    max_loss_streak = 0
    cur_win = 0
    cur_loss = 0
    for p in pnls:
        if p > 0:
            cur_win += 1
            cur_loss = 0
            max_win_streak = max(max_win_streak, cur_win)
        else:
            cur_loss += 1
            cur_win = 0
            max_loss_streak = max(max_loss_streak, cur_loss)
    
    metrics = {
        "strategy_code": code,
        "label": label,
        "style": dna.get("style", ""),
        "confidence": dna.get("confidence", 0),
        "total_trades": n_trades,
        "wins": n_wins,
        "losses": n_losses,
        "win_rate": round(win_rate, 4),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "total_pnl_dollar": round(total_pnl_dollar, 2),
        "sharpe_ratio": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
        "profit_factor": round(profit_factor, 4),
        "expectancy_per_trade": round(expectancy, 6),
        "avg_win": round(avg_win, 6),
        "avg_loss": round(avg_loss, 6),
        "largest_win": round(largest_win, 6),
        "largest_loss": round(largest_loss, 6),
        "avg_holding_bars": round(avg_hold, 1),
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
    }
    
    return metrics, trades


# ── Regime Testing ────────────────────────────────────────────────────────

def run_regime_test(dna, df):
    """
    Split data into trending/ranging/volatile regimes.
    Run backtest on each regime separately.
    """
    regime_series = classify_regimes(df)
    
    results = {}
    for regime_name in ["trending", "ranging", "volatile"]:
        mask = regime_series == regime_name
        regime_df = df[mask].copy()
        
        if len(regime_df) < 100:
            results[regime_name] = {
                "bars": len(regime_df),
                "trades": 0,
                "profitable": False,
                "note": f"Insufficient data ({len(regime_df)} bars)"
            }
            continue
        
        try:
            out = run_full_backtest(dna, regime_df, label=f"regime_{regime_name}")
            if isinstance(out, tuple):
                metrics, trades = out
            else:
                metrics = out
                trades = []
            
            profitable = metrics.get("total_pnl_pct", 0) > 0
            results[regime_name] = {
                "bars": len(regime_df),
                "trades": metrics.get("total_trades", 0),
                "pnl_pct": metrics.get("total_pnl_pct", 0),
                "win_rate": metrics.get("win_rate", 0),
                "sharpe": metrics.get("sharpe_ratio", 0),
                "profitable": profitable,
            }
        except Exception as e:
            results[regime_name] = {
                "bars": len(regime_df),
                "error": str(e),
                "profitable": False,
            }
    
    regimes_profitable = sum(1 for r in results.values() if r.get("profitable", False))
    
    return results, regimes_profitable


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("  DARWIN FULL 16-YEAR BACKTEST — Gen 3 Strategies on CL Crude Oil")
    print("=" * 80)
    
    # Load DNAs
    with open(DNA_PATH) as f:
        all_dnas = json.load(f)
    
    dna_map = {d["strategy_code"]: d for d in all_dnas}
    
    # Load CL daily data
    print("\n📊 Loading CL data...")
    df_daily = load_parquet("CL", "daily")
    print(f"   Daily: {len(df_daily)} bars, {df_daily.index[0]} → {df_daily.index[-1]}")
    
    # Also load 4h and 1h for better resolution
    try:
        df_4h = load_parquet("CL", "4h")
        print(f"   4H:    {len(df_4h)} bars")
    except:
        df_4h = None
        print("   4H:    Not available, using daily")
    
    try:
        df_1h = load_parquet("CL", "1h")
        print(f"   1H:    {len(df_1h)} bars")
    except:
        df_1h = None
    
    # Use daily data (most complete 16-year coverage)
    # Daily bars approximate 4h bias level
    df = df_daily.copy()
    
    print(f"\n🧬 Testing {len(STRATEGIES_TO_TEST)} strategies...")
    print("-" * 80)
    
    all_results = {}
    all_trade_logs = {}
    production_candidates = []
    
    for code in STRATEGIES_TO_TEST:
        if code not in dna_map:
            print(f"  ❌ {code} — DNA not found!")
            continue
        
        dna = dna_map[code]
        print(f"\n🔬 Backtesting {code} ({dna['style']})...")
        
        try:
            out = run_full_backtest(dna, df, label="full_16yr")
            if isinstance(out, tuple):
                metrics, trades = out
            else:
                metrics = out
                trades = []
            
            # Regime testing
            print(f"   Running regime decomposition...")
            regime_results, regimes_profitable = run_regime_test(dna, df)
            metrics["regime_breakdown"] = regime_results
            metrics["regimes_profitable"] = regimes_profitable
            
            all_results[code] = metrics
            all_trade_logs[code] = trades[:200]  # cap trade log
            
            # Print summary
            nt = metrics.get("total_trades", 0)
            wr = metrics.get("win_rate", 0)
            sr = metrics.get("sharpe_ratio", 0)
            dd = metrics.get("max_drawdown", 0)
            pf = metrics.get("profit_factor", 0)
            pnl = metrics.get("total_pnl_pct", 0)
            
            print(f"   Trades: {nt} | WR: {wr:.1%} | Sharpe: {sr:.2f} | MaxDD: {dd:.1%} | PF: {pf:.2f} | PnL: {pnl:+.1f}%")
            print(f"   Regimes profitable: {regimes_profitable}/3 — {regime_results}")
            
            # Darwin criteria check
            passes_darwin = (
                wr >= DARWIN_CRITERIA["min_win_rate"] and
                sr >= DARWIN_CRITERIA["min_sharpe"] and
                dd <= DARWIN_CRITERIA["max_drawdown"] and
                regimes_profitable >= DARWIN_CRITERIA["min_regimes_profitable"] and
                nt >= 20
            )
            
            metrics["passes_darwin"] = passes_darwin
            
            if passes_darwin:
                production_candidates.append(code)
                metrics["tag"] = "FIRST_PRODUCTION_CANDIDATE"
                print(f"   🏆 *** PASSES DARWIN — PRODUCTION CANDIDATE ***")
            else:
                reasons = []
                if wr < DARWIN_CRITERIA["min_win_rate"]:
                    reasons.append(f"WR {wr:.1%} < 40%")
                if sr < DARWIN_CRITERIA["min_sharpe"]:
                    reasons.append(f"Sharpe {sr:.2f} < 0.5")
                if dd > DARWIN_CRITERIA["max_drawdown"]:
                    reasons.append(f"DD {dd:.1%} > 10%")
                if regimes_profitable < DARWIN_CRITERIA["min_regimes_profitable"]:
                    reasons.append(f"Regimes {regimes_profitable}/3 < 2")
                if nt < 20:
                    reasons.append(f"Trades {nt} < 20")
                print(f"   ❌ Failed: {', '.join(reasons)}")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            all_results[code] = {"strategy_code": code, "error": str(e)}
    
    # ── Leaderboard ──
    print("\n" + "=" * 80)
    print("  📊 STRATEGY LEADERBOARD — Ranked by Sharpe Ratio")
    print("=" * 80)
    
    ranked = sorted(
        [(k, v) for k, v in all_results.items() if isinstance(v, dict) and "total_trades" in v and v["total_trades"] > 0],
        key=lambda x: x[1].get("sharpe_ratio", -999),
        reverse=True
    )
    
    print(f"\n{'Rank':<5} {'Strategy':<12} {'Trades':>7} {'WinRate':>8} {'Sharpe':>7} {'MaxDD':>7} {'PF':>7} {'PnL%':>8} {'Regimes':>8} {'Darwin':>8}")
    print("-" * 95)
    
    for rank, (code, m) in enumerate(ranked, 1):
        tag = "✅ PASS" if m.get("passes_darwin") else "❌ FAIL"
        print(f"{rank:<5} {code:<12} {m['total_trades']:>7} {m['win_rate']:>7.1%} {m['sharpe_ratio']:>7.2f} {m['max_drawdown']:>6.1%} {m['profit_factor']:>7.2f} {m['total_pnl_pct']:>+7.1f}% {m.get('regimes_profitable',0):>5}/3   {tag}")
    
    # ── Production Candidates ──
    if production_candidates:
        print("\n" + "🏆" * 40)
        print("  🚀 FIRST PRODUCTION CANDIDATES IDENTIFIED!")
        print("🏆" * 40)
        for c in production_candidates:
            m = all_results[c]
            print(f"\n  ✅ {c}")
            print(f"     Style:        {m.get('style', '')}")
            print(f"     Win Rate:     {m['win_rate']:.1%}")
            print(f"     Sharpe:       {m['sharpe_ratio']:.2f}")
            print(f"     Max DD:       {m['max_drawdown']:.1%}")
            print(f"     Profit Factor:{m['profit_factor']:.2f}")
            print(f"     Total PnL:    {m['total_pnl_pct']:+.1f}%")
            print(f"     Expectancy:   {m['expectancy_per_trade']:.4%} per trade")
            print(f"     Regimes:      {m.get('regimes_profitable',0)}/3 profitable")
    else:
        print("\n⚠️  No strategies passed Darwin criteria this round.")
        print("    Closest candidates should be re-optimized.")
    
    # ── Save Results ──
    output = {
        "meta": {
            "backtest_date": str(pd.Timestamp.now()),
            "data_range": f"{df.index[0]} to {df.index[-1]}",
            "bars": len(df),
            "initial_capital": INITIAL_CAPITAL,
            "darwin_criteria": DARWIN_CRITERIA,
            "strategies_tested": STRATEGIES_TO_TEST,
        },
        "results": all_results,
        "trade_logs": {k: v[:100] for k, v in all_trade_logs.items()},  # cap at 100 per strategy
        "production_candidates": production_candidates,
        "leaderboard": [
            {"rank": i+1, "code": code, **metrics}
            for i, (code, metrics) in enumerate(ranked)
        ],
    }
    
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\n💾 Results saved to: {OUTPUT_PATH}")
    print(f"   Total strategies: {len(STRATEGIES_TO_TEST)}")
    print(f"   Production candidates: {len(production_candidates)}")
    print("=" * 80)


if __name__ == "__main__":
    main()

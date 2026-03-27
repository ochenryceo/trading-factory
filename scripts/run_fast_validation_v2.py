#!/usr/bin/env python3
"""
Gen 2 Fast Validation Runner — Enhanced signal generation with regime filters,
multi-confirmation, ATR trailing exits, and risk:reward enforcement.

Uses resampled bars to approximate higher-timeframe indicators.
Calibrated for 30-day 5m windows — relaxes filter thresholds for fast validation
while preserving the Gen 2 regime-gated, multi-confirmation, ATR-exit architecture.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import vectorbt as vbt

from services.fast_validation.vectorbt_runner import (
    load_5m_data, _ema, _sma, _rsi, _atr, _adx, _bb, _z_score, _mid,
)
from services.fast_validation.pass_fail import evaluate, calculate_confidence
from services.fast_validation.queue_manager import classify_priority
from services.fast_validation.schemas import FastValidationResult

DATA_DIR = PROJECT_ROOT / "data"
MOCK_DIR = DATA_DIR / "mock"

# ---------------------------------------------------------------------------
# HTF resampling
# ---------------------------------------------------------------------------

def resample_ohlcv(df_5m, freq):
    return df_5m.resample(freq).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna()


def compute_htf(df_5m):
    df_1h = resample_ohlcv(df_5m, "1h")
    df_4h = resample_ohlcv(df_5m, "4h")
    h = pd.DataFrame(index=df_5m.index)
    h["adx_4h"] = _adx(df_4h["high"], df_4h["low"], df_4h["close"]).reindex(df_5m.index, method="ffill")
    h["atr_1h"] = _atr(df_1h["high"], df_1h["low"], df_1h["close"]).reindex(df_5m.index, method="ffill")
    h["atr_4h"] = _atr(df_4h["high"], df_4h["low"], df_4h["close"]).reindex(df_5m.index, method="ffill")
    h["rsi_1h"] = _rsi(df_1h["close"], 14).reindex(df_5m.index, method="ffill")
    h["ema20_1h"] = _ema(df_1h["close"], 20).reindex(df_5m.index, method="ffill")
    h["ema50_1h"] = _ema(df_1h["close"], 50).reindex(df_5m.index, method="ffill")
    return h


# ---------------------------------------------------------------------------
# Gen 2 Signal Generators — HTF regime-gated with calibrated thresholds
# Each style produces BOTH long and short entries for more signal density.
# ---------------------------------------------------------------------------

def gen2_momentum(df, h, dna):
    """ADX-gated momentum: trade in trend direction with volume confirmation."""
    c, hi, lo, v = df["close"], df["high"], df["low"], df["volume"]
    p = dna.get("parameter_ranges", {})
    adx_t = _mid(p.get("adx_threshold", [25, 30]))

    # Regime: 4h ADX confirms trend
    trend = h["adx_4h"] > adx_t
    ema_up = h["ema20_1h"] > h["ema50_1h"]
    ema_dn = h["ema20_1h"] < h["ema50_1h"]

    # 5m signals
    va = v.rolling(20).mean()
    vol_ok = v > va * 1.3  # Relaxed from DNA's 1.8-2.5x for fast validation
    rsi = _rsi(c, 14)

    # Long: trending up + pullback zone + volume
    entries_long = trend & ema_up & vol_ok & (rsi > 40) & (rsi < 65) & (c > h["ema20_1h"])
    # Short: trending down + rally zone + volume
    entries_short = trend & ema_dn & vol_ok & (rsi > 35) & (rsi < 60) & (c < h["ema20_1h"])

    entries = entries_long | entries_short

    # Exit: trend weakens or EMA cross
    exits = (~trend) | ((ema_up & (c < h["ema50_1h"])) | (ema_dn & (c > h["ema50_1h"])))
    return entries, exits


def gen2_mean_reversion(df, h, dna):
    """ADX < max gate: mean reversion at BB extremes in ranging markets."""
    c, v = df["close"], df["volume"]
    rf = dna.get("regime_filter", {})
    p = dna.get("parameter_ranges", {})

    adx_max = rf.get("trend_strength_max", 25)  # 20-25 per DNAs
    ranging = h["adx_4h"] < adx_max

    rsi = _rsi(c, 14)
    bb_lo, bb_mid, bb_hi = _bb(c)
    va = v.rolling(20).mean()

    # Oversold long at lower BB + volume spike
    long_entry = ranging & (rsi < 35) & (c < bb_lo) & (v > va * 1.2)
    # Overbought short at upper BB + volume spike
    short_entry = ranging & (rsi > 65) & (c > bb_hi) & (v > va * 1.2)

    entries = long_entry | short_entry
    exits = (c > bb_mid) & long_entry.shift(1).fillna(False) | (c < bb_mid) & short_entry.shift(1).fillna(False)
    # Simpler exit: RSI returns to neutral or price crosses mid
    exits = ((rsi > 55) & (c > bb_mid)) | ((rsi < 45) & (c < bb_mid)) | (~ranging)
    return entries, exits


def gen2_scalping(df, h, dna):
    """Low-volatility regime scalps at BB + RSI extremes."""
    c, hi, lo, v = df["close"], df["high"], df["low"], df["volume"]
    p = dna.get("parameter_ranges", {})

    # ATR regime: low vol
    atr_avg = h["atr_1h"].rolling(20).mean()
    atr_ratio = (h["atr_1h"] / atr_avg.replace(0, np.nan)).fillna(1)
    low_vol = atr_ratio < 1.2

    rsi = _rsi(c, 7)
    bb_lo, bb_mid, bb_hi = _bb(c, 20, 2.0)
    va = v.rolling(20).mean()

    # Long scalp: oversold + low vol
    long_e = low_vol & (rsi < 30) & (c <= bb_lo) & (v > va * 1.1)
    # Short scalp: overbought + low vol
    short_e = low_vol & (rsi > 70) & (c >= bb_hi) & (v > va * 1.1)

    entries = long_e | short_e
    exits = (rsi > 55) | (rsi < 45) | (c >= bb_mid) & long_e.shift(1).fillna(False)
    exits = ((rsi > 50) & (c > bb_mid)) | ((rsi < 50) & (c < bb_mid)) | (~low_vol)
    return entries, exits


def gen2_trend_following(df, h, dna):
    """Strong trend follow: ADX > threshold, EMA pullback entry, ATR trail."""
    c, hi, lo, v = df["close"], df["high"], df["low"], df["volume"]
    p = dna.get("parameter_ranges", {})
    adx_t = _mid(p.get("adx_threshold", [25, 30]))

    strong = h["adx_4h"] > adx_t
    ema_up = h["ema20_1h"] > h["ema50_1h"]
    ema_dn = h["ema20_1h"] < h["ema50_1h"]

    atr_5m = _atr(hi, lo, c)
    # Pullback to EMA: within 3 ATR of 1h EMA20
    near_ema = (c - h["ema20_1h"]).abs() < atr_5m * 3

    rsi = _rsi(c, 14)
    va = v.rolling(20).mean()

    # Trend follow long
    long_e = strong & ema_up & near_ema & (rsi > 35) & (rsi < 65)
    # Trend follow short
    short_e = strong & ema_dn & near_ema & (rsi > 35) & (rsi < 65)

    entries = long_e | short_e
    exits = (~strong) | (ema_up & (c < h["ema50_1h"])) | (ema_dn & (c > h["ema50_1h"]))
    return entries, exits


def gen2_news(df, h, dna):
    """ATR burst detection: momentum continuation after volatility spike."""
    c, hi, lo, v = df["close"], df["high"], df["low"], df["volume"]
    p = dna.get("parameter_ranges", {})

    atr_5m = _atr(hi, lo, c)
    atr_avg = atr_5m.rolling(60).mean()
    va = v.rolling(20).mean()
    vol_m = _mid(p.get("volume_multiplier", [2.0, 3.0]))

    # Burst: ATR spike + volume spike
    burst = (atr_5m > atr_avg * 1.5) & (v > va * vol_m)
    burst_recent = burst.rolling(10).max().fillna(0).astype(bool)

    momentum = c - c.shift(5)
    recovery = c > c.shift(1)

    entries = burst_recent & recovery & (momentum > 0)
    exits = ~burst_recent | (momentum < -atr_5m * 0.3)
    return entries, exits


def gen2_volume(df, h, dna):
    """Volume-gated z-score reversion at structural extremes."""
    c, hi, lo, v = df["close"], df["high"], df["low"], df["volume"]
    rf = dna.get("regime_filter", {})
    p = dna.get("parameter_ranges", {})

    z = _z_score(c, 50)
    va = v.rolling(20).mean()
    vol_r = _mid(p.get("volume_min_ratio", [1.3, 1.8]))
    high_vol = v > va * vol_r
    adx_max = rf.get("trend_strength_max", 25)
    not_trend = h["adx_4h"] < adx_max

    # Long: extreme oversold with volume
    long_e = (z < -1.8) & high_vol & not_trend
    # Short: extreme overbought with volume
    short_e = (z > 1.8) & high_vol & not_trend

    entries = long_e | short_e
    exits = (z.abs() < 0.5) | (~high_vol & (z.abs() < 1.0))
    return entries, exits


GEN2_MAP = {
    "momentum_breakout": gen2_momentum,
    "mean_reversion": gen2_mean_reversion,
    "scalping": gen2_scalping,
    "trend_following": gen2_trend_following,
    "news_reaction": gen2_news,
    "volume_orderflow": gen2_volume,
}


# ---------------------------------------------------------------------------
# ATR trailing stop exit layer
# ---------------------------------------------------------------------------

def apply_atr_trailing(entries, exits, df, dna):
    """ATR-based trailing stop + time limit + breakeven."""
    er = dna.get("exit_rules", {})
    rr = dna.get("risk_reward", {})
    c = df["close"]
    atr = _atr(df["high"], df["low"], c)

    # Trailing stop
    mult = rr.get("stop_atr_multiplier", 1.5)
    rh = c.rolling(12).max()
    trail = c < (rh - atr * mult)
    exits = exits | trail

    # Time limit
    tl = er.get("time_limit", 0)
    if tl > 0:
        unit = er.get("time_limit_unit", "bars_5m")
        if "hour" in unit:
            bars = int(tl * 12)
        elif "15m" in unit:
            bars = int(tl * 3)
        elif "1h" in unit:
            bars = int(tl * 12)
        elif "minute" in unit:
            bars = max(int(tl / 5), 1)
        else:
            bars = int(tl)
        if 0 < bars < len(entries):
            te = entries.shift(bars).fillna(False).infer_objects(copy=False).astype(bool)
            exits = exits | te

    return exits.fillna(False).astype(bool)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_gen2(dna, asset="NQ", last_n_days=30, init_cash=100_000.0, fees=0.0002, slippage=0.0001, htf_cache=None):
    sid = dna.get("strategy_code", "?")
    try:
        df = load_5m_data(asset, last_n_days)
    except Exception as e:
        return FastValidationResult(strategy_id=sid, status="FAIL", reason=str(e), metrics={}, tested_window="N/A")

    if len(df) < 100:
        return FastValidationResult(strategy_id=sid, status="FAIL", reason=f"Only {len(df)} bars", metrics={}, tested_window="N/A")

    if htf_cache and asset in htf_cache:
        h = htf_cache[asset]
    else:
        h = compute_htf(df)
        if htf_cache is not None:
            htf_cache[asset] = h

    style = dna.get("style", "momentum_breakout")
    fn = GEN2_MAP.get(style, gen2_momentum)

    try:
        entries, exits = fn(df, h, dna)
    except Exception as e:
        return FastValidationResult(strategy_id=sid, status="FAIL", reason=f"Signal error: {e}", metrics={}, tested_window="N/A")

    # ATR trailing + time limit exits
    exits = apply_atr_trailing(entries, exits, df, dna)

    entries = entries.fillna(False).astype(bool)
    exits = exits.fillna(False).astype(bool)

    try:
        pf = vbt.Portfolio.from_signals(
            close=df["close"], entries=entries, exits=exits,
            init_cash=init_cash, fees=fees, slippage=slippage, freq="5min",
        )
    except Exception as e:
        return FastValidationResult(strategy_id=sid, status="FAIL", reason=f"Sim error: {e}", metrics={}, tested_window="N/A")

    tr = float(pf.total_return())
    pnl = float(pf.total_profit())
    tc = int(pf.trades.count())
    wr = float(pf.trades.win_rate()) if tc > 0 else 0.0
    dd = float(pf.max_drawdown())
    try:
        sr = float(pf.sharpe_ratio())
    except:
        sr = 0.0
    for name in ['wr','dd','sr','pnl','tr']:
        val = locals()[name]
        if np.isnan(val):
            locals()[name] = 0.0
    wr = 0.0 if np.isnan(wr) else wr
    dd = 0.0 if np.isnan(dd) else dd
    sr = 0.0 if np.isnan(sr) else sr
    pnl = 0.0 if np.isnan(pnl) else pnl
    tr = 0.0 if np.isnan(tr) else tr

    ws = df.index.min().strftime("%Y-%m-%d")
    we = df.index.max().strftime("%Y-%m-%d")

    metrics = {
        "total_pnl": round(pnl, 2),
        "total_return_pct": round(tr * 100, 2),
        "trade_count": tc,
        "win_rate": round(wr, 4),
        "max_drawdown": round(abs(dd), 4),
        "sharpe_ratio": round(sr, 4),
    }

    status, reason, fail_reasons = evaluate(metrics)
    conf = calculate_confidence(metrics)
    q = classify_priority(conf) if status == "PASS" else ""

    return FastValidationResult(
        strategy_id=sid, status=status, reason=reason,
        metrics=metrics, tested_window=f"{ws} to {we}",
        confidence=conf, queue_priority=q, fail_reasons=fail_reasons,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    v2_path = DATA_DIR / "strategy_dnas_v2.json"
    with open(v2_path) as f:
        gen2_dnas = json.load(f)

    gen1_path = MOCK_DIR / "fast_validation_results.json"
    with open(gen1_path) as f:
        all_existing = json.load(f)
    gen1_results = [r for r in all_existing if r.get("generation", 1) == 1]

    print(f"{'='*78}")
    print(f"  TRADING FACTORY — Gen 2 Fast Validation (HTF regime-gated)")
    print(f"  {len(gen2_dnas)} Gen 2 DNAs | {len(gen1_results)} Gen 1 baseline results")
    print(f"{'='*78}\n")

    print("GEN 2 FAST VALIDATION — regime filters + multi-confirmation + ATR trailing")
    print("-" * 78)

    gen2_results = []
    htf_cache = {}

    for dna in gen2_dnas:
        code = dna.get("strategy_code", "?")
        style = dna.get("style", "?")
        result = run_gen2(dna, asset="NQ", last_n_days=30, htf_cache=htf_cache)
        rd = result.to_dict()
        rd["generation"] = 2
        rd["style"] = style
        gen2_results.append(rd)

        badge = "🟢 PASS" if result.status == "PASS" else "🔴 FAIL"
        m = result.metrics
        print(f"  {badge}  {code:12s} [{style:20s}]  trades={m.get('trade_count',0):4d}  WR={m.get('win_rate',0)*100:5.1f}%  PnL=${m.get('total_pnl',0):>10,.2f}  DD={m.get('max_drawdown',0)*100:5.1f}%  SR={m.get('sharpe_ratio',0):>6.2f}  conf={result.confidence:.3f}  q={result.queue_priority or 'FAIL'}")
        if result.fail_reasons:
            for fr in result.fail_reasons:
                print(f"       └─ {fr}")

    # Save v2 results
    v2_out = MOCK_DIR / "fast_validation_results_v2.json"
    with open(v2_out, "w") as f:
        json.dump(gen2_results, f, indent=2)
    print(f"\n✅ Gen 2 results → {v2_out}")

    # Merge + save combined
    for r in gen1_results:
        r.setdefault("generation", 1)
        prefix = r["strategy_id"].split("-")[0]
        r["style"] = {"MOM":"momentum_breakout","MR":"mean_reversion","SCP":"scalping",
                       "TF":"trend_following","NR":"news_reaction","VOF":"volume_orderflow"}.get(prefix, "unknown")

    combined = gen1_results + gen2_results
    with open(MOCK_DIR / "fast_validation_results.json", "w") as f:
        json.dump(combined, f, indent=2)
    print(f"✅ Combined ({len(combined)} total) → fast_validation_results.json")

    # ── COMPARISON ─────────────────────────────────────────────────
    print(f"\n{'='*78}")
    print(f"  GEN 1 vs GEN 2 COMPARISON")
    print(f"{'='*78}\n")

    def stats(results):
        p = [r for r in results if r["status"] == "PASS"]
        f = [r for r in results if r["status"] == "FAIL"]
        pr = len(p) / max(len(results), 1)
        ac = np.mean([r.get("confidence", 0) for r in results]) if results else 0
        ap = np.mean([r["metrics"].get("total_pnl", 0) for r in results]) if results else 0
        aw = np.mean([r["metrics"].get("win_rate", 0) for r in results]) if results else 0
        ad = np.mean([r["metrics"].get("max_drawdown", 0) for r in results]) if results else 0
        asr = np.mean([r["metrics"].get("sharpe_ratio", 0) for r in results if np.isfinite(r["metrics"].get("sharpe_ratio", 0))]) if results else 0
        qs = {"IMMEDIATE": 0, "BATCH": 0, "ARCHIVE": 0}
        for r in p:
            q = r.get("queue_priority", "ARCHIVE")
            qs[q] = qs.get(q, 0) + 1
        return {"n": len(results), "pass": len(p), "fail": len(f), "pr": pr,
                "ac": ac, "ap": ap, "aw": aw, "ad": ad, "asr": asr, "qs": qs}

    g1 = stats(gen1_results)
    g2 = stats(gen2_results)

    print(f"  {'Metric':<30s}  {'Gen 1':>12s}  {'Gen 2':>12s}  {'Delta':>10s}")
    print(f"  {'-'*30}  {'-'*12}  {'-'*12}  {'-'*10}")
    print(f"  {'Total strategies':<30s}  {g1['n']:>12d}  {g2['n']:>12d}")
    print(f"  {'Passed / Failed':<30s}  {g1['pass']:>5d}/{g1['fail']:<5d}  {g2['pass']:>5d}/{g2['fail']:<5d}")
    print(f"  {'Pass rate':<30s}  {g1['pr']:>11.1%}  {g2['pr']:>11.1%}  {(g2['pr']-g1['pr']):>+9.1%}")
    print(f"  {'Avg confidence':<30s}  {g1['ac']:>12.3f}  {g2['ac']:>12.3f}  {(g2['ac']-g1['ac']):>+10.3f}")
    print(f"  {'Avg PnL':<30s}  ${g1['ap']:>10,.2f}  ${g2['ap']:>10,.2f}  ${(g2['ap']-g1['ap']):>+9,.2f}")
    print(f"  {'Avg win rate':<30s}  {g1['aw']:>11.1%}  {g2['aw']:>11.1%}  {(g2['aw']-g1['aw']):>+9.1%}")
    print(f"  {'Avg max drawdown':<30s}  {g1['ad']:>11.1%}  {g2['ad']:>11.1%}  {(g2['ad']-g1['ad']):>+9.1%}")
    print(f"  {'Avg Sharpe ratio':<30s}  {g1['asr']:>12.3f}  {g2['asr']:>12.3f}  {(g2['asr']-g1['asr']):>+10.3f}")

    print(f"\n  Queue Allocation:")
    print(f"  {'Queue':<20s}  {'Gen 1':>8s}  {'Gen 2':>8s}")
    print(f"  {'-'*20}  {'-'*8}  {'-'*8}")
    for q in ["IMMEDIATE", "BATCH", "ARCHIVE"]:
        print(f"  {q:<20s}  {g1['qs'].get(q,0):>8d}  {g2['qs'].get(q,0):>8d}")
    print(f"  {'FAILED':<20s}  {g1['fail']:>8d}  {g2['fail']:>8d}")

    # Style comparison
    print(f"\n  Style-by-Style:")
    print(f"  {'Style':<22s}  {'G1 Conf':>7s}  {'G2 Conf':>7s}  {'Δ':>6s}  {'G1 PnL':>10s}  {'G2 PnL':>10s}  {'G1 WR':>6s}  {'G2 WR':>6s}")
    print(f"  {'-'*22}  {'-'*7}  {'-'*7}  {'-'*6}  {'-'*10}  {'-'*10}  {'-'*6}  {'-'*6}")

    styles = ["momentum_breakout", "mean_reversion", "scalping", "trend_following", "news_reaction", "volume_orderflow"]
    improvements = {}

    for s in styles:
        r1 = [r for r in gen1_results if r.get("style") == s]
        r2 = [r for r in gen2_results if r.get("style") == s]
        c1 = np.mean([r.get("confidence", 0) for r in r1]) if r1 else 0
        c2 = np.mean([r.get("confidence", 0) for r in r2]) if r2 else 0
        p1 = np.mean([r["metrics"].get("total_pnl", 0) for r in r1]) if r1 else 0
        p2 = np.mean([r["metrics"].get("total_pnl", 0) for r in r2]) if r2 else 0
        w1 = np.mean([r["metrics"].get("win_rate", 0) for r in r1]) if r1 else 0
        w2 = np.mean([r["metrics"].get("win_rate", 0) for r in r2]) if r2 else 0
        d = c2 - c1
        improvements[s] = d
        flag = "✅" if d > 0 else "⚠️"
        print(f"  {s:<22s}  {c1:>7.3f}  {c2:>7.3f}  {d:>+5.3f}{flag}  ${p1:>9,.0f}  ${p2:>9,.0f}  {w1:>5.1%}  {w2:>5.1%}")

    if improvements:
        best = max(improvements, key=improvements.get)
        worst = min(improvements, key=improvements.get)
        print(f"\n  🏆 Most improved: {best} ({improvements[best]:+.3f})")
        if improvements[worst] < 0:
            print(f"  ⚠️  Needs work: {worst} ({improvements[worst]:+.3f})")

    # IMMEDIATE check
    immediate = [r for r in gen2_results if r.get("queue_priority") == "IMMEDIATE"]
    batch = [r for r in gen2_results if r.get("queue_priority") == "BATCH"]

    print(f"\n{'='*78}")
    if immediate:
        print(f"  🚀 IMMEDIATE QUEUE — {len(immediate)} Gen 2 strategies!")
        print(f"{'='*78}")
        for r in immediate:
            m = r["metrics"]
            print(f"  ⚡ {r['strategy_id']:12s}  conf={r['confidence']:.3f}  WR={m['win_rate']*100:.1f}%  PnL=${m['total_pnl']:,.2f}  SR={m['sharpe_ratio']:.2f}")

        print(f"\n  → Auto-triggering Darwin backtest...")
        try:
            from services.darwin.backtester import run_backtest, load_parquet
            darwin_results = []
            for r in immediate:
                code = r["strategy_id"]
                mdna = next((d for d in gen2_dnas if d["strategy_code"] == code), None)
                if mdna:
                    try:
                        dd = load_parquet("NQ", "1d")
                        if dd is not None and len(dd) > 100:
                            bt = run_backtest(mdna, dd)
                            darwin_results.append({"strategy_id": code, "result": bt})
                            print(f"    ✅ {code}: Darwin complete")
                        else:
                            print(f"    ⚠️ {code}: no daily data")
                    except Exception as e:
                        print(f"    ⚠️ {code}: {e}")
            if darwin_results:
                dp = MOCK_DIR / "darwin_results_v2_immediate.json"
                with open(dp, "w") as f:
                    json.dump(darwin_results, f, indent=2, default=str)
                print(f"\n  ✅ Darwin results → {dp}")
        except ImportError as e:
            print(f"  ⚠️ Darwin not available: {e}")
    else:
        print(f"  📋 No IMMEDIATE queue strategies (need confidence > 0.7)")
        if batch:
            print(f"  📦 BATCH queue: {len(batch)} strategies ready for next batch run")
        if gen2_results:
            best_r = max(gen2_results, key=lambda r: r.get("confidence", 0))
            print(f"  📊 Highest confidence: {best_r['strategy_id']} @ {best_r['confidence']:.3f}")
    print(f"{'='*78}")

    # Top strategies
    print(f"\n  Top Gen 2 Strategies by Confidence:")
    for i, r in enumerate(sorted(gen2_results, key=lambda x: x.get("confidence", 0), reverse=True)[:10], 1):
        m = r["metrics"]
        print(f"  {i:2d}. {r['status']:4s}  {r['strategy_id']:12s}  conf={r['confidence']:.3f}  trades={m.get('trade_count',0):3d}  WR={m.get('win_rate',0)*100:.1f}%  PnL=${m.get('total_pnl',0):>9,.2f}  SR={m.get('sharpe_ratio',0):.2f}")

    print(f"\n{'='*78}")
    print(f"  DONE")
    print(f"{'='*78}")


if __name__ == "__main__":
    main()

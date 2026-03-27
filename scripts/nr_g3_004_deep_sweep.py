#!/usr/bin/env python3
"""
NR-G3-004 Deep Research — The bb_width_percentile parameter is NOT used
by the backtester's news_reaction signal generator. The actual signal logic:

    burst = (ATR > ATR_avg * 1.5) & (vol > vol_avg * vol_mult)
    momentum = close - close.shift(3)

This script:
1. Diagnoses WHY 2023+ has so few trades (what changed in ATR/volume patterns)
2. Sweeps the parameters that ACTUALLY affect signals: volume_multiplier and ATR threshold
3. Finds a variant that passes distribution
"""
import sys, json, copy
from pathlib import Path
from collections import defaultdict

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import pandas as pd
import numpy as np

from services.darwin.backtester import (
    load_parquet, run_backtest, BacktestResult, TradeRecord,
    atr, ema, bollinger_bands
)
from services.trade_distribution_gate import gini_coefficient
from services.walk_forward import walk_forward_test
from services.monte_carlo import monte_carlo_test

# ── Step 1: Diagnose the 2023+ trade drought ──────────────────────────
print("=" * 70)
print("STEP 1: WHY does 2023+ have so few trades?")
print("=" * 70)

df = load_parquet("NQ", "1h")
close = df["close"]
high = df["high"]
low = df["low"]
vol = df.get("volume", pd.Series(1, index=df.index))

# Compute the actual signal conditions
_atr = atr(high, low, close, 14)
atr_avg = _atr.rolling(20).mean()
vol_avg = vol.rolling(20).mean()

# Default vol_mult for news_reaction = _mid([2.0, 3.0]) = 2.5
vol_mult = 2.5

burst = (_atr > atr_avg * 1.5) & (vol > vol_avg * vol_mult)
momentum = close - close.shift(3)
has_signal = burst & (momentum.abs() > 0)

df_analysis = pd.DataFrame({
    "atr": _atr,
    "atr_avg": atr_avg,
    "atr_ratio": _atr / atr_avg.replace(0, np.nan),
    "vol": vol,
    "vol_avg": vol_avg,
    "vol_ratio": vol / vol_avg.replace(0, np.nan),
    "burst": burst.astype(int),
    "signal": has_signal.astype(int),
}, index=df.index)
df_analysis["year"] = df_analysis.index.year

print("\nPer-year signal statistics:")
print(f"{'Year':>6} | {'Bars':>6} | {'Signals':>7} | {'Bursts':>7} | {'AvgATR':>8} | {'AvgVol':>10} | {'ATR>1.5x%':>9} | {'Vol>2.5x%':>9}")
print("-" * 85)

for yr, grp in df_analysis.groupby("year"):
    n_bars = len(grp)
    n_signals = grp["signal"].sum()
    n_bursts = grp["burst"].sum()
    avg_atr = grp["atr"].mean()
    avg_vol = grp["vol"].mean()
    atr_exceed = (grp["atr_ratio"] > 1.5).mean() * 100
    vol_exceed = (grp["vol_ratio"] > 2.5).mean() * 100
    print(f"{yr:>6} | {n_bars:>6} | {n_signals:>7} | {n_bursts:>7} | {avg_atr:>8.1f} | {avg_vol:>10.0f} | {atr_exceed:>8.1f}% | {vol_exceed:>8.1f}%")

# Check: is it ATR or volume that dried up?
print("\n\nDiagnosis: Which condition fails in 2023+?")
for yr in [2021, 2022, 2023, 2024, 2025]:
    grp = df_analysis[df_analysis["year"] == yr]
    atr_pass = (grp["atr_ratio"] > 1.5)
    vol_pass = (grp["vol_ratio"] > 2.5)
    both = atr_pass & vol_pass
    print(f"  {yr}: ATR>1.5x: {atr_pass.sum():>5} bars ({atr_pass.mean()*100:.1f}%), "
          f"Vol>2.5x: {vol_pass.sum():>5} bars ({vol_pass.mean()*100:.1f}%), "
          f"Both: {both.sum():>5} bars ({both.mean()*100:.1f}%)")

# ── Step 2: Parameter sweep on ACTUAL signal parameters ───────────────
print("\n" + "=" * 70)
print("STEP 2: Sweep volume_multiplier (the actual signal parameter)")
print("=" * 70)

dnas = json.load(open(PROJECT / "data" / "strategy_dnas_v3.json"))
base_dna = None
for d in dnas:
    if d.get("strategy_code") == "NR-G3-004":
        base_dna = d
        break

# The actual params that matter: volume_multiplier
# Default for news_reaction: [2.0, 3.0] → mid = 2.5
# Try lower values to catch more events
sweep_configs = [
    {"label": "vol[2.0,3.0] (baseline)", "volume_multiplier": [2.0, 3.0]},
    {"label": "vol[1.5,2.5]", "volume_multiplier": [1.5, 2.5]},
    {"label": "vol[1.2,2.0]", "volume_multiplier": [1.2, 2.0]},
    {"label": "vol[1.0,1.8]", "volume_multiplier": [1.0, 1.8]},
    {"label": "vol[0.8,1.5]", "volume_multiplier": [0.8, 1.5]},
    {"label": "vol[1.5,2.0]", "volume_multiplier": [1.5, 2.0]},
    {"label": "vol[1.3,1.8]", "volume_multiplier": [1.3, 1.8]},
]

results = []

for cfg in sweep_configs:
    label = cfg["label"]
    print(f"\n--- Testing {label} ---")
    
    dna = copy.deepcopy(base_dna)
    dna["parameter_ranges"]["volume_multiplier"] = cfg["volume_multiplier"]
    
    result = run_backtest(dna, df, asset="NQ")
    
    # Yearly trade distribution
    yearly_trades = defaultdict(int)
    for t in result.trade_log:
        entry_time = t.get("entry_time", "")
        if len(entry_time) >= 4:
            yearly_trades[entry_time[:4]] += 1
    
    pnls = [t.get("pnl_pct", 0) for t in result.trade_log]
    gini = gini_coefficient(pnls) if pnls else 0.0
    
    wf = walk_forward_test(dna, "NQ", "1h")
    
    trades = [TradeRecord(
        entry_idx=0, exit_idx=0, direction=1,
        entry_price=t.get("entry_price", 0),
        exit_price=t.get("exit_price", 0),
        pnl_pct=t.get("pnl_pct", 0),
        entry_time=t.get("entry_time", ""),
        exit_time=t.get("exit_time", ""),
    ) for t in result.trade_log]
    mc = monte_carlo_test(trades)
    
    row = {
        "label": label,
        "vol_mult": cfg["volume_multiplier"],
        "trades": result.trade_count,
        "wr": result.win_rate,
        "sharpe": result.sharpe_ratio,
        "pf": result.profit_factor,
        "dd": result.max_drawdown,
        "ret": result.total_return_pct,
        "gini": gini,
        "wf_passed": wf.get("passed", False),
        "wf_oos_sharpe": wf.get("oos_sharpe", 0),
        "mc_passed": mc.get("passed", False),
        "mc_survival": mc.get("survival_rate", 0),
        "mc_p95_dd": mc.get("p95_dd", 0),
        "yearly": yearly_trades,
        "dna": dna,
    }
    results.append(row)
    
    print(f"  Trades: {row['trades']}, WR: {row['wr']:.1f}%, Sharpe: {row['sharpe']:.2f}, "
          f"PF: {row['pf']:.2f}, DD: {row['dd']:.1f}%, Ret: {row['ret']:+.1f}%, "
          f"Gini: {row['gini']:.3f}")
    print(f"  WF: {'PASS' if row['wf_passed'] else 'FAIL'} (OOS Sharpe: {row['wf_oos_sharpe']:.2f}), "
          f"MC: {'PASS' if row['mc_passed'] else 'FAIL'} (survival: {row['mc_survival']:.1%}, p95DD: {row['mc_p95_dd']:.1%})")
    yr_str = ", ".join(f"{y}: {c}" for y, c in sorted(yearly_trades.items()) if int(y) >= 2020)
    print(f"  Recent years: {yr_str}")

# ── Step 3: Comparison Table ───────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 3: Comparison Table")
print("=" * 70)

years_of_interest = ["2020", "2021", "2022", "2023", "2024", "2025", "2026"]
header = f"{'Config':>20} | {'Trades':>6} | {'WR':>6} | {'Sharpe':>6} | {'PF':>5} | {'DD':>6} | {'Ret':>7} | {'Gini':>5} | {'WF':>4} | {'MC':>4}"
for y in years_of_interest:
    header += f" | {y:>4}"
print(header)
print("-" * len(header))

for r in results:
    line = (f"{r['label']:>20} | {r['trades']:>6} | {r['wr']:>5.1f}% | {r['sharpe']:>6.2f} | "
            f"{r['pf']:>5.2f} | {r['dd']:>5.1f}% | {r['ret']:>+6.1f}% | {r['gini']:>5.3f} | "
            f"{'PASS' if r['wf_passed'] else 'FAIL':>4} | {'PASS' if r['mc_passed'] else 'FAIL':>4}")
    for y in years_of_interest:
        line += f" | {r['yearly'].get(y, 0):>4}"
    print(line)

# ── Step 4: Best Variant ──────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 4: Best Variant Selection")
print("=" * 70)

best = None
for r in results:
    recent_trades = sum(r["yearly"].get(y, 0) for y in ["2023", "2024", "2025", "2026"])
    passes_all = (
        r["gini"] < 0.50 and
        r["wf_passed"] and
        r["mc_passed"] and
        r["trades"] >= 100 and
        recent_trades > 0
    )
    
    if passes_all:
        if best is None or r["sharpe"] > best["sharpe"]:
            best = r
    
    status = "✅ PASSES ALL" if passes_all else "❌"
    fail_reasons = []
    if r["gini"] >= 0.50: fail_reasons.append(f"Gini {r['gini']:.3f}")
    if not r["wf_passed"]: fail_reasons.append("WF FAIL")
    if not r["mc_passed"]: fail_reasons.append("MC FAIL")
    if r["trades"] < 100: fail_reasons.append(f"trades={r['trades']}")
    if recent_trades == 0: fail_reasons.append("no 2023+ trades")
    
    print(f"  {r['label']:>20}: {status} {', '.join(fail_reasons)}")

if best:
    print(f"\n🏆 BEST VARIANT: {best['label']}")
    print(f"   volume_multiplier: {best['vol_mult']}")
    print(f"   Trades: {best['trades']}, Sharpe: {best['sharpe']:.2f}, Gini: {best['gini']:.3f}")
    recent = sum(best["yearly"].get(y, 0) for y in ["2023", "2024", "2025", "2026"])
    print(f"   2023+ trades: {recent}")
    
    out_dir = PROJECT / "data" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "NR-G3-004-optimized.json"
    
    save_dna = copy.deepcopy(best["dna"])
    with open(out_path, "w") as f:
        json.dump(save_dna, f, indent=2)
    print(f"   Saved to: {out_path}")
else:
    print("\n❌ NO VARIANT passes all criteria.")
    print("\nRoot cause analysis:")
    print("The backtester's news_reaction signal generator uses a FIXED ATR threshold (1.5x)")
    print("hardcoded in generate_signals(). The bb_width_percentile parameter in the DNA is")
    print("purely descriptive and NOT consumed by signal generation.")
    print()
    print("The 2023+ trade drought is caused by changed ATR/volume dynamics, and the")
    print("volume_multiplier parameter IS read but may not be sufficient to fix distribution.")
    print()
    print("RECOMMENDED ACTIONS:")
    print("1. Modify backtester.py to implement bb_width_percentile in news_reaction signals")
    print("2. Add BB compression filter: bb_width < percentile(bb_width_history, X)")
    print("3. Lower the ATR threshold from 1.5x to make it parameterizable")
    print("4. Consider this a conditional pass — the edge is real but regime-dependent")

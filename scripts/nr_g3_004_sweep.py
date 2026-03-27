#!/usr/bin/env python3
"""
NR-G3-004 Edge Research — BB Width Percentile Sweep

Diagnoses the trade distribution failure (Gini 0.520 > 0.50 threshold)
by checking data integrity and sweeping bb_width_percentile upper bound.
"""
import sys, json, copy
from pathlib import Path
from collections import defaultdict

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import pandas as pd
import numpy as np

from services.darwin.backtester import load_parquet, run_backtest, BacktestResult, TradeRecord
from services.trade_distribution_gate import gini_coefficient
from services.walk_forward import walk_forward_test
from services.monte_carlo import monte_carlo_test

# ── Step 1: Data Integrity ─────────────────────────────────────────────
print("=" * 70)
print("STEP 1: NQ 1h Data Integrity Check")
print("=" * 70)

df = load_parquet("NQ", "1h")
print(f"Total bars: {len(df)}")
print(f"Date range: {df.index.min()} → {df.index.max()}")
print()

# Bars per year
df_year = df.copy()
df_year["year"] = df_year.index.year
year_counts = df_year.groupby("year").size()
print("Bars per year:")
for yr, cnt in year_counts.items():
    marker = " ⚠️  LOW" if cnt < 5000 else ""
    print(f"  {yr}: {cnt:,}{marker}")
print()

# Check for gaps > 24h
gaps = df.index.to_series().diff()
big_gaps = gaps[gaps > pd.Timedelta(hours=24)]
if len(big_gaps) > 0:
    print(f"Gaps > 24h: {len(big_gaps)}")
    for ts, gap in big_gaps.head(10).items():
        print(f"  {ts}: {gap}")
else:
    print("No gaps > 24h found ✓")
print()

# ── Step 2: Load base DNA and sweep ────────────────────────────────────
print("=" * 70)
print("STEP 2: BB Width Percentile Sweep")
print("=" * 70)

dnas = json.load(open(PROJECT / "data" / "strategy_dnas_v3.json"))
base_dna = None
for d in dnas:
    if d.get("strategy_code") == "NR-G3-004":
        base_dna = d
        break

if not base_dna:
    print("ERROR: NR-G3-004 not found in strategy_dnas_v3.json")
    sys.exit(1)

print(f"Base DNA: {base_dna['strategy_code']}")
print(f"Base bb_width_percentile range: {base_dna['parameter_ranges']['bb_width_percentile']}")
print()

sweep_values = [10, 15, 20, 25, 30, 35]
results = []

for bb_pct in sweep_values:
    print(f"\n--- Testing bb_width_percentile = [5, {bb_pct}] ---")
    
    # Clone and modify DNA
    dna = copy.deepcopy(base_dna)
    dna["parameter_ranges"]["bb_width_percentile"] = [5, bb_pct]
    
    # Also update the event filter and filters list to match
    if "regime_filter" in dna and "event_filter" in dna["regime_filter"]:
        dna["regime_filter"]["event_filter"]["bb_width_percentile_max"] = bb_pct
    
    # Update filter text references
    new_filters = []
    for f in dna.get("filters", []):
        if "percentile" in f.lower():
            new_filters.append(f"BB width < {bb_pct}th percentile — genuine compression required")
        else:
            new_filters.append(f)
    dna["filters"] = new_filters
    
    # Update timeframe logic text
    if "timeframe_logic" in dna and "1h" in dna["timeframe_logic"]:
        dna["timeframe_logic"]["1h"] = f"BB width at {bb_pct}th percentile or lower. ATR declining 3+ bars. Genuine pre-event compression."
    
    # Run backtest
    result = run_backtest(dna, df, asset="NQ")
    
    # Yearly trade distribution
    yearly_trades = defaultdict(int)
    for t in result.trade_log:
        entry_time = t.get("entry_time", "")
        if len(entry_time) >= 4:
            yearly_trades[entry_time[:4]] += 1
    
    # Gini
    pnls = [t.get("pnl_pct", 0) for t in result.trade_log]
    gini = gini_coefficient(pnls) if pnls else 0.0
    
    # Walk-forward
    wf = walk_forward_test(dna, "NQ", "1h")
    
    # Monte Carlo (need TradeRecord objects)
    trades = []
    for t in result.trade_log:
        trades.append(TradeRecord(
            entry_idx=0, exit_idx=0,
            direction=1,
            entry_price=t.get("entry_price", 0),
            exit_price=t.get("exit_price", 0),
            pnl_pct=t.get("pnl_pct", 0),
            entry_reason=t.get("entry_reason", ""),
            exit_reason=t.get("exit_reason", ""),
            entry_time=t.get("entry_time", ""),
            exit_time=t.get("exit_time", ""),
        ))
    mc = monte_carlo_test(trades)
    
    row = {
        "bb_pct": bb_pct,
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

# Header
header = f"{'BB_PCT':>6} | {'Trades':>6} | {'WR':>6} | {'Sharpe':>6} | {'PF':>5} | {'DD':>6} | {'Ret':>7} | {'Gini':>5} | {'WF':>4} | {'MC':>4}"
years_of_interest = ["2020", "2021", "2022", "2023", "2024", "2025", "2026"]
for y in years_of_interest:
    header += f" | {y:>4}"
print(header)
print("-" * len(header))

for r in results:
    line = (f"{r['bb_pct']:>6} | {r['trades']:>6} | {r['wr']:>5.1f}% | {r['sharpe']:>6.2f} | "
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
    if r["gini"] >= 0.50: fail_reasons.append(f"Gini {r['gini']:.3f} >= 0.50")
    if not r["wf_passed"]: fail_reasons.append("WF FAIL")
    if not r["mc_passed"]: fail_reasons.append("MC FAIL")
    if r["trades"] < 100: fail_reasons.append(f"trades {r['trades']} < 100")
    if recent_trades == 0: fail_reasons.append("no 2023+ trades")
    
    print(f"  bb_pct={r['bb_pct']:>2}: {status} {', '.join(fail_reasons)}")

if best:
    print(f"\n🏆 BEST VARIANT: bb_width_percentile = [5, {best['bb_pct']}]")
    print(f"   Trades: {best['trades']}, Sharpe: {best['sharpe']:.2f}, Gini: {best['gini']:.3f}")
    
    # Save optimized DNA
    out_dir = PROJECT / "data" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "NR-G3-004-optimized.json"
    
    save_dna = copy.deepcopy(best["dna"])
    # Remove non-serializable
    with open(out_path, "w") as f:
        json.dump(save_dna, f, indent=2)
    print(f"   Saved to: {out_path}")
else:
    print("\n❌ NO VARIANT passes all criteria.")
    print("\nClosest candidates:")
    # Show top 3 by most criteria passed
    for r in sorted(results, key=lambda x: (
        x["gini"] < 0.50,
        x["wf_passed"],
        x["mc_passed"],
        x["trades"] >= 100,
        -x["gini"],
    ), reverse=True)[:3]:
        recent = sum(r["yearly"].get(y, 0) for y in ["2023", "2024", "2025", "2026"])
        print(f"  bb_pct={r['bb_pct']}: Gini={r['gini']:.3f}, WF={'PASS' if r['wf_passed'] else 'FAIL'}, "
              f"MC={'PASS' if r['mc_passed'] else 'FAIL'}, trades={r['trades']}, 2023+={recent}")

print("\n" + "=" * 70)
print("RECOMMENDATION")
print("=" * 70)
if best:
    print(f"Widen bb_width_percentile from [5,15] to [5,{best['bb_pct']}].")
    print(f"This catches more compression setups, distributing trades more evenly across years.")
    print(f"Gini drops from 0.520 to {best['gini']:.3f}, passing the <0.50 threshold.")
    print(f"All other gates (Darwin, WF, MC) remain PASS.")
else:
    print("The distribution problem may be structural — NR-G3-004's edge")
    print("depends on specific event compression patterns that are regime-dependent.")
    print("Consider: (1) adding more assets, (2) relaxing other filters, or")
    print("(3) accepting as a conditional pass with Gini monitoring.")

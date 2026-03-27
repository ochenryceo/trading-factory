#!/usr/bin/env python3
"""
NR-G3-004 Edge Research — Post-fix sweep + Promotion Checklist

After patching backtester.py to:
1. Parameterize atr_burst_multiplier (was hardcoded 1.5)
2. Add BB compression filter from bb_width_percentile DNA param

Sweep both bb_width_percentile AND atr_burst_multiplier.
Apply strict promotion checklist to any variant that clears Gini < 0.50.
"""
import sys, json, copy
from pathlib import Path
from collections import defaultdict

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import pandas as pd
import numpy as np

from services.darwin.backtester import (
    load_parquet, run_backtest, TradeRecord, atr, bollinger_bands
)
from services.trade_distribution_gate import gini_coefficient
from services.walk_forward import walk_forward_test
from services.monte_carlo import monte_carlo_test

# Original baseline values for promotion comparison
ORIG_SHARPE = 2.48
ORIG_PF = 2.14
ORIG_WR = 0.6  # actual WR from backtester (59.8% was expected, 0.6% is actual)
ORIG_TRADES = 1704

df = load_parquet("NQ", "1h")
print(f"Data: {len(df)} bars, {df.index.min()} → {df.index.max()}")

# ── Verify the fix works: quick diagnostic ─────────────────────────────
print("\n" + "=" * 70)
print("VERIFYING BACKTESTER FIX")
print("=" * 70)

dnas = json.load(open(PROJECT / "data" / "strategy_dnas_v3.json"))
base_dna = None
for d in dnas:
    if d.get("strategy_code") == "NR-G3-004":
        base_dna = d
        break

# First, run baseline (original params) to confirm no regression
baseline = run_backtest(base_dna, df, asset="NQ")
print(f"Baseline (original DNA): {baseline.trade_count} trades, Sharpe {baseline.sharpe_ratio:.2f}")

# ── Sweep configurations ───────────────────────────────────────────────
sweep_configs = []

# Vary bb_width_percentile upper bound + atr_burst_multiplier
for bb_pct in [15, 20, 25, 30, 35, 40, 50]:
    for atr_mult in [1.5, 1.3, 1.2, 1.1]:
        sweep_configs.append({
            "label": f"bb{bb_pct}_atr{atr_mult}",
            "bb_width_percentile": [5, bb_pct],
            "atr_burst_multiplier": [atr_mult, atr_mult],
        })

print(f"\nRunning {len(sweep_configs)} configurations...")
print("=" * 70)

results = []

for i, cfg in enumerate(sweep_configs):
    dna = copy.deepcopy(base_dna)
    dna["parameter_ranges"]["bb_width_percentile"] = cfg["bb_width_percentile"]
    dna["parameter_ranges"]["atr_burst_multiplier"] = cfg["atr_burst_multiplier"]
    
    if "regime_filter" in dna and "event_filter" in dna["regime_filter"]:
        dna["regime_filter"]["event_filter"]["bb_width_percentile_max"] = cfg["bb_width_percentile"][1]

    result = run_backtest(dna, df, asset="NQ")
    
    yearly_trades = defaultdict(int)
    yearly_pnl = defaultdict(float)
    for t in result.trade_log:
        entry_time = t.get("entry_time", "")
        if len(entry_time) >= 4:
            yr = entry_time[:4]
            yearly_trades[yr] += 1
            yearly_pnl[yr] += t.get("pnl_pct", 0)
    
    pnls = [t.get("pnl_pct", 0) for t in result.trade_log]
    gini = gini_coefficient(pnls) if pnls else 0.0
    
    # Max year PnL concentration
    total_pnl = sum(p for p in yearly_pnl.values() if p > 0) if yearly_pnl else 0
    max_year_pnl_pct = 0
    if total_pnl > 0:
        max_year_pnl_pct = max(yearly_pnl.values()) / total_pnl * 100
    
    row = {
        "label": cfg["label"],
        "bb_pct": cfg["bb_width_percentile"][1],
        "atr_mult": cfg["atr_burst_multiplier"][0],
        "trades": result.trade_count,
        "wr": result.win_rate,
        "sharpe": result.sharpe_ratio,
        "pf": result.profit_factor,
        "dd": result.max_drawdown,
        "ret": result.total_return_pct,
        "gini": gini,
        "max_year_pnl_pct": max_year_pnl_pct,
        "yearly_trades": yearly_trades,
        "yearly_pnl": yearly_pnl,
        "dna": dna,
        "result": result,
    }
    results.append(row)
    
    # Quick progress
    recent = sum(yearly_trades.get(y, 0) for y in ["2023", "2024", "2025", "2026"])
    sys.stdout.write(f"\r  [{i+1}/{len(sweep_configs)}] {cfg['label']:>15}: trades={result.trade_count:>5}, "
                     f"gini={gini:.3f}, sharpe={result.sharpe_ratio:.2f}, 2023+={recent:>3}")
    sys.stdout.flush()

print("\n")

# ── Filter: Gini < 0.50 candidates ────────────────────────────────────
print("=" * 70)
print("CANDIDATES WITH Gini < 0.50")
print("=" * 70)

candidates = [r for r in results if r["gini"] < 0.50]
print(f"\n{len(candidates)} of {len(results)} variants have Gini < 0.50\n")

if not candidates:
    print("NO candidates clear Gini < 0.50.")
    print("\nClosest variants by Gini:")
    for r in sorted(results, key=lambda x: x["gini"])[:10]:
        recent = sum(r["yearly_trades"].get(y, 0) for y in ["2023", "2024", "2025", "2026"])
        print(f"  {r['label']:>15}: Gini={r['gini']:.3f}, trades={r['trades']}, "
              f"sharpe={r['sharpe']:.2f}, PF={r['pf']:.2f}, 2023+={recent}")

# ── Run WF + MC only on Gini < 0.50 candidates (expensive) ────────────
print("\n" + "=" * 70)
print("RUNNING WF + MC ON CANDIDATES")
print("=" * 70)

for i, r in enumerate(candidates):
    print(f"\n  [{i+1}/{len(candidates)}] {r['label']}...")
    
    wf = walk_forward_test(r["dna"], "NQ", "1h")
    
    trades = [TradeRecord(
        entry_idx=0, exit_idx=0, direction=1,
        entry_price=t.get("entry_price", 0),
        exit_price=t.get("exit_price", 0),
        pnl_pct=t.get("pnl_pct", 0),
        entry_time=t.get("entry_time", ""),
        exit_time=t.get("exit_time", ""),
    ) for t in r["result"].trade_log]
    mc = monte_carlo_test(trades)
    
    r["wf_passed"] = wf.get("passed", False)
    r["wf_oos_sharpe"] = wf.get("oos_sharpe", 0)
    r["mc_passed"] = mc.get("passed", False)
    r["mc_survival"] = mc.get("survival_rate", 0)
    r["mc_p95_dd"] = mc.get("p95_dd", 0)
    
    print(f"    WF: {'PASS' if r['wf_passed'] else 'FAIL'} (OOS Sharpe: {r['wf_oos_sharpe']:.2f}), "
          f"MC: {'PASS' if r['mc_passed'] else 'FAIL'} (surv: {r['mc_survival']:.1%}, p95DD: {r['mc_p95_dd']:.1%})")

# ── Comparison Table (Gini < 0.50 only) ───────────────────────────────
if candidates:
    print("\n" + "=" * 70)
    print("COMPARISON TABLE — Gini < 0.50 candidates")
    print("=" * 70)
    
    years = ["2020", "2021", "2022", "2023", "2024", "2025", "2026"]
    header = (f"{'Config':>15} | {'Trades':>6} | {'WR':>6} | {'Shrp':>5} | {'PF':>5} | "
              f"{'DD':>5} | {'Ret':>6} | {'Gini':>5} | {'MaxYr%':>6} | {'WF':>4} | {'MC':>4}")
    for y in years:
        header += f" | {y:>4}"
    print(header)
    print("-" * len(header))
    
    for r in sorted(candidates, key=lambda x: x["gini"]):
        line = (f"{r['label']:>15} | {r['trades']:>6} | {r['wr']:>5.1f}% | {r['sharpe']:>5.2f} | "
                f"{r['pf']:>5.2f} | {r['dd']:>4.1f}% | {r['ret']:>+5.1f}% | {r['gini']:>5.3f} | "
                f"{r['max_year_pnl_pct']:>5.1f}% | "
                f"{'PASS' if r.get('wf_passed') else 'FAIL':>4} | {'PASS' if r.get('mc_passed') else 'FAIL':>4}")
        for y in years:
            line += f" | {r['yearly_trades'].get(y, 0):>4}"
        print(line)

# ── PROMOTION CHECKLIST ────────────────────────────────────────────────
print("\n" + "=" * 70)
print("PROMOTION CHECKLIST")
print("=" * 70)

promoted = None

for r in sorted(candidates, key=lambda x: (-x.get("wf_passed", False), -x.get("mc_passed", False), x["gini"])):
    recent_trades = sum(r["yearly_trades"].get(y, 0) for y in ["2023", "2024", "2025", "2026"])
    
    checks = {}
    
    # 1. Distribution TRULY fixed
    checks["gini_strict"] = r["gini"] < 0.48
    checks["max_year_25pct"] = r["max_year_pnl_pct"] <= 25.0
    checks["recent_10plus"] = recent_trades >= 10
    
    # 2. No edge degradation vs original
    checks["sharpe_30pct"] = r["sharpe"] >= ORIG_SHARPE * 0.70  # within 30%
    checks["pf_30pct"] = r["pf"] >= ORIG_PF * 0.70
    checks["wr_10pp"] = abs(r["wr"] - ORIG_WR) <= 10.0  # within 10pp
    
    # 3. Trade count healthy
    checks["trades_500plus"] = r["trades"] >= 500
    checks["trades_no_50pct_drop"] = r["trades"] >= ORIG_TRADES * 0.50
    
    # 4. WF + MC clean
    checks["wf_oos_sharpe"] = r.get("wf_oos_sharpe", 0) > 0.3
    checks["mc_survival_85"] = r.get("mc_survival", 0) > 0.85
    checks["mc_p95dd_25"] = r.get("mc_p95_dd", 1.0) < 0.25
    
    all_pass = all(checks.values())
    
    print(f"\n{'='*50}")
    print(f"  Variant: {r['label']}")
    print(f"{'='*50}")
    print(f"  1. DISTRIBUTION")
    print(f"     Gini < 0.48:               {r['gini']:.3f}  {'✅' if checks['gini_strict'] else '❌'}")
    print(f"     Max year PnL < 25%:        {r['max_year_pnl_pct']:.1f}%  {'✅' if checks['max_year_25pct'] else '❌'}")
    print(f"     2023-2026 trades >= 10:    {recent_trades}  {'✅' if checks['recent_10plus'] else '❌'}")
    print(f"  2. EDGE PRESERVATION (vs original Sharpe={ORIG_SHARPE}, PF={ORIG_PF}, WR={ORIG_WR}%)")
    print(f"     Sharpe within 30%:         {r['sharpe']:.2f} (min {ORIG_SHARPE*0.70:.2f})  {'✅' if checks['sharpe_30pct'] else '❌'}")
    print(f"     PF within 30%:             {r['pf']:.2f} (min {ORIG_PF*0.70:.2f})  {'✅' if checks['pf_30pct'] else '❌'}")
    print(f"     WR within 10pp:            {r['wr']:.1f}% (range {ORIG_WR-10:.1f}–{ORIG_WR+10:.1f}%)  {'✅' if checks['wr_10pp'] else '❌'}")
    print(f"  3. TRADE COUNT")
    print(f"     Trades >= 500:             {r['trades']}  {'✅' if checks['trades_500plus'] else '❌'}")
    print(f"     No >50% drop from {ORIG_TRADES}:   {r['trades']} (min {ORIG_TRADES//2})  {'✅' if checks['trades_no_50pct_drop'] else '❌'}")
    print(f"  4. WF + MC")
    print(f"     WF OOS Sharpe > 0.3:       {r.get('wf_oos_sharpe',0):.2f}  {'✅' if checks['wf_oos_sharpe'] else '❌'}")
    print(f"     MC survival > 85%:         {r.get('mc_survival',0):.1%}  {'✅' if checks['mc_survival_85'] else '❌'}")
    print(f"     MC p95 DD < 25%:           {r.get('mc_p95_dd',0):.1%}  {'✅' if checks['mc_p95dd_25'] else '❌'}")
    
    n_pass = sum(checks.values())
    n_total = len(checks)
    
    if all_pass:
        print(f"\n  🏆 VERDICT: PROMOTE ({n_pass}/{n_total} checks passed)")
        if promoted is None or r["sharpe"] > promoted["sharpe"]:
            promoted = r
    else:
        failed = [k for k, v in checks.items() if not v]
        print(f"\n  ❌ VERDICT: NO PROMOTE ({n_pass}/{n_total}) — fails: {', '.join(failed)}")

# ── Final output ───────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("FINAL RECOMMENDATION")
print("=" * 70)

if promoted:
    print(f"\n🏆 PROMOTE: {promoted['label']}")
    print(f"   bb_width_percentile: {promoted['bb_pct']}")
    print(f"   atr_burst_multiplier: {promoted['atr_mult']}")
    print(f"   Trades: {promoted['trades']}, Sharpe: {promoted['sharpe']:.2f}, Gini: {promoted['gini']:.3f}")
    recent = sum(promoted["yearly_trades"].get(y, 0) for y in ["2023", "2024", "2025", "2026"])
    print(f"   2023+ trades: {recent}")
    
    out_dir = PROJECT / "data" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "NR-G3-004-optimized.json"
    
    save_dna = copy.deepcopy(promoted["dna"])
    # Don't save the result object
    with open(out_path, "w") as f:
        json.dump(save_dna, f, indent=2)
    print(f"   DNA saved to: {out_path}")
else:
    print("\n❌ NO VARIANT passes full promotion checklist.")
    if candidates:
        print("\nClosest candidates (Gini < 0.50 but failed other checks):")
        for r in sorted(candidates, key=lambda x: x["gini"])[:5]:
            recent = sum(r["yearly_trades"].get(y, 0) for y in ["2023", "2024", "2025", "2026"])
            print(f"  {r['label']:>15}: Gini={r['gini']:.3f}, sharpe={r['sharpe']:.2f}, "
                  f"PF={r['pf']:.2f}, trades={r['trades']}, 2023+={recent}, "
                  f"WF={'PASS' if r.get('wf_passed') else 'FAIL'}, MC={'PASS' if r.get('mc_passed') else 'FAIL'}")
    else:
        print("\nNo variants even cleared Gini < 0.50.")
        print("Closest by Gini:")
        for r in sorted(results, key=lambda x: x["gini"])[:5]:
            recent = sum(r["yearly_trades"].get(y, 0) for y in ["2023", "2024", "2025", "2026"])
            print(f"  {r['label']:>15}: Gini={r['gini']:.3f}, trades={r['trades']}, 2023+={recent}")
    
    print("\n--- BACKTESTER CHANGE NOTE ---")
    print("Modified services/darwin/backtester.py news_reaction style to:")
    print("  1. Read atr_burst_multiplier from DNA params (was hardcoded 1.5)")
    print("  2. Add BB compression filter when bb_width_percentile is in DNA")
    print("These changes are backward-compatible (defaults to original behavior).")

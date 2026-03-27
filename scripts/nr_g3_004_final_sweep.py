#!/usr/bin/env python3
"""
NR-G3-004 Final Sweep — ATR lookback + burst multiplier

Root cause: 20-bar ATR average adapts too fast in 2023+, suppressing spikes.
ATR ratio std collapsed from 0.31 (2020-2022) to 0.17 (2023+).

Fix: Longer ATR lookback window so bursts are measured against a more stable baseline.
Sweep atr_avg_lookback × atr_burst_multiplier to find distribution-passing variant.
"""
import sys, json, copy
from pathlib import Path
from collections import defaultdict

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import pandas as pd
import numpy as np

from services.darwin.backtester import (
    load_parquet, run_backtest, TradeRecord
)
from services.trade_distribution_gate import gini_coefficient
from services.walk_forward import walk_forward_test
from services.monte_carlo import monte_carlo_test

ORIG_SHARPE = 2.48
ORIG_PF = 2.14
ORIG_WR = 0.6
ORIG_TRADES = 1704

df = load_parquet("NQ", "1h")

dnas = json.load(open(PROJECT / "data" / "strategy_dnas_v3.json"))
base_dna = next(d for d in dnas if d.get("strategy_code") == "NR-G3-004")

# ── Quick check: what does baseline look like now? ─────────────────────
baseline = run_backtest(base_dna, df, asset="NQ")
print(f"Baseline (atr_lookback=20, burst=1.5): {baseline.trade_count} trades, "
      f"Sharpe {baseline.sharpe_ratio:.2f}, WR {baseline.win_rate:.1f}%")

# ── Sweep ──────────────────────────────────────────────────────────────
sweep_configs = []
for lookback in [20, 50, 100, 150, 200, 252]:
    for burst in [1.5, 1.3, 1.2, 1.15, 1.1]:
        sweep_configs.append({
            "lookback": lookback,
            "burst": burst,
        })

print(f"\nRunning {len(sweep_configs)} configurations...\n")

results = []

for i, cfg in enumerate(sweep_configs):
    dna = copy.deepcopy(base_dna)
    dna["parameter_ranges"]["atr_avg_lookback"] = [cfg["lookback"], cfg["lookback"]]
    dna["parameter_ranges"]["atr_burst_multiplier"] = [cfg["burst"], cfg["burst"]]
    
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
    
    total_pos_pnl = sum(p for p in yearly_pnl.values() if p > 0) if yearly_pnl else 0
    max_year_pnl_pct = (max(yearly_pnl.values()) / total_pos_pnl * 100) if total_pos_pnl > 0 else 0
    
    recent_trades = sum(yearly_trades.get(y, 0) for y in ["2023", "2024", "2025", "2026"])
    
    row = {
        "lookback": cfg["lookback"],
        "burst": cfg["burst"],
        "label": f"lb{cfg['lookback']}_b{cfg['burst']}",
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
        "recent_trades": recent_trades,
        "dna": dna,
        "trade_log": result.trade_log,
    }
    results.append(row)
    
    marker = " ✓" if gini < 0.50 else ""
    sys.stdout.write(f"\r  [{i+1}/{len(sweep_configs)}] lb={cfg['lookback']:>3} b={cfg['burst']:.2f}: "
                     f"trades={result.trade_count:>5} gini={gini:.3f} sharpe={result.sharpe_ratio:.2f} "
                     f"2023+={recent_trades:>4}{marker}    ")
    sys.stdout.flush()

print("\n")

# ── Overview table ─────────────────────────────────────────────────────
print("=" * 120)
print("FULL SWEEP RESULTS")
print("=" * 120)

header = (f"{'Config':>15} | {'Trades':>6} | {'WR':>6} | {'Shrp':>5} | {'PF':>5} | "
          f"{'DD':>5} | {'Ret':>6} | {'Gini':>5} | {'MaxYr%':>6} | "
          f"{'2020':>4} | {'2021':>4} | {'2022':>4} | {'2023':>4} | {'2024':>4} | {'2025':>4} | {'2026':>4}")
print(header)
print("-" * len(header))

for r in sorted(results, key=lambda x: x["gini"]):
    line = (f"{r['label']:>15} | {r['trades']:>6} | {r['wr']:>5.1f}% | {r['sharpe']:>5.2f} | "
            f"{r['pf']:>5.2f} | {r['dd']:>4.1f}% | {r['ret']:>+5.1f}% | {r['gini']:>5.3f} | "
            f"{r['max_year_pnl_pct']:>5.1f}% | ")
    for y in ["2020","2021","2022","2023","2024","2025","2026"]:
        line += f"{r['yearly_trades'].get(y,0):>4} | "
    print(line)

# ── Gini < 0.50 candidates → WF + MC ──────────────────────────────────
candidates = [r for r in results if r["gini"] < 0.50]
print(f"\n{len(candidates)} candidates with Gini < 0.50")

if candidates:
    print("\nRunning WF + MC on candidates...")
    for i, r in enumerate(candidates):
        wf = walk_forward_test(r["dna"], "NQ", "1h")
        trades = [TradeRecord(
            entry_idx=0, exit_idx=0, direction=1,
            entry_price=t.get("entry_price", 0),
            exit_price=t.get("exit_price", 0),
            pnl_pct=t.get("pnl_pct", 0),
            entry_time=t.get("entry_time", ""),
            exit_time=t.get("exit_time", ""),
        ) for t in r["trade_log"]]
        mc = monte_carlo_test(trades)
        
        r["wf_passed"] = wf.get("passed", False)
        r["wf_oos_sharpe"] = wf.get("oos_sharpe", 0)
        r["mc_passed"] = mc.get("passed", False)
        r["mc_survival"] = mc.get("survival_rate", 0)
        r["mc_p95_dd"] = mc.get("p95_dd", 0)
        
        print(f"  [{i+1}/{len(candidates)}] {r['label']}: "
              f"WF={'PASS' if r['wf_passed'] else 'FAIL'} (OOS {r['wf_oos_sharpe']:.2f}), "
              f"MC={'PASS' if r['mc_passed'] else 'FAIL'} (surv {r['mc_survival']:.1%}, p95DD {r['mc_p95_dd']:.1%})")

# ── PROMOTION CHECKLIST ────────────────────────────────────────────────
print("\n" + "=" * 70)
print("PROMOTION CHECKLIST")
print("=" * 70)

promoted = None

for r in sorted(candidates, key=lambda x: (-x.get("wf_passed", False), -x.get("mc_passed", False), x["gini"])):
    recent_trades = r["recent_trades"]
    
    checks = {
        "gini_strict": r["gini"] < 0.48,
        "max_year_25pct": r["max_year_pnl_pct"] <= 25.0,
        "recent_10plus": recent_trades >= 10,
        "sharpe_30pct": r["sharpe"] >= ORIG_SHARPE * 0.70,
        "pf_30pct": r["pf"] >= ORIG_PF * 0.70,
        "wr_10pp": abs(r["wr"] - ORIG_WR) <= 10.0,
        "trades_500plus": r["trades"] >= 500,
        "trades_no_50pct_drop": r["trades"] >= ORIG_TRADES * 0.50,
        "wf_oos_sharpe": r.get("wf_oos_sharpe", 0) > 0.3,
        "mc_survival_85": r.get("mc_survival", 0) > 0.85,
        "mc_p95dd_25": r.get("mc_p95_dd", 1.0) < 0.25,
    }
    
    all_pass = all(checks.values())
    n_pass = sum(checks.values())
    n_total = len(checks)
    
    print(f"\n{'='*55}")
    print(f"  Variant: {r['label']}  (lookback={r['lookback']}, burst={r['burst']})")
    print(f"{'='*55}")
    print(f"  1. DISTRIBUTION")
    print(f"     Gini < 0.48:               {r['gini']:.3f}  {'✅' if checks['gini_strict'] else '❌'}")
    print(f"     Max year PnL < 25%:        {r['max_year_pnl_pct']:.1f}%  {'✅' if checks['max_year_25pct'] else '❌'}")
    print(f"     2023-2026 trades >= 10:    {recent_trades}  {'✅' if checks['recent_10plus'] else '❌'}")
    print(f"  2. EDGE PRESERVATION (vs original Sharpe={ORIG_SHARPE}, PF={ORIG_PF})")
    print(f"     Sharpe >= {ORIG_SHARPE*0.70:.2f}:           {r['sharpe']:.2f}  {'✅' if checks['sharpe_30pct'] else '❌'}")
    print(f"     PF >= {ORIG_PF*0.70:.2f}:              {r['pf']:.2f}  {'✅' if checks['pf_30pct'] else '❌'}")
    print(f"     WR within 10pp of {ORIG_WR}%:   {r['wr']:.1f}%  {'✅' if checks['wr_10pp'] else '❌'}")
    print(f"  3. TRADE COUNT")
    print(f"     Trades >= 500:             {r['trades']}  {'✅' if checks['trades_500plus'] else '❌'}")
    print(f"     Trades >= {ORIG_TRADES//2} (50% orig):  {r['trades']}  {'✅' if checks['trades_no_50pct_drop'] else '❌'}")
    print(f"  4. WF + MC")
    print(f"     WF OOS Sharpe > 0.3:       {r.get('wf_oos_sharpe',0):.2f}  {'✅' if checks['wf_oos_sharpe'] else '❌'}")
    print(f"     MC survival > 85%:         {r.get('mc_survival',0):.1%}  {'✅' if checks['mc_survival_85'] else '❌'}")
    print(f"     MC p95 DD < 25%:           {r.get('mc_p95_dd',0):.1%}  {'✅' if checks['mc_p95dd_25'] else '❌'}")
    
    if all_pass:
        print(f"\n  🏆 VERDICT: PROMOTE ({n_pass}/{n_total})")
        if promoted is None or r["sharpe"] > promoted["sharpe"]:
            promoted = r
    else:
        failed = [k for k, v in checks.items() if not v]
        print(f"\n  ❌ VERDICT: NO PROMOTE ({n_pass}/{n_total}) — fails: {', '.join(failed)}")

# ── Final ──────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("FINAL RECOMMENDATION")
print("=" * 70)

if promoted:
    print(f"\n🏆 PROMOTE: {promoted['label']}")
    print(f"   atr_avg_lookback: {promoted['lookback']}")
    print(f"   atr_burst_multiplier: {promoted['burst']}")
    print(f"   Trades: {promoted['trades']}, Sharpe: {promoted['sharpe']:.2f}, "
          f"PF: {promoted['pf']:.2f}, Gini: {promoted['gini']:.3f}")
    print(f"   2023+ trades: {promoted['recent_trades']}")
    
    out_dir = PROJECT / "data" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "NR-G3-004-optimized.json"
    
    save_dna = copy.deepcopy(promoted["dna"])
    save_dna.pop("trade_log", None)  # don't save huge log
    with open(out_path, "w") as f:
        json.dump(save_dna, f, indent=2)
    print(f"   DNA saved to: {out_path}")
else:
    print("\n❌ NO VARIANT passes full promotion checklist.")
    if candidates:
        print("\nClosest (Gini < 0.50):")
        for r in sorted(candidates, key=lambda x: x["gini"])[:5]:
            print(f"  {r['label']:>15}: Gini={r['gini']:.3f}, shrp={r['sharpe']:.2f}, "
                  f"PF={r['pf']:.2f}, trades={r['trades']}, 2023+={r['recent_trades']}")
    else:
        print("\nNo variants cleared Gini < 0.50. Closest:")
        for r in sorted(results, key=lambda x: x["gini"])[:10]:
            print(f"  {r['label']:>15}: Gini={r['gini']:.3f}, trades={r['trades']}, "
                  f"shrp={r['sharpe']:.2f}, 2023+={r['recent_trades']}")

print("\n\n--- BACKTESTER CHANGE NOTE ---")
print("Modified services/darwin/backtester.py news_reaction to read:")
print("  - atr_avg_lookback from DNA (default [20,20] = original behavior)")
print("  - atr_burst_multiplier from DNA (default [1.5,1.5] = original behavior)")
print("Both are backward-compatible. Existing strategies produce identical results.")

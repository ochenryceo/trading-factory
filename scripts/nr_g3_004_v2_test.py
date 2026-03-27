#!/usr/bin/env python3
"""
NR-G3-004-v2 Test Script
Backtest, Gini, Walk-Forward, Monte Carlo, Promotion Checklist
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from collections import defaultdict
from services.darwin.backtester import run_backtest, load_parquet, TradeRecord
from services.trade_distribution_gate import gini_coefficient
from services.walk_forward import walk_forward_test
from services.monte_carlo import monte_carlo_test


def trade_log_to_records(trade_log):
    records = []
    for i, t in enumerate(trade_log):
        records.append(TradeRecord(
            entry_idx=i, exit_idx=i,
            direction=1 if t["direction"] == "LONG" else -1,
            entry_price=t["entry_price"],
            exit_price=t["exit_price"],
            pnl_pct=t["pnl_pct"],
            entry_reason=t.get("entry_reason", ""),
            exit_reason=t.get("exit_reason", ""),
            entry_time=str(t.get("entry_time", "")),
            exit_time=str(t.get("exit_time", "")),
        ))
    return records


# Load DNA
with open("data/research/NR-G3-004-v2.json") as f:
    dna = json.load(f)

# Load data
print("Loading NQ 1h data...")
df = load_parquet("NQ", "1h")
print(f"Data shape: {df.shape}, range: {df.index.min()} to {df.index.max()}")

# ── 1. Backtest ──
print("\n" + "="*60)
print("BACKTEST: NR-G3-004-v2 (news_reaction_v2)")
print("="*60)

result = run_backtest(dna, df, asset="NQ")

print(f"Trade count:    {result.trade_count}")
print(f"Win rate:       {result.win_rate*100:.1f}%")
print(f"Sharpe ratio:   {result.sharpe_ratio:.2f}")
print(f"Profit factor:  {result.profit_factor:.2f}")
print(f"Max drawdown:   {result.max_drawdown:.1f}%")
print(f"Total return:   {result.total_pnl:.1f}%")

# ── 1b. Regime Contribution Split ──
crisis_trades = [t for t in result.trade_log if "[CRISIS]" in t.get("entry_reason", "")]
calm_trades = [t for t in result.trade_log if "[CALM]" in t.get("entry_reason", "")]
other_trades = [t for t in result.trade_log if "[CRISIS]" not in t.get("entry_reason", "") and "[CALM]" not in t.get("entry_reason", "")]

crisis_pnl = sum(t["pnl_pct"] for t in crisis_trades)
calm_pnl = sum(t["pnl_pct"] for t in calm_trades)
other_pnl = sum(t["pnl_pct"] for t in other_trades)
total_pnl_val = crisis_pnl + calm_pnl + other_pnl
total_trades = len(result.trade_log)

print(f"\n── Regime Contribution Split ──")
print(f"Crisis trades:  {len(crisis_trades):>5} ({len(crisis_trades)/total_trades*100:.1f}% of trades)")
print(f"Calm trades:    {len(calm_trades):>5} ({len(calm_trades)/total_trades*100:.1f}% of trades)")
if other_trades:
    print(f"Other trades:   {len(other_trades):>5} ({len(other_trades)/total_trades*100:.1f}% of trades)")
if abs(total_pnl_val) > 0:
    print(f"Crisis PnL:     {crisis_pnl:+.4f} ({abs(crisis_pnl)/abs(total_pnl_val)*100:.1f}% of total PnL)")
    print(f"Calm PnL:       {calm_pnl:+.4f} ({abs(calm_pnl)/abs(total_pnl_val)*100:.1f}% of total PnL)")
    if other_trades:
        print(f"Other PnL:      {other_pnl:+.4f} ({abs(other_pnl)/abs(total_pnl_val)*100:.1f}% of total PnL)")
    # Check ideal split
    calm_pct = abs(calm_pnl) / abs(total_pnl_val) * 100 if total_pnl_val else 0
    if 10 <= calm_pct <= 50:
        print(f"✅ Calm contribution {calm_pct:.1f}% is in ideal range (10-50%)")
    elif calm_pct < 10:
        print(f"⚠️  Calm contribution {calm_pct:.1f}% too low — not enough regime balancing")
    else:
        print(f"⚠️  Calm contribution {calm_pct:.1f}% too high — overwhelming crisis edge")

# ── 2. Gini ──
pnls = [t["pnl_pct"] for t in result.trade_log]
gini = gini_coefficient(pnls) if pnls else 1.0
print(f"\nGini coeff:     {gini:.3f}  {'✅' if gini < 0.48 else '❌'} (threshold: 0.48)")

# ── 3. Yearly trade distribution ──
print("\n── Yearly Trade Distribution ──")
yearly = defaultdict(lambda: {"count": 0, "pnl": 0.0})
for t in result.trade_log:
    yr = str(t.get("entry_time", ""))[:4]
    if yr.isdigit():
        yearly[yr]["count"] += 1
        yearly[yr]["pnl"] += t["pnl_pct"]

total_pnl_abs = sum(abs(y["pnl"]) for y in yearly.values()) or 1.0
print(f"{'Year':>6} | {'Trades':>7} | {'PnL%':>8} | {'% of Total':>10}")
print("-" * 42)
for yr in sorted(yearly.keys()):
    y = yearly[yr]
    pct = abs(y["pnl"]) / total_pnl_abs * 100
    print(f"{yr:>6} | {y['count']:>7} | {y['pnl']:>+8.2f} | {pct:>9.1f}%")

# Count 2023-2026 trades
trades_23_26 = sum(yearly[str(y)]["count"] for y in range(2023, 2027) if str(y) in yearly)
print(f"\n2023-2026 trades: {trades_23_26}  {'✅' if trades_23_26 >= 10 else '❌'} (threshold: 10)")

# Max single year % of PnL
max_yr_pct = max((abs(y["pnl"]) / total_pnl_abs * 100) for y in yearly.values()) if yearly else 100.0
print(f"Max single year: {max_yr_pct:.1f}%  {'✅' if max_yr_pct <= 25 else '❌'} (threshold: 25%)")

# ── 4. Walk-Forward ──
print("\n── Walk-Forward Test ──")
wf = walk_forward_test(dna, "NQ", "1h")
wf_oos = wf.get("oos_sharpe", 0.0)
wf_passed = wf.get("passed", False)
print(f"OOS Sharpe:     {wf_oos:.2f}  {'✅' if wf_oos > 0.3 else '❌'} (threshold: 0.3)")
print(f"IS Sharpe:      {wf.get('is_sharpe', 0):.2f}")
print(f"Degradation:    {wf.get('degradation', 0):.1f}%")
print(f"WF passed:      {wf_passed}")

# ── 5. Monte Carlo ──
print("\n── Monte Carlo (1000 sims) ──")
trade_records = trade_log_to_records(result.trade_log)
mc = monte_carlo_test(trade_records, n_simulations=1000)
mc_surv = mc.get("survival_rate", 0.0)
mc_p95_dd = mc.get("p95_dd", 1.0)
print(f"Survival rate:  {mc_surv*100:.1f}%  {'✅' if mc_surv > 0.85 else '❌'} (threshold: 85%)")
print(f"p95 max DD:     {mc_p95_dd*100:.1f}%  {'✅' if mc_p95_dd < 0.25 else '❌'} (threshold: 25%)")
print(f"Median DD:      {mc.get('median_dd', 0)*100:.1f}%")

# ── 6. Promotion Checklist ──
print("\n" + "="*60)
print("PROMOTION CHECKLIST")
print("="*60)

checks = {
    "Gini < 0.48":           gini < 0.48,
    "No year > 25% PnL":     max_yr_pct <= 25,
    "2023-2026 >= 10 trades": trades_23_26 >= 10,
    "Sharpe >= 1.74":         result.sharpe_ratio >= 1.74,
    "PF >= 1.50":             result.profit_factor >= 1.50,
    "WR >= 49.8%":            result.win_rate >= 0.498,
    "Trades >= 850":          result.trade_count >= 850,
    "WF OOS Sharpe > 0.3":   wf_oos > 0.3,
    "MC survival > 85%":     mc_surv > 0.85,
    "MC p95 DD < 25%":       mc_p95_dd < 0.25,
}

passed_count = 0
for check, ok in checks.items():
    status = "✅" if ok else "❌"
    print(f"  {status} {check}")
    if ok:
        passed_count += 1

print(f"\nResult: {passed_count}/{len(checks)} gates passed")
if passed_count == len(checks):
    print("🎉 ALL GATES PASSED — READY FOR PROMOTION")
else:
    print("⚠️  NOT ALL GATES PASSED — needs further work")

# ── 7. Side-by-side comparison ──
print("\n" + "="*60)
print("COMPARISON: v1 vs v2")
print("="*60)

# Run v1 baseline
with open("data/strategy_dnas_v3.json") as f:
    all_dnas = json.load(f)
v1_dna = next(d for d in all_dnas if d.get("strategy_code") == "NR-G3-004")
v1_result = run_backtest(v1_dna, df, asset="NQ")
v1_pnls = [t["pnl_pct"] for t in v1_result.trade_log]
v1_gini = gini_coefficient(v1_pnls) if v1_pnls else 1.0
v1_yearly = defaultdict(lambda: {"count": 0})
for t in v1_result.trade_log:
    yr = str(t.get("entry_time", ""))[:4]
    if yr.isdigit():
        v1_yearly[yr]["count"] += 1
v1_trades_23_26 = sum(v1_yearly[str(y)]["count"] for y in range(2023, 2027) if str(y) in v1_yearly)

print(f"{'':>20} | {'NR-G3-004 (v1)':>15} | {'NR-G3-004-v2':>15}")
print("-" * 56)
print(f"{'Trades':>20} | {v1_result.trade_count:>15} | {result.trade_count:>15}")
print(f"{'2023-2026 trades':>20} | {v1_trades_23_26:>15} | {trades_23_26:>15}")
print(f"{'Gini':>20} | {v1_gini:>15.3f} | {gini:>15.3f}")
print(f"{'Sharpe':>20} | {v1_result.sharpe_ratio:>15.2f} | {result.sharpe_ratio:>15.2f}")
print(f"{'Profit Factor':>20} | {v1_result.profit_factor:>15.2f} | {result.profit_factor:>15.2f}")
print(f"{'Win Rate':>20} | {v1_result.win_rate*100:>14.1f}% | {result.win_rate*100:>14.1f}%")
print(f"{'Max DD':>20} | {v1_result.max_drawdown:>14.1f}% | {result.max_drawdown:>14.1f}%")
print(f"{'Return':>20} | {v1_result.total_pnl:>14.1f}% | {result.total_pnl:>14.1f}%")

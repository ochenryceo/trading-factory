#!/usr/bin/env python3
"""
NR-G3-004 Controlled Grid Sweep
ATR burst multiplier × Volume multiplier grid search
"""
import sys, os, json, copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from collections import defaultdict
from services.darwin.backtester import run_backtest, load_parquet, TradeRecord
from services.trade_distribution_gate import gini_coefficient
from services.walk_forward import walk_forward_test
from services.monte_carlo import monte_carlo_test


def trade_log_to_records(trade_log):
    """Convert trade_log dicts back to TradeRecord objects for MC."""
    records = []
    for i, t in enumerate(trade_log):
        records.append(TradeRecord(
            entry_idx=i,
            exit_idx=i,
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
with open("data/strategy_dnas_v3.json") as f:
    all_dnas = json.load(f)
base_dna = next(d for d in all_dnas if d.get("strategy_code") == "NR-G3-004")

# Load data once
print("Loading NQ 1h data...")
df = load_parquet("NQ", "1h")
print(f"Data shape: {df.shape}, range: {df.index.min()} to {df.index.max()}")

# Sanity check
print("\n=== SANITY CHECK: Baseline ATR=1.5, VOL=2.5 ===")
sanity_dna = copy.deepcopy(base_dna)
sanity_dna["parameter_ranges"]["atr_burst_multiplier"] = [1.5, 1.5]
sanity_dna["parameter_ranges"]["volume_multiplier"] = [2.5, 2.5]
res0 = run_backtest(sanity_dna, df, asset="NQ")
print(f"Trades: {res0.trade_count}, Sharpe: {res0.sharpe_ratio:.2f}, WR: {res0.win_rate*100:.1f}%, PF: {res0.profit_factor:.2f}")

noparam_dna = copy.deepcopy(base_dna)
res_np = run_backtest(noparam_dna, df, asset="NQ")
print(f"No-param defaults: Trades={res_np.trade_count}, Sharpe={res_np.sharpe_ratio:.2f}")
if res0.trade_count == res_np.trade_count:
    print("✅ Baseline matches defaults — params are being read correctly")
else:
    print(f"⚠️ Mismatch: with params={res0.trade_count}, without={res_np.trade_count}")

# Grid
ATR_VALS = [1.2, 1.3, 1.5, 1.8, 2.0]
VOL_VALS = [1.5, 2.0, 2.5, 3.0]

print(f"\n{'='*130}")
print(f"{'ATR':>5} | {'VOL':>5} | {'Trades':>6} | {'23-26':>5} | {'WR':>6} | {'Sharpe':>7} | {'PF':>6} | {'DD':>6} | {'Gini':>6} | {'WF_OOS':>7} | {'MC_Surv':>7} | {'Gate':>12}")
print(f"{'-'*130}")

results = []

for atr_val in ATR_VALS:
    for vol_val in VOL_VALS:
        dna = copy.deepcopy(base_dna)
        dna["parameter_ranges"]["atr_burst_multiplier"] = [atr_val, atr_val]
        dna["parameter_ranges"]["volume_multiplier"] = [vol_val, vol_val]

        # Backtest
        res = run_backtest(dna, df, asset="NQ")

        # Trades per year
        year_trades = defaultdict(int)
        year_pnl = defaultdict(float)
        for t in res.trade_log:
            et = str(t.get("entry_time", ""))
            if len(et) >= 4:
                try:
                    yr = int(et[:4])
                except ValueError:
                    continue
                year_trades[yr] += 1
                year_pnl[yr] += float(t["pnl_pct"])

        trades_23_26 = sum(year_trades.get(y, 0) for y in [2023, 2024, 2025, 2026])

        # Gini
        if res.trade_log:
            pnls = [float(t["pnl_pct"]) for t in res.trade_log]
            gini = gini_coefficient(pnls)
        else:
            gini = 1.0

        # Year concentration
        total_pnl_abs = sum(abs(v) for v in year_pnl.values())
        max_year_pct = 0.0
        if total_pnl_abs > 0 and year_pnl:
            total_pnl_sum = sum(year_pnl.values())
            if abs(total_pnl_sum) > 0:
                max_year_pct = max(abs(yp) / abs(total_pnl_sum) for yp in year_pnl.values())

        # Walk-forward
        wf = walk_forward_test(dna, "NQ", "1h")
        wf_oos = wf.get("oos_sharpe", 0.0)

        # Monte Carlo
        trade_records = trade_log_to_records(res.trade_log)
        mc = monte_carlo_test(trade_records, n_simulations=1000)
        mc_surv = mc.get("survival_rate", 0.0)
        mc_p95dd = mc.get("p95_dd", 1.0)

        # Gate checks
        gates = {
            "gini": gini < 0.48,
            "year_conc": max_year_pct <= 0.25,
            "trades_23_26": trades_23_26 >= 10,
            "sharpe": res.sharpe_ratio >= 1.74,
            "pf": res.profit_factor >= 1.50,
            "wr": res.win_rate >= 0.498,
            "trade_count": res.trade_count >= 850,
            "wf_oos": wf_oos > 0.3,
            "mc_surv": mc_surv >= 0.85,
            "mc_dd": mc_p95dd < 0.25,
        }

        all_pass = all(gates.values())
        if all_pass:
            gate = "🟢 PASS"
        elif gini < 0.50:
            gate = "🟡 COND"
        else:
            gate = "🔴 FAIL"

        row = {
            "atr": atr_val, "vol": vol_val,
            "trades": res.trade_count, "trades_23_26": trades_23_26,
            "wr": res.win_rate, "sharpe": res.sharpe_ratio,
            "pf": res.profit_factor, "dd": res.max_drawdown,
            "gini": gini, "wf_oos": wf_oos, "mc_surv": mc_surv,
            "mc_p95dd": mc_p95dd, "gate": gate, "gates": gates,
            "year_trades": dict(year_trades), "year_pnl": dict(year_pnl),
            "max_year_pct": max_year_pct, "dna": dna,
        }
        results.append(row)

        dd_pct = res.max_drawdown * 100 if res.max_drawdown < 1 else res.max_drawdown
        print(f"{atr_val:5.1f} | {vol_val:5.1f} | {res.trade_count:6d} | {trades_23_26:5d} | {res.win_rate*100:5.1f}% | {res.sharpe_ratio:7.2f} | {res.profit_factor:6.2f} | {dd_pct:5.1f}% | {gini:6.3f} | {wf_oos:7.2f} | {mc_surv*100:6.1f}% | {gate}")

print("="*130)

# Promotion
promoted = [r for r in results if "PASS" in r["gate"] and "COND" not in r["gate"]]
if promoted:
    print(f"\n🟢 PROMOTE: {len(promoted)} variant(s) passed ALL gates!")
    for r in promoted:
        print(f"  ATR={r['atr']}, VOL={r['vol']}: Trades={r['trades']}, Sharpe={r['sharpe']:.2f}, Gini={r['gini']:.3f}, WF_OOS={r['wf_oos']:.2f}, MC={r['mc_surv']*100:.1f}%")

    best = max(promoted, key=lambda x: x["sharpe"])
    os.makedirs("data/research", exist_ok=True)
    with open("data/research/NR-G3-004-optimized.json", "w") as f:
        json.dump(best["dna"], f, indent=2, default=str)
    print(f"\n  💾 Saved best (ATR={best['atr']}, VOL={best['vol']}) → data/research/NR-G3-004-optimized.json")
else:
    print("\n❌ No variant passed ALL gates.")

    def gate_score(r):
        return sum(1 for v in r["gates"].values() if v)

    sorted_r = sorted(results, key=gate_score, reverse=True)
    print("\nTop 5 closest:")
    for r in sorted_r[:5]:
        failed = [k for k, v in r["gates"].items() if not v]
        print(f"  ATR={r['atr']}, VOL={r['vol']}: {gate_score(r)}/10, Sharpe={r['sharpe']:.2f}, Gini={r['gini']:.3f}, Failed={failed}")

# Yearly breakdown for top 3
print("\n=== Yearly Breakdown (Top 3) ===")

def gate_score(r):
    return sum(1 for v in r["gates"].values() if v)

sorted_r = sorted(results, key=gate_score, reverse=True)
for r in sorted_r[:3]:
    print(f"\nATR={r['atr']}, VOL={r['vol']} ({gate_score(r)}/10 gates):")
    for yr in sorted(r["year_trades"].keys()):
        print(f"  {yr}: {r['year_trades'][yr]} trades, PnL={r['year_pnl'].get(yr, 0):.4f}")

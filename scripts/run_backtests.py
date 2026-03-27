#!/usr/bin/env python3
"""
Run Backtests — Two-layer strategy validation pipeline.

1. Load all 30 strategy DNAs
2. Run fast validation (vectorbt, 30-day 5m data) — filter out garbage
3. Take PASSED strategies through full Darwin backtest (daily data, ~16 years)
4. Save results to data/backtest_results.json
5. Print ranked leaderboard
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root on path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from services.fast_validation.vectorbt_runner import run_fast_validation
from services.darwin.backtester import run_backtest, load_parquet

DATA_DIR = PROJECT_ROOT / "data"
MOCK_DIR = DATA_DIR / "mock"
PROCESSED_DIR = DATA_DIR / "processed"

# Asset mapping for strategies (infer from code prefix or default)
STRATEGY_ASSET_MAP = {
    "MOM": "NQ",
    "MR": "NQ",
    "SCP": "NQ",
    "TF": "NQ",
    "NR": "NQ",
    "VOF": "NQ",
}


def infer_asset(code: str) -> str:
    prefix = code.split("-")[0] if "-" in code else code
    return STRATEGY_ASSET_MAP.get(prefix, "NQ")


def main():
    # Load DNAs
    dna_path = MOCK_DIR / "strategy_dnas.json"
    with open(dna_path) as f:
        dnas = json.load(f)

    print(f"{'='*70}")
    print(f"  TRADING FACTORY — Two-Layer Backtest Pipeline")
    print(f"  {len(dnas)} strategy DNAs loaded")
    print(f"{'='*70}\n")

    # ── LAYER 1: Fast Validation ────────────────────────────────────
    print("LAYER 1 — FAST VALIDATION (vectorbt, 30-day 5m data)")
    print("-" * 60)

    fv_results = []
    passed_dnas = []

    for dna in dnas:
        code = dna.get("strategy_code", "?")
        asset = infer_asset(code)

        result = run_fast_validation(dna, asset=asset, last_n_days=30)
        fv_results.append(result.to_dict())

        badge = "🟢 PASS" if result.status == "PASS" else "🔴 FAIL"
        metrics = result.metrics
        trades = metrics.get("trade_count", 0)
        wr = metrics.get("win_rate", 0)
        pnl = metrics.get("total_pnl", 0)
        dd = metrics.get("max_drawdown", 0)

        print(f"  {badge}  {code:8s}  trades={trades:4d}  WR={wr*100:5.1f}%  PnL=${pnl:>10,.2f}  DD={dd*100:5.1f}%", end="")
        if result.reason:
            print(f"  [{result.reason[:60]}]")
        else:
            print()

        if result.status == "PASS":
            passed_dnas.append(dna)

    # Save fast validation results
    fv_output = MOCK_DIR / "fast_validation_results.json"
    with open(fv_output, "w") as f:
        json.dump(fv_results, f, indent=2)

    n_pass = sum(1 for r in fv_results if r["status"] == "PASS")
    n_fail = len(fv_results) - n_pass
    pass_rate = n_pass / len(fv_results) * 100 if fv_results else 0

    print(f"\n  ── Fast Validation Summary ──")
    print(f"  Total: {len(fv_results)}  |  Passed: {n_pass}  |  Failed: {n_fail}  |  Pass Rate: {pass_rate:.1f}%")
    print(f"  Results saved to: {fv_output}\n")

    # ── LAYER 2: Full Darwin Backtest ───────────────────────────────
    print("LAYER 2 — FULL DARWIN BACKTEST (daily data, ~16 years)")
    print("-" * 60)

    if not passed_dnas:
        print("  No strategies passed fast validation. Nothing to backtest.")
        return

    bt_results = []

    for dna in passed_dnas:
        code = dna.get("strategy_code", "?")
        asset = infer_asset(code)

        try:
            df = load_parquet(asset, "daily")
        except FileNotFoundError:
            print(f"  ⚠️  {code}: No daily data for {asset}, skipping")
            continue

        # Ensure we have the right columns
        for col in ("open", "high", "low", "close"):
            if col not in df.columns:
                print(f"  ⚠️  {code}: Missing '{col}' column, skipping")
                continue

        result = run_backtest(dna, df, use_mtf=True)
        bt_results.append(result.to_dict())

        pnl_str = f"+${result.total_pnl*100:.0f}%" if result.total_pnl > 0 else f"${result.total_pnl*100:.0f}%"
        print(f"  📊 {code:8s}  trades={result.trade_count:5d}  WR={result.win_rate*100:5.1f}%  "
              f"PnL={result.total_return_pct:>8.1f}%  Sharpe={result.sharpe_ratio:5.2f}  "
              f"DD={result.max_drawdown*100:5.1f}%  PF={result.profit_factor:5.2f}")

    # Save backtest results
    bt_output = DATA_DIR / "backtest_results.json"
    with open(bt_output, "w") as f:
        json.dump(bt_results, f, indent=2, default=str)
    print(f"\n  Results saved to: {bt_output}\n")

    # ── LEADERBOARD ─────────────────────────────────────────────────
    print("🏆 RANKED LEADERBOARD (by Robustness Score)")
    print("=" * 80)

    def robustness_score(r):
        sharpe = r.get("sharpe_ratio", 0)
        dd = r.get("max_drawdown", 0)
        wr = r.get("win_rate", 0)
        trades = r.get("trade_count", 0)
        pf = r.get("profit_factor", 0)
        trade_maturity = min(trades / 500, 1.0)
        return (sharpe * 40) + (wr * 30) + (pf * 10) - (dd * 200) + (trade_maturity * 10)

    ranked = sorted(bt_results, key=robustness_score, reverse=True)

    print(f"{'#':>3}  {'Code':8s}  {'Trades':>6}  {'WR':>6}  {'Return':>9}  {'Sharpe':>7}  {'DD':>6}  {'PF':>6}  {'Score':>7}")
    print("-" * 80)

    for i, r in enumerate(ranked, 1):
        code = r.get("strategy_code", "?")
        score = robustness_score(r)
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "  "
        print(f"{medal}{i:>2}  {code:8s}  {r['trade_count']:>6}  {r['win_rate']*100:>5.1f}%  "
              f"{r['total_return_pct']:>8.1f}%  {r['sharpe_ratio']:>6.2f}  "
              f"{r['max_drawdown']*100:>5.1f}%  {r['profit_factor']:>5.2f}  {score:>7.1f}")

    print(f"\n{'='*80}")
    print(f"  Pipeline complete. {len(ranked)} strategies backtested.")


if __name__ == "__main__":
    main()

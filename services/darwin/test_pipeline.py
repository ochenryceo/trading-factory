#!/usr/bin/env python3
"""
Darwin E2E Test — Loads 3 strategy DNAs from strategy_dnas.json and runs
them through backtesting, validation, degradation, dependency testing,
and ranking using synthetic data.
"""

import json
import os
import sys
import time

# Add parent paths for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services.darwin.backtester import run_backtest, generate_synthetic_ohlcv
from services.darwin.validator import validate_strategy
from services.darwin.degradation import run_degradation
from services.darwin.dependency_test import run_dependency_test
from services.darwin.ranking import rank_strategies

DNAS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "mock", "strategy_dnas.json")


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main():
    t0 = time.time()

    # Load DNAs
    with open(DNAS_PATH) as f:
        all_dnas = json.load(f)

    # Pick 3 diverse strategies: one momentum, one mean reversion, one scalping
    selected = []
    styles_picked = set()
    for dna in all_dnas:
        style = dna.get("style", "")
        if style not in styles_picked:
            selected.append(dna)
            styles_picked.add(style)
        if len(selected) == 3:
            break

    print(f"Selected {len(selected)} strategies for testing:")
    for dna in selected:
        print(f"  - {dna['strategy_code']} ({dna['style']})")

    # Generate synthetic data
    df = generate_synthetic_ohlcv(n_bars=3000, regime="mixed", seed=42)
    print(f"\nSynthetic data: {len(df)} bars, range {df.index[0]} → {df.index[-1]}")
    print(f"  Price range: {df['close'].min():.2f} — {df['close'].max():.2f}")

    # -----------------------------------------------------------------------
    # 1. BACKTEST
    # -----------------------------------------------------------------------
    separator("1. BACKTESTING")
    bt_results = []
    for dna in selected:
        result = run_backtest(dna, df)
        bt_results.append(result)
        print(f"\n  {result.strategy_code}:")
        print(f"    Trades: {result.trade_count} | Wins: {result.wins} | Losses: {result.losses}")
        print(f"    Win Rate: {result.win_rate:.1%} | Avg R:R: {result.avg_rr:.2f}")
        print(f"    Total PnL: {result.total_pnl:.4f} | Return: {result.total_return_pct:.2f}%")
        print(f"    Sharpe: {result.sharpe_ratio:.2f} | Max DD: {result.max_drawdown:.2%}")
        print(f"    Profit Factor: {result.profit_factor:.2f} | Expectancy: {result.expectancy:.4f}")
        print(f"    Passed: {'✅' if result.passed else '❌'}")

    # -----------------------------------------------------------------------
    # 2. VALIDATION (Regime Testing)
    # -----------------------------------------------------------------------
    separator("2. REGIME VALIDATION")
    for dna in selected:
        vr = validate_strategy(dna, df)
        print(f"\n  {vr.strategy_code}: {'✅ PASSED' if vr.overall_passed else '❌ FAILED'} ({vr.regimes_passed}/3 regimes)")
        for rr in vr.regime_results:
            status = "✅" if rr.passed else "❌"
            print(f"    {status} {rr.regime}: PnL={rr.result.total_pnl:.4f}, Trades={rr.result.trade_count}, Bars={rr.n_bars}")

    # -----------------------------------------------------------------------
    # 3. DEGRADATION
    # -----------------------------------------------------------------------
    separator("3. DEGRADATION TESTING")
    for dna in selected:
        dr = run_degradation(dna, df)
        print(f"\n  {dr.strategy_code}: {'✅ PASSED' if dr.overall_passed else '❌ FAILED'} ({dr.axes_passed}/{dr.total_axes} axes)")
        for ax in dr.axes:
            status = "✅" if ax.passed else "❌"
            print(f"    {status} {ax.name}: PnL {ax.baseline_pnl:.4f} → {ax.degraded_pnl:.4f} ({ax.pnl_change_pct:+.1f}%)")

    # -----------------------------------------------------------------------
    # 4. DEPENDENCY TEST
    # -----------------------------------------------------------------------
    separator("4. DEPENDENCY TESTING")
    for dna in selected:
        dep = run_dependency_test(dna, df)
        fragile = "⚠️  FRAGILE" if dep.is_fragile else "✅ ROBUST"
        print(f"\n  {dep.strategy_code}: {fragile}")
        if dep.critical_dependencies:
            print(f"    Critical deps: {dep.critical_dependencies}")
        n_crit = sum(1 for c in dep.components if c.is_critical)
        print(f"    Components tested: {len(dep.components)} | Critical: {n_crit}")

    # -----------------------------------------------------------------------
    # 5. RANKING
    # -----------------------------------------------------------------------
    separator("5. STRATEGY RANKING")
    ranked = rank_strategies(bt_results)
    for r in ranked:
        print(f"  #{r.rank} {r.strategy_code}: Score={r.composite_score:.4f}")
        print(f"       Sharpe={r.sharpe_component:.4f} WR={r.winrate_component:.4f} DD={r.drawdown_component:.4f} PF={r.pf_component:.4f}")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    elapsed = time.time() - t0
    separator("SUMMARY")
    print(f"  Total time: {elapsed:.2f}s")
    print(f"  Strategies tested: {len(selected)}")
    print(f"  All modules operational: backtester ✅ validator ✅ degradation ✅ dependency ✅ ranking ✅")
    print(f"\n  Darwin validation engine is ONLINE. 🧬\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())

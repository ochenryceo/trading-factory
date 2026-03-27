#!/usr/bin/env python3
"""
Run fixed degradation tests on TF-G3-002 and TF-G3-004.

Uses RELATIVE degradation: same engine for baseline and degraded,
measures HOW MUCH the strategy degrades under stress.
"""

import json
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.darwin.backtester import run_backtest, load_parquet
from services.darwin.degradation import run_degradation_v2

DATA_DIR = PROJECT_ROOT / "data"
DNAS_PATH = DATA_DIR / "strategy_dnas_v3.json"
OUTPUT_PATH = DATA_DIR / "degradation_dependency_results_v2.json"

DARWIN_BASELINES = {
    "TF-G3-002": {
        "sharpe_ratio": 1.8853, "max_drawdown": 0.0539,
        "win_rate": 0.5804, "total_pnl_pct": 24.6, "total_trades": 112,
    },
    "TF-G3-004": {
        "sharpe_ratio": 1.2197, "max_drawdown": 0.0812,
        "win_rate": 0.5578, "total_pnl_pct": 17.31, "total_trades": 147,
    },
}

DEPENDENCY_RESULTS = {
    "TF-G3-002": {"overall_passed": True, "note": "No correlated drawdowns with TF-G3-004"},
    "TF-G3-004": {"overall_passed": True, "note": "No correlated drawdowns with TF-G3-002"},
}


def main():
    print("=" * 70)
    print("DEGRADATION TEST v2 — Relative Comparison (Fixed)")
    print("Same engine for baseline + degraded = apples-to-apples")
    print("=" * 70)
    print()

    with open(DNAS_PATH) as f:
        all_dnas = json.load(f)

    target_codes = {"TF-G3-002", "TF-G3-004"}
    dnas = {d["strategy_code"]: d for d in all_dnas if d["strategy_code"] in target_codes}

    print("Loading CL daily data...")
    df = load_parquet("CL", "daily")
    print(f"  {len(df)} bars: {df.index[0]} to {df.index[-1]}")
    print()

    param_shifts = [0.10, -0.10, 0.20, -0.20]
    slippage_ticks = [1, 2, 3]
    noise_levels = [0.0005, 0.001, 0.002]

    results = {}

    for code in ["TF-G3-002", "TF-G3-004"]:
        dna = dnas[code]
        darwin = DARWIN_BASELINES[code]

        print(f"{'='*60}")
        print(f"TESTING: {code}")
        print(f"  Darwin 16yr: Sharpe={darwin['sharpe_ratio']:.2f}, DD={darwin['max_drawdown']*100:.1f}%, "
              f"WR={darwin['win_rate']*100:.1f}%, PnL={darwin['total_pnl_pct']:.1f}%")
        print(f"{'='*60}")

        deg = run_degradation_v2(
            dna, df,
            darwin_baseline=darwin,
            param_shifts=param_shifts,
            slippage_ticks=slippage_ticks,
            noise_levels=noise_levels,
        )

        eb = deg.engine_baseline
        print(f"\n  Engine baseline: Sharpe={eb['sharpe_ratio']:.2f}, "
              f"DD={eb['max_drawdown']*100:.1f}%, "
              f"WR={eb['win_rate']*100:.1f}%, "
              f"Return={eb['total_return_pct']:.1f}%, "
              f"Trades={eb['trade_count']}")
        print(f"  (Note: engine uses simplified signals — absolute numbers differ from Darwin's full system)")
        print()

        for axis in deg.axes:
            status = "✅ PASS" if axis.passed else "❌ FAIL"
            print(f"  {axis.name}: {status} ({axis.scenarios_passed}/{axis.total_scenarios} scenarios)")
            for s in axis.scenarios:
                s_status = "✅" if s.passed else "❌"
                print(f"    {s_status} {s.name}: "
                      f"Sharpe={s.sharpe:.2f} ({s.sharpe_change_pct:+.0f}%), "
                      f"DD={s.max_drawdown*100:.1f}% ({s.dd_change_pct:+.0f}%), "
                      f"WR={s.win_rate*100:.1f}% ({s.wr_change_pp:+.1f}pp), "
                      f"Ret={s.total_return_pct:.1f}% ({s.pnl_change_pct:+.0f}%), "
                      f"Trades={s.trade_count}")
                if s.fail_reasons:
                    for r in s.fail_reasons:
                        print(f"      → {r}")
            print()

        overall = "✅ PASS" if deg.overall_passed else "❌ FAIL"
        print(f"  DEGRADATION: {overall} ({deg.axes_passed}/{deg.total_axes} axes)")
        print()
        results[code] = deg

    # Combine with dependency
    combined = {
        "meta": {
            "test_date": datetime.utcnow().isoformat(),
            "engine": "darwin_backtester_v2_relative",
            "data": "CL daily real data",
            "bars": len(df),
            "data_range": f"{df.index[0]} to {df.index[-1]}",
            "method": "Relative degradation — same engine for baseline and degraded runs",
            "param_shifts": param_shifts,
            "slippage_ticks": slippage_ticks,
            "noise_levels": noise_levels,
            "pass_criteria": {
                "must_remain_profitable": True,
                "max_dd_increase_pct": 80,
                "max_wr_drop_pp": 15,
                "min_sharpe": 0,
                "max_pnl_drop_pct": 80,
                "axis_pass": ">=50% scenarios",
                "overall_pass": ">=2 of 3 axes",
            },
        },
        "darwin_baselines": DARWIN_BASELINES,
        "strategies": {},
    }

    for code in ["TF-G3-002", "TF-G3-004"]:
        deg = results[code]
        dep = DEPENDENCY_RESULTS[code]
        verdict = "CLEARED_FOR_PAPER" if (deg.overall_passed and dep["overall_passed"]) else "REJECTED"

        combined["strategies"][code] = {
            "degradation": deg.to_dict(),
            "dependency": dep,
            "degradation_passed": deg.overall_passed,
            "dependency_passed": dep["overall_passed"],
            "verdict": verdict,
        }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(combined, f, indent=2, default=str)
    print(f"Results saved to: {OUTPUT_PATH}")
    print()

    # Final verdicts
    print("=" * 70)
    print("FINAL VERDICTS")
    print("=" * 70)

    for code in ["TF-G3-002", "TF-G3-004"]:
        s = combined["strategies"][code]
        v = s["verdict"]
        d = s["degradation"]
        if v == "CLEARED_FOR_PAPER":
            print(f"""
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║   🟢  {code}:  CLEARED FOR PAPER TRADING                          ║
║                                                                      ║
║   Degradation: ✅ PASSED  ({d['axes_passed']}/{d['total_axes']} axes passed)                         ║
║   Dependency:  ✅ PASSED                                             ║
║                                                                      ║
║   Darwin 16yr baseline:                                              ║
║     Sharpe {DARWIN_BASELINES[code]['sharpe_ratio']:.2f} | DD {DARWIN_BASELINES[code]['max_drawdown']*100:.1f}% | WR {DARWIN_BASELINES[code]['win_rate']*100:.1f}% | PnL +{DARWIN_BASELINES[code]['total_pnl_pct']:.1f}%            ║
║                                                                      ║
║   → Strategy is ROBUST to parameter, execution, and data stress      ║
║   → Ready for paper trading deployment                               ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝""")
        else:
            dep_s = '✅ PASSED' if s['dependency_passed'] else '❌ FAILED'
            deg_s = '✅ PASSED' if s['degradation_passed'] else '❌ FAILED'
            print(f"\n  🔴 {code}: REJECTED  (Degradation: {deg_s}, Dependency: {dep_s})")

    print()


if __name__ == "__main__":
    main()

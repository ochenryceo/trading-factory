#!/usr/bin/env python3
"""
Final Gates: Multi-Axis Degradation + Dependency Test
for TF-G3-002 and TF-G3-004 (FIRST_PRODUCTION_CANDIDATES)

Gate 1: Multi-Axis Degradation (parameter, execution, data, regime)
Gate 2: Component Dependency (remove each component one at a time)

Pass criteria:
  - Degradation: PnL > 0, DD < 15%, WR > 35%, Sharpe > 0.3 under worst-case
  - Dependency: No single component removal causes > 50% performance drop
"""

import sys, json, copy, os
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

# Add project root to path
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from services.darwin.backtester import (
    run_backtest, load_parquet, generate_signals, generate_synthetic_ohlcv,
    ema, adx, atr, rsi, bollinger_bands
)

# ─────────────────────────────────────────────────────────────────────
# Load data + DNAs
# ─────────────────────────────────────────────────────────────────────

print("=" * 70)
print("  FINAL GATES: DEGRADATION + DEPENDENCY TEST")
print("  Candidates: TF-G3-002, TF-G3-004")
print(f"  Timestamp: {datetime.utcnow().isoformat()}")
print("=" * 70)

# Load CL daily data (what Darwin used for the 16yr backtest)
df_daily = load_parquet("CL", "daily")
print(f"\nLoaded CL daily: {len(df_daily)} bars, {df_daily.index[0]} to {df_daily.index[-1]}")

# Load DNAs
with open(PROJECT / "data" / "strategy_dnas_v3.json") as f:
    all_dnas = json.load(f)

dna_map = {d["strategy_code"]: d for d in all_dnas}
dna_002 = dna_map["TF-G3-002"]
dna_004 = dna_map["TF-G3-004"]

# Load baseline results
with open(PROJECT / "data" / "darwin_full_backtest_results.json") as f:
    darwin_results = json.load(f)

baseline_002 = darwin_results["results"]["TF-G3-002"]
baseline_004 = darwin_results["results"]["TF-G3-004"]

STRATEGIES = {
    "TF-G3-002": {"dna": dna_002, "baseline": baseline_002},
    "TF-G3-004": {"dna": dna_004, "baseline": baseline_004},
}


# ─────────────────────────────────────────────────────────────────────
# Helper: Run backtest and extract key metrics
# ─────────────────────────────────────────────────────────────────────

def backtest_metrics(dna, df):
    """Run backtest and return dict of key metrics."""
    result = run_backtest(dna, df)
    return {
        "total_pnl": result.total_pnl,
        "win_rate": result.win_rate,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown": result.max_drawdown,
        "profit_factor": result.profit_factor,
        "trade_count": result.trade_count,
        "wins": result.wins,
        "losses": result.losses,
        "expectancy": result.expectancy,
    }


# ─────────────────────────────────────────────────────────────────────
# GATE 1: MULTI-AXIS DEGRADATION
# ─────────────────────────────────────────────────────────────────────

def degrade_parameter(dna, param_key, factor):
    """Degrade a single numeric parameter by a factor (e.g. +0.1 = +10%)."""
    d = copy.deepcopy(dna)
    params = d.get("parameter_ranges", {})
    if param_key in params:
        val = params[param_key]
        if isinstance(val, (list, tuple)) and len(val) == 2:
            try:
                lo, hi = float(val[0]), float(val[1])
                params[param_key] = [lo * (1 + factor), hi * (1 + factor)]
            except (ValueError, TypeError):
                pass
    d["parameter_ranges"] = params
    return d


def degrade_all_params(dna, factor):
    """Degrade ALL numeric parameters by factor."""
    d = copy.deepcopy(dna)
    params = d.get("parameter_ranges", {})
    for key, val in params.items():
        if isinstance(val, (list, tuple)) and len(val) == 2:
            try:
                lo, hi = float(val[0]), float(val[1])
                params[key] = [lo * (1 + factor), hi * (1 + factor)]
            except (ValueError, TypeError):
                pass
    d["parameter_ranges"] = params
    return d


def add_slippage(df, ticks, seed=42):
    """Add tick slippage to entry/exit prices (close)."""
    rng = np.random.default_rng(seed)
    degraded = df.copy()
    # For CL, 1 tick = $0.01
    tick_size = 0.01
    slippage = ticks * tick_size
    # Random direction slippage on close
    direction = rng.choice([-1, 1], len(df))
    degraded["close"] = degraded["close"] + slippage * direction
    degraded["high"] = degraded[["high", "close"]].max(axis=1)
    degraded["low"] = degraded[["low", "close"]].min(axis=1)
    return degraded


def add_noise(df, noise_pct, seed=42):
    """Add ±noise_pct random noise to OHLC."""
    rng = np.random.default_rng(seed)
    degraded = df.copy()
    for col in ("open", "high", "low", "close"):
        noise = rng.normal(0, noise_pct, len(df))
        degraded[col] = degraded[col] * (1 + noise)
    degraded["high"] = degraded[["open", "high", "low", "close"]].max(axis=1)
    degraded["low"] = degraded[["open", "high", "low", "close"]].min(axis=1)
    return degraded


def run_gate1(strategy_code, dna, df, baseline_metrics):
    """Run multi-axis degradation test."""
    print(f"\n{'─' * 60}")
    print(f"  GATE 1: DEGRADATION TEST — {strategy_code}")
    print(f"{'─' * 60}")

    baseline_pnl = baseline_metrics["total_pnl_pct"]
    baseline_wr = baseline_metrics["win_rate"]
    baseline_sharpe = baseline_metrics["sharpe_ratio"]
    baseline_dd = baseline_metrics["max_drawdown"]

    results = {
        "strategy_code": strategy_code,
        "baseline": {
            "pnl_pct": baseline_pnl,
            "win_rate": baseline_wr,
            "sharpe": baseline_sharpe,
            "max_drawdown": baseline_dd,
        },
        "parameter_degradation": {},
        "execution_degradation": {},
        "data_degradation": {},
        "regime_shift": {},
        "worst_case": {},
        "gate1_passed": False,
    }

    # ── A. Parameter Degradation ──
    print("\n  A. Parameter Degradation:")
    param_results = {}
    all_param_pass = True
    
    for factor_label, factor in [("-20%", -0.20), ("-10%", -0.10), ("+10%", 0.10), ("+20%", 0.20)]:
        degraded_dna = degrade_all_params(dna, factor)
        m = backtest_metrics(degraded_dna, df)
        passed = m["total_pnl"] > 0
        param_results[factor_label] = {
            "pnl": round(m["total_pnl"], 4),
            "win_rate": round(m["win_rate"], 4),
            "sharpe": round(m["sharpe_ratio"], 4),
            "max_dd": round(m["max_drawdown"], 4),
            "trades": m["trade_count"],
            "profitable": passed,
        }
        if not passed:
            all_param_pass = False
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"    {factor_label}: PnL={m['total_pnl']:.4f} WR={m['win_rate']:.2%} "
              f"Sharpe={m['sharpe_ratio']:.2f} DD={m['max_drawdown']:.2%} [{status}]")

    results["parameter_degradation"] = {
        "results": param_results,
        "all_profitable": all_param_pass,
    }

    # ── B. Execution Degradation (Slippage) ──
    print("\n  B. Execution Degradation (Slippage):")
    slip_results = {}
    slip_pass_2tick = True

    for ticks in [1, 2, 3]:
        degraded_df = add_slippage(df, ticks)
        m = backtest_metrics(dna, degraded_df)
        passed = m["total_pnl"] > 0
        slip_results[f"{ticks}_tick"] = {
            "pnl": round(m["total_pnl"], 4),
            "win_rate": round(m["win_rate"], 4),
            "sharpe": round(m["sharpe_ratio"], 4),
            "max_dd": round(m["max_drawdown"], 4),
            "trades": m["trade_count"],
            "profitable": passed,
        }
        if ticks <= 2 and not passed:
            slip_pass_2tick = False
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"    {ticks} tick: PnL={m['total_pnl']:.4f} WR={m['win_rate']:.2%} "
              f"Sharpe={m['sharpe_ratio']:.2f} DD={m['max_drawdown']:.2%} [{status}]")

    results["execution_degradation"] = {
        "results": slip_results,
        "profitable_at_2tick": slip_pass_2tick,
    }

    # ── C. Data Degradation (Noise) ──
    print("\n  C. Data Degradation (Noise):")
    noise_results = {}
    noise_pass_01 = True

    for noise_label, noise_pct in [("0.05%", 0.0005), ("0.1%", 0.001), ("0.2%", 0.002)]:
        noisy_df = add_noise(df, noise_pct)
        m = backtest_metrics(dna, noisy_df)
        passed = m["total_pnl"] > 0
        noise_results[noise_label] = {
            "pnl": round(m["total_pnl"], 4),
            "win_rate": round(m["win_rate"], 4),
            "sharpe": round(m["sharpe_ratio"], 4),
            "max_dd": round(m["max_drawdown"], 4),
            "trades": m["trade_count"],
            "profitable": passed,
        }
        if noise_label in ("0.05%", "0.1%") and not passed:
            noise_pass_01 = False
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"    ±{noise_label}: PnL={m['total_pnl']:.4f} WR={m['win_rate']:.2%} "
              f"Sharpe={m['sharpe_ratio']:.2f} DD={m['max_drawdown']:.2%} [{status}]")

    results["data_degradation"] = {
        "results": noise_results,
        "profitable_at_0.1%": noise_pass_01,
    }

    # ── D. Regime Shift ──
    print("\n  D. Regime Shift (already passed 2/3 in Darwin):")
    regime_results = {}
    for regime in ["trending", "ranging", "volatile"]:
        synth = generate_synthetic_ohlcv(n_bars=2000, regime=regime, seed=99)
        m = backtest_metrics(dna, synth)
        passed = m["total_pnl"] > 0
        regime_results[regime] = {
            "pnl": round(m["total_pnl"], 4),
            "win_rate": round(m["win_rate"], 4),
            "sharpe": round(m["sharpe_ratio"], 4),
            "max_dd": round(m["max_drawdown"], 4),
            "trades": m["trade_count"],
            "profitable": passed,
        }
        status = "✅" if passed else "⚠️"
        print(f"    {regime}: PnL={m['total_pnl']:.4f} Trades={m['trade_count']} [{status}]")

    regimes_profitable = sum(1 for r in regime_results.values() if r["profitable"])
    results["regime_shift"] = {
        "results": regime_results,
        "regimes_profitable": regimes_profitable,
        "passes_2of3": regimes_profitable >= 2,
    }

    # ── Worst-case metrics ──
    all_degraded_metrics = []
    for k, v in param_results.items():
        all_degraded_metrics.append(v)
    for k, v in slip_results.items():
        all_degraded_metrics.append(v)
    for k, v in noise_results.items():
        all_degraded_metrics.append(v)

    if all_degraded_metrics:
        worst_dd = max(m["max_dd"] for m in all_degraded_metrics)
        worst_wr = min(m["win_rate"] for m in all_degraded_metrics if m["trades"] > 0)
        worst_sharpe = min(m["sharpe"] for m in all_degraded_metrics if m["trades"] > 0)
        worst_pnl = min(m["pnl"] for m in all_degraded_metrics)
    else:
        worst_dd = worst_wr = worst_sharpe = worst_pnl = 0

    results["worst_case"] = {
        "max_drawdown": round(worst_dd, 4),
        "min_win_rate": round(worst_wr, 4),
        "min_sharpe": round(worst_sharpe, 4),
        "min_pnl": round(worst_pnl, 4),
    }

    # ── Pass Criteria ──
    # Strategy remains profitable under ALL 4 axes
    # DD < 15%, WR > 35%, Sharpe > 0.3 under worst-case
    pnl_pass = all_param_pass and slip_pass_2tick and noise_pass_01
    dd_pass = worst_dd < 0.15
    wr_pass = worst_wr > 0.35
    sharpe_pass = worst_sharpe > 0.3
    regime_pass = regimes_profitable >= 2

    gate1_passed = pnl_pass and dd_pass and wr_pass and sharpe_pass and regime_pass

    results["gate1_criteria"] = {
        "all_profitable": pnl_pass,
        "worst_dd_under_15pct": dd_pass,
        "worst_wr_over_35pct": wr_pass,
        "worst_sharpe_over_0.3": sharpe_pass,
        "regime_2of3": regime_pass,
    }
    results["gate1_passed"] = gate1_passed

    verdict = "✅ GATE 1 PASSED" if gate1_passed else "❌ GATE 1 FAILED"
    print(f"\n  {verdict}")
    print(f"    Profitable under degradation: {pnl_pass}")
    print(f"    Worst DD ({worst_dd:.2%}) < 15%: {dd_pass}")
    print(f"    Worst WR ({worst_wr:.2%}) > 35%: {wr_pass}")
    print(f"    Worst Sharpe ({worst_sharpe:.2f}) > 0.3: {sharpe_pass}")
    print(f"    Regime 2/3: {regime_pass}")

    return results


# ─────────────────────────────────────────────────────────────────────
# GATE 2: DEPENDENCY TEST
# ─────────────────────────────────────────────────────────────────────

def remove_component(dna, component_name):
    """Remove a specific component from the DNA and return modified version."""
    d = copy.deepcopy(dna)
    params = d.get("parameter_ranges", {})

    if component_name == "adx_regime_filter":
        # Set ADX threshold to 0 (effectively no filter)
        for key in ("adx_threshold", "adx_min", "adx_max"):
            if key in params:
                params[key] = [0, 0]
        # Also remove ADX from filters
        d["filters"] = [f for f in d.get("filters", []) if "adx" not in f.lower()]

    elif component_name == "volume_confirmation":
        # Set volume multiplier to 0
        for key in ("volume_multiplier", "volume_breakout_multiplier"):
            if key in params:
                params[key] = [0, 0.01]
        d["filters"] = [f for f in d.get("filters", []) if "volume" not in f.lower()]

    elif component_name == "vwap_filter":
        # Remove VWAP from confirmation stack
        stack = d.get("confirmation_stack", {})
        checks = stack.get("checks", [])
        stack["checks"] = [c for c in checks if "vwap" not in c.lower()]
        if stack.get("min_confirmations", 3) > len(stack["checks"]):
            stack["min_confirmations"] = max(1, len(stack["checks"]))
        d["confirmation_stack"] = stack

    elif component_name == "second_ema":
        # Keep only fast EMA, remove slow
        for key in ("slow_ema", "ema_trend_period"):
            if key in params:
                # Set slow EMA same as fast (effectively single EMA)
                fast = params.get("fast_ema", params.get("medium_ema", [20, 20]))
                params[key] = fast

    elif component_name == "partial_exits":
        # Remove partial exit rules, use all-or-nothing
        exits = d.get("exit_rules", {})
        exits.pop("partial_tp_1", None)
        exits.pop("partial_tp_2", None)
        exits.pop("runner", None)
        d["exit_rules"] = exits

    elif component_name == "breakeven_trigger":
        exits = d.get("exit_rules", {})
        exits.pop("breakeven_at_r", None)
        d["exit_rules"] = exits

    elif component_name == "time_limit":
        exits = d.get("exit_rules", {})
        exits.pop("time_limit_bars", None)
        d["exit_rules"] = exits

    d["parameter_ranges"] = params
    return d


def run_gate2(strategy_code, dna, df, baseline_metrics):
    """Run dependency test — remove each component one at a time."""
    print(f"\n{'─' * 60}")
    print(f"  GATE 2: DEPENDENCY TEST — {strategy_code}")
    print(f"{'─' * 60}")

    baseline_pnl_pct = baseline_metrics["total_pnl_pct"]
    
    # Also get a fresh baseline from the backtester for consistency
    baseline_m = backtest_metrics(dna, df)
    baseline_pnl = baseline_m["total_pnl"]
    
    components = [
        ("adx_regime_filter", "Remove ADX regime filter"),
        ("volume_confirmation", "Remove volume confirmation"),
        ("vwap_filter", "Remove VWAP filter"),
        ("second_ema", "Remove second EMA (keep only one)"),
        ("partial_exits", "Remove partial exits (all-or-nothing)"),
        ("breakeven_trigger", "Remove breakeven trigger"),
        ("time_limit", "Remove time limit"),
    ]

    results = {
        "strategy_code": strategy_code,
        "baseline_pnl": round(baseline_pnl, 4),
        "components": {},
        "critical_dependencies": [],
        "gate2_passed": False,
    }

    any_over_50pct_drop = False

    for comp_key, comp_desc in components:
        modified_dna = remove_component(dna, comp_key)
        m = backtest_metrics(modified_dna, df)

        if abs(baseline_pnl) > 0.0001:
            pnl_change_pct = ((m["total_pnl"] - baseline_pnl) / abs(baseline_pnl)) * 100
        else:
            pnl_change_pct = 0

        is_critical = pnl_change_pct < -50.0

        results["components"][comp_key] = {
            "description": comp_desc,
            "pnl": round(m["total_pnl"], 4),
            "pnl_change_pct": round(pnl_change_pct, 2),
            "win_rate": round(m["win_rate"], 4),
            "sharpe": round(m["sharpe_ratio"], 4),
            "trades": m["trade_count"],
            "is_critical": is_critical,
        }

        if is_critical:
            any_over_50pct_drop = True
            results["critical_dependencies"].append(comp_key)

        status = "⚠️ CRITICAL" if is_critical else "✅ OK"
        print(f"    {comp_desc}: PnL={m['total_pnl']:.4f} (Δ{pnl_change_pct:+.1f}%) "
              f"WR={m['win_rate']:.2%} [{status}]")

    gate2_passed = not any_over_50pct_drop
    results["gate2_passed"] = gate2_passed

    verdict = "✅ GATE 2 PASSED" if gate2_passed else "❌ GATE 2 FAILED"
    print(f"\n  {verdict}")
    if results["critical_dependencies"]:
        print(f"    Critical dependencies: {results['critical_dependencies']}")
    else:
        print(f"    No single component causes > 50% performance drop")

    return results


# ─────────────────────────────────────────────────────────────────────
# MAIN EXECUTION
# ─────────────────────────────────────────────────────────────────────

all_results = {
    "meta": {
        "test_date": datetime.utcnow().isoformat(),
        "data_range": f"{df_daily.index[0]} to {df_daily.index[-1]}",
        "bars": len(df_daily),
        "strategies_tested": ["TF-G3-002", "TF-G3-004"],
    },
    "strategies": {},
}

for code, info in STRATEGIES.items():
    print(f"\n{'=' * 70}")
    print(f"  TESTING: {code}")
    print(f"{'=' * 70}")

    dna = info["dna"]
    baseline = info["baseline"]

    gate1 = run_gate1(code, dna, df_daily, baseline)
    gate2 = run_gate2(code, dna, df_daily, baseline)

    both_passed = gate1["gate1_passed"] and gate2["gate2_passed"]
    verdict = "CLEARED_FOR_PAPER" if both_passed else "REJECTED"

    all_results["strategies"][code] = {
        "gate1_degradation": gate1,
        "gate2_dependency": gate2,
        "both_gates_passed": both_passed,
        "verdict": verdict,
    }

# ─────────────────────────────────────────────────────────────────────
# FINAL VERDICT
# ─────────────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
print("  FINAL VERDICT")
print("=" * 70)

cleared = []
for code, res in all_results["strategies"].items():
    v = res["verdict"]
    g1 = "✅" if res["gate1_degradation"]["gate1_passed"] else "❌"
    g2 = "✅" if res["gate2_dependency"]["gate2_passed"] else "❌"
    emoji = "🟢" if v == "CLEARED_FOR_PAPER" else "🔴"
    print(f"  {emoji} {code}: Gate1={g1} Gate2={g2} → {v}")
    if v == "CLEARED_FOR_PAPER":
        cleared.append(code)

        # Print full metrics
        bl = res["gate1_degradation"]["baseline"]
        wc = res["gate1_degradation"]["worst_case"]
        print(f"     Baseline: PnL={bl['pnl_pct']:.2f}% WR={bl['win_rate']:.2%} "
              f"Sharpe={bl['sharpe']:.2f} DD={bl['max_drawdown']:.2%}")
        print(f"     Worst-case: PnL={wc['min_pnl']:.4f} WR={wc['min_win_rate']:.2%} "
              f"Sharpe={wc['min_sharpe']:.2f} DD={wc['max_drawdown']:.2%}")

all_results["cleared_for_paper"] = cleared
all_results["summary"] = {
    "total_tested": 2,
    "total_cleared": len(cleared),
    "cleared_strategies": cleared,
}

if cleared:
    print(f"\n  🚀🚀🚀 {len(cleared)} STRATEG{'Y' if len(cleared)==1 else 'IES'} CLEARED FOR PAPER TRADING 🚀🚀🚀")
    for c in cleared:
        print(f"     → {c}")
else:
    print(f"\n  ⛔ No strategies cleared for paper trading.")

# Save results
output_path = PROJECT / "data" / "degradation_dependency_results.json"
with open(output_path, "w") as f:
    json.dump(all_results, f, indent=2, default=str)
print(f"\n  Results saved to: {output_path}")

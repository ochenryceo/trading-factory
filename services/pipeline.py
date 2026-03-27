#!/usr/bin/env python3
"""
Shared Pipeline — 8-Gate Validation Pipeline

Used by both continuous_backtester.py and parallel_backtester.py.

Pipeline order:
1. Data Integrity — sanity check prices, no NaN, no gaps
2. Simulation Validity — equity sanity, forced_exit_ratio < 0.3
3. Trade Validity — no outlier trades, realistic per-trade PnL
4. Execution Constraints — (implicit from backtester)
5. Statistical Viability — Darwin pre-screened (safety net)
6. Distribution — Gini < 0.6, no month > 30%, PnL spans 3+ years
7. Stability — robustness, walk-forward, light MC, full MC
8. Complexity — final validation + deep inspection
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

PROJECT = Path(__file__).resolve().parents[1]

from services.darwin.backtester import TradeRecord, robustness_check
from services.walk_forward import walk_forward_test
from services.monte_carlo import monte_carlo_light, monte_carlo_test
from services.heavy_gate_scheduler import heavy_gate
from services.trade_distribution_gate import check_trade_distribution
from services.final_validation import validate_strategy, ValidationTag
from services.deep_inspect import deep_inspect
from services.failure_intelligence import (
    record_validation_failure,
)

log = logging.getLogger("pipeline")

# ── Paths ──────────────────────────────────────────────────────────────────

FAILURE_REGISTRY_PATH = PROJECT / "data" / "failure_registry.jsonl"

# ── Darwin Criteria ────────────────────────────────────────────────────────

DARWIN_CRITERIA = {
    "min_win_rate": 0.40,
    "min_sharpe": 0.5,
    "max_drawdown": 0.20,
    "min_trades": 100,
    "min_profit_factor": 1.1,
    "min_unique_months": 12,
    "max_entry_conditions": 3,
}

# Style archetypes for simplicity enforcement
STYLE_ARCHETYPES = {
    "momentum_breakout": {"archetype": "breakout", "max_conditions": 3},
    "trend_following":   {"archetype": "breakout", "max_conditions": 3},
    "mean_reversion":    {"archetype": "mean_reversion", "max_conditions": 2},
    "scalping":          {"archetype": "mean_reversion", "max_conditions": 3},
    "volume_orderflow":  {"archetype": "volume", "max_conditions": 2},
    "news_reaction":     {"archetype": "volume", "max_conditions": 2},
}


# ── Simplicity Helpers ─────────────────────────────────────────────────────

def count_entry_conditions(dna: dict) -> int:
    """Count active entry indicators for a strategy style."""
    style = dna.get("style", "")
    info = STYLE_ARCHETYPES.get(style)
    if info:
        return info["max_conditions"]
    return len(dna.get("parameter_ranges", {}))


def check_style_purity(dna: dict) -> Tuple[bool, str]:
    """Reject DNAs that mix archetypes."""
    style = dna.get("style", "")
    info = STYLE_ARCHETYPES.get(style)
    if not info:
        return False, f"Unknown style '{style}'"

    archetype = info["archetype"]
    params = dna.get("parameter_ranges", {})

    has_mr = any(k in params for k in ("rsi_threshold", "rsi_period", "rsi_extreme",
                                        "rsi2_threshold", "bb_period", "bb_std"))
    has_bo = any(k in params for k in ("fast_ema", "slow_ema", "ema_period",
                                        "ema_trend_period", "medium_ema"))
    if archetype == "mean_reversion" and has_bo:
        return False, "Mean reversion DNA has breakout indicators (EMA)"
    if archetype == "breakout" and has_mr:
        return False, "Breakout DNA has mean reversion indicators (RSI/BB)"

    n_conditions = count_entry_conditions(dna)
    if n_conditions > DARWIN_CRITERIA["max_entry_conditions"]:
        return False, f"{n_conditions} entry conditions > max {DARWIN_CRITERIA['max_entry_conditions']}"

    return True, ""


# ── Darwin Gate ────────────────────────────────────────────────────────────

def _count_unique_months(trade_log: List[Dict]) -> int:
    months = set()
    for t in trade_log:
        entry_time = t.get("entry_time", "")
        if entry_time and len(entry_time) >= 7:
            months.add(entry_time[:7])
    return len(months)


def passes_darwin(result: Dict, dna: dict) -> Tuple[bool, Optional[str]]:
    """Check Darwin criteria. Returns (passed, failure_tag or None)."""
    if result["trade_count"] < DARWIN_CRITERIA["min_trades"]:
        return False, "FAIL_LOW_SAMPLE"
    if result["win_rate"] < DARWIN_CRITERIA["min_win_rate"]:
        return False, "FAIL_LOW_SAMPLE"
    if result["sharpe_ratio"] < DARWIN_CRITERIA["min_sharpe"]:
        return False, "FAIL_LOW_SAMPLE"
    if result["max_drawdown"] > DARWIN_CRITERIA["max_drawdown"]:
        return False, "FAIL_EXECUTION_SENSITIVITY"
    if result["profit_factor"] < DARWIN_CRITERIA["min_profit_factor"]:
        return False, "FAIL_LOW_SAMPLE"

    trade_log = result.get("_trade_log", result.get("trade_log", []))
    if trade_log:
        unique_months = _count_unique_months(trade_log)
        if unique_months < DARWIN_CRITERIA.get("min_unique_months", 12):
            return False, "FAIL_LOW_SAMPLE"

    style_ok, reason = check_style_purity(dna)
    if not style_ok:
        return False, "FAIL_COMPLEXITY"

    return True, None


# ── Trust Score ────────────────────────────────────────────────────────────

def compute_trust(
    robustness_result: dict,
    walk_forward_result: dict,
    monte_carlo_result: dict,
    distribution_result: dict,
    complexity_count: int,
    forced_exit_ratio: float = 0.0,
) -> float:
    """Composite trust score (0.0 to 1.0)."""
    wf_degradation = walk_forward_result.get("degradation", 1.0)
    wf_score = max(0, 1.0 - abs(wf_degradation))
    mc_survival = monte_carlo_result.get("survival_rate", 0)
    mc_dd = monte_carlo_result.get("p95_dd", 1.0)
    mc_score = mc_survival * (1.0 - mc_dd)
    stability_score = (wf_score * 0.5 + mc_score * 0.5)

    gini = distribution_result.get("gini", 0.5)
    distribution_score = max(0, 1.0 - gini)

    simplicity_score = max(0.3, 1.0 - (complexity_count - 1) * 0.2)

    penalty = 0.0
    if forced_exit_ratio > 0.1:
        penalty += 0.1
    stripped_ratio = robustness_result.get("return_ratio", 1.0)
    if stripped_ratio < 0.5:
        penalty += 0.1

    trust = stability_score * distribution_score * simplicity_score * (1.0 - penalty)
    return round(max(0.0, min(1.0, trust)), 3)


# ── Multi-failure Logger ───────────────────────────────────────────────────

def _log_multi_failure(code: str, asset: str, tf: str,
                       tags: List[Dict], result: Dict):
    """Log a multi-tag failure entry to the failure registry."""
    metrics = {
        "trade_count": result.get("trade_count", 0),
        "win_rate": result.get("win_rate", 0),
        "sharpe_ratio": result.get("sharpe_ratio", 0),
        "max_drawdown": result.get("max_drawdown", 0),
        "profit_factor": result.get("profit_factor", 0),
        "total_return_pct": result.get("total_return_pct", 0),
    }
    FAILURE_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "strategy_code": code,
        "asset": asset,
        "timeframe": tf,
        "failures": tags,
        "metrics": metrics,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(FAILURE_REGISTRY_PATH, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ── Pipeline Runner ────────────────────────────────────────────────────────

def run_pipeline(dna: dict, result: Dict, asset: str, tf: str,
                 failure_summary: dict = None,
                 on_pass=None, on_conditional=None,
                 agent_name: str = "unknown") -> str:
    """
    Run the full 8-gate validation pipeline after Darwin pass.
    Returns final status: "PASSED", "CONDITIONAL", or failure tag string.

    Args:
        dna: Strategy DNA dict
        result: Backtest result dict (must contain _trades, _trade_log, trade_log, extra)
        asset: Asset symbol (NQ, GC, CL)
        tf: Timeframe string
        failure_summary: Optional dict to accumulate failure tag counts
        on_pass: Optional callback(result, gates_cleared, trust) for passed strategies
        on_conditional: Optional callback(result, gates_cleared, conditional_gates, trust)
    """
    if failure_summary is None:
        failure_summary = defaultdict(int)

    code = result["strategy_code"]
    raw_trades = result.get("_trades", [])
    trade_log = result.get("_trade_log", result.get("trade_log", []))
    extra = result.get("extra", {})

    gates_cleared = ["darwin"]
    conditional_gates = []
    failure_tags = []
    is_conditional = False

    def _record_tag(gate: str, tag: str, severity: str = "hard_fail", metrics: dict = None):
        failure_tags.append({"tag": tag, "severity": severity, "gate": gate})
        if severity == "hard_fail":
            failure_summary[tag] = failure_summary.get(tag, 0) + 1

    # ══════════════════════════════════════════════════════════════════════
    # CHEAP GATES (1-4)
    # ══════════════════════════════════════════════════════════════════════

    # ── Gate 1: DATA INTEGRITY ──
    nan_count = 0
    bad_price_count = 0
    for t in trade_log[:200]:
        ep = t.get("entry_price", 0)
        xp = t.get("exit_price", 0)
        pnl = t.get("pnl_pct", 0)
        if ep <= 0 or xp <= 0:
            bad_price_count += 1
        if pnl != pnl:  # NaN check
            nan_count += 1
    if nan_count > 0:
        _record_tag("data_integrity", "FAIL_DATA_INTEGRITY", "hard_fail",
                     {"nan_trades": nan_count})
        log.info(f"  🚫 DATA INTEGRITY: FAIL — {nan_count} NaN trades")
    if bad_price_count > len(trade_log) * 0.05:
        _record_tag("data_integrity", "FAIL_DATA_INTEGRITY", "hard_fail",
                     {"bad_prices": bad_price_count})
        log.info(f"  🚫 DATA INTEGRITY: FAIL — {bad_price_count} bad price trades")

    if not any(ft["severity"] == "hard_fail" and ft["gate"] == "data_integrity" for ft in failure_tags):
        gates_cleared.append("data_integrity")
        log.info(f"  ✅ DATA INTEGRITY: PASS")

    # ── Gate 2: SIMULATION VALIDITY ──
    sim_hard_fail = False
    total_return = result.get("total_return_pct", 0)
    pf = result.get("profit_factor", 0)
    forced_exit_ratio = extra.get("forced_exit_ratio", 0)

    if total_return > 10000 or total_return < -100:
        _record_tag("simulation_validity", "FAIL_BROKEN_EQUITY", "hard_fail",
                     {"total_return_pct": total_return})
        sim_hard_fail = True
        log.info(f"  🚫 SIM VALIDITY: FAIL — broken equity: {total_return:+.1f}%")
    if pf > 10:
        _record_tag("simulation_validity", "FAIL_BROKEN_EQUITY", "hard_fail",
                     {"profit_factor": pf})
        sim_hard_fail = True
        log.info(f"  🚫 SIM VALIDITY: FAIL — unrealistic PF: {pf:.2f}")
    if forced_exit_ratio > 0.3:
        _record_tag("simulation_validity", "FAIL_FORCED_EXIT_DEPENDENCY", "hard_fail",
                     {"forced_exit_ratio": forced_exit_ratio})
        sim_hard_fail = True
        log.info(f"  🚫 SIM VALIDITY: FAIL — forced_exit_ratio {forced_exit_ratio:.1%} > 30%")
    elif forced_exit_ratio > 0.2:
        _record_tag("simulation_validity", "FAIL_FORCED_EXIT_DEPENDENCY", "warning",
                     {"forced_exit_ratio": forced_exit_ratio})
        log.info(f"  ⚠️ SIM VALIDITY: WARNING — forced_exit_ratio {forced_exit_ratio:.1%}")

    if not sim_hard_fail:
        gates_cleared.append("simulation_validity")
        log.info(f"  ✅ SIM VALIDITY: PASS")

    # ── Gate 3: TRADE VALIDITY ──
    trade_hard_fail = False
    total_pnl = result.get("total_pnl", 0)
    if total_pnl > 0 and trade_log:
        max_single_pct = 0
        for t in trade_log:
            tpnl = abs(t.get("pnl_pct", 0))
            single_pct = tpnl / total_pnl * 100 if total_pnl > 0 else 0
            max_single_pct = max(max_single_pct, single_pct)
        if max_single_pct > 50:
            _record_tag("trade_validity", "FAIL_OUTLIER_TRADE", "hard_fail",
                         {"max_single_trade_pct": round(max_single_pct, 1)})
            trade_hard_fail = True
            log.info(f"  🚫 TRADE VALIDITY: FAIL — single trade = {max_single_pct:.0f}% of PnL")
        elif max_single_pct > 15:
            _record_tag("trade_validity", "FAIL_OUTLIER_TRADE", "warning",
                         {"max_single_trade_pct": round(max_single_pct, 1)})
            log.info(f"  ⚠️ TRADE VALIDITY: WARNING — single trade = {max_single_pct:.0f}% of PnL")

    absurd_trades = sum(1 for t in trade_log if abs(t.get("pnl_pct", 0)) > 1.0)
    if absurd_trades > 0:
        _record_tag("trade_validity", "FAIL_DATA_INTEGRITY", "hard_fail",
                     {"absurd_trades": absurd_trades})
        trade_hard_fail = True
        log.info(f"  🚫 TRADE VALIDITY: FAIL — {absurd_trades} trades with >100% PnL (bad data)")

    if not trade_hard_fail:
        gates_cleared.append("trade_validity")
        log.info(f"  ✅ TRADE VALIDITY: PASS")

    # ── Gate 4: EXECUTION CONSTRAINTS (implicit) ──
    gates_cleared.append("execution_constraints")

    # ── FAIL FAST ──
    hard_fails = [ft for ft in failure_tags if ft["severity"] == "hard_fail"]
    if hard_fails:
        _log_multi_failure(code, asset, tf, failure_tags, result)
        return hard_fails[0]["tag"]

    # ══════════════════════════════════════════════════════════════════════
    # MEDIUM GATES (5-6)
    # ══════════════════════════════════════════════════════════════════════

    gates_cleared.append("statistical_viability")
    log.info(f"  ✅ STATISTICAL VIABILITY: PASS (Darwin pre-screened)")

    # ── Gate 6: DISTRIBUTION ──
    try:
        td = check_trade_distribution(trade_log, total_pnl)
        result["trade_distribution"] = td
        gini_str = f"gini={td.get('gini', 0):.2f} " if 'gini' in td else ""
        log.info(f"  📊 DISTRIBUTION: {gini_str}month={td['max_month_pnl_pct']:.1f}% "
                 f"trade={td['max_trade_pnl_pct']:.1f}% years={td['years_with_pnl']} "
                 f"{'PASS' if td['passed'] else 'COND' if td.get('conditional') else 'FAIL'}")
        if td["passed"]:
            gates_cleared.append("distribution")
        elif td.get("conditional"):
            conditional_gates.append("CONDITIONAL_DISTRIBUTION")
            gates_cleared.append("distribution")
            is_conditional = True
        else:
            tag = td.get("failure_tag", "FAIL_TRADE_DISTRIBUTION")
            _record_tag("distribution", tag, "hard_fail", td)
            _log_multi_failure(code, asset, tf, failure_tags, result)
            return tag
    except Exception as e:
        log.error(f"  Distribution error: {e}")
        return "FAIL_TRADE_DISTRIBUTION"

    # ══════════════════════════════════════════════════════════════════════
    # EXPENSIVE GATES (7)
    # ══════════════════════════════════════════════════════════════════════

    # ── Gate 7a: Robustness ──
    if not raw_trades or len(raw_trades) < 10:
        _record_tag("robustness", "FAIL_PNL_CONCENTRATION", "hard_fail",
                     {"trade_count": len(raw_trades)})
        _log_multi_failure(code, asset, tf, failure_tags, result)
        return "FAIL_PNL_CONCENTRATION"

    try:
        rob = robustness_check(raw_trades)
        result["robustness_check"] = rob
        log.info(f"  🔍 ROBUSTNESS: ratio={rob['return_ratio']:.2f} share={rob['top5_pnl_share']:.2f} "
                 f"{'PASS' if rob['passed'] else 'COND' if rob.get('conditional') else 'FAIL'}")
        if rob["passed"]:
            gates_cleared.append("robustness")
        elif rob.get("conditional"):
            conditional_gates.append("CONDITIONAL_ROBUSTNESS")
            gates_cleared.append("robustness")
            is_conditional = True
        else:
            tag = rob.get("failure_tag", "FAIL_PNL_CONCENTRATION")
            _record_tag("robustness", tag, "hard_fail", rob)
            _log_multi_failure(code, asset, tf, failure_tags, result)
            return tag
    except Exception as e:
        log.error(f"  Robustness error: {e}")
        return "FAIL_PNL_CONCENTRATION"

    # ── Gate 7b: Light Monte Carlo ──
    try:
        with heavy_gate(agent_name):
            mc_light = monte_carlo_light(raw_trades)
            result["monte_carlo_light"] = mc_light
        log.info(f"  🎲 LIGHT MC: survival={mc_light['survival_rate']:.1%} "
                 f"{'PASS' if mc_light['passed'] else 'COND' if mc_light.get('conditional') else 'FAIL'}")
        if mc_light["passed"]:
            gates_cleared.append("light_mc")
        elif mc_light.get("conditional"):
            conditional_gates.append("CONDITIONAL_LIGHT_MC")
            gates_cleared.append("light_mc")
            is_conditional = True
        else:
            tag = mc_light.get("failure_tag", "FAIL_MC_FRAGILITY")
            _record_tag("light_mc", tag, "hard_fail", mc_light)
            _log_multi_failure(code, asset, tf, failure_tags, result)
            return tag
    except Exception as e:
        log.error(f"  Light MC error: {e}")
        return "FAIL_MC_FRAGILITY"

    # ── Gate 7c: Walk-Forward ──
    try:
        with heavy_gate(agent_name):
            wf = walk_forward_test(dna, asset, tf)
        result["walk_forward"] = wf
        log.info(f"  📈 WALK-FORWARD: OOS Sharpe={wf['oos_sharpe']:.2f} deg={wf['degradation']:.2f} "
                 f"{'PASS' if wf['passed'] else 'COND' if wf.get('conditional') else 'FAIL'}")
        if wf["passed"]:
            gates_cleared.append("walk_forward")
        elif wf.get("conditional"):
            conditional_gates.append("CONDITIONAL_WALK_FORWARD")
            gates_cleared.append("walk_forward")
            is_conditional = True
        else:
            tag = wf.get("failure_tag", "FAIL_WF_INSTABILITY")
            _record_tag("walk_forward", tag, "hard_fail", wf)
            _log_multi_failure(code, asset, tf, failure_tags, result)
            return tag
    except Exception as e:
        log.error(f"  Walk-forward error: {e}")
        return "FAIL_WF_INSTABILITY"

    # ── Gate 7d: Full Monte Carlo ──
    try:
        with heavy_gate(agent_name):
            mc_full = monte_carlo_test(raw_trades)
        result["monte_carlo_full"] = mc_full
        log.info(f"  🎲 FULL MC: survival={mc_full['survival_rate']:.1%} p95_dd={mc_full['p95_dd']:.1%} "
                 f"{'PASS' if mc_full['passed'] else 'COND' if mc_full.get('conditional') else 'FAIL'}")
        if mc_full["passed"]:
            gates_cleared.append("full_mc")
        elif mc_full.get("conditional"):
            conditional_gates.append("CONDITIONAL_FULL_MC")
            gates_cleared.append("full_mc")
            is_conditional = True
        else:
            tag = mc_full.get("failure_tag", "FAIL_MC_FRAGILITY")
            _record_tag("full_mc", tag, "hard_fail", mc_full)
            _log_multi_failure(code, asset, tf, failure_tags, result)
            return tag
    except Exception as e:
        log.error(f"  Full MC error: {e}")
        return "FAIL_MC_FRAGILITY"

    # ══════════════════════════════════════════════════════════════════════
    # CONDITIONAL SAFETY CHECK
    # ══════════════════════════════════════════════════════════════════════
    if is_conditional:
        safety_fail = False
        if total_return > 10000 or total_return < -100:
            safety_fail = True
        if pf > 10:
            safety_fail = True
        if total_pnl > 0 and trade_log:
            max_share = max(abs(t.get("pnl_pct", 0)) / total_pnl * 100
                           for t in trade_log) if trade_log else 0
            if max_share > 50:
                safety_fail = True

        if safety_fail:
            _record_tag("conditional_safety", "FAIL_BROKEN_EQUITY", "hard_fail")
            _log_multi_failure(code, asset, tf, failure_tags, result)
            return "FAIL_BROKEN_EQUITY"

        try:
            n_cond = count_entry_conditions(dna) if dna else 2
            cond_trust = compute_trust(
                robustness_result=result.get("robustness_check", {}),
                walk_forward_result=result.get("walk_forward", {}),
                monte_carlo_result=result.get("monte_carlo_full", {}),
                distribution_result=result.get("trade_distribution", {}),
                complexity_count=n_cond,
                forced_exit_ratio=extra.get("forced_exit_ratio", 0),
            )
        except Exception:
            cond_trust = 0.0

        if on_conditional:
            on_conditional(result, gates_cleared, conditional_gates, cond_trust)
        log.info(f"  🟡 CONDITIONAL: {code} on {asset}/{tf} (trust={cond_trust:.3f}) | conditions: {conditional_gates}")
        return "CONDITIONAL"

    # ══════════════════════════════════════════════════════════════════════
    # Gate 8: COMPLEXITY — Final Validation + Deep Inspection
    # ══════════════════════════════════════════════════════════════════════
    log.info(f"  ⚙️ FINAL VALIDATION: {code} → Gate 4 + Gate 5...")
    try:
        fv = validate_strategy(dna, asset, tf)

        if fv.tag == ValidationTag.READY_FOR_PAPER:
            gates_cleared.append("final_validation")
            result["final_validation"] = "READY_FOR_PAPER"

            # Deep Inspection
            try:
                inspection = deep_inspect(dna, asset, tf, n_clones=5)
                result["deep_inspection_verdict"] = inspection.verdict
                result["deep_inspection_warnings"] = inspection.warnings[:5]
                result["clone_reproducible"] = (
                    inspection.clone_validation.get("reproducible", False)
                    if inspection.clone_validation else False
                )
                gates_cleared.append("deep_inspection")
                log.info(f"  🔬 DEEP INSPECT: {inspection.verdict} | "
                         f"Reproducible: {result['clone_reproducible']}")
            except Exception as e:
                log.error(f"  Deep inspection error: {e}")
                result["deep_inspection_verdict"] = "ERROR"

            # Compute trust score
            try:
                n_conditions = count_entry_conditions(dna) if dna else 2
                trust = compute_trust(
                    robustness_result=result.get("robustness_check", {}),
                    walk_forward_result=result.get("walk_forward", {}),
                    monte_carlo_result=result.get("monte_carlo_full", {}),
                    distribution_result=result.get("trade_distribution", {}),
                    complexity_count=n_conditions,
                    forced_exit_ratio=extra.get("forced_exit_ratio", 0),
                )
            except Exception:
                trust = 0.0

            if on_pass:
                on_pass(result, gates_cleared, trust)
            log.info(f"  🟢 PASSED ALL GATES: {code} on {asset}/{tf} (trust={trust:.3f})")
            return "PASSED"

        elif fv.tag == ValidationTag.REQUIRES_HARDENING:
            log.info(f"  🟡 REQUIRES_HARDENING: {code} | "
                     f"G4={'P' if fv.degradation_passed else 'F'} "
                     f"G5={'P' if fv.dependency_passed else 'F'}")
            result["final_validation"] = "REQUIRES_HARDENING"
            try:
                record_validation_failure(dna, asset, fv)
            except Exception:
                pass
            _record_tag("final_validation", "FAIL_EXECUTION_SENSITIVITY", "hard_fail",
                        {"reasons": fv.fail_summary[:5]})
            _log_multi_failure(code, asset, tf, failure_tags, result)
            return "FAIL_EXECUTION_SENSITIVITY"

        else:
            log.info(f"  🔴 REJECTED_POST_DARWIN: {code} | {fv.fail_summary[:3]}")
            result["final_validation"] = "REJECTED_POST_DARWIN"
            try:
                record_validation_failure(dna, asset, fv)
            except Exception:
                pass
            _record_tag("final_validation", "FAIL_EXECUTION_SENSITIVITY", "hard_fail",
                        {"reasons": fv.fail_summary[:5]})
            _log_multi_failure(code, asset, tf, failure_tags, result)
            return "FAIL_EXECUTION_SENSITIVITY"

    except Exception as e:
        log.error(f"  ❌ Final validation error: {e}")
        return "FAIL_EXECUTION_SENSITIVITY"


# ── Cross-Asset Validation (CL Stress Test) ────────────────────────────────

def validate_on_cl(dna: dict, original_asset: str, original_tf: str) -> dict:
    """
    Post-graduation stress test: run a passed strategy on CL.
    Called automatically when a strategy passes all gates on NQ or GC.
    
    NOT a gate — informational. Adds metadata to the registry entry.
    
    Returns:
        {
            "cl_tested": True,
            "cl_verdict": "SURVIVES" | "FAILS" | "BREAKS",
            "cl_sharpe": float,
            "cl_win_rate": float,
            "cl_trade_count": int,
            "cl_profit_factor": float,
            "cl_max_drawdown": float,
            "cl_details": str,
        }
    """
    from services.darwin.backtester import load_parquet, run_backtest
    
    log = logging.getLogger("pipeline")
    code = dna.get("strategy_code", "UNKNOWN")
    
    # Try CL on the same timeframe as the original
    try:
        df = load_parquet("CL", original_tf)
    except FileNotFoundError:
        return {"cl_tested": False, "cl_verdict": "NO_DATA", "cl_details": f"No CL {original_tf} data"}
    
    if len(df) < 100:
        return {"cl_tested": False, "cl_verdict": "INSUFFICIENT_DATA", "cl_details": f"CL {original_tf}: only {len(df)} bars"}
    
    try:
        result = run_backtest(dna, df, asset="CL")
    except Exception as e:
        return {"cl_tested": True, "cl_verdict": "BREAKS", "cl_details": f"Backtest crashed: {e}"}
    
    cl_result = {
        "cl_tested": True,
        "cl_sharpe": result.sharpe_ratio,
        "cl_win_rate": result.win_rate,
        "cl_trade_count": result.trade_count,
        "cl_profit_factor": result.profit_factor,
        "cl_max_drawdown": result.max_drawdown,
        "cl_total_return_pct": result.total_return_pct,
    }
    
    # Classify result
    if result.trade_count < 20:
        cl_result["cl_verdict"] = "INSUFFICIENT_TRADES"
        cl_result["cl_details"] = f"Only {result.trade_count} trades on CL"
    elif result.sharpe_ratio > 0.3 and result.profit_factor > 1.0 and result.total_return_pct > 0:
        cl_result["cl_verdict"] = "SURVIVES"
        cl_result["cl_details"] = (
            f"CL Sharpe={result.sharpe_ratio:.2f} PF={result.profit_factor:.2f} "
            f"WR={result.win_rate:.0%} DD={result.max_drawdown:.1%} — generalizable edge"
        )
    elif result.total_return_pct > 0 and result.profit_factor > 0.9:
        cl_result["cl_verdict"] = "FAILS"
        cl_result["cl_details"] = (
            f"CL Sharpe={result.sharpe_ratio:.2f} PF={result.profit_factor:.2f} "
            f"WR={result.win_rate:.0%} — marginal, asset-specific edge"
        )
    else:
        cl_result["cl_verdict"] = "BREAKS"
        cl_result["cl_details"] = (
            f"CL Sharpe={result.sharpe_ratio:.2f} PF={result.profit_factor:.2f} "
            f"Ret={result.total_return_pct:+.1f}% — hidden fragility detected"
        )
    
    verdict = cl_result["cl_verdict"]
    details = cl_result["cl_details"]
    log.info(f"  🛢️ CL STRESS TEST: {code} → {verdict} | {details}")
    return cl_result

#!/usr/bin/env python3
"""
CEO Directive — FINAL VALIDATION PROTOCOL
==========================================
Non-negotiable. Code-enforced. No manual override.

Every strategy that passes Darwin MUST clear this gate before paper trading.
No exceptions. No shortcuts. If this module doesn't tag it READY_FOR_PAPER,
it does NOT trade.

Gate 4: Multi-Axis Degradation Test (simultaneous)
Gate 5: Dependency Test (component removal)

Decision Engine:
  🟢 READY_FOR_PAPER      — both gates passed, auto-forward to paper
  🟡 REQUIRES_HARDENING   — partial pass, sent to R&D loop
  🔴 REJECTED_POST_DARWIN — failed, blocked from pipeline, archived

CRITICAL: This is enforced at code level.
  if not degradation_passed or not dependency_passed:
      block_paper_trading()
"""

from __future__ import annotations
import json
import copy
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

import numpy as np
import pandas as pd

from services.darwin.backtester import run_backtest, load_parquet, BacktestResult
from services.darwin.degradation import run_degradation_v2, DegradationResult
from services.darwin.dependency_test import run_dependency_test, DependencyResult

log = logging.getLogger("final_validation")

PROJECT = Path(__file__).resolve().parents[1]
VALIDATION_LOG_PATH = PROJECT / "data" / "final_validation_log.jsonl"
VALIDATED_PATH = PROJECT / "data" / "validated_strategies.json"


# ── Decision Tags ──────────────────────────────────────────────────────────

class ValidationTag:
    READY_FOR_PAPER = "READY_FOR_PAPER"
    REQUIRES_HARDENING = "REQUIRES_HARDENING"
    REJECTED_POST_DARWIN = "REJECTED_POST_DARWIN"


# ── Degradation Criteria (CEO Directive) ───────────────────────────────────
# Strategy must:
#   - Remain profitable OR near break-even
#   - Maintain controlled drawdown (< +50% increase from baseline max)
#   - Avoid equity curve collapse
# Not perfection — resilience.

DEGRADATION_CRITERIA = {
    "max_dd_increase_pct": 50.0,      # DD must not increase more than 50% from baseline
    "min_profitable_scenarios": 0.5,   # at least 50% of scenarios must stay profitable
    "must_remain_profitable": False,   # near break-even is OK (resilience, not perfection)
    "max_return_drop_pct": 80.0,       # PnL can't drop more than 80%
}

# ── Dependency Criteria (CEO Directive) ────────────────────────────────────
# No single component removal causes:
#   - 50% performance drop
#   - Total collapse
# Edge must be distributed, not fragile.

DEPENDENCY_CRITERIA = {
    "critical_drop_threshold_pct": 40.0,  # >40% drop = critical dependency (Directive 002: no single-indicator edges)
    "max_critical_dependencies": 0,        # ZERO critical dependencies allowed
}

# ── Suspicion Filter (CEO Directive 004) ───────────────────────────────────
# If it looks too good, it probably is. Flag it, don't kill it — let the
# degradation and dependency tests expose the truth.
# Suspicion thresholds — SEPARATE for daily vs intraday (CEO Directive 2026-03-23)
# Intraday naturally has higher WR, Sharpe, lower DD. Don't reject valid alpha.
SUSPICION_THRESHOLDS_DAILY = {
    "max_believable_wr": 0.85,
    "min_believable_dd": 0.01,
    "max_believable_sharpe": 4.0,
    "min_avg_loss_ratio": 0.3,
}
SUSPICION_THRESHOLDS_INTRADAY = {
    "max_believable_wr": 0.92,         # Intraday WR up to 92% can be real
    "min_believable_dd": 0.005,        # Tighter DD normal for short exposure
    "max_believable_sharpe": 6.0,      # Higher Sharpe normal with frequent trades
    "min_avg_loss_ratio": 0.3,
}

# Realistic bands — SEPARATE for daily vs intraday
REALISTIC_BAND_DAILY = {"min_sharpe": 1.0, "max_sharpe": 2.5, "min_wr": 0.50, "max_wr": 0.70, "min_dd": 0.03, "max_dd": 0.10, "min_trades": 20}
REALISTIC_BAND_INTRADAY = {"min_sharpe": 1.2, "max_sharpe": 3.2, "min_wr": 0.45, "max_wr": 0.75, "min_dd": 0.02, "max_dd": 0.12, "min_trades": 150}

INTRADAY_TIMEFRAMES = {"5m", "15m", "1h", "4h"}

# Keep backward compat
SUSPICION_THRESHOLDS = SUSPICION_THRESHOLDS_DAILY


# ── Result Containers ──────────────────────────────────────────────────────

@dataclass
class FinalValidationResult:
    """Complete final validation result for a strategy."""
    strategy_code: str
    asset: str
    tag: str = ValidationTag.REJECTED_POST_DARWIN
    timestamp: str = ""
    
    # Gate 4: Degradation
    degradation_passed: bool = False
    degradation_result: Optional[Dict] = None
    degradation_fail_reasons: List[str] = field(default_factory=list)
    
    # Gate 5: Dependency
    dependency_passed: bool = False
    dependency_result: Optional[Dict] = None
    dependency_fail_reasons: List[str] = field(default_factory=list)
    
    # Baseline metrics (for reference)
    baseline_sharpe: float = 0.0
    baseline_win_rate: float = 0.0
    baseline_max_dd: float = 0.0
    baseline_return_pct: float = 0.0
    
    # Summary
    overall_passed: bool = False
    partial_pass: bool = False
    fail_summary: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return asdict(self)


# ── Gate 4: Multi-Axis Degradation (Simultaneous) ─────────────────────────

def run_gate4_degradation(
    dna: dict,
    df: pd.DataFrame,
) -> Tuple[bool, DegradationResult, List[str]]:
    """
    Gate 4 — Multi-Axis Degradation Test
    
    Runs ALL axes simultaneously (not separately):
    1. Parameter Degradation: ±10-20% across key params
    2. Execution Degradation: slippage, latency, worse fills
    3. Data Degradation: noise injection, missing ticks/gaps
    4. Regime Shift Stress: trending, ranging, volatile
    
    PASS Criteria:
    - Strategy must remain profitable OR near break-even
    - Drawdown must not increase more than 50% from baseline
    - No equity curve collapse
    - NOT perfection — resilience
    """
    fail_reasons = []
    
    # Run degradation with expanded scenarios
    deg_result = run_degradation_v2(
        dna, df,
        param_shifts=[0.10, -0.10, 0.15, -0.15, 0.20, -0.20],
        slippage_ticks=[1, 2, 3, 5],
        noise_levels=[0.0005, 0.001, 0.002, 0.003],
    )
    
    # Evaluate each axis against CEO criteria
    total_scenarios = 0
    profitable_scenarios = 0
    collapsed_scenarios = 0
    
    for axis in deg_result.axes:
        for scenario in axis.scenarios:
            total_scenarios += 1
            if scenario.total_return_pct > -1.0:  # near break-even or better
                profitable_scenarios += 1
            if scenario.total_return_pct < -50.0:  # equity curve collapse
                collapsed_scenarios += 1
                fail_reasons.append(
                    f"COLLAPSE on {scenario.name}: return={scenario.total_return_pct:.1f}%"
                )
            if scenario.dd_change_pct > DEGRADATION_CRITERIA["max_dd_increase_pct"]:
                fail_reasons.append(
                    f"DD spike on {scenario.name}: +{scenario.dd_change_pct:.0f}% increase"
                )
    
    # Check minimum profitable ratio
    if total_scenarios > 0:
        profitable_ratio = profitable_scenarios / total_scenarios
        if profitable_ratio < DEGRADATION_CRITERIA["min_profitable_scenarios"]:
            fail_reasons.append(
                f"Only {profitable_scenarios}/{total_scenarios} scenarios profitable "
                f"({profitable_ratio:.0%} < {DEGRADATION_CRITERIA['min_profitable_scenarios']:.0%} required)"
            )
    
    # Check for any collapse
    if collapsed_scenarios > 0:
        fail_reasons.append(f"{collapsed_scenarios} scenario(s) suffered equity curve collapse")
    
    # Overall axis pass: use degradation result + our CEO criteria
    passed = deg_result.overall_passed and len(fail_reasons) == 0
    
    return passed, deg_result, fail_reasons


# ── Gate 5: Dependency Test (Component Removal) ───────────────────────────

def run_gate5_dependency(
    dna: dict,
    df: pd.DataFrame,
) -> Tuple[bool, DependencyResult, List[str]]:
    """
    Gate 5 — Dependency Test
    
    Remove components one at a time:
    - Time filters
    - Confirmation layers
    - Secondary indicators
    - Volume filters
    
    PASS Criteria:
    - No single removal causes 50% performance drop
    - No single removal causes total collapse
    - Edge must be distributed, not fragile
    """
    fail_reasons = []
    
    dep_result = run_dependency_test(
        dna, df,
        critical_threshold_pct=DEPENDENCY_CRITERIA["critical_drop_threshold_pct"],
    )
    
    # CEO directive: ZERO critical dependencies
    if len(dep_result.critical_dependencies) > DEPENDENCY_CRITERIA["max_critical_dependencies"]:
        fail_reasons.append(
            f"Critical dependencies found: {dep_result.critical_dependencies}"
        )
    
    if dep_result.is_fragile:
        fail_reasons.append("Strategy is FRAGILE — edge concentrated in single component")
    
    passed = not dep_result.is_fragile and len(fail_reasons) == 0
    
    return passed, dep_result, fail_reasons


# ── Decision Engine (Code-Enforced) ───────────────────────────────────────

def decide_tag(degradation_passed: bool, dependency_passed: bool) -> str:
    """
    Decision Engine — Non-negotiable, code-enforced.
    
    🟢 READY_FOR_PAPER:       Both gates passed → auto-forward to paper
    🟡 REQUIRES_HARDENING:    One gate passed → R&D loop for fixes
    🔴 REJECTED_POST_DARWIN:  Both failed → blocked, archived
    
    CRITICAL ENFORCEMENT:
        if not degradation_passed or not dependency_passed:
            block_paper_trading()
    """
    if degradation_passed and dependency_passed:
        return ValidationTag.READY_FOR_PAPER
    elif degradation_passed or dependency_passed:
        return ValidationTag.REQUIRES_HARDENING
    else:
        return ValidationTag.REJECTED_POST_DARWIN


def block_paper_trading():
    """
    Code-enforced block. Called when validation fails.
    This is the hard gate — no manual override except Jordan.
    """
    # This function exists as the enforcement mechanism.
    # The continuous backtester checks the tag directly.
    # If tag != READY_FOR_PAPER, the strategy CANNOT progress.
    pass


# ── Main Validation Entry Point ───────────────────────────────────────────

def validate_strategy(
    dna: dict,
    asset: str = "CL",
    timeframe: str = "daily",
    darwin_metrics: Optional[Dict] = None,
) -> FinalValidationResult:
    """
    Run the complete Final Validation Protocol on a strategy.
    
    This is THE gate between Darwin approval and paper trading.
    Non-negotiable. Code-enforced.
    
    Returns FinalValidationResult with tag:
      READY_FOR_PAPER / REQUIRES_HARDENING / REJECTED_POST_DARWIN
    """
    code = dna.get("strategy_code", "UNKNOWN")
    log.info(f"━━━ FINAL VALIDATION: {code} on {asset}/{timeframe} ━━━")
    
    # Load data
    df = load_parquet(asset, timeframe)
    
    # Run baseline for reference
    baseline = run_backtest(dna, df)
    
    result = FinalValidationResult(
        strategy_code=code,
        asset=asset,
        timestamp=datetime.now(timezone.utc).isoformat(),
        baseline_sharpe=baseline.sharpe_ratio,
        baseline_win_rate=baseline.win_rate,
        baseline_max_dd=baseline.max_drawdown,
        baseline_return_pct=baseline.total_return_pct,
    )
    
    # ── Pre-Gate: Suspicion Filter (CEO Directive 004) ──
    # Use intraday thresholds for short timeframes, daily for daily
    is_intraday = timeframe in INTRADAY_TIMEFRAMES
    sus_thresh = SUSPICION_THRESHOLDS_INTRADAY if is_intraday else SUSPICION_THRESHOLDS_DAILY
    
    suspicion_flags = []
    if baseline.win_rate > sus_thresh["max_believable_wr"] and baseline.max_drawdown < sus_thresh["min_believable_dd"]:
        suspicion_flags.append(f"TOO_GOOD_TO_BE_TRUE: WR {baseline.win_rate:.0%} + DD {baseline.max_drawdown:.1%}")
    if baseline.win_rate > sus_thresh["max_believable_wr"]:
        suspicion_flags.append(f"HIGH_WR: {baseline.win_rate:.0%} > {sus_thresh['max_believable_wr']:.0%} threshold")
    if baseline.max_drawdown < sus_thresh["min_believable_dd"] and baseline.trade_count > 20:
        suspicion_flags.append(f"ULTRA_LOW_DD: {baseline.max_drawdown:.2%} with {baseline.trade_count} trades")
    if baseline.sharpe_ratio > sus_thresh["max_believable_sharpe"]:
        suspicion_flags.append(f"EXTREME_SHARPE: {baseline.sharpe_ratio:.2f} > {sus_thresh['max_believable_sharpe']:.1f}")
    # Intraday: enforce minimum trade count (kills fake high-Sharpe)
    if is_intraday and baseline.trade_count < REALISTIC_BAND_INTRADAY["min_trades"]:
        suspicion_flags.append(f"LOW_TRADE_COUNT_INTRADAY: {baseline.trade_count} < {REALISTIC_BAND_INTRADAY['min_trades']} minimum")
    # Check avg win vs avg loss ratio (hidden tail risk)
    if baseline.avg_loss != 0 and baseline.avg_win != 0:
        loss_ratio = abs(baseline.avg_loss) / abs(baseline.avg_win)
        if loss_ratio > 3.0:
            suspicion_flags.append(f"HIDDEN_TAIL_RISK: avg loss is {loss_ratio:.1f}x avg win (tiny wins, big losses)")
    # Check largest single loss vs total PnL
    if baseline.total_pnl > 0 and baseline.largest_loss != 0:
        loss_impact = abs(baseline.largest_loss) / abs(baseline.total_pnl)
        if loss_impact > 0.5:
            suspicion_flags.append(f"SINGLE_LOSS_WIPEOUT: largest loss = {loss_impact:.0%} of total PnL")
    
    if suspicion_flags:
        log.info(f"  ⚠️ SUSPICION FLAGS ({len(suspicion_flags)}):")
        for sf in suspicion_flags:
            log.info(f"     🔍 {sf}")
        result.fail_summary.extend([f"SUSPICIOUS: {sf}" for sf in suspicion_flags])
    
    # Don't kill — let it pass through gates. Degradation will expose fakes.
    
    # ── Pre-Gate: Time Consistency Check (CEO Directive 006) ──
    log.info(f"  ⏱️ Time Consistency Check...")
    try:
        trade_log = baseline.trade_log
        if len(trade_log) >= 10:
            import numpy as np
            
            # Split trades into time periods (quarters)
            period_pnls = {}
            for t in trade_log:
                entry_time = t.get("entry_time", "")
                if entry_time and len(entry_time) >= 7:
                    quarter = entry_time[:4] + "-Q" + str((int(entry_time[5:7]) - 1) // 3 + 1)
                    if quarter not in period_pnls:
                        period_pnls[quarter] = []
                    period_pnls[quarter].append(t.get("pnl_pct", 0))
            
            if len(period_pnls) >= 3:  # need at least 3 periods
                # Calculate per-period returns
                period_returns = []
                period_wrs = []
                for period, pnls_list in sorted(period_pnls.items()):
                    if len(pnls_list) >= 2:
                        pr = sum(pnls_list)
                        wr = sum(1 for p in pnls_list if p > 0) / len(pnls_list)
                        period_returns.append(pr)
                        period_wrs.append(wr)
                
                if len(period_returns) >= 3:
                    returns_arr = np.array(period_returns)
                    wrs_arr = np.array(period_wrs)
                    
                    # Check 1: Are there losing periods?
                    losing_periods = sum(1 for r in returns_arr if r <= 0)
                    total_periods = len(returns_arr)
                    
                    # Check 2: Performance variance across periods
                    if returns_arr.mean() != 0:
                        cv = abs(returns_arr.std() / returns_arr.mean())  # coefficient of variation
                    else:
                        cv = 999
                    
                    # Check 3: Win rate consistency
                    wr_spread = wrs_arr.max() - wrs_arr.min()
                    
                    # Check 4: Was there a "golden period" carrying everything?
                    if returns_arr.sum() > 0:
                        best_period_pct = returns_arr.max() / returns_arr.sum() * 100
                    else:
                        best_period_pct = 0
                    
                    log.info(f"     Periods: {total_periods} | Losing: {losing_periods} | CV: {cv:.2f} | WR spread: {wr_spread:.0%} | Best period: {best_period_pct:.0f}% of PnL")
                    
                    # Flag conditions
                    if cv > 2.0:
                        suspicion_flags.append(f"REGIME_DEPENDENT_EDGE: performance CV={cv:.1f} across {total_periods} periods (high variance)")
                    if losing_periods == 0 and total_periods >= 4:
                        suspicion_flags.append(f"NO_LOSING_PERIODS: {total_periods} periods all profitable — suspicious consistency")
                    if best_period_pct > 60 and total_periods >= 4:
                        suspicion_flags.append(f"GOLDEN_PERIOD: best period = {best_period_pct:.0f}% of total PnL — edge may be temporal")
                    if wr_spread > 0.40:
                        suspicion_flags.append(f"INCONSISTENT_WR: win rate ranges {wrs_arr.min():.0%}–{wrs_arr.max():.0%} across periods ({wr_spread:.0%} spread)")
                else:
                    log.info(f"     Not enough periods with 2+ trades for consistency check")
            else:
                log.info(f"     Only {len(period_pnls)} periods — need 3+ for consistency check")
        else:
            log.info(f"     Only {len(trade_log)} trades — skipping time consistency")
    except Exception as e:
        log.debug(f"     Time consistency check error: {e}")
    
    # ── Pre-Gate: Equity Curve Smoothness Check (CEO Directive 007) ──
    log.info(f"  📈 Equity Curve Smoothness Check...")
    try:
        trade_log = baseline.trade_log
        if len(trade_log) >= 15:
            import numpy as np
            
            # Build equity curve from trade PnLs
            pnls = [t.get("pnl_pct", 0) for t in trade_log]
            pnl_arr = np.array(pnls)
            
            # Additive equity curve (matches backtester for high-frequency)
            if len(pnls) > 100:
                eq = np.cumsum(pnl_arr) + 1.0
            else:
                eq = np.cumprod(1 + pnl_arr)
            
            # 1. Equity curve volatility (rolling std of returns)
            if len(pnl_arr) > 10:
                rolling_std = pd.Series(pnl_arr).rolling(max(5, len(pnl_arr)//10)).std().dropna()
                if len(rolling_std) > 0 and rolling_std.mean() > 0:
                    vol_ratio = rolling_std.max() / rolling_std.mean()
                else:
                    vol_ratio = 0
            else:
                vol_ratio = 0
            
            # 2. Growth linearity — R² of equity curve vs straight line
            x = np.arange(len(eq))
            if len(eq) > 2 and np.var(eq) > 0:
                correlation = np.corrcoef(x, eq)[0, 1]
                r_squared = correlation ** 2 if not np.isnan(correlation) else 0
            else:
                r_squared = 0
            
            # 3. Longest flat/drawdown streak (bars without new equity high)
            peak = np.maximum.accumulate(eq)
            underwater = eq < peak
            max_flat = 0
            current_flat = 0
            for uw in underwater:
                if uw:
                    current_flat += 1
                    max_flat = max(max_flat, current_flat)
                else:
                    current_flat = 0
            flat_pct = max_flat / len(eq) * 100 if len(eq) > 0 else 0
            
            # 4. Growth burst ratio — does most growth happen in short bursts?
            if len(pnl_arr) >= 10:
                sorted_pnls = np.sort(pnl_arr)[::-1]
                top_10pct = sorted_pnls[:max(1, len(sorted_pnls)//10)]
                total_positive = pnl_arr[pnl_arr > 0].sum()
                if total_positive > 0:
                    burst_ratio = top_10pct.sum() / total_positive
                else:
                    burst_ratio = 0
            else:
                burst_ratio = 0
            
            log.info(f"     R²={r_squared:.3f} | Vol ratio={vol_ratio:.1f} | Longest flat={flat_pct:.0f}% | Burst ratio={burst_ratio:.0%}")
            
            # Flag conditions
            if r_squared < 0.5 and len(eq) > 20:
                suspicion_flags.append(f"UNSTABLE_GROWTH: equity curve R²={r_squared:.2f} (not linear, erratic growth)")
            if vol_ratio > 4.0:
                suspicion_flags.append(f"VOLATILITY_SPIKES: return volatility ratio={vol_ratio:.1f} (growth in bursts)")
            if flat_pct > 50:
                suspicion_flags.append(f"LONG_STALL: equity underwater {flat_pct:.0f}% of time (stalled growth)")
            if burst_ratio > 0.6 and len(pnl_arr) >= 20:
                suspicion_flags.append(f"BURST_DEPENDENT: top 10% of trades = {burst_ratio:.0%} of gains (growth in spurts)")
        else:
            log.info(f"     Only {len(trade_log)} trades — skipping smoothness check")
    except Exception as e:
        log.debug(f"     Equity smoothness check error: {e}")
    
    # ── Gate 4: Multi-Axis Degradation ──
    log.info(f"  Gate 4: Multi-Axis Degradation Test...")
    try:
        deg_passed, deg_result, deg_fails = run_gate4_degradation(dna, df)
        result.degradation_passed = deg_passed
        result.degradation_result = deg_result.to_dict()
        result.degradation_fail_reasons = deg_fails
        
        if deg_passed:
            log.info(f"  Gate 4: ✅ PASSED — resilient under degradation")
        else:
            log.info(f"  Gate 4: ❌ FAILED — {len(deg_fails)} issue(s): {deg_fails[:3]}")
    except Exception as e:
        log.error(f"  Gate 4: ERROR — {e}")
        result.degradation_passed = False
        result.degradation_fail_reasons = [f"Exception: {str(e)}"]
    
    # ── Gate 5: Dependency Test ──
    log.info(f"  Gate 5: Dependency Test (component removal)...")
    try:
        dep_passed, dep_result, dep_fails = run_gate5_dependency(dna, df)
        result.dependency_passed = dep_passed
        result.dependency_result = dep_result.to_dict()
        result.dependency_fail_reasons = dep_fails
        
        if dep_passed:
            log.info(f"  Gate 5: ✅ PASSED — edge is distributed, not fragile")
        else:
            log.info(f"  Gate 5: ❌ FAILED — {len(dep_fails)} issue(s): {dep_fails[:3]}")
    except Exception as e:
        log.error(f"  Gate 5: ERROR — {e}")
        result.dependency_passed = False
        result.dependency_fail_reasons = [f"Exception: {str(e)}"]
    
    # ── Decision Engine (Code-Enforced) ──
    result.tag = decide_tag(result.degradation_passed, result.dependency_passed)
    
    # CEO Directive 004: Suspicious strategies that pass get extra scrutiny tag
    if result.tag == ValidationTag.READY_FOR_PAPER and suspicion_flags:
        result.tag = "READY_FOR_PAPER_SUSPICIOUS"
        log.info(f"  ⚠️ Strategy passed gates but flagged SUSPICIOUS — requires manual review")
    
    result.overall_passed = result.tag == ValidationTag.READY_FOR_PAPER
    result.partial_pass = result.tag == ValidationTag.REQUIRES_HARDENING or result.tag == "READY_FOR_PAPER_SUSPICIOUS"
    
    # Compile fail summary
    result.fail_summary = result.degradation_fail_reasons + result.dependency_fail_reasons
    
    # ── HARD ENFORCEMENT ──
    if not result.degradation_passed or not result.dependency_passed:
        block_paper_trading()
    
    # Log decision
    tag_emoji = {
        ValidationTag.READY_FOR_PAPER: "🟢",
        ValidationTag.REQUIRES_HARDENING: "🟡",
        ValidationTag.REJECTED_POST_DARWIN: "🔴",
    }
    emoji = tag_emoji.get(result.tag, "❓")
    log.info(f"  {emoji} DECISION: {result.tag}")
    log.info(f"     Baseline: Sharpe={baseline.sharpe_ratio:.2f} WR={baseline.win_rate:.1%} DD={baseline.max_drawdown:.1%} Ret={baseline.total_return_pct:+.1f}%")
    log.info(f"     Gate 4 (Degradation): {'PASS' if result.degradation_passed else 'FAIL'}")
    log.info(f"     Gate 5 (Dependency):  {'PASS' if result.dependency_passed else 'FAIL'}")
    
    if result.fail_summary:
        log.info(f"     Failures: {result.fail_summary[:5]}")
    
    # Persist to log
    _log_validation(result)
    
    return result


# ── Batch Validation ───────────────────────────────────────────────────────

def validate_batch(
    dnas: List[dict],
    assets: List[str] = None,
    timeframe: str = "daily",
) -> List[FinalValidationResult]:
    """
    Validate a batch of strategies across multiple assets.
    Returns list of all results.
    """
    if assets is None:
        assets = ["CL", "NQ", "GC"]
    
    results = []
    for dna in dnas:
        for asset in assets:
            try:
                result = validate_strategy(dna, asset, timeframe)
                results.append(result)
            except Exception as e:
                log.error(f"Validation failed for {dna.get('strategy_code', '?')} on {asset}: {e}")
    
    # Save validated strategies (READY_FOR_PAPER only)
    paper_ready = [r for r in results if r.tag == ValidationTag.READY_FOR_PAPER]
    if paper_ready:
        _save_validated(paper_ready)
    
    # Summary
    n_ready = sum(1 for r in results if r.tag == ValidationTag.READY_FOR_PAPER)
    n_hardening = sum(1 for r in results if r.tag == ValidationTag.REQUIRES_HARDENING)
    n_rejected = sum(1 for r in results if r.tag == ValidationTag.REJECTED_POST_DARWIN)
    
    log.info(f"\n{'='*60}")
    log.info(f"  BATCH VALIDATION COMPLETE")
    log.info(f"  🟢 READY_FOR_PAPER:      {n_ready}")
    log.info(f"  🟡 REQUIRES_HARDENING:    {n_hardening}")
    log.info(f"  🔴 REJECTED_POST_DARWIN:  {n_rejected}")
    log.info(f"{'='*60}")
    
    return results


# ── Persistence ────────────────────────────────────────────────────────────

def _log_validation(result: FinalValidationResult):
    """Append validation result to JSONL log."""
    VALIDATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(VALIDATION_LOG_PATH, "a") as f:
        f.write(json.dumps(result.to_dict(), default=str) + "\n")


def _save_validated(results: List[FinalValidationResult]):
    """Save READY_FOR_PAPER strategies to validated file."""
    VALIDATED_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    existing = []
    if VALIDATED_PATH.exists():
        try:
            with open(VALIDATED_PATH) as f:
                existing = json.load(f)
        except:
            existing = []
    
    for r in results:
        entry = {
            "strategy_code": r.strategy_code,
            "asset": r.asset,
            "tag": r.tag,
            "timestamp": r.timestamp,
            "baseline_sharpe": r.baseline_sharpe,
            "baseline_win_rate": r.baseline_win_rate,
            "baseline_max_dd": r.baseline_max_dd,
            "baseline_return_pct": r.baseline_return_pct,
        }
        # Deduplicate by strategy_code + asset
        existing = [e for e in existing if not (
            e["strategy_code"] == r.strategy_code and e["asset"] == r.asset
        )]
        existing.append(entry)
    
    with open(VALIDATED_PATH, "w") as f:
        json.dump(existing, f, indent=2, default=str)


# ── Query Functions ────────────────────────────────────────────────────────

def is_paper_ready(strategy_code: str, asset: str) -> bool:
    """
    THE enforcement function.
    Returns True ONLY if strategy has been validated and tagged READY_FOR_PAPER.
    Called by any system that wants to promote to paper trading.
    """
    if not VALIDATED_PATH.exists():
        return False
    
    try:
        with open(VALIDATED_PATH) as f:
            validated = json.load(f)
        
        for entry in validated:
            if (entry["strategy_code"] == strategy_code and 
                entry["asset"] == asset and
                entry["tag"] == ValidationTag.READY_FOR_PAPER):
                return True
    except:
        pass
    
    return False


def get_validation_status(strategy_code: str) -> List[Dict]:
    """Get all validation results for a strategy."""
    results = []
    if not VALIDATION_LOG_PATH.exists():
        return results
    
    with open(VALIDATION_LOG_PATH) as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if entry.get("strategy_code") == strategy_code:
                    results.append(entry)
            except:
                continue
    
    return results

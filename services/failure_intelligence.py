#!/usr/bin/env python3
"""
Failure Intelligence — Structured Failure Logging & Pattern Learning

Every failure is training data for the next generation.

This module:
1. Captures STRUCTURED failure data (not just human strings)
2. Tags failure patterns (taxonomy)
3. Builds a failure knowledge base
4. Provides queries for the mutation engine to AVOID known-bad patterns

The failure DB becomes the system's immune system — 
it learns what doesn't work so it stops generating it.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import Counter

log = logging.getLogger("failure_intelligence")

PROJECT = Path(__file__).resolve().parents[1]
FAILURE_DB_PATH = PROJECT / "data" / "failure_intelligence.jsonl"
PATTERN_SUMMARY_PATH = PROJECT / "data" / "failure_patterns.json"


# ── Failure Taxonomy ───────────────────────────────────────────────────────

class FailureAxis:
    """Which validation axis failed."""
    DARWIN_WIN_RATE = "darwin.win_rate"
    DARWIN_SHARPE = "darwin.sharpe"
    DARWIN_DRAWDOWN = "darwin.drawdown"
    DARWIN_PROFIT_FACTOR = "darwin.profit_factor"
    DARWIN_TRADE_COUNT = "darwin.trade_count"
    DEGRADE_PARAM = "degradation.parameter"
    DEGRADE_EXEC = "degradation.execution"
    DEGRADE_DATA = "degradation.data"
    DEGRADE_DD_SPIKE = "degradation.dd_spike"
    DEGRADE_COLLAPSE = "degradation.equity_collapse"
    DEPEND_SINGLE_INDICATOR = "dependency.single_indicator"
    DEPEND_FRAGILE = "dependency.fragile_edge"
    INSPECT_OUTLIER = "inspection.outlier_dependency"
    INSPECT_REGIME_DEP = "inspection.regime_dependency"
    INSPECT_TEMPORAL_CLUSTER = "inspection.temporal_clustering"
    INSPECT_NOT_REPRODUCIBLE = "inspection.not_reproducible"


class FailurePattern:
    """Higher-level pattern tags — what the system should LEARN to avoid."""
    ADX_CRUTCH = "ADX_CRUTCH"                       # Edge depends on ADX regime gate
    SINGLE_INDICATOR_EDGE = "SINGLE_INDICATOR_EDGE"  # One indicator carries the whole strategy
    PARAM_SENSITIVE = "PARAM_SENSITIVE"              # ±10-20% breaks it = curve fit
    NOISE_FRAGILE = "NOISE_FRAGILE"                  # Data noise destroys the edge
    SLIPPAGE_SENSITIVE = "SLIPPAGE_SENSITIVE"         # Can't handle real-world execution
    OUTLIER_DEPENDENT = "OUTLIER_DEPENDENT"           # Few big wins carry everything
    REGIME_LOCKED = "REGIME_LOCKED"                   # Only works in one market regime
    LOW_TRADE_COUNT = "LOW_TRADE_COUNT"              # Not enough trades for significance
    OVERFIT = "OVERFIT"                              # General overfitting signal
    FRAGILE_EDGE = "FRAGILE_EDGE"                    # Edge concentrated, not distributed


# ── Structured Failure Record ──────────────────────────────────────────────

@dataclass
class FailureRecord:
    """One structured failure record — THE training data unit."""
    # Identity
    strategy_code: str
    asset: str
    style: str
    generation: int = 0
    parent: str = ""
    timestamp: str = ""
    
    # The DNA that failed (full params for learning)
    dna_snapshot: Dict = field(default_factory=dict)
    
    # Gate that rejected it
    rejected_at: str = ""  # "darwin" / "final_validation" / "deep_inspection"
    
    # Structured failure axes (which specific checks failed)
    failed_axes: List[str] = field(default_factory=list)
    
    # Quantitative failure data
    metrics: Dict[str, float] = field(default_factory=dict)  # actual values
    thresholds: Dict[str, float] = field(default_factory=dict)  # what was required
    deltas: Dict[str, float] = field(default_factory=dict)  # how far off
    
    # Degradation specifics (if applicable)
    degradation_details: List[Dict] = field(default_factory=list)
    # Each: {axis, scenario, metric, baseline, degraded, change_pct}
    
    # Dependency specifics (if applicable)  
    critical_dependencies: List[str] = field(default_factory=list)
    dependency_drops: Dict[str, float] = field(default_factory=dict)  # component -> pnl_drop_%
    
    # Pattern tags (high-level learning signals)
    patterns: List[str] = field(default_factory=list)
    
    # Human-readable summary (for debugging, not training)
    summary: str = ""
    
    def to_dict(self) -> dict:
        return asdict(self)


# ── Failure Recording Functions ────────────────────────────────────────────

def record_darwin_failure(
    dna: dict,
    asset: str,
    metrics: Dict[str, float],
) -> FailureRecord:
    """Record a Darwin gate failure with full context."""
    code = dna.get("strategy_code", "UNKNOWN")
    
    thresholds = {
        "win_rate": 0.40,
        "sharpe_ratio": 0.50,
        "max_drawdown": 0.10,
        "profit_factor": 1.10,
        "trade_count": 20,
    }
    
    failed_axes = []
    deltas = {}
    patterns = []
    
    wr = metrics.get("win_rate", 0)
    sr = metrics.get("sharpe_ratio", 0)
    dd = metrics.get("max_drawdown", 1)
    pf = metrics.get("profit_factor", 0)
    tc = metrics.get("trade_count", 0)
    
    if wr < thresholds["win_rate"]:
        failed_axes.append(FailureAxis.DARWIN_WIN_RATE)
        deltas["win_rate"] = round(wr - thresholds["win_rate"], 4)
    
    if sr < thresholds["sharpe_ratio"]:
        failed_axes.append(FailureAxis.DARWIN_SHARPE)
        deltas["sharpe_ratio"] = round(sr - thresholds["sharpe_ratio"], 4)
    
    if dd > thresholds["max_drawdown"]:
        failed_axes.append(FailureAxis.DARWIN_DRAWDOWN)
        deltas["max_drawdown"] = round(dd - thresholds["max_drawdown"], 4)
    
    if pf < thresholds["profit_factor"]:
        failed_axes.append(FailureAxis.DARWIN_PROFIT_FACTOR)
        deltas["profit_factor"] = round(pf - thresholds["profit_factor"], 4)
    
    if tc < thresholds["trade_count"]:
        failed_axes.append(FailureAxis.DARWIN_TRADE_COUNT)
        deltas["trade_count"] = tc - thresholds["trade_count"]
        patterns.append(FailurePattern.LOW_TRADE_COUNT)
    
    # Pattern detection
    if sr < 0:
        patterns.append(FailurePattern.OVERFIT)
    if dd > 0.15 and sr < 0:
        patterns.append(FailurePattern.PARAM_SENSITIVE)
    
    record = FailureRecord(
        strategy_code=code,
        asset=asset,
        style=dna.get("style", ""),
        generation=dna.get("generation", 0),
        parent=dna.get("parent", ""),
        timestamp=datetime.now(timezone.utc).isoformat(),
        dna_snapshot=_slim_dna(dna),
        rejected_at="darwin",
        failed_axes=failed_axes,
        metrics=metrics,
        thresholds=thresholds,
        deltas=deltas,
        patterns=patterns,
        summary=f"Darwin fail: {', '.join(failed_axes)}",
    )
    
    _persist(record)
    return record


def record_validation_failure(
    dna: dict,
    asset: str,
    fv_result: Any,  # FinalValidationResult
) -> FailureRecord:
    """Record a Final Validation failure with full degradation/dependency detail."""
    code = dna.get("strategy_code", "UNKNOWN")
    
    failed_axes = []
    patterns = []
    degradation_details = []
    dep_drops = {}
    
    # Parse degradation failures
    if not fv_result.degradation_passed:
        deg = fv_result.degradation_result or {}
        for axis in deg.get("axes", []):
            axis_name = axis.get("name", "")
            for scenario in axis.get("scenarios", []):
                if not scenario.get("passed", True):
                    # Structured detail
                    detail = {
                        "axis": axis_name,
                        "scenario": scenario.get("name", ""),
                        "description": scenario.get("description", ""),
                        "sharpe": scenario.get("sharpe", 0),
                        "sharpe_change_pct": scenario.get("sharpe_change_pct", 0),
                        "dd_change_pct": scenario.get("dd_change_pct", 0),
                        "wr_change_pp": scenario.get("wr_change_pp", 0),
                        "pnl_change_pct": scenario.get("pnl_change_pct", 0),
                        "total_return_pct": scenario.get("total_return_pct", 0),
                        "fail_reasons": scenario.get("fail_reasons", []),
                    }
                    degradation_details.append(detail)
                    
                    # Classify axis failure
                    if "parameter" in axis_name:
                        failed_axes.append(FailureAxis.DEGRADE_PARAM)
                        patterns.append(FailurePattern.PARAM_SENSITIVE)
                    elif "execution" in axis_name:
                        failed_axes.append(FailureAxis.DEGRADE_EXEC)
                        patterns.append(FailurePattern.SLIPPAGE_SENSITIVE)
                    elif "data" in axis_name:
                        failed_axes.append(FailureAxis.DEGRADE_DATA)
                        patterns.append(FailurePattern.NOISE_FRAGILE)
                    
                    if scenario.get("dd_change_pct", 0) > 50:
                        failed_axes.append(FailureAxis.DEGRADE_DD_SPIKE)
                    if scenario.get("total_return_pct", 0) < -50:
                        failed_axes.append(FailureAxis.DEGRADE_COLLAPSE)
    
    # Parse dependency failures
    if not fv_result.dependency_passed:
        dep = fv_result.dependency_result or {}
        crit_deps = dep.get("critical_dependencies", [])
        
        for comp in dep.get("components", []):
            if comp.get("is_critical", False):
                dep_drops[comp["component"]] = comp.get("pnl_change_pct", 0)
                
                # Detect ADX crutch specifically
                if "adx" in comp["component"].lower():
                    patterns.append(FailurePattern.ADX_CRUTCH)
                
                failed_axes.append(FailureAxis.DEPEND_SINGLE_INDICATOR)
        
        if dep.get("is_fragile", False):
            failed_axes.append(FailureAxis.DEPEND_FRAGILE)
            patterns.append(FailurePattern.FRAGILE_EDGE)
    
    # Deduplicate
    failed_axes = list(dict.fromkeys(failed_axes))
    patterns = list(dict.fromkeys(patterns))
    
    record = FailureRecord(
        strategy_code=code,
        asset=asset,
        style=dna.get("style", ""),
        generation=dna.get("generation", 0),
        parent=dna.get("parent", ""),
        timestamp=datetime.now(timezone.utc).isoformat(),
        dna_snapshot=_slim_dna(dna),
        rejected_at="final_validation",
        failed_axes=failed_axes,
        metrics={
            "baseline_sharpe": fv_result.baseline_sharpe,
            "baseline_win_rate": fv_result.baseline_win_rate,
            "baseline_max_dd": fv_result.baseline_max_dd,
            "baseline_return_pct": fv_result.baseline_return_pct,
        },
        degradation_details=degradation_details,
        critical_dependencies=fv_result.dependency_fail_reasons,
        dependency_drops=dep_drops,
        patterns=patterns,
        summary=f"FV fail ({fv_result.tag}): axes={failed_axes}, patterns={patterns}",
    )
    
    _persist(record)
    return record


def record_inspection_failure(
    dna: dict,
    asset: str,
    inspection_result: Any,  # DeepInspectionResult
) -> FailureRecord:
    """Record a deep inspection SUSPECT/REJECTED verdict."""
    code = dna.get("strategy_code", "UNKNOWN")
    
    failed_axes = []
    patterns = []
    
    td = inspection_result.trade_distribution or {}
    if isinstance(td, dict):
        if td.get("has_outlier_dependency"):
            failed_axes.append(FailureAxis.INSPECT_OUTLIER)
            patterns.append(FailurePattern.OUTLIER_DEPENDENT)
        if td.get("regime_dependent"):
            failed_axes.append(FailureAxis.INSPECT_REGIME_DEP)
            patterns.append(FailurePattern.REGIME_LOCKED)
        if td.get("has_temporal_clustering"):
            failed_axes.append(FailureAxis.INSPECT_TEMPORAL_CLUSTER)
    
    cv = inspection_result.clone_validation or {}
    if isinstance(cv, dict) and not cv.get("reproducible", True):
        failed_axes.append(FailureAxis.INSPECT_NOT_REPRODUCIBLE)
        patterns.append(FailurePattern.OVERFIT)
    
    record = FailureRecord(
        strategy_code=code,
        asset=asset,
        style=dna.get("style", ""),
        generation=dna.get("generation", 0),
        parent=dna.get("parent", ""),
        timestamp=datetime.now(timezone.utc).isoformat(),
        dna_snapshot=_slim_dna(dna),
        rejected_at="deep_inspection",
        failed_axes=failed_axes,
        patterns=patterns,
        summary=f"Inspection verdict: {inspection_result.verdict}, warnings: {inspection_result.warnings}",
    )
    
    _persist(record)
    return record


# ── Pattern Analysis (Query the Failure DB) ────────────────────────────────

def analyze_failure_patterns() -> Dict[str, Any]:
    """
    Analyze the failure DB and return pattern frequencies.
    This is what the mutation engine uses to avoid known-bad patterns.
    """
    if not FAILURE_DB_PATH.exists():
        return {"total_failures": 0, "patterns": {}, "axes": {}, "style_failures": {}}
    
    records = []
    with open(FAILURE_DB_PATH) as f:
        for line in f:
            try:
                records.append(json.loads(line.strip()))
            except:
                continue
    
    pattern_counts = Counter()
    axis_counts = Counter()
    style_failures = Counter()
    style_totals = Counter()
    gate_counts = Counter()
    
    # Per-style pattern tracking
    style_patterns = {}  # style -> {pattern: count}
    
    for r in records:
        style = r.get("style", "unknown")
        style_totals[style] += 1
        gate_counts[r.get("rejected_at", "unknown")] += 1
        
        for p in r.get("patterns", []):
            pattern_counts[p] += 1
            if style not in style_patterns:
                style_patterns[style] = Counter()
            style_patterns[style][p] += 1
        
        for a in r.get("failed_axes", []):
            axis_counts[a] += 1
    
    # Build avoidance rules
    avoidance_rules = []
    for pattern, count in pattern_counts.most_common(10):
        if count >= 5:  # pattern seen 5+ times = reliable signal
            avoidance_rules.append({
                "pattern": pattern,
                "occurrences": count,
                "recommendation": _pattern_recommendation(pattern),
            })
    
    summary = {
        "total_failures": len(records),
        "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
        "patterns": dict(pattern_counts.most_common(20)),
        "axes": dict(axis_counts.most_common(20)),
        "by_gate": dict(gate_counts),
        "by_style": dict(style_totals),
        "style_patterns": {k: dict(v.most_common(10)) for k, v in style_patterns.items()},
        "avoidance_rules": avoidance_rules,
    }
    
    # Persist summary
    PATTERN_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PATTERN_SUMMARY_PATH, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    
    return summary


def get_avoidance_rules(style: str = None) -> List[Dict]:
    """
    Get avoidance rules for the mutation engine.
    Returns patterns to avoid when generating new strategies.
    """
    if not PATTERN_SUMMARY_PATH.exists():
        analyze_failure_patterns()
    
    if not PATTERN_SUMMARY_PATH.exists():
        return []
    
    with open(PATTERN_SUMMARY_PATH) as f:
        summary = json.load(f)
    
    rules = summary.get("avoidance_rules", [])
    
    # Add style-specific patterns
    if style and style in summary.get("style_patterns", {}):
        style_pats = summary["style_patterns"][style]
        for pat, count in style_pats.items():
            if count >= 3:
                rules.append({
                    "pattern": pat,
                    "occurrences": count,
                    "style_specific": True,
                    "recommendation": _pattern_recommendation(pat),
                })
    
    return rules


def _pattern_recommendation(pattern: str) -> str:
    """Human-readable recommendation for each failure pattern."""
    recs = {
        FailurePattern.ADX_CRUTCH: "Reduce reliance on ADX as sole regime filter. Add independent entry logic.",
        FailurePattern.SINGLE_INDICATOR_EDGE: "Distribute edge across multiple independent signals.",
        FailurePattern.PARAM_SENSITIVE: "Widen parameter ranges. Use adaptive parameters or regime-aware tuning.",
        FailurePattern.NOISE_FRAGILE: "Add data smoothing. Reduce sensitivity to individual bar noise.",
        FailurePattern.SLIPPAGE_SENSITIVE: "Widen stops. Use limit orders. Avoid tight scalping entries.",
        FailurePattern.OUTLIER_DEPENDENT: "Improve average trade quality. Don't rely on home runs.",
        FailurePattern.REGIME_LOCKED: "Test across all regimes. Add regime-adaptive logic.",
        FailurePattern.LOW_TRADE_COUNT: "Loosen entry conditions. Test on more assets/timeframes.",
        FailurePattern.OVERFIT: "Simplify strategy. Remove unnecessary parameters. Test on out-of-sample data.",
        FailurePattern.FRAGILE_EDGE: "Edge must be distributed. No single component should be critical.",
    }
    return recs.get(pattern, "Review strategy logic for robustness.")


# ── Helpers ────────────────────────────────────────────────────────────────

def _slim_dna(dna: dict) -> dict:
    """Keep only the fields needed for learning — not the full verbose DNA."""
    return {
        "strategy_code": dna.get("strategy_code", ""),
        "style": dna.get("style", ""),
        "generation": dna.get("generation", 0),
        "parent": dna.get("parent", ""),
        "parameter_ranges": dna.get("parameter_ranges", {}),
        "regime_filter": dna.get("regime_filter", {}),
        "risk_reward": dna.get("risk_reward", {}),
        "exit_rules": dna.get("exit_rules", {}),
        "filters": dna.get("filters", []),
    }


def _persist(record: FailureRecord):
    """Append failure record to DB."""
    FAILURE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FAILURE_DB_PATH, "a") as f:
        f.write(json.dumps(record.to_dict(), default=str) + "\n")

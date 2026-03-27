#!/usr/bin/env python3
"""
Deep Strategy Inspection — Edge Decomposition & Clone Validation

When a strategy passes Final Validation (READY_FOR_PAPER), this module:

1. EDGE DECOMPOSITION
   - What is the core signal? (momentum / mean reversion / hybrid)
   - Break into: entry drivers, exit logic, filters
   - Identify what ACTUALLY creates the edge

2. TRADE DISTRIBUTION ANALYSIS
   - Clustered wins (temporal clustering)
   - Regime dependency
   - Outlier trades (are a few big wins carrying the whole thing?)

3. CLONE & REPRODUCE
   - Generate 5 slight variations
   - Run through full pipeline (Darwin + Final Validation)
   - Confirm the edge is REPRODUCIBLE, not an artifact

CEO Directive: This runs automatically for every READY_FOR_PAPER strategy.
"""

import json
import copy
import random
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

import numpy as np
import pandas as pd

import sys
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from services.darwin.backtester import (
    run_backtest, load_parquet, BacktestResult,
    ema, sma, rsi, atr, adx, bollinger_bands, z_score
)
from services.final_validation import (
    validate_strategy, ValidationTag, FinalValidationResult
)

log = logging.getLogger("deep_inspect")

INSPECTION_LOG_PATH = PROJECT / "data" / "deep_inspections.jsonl"
CLONE_RESULTS_PATH = PROJECT / "data" / "clone_validations.jsonl"


# ── 1. Edge Decomposition ─────────────────────────────────────────────────

@dataclass
class EdgeDecomposition:
    strategy_code: str
    style: str
    signal_type: str = ""           # momentum / mean_reversion / hybrid
    
    # Entry drivers
    entry_drivers: List[str] = field(default_factory=list)
    entry_driver_weights: Dict[str, float] = field(default_factory=dict)
    primary_entry_driver: str = ""
    
    # Exit logic
    exit_mechanism: str = ""
    exit_drivers: List[str] = field(default_factory=list)
    
    # Filters
    active_filters: List[str] = field(default_factory=list)
    filter_contribution: Dict[str, str] = field(default_factory=dict)  # filter -> "essential" / "helpful" / "negligible"
    
    # Edge source
    edge_source: str = ""           # what actually creates the edge
    edge_confidence: str = ""       # high / medium / low
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return asdict(self)


def decompose_edge(dna: dict, df: pd.DataFrame) -> EdgeDecomposition:
    """Break a strategy into its components and identify the real edge."""
    code = dna.get("strategy_code", "UNKNOWN")
    style = dna.get("style", "unknown")
    params = dna.get("parameter_ranges", {})
    
    decomp = EdgeDecomposition(strategy_code=code, style=style)
    
    # Classify signal type
    if style in ["momentum_breakout", "trend_following"]:
        decomp.signal_type = "momentum"
    elif style in ["mean_reversion"]:
        decomp.signal_type = "mean_reversion"
    elif style in ["scalping"]:
        decomp.signal_type = "hybrid"  # scalping uses both momentum and reversion
    elif style in ["volume_orderflow"]:
        decomp.signal_type = "mean_reversion"  # z-score based
    else:
        decomp.signal_type = "hybrid"
    
    # Identify entry drivers based on style
    close = df["close"]
    high, low, vol = df["high"], df["low"], df["volume"]
    
    if style == "momentum_breakout":
        decomp.entry_drivers = ["EMA crossover", "ADX trend strength", "Volume breakout"]
        decomp.primary_entry_driver = "EMA crossover"
        decomp.exit_mechanism = "EMA reverse crossover or ADX weakness"
        decomp.active_filters = ["ADX threshold", "Volume multiplier"]
        
    elif style == "mean_reversion":
        decomp.entry_drivers = ["RSI extreme", "Bollinger Band touch", "Price deviation"]
        decomp.primary_entry_driver = "RSI extreme"
        decomp.exit_mechanism = "RSI normalization or BB midline return"
        decomp.active_filters = ["RSI threshold", "BB period/std"]
        
    elif style == "scalping":
        decomp.entry_drivers = ["RSI oversold", "BB lower band", "Volume confirmation"]
        decomp.primary_entry_driver = "RSI oversold + BB touch"
        decomp.exit_mechanism = "RSI recovery or BB midline"
        decomp.active_filters = ["Volume multiplier", "RSI period"]
        
    elif style == "trend_following":
        decomp.entry_drivers = ["EMA alignment", "ADX strength", "Price above fast EMA"]
        decomp.primary_entry_driver = "EMA alignment"
        decomp.exit_mechanism = "EMA breakdown or trend reversal"
        decomp.active_filters = ["ADX threshold"]
        
    elif style == "volume_orderflow":
        decomp.entry_drivers = ["Z-score extreme", "Volume surge"]
        decomp.primary_entry_driver = "Z-score deviation"
        decomp.exit_mechanism = "Z-score normalization"
        decomp.active_filters = ["Volume multiplier", "Lookback period"]
    
    # Run component removal to quantify each driver
    baseline = run_backtest(dna, df)
    baseline_pnl = baseline.total_return_pct
    
    for key in params:
        modified = copy.deepcopy(dna)
        modified["parameter_ranges"][key] = [0, 0]  # neutralize
        result = run_backtest(modified, df)
        
        if baseline_pnl != 0:
            impact_pct = ((result.total_return_pct - baseline_pnl) / abs(baseline_pnl)) * 100
        else:
            impact_pct = 0
        
        decomp.entry_driver_weights[key] = round(impact_pct, 1)
        
        if impact_pct < -40:
            decomp.filter_contribution[key] = "essential"
            decomp.warnings.append(f"⚠️ {key} is essential — removing it causes {impact_pct:.0f}% PnL drop")
        elif impact_pct < -15:
            decomp.filter_contribution[key] = "helpful"
        else:
            decomp.filter_contribution[key] = "negligible"
    
    # Determine edge source
    essential_count = sum(1 for v in decomp.filter_contribution.values() if v == "essential")
    if essential_count == 0:
        decomp.edge_source = "Distributed — edge spread across multiple signals (GOOD)"
        decomp.edge_confidence = "high"
    elif essential_count == 1:
        essential_key = [k for k, v in decomp.filter_contribution.items() if v == "essential"][0]
        decomp.edge_source = f"Concentrated in {essential_key} (CAUTION)"
        decomp.edge_confidence = "medium"
        decomp.warnings.append(f"Edge depends heavily on {essential_key}")
    else:
        decomp.edge_source = f"Multi-concentrated ({essential_count} essential components)"
        decomp.edge_confidence = "low"
        decomp.warnings.append("Multiple essential dependencies — fragile")
    
    return decomp


# ── 2. Trade Distribution Analysis ────────────────────────────────────────

@dataclass
class TradeDistribution:
    strategy_code: str
    total_trades: int = 0
    
    # Temporal clustering
    monthly_trade_counts: Dict[str, int] = field(default_factory=dict)
    has_temporal_clustering: bool = False
    clustering_months: List[str] = field(default_factory=list)  # months with >2x avg trades
    
    # Regime dependency
    regime_breakdown: Dict[str, Dict] = field(default_factory=dict)  # regime -> {trades, win_rate, pnl}
    regime_dependent: bool = False
    dominant_regime: str = ""
    
    # Outlier analysis
    top_5_trades_pct_of_total: float = 0.0  # what % of total PnL comes from top 5 trades
    has_outlier_dependency: bool = False     # >50% of PnL from top 5 trades
    
    # Win/loss distribution
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    median_win_pct: float = 0.0
    median_loss_pct: float = 0.0
    win_std: float = 0.0
    loss_std: float = 0.0
    
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return asdict(self)


def analyze_trade_distribution(dna: dict, df: pd.DataFrame) -> TradeDistribution:
    """Analyze trade distribution for clustering, regime dependency, and outliers."""
    code = dna.get("strategy_code", "UNKNOWN")
    
    result = run_backtest(dna, df)
    trades = result.trade_log
    
    dist = TradeDistribution(strategy_code=code, total_trades=len(trades))
    
    if len(trades) < 5:
        dist.warnings.append("Too few trades for meaningful distribution analysis")
        return dist
    
    pnls = [t["pnl_pct"] for t in trades]
    pnl_arr = np.array(pnls)
    wins = pnl_arr[pnl_arr > 0]
    losses = pnl_arr[pnl_arr <= 0]
    
    # ── Win/loss distribution ──
    if len(wins) > 0:
        dist.avg_win_pct = round(float(wins.mean()) * 100, 4)
        dist.median_win_pct = round(float(np.median(wins)) * 100, 4)
        dist.win_std = round(float(wins.std()) * 100, 4) if len(wins) > 1 else 0
    if len(losses) > 0:
        dist.avg_loss_pct = round(float(losses.mean()) * 100, 4)
        dist.median_loss_pct = round(float(np.median(losses)) * 100, 4)
        dist.loss_std = round(float(losses.std()) * 100, 4) if len(losses) > 1 else 0
    
    # ── Temporal clustering ──
    for trade in trades:
        entry_time = trade.get("entry_time", "")
        if entry_time:
            try:
                month = entry_time[:7]  # YYYY-MM
                dist.monthly_trade_counts[month] = dist.monthly_trade_counts.get(month, 0) + 1
            except:
                pass
    
    if dist.monthly_trade_counts:
        counts = list(dist.monthly_trade_counts.values())
        avg_monthly = np.mean(counts) if counts else 0
        if avg_monthly > 0:
            for month, count in dist.monthly_trade_counts.items():
                if count > avg_monthly * 2.5:
                    dist.clustering_months.append(f"{month} ({count} trades, avg={avg_monthly:.1f})")
        dist.has_temporal_clustering = len(dist.clustering_months) > 0
        if dist.has_temporal_clustering:
            dist.warnings.append(f"Temporal clustering detected in {len(dist.clustering_months)} month(s)")
    
    # ── Outlier analysis ──
    total_pnl = float(pnl_arr.sum())
    if total_pnl > 0 and len(pnl_arr) >= 5:
        sorted_pnls = np.sort(pnl_arr)[::-1]  # descending
        top_5_pnl = float(sorted_pnls[:5].sum())
        dist.top_5_trades_pct_of_total = round((top_5_pnl / total_pnl) * 100, 1)
        dist.has_outlier_dependency = dist.top_5_trades_pct_of_total > 50
        if dist.has_outlier_dependency:
            dist.warnings.append(
                f"Outlier dependency: top 5 trades account for {dist.top_5_trades_pct_of_total:.0f}% of total PnL"
            )
    
    # ── Regime dependency ──
    # Classify each bar into regime, then map trades to regimes
    _adx = adx(df["high"], df["low"], df["close"], 14)
    _atr = atr(df["high"], df["low"], df["close"], 14)
    
    regime = pd.Series("ranging", index=df.index)
    regime[_adx > 25] = "trending"
    atr_pct = _atr.rolling(50).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)
    regime[(atr_pct > 0.75) & (_adx < 25)] = "volatile"
    
    regime_trades = {"trending": [], "ranging": [], "volatile": []}
    
    for trade in trades:
        entry_time = trade.get("entry_time", "")
        if entry_time:
            try:
                ts = pd.Timestamp(entry_time)
                # Find nearest index
                idx = df.index.get_indexer([ts], method="nearest")[0]
                if 0 <= idx < len(regime):
                    r = regime.iloc[idx]
                    regime_trades[r].append(trade["pnl_pct"])
            except:
                pass
    
    for r_name, r_pnls in regime_trades.items():
        if r_pnls:
            r_arr = np.array(r_pnls)
            dist.regime_breakdown[r_name] = {
                "trades": len(r_pnls),
                "win_rate": round(float((r_arr > 0).mean()), 3),
                "total_pnl_pct": round(float(r_arr.sum()) * 100, 2),
                "avg_pnl_pct": round(float(r_arr.mean()) * 100, 4),
            }
        else:
            dist.regime_breakdown[r_name] = {"trades": 0, "win_rate": 0, "total_pnl_pct": 0}
    
    # Check for regime dependency
    regime_pnls = {k: v.get("total_pnl_pct", 0) for k, v in dist.regime_breakdown.items() if v.get("trades", 0) > 0}
    if regime_pnls:
        total_regime_pnl = sum(abs(v) for v in regime_pnls.values())
        if total_regime_pnl > 0:
            for r_name, r_pnl in regime_pnls.items():
                if abs(r_pnl) / total_regime_pnl > 0.70:
                    dist.regime_dependent = True
                    dist.dominant_regime = r_name
                    dist.warnings.append(f"Regime dependent: {r_pnl:.1f}% of PnL from {r_name} regime")
    
    return dist


# ── 3. Clone & Reproduce ──────────────────────────────────────────────────

def clone_strategy(dna: dict, clone_id: int) -> dict:
    """Create a slight variation — ±5% parameter shifts only."""
    clone = copy.deepcopy(dna)
    base_code = dna["strategy_code"]
    clone["strategy_code"] = f"{base_code}-clone{clone_id}"
    clone["parent"] = base_code
    clone["clone_timestamp"] = datetime.now(timezone.utc).isoformat()
    
    params = clone.get("parameter_ranges", {})
    for key, val in params.items():
        if isinstance(val, (list, tuple)) and len(val) == 2:
            try:
                lo, hi = float(val[0]), float(val[1])
                # ±5% shift — SLIGHT variation only
                shift = random.uniform(-0.05, 0.05)
                params[key] = [round(lo * (1 + shift), 4), round(hi * (1 + shift), 4)]
            except:
                pass
        elif isinstance(val, (int, float)):
            try:
                shift = random.uniform(-0.05, 0.05)
                new_val = float(val) * (1 + shift)
                params[key] = int(round(new_val)) if isinstance(val, int) else round(new_val, 4)
            except:
                pass
    
    return clone


def clone_and_validate(
    dna: dict,
    asset: str,
    timeframe: str = "daily",
    n_clones: int = 5,
) -> Dict[str, Any]:
    """
    Clone a strategy with slight variations and validate each.
    Confirms the edge is REPRODUCIBLE, not an artifact.
    """
    code = dna.get("strategy_code", "UNKNOWN")
    log.info(f"  🧬 Cloning {code} — {n_clones} variations...")
    
    results = {
        "parent": code,
        "asset": asset,
        "n_clones": n_clones,
        "clones_passed_darwin": 0,
        "clones_passed_final": 0,
        "clone_results": [],
        "reproducible": False,
        "reproduction_rate": 0.0,
    }
    
    for i in range(n_clones):
        clone = clone_strategy(dna, i + 1)
        
        try:
            # Quick backtest first
            df = load_parquet(asset, timeframe)
            bt = run_backtest(clone, df)
            
            clone_data = {
                "clone_code": clone["strategy_code"],
                "trade_count": bt.trade_count,
                "win_rate": bt.win_rate,
                "sharpe_ratio": bt.sharpe_ratio,
                "max_drawdown": bt.max_drawdown,
                "total_return_pct": bt.total_return_pct,
                "profit_factor": bt.profit_factor,
            }
            
            # Check Darwin criteria
            darwin_pass = (
                bt.trade_count >= 20 and
                bt.win_rate >= 0.40 and
                bt.sharpe_ratio >= 0.5 and
                bt.max_drawdown <= 0.10 and
                bt.profit_factor >= 1.1
            )
            clone_data["darwin_pass"] = darwin_pass
            
            if darwin_pass:
                results["clones_passed_darwin"] += 1
                
                # Run full Final Validation
                fv = validate_strategy(clone, asset, timeframe)
                clone_data["final_validation_tag"] = fv.tag
                clone_data["degradation_passed"] = fv.degradation_passed
                clone_data["dependency_passed"] = fv.dependency_passed
                
                if fv.tag == ValidationTag.READY_FOR_PAPER:
                    results["clones_passed_final"] += 1
                    log.info(f"    ✅ Clone {i+1}: READY_FOR_PAPER (Sharpe={bt.sharpe_ratio:.2f})")
                else:
                    log.info(f"    🟡 Clone {i+1}: {fv.tag} (Sharpe={bt.sharpe_ratio:.2f})")
            else:
                clone_data["final_validation_tag"] = "SKIPPED_DARWIN_FAIL"
                log.info(f"    ❌ Clone {i+1}: Darwin fail (Sharpe={bt.sharpe_ratio:.2f}, WR={bt.win_rate:.1%})")
            
            results["clone_results"].append(clone_data)
            
        except Exception as e:
            log.error(f"    ❌ Clone {i+1} error: {e}")
            results["clone_results"].append({"clone_code": clone["strategy_code"], "error": str(e)})
    
    # Reproducibility verdict
    results["reproduction_rate"] = results["clones_passed_final"] / n_clones if n_clones > 0 else 0
    results["reproducible"] = results["clones_passed_final"] >= 3  # at least 3/5 must pass
    
    return results


# ── Full Deep Inspection ───────────────────────────────────────────────────

@dataclass
class DeepInspectionResult:
    strategy_code: str
    asset: str
    timestamp: str = ""
    
    edge_decomposition: Optional[Dict] = None
    trade_distribution: Optional[Dict] = None
    clone_validation: Optional[Dict] = None
    
    verdict: str = ""  # "CONFIRMED" / "SUSPECT" / "REJECTED"
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return asdict(self)


def deep_inspect(
    dna: dict,
    asset: str,
    timeframe: str = "daily",
    n_clones: int = 5,
) -> DeepInspectionResult:
    """
    Full deep inspection of a READY_FOR_PAPER strategy.
    
    1. Edge Decomposition — what's the real signal?
    2. Trade Distribution — clustering, regime dependency, outliers
    3. Clone & Reproduce — confirm it's reproducible
    
    Returns verdict: CONFIRMED / SUSPECT / REJECTED
    """
    code = dna.get("strategy_code", "UNKNOWN")
    log.info(f"\n{'='*60}")
    log.info(f"  🔬 DEEP INSPECTION: {code} on {asset}")
    log.info(f"{'='*60}")
    
    df = load_parquet(asset, timeframe)
    
    result = DeepInspectionResult(
        strategy_code=code,
        asset=asset,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    
    all_warnings = []
    
    # ── Step 1: Edge Decomposition ──
    log.info(f"\n  📊 Step 1: Edge Decomposition")
    try:
        decomp = decompose_edge(dna, df)
        result.edge_decomposition = decomp.to_dict()
        all_warnings.extend(decomp.warnings)
        
        log.info(f"    Signal type: {decomp.signal_type}")
        log.info(f"    Primary driver: {decomp.primary_entry_driver}")
        log.info(f"    Edge source: {decomp.edge_source}")
        log.info(f"    Confidence: {decomp.edge_confidence}")
        for w in decomp.warnings:
            log.info(f"    ⚠️ {w}")
    except Exception as e:
        log.error(f"    Edge decomposition failed: {e}")
        result.edge_decomposition = {"error": str(e)}
    
    # ── Step 2: Trade Distribution ──
    log.info(f"\n  📈 Step 2: Trade Distribution Analysis")
    try:
        dist = analyze_trade_distribution(dna, df)
        result.trade_distribution = dist.to_dict()
        all_warnings.extend(dist.warnings)
        
        log.info(f"    Total trades: {dist.total_trades}")
        log.info(f"    Avg win: {dist.avg_win_pct:.3f}% | Avg loss: {dist.avg_loss_pct:.3f}%")
        log.info(f"    Temporal clustering: {'YES ⚠️' if dist.has_temporal_clustering else 'No ✅'}")
        log.info(f"    Regime dependent: {'YES ⚠️' if dist.regime_dependent else 'No ✅'}")
        log.info(f"    Outlier dependency: {'YES ⚠️' if dist.has_outlier_dependency else 'No ✅'}")
        if dist.regime_breakdown:
            for r_name, r_data in dist.regime_breakdown.items():
                log.info(f"      {r_name}: {r_data.get('trades', 0)} trades, WR={r_data.get('win_rate', 0):.1%}, PnL={r_data.get('total_pnl_pct', 0):+.2f}%")
        for w in dist.warnings:
            log.info(f"    ⚠️ {w}")
    except Exception as e:
        log.error(f"    Trade distribution failed: {e}")
        result.trade_distribution = {"error": str(e)}
    
    # ── Step 3: Clone & Reproduce ──
    log.info(f"\n  🧬 Step 3: Clone & Reproduce ({n_clones} clones)")
    try:
        clone_results = clone_and_validate(dna, asset, timeframe, n_clones)
        result.clone_validation = clone_results
        
        log.info(f"    Clones passed Darwin: {clone_results['clones_passed_darwin']}/{n_clones}")
        log.info(f"    Clones passed Final Validation: {clone_results['clones_passed_final']}/{n_clones}")
        log.info(f"    Reproduction rate: {clone_results['reproduction_rate']:.0%}")
        log.info(f"    Reproducible: {'YES ✅' if clone_results['reproducible'] else 'NO ⚠️'}")
        
        if not clone_results["reproducible"]:
            all_warnings.append(f"Edge NOT reproducible — only {clone_results['clones_passed_final']}/{n_clones} clones passed")
    except Exception as e:
        log.error(f"    Clone validation failed: {e}")
        result.clone_validation = {"error": str(e)}
    
    # ── Verdict ──
    result.warnings = all_warnings
    
    critical_warnings = [w for w in all_warnings if "⚠️" in w or "essential" in w.lower() or "fragile" in w.lower() or "NOT reproducible" in w.lower()]
    
    clone_ok = result.clone_validation and result.clone_validation.get("reproducible", False)
    no_outlier_dep = result.trade_distribution and not result.trade_distribution.get("has_outlier_dependency", True)
    edge_ok = result.edge_decomposition and result.edge_decomposition.get("edge_confidence") in ["high", "medium"]
    
    if clone_ok and no_outlier_dep and edge_ok and len(critical_warnings) <= 1:
        result.verdict = "CONFIRMED"
    elif clone_ok or (no_outlier_dep and edge_ok):
        result.verdict = "SUSPECT"
    else:
        result.verdict = "REJECTED"
    
    verdict_emoji = {"CONFIRMED": "✅", "SUSPECT": "🟡", "REJECTED": "🔴"}
    log.info(f"\n  {verdict_emoji.get(result.verdict, '❓')} VERDICT: {result.verdict}")
    log.info(f"  Warnings: {len(all_warnings)}")
    for w in all_warnings:
        log.info(f"    - {w}")
    
    # Persist
    _log_inspection(result)
    
    return result


def _log_inspection(result: DeepInspectionResult):
    """Persist inspection result."""
    INSPECTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INSPECTION_LOG_PATH, "a") as f:
        f.write(json.dumps(result.to_dict(), default=str) + "\n")

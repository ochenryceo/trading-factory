#!/usr/bin/env python3
"""
Gen 3 DNA Creation + Cross-Market Validation + Gen 3 Fast Validation
All three tasks in one script.
"""
import json
import sys
import copy
from pathlib import Path

# Project root
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from services.fast_validation.vectorbt_runner import run_fast_validation

DATA_DIR = PROJECT / "data"
MOCK_DIR = DATA_DIR / "mock"

# ──────────────────────────────────────────────────────────────
# TASK 1: Create Gen 3 DNAs
# ──────────────────────────────────────────────────────────────

def load_gen2_dnas():
    with open(DATA_DIR / "strategy_dnas_v2.json") as f:
        return json.load(f)

def upgrade_to_gen3(dna):
    """Apply all 5 Gen 3 fixes to a Gen 2 DNA."""
    g3 = copy.deepcopy(dna)
    
    # Update code and generation
    old_code = g3["strategy_code"]
    g3["strategy_code"] = old_code.replace("-G2-", "-G3-")
    g3["generation"] = 3
    
    # Fix 1: Breakout Strength Filters
    g3["entry_filters"] = {
        "range_expansion": True,
        "atr_expansion": True,
        "avoid_first_candle": True,
        "min_bars_since_level": 3
    }
    
    # Fix 2: Confirmation Stacking
    g3["confirmation_stack"] = {
        "min_confirmations": 3,
        "checks": [
            "trend_aligned",
            "structure_confirmed",
            "momentum_confirmed",
            "volume_confirmed",
            "vwap_confirmed"
        ]
    }
    
    # Fix 3: Trade Quality Gate
    g3["trade_quality_gate"] = {
        "min_score": 0.65,
        "scoring": {
            "trend_strength": 0.25,
            "breakout_strength": 0.25,
            "volume_confirmation": 0.25,
            "alignment_score": 0.25
        }
    }
    
    # Fix 4: Better Exits
    g3["exit_rules"] = {
        "partial_tp_1": {"at_r": 1.0, "close_pct": 0.33},
        "partial_tp_2": {"at_r": 2.0, "close_pct": 0.33},
        "runner": {"trailing_atr": 2.0},
        "structure_exit": True,
        "time_limit_bars": 15,
        "breakeven_at_r": 0.75
    }
    
    # Fix 5: Enforce Asymmetry
    g3["risk_reward"] = {
        "min_rr": 2.5,
        "target_rr": 3.5,
        "stop_method": "structure_plus_atr",
        "stop_atr_multiplier": 1.0
    }
    
    # Update signal filters to require 3 confirmations (aligned with confirmation_stack)
    if "signal_filters" in g3:
        g3["signal_filters"]["min_confirmations"] = 3
        g3["signal_filters"]["min_signal_strength"] = 0.70
    
    # Update description
    g3["description"] = f"[Gen3] {g3['description']} — upgraded with entry quality filters, confirmation stacking, trade quality gate, partial exits, and enforced asymmetry"
    
    # Add gen3 improvements
    g3["gen3_improvements"] = [
        "Breakout strength filters: range expansion, ATR expansion, fakeout avoidance",
        "Confirmation stacking: 3 of 5 checks required (trend, structure, momentum, volume, VWAP)",
        "Trade quality gate: min score 0.65 across 4 weighted dimensions",
        "Partial exits: 1/3 at 1R, 1/3 at 2R, 1/3 runner with 2 ATR trail",
        "Enforced asymmetry: min 2.5 RR, target 3.5 RR, structure+ATR stops"
    ]
    
    return g3

def create_gen3_dnas():
    gen2 = load_gen2_dnas()
    gen3 = [upgrade_to_gen3(d) for d in gen2]
    
    out_path = DATA_DIR / "strategy_dnas_v3.json"
    with open(out_path, "w") as f:
        json.dump(gen3, f, indent=2)
    
    print(f"✅ TASK 1 COMPLETE: Created {len(gen3)} Gen 3 DNAs → {out_path}")
    print(f"   Styles: {sorted(set(d['style'] for d in gen3))}")
    print(f"   Codes: {[d['strategy_code'] for d in gen3]}")
    return gen3

# ──────────────────────────────────────────────────────────────
# TASK 2: Cross-Market Validation (Gen 1 + Gen 2)
# ──────────────────────────────────────────────────────────────

def load_gen1_dnas():
    with open(DATA_DIR / "mock" / "strategy_dnas.json") as f:
        return json.load(f)

def load_gen1_results():
    with open(MOCK_DIR / "fast_validation_results.json") as f:
        data = json.load(f)
    # Only Gen 1 results (no G2 suffix)
    return [r for r in data if r.get("generation") == 1 or "-G2-" not in r.get("strategy_id", "")]

def run_cross_market_validation():
    """Run Gen 1 + Gen 2 strategies through fast validation on NQ, GC, CL."""
    
    # Load DNAs
    gen2_dnas = load_gen2_dnas()
    
    # Try to load Gen 1 DNAs from the original file
    gen1_path = DATA_DIR / "mock" / "strategy_dnas.json"
    if not gen1_path.exists():
        # Fall back - load from the main dnas file
        gen1_path = DATA_DIR / "strategy_dnas.json"
    
    if gen1_path.exists():
        with open(gen1_path) as f:
            gen1_dnas = json.load(f)
    else:
        gen1_dnas = []
    
    all_dnas = gen1_dnas + gen2_dnas
    markets = ["NQ", "GC", "CL"]
    
    print(f"\n🔄 TASK 2: Cross-market validation — {len(all_dnas)} strategies × {len(markets)} markets")
    
    all_results = []
    style_market_results = {}  # {style: {market: [results]}}
    
    for dna in all_dnas:
        sid = dna.get("strategy_code", "UNKNOWN")
        style = dna.get("style", "unknown")
        gen = dna.get("generation", 1)
        
        for market in markets:
            print(f"  Testing {sid} on {market}...", end=" ")
            try:
                result = run_fast_validation(dna=dna, asset=market, last_n_days=30)
                r_dict = result.to_dict()
                r_dict["generation"] = gen
                r_dict["style"] = style
                r_dict["market"] = market
                all_results.append(r_dict)
                
                # Track by style+market
                if style not in style_market_results:
                    style_market_results[style] = {}
                if market not in style_market_results[style]:
                    style_market_results[style][market] = []
                style_market_results[style][market].append(r_dict)
                
                print(f"{result.status} (WR: {r_dict['metrics'].get('win_rate', 0):.1%}, PnL: ${r_dict['metrics'].get('total_pnl', 0):.0f})")
            except Exception as e:
                print(f"ERROR: {e}")
                all_results.append({
                    "strategy_id": sid,
                    "status": "FAIL",
                    "reason": str(e),
                    "metrics": {},
                    "market": market,
                    "generation": gen,
                    "style": style
                })
    
    # Build matrix
    matrix = {}
    best_market = {}
    details = {}
    
    for style, markets_data in style_market_results.items():
        matrix[style] = {}
        details[style] = {}
        best_score = -999
        best_m = "NQ"
        
        for market, results in markets_data.items():
            pass_count = sum(1 for r in results if r["status"] == "PASS")
            total = len(results)
            avg_pnl = sum(r["metrics"].get("total_pnl", 0) for r in results) / max(total, 1)
            avg_wr = sum(r["metrics"].get("win_rate", 0) for r in results) / max(total, 1)
            avg_conf = sum(r.get("confidence", 0) for r in results) / max(total, 1)
            
            matrix[style][market] = "PASS" if pass_count > total / 2 else "FAIL"
            details[style][market] = {
                "pass_count": pass_count,
                "total": total,
                "pass_rate": round(pass_count / max(total, 1), 2),
                "avg_pnl": round(avg_pnl, 2),
                "avg_win_rate": round(avg_wr, 4),
                "avg_confidence": round(avg_conf, 3),
                "strategies": [{
                    "id": r["strategy_id"],
                    "gen": r["generation"],
                    "status": r["status"],
                    "pnl": r["metrics"].get("total_pnl", 0),
                    "win_rate": r["metrics"].get("win_rate", 0),
                    "trades": r["metrics"].get("trade_count", 0)
                } for r in results]
            }
            
            # Score for best market: weighted combo
            score = avg_pnl * 0.3 + avg_wr * 1000 * 0.4 + avg_conf * 100 * 0.3
            if score > best_score:
                best_score = score
                best_m = market
        
        best_market[style] = best_m
    
    coverage = {
        "matrix": matrix,
        "best_market_per_style": best_market,
        "details": details,
        "total_tests": len(all_results),
        "total_pass": sum(1 for r in all_results if r["status"] == "PASS"),
        "total_fail": sum(1 for r in all_results if r["status"] == "FAIL"),
    }
    
    out_path = DATA_DIR / "market_coverage_matrix.json"
    with open(out_path, "w") as f:
        json.dump(coverage, f, indent=2)
    
    print(f"\n✅ TASK 2 COMPLETE: Market coverage matrix → {out_path}")
    print(f"   Total tests: {coverage['total_tests']} | PASS: {coverage['total_pass']} | FAIL: {coverage['total_fail']}")
    
    # Print matrix
    print("\n" + "=" * 70)
    print("MARKET COVERAGE MATRIX")
    print("=" * 70)
    print(f"{'Style':<25} {'NQ':>8} {'GC':>8} {'CL':>8} {'Best':>8}")
    print("-" * 70)
    for style in sorted(matrix.keys()):
        nq = matrix[style].get("NQ", "N/A")
        gc = matrix[style].get("GC", "N/A")
        cl = matrix[style].get("CL", "N/A")
        best = best_market[style]
        print(f"{style:<25} {nq:>8} {gc:>8} {cl:>8} {best:>8}")
    print("=" * 70)
    
    return coverage, all_results

# ──────────────────────────────────────────────────────────────
# TASK 3: Run Gen 3 Through Fast Validation
# ──────────────────────────────────────────────────────────────

def run_gen3_validation(gen3_dnas):
    """Run all 24 Gen 3 DNAs through fast validation on NQ, GC, CL."""
    markets = ["NQ", "GC", "CL"]
    results = []
    
    print(f"\n🔄 TASK 3: Gen 3 fast validation — {len(gen3_dnas)} strategies × {len(markets)} markets")
    
    for dna in gen3_dnas:
        sid = dna["strategy_code"]
        style = dna["style"]
        
        for market in markets:
            print(f"  Testing {sid} on {market}...", end=" ")
            try:
                result = run_fast_validation(dna=dna, asset=market, last_n_days=30)
                r_dict = result.to_dict()
                r_dict["generation"] = 3
                r_dict["style"] = style
                r_dict["market"] = market
                results.append(r_dict)
                print(f"{result.status} (WR: {r_dict['metrics'].get('win_rate', 0):.1%}, PnL: ${r_dict['metrics'].get('total_pnl', 0):.0f}, Conf: {r_dict.get('confidence', 0):.3f})")
            except Exception as e:
                print(f"ERROR: {e}")
                results.append({
                    "strategy_id": sid,
                    "status": "FAIL",
                    "reason": str(e),
                    "metrics": {},
                    "market": market,
                    "generation": 3,
                    "style": style,
                    "confidence": 0,
                    "queue_priority": "",
                    "fail_reasons": [str(e)]
                })
    
    # Save results (NQ-only for the main v3 results file, all for extended)
    nq_results = [r for r in results if r.get("market") == "NQ"]
    out_path = MOCK_DIR / "fast_validation_results_v3.json"
    with open(out_path, "w") as f:
        json.dump(nq_results, f, indent=2)
    
    # Also save full cross-market results
    full_path = MOCK_DIR / "fast_validation_results_v3_all_markets.json"
    with open(full_path, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\n✅ TASK 3 COMPLETE: Gen 3 validation results → {out_path}")
    
    return results, nq_results

# ──────────────────────────────────────────────────────────────
# Comparison & Summary
# ──────────────────────────────────────────────────────────────

def print_comparison(gen3_nq_results):
    """Print Gen 1 vs Gen 2 vs Gen 3 comparison."""
    
    # Load Gen 1 and Gen 2 NQ results
    with open(MOCK_DIR / "fast_validation_results.json") as f:
        all_old = json.load(f)
    
    gen1_nq = [r for r in all_old if r.get("generation") == 1]
    gen2_nq = [r for r in all_old if r.get("generation") == 2]
    
    def summarize(results, label):
        total = len(results)
        passed = sum(1 for r in results if r["status"] == "PASS")
        failed = total - passed
        avg_conf = sum(r.get("confidence", 0) for r in results) / max(total, 1)
        avg_pnl = sum(r["metrics"].get("total_pnl", 0) for r in results if r["metrics"]) / max(total, 1)
        avg_wr = sum(r["metrics"].get("win_rate", 0) for r in results if r["metrics"]) / max(total, 1)
        
        # Queue breakdown
        immediate = sum(1 for r in results if r.get("queue_priority") == "IMMEDIATE")
        batch = sum(1 for r in results if r.get("queue_priority") == "BATCH")
        archive = sum(1 for r in results if r.get("queue_priority") == "ARCHIVE")
        
        return {
            "label": label,
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / max(total, 1), 2),
            "avg_confidence": round(avg_conf, 3),
            "avg_pnl": round(avg_pnl, 2),
            "avg_win_rate": round(avg_wr, 4),
            "immediate": immediate,
            "batch": batch,
            "archive": archive,
        }
    
    g1 = summarize(gen1_nq, "Gen 1")
    g2 = summarize(gen2_nq, "Gen 2")
    g3 = summarize(gen3_nq_results, "Gen 3")
    
    print("\n" + "=" * 80)
    print("GENERATION COMPARISON: Gen 1 vs Gen 2 vs Gen 3 (NQ)")
    print("=" * 80)
    print(f"{'Metric':<25} {'Gen 1':>15} {'Gen 2':>15} {'Gen 3':>15}")
    print("-" * 80)
    for key in ["total", "passed", "failed", "pass_rate", "avg_confidence", "avg_pnl", "avg_win_rate", "immediate", "batch", "archive"]:
        print(f"{key:<25} {str(g1[key]):>15} {str(g2[key]):>15} {str(g3[key]):>15}")
    print("=" * 80)
    
    # Flag IMMEDIATE queue hits
    immediate_hits = [r for r in gen3_nq_results if r.get("queue_priority") == "IMMEDIATE"]
    if immediate_hits:
        print("\n🚀 IMMEDIATE QUEUE HITS (Gen 3):")
        for r in immediate_hits:
            print(f"   {r['strategy_id']} — Confidence: {r.get('confidence', 0):.3f}, PnL: ${r['metrics'].get('total_pnl', 0):.2f}, WR: {r['metrics'].get('win_rate', 0):.1%}")
    else:
        print("\n⚠️  No IMMEDIATE queue hits in Gen 3 (NQ)")
    
    return g1, g2, g3

# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("TRADING FACTORY: Gen 3 + Cross-Market Validation")
    print("=" * 70)
    
    # Check for gen1 dnas file
    gen1_path = DATA_DIR / "mock" / "strategy_dnas.json"
    if not gen1_path.exists():
        # Check main path
        gen1_path2 = DATA_DIR / "strategy_dnas.json"
        if gen1_path2.exists():
            print(f"Using Gen 1 DNAs from: {gen1_path2}")
        else:
            print("⚠️  No Gen 1 DNA file found — will only use Gen 2 for cross-market")
    
    # TASK 1
    gen3_dnas = create_gen3_dnas()
    
    # TASK 2
    coverage, cross_results = run_cross_market_validation()
    
    # TASK 3
    gen3_all_results, gen3_nq_results = run_gen3_validation(gen3_dnas)
    
    # Comparison
    g1_summary, g2_summary, g3_summary = print_comparison(gen3_nq_results)
    
    # Print Gen 3 cross-market matrix
    print("\n" + "=" * 70)
    print("GEN 3 CROSS-MARKET PERFORMANCE")
    print("=" * 70)
    
    styles = sorted(set(r["style"] for r in gen3_all_results))
    markets = ["NQ", "GC", "CL"]
    
    print(f"{'Style':<25} {'NQ':>12} {'GC':>12} {'CL':>12}")
    print("-" * 70)
    for style in styles:
        row = {}
        for market in markets:
            style_market = [r for r in gen3_all_results if r["style"] == style and r.get("market") == market]
            passed = sum(1 for r in style_market if r["status"] == "PASS")
            total = len(style_market)
            avg_pnl = sum(r["metrics"].get("total_pnl", 0) for r in style_market if r["metrics"]) / max(total, 1)
            row[market] = f"{passed}/{total} ${avg_pnl:.0f}"
        print(f"{style:<25} {row['NQ']:>12} {row['GC']:>12} {row['CL']:>12}")
    print("=" * 70)
    
    # Write summary file
    summary = {
        "timestamp": "2026-03-22T21:41:00Z",
        "gen1_summary": g1_summary,
        "gen2_summary": g2_summary,
        "gen3_summary": g3_summary,
        "market_coverage": coverage["matrix"],
        "best_markets": coverage["best_market_per_style"],
        "gen3_immediate_hits": [r["strategy_id"] for r in gen3_nq_results if r.get("queue_priority") == "IMMEDIATE"],
        "gen3_batch_hits": [r["strategy_id"] for r in gen3_nq_results if r.get("queue_priority") == "BATCH"],
    }
    
    summary_path = DATA_DIR / "gen3_validation_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n📊 Full summary → {summary_path}")
    print("\n🏁 ALL TASKS COMPLETE")

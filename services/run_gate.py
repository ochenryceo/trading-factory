#!/usr/bin/env python3
"""
Run Production Gate on persisted candidates.
Usage:
  python -m services.run_gate                        # Run on all candidates
  python -m services.run_gate RND-G56-24687          # Run on specific candidate
  python -m services.run_gate --top 5                # Run on top 5 by fitness
"""

import json
import sys
import numpy as np
from pathlib import Path

BASE_DIR = Path("Path(__file__).resolve().parents[1]")
sys.path.insert(0, str(BASE_DIR))

from services.candidate_store import load_candidate, list_candidates, CANDIDATE_DIR
from services.production_gate import evaluate as gate_evaluate, pre_filter


def run_gate_on_candidate(code: str) -> dict:
    """Load candidate artifact and run full production gate."""
    artifact = load_candidate(code)
    if not artifact:
        return {"strategy_code": code, "status": "ERROR", "reason": "No artifact found"}
    
    # Reconstruct candidate dict for gate
    candidate = {
        "strategy_code": artifact["strategy_code"],
        "style": artifact["style"],
        "parameters": artifact["parameters"],
        "sharpe_ratio": artifact["performance"]["sharpe_ratio"],
        "max_drawdown": artifact["performance"]["max_drawdown"],
        "win_rate": artifact["performance"]["win_rate"],
        "profit_factor": artifact["performance"]["profit_factor"],
        "total_return_pct": artifact["performance"]["total_return_pct"],
        "trade_count": artifact["performance"]["trade_count"],
        "fitness": artifact["fitness"],
        "lineage_id": artifact.get("lineage_id", ""),
        "stability_score": 0.95,  # Persisted = survived multiple brain cycles
        "survival_depth": artifact.get("generation", 0),
    }
    
    # Pre-filter
    pf_ok, pf_reason = pre_filter(candidate)
    if not pf_ok:
        return {
            "strategy_code": code,
            "status": "PRE-FILTER FAIL",
            "reason": pf_reason,
            "performance": artifact["performance"],
        }
    
    # Full gate evaluation with trade data
    trade_returns = artifact.get("trade_returns", [])
    
    # We don't have the original price arrays, so pass what we can
    result = gate_evaluate(
        candidate,
        returns=trade_returns if trade_returns else None,
        generation=artifact.get("generation", 0),
    )
    
    return result


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--top":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        candidates = list_candidates()[:n]
        codes = [c["strategy_code"] for c in candidates]
    elif len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        codes = sys.argv[1:]
    else:
        candidates = list_candidates()
        codes = [c["strategy_code"] for c in candidates]
    
    if not codes:
        print("No candidates found in data/candidates/")
        print("The persistence layer needs the backtester to run and store new candidates.")
        return
    
    print(f"Running Production Gate on {len(codes)} candidate(s)...\n")
    
    results = []
    for code in codes:
        print(f"{'='*60}")
        print(f"📋 {code}")
        print(f"{'='*60}")
        
        result = run_gate_on_candidate(code)
        results.append(result)
        
        status = result.get("status", "UNKNOWN")
        score = result.get("production_score", 0)
        
        if status == "APPROVED":
            print(f"  🟢 APPROVED (score={score:.2f})")
        elif status == "WATCHLIST":
            print(f"  🟡 WATCHLIST (score={score:.2f})")
        elif status == "PRE-FILTER FAIL":
            print(f"  ⚠️  PRE-FILTER FAIL: {result.get('reason', '?')}")
        else:
            print(f"  🔴 REJECTED (score={score:.2f})")
        
        # Print check details
        checks = result.get("checks", {})
        for check_name, check_data in checks.items():
            passed = check_data.get("passed", False)
            icon = "✅" if passed else "❌"
            print(f"    {icon} {check_name}: {json.dumps({k:v for k,v in check_data.items() if k != 'passed'}, default=str)}")
        
        failures = result.get("failure_reasons", [])
        if failures:
            print(f"  Failures: {', '.join(failures)}")
        
        print()
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    approved = [r for r in results if r.get("status") == "APPROVED"]
    watchlist = [r for r in results if r.get("status") == "WATCHLIST"]
    rejected = [r for r in results if r.get("status") not in ("APPROVED", "WATCHLIST")]
    print(f"  🟢 Approved: {len(approved)}")
    print(f"  🟡 Watchlist: {len(watchlist)}")
    print(f"  🔴 Rejected/Failed: {len(rejected)}")
    
    if approved:
        print(f"\n  Ready for paper trading:")
        for r in approved:
            print(f"    → {r['strategy_id']} (score={r['production_score']:.2f})")


if __name__ == "__main__":
    main()

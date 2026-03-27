#!/usr/bin/env python3
"""
Run ALL Gen 3 DNAs through the upgraded vectorbt runner on NQ, GC, CL.
Saves results and prints comparison.
"""
import json
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.fast_validation.vectorbt_runner_v3_upgraded import run_fast_validation

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DNA_FILE = os.path.join(DATA_DIR, "strategy_dnas_v3.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "mock", "fast_validation_results_v3_upgraded.json")
PREV_RESULTS_FILE = os.path.join(DATA_DIR, "mock", "fast_validation_results_v3_all_markets.json")
COMBINED_FILE = os.path.join(DATA_DIR, "mock", "fast_validation_results.json")

MARKETS = ["NQ", "GC", "CL"]

def main():
    with open(DNA_FILE) as f:
        dnas = json.load(f)

    print(f"Running {len(dnas)} Gen 3 DNAs across {len(MARKETS)} markets...")
    print(f"Total runs: {len(dnas) * len(MARKETS)}")
    print("=" * 80)

    results = []
    for dna in dnas:
        sid = dna["strategy_code"]
        style = dna["style"]
        for market in MARKETS:
            print(f"  {sid} on {market} ({style})...", end=" ", flush=True)
            try:
                result = run_fast_validation(dna, asset=market)
                rd = result.to_dict()
                rd["generation"] = 3
                rd["style"] = style
                rd["market"] = market
                rd["runner_version"] = "v3_upgraded"
                results.append(rd)
                print(f"conf={rd['confidence']:.3f} {rd['status']} {rd.get('queue_priority', '')}")
            except Exception as e:
                print(f"ERROR: {e}")
                results.append({
                    "strategy_id": sid,
                    "status": "FAIL",
                    "reason": f"Runner error: {e}",
                    "metrics": {},
                    "tested_window": "N/A",
                    "confidence": 0.0,
                    "queue_priority": "",
                    "fail_reasons": [f"Runner error: {e}"],
                    "generation": 3,
                    "style": style,
                    "market": market,
                    "runner_version": "v3_upgraded",
                })

    # Save results
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved upgraded results to {OUTPUT_FILE}")

    # =====================================================================
    # Comparison: v3 simplified vs v3 upgraded
    # =====================================================================
    print("\n" + "=" * 80)
    print("COMPARISON: V3 Simplified vs V3 Upgraded")
    print("=" * 80)

    prev_results = []
    if os.path.exists(PREV_RESULTS_FILE):
        with open(PREV_RESULTS_FILE) as f:
            prev_results = json.load(f)

    # Build lookup: (strategy_id, market) -> result
    prev_lookup = {}
    for r in prev_results:
        key = (r["strategy_id"], r.get("market", "NQ"))
        prev_lookup[key] = r

    print(f"\n{'Strategy':15s} {'Market':5s} {'Old Conf':>10s} {'New Conf':>10s} {'Delta':>8s} {'Old Status':>12s} {'New Status':>12s} {'Queue':>10s}")
    print("-" * 90)

    immediate_hits = []
    for r in results:
        key = (r["strategy_id"], r["market"])
        prev = prev_lookup.get(key, {})
        old_conf = prev.get("confidence", 0)
        new_conf = r.get("confidence", 0)
        delta = new_conf - old_conf

        marker = ""
        if new_conf >= 0.7:
            marker = " ⚡ IMMEDIATE"
            immediate_hits.append(r)
        elif new_conf >= 0.65:
            marker = " 🔥 NEAR"

        print(f"{r['strategy_id']:15s} {r['market']:5s} {old_conf:10.3f} {new_conf:10.3f} {delta:+8.3f} {prev.get('status', 'N/A'):>12s} {r['status']:>12s} {r.get('queue_priority', ''):>10s}{marker}")

    # =====================================================================
    # Top 10 by confidence
    # =====================================================================
    print("\n" + "=" * 80)
    print("TOP 10 STRATEGIES BY CONFIDENCE (V3 Upgraded)")
    print("=" * 80)

    sorted_results = sorted(results, key=lambda x: x.get("confidence", 0), reverse=True)
    print(f"\n{'Rank':>4s} {'Strategy':15s} {'Market':5s} {'Conf':>8s} {'Status':>8s} {'PnL':>12s} {'WinRate':>8s} {'MaxDD':>8s} {'Sharpe':>8s} {'Queue':>10s}")
    print("-" * 100)
    for i, r in enumerate(sorted_results[:10], 1):
        m = r.get("metrics", {})
        print(f"{i:4d} {r['strategy_id']:15s} {r['market']:5s} {r.get('confidence', 0):8.3f} {r['status']:>8s} ${m.get('total_pnl', 0):>10.2f} {m.get('win_rate', 0):8.1%} {m.get('max_drawdown', 0):8.1%} {m.get('sharpe_ratio', 0):8.2f} {r.get('queue_priority', ''):>10s}")

    # =====================================================================
    # IMMEDIATE queue hits
    # =====================================================================
    print("\n" + "=" * 80)
    if immediate_hits:
        print(f"🚨 {len(immediate_hits)} IMMEDIATE QUEUE HITS (confidence > 0.700)!")
        print("=" * 80)
        for r in immediate_hits:
            m = r.get("metrics", {})
            print(f"  ⚡ {r['strategy_id']} on {r['market']}: conf={r['confidence']:.3f}")
            print(f"     PnL=${m.get('total_pnl', 0):.2f} | WR={m.get('win_rate', 0):.1%} | DD={m.get('max_drawdown', 0):.1%} | Sharpe={m.get('sharpe_ratio', 0):.2f}")
            print(f"     Trades={m.get('trade_count', 0)} | Return={m.get('total_return_pct', 0):.2f}%")
        print("\n→ These should be run through full Darwin backtest on 16 years of data!")
    else:
        print("No IMMEDIATE queue hits (confidence > 0.700).")
        print("=" * 80)

        # Show near-misses
        near_misses = [r for r in sorted_results if 0.65 <= r.get("confidence", 0) < 0.7]
        if near_misses:
            print(f"\n🔥 {len(near_misses)} NEAR-MISSES (confidence 0.650-0.699):")
            for r in near_misses:
                m = r.get("metrics", {})
                print(f"  🔥 {r['strategy_id']} on {r['market']}: conf={r['confidence']:.3f} (need +{0.7 - r['confidence']:.3f})")

    # =====================================================================
    # Update combined results file
    # =====================================================================
    combined = []
    if os.path.exists(COMBINED_FILE):
        with open(COMBINED_FILE) as f:
            combined = json.load(f)

    # Remove any existing v3_upgraded entries
    combined = [r for r in combined if r.get("runner_version") != "v3_upgraded"]

    # Add new results
    combined.extend(results)

    with open(COMBINED_FILE, "w") as f:
        json.dump(combined, f, indent=2)
    print(f"\nUpdated combined results file: {COMBINED_FILE}")
    print(f"Total entries in combined file: {len(combined)}")

    # Summary stats
    pass_count = sum(1 for r in results if r["status"] == "PASS")
    fail_count = sum(1 for r in results if r["status"] == "FAIL")
    avg_conf = sum(r.get("confidence", 0) for r in results) / max(len(results), 1)
    print(f"\nSummary: {pass_count} PASS, {fail_count} FAIL, avg confidence={avg_conf:.3f}")


if __name__ == "__main__":
    main()

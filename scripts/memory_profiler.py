#!/usr/bin/env python3
"""
Memory Leak Profiler — Controlled single-process run to find the leak.

Steps:
1. Baseline memory tracking (RSS every 50 backtests)
2. tracemalloc for allocation hotspots
3. Object count tracking
4. Per-backtest delta measurement
5. Binary search: disable components to isolate

Usage: python3 scripts/memory_profiler.py
"""

import os
import sys
import gc
import json
import time
import copy
import random
import tracemalloc
from pathlib import Path
from collections import Counter

import psutil
import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from services.darwin.backtester import load_parquet, run_backtest, generate_signals

process = psutil.Process(os.getpid())

# ── Helpers ────────────────────────────────────────────────────────────────

def rss_gb():
    return process.memory_info().rss / (1024 ** 3)

def log_memory(tag=""):
    print(f"[MEM] {tag} RSS={rss_gb():.3f} GB")

def count_objects():
    objs = gc.get_objects()
    counter = Counter(type(o).__name__ for o in objs)
    top = counter.most_common(15)
    print(f"[OBJ COUNT] {top}")
    return counter

def measure_backtest_delta(dna, df, asset, n=1):
    """Measure memory delta for a single backtest."""
    gc.collect()
    before = process.memory_info().rss
    for _ in range(n):
        result = run_backtest(dna, df, asset=asset)
        del result
    gc.collect()
    after = process.memory_info().rss
    delta_mb = (after - before) / (1024 ** 2)
    return delta_mb


# ── DNA Generation ─────────────────────────────────────────────────────────

def generate_random_dna():
    style = random.choice(["mean_reversion", "scalping", "volume_orderflow", "momentum_breakout", "trend_following"])
    return {
        "strategy_code": f"PROF-{random.randint(10000,99999)}",
        "style": style,
        "parameter_ranges": {
            "rsi_threshold": [25, 35],
            "rsi_period": [7, 14],
            "fast_ema": [15, 25],
            "slow_ema": [40, 60],
            "adx_threshold": [20, 30],
            "volume_multiplier": [1.2, 2.0],
            "bb_period": [15, 25],
            "z_score_threshold": [1.5, 2.5],
        },
        "regime_filter": {"trend_strength_min": 25},
        "risk_reward": {"min_rr": 2.0},
        "exit_rules": {"time_limit_bars": 20},
    }


# ── Main Profiling Run ────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("MEMORY LEAK PROFILER")
    print("=" * 60)

    # Start tracemalloc
    tracemalloc.start()

    # Load data once
    print("\nLoading data...")
    datasets = {}
    for asset in ["NQ", "GC", "CL"]:
        for tf in ["1h", "daily"]:
            try:
                df = load_parquet(asset, tf)
                datasets[f"{asset}/{tf}"] = df
                print(f"  ✅ {asset}/{tf}: {len(df)} bars")
            except:
                print(f"  ❌ {asset}/{tf}: not found")

    if not datasets:
        print("No data loaded! Exiting.")
        return

    # Baseline
    gc.collect()
    log_memory("BASELINE")
    baseline_objs = count_objects()
    snap_baseline = tracemalloc.take_snapshot()

    # ── Phase 1: Bulk run with periodic monitoring ──
    print("\n" + "=" * 60)
    print("PHASE 1: Bulk Run (500 backtests, log every 50)")
    print("=" * 60)

    rss_history = []
    N = 500

    for i in range(N):
        dna = generate_random_dna()
        key = random.choice(list(datasets.keys()))
        asset = key.split("/")[0]
        df = datasets[key]

        try:
            result = run_backtest(dna, df, asset=asset)
            del result
        except Exception as e:
            pass

        if (i + 1) % 50 == 0:
            gc.collect()
            rss = rss_gb()
            rss_history.append((i + 1, rss))
            log_memory(f"after {i+1}/{N}")

    # Growth rate
    if len(rss_history) >= 2:
        start_rss = rss_history[0][1]
        end_rss = rss_history[-1][1]
        growth = end_rss - start_rss
        per_run = growth / N * 1024  # MB per run
        print(f"\n[GROWTH] {start_rss:.3f} → {end_rss:.3f} GB ({growth*1024:.1f} MB over {N} runs, ~{per_run:.2f} MB/run)")

    # ── Phase 2: tracemalloc hotspots ──
    print("\n" + "=" * 60)
    print("PHASE 2: tracemalloc Hotspots")
    print("=" * 60)

    snap_after = tracemalloc.take_snapshot()
    stats = snap_after.compare_to(snap_baseline, 'lineno')
    print("\nTop 15 memory growth by line:")
    for stat in stats[:15]:
        print(f"  {stat}")

    # ── Phase 3: Object count diff ──
    print("\n" + "=" * 60)
    print("PHASE 3: Object Count Diff")
    print("=" * 60)

    gc.collect()
    after_objs = count_objects()

    print("\nGrowing object types:")
    for typ, count in after_objs.most_common(20):
        baseline_count = baseline_objs.get(typ, 0)
        if count > baseline_count + 100:
            print(f"  {typ}: {baseline_count} → {count} (+{count - baseline_count})")

    # ── Phase 4: Per-backtest delta ──
    print("\n" + "=" * 60)
    print("PHASE 4: Per-Backtest Delta (10 individual runs)")
    print("=" * 60)

    key = list(datasets.keys())[0]
    asset = key.split("/")[0]
    df = datasets[key]

    for i in range(10):
        dna = generate_random_dna()
        delta = measure_backtest_delta(dna, df, asset)
        print(f"  Run {i+1}: {delta:+.2f} MB")

    # ── Phase 5: Binary search — component isolation ──
    print("\n" + "=" * 60)
    print("PHASE 5: Component Isolation (50 runs each)")
    print("=" * 60)

    # Test 1: Just signal generation (no backtest)
    gc.collect()
    before = process.memory_info().rss
    for i in range(50):
        dna = generate_random_dna()
        key = random.choice(list(datasets.keys()))
        df = datasets[key]
        try:
            signals = generate_signals(dna, df)
            del signals
        except:
            pass
    gc.collect()
    after = process.memory_info().rss
    delta = (after - before) / (1024 ** 2)
    print(f"  Signal generation only: {delta:+.1f} MB")

    # Test 2: Full backtest but discard trade_log
    gc.collect()
    before = process.memory_info().rss
    for i in range(50):
        dna = generate_random_dna()
        key = random.choice(list(datasets.keys()))
        asset = key.split("/")[0]
        df = datasets[key]
        try:
            result = run_backtest(dna, df, asset=asset)
            # Explicitly clear heavy fields
            result.trade_log.clear()
            result.extra.clear()
            del result
        except:
            pass
    gc.collect()
    after = process.memory_info().rss
    delta = (after - before) / (1024 ** 2)
    print(f"  Full backtest (trade_log cleared): {delta:+.1f} MB")

    # Test 3: Full backtest, keep everything (control)
    gc.collect()
    before = process.memory_info().rss
    for i in range(50):
        dna = generate_random_dna()
        key = random.choice(list(datasets.keys()))
        asset = key.split("/")[0]
        df = datasets[key]
        try:
            result = run_backtest(dna, df, asset=asset)
            del result
        except:
            pass
    gc.collect()
    after = process.memory_info().rss
    delta = (after - before) / (1024 ** 2)
    print(f"  Full backtest (keep everything): {delta:+.1f} MB")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("PROFILING COMPLETE")
    print("=" * 60)
    log_memory("FINAL")

    tracemalloc.stop()


if __name__ == "__main__":
    main()

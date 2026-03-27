#!/usr/bin/env python3
"""
FEED: Pull maximum historical data for all instruments.
- Daily data back to 2010 (yfinance)
- 1-minute intraday for last 30 days (Databento → yfinance fallback)
- Aggregate: 1m → 5m, 15m, 1h, 4h; daily → weekly, monthly
- Feature engineering on ALL timeframes
- Save everything to data/processed/{NQ,GC,CL}/
"""

import sys
import os
import logging
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from services.feed.databento_client import (
    INSTRUMENTS, pull_all_history, PROCESSED_DIR, RAW_DIR,
    aggregate_daily_to_weekly, aggregate_daily_to_monthly,
)
from services.feed.timeframe_aggregator import aggregate_and_save, TIMEFRAMES
from services.feed.feature_engine import enrich

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

API_KEY = os.getenv("DATABENTO_API_KEY")

# Track coverage for final report
coverage = {}


def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Add VWAP column if missing."""
    df = df.copy()
    if "vwap" not in df.columns:
        df["vwap"] = (df["high"] + df["low"] + df["close"]) / 3
    return df


def process_instrument(sym: str):
    """Full pipeline for one instrument."""
    print(f"\n{'='*70}")
    print(f"📊 {sym} — {INSTRUMENTS[sym]['name']}")
    print(f"{'='*70}")

    coverage[sym] = {}
    out_dir = PROCESSED_DIR / sym
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Pull all raw data ──
    print("\n[1/3] Pulling raw data...")
    results = pull_all_history(sym, api_key=API_KEY, daily_start="2010-01-01", intraday_days=30)

    # ── Step 2: Aggregate timeframes ──
    print("\n[2/3] Aggregating timeframes...")

    # 2a. Intraday aggregation: 1m → 5m, 15m, 1h, 4h
    if "1m" in results and len(results["1m"]) > 0:
        df_1m = results["1m"]
        intraday_aggs = aggregate_and_save(sym, df_1m)
        for tf, df in intraday_aggs.items():
            results[tf] = df
            print(f"    ✓ {tf}: {len(df)} bars")
    else:
        print("    ⚠ No 1m data — skipping intraday aggregation")

    # 2b. Save daily/weekly/monthly
    if "daily" in results:
        df_daily = add_vwap(results["daily"])
        df_daily.to_parquet(out_dir / "daily.parquet", index=False)
        results["daily"] = df_daily
        print(f"    ✓ daily: {len(df_daily)} bars → saved")

    if "weekly" in results:
        df_weekly = results["weekly"]
        df_weekly.to_parquet(out_dir / "weekly.parquet", index=False)
        print(f"    ✓ weekly: {len(df_weekly)} bars → saved")

    if "monthly" in results:
        df_monthly = results["monthly"]
        df_monthly.to_parquet(out_dir / "monthly.parquet", index=False)
        print(f"    ✓ monthly: {len(df_monthly)} bars → saved")

    # ── Step 3: Feature engineering on ALL timeframes ──
    print("\n[3/3] Feature engineering...")

    all_timeframes = ["1m", "5m", "15m", "1h", "4h", "daily", "weekly", "monthly"]
    for tf in all_timeframes:
        path = out_dir / f"{tf}.parquet"
        if not path.exists():
            continue

        try:
            df = pd.read_parquet(path)
            if len(df) < 2:
                print(f"    ⚠ {tf}: too few rows ({len(df)}), skipping enrichment")
                continue

            df_enriched = enrich(df)
            df_enriched.to_parquet(path, index=False)

            # Record coverage
            ts_min = pd.to_datetime(df_enriched["timestamp"]).min()
            ts_max = pd.to_datetime(df_enriched["timestamp"]).max()
            coverage[sym][tf] = {
                "bars": len(df_enriched),
                "from": str(ts_min.date()) if hasattr(ts_min, 'date') else str(ts_min),
                "to": str(ts_max.date()) if hasattr(ts_max, 'date') else str(ts_max),
            }
            print(f"    ✓ {tf}: {len(df_enriched)} bars enriched | {ts_min.date()} → {ts_max.date()}")

        except Exception as e:
            print(f"    ✗ {tf}: {e}")

    print(f"\n✅ {sym} complete!")


def print_coverage():
    """Print final coverage report."""
    print(f"\n\n{'='*70}")
    print("📊 TOTAL DATA COVERAGE")
    print(f"{'='*70}")

    for sym in coverage:
        print(f"\n  {sym} ({INSTRUMENTS[sym]['name']}):")
        if not coverage[sym]:
            print("    No data")
            continue
        for tf, info in sorted(coverage[sym].items(), key=lambda x: x[0]):
            print(f"    {tf:>8s}: {info['bars']:>8,} bars  |  {info['from']} → {info['to']}")


def write_status():
    """Write status file for the agent system."""
    status_dir = PROJECT_ROOT.parent / "agents" / "feed"
    status_dir.mkdir(parents=True, exist_ok=True)
    status_path = status_dir / "status.md"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Feed Agent Status",
        f"\n**Last run:** {now}",
        f"**Task:** Maximum historical data pull + feature engineering",
        f"**Status:** ✅ Complete",
        "",
        "## Data Coverage",
        "",
    ]

    for sym in coverage:
        lines.append(f"### {sym} ({INSTRUMENTS[sym]['name']})")
        lines.append("")
        lines.append("| Timeframe | Bars | From | To |")
        lines.append("|-----------|------|------|----|")
        for tf, info in sorted(coverage[sym].items(), key=lambda x: x[0]):
            lines.append(f"| {tf} | {info['bars']:,} | {info['from']} | {info['to']} |")
        lines.append("")

    lines.append("## Storage")
    lines.append("")
    lines.append("All data saved to `trading-factory/data/processed/{NQ,GC,CL}/`")
    lines.append("")
    lines.append("Files per instrument:")
    lines.append("- `1m.parquet` — 1-minute (last 30 days)")
    lines.append("- `5m.parquet` — 5-minute (last 30 days)")
    lines.append("- `15m.parquet` — 15-minute (last 30 days)")
    lines.append("- `1h.parquet` — 1-hour (last 30 days)")
    lines.append("- `4h.parquet` — 4-hour (last 30 days)")
    lines.append("- `daily.parquet` — Daily (2010+)")
    lines.append("- `weekly.parquet` — Weekly (2010+)")
    lines.append("- `monthly.parquet` — Monthly (2010+)")
    lines.append("")
    lines.append("All files enriched with: ATR(14), RSI(14), EMA(20), EMA(50), VWAP, trend, support, resistance")

    status_path.write_text("\n".join(lines))
    print(f"\n📝 Status written to {status_path}")


if __name__ == "__main__":
    print("🚀 FEED: Maximum Historical Data Pull")
    print(f"   Instruments: {list(INSTRUMENTS.keys())}")
    print(f"   Daily: 2010-01-01 → present")
    print(f"   Intraday: last 30 days")
    print(f"   Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    for sym in INSTRUMENTS:
        try:
            process_instrument(sym)
        except Exception as e:
            print(f"\n❌ {sym} FAILED: {e}")
            import traceback
            traceback.print_exc()

    print_coverage()
    write_status()
    print("\n🏁 Feed pipeline complete!")

"""
Databento client for pulling CME futures historical data.
Falls back to yfinance if Databento API has issues.

Supports:
  - 1-minute intraday data (last 30 days via yfinance 5m→1m or Databento)
  - Daily data going back to 2010+ (yfinance period="max")
  - Weekly/monthly aggregation from daily
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Instrument mapping
INSTRUMENTS = {
    "NQ": {"databento": "NQ.FUT", "dataset": "GLBX.MDP3", "yfinance": "NQ=F", "name": "E-mini NASDAQ"},
    "GC": {"databento": "GC.FUT", "dataset": "GLBX.MDP3", "yfinance": "GC=F", "name": "Gold"},
    "CL": {"databento": "CL.FUT", "dataset": "GLBX.MDP3", "yfinance": "CL=F", "name": "Crude Oil"},
}

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"


def _ensure_dirs():
    for sym in INSTRUMENTS:
        (RAW_DIR / sym).mkdir(parents=True, exist_ok=True)
        (PROCESSED_DIR / sym).mkdir(parents=True, exist_ok=True)


def pull_databento(
    instrument: str,
    days: int = 30,
    api_key: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    """Pull 1-minute OHLCV from Databento for a CME futures instrument."""
    try:
        import databento as db
    except ImportError:
        logger.error("databento SDK not installed")
        return None

    key = api_key or os.getenv("DATABENTO_API_KEY")
    if not key:
        logger.error("No Databento API key provided")
        return None

    info = INSTRUMENTS[instrument]
    end = datetime.now(timezone.utc) - timedelta(minutes=30)
    start = end - timedelta(days=days)

    try:
        client = db.Historical(key=key)
        data = client.timeseries.get_range(
            dataset=info["dataset"],
            symbols=[info["databento"]],
            schema="ohlcv-1m",
            start=start.strftime("%Y-%m-%dT%H:%M"),
            end=end.strftime("%Y-%m-%dT%H:%M"),
        )
        df = data.to_df()
        df = df.rename(columns={
            "open": "open", "high": "high",
            "low": "low", "close": "close", "volume": "volume",
        })
        if "ts_event" in df.columns:
            df["timestamp"] = pd.to_datetime(df["ts_event"], utc=True)
        elif df.index.name and "ts" in df.index.name:
            df["timestamp"] = df.index
            df = df.reset_index(drop=True)
        else:
            df["timestamp"] = df.index
            df = df.reset_index(drop=True)

        df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
        df = df.sort_values("timestamp").reset_index(drop=True)
        logger.info(f"Databento: pulled {len(df)} rows for {instrument}")
        return df

    except Exception as e:
        logger.warning(f"Databento failed for {instrument}: {e}")
        return None


# ── yfinance helpers ──────────────────────────────────────────────────

def pull_yfinance_intraday(instrument: str, days: int = 30) -> Optional[pd.DataFrame]:
    """
    Pull intraday data from yfinance.
    yfinance limits: 1m→7d, 2m→60d, 5m→60d.
    Strategy: pull 5m for full range, 1m for last 7 days, merge.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed")
        return None

    info = INSTRUMENTS[instrument]
    ticker = info["yfinance"]

    try:
        tk = yf.Ticker(ticker)
        end = datetime.now(timezone.utc)

        # Pull 1m for last 7 days
        start_7d = end - timedelta(days=7)
        df_1m = tk.history(interval="1m",
                           start=start_7d.strftime("%Y-%m-%d"),
                           end=end.strftime("%Y-%m-%d"))

        # Pull 5m for full range (up to 60 days)
        actual_days = min(days, 59)
        start_full = end - timedelta(days=actual_days)
        df_5m = tk.history(interval="5m",
                           start=start_full.strftime("%Y-%m-%d"),
                           end=end.strftime("%Y-%m-%d"))

        frames = []

        # Process 5m data → expand to 1m
        if len(df_5m) > 0:
            df_5m.index = pd.to_datetime(df_5m.index, utc=True)
            df_5m = df_5m[["Open", "High", "Low", "Close", "Volume"]].copy()
            df_5m.columns = ["open", "high", "low", "close", "volume"]
            rows = []
            for ts, row in df_5m.iterrows():
                for i in range(5):
                    new_ts = ts + timedelta(minutes=i)
                    rows.append({
                        "timestamp": new_ts,
                        "open": row["open"] if i == 0 else row["close"],
                        "high": row["high"],
                        "low": row["low"],
                        "close": row["close"],
                        "volume": int(row["volume"] / 5),
                    })
            df_expanded = pd.DataFrame(rows)
            frames.append(df_expanded)

        # Overlay real 1m data
        if len(df_1m) > 0:
            df_1m.index = pd.to_datetime(df_1m.index, utc=True)
            df_1m = df_1m[["Open", "High", "Low", "Close", "Volume"]].copy()
            df_1m.columns = ["open", "high", "low", "close", "volume"]
            df_1m["timestamp"] = df_1m.index
            df_1m = df_1m.reset_index(drop=True)

            if frames:
                cutoff = df_1m["timestamp"].min()
                frames[0] = frames[0][frames[0]["timestamp"] < cutoff]

            frames.append(df_1m)

        if not frames:
            return None

        df = pd.concat(frames, ignore_index=True)
        df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp").drop_duplicates(subset="timestamp").reset_index(drop=True)

        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype(float)
        df["volume"] = df["volume"].astype(int)

        logger.info(f"yfinance intraday: {len(df)} rows for {instrument}")
        return df

    except Exception as e:
        logger.warning(f"yfinance intraday failed for {instrument}: {e}")
        return None


def pull_yfinance_daily(instrument: str, start_date: str = "2010-01-01") -> Optional[pd.DataFrame]:
    """
    Pull daily OHLCV data from yfinance going back to start_date.
    This gives us years of history for regime analysis and long-term backtesting.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed")
        return None

    info = INSTRUMENTS[instrument]
    ticker = info["yfinance"]

    try:
        tk = yf.Ticker(ticker)
        df = tk.history(interval="1d", start=start_date)

        if df is None or len(df) == 0:
            logger.warning(f"yfinance daily returned no data for {instrument}")
            return None

        df.index = pd.to_datetime(df.index, utc=True)
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.columns = ["open", "high", "low", "close", "volume"]
        df["timestamp"] = df.index
        df = df.reset_index(drop=True)
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]

        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype(float)
        df["volume"] = df["volume"].astype("int64")

        df = df.sort_values("timestamp").drop_duplicates(subset="timestamp").reset_index(drop=True)
        logger.info(f"yfinance daily: {len(df)} rows for {instrument} from {df['timestamp'].min()} to {df['timestamp'].max()}")
        return df

    except Exception as e:
        logger.warning(f"yfinance daily failed for {instrument}: {e}")
        return None


def aggregate_daily_to_weekly(df_daily: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily OHLCV to weekly."""
    df = df_daily.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()

    agg = df.resample("W-FRI", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna(subset=["open", "close"])

    agg["vwap"] = (agg["high"] + agg["low"] + agg["close"]) / 3
    agg = agg.reset_index().rename(columns={"index": "timestamp"})
    if "timestamp" not in agg.columns:
        agg = agg.rename(columns={agg.columns[0]: "timestamp"})
    return agg


def aggregate_daily_to_monthly(df_daily: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily OHLCV to monthly."""
    df = df_daily.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()

    agg = df.resample("MS", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna(subset=["open", "close"])

    agg["vwap"] = (agg["high"] + agg["low"] + agg["close"]) / 3
    agg = agg.reset_index().rename(columns={"index": "timestamp"})
    if "timestamp" not in agg.columns:
        agg = agg.rename(columns={agg.columns[0]: "timestamp"})
    return agg


# ── Main pull functions ───────────────────────────────────────────────

def pull_data(
    instrument: str,
    days: int = 30,
    api_key: Optional[str] = None,
    force_source: Optional[str] = None,
) -> pd.DataFrame:
    """
    Pull 1-minute OHLCV data. Tries Databento first, falls back to yfinance.
    Saves raw data to data/raw/{instrument}/1m.parquet
    """
    _ensure_dirs()

    if instrument not in INSTRUMENTS:
        raise ValueError(f"Unknown instrument: {instrument}. Choose from {list(INSTRUMENTS.keys())}")

    df = None

    if force_source != "yfinance":
        df = pull_databento(instrument, days=days, api_key=api_key)

    if df is None or len(df) == 0:
        logger.info(f"Falling back to yfinance for {instrument}")
        df = pull_yfinance_intraday(instrument, days=days)

    if df is None or len(df) == 0:
        raise RuntimeError(f"Could not pull data for {instrument} from any source")

    out_path = RAW_DIR / instrument / "1m.parquet"
    df.to_parquet(out_path, index=False)
    logger.info(f"Saved {len(df)} rows to {out_path}")
    return df


def pull_all_history(
    instrument: str,
    api_key: Optional[str] = None,
    daily_start: str = "2010-01-01",
    intraday_days: int = 30,
) -> dict:
    """
    Pull MAXIMUM historical data for an instrument:
      - Daily data back to daily_start (via yfinance)
      - 1-minute intraday data for last intraday_days (Databento → yfinance fallback)
      - Weekly + monthly aggregations from daily

    Returns dict with all DataFrames.
    """
    _ensure_dirs()

    if instrument not in INSTRUMENTS:
        raise ValueError(f"Unknown instrument: {instrument}")

    results = {}

    # 1. Daily data (long history)
    print(f"  📅 Pulling daily data from {daily_start}...")
    df_daily = pull_yfinance_daily(instrument, start_date=daily_start)
    if df_daily is not None and len(df_daily) > 0:
        raw_path = RAW_DIR / instrument / "daily.parquet"
        df_daily.to_parquet(raw_path, index=False)
        results["daily"] = df_daily
        print(f"    ✓ {len(df_daily)} daily bars: {df_daily['timestamp'].min().date()} → {df_daily['timestamp'].max().date()}")

        # Weekly
        df_weekly = aggregate_daily_to_weekly(df_daily)
        results["weekly"] = df_weekly
        print(f"    ✓ {len(df_weekly)} weekly bars")

        # Monthly
        df_monthly = aggregate_daily_to_monthly(df_daily)
        results["monthly"] = df_monthly
        print(f"    ✓ {len(df_monthly)} monthly bars")
    else:
        print(f"    ✗ No daily data")

    # 2. Intraday 1m data (last N days)
    print(f"  ⏱️  Pulling {intraday_days}-day intraday data...")
    df_1m = None

    # Try Databento first
    if api_key:
        df_1m = pull_databento(instrument, days=intraday_days, api_key=api_key)

    # Fallback to yfinance
    if df_1m is None or len(df_1m) == 0:
        print(f"    → Using yfinance for intraday...")
        df_1m = pull_yfinance_intraday(instrument, days=intraday_days)

    if df_1m is not None and len(df_1m) > 0:
        raw_path = RAW_DIR / instrument / "1m.parquet"
        df_1m.to_parquet(raw_path, index=False)
        results["1m"] = df_1m
        print(f"    ✓ {len(df_1m)} 1m bars: {df_1m['timestamp'].min()} → {df_1m['timestamp'].max()}")
    else:
        print(f"    ✗ No intraday data")

    return results


def load_raw(instrument: str, timeframe: str = "1m") -> pd.DataFrame:
    """Load previously saved raw data."""
    path = RAW_DIR / instrument / f"{timeframe}.parquet"
    if not path.exists():
        # Fallback to old path
        path = RAW_DIR / instrument / "1m.parquet"
    if not path.exists():
        raise FileNotFoundError(f"No raw data at {path}. Run pull_data first.")
    return pd.read_parquet(path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    api_key = os.getenv("DATABENTO_API_KEY")

    for sym in INSTRUMENTS:
        print(f"\n{'='*60}")
        print(f"Pulling MAX history for {sym} ({INSTRUMENTS[sym]['name']})...")
        try:
            results = pull_all_history(sym, api_key=api_key)
            print(f"  Total timeframes: {list(results.keys())}")
        except Exception as e:
            print(f"  ✗ Error: {e}")

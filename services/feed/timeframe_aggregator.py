"""
Aggregate 1-minute OHLCV data to higher timeframes (5m, 15m, 1h, 4h).
Computes OHLC, volume, and VWAP per candle.
"""

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"

TIMEFRAMES = {
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
}


def aggregate(df_1m: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Aggregate 1-minute OHLCV data to a higher timeframe.
    Adds VWAP column.
    """
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"Unknown timeframe: {timeframe}. Choose from {list(TIMEFRAMES.keys())}")

    freq = TIMEFRAMES[timeframe]
    df = df_1m.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()

    # Compute typical price * volume for VWAP
    df["tp_vol"] = ((df["high"] + df["low"] + df["close"]) / 3) * df["volume"]

    agg = df.resample(freq, label="left", closed="left").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "tp_vol": "sum",
    })

    # Drop rows where all OHLC are NaN (non-trading periods)
    agg = agg.dropna(subset=["open", "close"])

    # VWAP = sum(tp*vol) / sum(vol)
    agg["vwap"] = agg["tp_vol"] / agg["volume"].replace(0, float("nan"))
    agg["vwap"] = agg["vwap"].fillna(agg["close"])  # fallback to close if no volume
    agg = agg.drop(columns=["tp_vol"])

    agg = agg.reset_index()
    agg = agg.rename(columns={"index": "timestamp"})
    if "timestamp" not in agg.columns:
        agg = agg.rename(columns={agg.columns[0]: "timestamp"})

    return agg


def aggregate_and_save(
    instrument: str,
    df_1m: pd.DataFrame,
    timeframes: Optional[list] = None,
) -> dict[str, pd.DataFrame]:
    """
    Aggregate 1m data to multiple timeframes and save as parquet.
    Returns dict of {timeframe: DataFrame}.
    """
    if timeframes is None:
        timeframes = list(TIMEFRAMES.keys())

    out_dir = PROCESSED_DIR / instrument
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    for tf in timeframes:
        df_agg = aggregate(df_1m, tf)
        out_path = out_dir / f"{tf}.parquet"
        df_agg.to_parquet(out_path, index=False)
        results[tf] = df_agg
        logger.info(f"Saved {instrument}/{tf}: {len(df_agg)} candles → {out_path}")

    # Also save the 1m data in processed for completeness
    df_1m_copy = df_1m.copy()
    df_1m_copy["timestamp"] = pd.to_datetime(df_1m_copy["timestamp"], utc=True)
    df_1m_copy = df_1m_copy.sort_values("timestamp")
    # Add VWAP to 1m
    df_1m_copy["vwap"] = ((df_1m_copy["high"] + df_1m_copy["low"] + df_1m_copy["close"]) / 3)
    out_1m = out_dir / "1m.parquet"
    df_1m_copy.to_parquet(out_1m, index=False)
    results["1m"] = df_1m_copy

    return results


def load_timeframe(instrument: str, timeframe: str) -> pd.DataFrame:
    """Load a processed timeframe parquet file."""
    path = PROCESSED_DIR / instrument / f"{timeframe}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"No data at {path}. Run aggregation first.")
    return pd.read_parquet(path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from databento_client import load_raw

    for sym in ["NQ", "GC", "CL"]:
        try:
            df = load_raw(sym)
            print(f"\n{'='*50}")
            print(f"Aggregating {sym} ({len(df)} 1m bars)...")
            results = aggregate_and_save(sym, df)
            for tf, tf_df in results.items():
                print(f"  {tf}: {len(tf_df)} candles")
        except Exception as e:
            print(f"  ✗ {sym}: {e}")

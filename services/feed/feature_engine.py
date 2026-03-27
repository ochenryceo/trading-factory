"""
Feature engine: compute technical indicators on each timeframe.
ATR(14), RSI(14), EMA(20), EMA(50), VWAP, trend direction, support/resistance.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
ENRICHED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"  # same dir, enriched files


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    return tr.ewm(span=period, adjust=False).mean()


def compute_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def compute_trend(df: pd.DataFrame) -> pd.Series:
    """Trend direction based on EMA(20) vs EMA(50) cross."""
    ema20 = df["ema_20"]
    ema50 = df["ema_50"]

    conditions = [
        ema20 > ema50 * 1.001,  # small buffer to avoid whipsaw
        ema20 < ema50 * 0.999,
    ]
    choices = ["up", "down"]
    return pd.Series(np.select(conditions, choices, default="neutral"), index=df.index)


def compute_swing_levels(df: pd.DataFrame, lookback: int = 20) -> tuple[pd.Series, pd.Series]:
    """
    Support and resistance as rolling swing lows/highs.
    Support = lowest low in lookback. Resistance = highest high in lookback.
    """
    support = df["low"].rolling(window=lookback, min_periods=1).min()
    resistance = df["high"].rolling(window=lookback, min_periods=1).max()
    return support, resistance


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Add all technical features to a DataFrame with OHLCV + vwap columns."""
    df = df.copy()

    # Core indicators
    df["atr_14"] = compute_atr(df, 14)
    df["rsi_14"] = compute_rsi(df, 14)
    df["ema_20"] = compute_ema(df["close"], 20)
    df["ema_50"] = compute_ema(df["close"], 50)

    # VWAP should already exist from aggregator; if not, compute
    if "vwap" not in df.columns:
        df["vwap"] = (df["high"] + df["low"] + df["close"]) / 3

    # Trend
    df["trend"] = compute_trend(df)

    # Support / Resistance
    df["support"], df["resistance"] = compute_swing_levels(df)

    return df


def enrich_and_save(instrument: str, timeframes: list[str] = None) -> dict[str, pd.DataFrame]:
    """Load processed data, enrich with features, save back."""
    if timeframes is None:
        timeframes = ["1m", "5m", "15m", "1h", "4h"]

    results = {}
    for tf in timeframes:
        path = PROCESSED_DIR / instrument / f"{tf}.parquet"
        if not path.exists():
            logger.warning(f"No data for {instrument}/{tf}, skipping")
            continue

        df = pd.read_parquet(path)
        df_enriched = enrich(df)

        out_path = ENRICHED_DIR / instrument / f"{tf}.parquet"
        df_enriched.to_parquet(out_path, index=False)
        results[tf] = df_enriched
        logger.info(f"Enriched {instrument}/{tf}: {len(df_enriched)} rows, "
                     f"cols={list(df_enriched.columns)}")

    return results


def load_enriched(instrument: str, timeframe: str) -> pd.DataFrame:
    """Load enriched parquet file."""
    path = ENRICHED_DIR / instrument / f"{timeframe}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"No enriched data at {path}")
    return pd.read_parquet(path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    for sym in ["NQ", "GC", "CL"]:
        print(f"\n{'='*50}")
        print(f"Enriching {sym}...")
        try:
            results = enrich_and_save(sym)
            for tf, df in results.items():
                print(f"  {tf}: {len(df)} rows | "
                      f"RSI={df['rsi_14'].iloc[-1]:.1f} "
                      f"ATR={df['atr_14'].iloc[-1]:.2f} "
                      f"Trend={df['trend'].iloc[-1]}")
        except Exception as e:
            print(f"  ✗ {sym}: {e}")

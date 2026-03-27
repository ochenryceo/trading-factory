"""
MarketContext: combines all timeframes into one queryable state per instrument.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from .feature_engine import load_enriched

logger = logging.getLogger(__name__)

TIMEFRAMES = ["5m", "15m", "1h", "4h"]


def _latest_row_to_dict(df: pd.DataFrame) -> dict[str, Any]:
    """Extract the latest row's key features as a dict."""
    if len(df) == 0:
        return {}

    row = df.iloc[-1]
    return {
        "ohlc": {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        },
        "volume": int(row.get("volume", 0)),
        "vwap": float(row.get("vwap", row["close"])),
        "rsi": round(float(row.get("rsi_14", 50)), 2),
        "atr": round(float(row.get("atr_14", 0)), 4),
        "ema_20": round(float(row.get("ema_20", row["close"])), 4),
        "ema_50": round(float(row.get("ema_50", row["close"])), 4),
        "trend": str(row.get("trend", "neutral")),
        "support": round(float(row.get("support", row["low"])), 4),
        "resistance": round(float(row.get("resistance", row["high"])), 4),
        "timestamp": str(row.get("timestamp", "")),
    }


def build_context(instrument: str, timeframes: Optional[list[str]] = None) -> dict[str, Any]:
    """
    Build a MarketContext dict combining all timeframes for an instrument.
    """
    if timeframes is None:
        timeframes = TIMEFRAMES

    context: dict[str, Any] = {
        "instrument": instrument,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    for tf in timeframes:
        try:
            df = load_enriched(instrument, tf)
            context[tf] = _latest_row_to_dict(df)
        except FileNotFoundError:
            logger.warning(f"No enriched data for {instrument}/{tf}")
            context[tf] = {"error": "no data available"}
        except Exception as e:
            logger.error(f"Error building context for {instrument}/{tf}: {e}")
            context[tf] = {"error": str(e)}

    return context


def get_candles(instrument: str, timeframe: str, limit: int = 100) -> list[dict]:
    """Get recent candle data as list of dicts."""
    df = load_enriched(instrument, timeframe)
    df = df.tail(limit)

    # Convert timestamp to string for JSON serialization
    df = df.copy()
    df["timestamp"] = df["timestamp"].astype(str)

    return df.to_dict(orient="records")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import json

    for sym in ["NQ", "GC", "CL"]:
        print(f"\n{'='*60}")
        print(f"MarketContext for {sym}")
        print("=" * 60)
        ctx = build_context(sym)
        print(json.dumps(ctx, indent=2, default=str))

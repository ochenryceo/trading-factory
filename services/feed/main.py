"""
Feed Service — FastAPI application exposing market data endpoints.

Endpoints:
  GET /health                          — health check
  GET /data/{instrument}/{timeframe}   — candle data (with optional ?limit=N)
  GET /context/{instrument}            — full MarketContext across all timeframes
"""

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from .market_context import build_context, get_candles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Feed Service — Trading Factory",
    description="Market data foundation: OHLCV + technical indicators",
    version="1.0.0",
)

VALID_INSTRUMENTS = ["NQ", "GC", "CL"]
VALID_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]


@app.get("/health")
def health():
    return {"status": "ok", "service": "feed"}


@app.get("/data/{instrument}/{timeframe}")
def get_data(
    instrument: str,
    timeframe: str,
    limit: Optional[int] = Query(100, ge=1, le=10000),
):
    instrument = instrument.upper()
    if instrument not in VALID_INSTRUMENTS:
        raise HTTPException(400, f"Unknown instrument: {instrument}. Use: {VALID_INSTRUMENTS}")
    if timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(400, f"Unknown timeframe: {timeframe}. Use: {VALID_TIMEFRAMES}")

    try:
        candles = get_candles(instrument, timeframe, limit=limit)
        return {
            "instrument": instrument,
            "timeframe": timeframe,
            "count": len(candles),
            "data": candles,
        }
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        raise HTTPException(500, str(e))


@app.get("/context/{instrument}")
def get_context(instrument: str):
    instrument = instrument.upper()
    if instrument not in VALID_INSTRUMENTS:
        raise HTTPException(400, f"Unknown instrument: {instrument}. Use: {VALID_INSTRUMENTS}")

    try:
        ctx = build_context(instrument)
        return ctx
    except Exception as e:
        logger.error(f"Error building context: {e}")
        raise HTTPException(500, str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

"""
Pulse — News & Sentiment FastAPI Service
=========================================
Endpoints:
    GET /sentiment/{instrument}  — current sentiment + recent headlines
    GET /events                  — recent high-impact events with tags
    GET /health                  — service health check
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .sentiment_engine import (
    HeadlineScore,
    InstrumentSentiment,
    aggregate_sentiment,
    score_headline,
    get_search_queries,
    INSTRUMENT_QUERIES,
)
from .event_tagger import TaggedEvent, tag_events, filter_high_impact


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Pulse — Sentiment Intelligence",
    description="Real-time news sentiment scoring for futures instruments",
    version="0.1.0",
)

# In-memory cache (replaced on each fetch cycle)
_cache: dict[str, InstrumentSentiment] = {}
_events_cache: list[TaggedEvent] = []


# ---------------------------------------------------------------------------
# Internal helpers (search integration stub)
# ---------------------------------------------------------------------------

def _fetch_headlines_stub(instrument: str) -> list[HeadlineScore]:
    """
    Stub that returns cached data or empty list.
    In production, this integrates with Brave Search API or similar.
    The actual search is done via the sample_run.py script which
    populates the cache through the /ingest endpoint.
    """
    if instrument in _cache:
        return _cache[instrument].headlines
    return []


# ---------------------------------------------------------------------------
# Ingest endpoint (for the sample runner / external feeds)
# ---------------------------------------------------------------------------

class HeadlineIn(BaseModel):
    title: str
    url: str = ""
    snippet: str = ""


class IngestPayload(BaseModel):
    instrument: str
    headlines: list[HeadlineIn]


@app.post("/ingest")
async def ingest_headlines(payload: IngestPayload):
    """Ingest raw headlines, score them, and update cache."""
    instrument = payload.instrument.upper()
    scored = [
        score_headline(h.title, h.snippet, h.url)
        for h in payload.headlines
    ]
    sentiment = aggregate_sentiment(instrument, scored)
    _cache[instrument] = sentiment

    # Update events cache
    global _events_cache
    all_headlines = []
    for inst_sent in _cache.values():
        all_headlines.extend(inst_sent.headlines)
    _events_cache = tag_events(all_headlines)

    return {
        "status": "ok",
        "instrument": instrument,
        "headlines_ingested": len(scored),
        "score": sentiment.score,
        "label": sentiment.label,
    }


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@app.get("/sentiment/{instrument}")
async def get_sentiment(instrument: str):
    """Get current sentiment score and recent headlines for an instrument."""
    instrument = instrument.upper()
    if instrument not in _cache:
        raise HTTPException(
            status_code=404,
            detail=f"No sentiment data for {instrument}. "
                   f"Available: {list(_cache.keys()) or list(INSTRUMENT_QUERIES.keys())}",
        )

    return _cache[instrument].to_dict()


@app.get("/events")
async def get_events(
    min_priority: int = Query(1, ge=1, le=5, description="Minimum event priority"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=200),
):
    """Get recent high-impact events with tags."""
    filtered = filter_high_impact(
        _events_cache,
        min_priority=min_priority,
        min_confidence=min_confidence,
    )
    return {
        "count": len(filtered[:limit]),
        "events": [e.to_dict() for e in filtered[:limit]],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health")
async def health():
    """Service health check."""
    return {
        "status": "healthy",
        "service": "pulse",
        "version": "0.1.0",
        "instruments_loaded": list(_cache.keys()),
        "total_headlines": sum(s.headline_count for s in _cache.values()),
        "total_events": len(_events_cache),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

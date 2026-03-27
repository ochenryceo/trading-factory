"""
Pulse Event Tagger
==================
Classifies news headlines into event types and tags timeframe impact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

from .sentiment_engine import HeadlineScore


# ---------------------------------------------------------------------------
# Event type definitions
# ---------------------------------------------------------------------------

EVENT_TYPES = {
    "fed_decision": {
        "keywords": [
            "fed", "federal reserve", "fomc", "rate decision", "rate hike",
            "rate cut", "powell", "monetary policy", "quantitative",
            "taper", "hawkish", "dovish", "basis points", "fed funds",
        ],
        "impact_timeframe": "4h+",
        "impact_minutes_min": 240,
        "impact_minutes_max": None,
        "priority": 5,
    },
    "geopolitical": {
        "keywords": [
            "war", "sanctions", "tariff", "trade war", "conflict",
            "military", "geopolitical", "embargo", "nuclear", "nato",
            "opec", "invasion", "attack", "ceasefire", "treaty",
            "diplomacy", "tension", "crisis",
        ],
        "impact_timeframe": "4h+",
        "impact_minutes_min": 240,
        "impact_minutes_max": None,
        "priority": 4,
    },
    "macro_release": {
        "keywords": [
            "cpi", "ppi", "gdp", "nonfarm", "payrolls", "unemployment",
            "inflation", "jobs report", "retail sales", "ism",
            "manufacturing", "consumer confidence", "housing starts",
            "pce", "initial claims", "jobless", "economic data",
            "trade balance", "industrial production",
        ],
        "impact_timeframe": "1h-4h",
        "impact_minutes_min": 60,
        "impact_minutes_max": 240,
        "priority": 3,
    },
    "earnings": {
        "keywords": [
            "earnings", "revenue", "eps", "quarterly results", "profit",
            "guidance", "forecast", "beat estimates", "miss estimates",
            "earnings call", "q1", "q2", "q3", "q4", "fiscal",
            "annual report", "dividend",
        ],
        "impact_timeframe": "15m-1h",
        "impact_minutes_min": 15,
        "impact_minutes_max": 60,
        "priority": 2,
    },
    "breaking_news": {
        "keywords": [
            "breaking", "just in", "alert", "flash", "developing",
            "urgent", "exclusive", "update",
        ],
        "impact_timeframe": "5m-15m",
        "impact_minutes_min": 5,
        "impact_minutes_max": 15,
        "priority": 1,
    },
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TaggedEvent:
    """A headline classified with event type and impact metadata."""
    title: str
    url: str
    event_type: str
    impact_timeframe: str
    impact_minutes_min: int
    impact_minutes_max: Optional[int]
    sentiment_score: float
    confidence: float
    priority: int
    matched_keywords: list[str]
    timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", text.lower())


def classify_event(headline: HeadlineScore) -> TaggedEvent:
    """
    Classify a scored headline into an event type.
    Picks the highest-priority matching type, or defaults to breaking_news.
    """
    combined = _normalize(f"{headline.title} {headline.snippet}")

    best_type: Optional[str] = None
    best_priority = -1
    best_matches: list[str] = []

    for etype, config in EVENT_TYPES.items():
        matches = [kw for kw in config["keywords"] if kw in combined]
        if matches and config["priority"] > best_priority:
            best_type = etype
            best_priority = config["priority"]
            best_matches = matches

    # Default to breaking_news if no specific type matched
    if best_type is None:
        best_type = "breaking_news"
        best_priority = EVENT_TYPES["breaking_news"]["priority"]
        best_matches = []

    config = EVENT_TYPES[best_type]

    return TaggedEvent(
        title=headline.title,
        url=headline.url,
        event_type=best_type,
        impact_timeframe=config["impact_timeframe"],
        impact_minutes_min=config["impact_minutes_min"],
        impact_minutes_max=config["impact_minutes_max"],
        sentiment_score=headline.score,
        confidence=headline.confidence,
        priority=best_priority,
        matched_keywords=best_matches,
        timestamp=headline.timestamp,
    )


def tag_events(headlines: list[HeadlineScore]) -> list[TaggedEvent]:
    """Classify and tag a batch of headlines. Returns sorted by priority desc."""
    events = [classify_event(h) for h in headlines]
    events.sort(key=lambda e: e.priority, reverse=True)
    return events


def filter_high_impact(
    events: list[TaggedEvent],
    min_priority: int = 2,
    min_confidence: float = 0.2,
) -> list[TaggedEvent]:
    """Filter to only high-impact events."""
    return [
        e for e in events
        if e.priority >= min_priority and e.confidence >= min_confidence
    ]

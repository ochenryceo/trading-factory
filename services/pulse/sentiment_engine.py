"""
Pulse Sentiment Engine
======================
Rule-based sentiment scoring for futures instruments.
Pulls headlines via web search and scores them using keyword analysis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Keyword dictionaries
# ---------------------------------------------------------------------------

BULLISH_KEYWORDS: list[str] = [
    "rally", "surge", "breakout", "bullish", "buy", "growth",
    "record high", "beat expectations", "soar", "gain", "climb",
    "upbeat", "optimistic", "rebound", "outperform", "upgrade",
    "boom", "all-time high", "strong", "positive", "rise",
    "recover", "accelerate", "expand", "beat", "jump", "spike",
    "momentum", "tailwind", "support",
]

BEARISH_KEYWORDS: list[str] = [
    "crash", "plunge", "bearish", "sell", "recession", "miss",
    "decline", "downgrade", "risk", "slump", "drop", "fall",
    "tumble", "weak", "negative", "fear", "concern", "warning",
    "cut", "layoff", "contraction", "slowdown", "headwind",
    "pullback", "correction", "dump", "collapse", "tank",
    "pressure", "threat", "loss", "drag", "deficit",
]

# Instrument → search queries
INSTRUMENT_QUERIES: dict[str, list[str]] = {
    "NQ": ["NASDAQ futures", "NQ futures market", "NASDAQ 100 today"],
    "GC": ["gold futures", "gold price today", "COMEX gold"],
    "CL": ["crude oil futures", "WTI oil price today", "oil market news"],
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class HeadlineScore:
    """Single scored headline."""
    title: str
    url: str
    snippet: str
    score: float          # -1.0 to 1.0
    confidence: float     # 0.0 to 1.0
    bullish_hits: list[str] = field(default_factory=list)
    bearish_hits: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class InstrumentSentiment:
    """Aggregated sentiment for an instrument."""
    instrument: str
    score: float                    # -1.0 to 1.0
    confidence: float               # 0.0 to 1.0
    label: str                      # "bullish" | "bearish" | "neutral"
    headline_count: int
    headlines: list[HeadlineScore]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "instrument": self.instrument,
            "score": round(self.score, 4),
            "confidence": round(self.confidence, 4),
            "label": self.label,
            "headline_count": self.headline_count,
            "headlines": [h.to_dict() for h in self.headlines],
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Scoring logic
# ---------------------------------------------------------------------------

def _normalize_text(text: str) -> str:
    """Lowercase and strip punctuation for matching."""
    return re.sub(r"[^a-z0-9\s]", " ", text.lower())


def score_headline(title: str, snippet: str = "", url: str = "") -> HeadlineScore:
    """
    Score a single headline + snippet using keyword analysis.

    Score = (bullish_count - bearish_count) / total_keyword_hits
    Confidence = total_keyword_hits / max(len(words), 1), capped at 1.0
    """
    combined = _normalize_text(f"{title} {snippet}")
    words = combined.split()
    word_count = max(len(words), 1)

    bullish_hits: list[str] = []
    bearish_hits: list[str] = []

    for kw in BULLISH_KEYWORDS:
        count = combined.count(kw)
        if count > 0:
            bullish_hits.extend([kw] * count)

    for kw in BEARISH_KEYWORDS:
        count = combined.count(kw)
        if count > 0:
            bearish_hits.extend([kw] * count)

    total_hits = len(bullish_hits) + len(bearish_hits)

    if total_hits == 0:
        score = 0.0
        confidence = 0.1  # low confidence when no keywords found
    else:
        raw = (len(bullish_hits) - len(bearish_hits)) / total_hits
        score = max(-1.0, min(1.0, raw))
        # Confidence scales with keyword density, capped at 1.0
        confidence = min(1.0, total_hits / max(word_count * 0.1, 1))

    return HeadlineScore(
        title=title,
        url=url,
        snippet=snippet,
        score=score,
        confidence=round(confidence, 4),
        bullish_hits=list(set(bullish_hits)),
        bearish_hits=list(set(bearish_hits)),
    )


def aggregate_sentiment(
    instrument: str,
    headlines: list[HeadlineScore],
) -> InstrumentSentiment:
    """
    Aggregate individual headline scores into an instrument-level sentiment.
    Weighted average by confidence.
    """
    if not headlines:
        return InstrumentSentiment(
            instrument=instrument,
            score=0.0,
            confidence=0.0,
            label="neutral",
            headline_count=0,
            headlines=[],
        )

    total_weight = sum(h.confidence for h in headlines)
    if total_weight == 0:
        avg_score = 0.0
        avg_conf = 0.0
    else:
        avg_score = sum(h.score * h.confidence for h in headlines) / total_weight
        avg_conf = total_weight / len(headlines)

    avg_score = max(-1.0, min(1.0, avg_score))
    avg_conf = min(1.0, avg_conf)

    if avg_score > 0.15:
        label = "bullish"
    elif avg_score < -0.15:
        label = "bearish"
    else:
        label = "neutral"

    return InstrumentSentiment(
        instrument=instrument,
        score=avg_score,
        confidence=avg_conf,
        label=label,
        headline_count=len(headlines),
        headlines=headlines,
    )


def get_search_queries(instrument: str) -> list[str]:
    """Return search queries for a given instrument code."""
    return INSTRUMENT_QUERIES.get(
        instrument.upper(),
        [f"{instrument} futures market news"],
    )

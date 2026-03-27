#!/usr/bin/env python3
"""
Pulse Sample Run
================
Scores real headlines fetched from web search and produces sentiment_sample.json.
Can also be used as a template for integrating with live search APIs.
"""

import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from services.pulse.sentiment_engine import score_headline, aggregate_sentiment
from services.pulse.event_tagger import tag_events, filter_high_impact


# ---------------------------------------------------------------------------
# Real headlines from web search (2026-03-22)
# ---------------------------------------------------------------------------

RAW_HEADLINES = {
    "NQ": [
        {
            "title": "Stock market today: Dow, S&P 500, Nasdaq jump to start week, oil rises with US and Iran targeting energy infrastructure",
            "url": "https://finance.yahoo.com/news/live/stock-market-today-dow-sp-500-nasdaq-futures-climb",
            "snippet": "The tech-heavy Nasdaq Composite led the way up with a gain of 1.1% to start Monday's session, while the Dow Jones and S&P 500 picked up 0.8% and 0.9%.",
        },
        {
            "title": "NASDAQ analysis today: Nasdaq futures show bullish repair as buyers defend key support",
            "url": "https://investinglive.com/news/nasdaq-analysis-today",
            "snippet": "NQ analysis: order flow points to a bullish repair, but not a runaway breakout. Nasdaq price prediction today leans bullish, with a market bias score of +5.8 as order flow improves.",
        },
        {
            "title": "Stock market today: Dow, S&P 500, Nasdaq futures retreat as oil swings amid Iran war jitters",
            "url": "https://finance.yahoo.com/news/live/stock-market-today-nasdaq-retreat",
            "snippet": "Brent futures traded near $105 a barrel after swinging between gains and losses. The major US stock gauges declined for the fourth straight week.",
        },
        {
            "title": "Stock market today: Dow, S&P 500, Nasdaq futures drop after stocks bounce back amid 3-week losing streak",
            "url": "https://finance.yahoo.com/news/live/stock-market-today-nasdaq-drop",
            "snippet": "Futures linked to the Dow Jones slid about 0.6%. Contracts tied to the S&P 500 and Nasdaq 100 also fell roughly 0.6%.",
        },
        {
            "title": "Stock market today: Dow, S&P 500, Nasdaq futures fall, oil surges after Iran, inflation worries sink stocks",
            "url": "https://finance.yahoo.com/news/live/stock-market-today-nasdaq-fall-iran",
            "snippet": "Futures tied to the Dow Jones slipped about 0.3%. Contracts on the S&P 500 and Nasdaq 100 also declined roughly 0.2% and 0.3%, respectively.",
        },
        {
            "title": "Nasdaq 100 (NQ) Technical Analysis: sitting just above key support zone near 24,500",
            "url": "https://blog.oneuptrader.com/analysis/nasdaq-100-nq-technical-analysis",
            "snippet": "Nasdaq futures are currently in a difficult position, sitting just above a key support zone while remaining below the 50 and 200-day moving averages. Consolidating at this period of uncertainty.",
        },
        {
            "title": "Dow tumbles more than 750 points to new correction territory",
            "url": "https://www.cnbc.com/2026/03/16/stock-market-today-live-updates.html",
            "snippet": "Futures tied to the S&P 500 and Nasdaq-100 each lost more than 0.1%. Dow tumbles more than 750 points to near correction.",
        },
        {
            "title": "FOMC Wednesday: Federal Reserve rate decision is the ultimate wildcard for Nasdaq",
            "url": "https://investinglive.com/news/fomc-wednesday",
            "snippet": "Today is FOMC Wednesday, and the Federal Reserve is the ultimate wildcard. While the market expects rates to stay steady, the danger lies in the Dot Plot and Chair Powell's tone.",
        },
    ],
    "GC": [
        {
            "title": "US Gold Price Today Crashes $100+ to $4,494 per Ounce, COMEX Futures Slide Amid Heavy Selling",
            "url": "https://swikblog.com/us-gold-price-today-crashes-100-4494",
            "snippet": "US gold price today crashes over $100 to $4,494 per ounce as COMEX futures slide amid heavy selling pressure.",
        },
        {
            "title": "US Gold Price Today Crashes to $4,574 per Ounce, COMEX Futures Sink Over 2%",
            "url": "https://swikblog.com/us-gold-price-today-crashes-4574",
            "snippet": "US gold price today crashes to $4,574 per ounce as COMEX futures sink over 2%, breaking $4,600 support and hitting intraday low near $4,490.",
        },
        {
            "title": "US Gold Price Today Falls Near $4,990 Per Ounce, COMEX Futures Slip 0.3% Ahead of Fed Cues",
            "url": "https://swikblog.com/us-gold-price-today-4990-fed-cues",
            "snippet": "US gold price today falls near $4,990 per ounce as COMEX futures slip 0.3% ahead of Fed cues.",
        },
        {
            "title": "US Gold Price Today Plunges $200 to $4,688 Per Ounce, COMEX Futures Crash Below $4,900",
            "url": "https://swikblog.com/us-gold-price-today-4688-crash",
            "snippet": "Gold price today plunges $200 to $4,688 per ounce as COMEX gold futures crash below $4,900.",
        },
        {
            "title": "Gold, silver rates today: Comex gold slides $171/oz; silver plunges on hotter-than-expected US PPI",
            "url": "https://www.livemint.com/market/commodities/gold-silver-rates",
            "snippet": "The April futures contract on COMEX gold fell $171, breaking below the key $5,000 mark to reach $4,837 per troy ounce, marking the lowest level since February.",
        },
        {
            "title": "Gold price today: Gold remains below $4,700 as rate-cut hopes fade",
            "url": "https://finance.yahoo.com/gold-price-today-march-20",
            "snippet": "COMEX gold at $4,574.90, down $30.80 (-0.67%). Rate-cut hopes fade as market reassesses Fed trajectory.",
        },
        {
            "title": "Gold futures plunge below $4,450 per ounce",
            "url": "https://tass.com/economy/2104149",
            "snippet": "The precious metal accelerated in its dip to $4,540.7 per Troy ounce.",
        },
    ],
    "CL": [
        {
            "title": "Oil prices top $112 after Iraq declares force majeure, Kuwait refineries attacked",
            "url": "https://www.cnbc.com/2026/03/20/oil-wti-brent",
            "snippet": "Crude prices topped $112. International benchmark Brent crude futures rose 3.26% to close at $112.19 per barrel.",
        },
        {
            "title": "U.S. oil soars past $100 a barrel, as Iran war shows no signs of ending soon",
            "url": "https://www.nbcnews.com/business/energy/oil-prices-iran-war",
            "snippet": "U.S. crude oil hit $100 per barrel, continuing its surge as the U.S.-Israeli war with Iran shows no signs of ending soon.",
        },
        {
            "title": "Oil Prices Surge as Brent-WTI Spread Blows Out on Iran Supply Risk",
            "url": "https://oilprice.com/oil-prices-surge-brent-wti-spread",
            "snippet": "Oil prices surged and the Brent-WTI spread widened to $10 per barrel as the Iran conflict disrupted flows through the Strait of Hormuz.",
        },
        {
            "title": "Oil extends gains to rise 5.6% after Iran attacks Gulf energy facilities",
            "url": "https://www.reuters.com/business/energy/oil-prices-2026-03-18",
            "snippet": "U.S. West Texas Intermediate crude extended gains to 4% after closing up at $96.32.",
        },
        {
            "title": "WTI Crude Oil Price Today: U.S. Benchmark Stays Below $100 as Brent Soars on Gulf Attacks",
            "url": "https://ts2.tech/en/wti-crude-oil-price-today",
            "snippet": "Even after a brief shot above $100, WTI crude settled back under triple digits, edging up just 0.3% to $96.59 a barrel.",
        },
        {
            "title": "Oil prices give up gains as Netanyahu says Israel will help US reopen Strait of Hormuz",
            "url": "https://finance.yahoo.com/news/oil-prices-give-up-gains-hormuz",
            "snippet": "Futures on US benchmark WTI crude moved up to hold around $97 per barrel.",
        },
        {
            "title": "$166 a barrel? Middle East oil gives clue to where all prices could be headed if Iran war drags on",
            "url": "https://www.cnbc.com/2026/03/19/166-a-barrel-oil-forecast",
            "snippet": "Brent and WTI will ultimately reprice higher as Atlantic basin inventories are drawn down and the global market is forced to clear at a materially tighter supply level.",
        },
    ],
}


def main():
    results = {}
    all_headlines = []

    for instrument, headlines_raw in RAW_HEADLINES.items():
        scored = []
        for h in headlines_raw:
            s = score_headline(h["title"], h["snippet"], h["url"])
            scored.append(s)
            all_headlines.append(s)

        sentiment = aggregate_sentiment(instrument, scored)
        results[instrument] = sentiment.to_dict()

        print(f"\n{'='*60}")
        print(f"  {instrument} Sentiment: {sentiment.label.upper()} "
              f"(score={sentiment.score:.4f}, conf={sentiment.confidence:.4f})")
        print(f"  Headlines scored: {sentiment.headline_count}")
        print(f"{'='*60}")
        for h in scored:
            direction = "🟢" if h.score > 0 else "🔴" if h.score < 0 else "⚪"
            print(f"  {direction} [{h.score:+.2f}] {h.title[:80]}")
            if h.bullish_hits:
                print(f"       ↑ bullish: {', '.join(h.bullish_hits)}")
            if h.bearish_hits:
                print(f"       ↓ bearish: {', '.join(h.bearish_hits)}")

    # Tag events
    events = tag_events(all_headlines)
    high_impact = filter_high_impact(events, min_priority=2, min_confidence=0.1)

    print(f"\n{'='*60}")
    print(f"  HIGH-IMPACT EVENTS ({len(high_impact)} found)")
    print(f"{'='*60}")
    for e in high_impact[:15]:
        print(f"  [{e.event_type:16s}] [{e.impact_timeframe:8s}] "
              f"score={e.sentiment_score:+.2f} | {e.title[:60]}")

    # Build output
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "instruments": results,
        "high_impact_events": [e.to_dict() for e in high_impact],
        "summary": {
            instrument: {
                "score": results[instrument]["score"],
                "label": results[instrument]["label"],
                "confidence": results[instrument]["confidence"],
                "headline_count": results[instrument]["headline_count"],
            }
            for instrument in results
        },
    }

    # Save
    out_path = Path(__file__).resolve().parent.parent.parent / "data" / "mock" / "sentiment_sample.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Saved to {out_path}")
    return output


if __name__ == "__main__":
    main()

"""Seed script — populates 25 realistic mock strategies across all pipeline stages."""
from __future__ import annotations

import asyncio
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

# Ensure core is importable
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession

from core.db import async_session_factory, init_db
from core.enums import (
    Asset,
    EventType,
    PipelineStage,
    STAGE_ORDER,
    StrategyStatus,
    StrategyStyle,
)
from core.models import (
    AuditLog,
    Override,
    ResearchSource,
    Strategy,
    StrategyHistory,
    StrategyMetric,
    StrategyResearchLink,
    TradeExplanation,
)

random.seed(42)

# --------------------------------------------------------------------------- #
# Strategy definitions                                                        #
# --------------------------------------------------------------------------- #

STRATEGY_DEFS = [
    # FULL_LIVE (2)
    {"code": "MOM-001", "name": "NQ Momentum Breakout Alpha", "style": "momentum", "asset": "NQ", "stage": "FULL_LIVE", "status": "ACTIVE"},
    {"code": "TRD-002", "name": "GC Trend Rider", "style": "trend", "asset": "GC", "stage": "FULL_LIVE", "status": "ACTIVE"},
    # MICRO_LIVE (3)
    {"code": "MOM-003", "name": "CL Momentum Surge", "style": "momentum", "asset": "CL", "stage": "MICRO_LIVE", "status": "ACTIVE"},
    {"code": "MRV-004", "name": "NQ Mean Revert Support", "style": "mean_reversion", "asset": "NQ", "stage": "MICRO_LIVE", "status": "ACTIVE"},
    {"code": "SCL-005", "name": "GC Scalp Orderflow", "style": "scalp", "asset": "GC", "stage": "MICRO_LIVE", "status": "ACTIVE"},
    # DEPENDENCY (2)
    {"code": "TRD-006", "name": "NQ Trend Continuation", "style": "trend", "asset": "NQ", "stage": "DEPENDENCY", "status": "ACTIVE"},
    {"code": "NWS-007", "name": "CL News Spike Fade", "style": "news_reaction", "asset": "CL", "stage": "DEPENDENCY", "status": "ACTIVE"},
    # DEGRADATION (3)
    {"code": "MOM-008", "name": "NQ Breakout Retest", "style": "momentum", "asset": "NQ", "stage": "DEGRADATION", "status": "ACTIVE"},
    {"code": "VOL-009", "name": "GC Volume Climax", "style": "volume_flow", "asset": "GC", "stage": "DEGRADATION", "status": "ACTIVE"},
    {"code": "MRV-010", "name": "CL Oversold Bounce", "style": "mean_reversion", "asset": "CL", "stage": "DEGRADATION", "status": "ACTIVE"},
    # PAPER (3)
    {"code": "SCL-011", "name": "NQ Scalp Level Break", "style": "scalp", "asset": "NQ", "stage": "PAPER", "status": "ACTIVE"},
    {"code": "TRD-012", "name": "CL Pullback Entry", "style": "trend", "asset": "CL", "stage": "PAPER", "status": "ACTIVE"},
    {"code": "MOM-013", "name": "GC Momentum Expansion", "style": "momentum", "asset": "GC", "stage": "PAPER", "status": "ACTIVE"},
    # VALIDATION (3)
    {"code": "MRV-014", "name": "NQ RSI Rejection", "style": "mean_reversion", "asset": "NQ", "stage": "VALIDATION", "status": "ACTIVE"},
    {"code": "NWS-015", "name": "GC FOMC Reaction", "style": "news_reaction", "asset": "GC", "stage": "VALIDATION", "status": "ACTIVE"},
    {"code": "VOL-016", "name": "CL OBV Divergence", "style": "volume_flow", "asset": "CL", "stage": "VALIDATION", "status": "ACTIVE"},
    # BACKTEST (4)
    {"code": "SCL-017", "name": "NQ Tick Imbalance", "style": "scalp", "asset": "NQ", "stage": "BACKTEST", "status": "ACTIVE"},
    {"code": "TRD-018", "name": "GC 4H Structure", "style": "trend", "asset": "GC", "stage": "BACKTEST", "status": "ACTIVE"},
    {"code": "MOM-019", "name": "CL Range Break", "style": "momentum", "asset": "CL", "stage": "BACKTEST", "status": "ACTIVE"},
    {"code": "MRV-020", "name": "NQ VWAP Reversion", "style": "mean_reversion", "asset": "NQ", "stage": "BACKTEST", "status": "ACTIVE"},
    # IDEA (3)
    {"code": "NWS-021", "name": "NQ Earnings Drift", "style": "news_reaction", "asset": "NQ", "stage": "IDEA", "status": "PENDING"},
    {"code": "VOL-022", "name": "GC Accumulation Detect", "style": "volume_flow", "asset": "GC", "stage": "IDEA", "status": "PENDING"},
    {"code": "SCL-023", "name": "CL Micro Breakout", "style": "scalp", "asset": "CL", "stage": "IDEA", "status": "PENDING"},
    # KILLED / RETIRED (2)
    {"code": "MOM-024", "name": "NQ False Breakout (Killed)", "style": "momentum", "asset": "NQ", "stage": "BACKTEST", "status": "KILLED"},
    {"code": "TRD-025", "name": "GC Overfit Trend (Retired)", "style": "trend", "asset": "GC", "stage": "IDEA", "status": "RETIRED"},
]


TEMPLATES = {
    "momentum": {
        "bias_timeframe": "4h/1h",
        "setup_timeframe": "15m",
        "entry_timeframe": "5m",
        "trigger": ["breakout", "volume_spike"],
        "risk_model": "fixed_R",
    },
    "mean_reversion": {
        "bias_timeframe": "4h/1h",
        "setup_timeframe": "15m",
        "entry_timeframe": "5m",
        "trigger": ["oversold_bounce", "support_rejection"],
        "risk_model": "fixed_R",
    },
    "scalp": {
        "bias_timeframe": "1h",
        "setup_timeframe": "5m",
        "entry_timeframe": "5m",
        "trigger": ["orderflow_imbalance", "level_break"],
        "risk_model": "fixed_R",
    },
    "trend": {
        "bias_timeframe": "4h",
        "setup_timeframe": "1h",
        "entry_timeframe": "15m/5m",
        "trigger": ["trend_continuation", "pullback_to_structure"],
        "risk_model": "trailing_R",
    },
    "news_reaction": {
        "bias_timeframe": "1h",
        "setup_timeframe": "15m",
        "entry_timeframe": "5m",
        "trigger": ["news_spike", "sentiment_shift"],
        "risk_model": "fixed_R",
    },
    "volume_flow": {
        "bias_timeframe": "4h/1h",
        "setup_timeframe": "15m",
        "entry_timeframe": "5m",
        "trigger": ["volume_climax", "obv_divergence"],
        "risk_model": "fixed_R",
    },
}

# --------------------------------------------------------------------------- #
# Research sources (top traders per style)                                    #
# --------------------------------------------------------------------------- #

RESEARCH_SOURCES = [
    # Momentum
    {"style": "momentum", "trader": "Oliver Velez", "focus": "NQ, ES", "notes": "Micro-pattern breakout specialist. Teaches momentum burst entries on 5m timeframe with volume confirmation.", "patterns": {"key_pattern": "opening_range_breakout", "timeframe_focus": "5m/15m", "risk_approach": "tight_stops"}},
    {"style": "momentum", "trader": "Ross Cameron", "focus": "Equities/Futures", "notes": "Gap-and-go momentum trader. Focuses on high relative volume and clean breakout levels.", "patterns": {"key_pattern": "gap_momentum", "timeframe_focus": "5m", "risk_approach": "risk_reward_2_1"}},
    {"style": "momentum", "trader": "Madaz Money", "focus": "Small caps/Futures", "notes": "Aggressive momentum trader. Multi-timeframe confirmation with heavy volume filter.", "patterns": {"key_pattern": "volume_spike_entry", "timeframe_focus": "1m/5m", "risk_approach": "scaling_in"}},
    {"style": "momentum", "trader": "Kira (TradesbyKira)", "focus": "NQ, ES", "notes": "Futures momentum trader focusing on session open plays and range expansion.", "patterns": {"key_pattern": "session_open_momentum", "timeframe_focus": "5m/15m", "risk_approach": "fixed_R"}},
    {"style": "momentum", "trader": "Sang Lucci", "focus": "Futures/Options", "notes": "Momentum and tape reading specialist. Uses order flow to time momentum entries.", "patterns": {"key_pattern": "tape_reading_momentum", "timeframe_focus": "5m", "risk_approach": "order_flow_stops"}},
    # Mean Reversion
    {"style": "mean_reversion", "trader": "Adam Grimes", "focus": "Futures/Equities", "notes": "Quantitative mean reversion researcher. Uses statistical edges with strict risk management.", "patterns": {"key_pattern": "statistical_reversion", "timeframe_focus": "1h/4h", "risk_approach": "volatility_based"}},
    {"style": "mean_reversion", "trader": "Linda Raschke", "focus": "Futures", "notes": "Classic mean reversion and pattern trader. Holy Grail setup, Turtle Soup.", "patterns": {"key_pattern": "turtle_soup", "timeframe_focus": "15m/1h", "risk_approach": "fixed_dollar"}},
    {"style": "mean_reversion", "trader": "Kevin Davey", "focus": "Futures", "notes": "Systematic mean reversion. Validates strategies through Monte Carlo and walk-forward.", "patterns": {"key_pattern": "systematic_reversion", "timeframe_focus": "1h/4h", "risk_approach": "kelly_fraction"}},
    {"style": "mean_reversion", "trader": "Larry Connors", "focus": "Equities/Futures", "notes": "RSI-based mean reversion. Published ConnorsRSI and short-term reversion strategies.", "patterns": {"key_pattern": "rsi_reversion", "timeframe_focus": "daily/1h", "risk_approach": "position_sizing"}},
    {"style": "mean_reversion", "trader": "Cesar Alvarez", "focus": "Futures/Equities", "notes": "Quantitative researcher for mean reversion. Focuses on oversold conditions with catalyst.", "patterns": {"key_pattern": "oversold_catalyst", "timeframe_focus": "1h", "risk_approach": "statistical_stops"}},
    # Scalp
    {"style": "scalp", "trader": "Jigsaw Trading (Peter Davies)", "focus": "Futures", "notes": "Order flow scalping specialist. DOM reading and footprint chart analysis.", "patterns": {"key_pattern": "dom_imbalance", "timeframe_focus": "1m/5m", "risk_approach": "tick_based_stops"}},
    {"style": "scalp", "trader": "Axia Futures", "focus": "Futures", "notes": "Institutional scalping. Level-based trading with order flow confirmation.", "patterns": {"key_pattern": "level_scalp", "timeframe_focus": "5m", "risk_approach": "institutional_levels"}},
    {"style": "scalp", "trader": "FuturesTrader71", "focus": "ES, NQ", "notes": "Volume profile and market profile scalping. Uses POC and value area for entries.", "patterns": {"key_pattern": "volume_profile_scalp", "timeframe_focus": "5m/15m", "risk_approach": "value_area_stops"}},
    {"style": "scalp", "trader": "Mack (PATs Trading)", "focus": "Futures", "notes": "Price action scalping. Clean chart, support/resistance with confirmation candles.", "patterns": {"key_pattern": "price_action_scalp", "timeframe_focus": "5m", "risk_approach": "candle_based"}},
    {"style": "scalp", "trader": "Al Brooks", "focus": "ES, Futures", "notes": "Bar-by-bar price action. Master of reading individual candle context.", "patterns": {"key_pattern": "bar_reading", "timeframe_focus": "5m", "risk_approach": "structure_based"}},
    # Trend
    {"style": "trend", "trader": "Ed Seykota", "focus": "Futures", "notes": "Legendary trend follower. Systematic trend following with strict risk rules.", "patterns": {"key_pattern": "systematic_trend", "timeframe_focus": "daily/4h", "risk_approach": "trailing_stops"}},
    {"style": "trend", "trader": "Richard Dennis", "focus": "Futures", "notes": "Turtle Trading founder. Breakout-based trend following with position sizing.", "patterns": {"key_pattern": "turtle_breakout", "timeframe_focus": "daily/4h", "risk_approach": "atr_based"}},
    {"style": "trend", "trader": "Michael Covel", "focus": "Futures/Global", "notes": "Trend following evangelist. Documents CTA-style trend following across all markets.", "patterns": {"key_pattern": "cross_market_trend", "timeframe_focus": "4h/daily", "risk_approach": "portfolio_heat"}},
    {"style": "trend", "trader": "Andreas Clenow", "focus": "Futures", "notes": "Systematic trend following. Published Following the Trend with full backtested systems.", "patterns": {"key_pattern": "momentum_trend", "timeframe_focus": "4h/daily", "risk_approach": "volatility_parity"}},
    {"style": "trend", "trader": "Jerry Parker", "focus": "Futures", "notes": "Original Turtle trader. Long-term trend following with diversified futures.", "patterns": {"key_pattern": "long_term_trend", "timeframe_focus": "daily/weekly", "risk_approach": "risk_parity"}},
    # News Reaction
    {"style": "news_reaction", "trader": "Kathy Lien", "focus": "Forex/Futures", "notes": "Macro event trader. Specializes in FOMC, NFP, and macro data reactions.", "patterns": {"key_pattern": "macro_event_fade", "timeframe_focus": "5m/15m", "risk_approach": "event_based"}},
    {"style": "news_reaction", "trader": "Raoul Pal", "focus": "Macro/Futures", "notes": "Global macro researcher. Uses macro cycles and events for directional bias.", "patterns": {"key_pattern": "macro_cycle", "timeframe_focus": "4h/daily", "risk_approach": "conviction_sizing"}},
    {"style": "news_reaction", "trader": "Jim Dalton", "focus": "Futures", "notes": "Market Profile and news reaction. Uses profile to gauge market acceptance of news.", "patterns": {"key_pattern": "profile_news_reaction", "timeframe_focus": "15m/1h", "risk_approach": "profile_based"}},
    # Volume Flow
    {"style": "volume_flow", "trader": "Anna Coulling", "focus": "Futures/Forex", "notes": "Volume spread analysis specialist. Uses volume to confirm price movements.", "patterns": {"key_pattern": "vsa_analysis", "timeframe_focus": "15m/1h", "risk_approach": "volume_based"}},
    {"style": "volume_flow", "trader": "Tom Williams", "focus": "Futures", "notes": "VSA founder. Wyckoff-based volume analysis for detecting smart money.", "patterns": {"key_pattern": "wyckoff_vsa", "timeframe_focus": "1h/4h", "risk_approach": "accumulation_distribution"}},
]

# --------------------------------------------------------------------------- #
# Explanation templates                                                       #
# --------------------------------------------------------------------------- #

WIN_EXPLANATIONS = [
    "4H trend confirmed bullish. 1H pullback completed. 15m setup triggered at VWAP. 5m breakout candle with volume spike. Clean 2R target hit.",
    "Higher timeframe alignment strong. Entry at 5m demand zone after 15m consolidation. Momentum carried through resistance. Trailed stop to breakeven, exited at 2.5R.",
    "RSI oversold on 1H at 4H support. 15m showed bullish divergence. 5m entry on engulfing candle. Mean reverted to VWAP for 1.8R profit.",
    "Volume climax detected on 15m. 5m showed absorption at support. Entered long on reversal candle. Price moved to 1H resistance for 2R.",
    "News catalyst aligned with 4H trend. 15m showed continuation pattern. 5m breakout entry with tight stop. Target hit within 45 minutes.",
]

LOSS_EXPLANATIONS = [
    "4H trend was ambiguous — ranging market. 15m setup looked valid but 5m entry failed. Stopped out at 1R loss. Regime was choppy.",
    "Entry was early — 5m trigger fired before 15m setup completed. Price faked out and reversed. Hit stop at 1R. Lesson: wait for full alignment.",
    "Volume was below average at entry. 15m setup was valid but lacked conviction. Slow bleed to stop loss. 0.8R loss.",
    "News spike caused volatility beyond normal range. Stop was hit within seconds of entry. 1R loss. Data feed lag may have contributed.",
    "Mean reversion entry at support, but support broke. 4H structure shifted during trade. Full 1R stop hit.",
]


def _rand_metrics(stage: str, status: str) -> dict:
    """Generate realistic metrics based on pipeline stage."""
    if status in ("KILLED", "RETIRED"):
        return {
            "pnl": round(random.uniform(-8000, -500), 2),
            "sharpe": round(random.uniform(-0.5, 0.4), 2),
            "drawdown": round(random.uniform(0.06, 0.15), 4),
            "win_rate": round(random.uniform(0.20, 0.38), 4),
            "trade_count": random.randint(50, 300),
            "expectancy": round(random.uniform(-50, -5), 2),
            "profit_factor": round(random.uniform(0.4, 0.9), 2),
        }

    stage_quality = {
        "IDEA": (0, 0),
        "BACKTEST": (0.3, 0.7),
        "VALIDATION": (0.5, 0.9),
        "PAPER": (0.6, 1.0),
        "DEGRADATION": (0.65, 1.1),
        "DEPENDENCY": (0.7, 1.2),
        "MICRO_LIVE": (0.75, 1.3),
        "FULL_LIVE": (0.8, 1.5),
    }
    wr_base, sharpe_base = stage_quality.get(stage, (0.4, 0.6))

    pnl_range = {
        "IDEA": (0, 0),
        "BACKTEST": (-2000, 5000),
        "VALIDATION": (500, 12000),
        "PAPER": (1000, 18000),
        "DEGRADATION": (2000, 20000),
        "DEPENDENCY": (3000, 25000),
        "MICRO_LIVE": (5000, 35000),
        "FULL_LIVE": (10000, 80000),
    }
    pnl_lo, pnl_hi = pnl_range.get(stage, (0, 0))

    return {
        "pnl": round(random.uniform(pnl_lo, pnl_hi), 2),
        "sharpe": round(max(0.1, sharpe_base + random.uniform(-0.3, 0.4)), 2),
        "drawdown": round(random.uniform(0.01, 0.08), 4),
        "win_rate": round(min(0.75, max(0.30, wr_base + random.uniform(-0.08, 0.12))), 4),
        "trade_count": random.randint(100, 2000) if stage != "IDEA" else 0,
        "expectancy": round(random.uniform(5, 120), 2) if stage != "IDEA" else 0,
        "profit_factor": round(random.uniform(1.0, 2.5), 2) if stage != "IDEA" else 0,
    }


async def seed_all():
    """Main seed function."""
    await init_db()

    async with async_session_factory() as session:
        now = datetime.now(timezone.utc)
        strategy_map: dict[str, Strategy] = {}
        research_map: dict[str, list[ResearchSource]] = {}

        # ------ Research Sources ------
        for rs in RESEARCH_SOURCES:
            src = ResearchSource(
                strategy_style=rs["style"],
                trader_name=rs["trader"],
                market_focus=rs["focus"],
                activity_status="active",
                research_notes=rs["notes"],
                extracted_patterns_json=rs["patterns"],
            )
            session.add(src)
            research_map.setdefault(rs["style"], []).append(src)

        await session.flush()

        # ------ Strategies ------
        for i, sd in enumerate(STRATEGY_DEFS):
            created = now - timedelta(days=random.randint(5, 60))
            s = Strategy(
                strategy_code=sd["code"],
                name=sd["name"],
                style=sd["style"],
                asset=sd["asset"],
                status=sd["status"],
                current_stage=sd["stage"],
                current_mode="paper" if sd["stage"] == "PAPER" else ("micro" if sd["stage"] == "MICRO_LIVE" else ("full" if sd["stage"] == "FULL_LIVE" else None)),
                created_at=created,
                updated_at=now,
                retired_at=now if sd["status"] == "RETIRED" else None,
                consecutive_demotions=3 if sd["status"] == "RETIRED" else (1 if sd["status"] == "KILLED" else 0),
                current_rank=i + 1 if sd["status"] == "ACTIVE" else None,
                is_active=sd["status"] == "ACTIVE",
                template_config=TEMPLATES.get(sd["style"]),
            )
            session.add(s)
            await session.flush()
            strategy_map[sd["code"]] = s

            # ------ Metrics ------
            metrics = _rand_metrics(sd["stage"], sd["status"])
            m = StrategyMetric(
                strategy_id=s.id,
                stage=sd["stage"],
                **metrics,
                timestamp=now - timedelta(hours=random.randint(1, 48)),
            )
            session.add(m)

            # ------ Stage History (build realistic progression) ------
            stage_idx = STAGE_ORDER.index(PipelineStage(sd["stage"]))
            history_time = created
            for j in range(stage_idx + 1):
                from_s = STAGE_ORDER[j - 1].value if j > 0 else None
                to_s = STAGE_ORDER[j].value
                evt = EventType.STRATEGY_CREATED if j == 0 else EventType.STAGE_PROMOTED
                h = StrategyHistory(
                    strategy_id=s.id,
                    event_type=evt.value,
                    from_stage=from_s,
                    to_stage=to_s,
                    reason=f"{'Created from template' if j == 0 else f'Passed {STAGE_ORDER[j-1].value} gate'}",
                    actor="Apex" if j == 0 else "Darwin",
                    created_at=history_time,
                )
                session.add(h)
                history_time += timedelta(days=random.randint(1, 5))

            # Kill/retire events
            if sd["status"] == "KILLED":
                h = StrategyHistory(
                    strategy_id=s.id,
                    event_type=EventType.STRATEGY_KILLED.value,
                    from_stage=sd["stage"],
                    to_stage="BACKTEST",
                    reason="Kill switch: drawdown > 5% and win_rate_30d < 35%",
                    actor="RiskEngine",
                    created_at=now - timedelta(hours=6),
                )
                session.add(h)
            elif sd["status"] == "RETIRED":
                h = StrategyHistory(
                    strategy_id=s.id,
                    event_type=EventType.STRATEGY_RETIRED.value,
                    from_stage=sd["stage"],
                    to_stage="IDEA",
                    reason="3 consecutive demotions — permanently retired",
                    actor="Darwin",
                    created_at=now - timedelta(hours=12),
                )
                session.add(h)

            # ------ Audit Log entries ------
            audit = AuditLog(
                strategy_id=s.id,
                event_type=EventType.STRATEGY_CREATED.value,
                source_service="SeedScript",
                payload_json={"strategy_code": sd["code"], "template": sd["style"]},
                success=True,
            )
            session.add(audit)

            # ------ Research Links ------
            style_sources = research_map.get(sd["style"], [])
            if style_sources:
                for src in random.sample(style_sources, min(2, len(style_sources))):
                    link = StrategyResearchLink(
                        strategy_id=s.id,
                        research_source_id=src.id,
                        influence_weight=round(random.uniform(0.3, 1.0), 2),
                        notes=f"Influenced by {src.trader_name}'s approach",
                    )
                    session.add(link)

            # ------ Trade Explanations (for strategies past BACKTEST) ------
            if stage_idx >= 1 and sd["status"] not in ("RETIRED",):
                for t_idx in range(random.randint(3, 8)):
                    is_win = random.random() < metrics.get("win_rate", 0.5)
                    expl = random.choice(WIN_EXPLANATIONS if is_win else LOSS_EXPLANATIONS)
                    te = TradeExplanation(
                        strategy_id=s.id,
                        trade_id=f"{sd['code']}-T{t_idx+1:04d}",
                        explanation_text=expl,
                        contributing_factors_json={
                            "timeframe_alignment": random.choice(["strong", "moderate", "weak"]),
                            "volume_confirmation": random.choice([True, False]),
                            "regime": random.choice(["trending", "ranging", "volatile"]),
                        },
                        result="WIN" if is_win else "LOSS",
                        pnl=round(random.uniform(50, 500) if is_win else random.uniform(-400, -20), 2),
                        created_at=now - timedelta(hours=random.randint(1, 200)),
                    )
                    session.add(te)

        # ------ Override examples ------
        override_approved = Override(
            strategy_id=strategy_map["MOM-001"].id,
            requested_by="Overseer",
            approved_by="Jordan",
            result="APPROVED",
            reason="Manual promotion override for prop firm funded stage — Jordan approved after review",
        )
        session.add(override_approved)

        override_rejected = Override(
            strategy_id=strategy_map["MOM-024"].id,
            requested_by="Alpha",
            approved_by=None,
            result="REJECTED",
            reason="Attempted to skip VALIDATION stage — blocked by pipeline enforcement",
        )
        session.add(override_rejected)

        # Audit for overrides
        session.add(AuditLog(
            strategy_id=strategy_map["MOM-024"].id,
            event_type=EventType.OVERRIDE_ATTEMPTED.value,
            source_service="Alpha",
            payload_json={"reason": "Attempted to skip VALIDATION"},
            success=False,
        ))
        session.add(AuditLog(
            strategy_id=strategy_map["MOM-024"].id,
            event_type=EventType.OVERRIDE_REJECTED.value,
            source_service="PipelineEngine",
            payload_json={"reason": "Cannot skip stages"},
            success=True,
        ))

        # Risk limit hit example
        session.add(AuditLog(
            strategy_id=strategy_map["MOM-024"].id,
            event_type=EventType.RISK_LIMIT_HIT.value,
            source_service="RiskEngine",
            payload_json={"rule": "max_drawdown", "value": 0.062, "threshold": 0.05},
            success=True,
        ))

        await session.commit()
        print(f"✅ Seeded {len(STRATEGY_DEFS)} strategies, {len(RESEARCH_SOURCES)} research sources")
        print("   + metrics, history, trade explanations, overrides, audit logs")


if __name__ == "__main__":
    asyncio.run(seed_all())

"""
Test: Load one DNA per style, create synthetic MarketContexts,
and verify each agent generates (or doesn't generate) signals.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from services.executors.base_executor import MarketContext, StrategyDNA, TimeframeData
from services.executors.signal_router import SignalRouter, EXECUTOR_REGISTRY


def load_dnas() -> list[dict]:
    dna_path = PROJECT_ROOT / "data" / "mock" / "strategy_dnas.json"
    with open(dna_path) as f:
        return json.load(f)


def make_bullish_trending_context(instrument: str = "NQ") -> MarketContext:
    """Synthetic context: strong uptrend, pulling back to support, with volume."""
    return MarketContext(
        instrument=instrument,
        timestamp="2026-03-22T20:00:00Z",
        tf_4h=TimeframeData(
            ohlc={"open": 21800, "high": 22050, "low": 21750, "close": 22000},
            volume=150000,
            vwap=21900,
            rsi=58.0,
            atr=120.0,
            ema_20=21850.0,
            ema_50=21700.0,
            trend="bullish",
            support=21700.0,
            resistance=22100.0,
            adx=28.0,
            macd=45.0,
            macd_signal=30.0,
            macd_histogram=15.0,
            bb_upper=22100.0,
            bb_lower=21600.0,
            bb_middle=21850.0,
            bb_width=500.0,
            poc=21850.0,
            vah=22000.0,
            val=21700.0,
            avg_volume=120000,
        ),
        tf_1h=TimeframeData(
            ohlc={"open": 21950, "high": 22010, "low": 21920, "close": 21980},
            volume=35000,
            vwap=21960,
            rsi=52.0,
            atr=45.0,
            ema_20=21950.0,
            ema_50=21880.0,
            trend="bullish",
            support=21900.0,
            resistance=22050.0,
            adx=26.0,
            bb_upper=22050.0,
            bb_lower=21860.0,
            bb_middle=21955.0,
            bb_width=190.0,
            stochastic_k=45.0,
            stochastic_d=50.0,
            cvd=5000.0,
            delta=1200.0,
            poc=21960.0,
            vah=22010.0,
            val=21910.0,
            avg_volume=30000,
        ),
        tf_15m=TimeframeData(
            ohlc={"open": 21970, "high": 21995, "low": 21955, "close": 21985},
            volume=12000,
            vwap=21975,
            rsi=48.0,
            atr=18.0,
            ema_20=21975.0,
            ema_50=21960.0,
            trend="neutral",
            support=21950.0,
            resistance=22000.0,
            adx=22.0,
            bb_upper=22010.0,
            bb_lower=21940.0,
            bb_middle=21975.0,
            bb_width=70.0,
            stochastic_k=42.0,
            stochastic_d=48.0,
            cvd=2000.0,
            delta=500.0,
            poc=21975.0,
            vah=21990.0,
            val=21960.0,
            avg_volume=10000,
        ),
        tf_5m=TimeframeData(
            ohlc={"open": 21975, "high": 21992, "low": 21970, "close": 21990},
            volume=5500,
            vwap=21982,
            rsi=55.0,
            atr=8.0,
            ema_20=21980.0,
            ema_50=21972.0,
            trend="bullish",
            support=21970.0,
            resistance=22000.0,
            adx=20.0,
            delta=300.0,
            cvd=800.0,
            avg_volume=4000,
        ),
    )


def make_oversold_reversal_context(instrument: str = "NQ") -> MarketContext:
    """Synthetic context: oversold at support, ripe for mean reversion."""
    return MarketContext(
        instrument=instrument,
        timestamp="2026-03-22T20:00:00Z",
        tf_4h=TimeframeData(
            ohlc={"open": 21900, "high": 21920, "low": 21700, "close": 21720},
            volume=160000,
            vwap=21800,
            rsi=32.0,
            atr=130.0,
            ema_20=21900.0,
            ema_50=21950.0,
            trend="bearish",
            support=21700.0,
            resistance=22000.0,
            adx=18.0,  # ranging — good for MR
            bb_upper=22100.0,
            bb_lower=21650.0,
            bb_middle=21875.0,
            bb_width=450.0,
            poc=21850.0,
            vah=21950.0,
            val=21720.0,
            avg_volume=130000,
        ),
        tf_1h=TimeframeData(
            ohlc={"open": 21780, "high": 21790, "low": 21700, "close": 21715},
            volume=38000,
            vwap=21750,
            rsi=25.0,  # oversold!
            atr=50.0,
            ema_20=21800.0,
            ema_50=21870.0,
            trend="bearish",
            support=21700.0,
            resistance=21850.0,
            bb_upper=21900.0,
            bb_lower=21700.0,
            bb_middle=21800.0,
            bb_width=200.0,
            stochastic_k=12.0,
            stochastic_d=18.0,
            cvd=-3000.0,
            delta=-800.0,
            poc=21750.0,
            vah=21800.0,
            val=21710.0,
            avg_volume=32000,
        ),
        tf_15m=TimeframeData(
            ohlc={"open": 21720, "high": 21730, "low": 21700, "close": 21710},
            volume=13000,
            vwap=21715,
            rsi=22.0,  # deeply oversold
            atr=15.0,
            ema_20=21740.0,
            ema_50=21770.0,
            trend="bearish",
            support=21700.0,
            resistance=21760.0,
            bb_upper=21770.0,
            bb_lower=21700.0,  # touching lower BB
            bb_middle=21735.0,
            bb_width=70.0,
            stochastic_k=8.0,
            stochastic_d=12.0,
            cvd=-1500.0,
            delta=-400.0,
            avg_volume=10000,
        ),
        tf_5m=TimeframeData(
            ohlc={"open": 21705, "high": 21720, "low": 21700, "close": 21718},
            volume=5200,
            vwap=21710,
            rsi=28.0,
            atr=6.0,
            ema_20=21710.0,
            ema_50=21730.0,
            trend="bearish",
            support=21700.0,
            resistance=21740.0,
            delta=100.0,  # delta turning positive — hidden buying
            cvd=-200.0,
            avg_volume=4200,
        ),
    )


def make_news_event_context(instrument: str = "NQ") -> MarketContext:
    """Synthetic context: post-CPI with volume surge and directional thrust."""
    return MarketContext(
        instrument=instrument,
        timestamp="2026-03-22T13:00:00Z",
        tf_4h=TimeframeData(
            ohlc={"open": 21800, "high": 21850, "low": 21780, "close": 21830},
            volume=140000,
            vwap=21810,
            rsi=55.0,
            atr=110.0,
            ema_20=21790.0,
            ema_50=21750.0,
            trend="bullish",
            support=21700.0,
            resistance=21900.0,
            adx=22.0,
            avg_volume=120000,
        ),
        tf_1h=TimeframeData(
            ohlc={"open": 21820, "high": 21835, "low": 21810, "close": 21825},
            volume=25000,
            vwap=21820,
            rsi=54.0,
            atr=30.0,
            ema_20=21815.0,
            ema_50=21790.0,
            trend="neutral",
            support=21800.0,
            resistance=21860.0,
            bb_upper=21860.0,
            bb_lower=21780.0,
            bb_middle=21820.0,
            bb_width=80.0,  # compressed before event
            avg_volume=28000,
        ),
        tf_15m=TimeframeData(
            ohlc={"open": 21825, "high": 21890, "low": 21820, "close": 21885},
            volume=22000,  # huge volume surge
            vwap=21855,
            rsi=72.0,
            atr=20.0,
            ema_20=21840.0,
            ema_50=21820.0,
            trend="bullish",
            support=21820.0,
            resistance=21900.0,
            delta=3000.0,
            cvd=5000.0,
            avg_volume=9000,  # 2.4x average
        ),
        tf_5m=TimeframeData(
            ohlc={"open": 21875, "high": 21895, "low": 21870, "close": 21892},
            volume=8500,
            vwap=21880,
            rsi=68.0,
            atr=10.0,
            ema_20=21870.0,
            ema_50=21850.0,
            trend="bullish",
            support=21870.0,
            resistance=21900.0,
            delta=1500.0,
            cvd=3000.0,
            avg_volume=4500,
        ),
        news_events=[{"type": "CPI", "time": "08:30", "surprise": "+0.2%"}],
    )


def run_test():
    print("=" * 80)
    print("STRATEGY EXECUTOR TEST — 6 Agents × Synthetic Market Contexts")
    print("=" * 80)

    dnas = load_dnas()
    print(f"\nLoaded {len(dnas)} strategy DNAs")

    # Initialize router with all DNAs
    router = SignalRouter(dnas, account_size=100_000.0)
    print(f"Initialized {len(router.agents)} agents:")
    for agent_id, agent in router.agents.items():
        print(f"  • {agent.AGENT_NAME} ({agent.dna.strategy_code})")

    # Test scenarios
    scenarios = [
        ("Bullish Trending Market", make_bullish_trending_context()),
        ("Oversold Reversal Setup", make_oversold_reversal_context()),
        ("News Event (CPI Surprise)", make_news_event_context()),
    ]

    total_signals = 0
    total_approved = 0
    total_rejected = 0

    for scenario_name, ctx in scenarios:
        print(f"\n{'─' * 70}")
        print(f"SCENARIO: {scenario_name}")
        print(f"Instrument: {ctx.instrument} | Time: {ctx.timestamp}")
        print(f"{'─' * 70}")

        result = router.run_all(ctx, auto_approve=False)

        if result.signals_generated:
            for sig in result.signals_generated:
                status = "✅ APPROVED" if sig["id"] in [a["id"] for a in result.signals_approved] else "❌ REJECTED"
                print(
                    f"  {status} | {sig['agent_id']:>8} | {sig['direction']:>5} {sig['instrument']} "
                    f"@ {sig['entry_price']:.2f} | SL={sig['stop_loss']:.2f} | "
                    f"TP={sig['target_1']:.2f} | RR={sig['reward_risk_ratio']:.2f} | "
                    f"Conf={sig['composite_confidence']:.3f}"
                )
        else:
            print("  (no signals generated)")

        if result.signals_rejected:
            for rej in result.signals_rejected:
                print(f"  ↳ Rejection reason: {rej.get('rejection_reason', 'unknown')}")

        if result.errors:
            for err in result.errors:
                print(f"  ⚠ ERROR: {err['agent_id']} — {err['error']}")

        total_signals += len(result.signals_generated)
        total_approved += len(result.signals_approved)
        total_rejected += len(result.signals_rejected)

    # Summary
    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")
    print(f"  Scenarios tested:    {len(scenarios)}")
    print(f"  Total signals:       {total_signals}")
    print(f"  Approved:            {total_approved}")
    print(f"  Rejected:            {total_rejected}")
    print()

    # Per-agent status
    print("Agent Status:")
    for agent_id, agent in router.agents.items():
        status = agent.get_status()
        print(
            f"  {agent.AGENT_NAME:35s} | "
            f"Signals={status['signals_generated']:2d} | "
            f"Approved={status['signals_approved']:2d} | "
            f"Rejected={status['signals_rejected']:2d}"
        )

    print(f"\n{'=' * 80}")
    print("TEST COMPLETE")
    print(f"{'=' * 80}")

    return total_signals > 0  # at least some signals should be generated


if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)

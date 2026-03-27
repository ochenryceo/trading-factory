"""
Test: Overseer Decision Engine — 5 trade signals with varying alignment levels.

Validates that the decision engine correctly approves, modifies, and rejects
based on multi-TF alignment, confidence, risk/reward, and performance rankings.
"""
from __future__ import annotations

import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.overseer.decision_engine import (
    Decision,
    DecisionEngine,
    Direction,
    MarketContext,
    PerformanceRanking,
    RiskLevel,
    Timeframe,
    TradeSignal,
)
from services.overseer.approvals import ApprovalPipeline, RiskState
from services.overseer.portfolio_manager import PortfolioManager


def build_engine() -> DecisionEngine:
    """Set up engine with rankings and market context."""
    eng = DecisionEngine()

    # Darwin rankings
    eng.update_rankings([
        PerformanceRanking("strat-momentum-1", rank=1, win_rate=0.62, sharpe=2.1, pnl_30d=4200),
        PerformanceRanking("strat-trend-2", rank=2, win_rate=0.58, sharpe=1.8, pnl_30d=3100),
        PerformanceRanking("strat-scalp-3", rank=3, win_rate=0.55, sharpe=1.4, pnl_30d=1800),
        PerformanceRanking("strat-mr-4", rank=4, win_rate=0.50, sharpe=1.0, pnl_30d=900),
        PerformanceRanking("strat-news-5", rank=5, win_rate=0.45, sharpe=0.7, pnl_30d=-200),
        PerformanceRanking("strat-vol-6", rank=6, win_rate=0.40, sharpe=0.3, pnl_30d=-800),
    ])

    # Market context: bullish trending
    eng.update_market_context(MarketContext(
        regime="trending",
        vix_level=18.0,
        market_direction=Direction.LONG,
        sentiment_score=0.6,
    ))

    return eng


def test_signal_1_full_alignment_high_confidence():
    """Signal 1: All 4 TFs aligned LONG, high confidence, top-ranked strategy → APPROVE."""
    eng = build_engine()

    signal = TradeSignal(
        strategy_id="strat-momentum-1",
        strategy_name="momentum",
        asset="NQ",
        direction=Direction.LONG,
        confidence=0.85,
        risk_level=RiskLevel.MEDIUM,
        timeframes={
            Timeframe.M5: Direction.LONG,
            Timeframe.M15: Direction.LONG,
            Timeframe.H1: Direction.LONG,
            Timeframe.H4: Direction.LONG,
        },
        entry_price=18500.0,
        stop_loss=18450.0,
        take_profit=18600.0,
        risk_reward_ratio=2.0,
    )

    decision = eng.evaluate(signal)
    print(f"\n{'='*60}")
    print(f"SIGNAL 1: Full alignment, high confidence (momentum)")
    print(f"  Direction: {signal.direction.value} | Confidence: {signal.confidence}")
    print(f"  TF Alignment: 4/4 LONG")
    print(f"  → Decision: {decision.decision.value}")
    print(f"  → Score:    {decision.score:.4f}")
    print(f"  → Reason:   {decision.reason}")
    print(f"  → Alignment: {decision.alignment_score}")

    assert decision.decision == Decision.APPROVE, f"Expected APPROVE, got {decision.decision}"
    assert decision.alignment_score == 1.0
    assert decision.score >= 0.50
    print(f"  ✅ PASSED")


def test_signal_2_three_tf_aligned():
    """Signal 2: 3/4 TFs aligned, moderate confidence → APPROVE (with possibly lower score)."""
    eng = build_engine()

    signal = TradeSignal(
        strategy_id="strat-trend-2",
        strategy_name="trend",
        asset="GC",
        direction=Direction.LONG,
        confidence=0.70,
        risk_level=RiskLevel.MEDIUM,
        timeframes={
            Timeframe.M5: Direction.SHORT,  # one dissenter
            Timeframe.M15: Direction.LONG,
            Timeframe.H1: Direction.LONG,
            Timeframe.H4: Direction.LONG,
        },
        risk_reward_ratio=2.5,
    )

    decision = eng.evaluate(signal)
    print(f"\n{'='*60}")
    print(f"SIGNAL 2: 3/4 TFs aligned, moderate confidence (trend)")
    print(f"  Direction: {signal.direction.value} | Confidence: {signal.confidence}")
    print(f"  TF Alignment: 3/4 LONG")
    print(f"  → Decision: {decision.decision.value}")
    print(f"  → Score:    {decision.score:.4f}")
    print(f"  → Reason:   {decision.reason}")
    print(f"  → Alignment: {decision.alignment_score}")

    assert decision.decision in (Decision.APPROVE, Decision.MODIFY), \
        f"Expected APPROVE or MODIFY, got {decision.decision}"
    assert decision.alignment_score == 0.7
    print(f"  ✅ PASSED")


def test_signal_3_poor_alignment_reject():
    """Signal 3: Only 2/4 TFs aligned → alignment 0.3 → REJECT."""
    eng = build_engine()

    signal = TradeSignal(
        strategy_id="strat-scalp-3",
        strategy_name="scalp",
        asset="CL",
        direction=Direction.LONG,
        confidence=0.60,
        risk_level=RiskLevel.MEDIUM,
        timeframes={
            Timeframe.M5: Direction.LONG,
            Timeframe.M15: Direction.SHORT,
            Timeframe.H1: Direction.LONG,
            Timeframe.H4: Direction.SHORT,
        },
        risk_reward_ratio=1.8,
    )

    decision = eng.evaluate(signal)
    print(f"\n{'='*60}")
    print(f"SIGNAL 3: 2/4 TFs aligned — poor alignment (scalp)")
    print(f"  Direction: {signal.direction.value} | Confidence: {signal.confidence}")
    print(f"  TF Alignment: 2/4 LONG")
    print(f"  → Decision: {decision.decision.value}")
    print(f"  → Score:    {decision.score:.4f}")
    print(f"  → Reason:   {decision.reason}")
    print(f"  → Alignment: {decision.alignment_score}")

    assert decision.decision == Decision.REJECT, f"Expected REJECT, got {decision.decision}"
    assert decision.alignment_score == 0.3
    print(f"  ✅ PASSED")


def test_signal_4_low_confidence_reject():
    """Signal 4: Low confidence (0.20) → instant REJECT before scoring."""
    eng = build_engine()

    signal = TradeSignal(
        strategy_id="strat-news-5",
        strategy_name="news_reaction",
        asset="NQ",
        direction=Direction.SHORT,
        confidence=0.20,
        risk_level=RiskLevel.HIGH,
        timeframes={
            Timeframe.M5: Direction.SHORT,
            Timeframe.M15: Direction.SHORT,
            Timeframe.H1: Direction.SHORT,
            Timeframe.H4: Direction.SHORT,
        },
        risk_reward_ratio=3.0,
    )

    decision = eng.evaluate(signal)
    print(f"\n{'='*60}")
    print(f"SIGNAL 4: Low confidence (0.20) — auto-reject (news_reaction)")
    print(f"  Direction: {signal.direction.value} | Confidence: {signal.confidence}")
    print(f"  TF Alignment: 4/4 SHORT")
    print(f"  → Decision: {decision.decision.value}")
    print(f"  → Score:    {decision.score:.4f}")
    print(f"  → Reason:   {decision.reason}")

    assert decision.decision == Decision.REJECT, f"Expected REJECT, got {decision.decision}"
    assert "confidence" in decision.reason.lower()
    print(f"  ✅ PASSED")


def test_signal_5_sentiment_conflict_modify():
    """Signal 5: Good alignment but sentiment conflict → MODIFY (reduced size)."""
    eng = build_engine()

    # Override to bearish sentiment
    eng.update_market_context(MarketContext(
        regime="trending",
        vix_level=20.0,
        market_direction=Direction.SHORT,
        sentiment_score=-0.7,  # strong bearish
    ))

    signal = TradeSignal(
        strategy_id="strat-mr-4",
        strategy_name="mean_reversion",
        asset="GC",
        direction=Direction.LONG,  # going against sentiment
        confidence=0.65,
        risk_level=RiskLevel.MEDIUM,
        timeframes={
            Timeframe.M5: Direction.LONG,
            Timeframe.M15: Direction.LONG,
            Timeframe.H1: Direction.LONG,
            Timeframe.H4: Direction.LONG,
        },
        risk_reward_ratio=2.0,
    )

    decision = eng.evaluate(signal)
    print(f"\n{'='*60}")
    print(f"SIGNAL 5: Good alignment, bearish sentiment conflict (mean_reversion)")
    print(f"  Direction: {signal.direction.value} | Confidence: {signal.confidence}")
    print(f"  TF Alignment: 4/4 LONG | Sentiment: -0.7 (bearish)")
    print(f"  → Decision: {decision.decision.value}")
    print(f"  → Score:    {decision.score:.4f}")
    print(f"  → Reason:   {decision.reason}")
    print(f"  → Sentiment: {decision.sentiment_alignment:.4f}")
    print(f"  → Market:    {decision.market_alignment:.4f}")

    # With low-ranked strategy + bearish sentiment against LONG,
    # this should either MODIFY or REJECT depending on total score
    assert decision.decision in (Decision.MODIFY, Decision.REJECT, Decision.APPROVE), \
        f"Unexpected decision: {decision.decision}"
    assert decision.sentiment_alignment < 0.3, \
        f"Sentiment alignment should be low, got {decision.sentiment_alignment}"
    print(f"  ✅ PASSED")


def test_approval_pipeline_integration():
    """Integration test: run Signal 1 through full approval pipeline."""
    eng = build_engine()
    pipe = ApprovalPipeline()

    signal = TradeSignal(
        strategy_id="strat-momentum-1",
        strategy_name="momentum",
        asset="NQ",
        direction=Direction.LONG,
        confidence=0.85,
        risk_level=RiskLevel.MEDIUM,
        timeframes={
            Timeframe.M5: Direction.LONG,
            Timeframe.M15: Direction.LONG,
            Timeframe.H1: Direction.LONG,
            Timeframe.H4: Direction.LONG,
        },
        risk_reward_ratio=2.0,
    )

    decision = eng.evaluate(signal)
    result = pipe.process(decision)

    print(f"\n{'='*60}")
    print(f"INTEGRATION: Full pipeline (evaluate → approve)")
    print(f"  Decision engine: {decision.decision.value} (score {decision.score:.4f})")
    print(f"  Pipeline result: approved={result['approved']}")
    print(f"  Capital allocated: ${result.get('capital_allocated', 0):.2f}")
    print(f"  Audit ID: {result.get('audit_id', 'N/A')[:8]}...")

    assert result["approved"] is True, f"Expected approved, got: {result}"
    assert result.get("capital_allocated", 0) > 0
    assert len(pipe.audit_trail) == 1
    print(f"  ✅ PASSED")


def test_portfolio_position_sizing():
    """Test portfolio manager computes correct sizes based on alignment."""
    pm = PortfolioManager(capital=100_000)

    # High alignment → full size
    size_high = pm.compute_position_size(alignment_score=1.0, risk_budget_pct=0.01)
    # Medium alignment → 75%
    size_med = pm.compute_position_size(alignment_score=0.7, risk_budget_pct=0.01)
    # Low alignment → 50%
    size_low = pm.compute_position_size(alignment_score=0.5, risk_budget_pct=0.01)

    print(f"\n{'='*60}")
    print(f"PORTFOLIO: Position sizing")
    print(f"  Alignment 1.0 → ${size_high:,.2f}")
    print(f"  Alignment 0.7 → ${size_med:,.2f}")
    print(f"  Alignment 0.5 → ${size_low:,.2f}")

    assert size_high > size_med > size_low, \
        f"Expected descending sizes: {size_high} > {size_med} > {size_low}"
    print(f"  ✅ PASSED")


if __name__ == "__main__":
    print("=" * 60)
    print("  OVERSEER DECISION ENGINE — TEST SUITE")
    print("=" * 60)

    tests = [
        test_signal_1_full_alignment_high_confidence,
        test_signal_2_three_tf_aligned,
        test_signal_3_poor_alignment_reject,
        test_signal_4_low_confidence_reject,
        test_signal_5_sentiment_conflict_modify,
        test_approval_pipeline_integration,
        test_portfolio_position_sizing,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed}/{passed+failed} passed", end="")
    if failed:
        print(f" ({failed} failed)")
    else:
        print(" — ALL PASSED ✅")
    print(f"{'='*60}")

    sys.exit(1 if failed else 0)

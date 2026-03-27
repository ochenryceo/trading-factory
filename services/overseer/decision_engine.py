"""
Overseer Decision Engine — signal aggregation, conflict resolution, and trade scoring.

Collects signals from all 6 strategy agents, resolves conflicts via weighted voting,
scores multi-timeframe alignment, and outputs APPROVE / MODIFY / REJECT decisions.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger("overseer.decision_engine")


# --------------------------------------------------------------------------- #
# Enums & Data Structures                                                     #
# --------------------------------------------------------------------------- #

class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


class Timeframe(str, Enum):
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    MODIFY = "MODIFY"
    REJECT = "REJECT"


STRATEGY_AGENTS = [
    "momentum",
    "mean_reversion",
    "scalp",
    "trend",
    "news_reaction",
    "volume_flow",
]


@dataclass
class TradeSignal:
    """Standardized signal from any strategy agent."""
    strategy_id: str
    strategy_name: str
    asset: str
    direction: Direction
    confidence: float          # 0.0 – 1.0
    risk_level: RiskLevel
    timeframes: dict[Timeframe, Direction] = field(default_factory=dict)
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_reward_ratio: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PerformanceRanking:
    """Darwin-provided performance ranking for a strategy."""
    strategy_id: str
    rank: int                  # 1 = best
    win_rate: float
    sharpe: float
    pnl_30d: float
    weight: float = 1.0       # computed from rank


@dataclass
class MarketContext:
    """Current market regime info from Pulse / Feed."""
    regime: str = "normal"     # trending, ranging, volatile, normal
    vix_level: float = 15.0
    market_direction: Direction = Direction.FLAT
    sentiment_score: float = 0.0   # -1.0 (bearish) to 1.0 (bullish)


@dataclass
class TradeDecision:
    """Final output of the decision engine."""
    decision: Decision
    score: float
    signal: TradeSignal
    reason: str
    modifications: dict[str, Any] = field(default_factory=dict)
    alignment_score: float = 0.0
    confidence_weighted: float = 0.0
    performance_score: float = 0.0
    market_alignment: float = 0.0
    sentiment_alignment: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "score": round(self.score, 4),
            "reason": self.reason,
            "alignment_score": round(self.alignment_score, 4),
            "confidence_weighted": round(self.confidence_weighted, 4),
            "performance_score": round(self.performance_score, 4),
            "market_alignment": round(self.market_alignment, 4),
            "sentiment_alignment": round(self.sentiment_alignment, 4),
            "modifications": self.modifications,
            "signal": {
                "strategy_id": self.signal.strategy_id,
                "strategy_name": self.signal.strategy_name,
                "asset": self.signal.asset,
                "direction": self.signal.direction.value,
                "confidence": self.signal.confidence,
                "risk_level": self.signal.risk_level.value,
            },
            "timestamp": self.timestamp.isoformat(),
        }


# --------------------------------------------------------------------------- #
# Decision Engine                                                             #
# --------------------------------------------------------------------------- #

class DecisionEngine:
    """
    Core decision engine. Aggregates signals, resolves conflicts, and scores trades.

    Scoring formula:
        final = confidence * 0.30
              + performance * 0.25
              + multi_tf_alignment * 0.25
              + market_alignment * 0.10
              + sentiment_alignment * 0.10
    """

    # Thresholds
    MIN_CONFIDENCE = 0.35
    MIN_RISK_REWARD = 1.5
    MIN_APPROVAL_SCORE = 0.50
    MODIFY_SCORE_FLOOR = 0.40

    def __init__(self) -> None:
        self.performance_rankings: dict[str, PerformanceRanking] = {}
        self.market_context = MarketContext()
        self._decision_history: list[TradeDecision] = []

    # ------------------------------------------------------------------ #
    # Configuration                                                      #
    # ------------------------------------------------------------------ #

    def update_rankings(self, rankings: list[PerformanceRanking]) -> None:
        """Update Darwin-provided performance rankings and compute weights."""
        total = len(rankings)
        for r in rankings:
            # Inverse rank weighting: rank 1 → highest weight
            r.weight = max(0.1, 1.0 - (r.rank - 1) / max(total, 1))
            self.performance_rankings[r.strategy_id] = r
        logger.info("Updated %d performance rankings", len(rankings))

    def update_market_context(self, ctx: MarketContext) -> None:
        self.market_context = ctx

    # ------------------------------------------------------------------ #
    # Multi-Timeframe Alignment                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def score_timeframe_alignment(
        timeframes: dict[Timeframe, Direction],
        target_direction: Direction,
    ) -> float:
        """
        Score multi-timeframe alignment:
          4/4 aligned → 1.0 (HIGH)
          3/4 aligned → 0.7 (MEDIUM)
          2/4 or less → 0.3 (LOW) → triggers REJECT
        """
        if not timeframes:
            return 0.3  # no TF data = low confidence

        aligned = sum(1 for d in timeframes.values() if d == target_direction)
        total = len(timeframes)

        # Normalize to 4-TF scale
        if total < 4:
            ratio = aligned / total
            if ratio >= 1.0:
                return 1.0
            elif ratio >= 0.75:
                return 0.7
            else:
                return 0.3

        if aligned == 4:
            return 1.0
        elif aligned == 3:
            return 0.7
        else:
            return 0.3

    # ------------------------------------------------------------------ #
    # Performance Score                                                  #
    # ------------------------------------------------------------------ #

    def get_performance_score(self, strategy_id: str) -> float:
        """Normalize strategy performance to 0-1 score using Darwin ranking."""
        ranking = self.performance_rankings.get(strategy_id)
        if not ranking:
            return 0.5  # neutral default

        # Composite: weight from rank + win_rate + sharpe normalization
        rank_score = ranking.weight
        wr_score = min(ranking.win_rate, 1.0)
        sharpe_score = min(max(ranking.sharpe / 3.0, 0.0), 1.0)  # 3.0 = excellent

        return rank_score * 0.4 + wr_score * 0.3 + sharpe_score * 0.3

    # ------------------------------------------------------------------ #
    # Market & Sentiment Alignment                                       #
    # ------------------------------------------------------------------ #

    def score_market_alignment(self, signal: TradeSignal) -> float:
        """How well does the signal align with current market regime?"""
        ctx = self.market_context

        score = 0.5  # neutral baseline

        # Direction alignment with market
        if signal.direction == ctx.market_direction:
            score += 0.3
        elif ctx.market_direction == Direction.FLAT:
            score += 0.1
        else:
            score -= 0.2

        # Penalize in extreme volatility
        if ctx.vix_level > 30:
            score -= 0.2
        elif ctx.vix_level > 25:
            score -= 0.1

        # Bonus for trading WITH the regime
        if ctx.regime == "trending" and signal.strategy_name in ("momentum", "trend"):
            score += 0.1
        elif ctx.regime == "ranging" and signal.strategy_name == "mean_reversion":
            score += 0.1

        return max(0.0, min(1.0, score))

    def score_sentiment_alignment(self, signal: TradeSignal) -> float:
        """Does sentiment support this trade direction?"""
        sentiment = self.market_context.sentiment_score  # -1.0 to 1.0

        if signal.direction == Direction.LONG:
            # Positive sentiment → good for longs
            return max(0.0, min(1.0, 0.5 + sentiment * 0.5))
        elif signal.direction == Direction.SHORT:
            # Negative sentiment → good for shorts
            return max(0.0, min(1.0, 0.5 - sentiment * 0.5))
        return 0.5

    # ------------------------------------------------------------------ #
    # Conflict Resolution (Weighted Voting)                              #
    # ------------------------------------------------------------------ #

    def resolve_conflicts(self, signals: list[TradeSignal]) -> Direction:
        """
        Weighted voting across signals using Darwin performance rankings.
        Returns the consensus direction.
        """
        votes: dict[Direction, float] = {Direction.LONG: 0, Direction.SHORT: 0, Direction.FLAT: 0}

        for sig in signals:
            weight = 1.0
            ranking = self.performance_rankings.get(sig.strategy_id)
            if ranking:
                weight = ranking.weight
            votes[sig.direction] += weight * sig.confidence

        winner = max(votes, key=lambda d: votes[d])
        logger.debug("Conflict resolution votes: %s → winner: %s", votes, winner)
        return winner

    # ------------------------------------------------------------------ #
    # Core Evaluation                                                    #
    # ------------------------------------------------------------------ #

    def evaluate(self, signal: TradeSignal) -> TradeDecision:
        """
        Evaluate a single trade signal through the full decision pipeline.

        Returns TradeDecision with APPROVE / MODIFY / REJECT.
        """
        reasons: list[str] = []

        # --- Pre-filters ---
        if signal.confidence < self.MIN_CONFIDENCE:
            return self._reject(signal, f"Low confidence ({signal.confidence:.2f} < {self.MIN_CONFIDENCE})")

        if signal.risk_reward_ratio is not None and signal.risk_reward_ratio < self.MIN_RISK_REWARD:
            return self._reject(signal, f"Poor risk/reward ({signal.risk_reward_ratio:.2f} < {self.MIN_RISK_REWARD})")

        if signal.risk_level == RiskLevel.EXTREME:
            return self._reject(signal, "Extreme risk level — auto-reject")

        # --- Component scores ---
        alignment = self.score_timeframe_alignment(signal.timeframes, signal.direction)
        if alignment <= 0.3:
            return self._reject(signal, f"Multi-TF alignment too low ({alignment:.2f})",
                                alignment=alignment)

        performance = self.get_performance_score(signal.strategy_id)
        market_align = self.score_market_alignment(signal)
        sentiment_align = self.score_sentiment_alignment(signal)

        # Sentiment conflict check
        if sentiment_align < 0.25:
            reasons.append("Sentiment conflicts with direction")

        # --- Final score ---
        final_score = (
            signal.confidence * 0.30
            + performance * 0.25
            + alignment * 0.25
            + market_align * 0.10
            + sentiment_align * 0.10
        )

        # --- Decision ---
        if final_score >= self.MIN_APPROVAL_SCORE and not reasons:
            decision = Decision.APPROVE
            reason = f"Score {final_score:.4f} ≥ {self.MIN_APPROVAL_SCORE} threshold"
        elif final_score >= self.MODIFY_SCORE_FLOOR:
            decision = Decision.MODIFY
            modifications = self._compute_modifications(final_score, alignment, signal)
            reason_parts = [f"Score {final_score:.4f} in modify range"]
            reason_parts.extend(reasons)
            td = TradeDecision(
                decision=decision,
                score=final_score,
                signal=signal,
                reason="; ".join(reason_parts),
                modifications=modifications,
                alignment_score=alignment,
                confidence_weighted=signal.confidence,
                performance_score=performance,
                market_alignment=market_align,
                sentiment_alignment=sentiment_align,
            )
            self._decision_history.append(td)
            return td
        else:
            decision = Decision.REJECT
            reason_parts = [f"Score {final_score:.4f} below {self.MODIFY_SCORE_FLOOR} threshold"]
            reason_parts.extend(reasons)
            return self._reject(signal, "; ".join(reason_parts), final_score,
                                alignment, performance, market_align, sentiment_align)

        td = TradeDecision(
            decision=decision,
            score=final_score,
            signal=signal,
            reason=reason,
            alignment_score=alignment,
            confidence_weighted=signal.confidence,
            performance_score=performance,
            market_alignment=market_align,
            sentiment_alignment=sentiment_align,
        )
        self._decision_history.append(td)
        return td

    # ------------------------------------------------------------------ #
    # Batch Evaluation                                                   #
    # ------------------------------------------------------------------ #

    def evaluate_batch(self, signals: list[TradeSignal]) -> list[TradeDecision]:
        """Evaluate multiple signals. Resolves conflicts first if same asset."""
        # Group by asset
        by_asset: dict[str, list[TradeSignal]] = {}
        for s in signals:
            by_asset.setdefault(s.asset, []).append(s)

        decisions: list[TradeDecision] = []
        for asset, asset_signals in by_asset.items():
            if len(asset_signals) > 1:
                # Resolve conflicts — only approve signals aligned with consensus
                consensus = self.resolve_conflicts(asset_signals)
                for sig in asset_signals:
                    if sig.direction != consensus:
                        decisions.append(self._reject(
                            sig,
                            f"Conflicts with consensus direction ({consensus.value}) for {asset}",
                        ))
                    else:
                        decisions.append(self.evaluate(sig))
            else:
                decisions.append(self.evaluate(asset_signals[0]))

        return decisions

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _reject(
        self,
        signal: TradeSignal,
        reason: str,
        score: float = 0.0,
        alignment: float = 0.0,
        performance: float = 0.0,
        market_align: float = 0.0,
        sentiment_align: float = 0.0,
    ) -> TradeDecision:
        td = TradeDecision(
            decision=Decision.REJECT,
            score=score,
            signal=signal,
            reason=reason,
            alignment_score=alignment,
            confidence_weighted=signal.confidence,
            performance_score=performance,
            market_alignment=market_align,
            sentiment_alignment=sentiment_align,
        )
        self._decision_history.append(td)
        logger.info("REJECT %s/%s: %s", signal.strategy_name, signal.asset, reason)
        return td

    @staticmethod
    def _compute_modifications(score: float, alignment: float, signal: TradeSignal) -> dict[str, Any]:
        """Suggest modifications for borderline trades."""
        mods: dict[str, Any] = {}

        # Reduce size for weaker alignment
        if alignment < 0.7:
            mods["size_multiplier"] = 0.5
            mods["reason_size"] = "Reduced size due to weak TF alignment"

        # Delay entry for moderate scores
        if score < 0.55:
            mods["delay_entry_seconds"] = 60
            mods["reason_timing"] = "Delay entry — score is borderline"

        # Tighten stop for higher risk
        if signal.risk_level == RiskLevel.HIGH:
            mods["tighten_stop_pct"] = 0.25
            mods["reason_risk"] = "Tightened stop — elevated risk level"

        return mods

    @property
    def history(self) -> list[TradeDecision]:
        return list(self._decision_history)

    def clear_history(self) -> None:
        self._decision_history.clear()

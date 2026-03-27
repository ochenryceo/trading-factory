"""Strategy lifecycle tracker — orchestrates promotion, demotion, and retirement."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import EventType, PipelineStage, StrategyStatus
from core.ledger import record_demotion, record_promotion
from core.models import Strategy, StrategyMetric
from core.pipeline import (
    TransitionResult,
    can_promote,
    demote,
    kill_switch_demote,
)


async def promote_strategy(
    session: AsyncSession,
    strategy_id: uuid.UUID,
    actor: str,
    metrics: dict[str, Any] | None = None,
) -> TransitionResult:
    """Attempt to promote a strategy to the next pipeline stage."""
    strategy = await session.get(Strategy, strategy_id)
    if strategy is None:
        return TransitionResult(
            allowed=False,
            from_stage=PipelineStage.IDEA,
            to_stage=None,
            event_type=None,
            reason=f"Strategy {strategy_id} not found",
        )

    current = PipelineStage(strategy.current_stage)
    result = can_promote(current, metrics)

    if result.allowed and result.to_stage:
        strategy.current_stage = result.to_stage.value
        strategy.consecutive_demotions = 0
        await record_promotion(
            session, strategy, current, result.to_stage, actor, result.reason, metrics
        )

    return result


async def demote_strategy(
    session: AsyncSession,
    strategy_id: uuid.UUID,
    actor: str,
    reason: str = "Performance degradation",
) -> TransitionResult:
    """Demote a strategy one stage. 3 consecutive → retire permanently."""
    strategy = await session.get(Strategy, strategy_id)
    if strategy is None:
        return TransitionResult(
            allowed=False,
            from_stage=PipelineStage.IDEA,
            to_stage=None,
            event_type=None,
            reason=f"Strategy {strategy_id} not found",
        )

    current = PipelineStage(strategy.current_stage)
    result = demote(current, reason, strategy.consecutive_demotions)

    if result.allowed and result.to_stage:
        strategy.current_stage = result.to_stage.value
        strategy.consecutive_demotions += 1

        if result.new_status == StrategyStatus.RETIRED:
            strategy.status = StrategyStatus.RETIRED.value
            strategy.is_active = False

        await record_demotion(
            session, strategy, current, result.to_stage, actor, result.reason,
            event_type=result.event_type or EventType.STRATEGY_DEMOTED,
        )

    return result


async def kill_strategy(
    session: AsyncSession,
    strategy_id: uuid.UUID,
    actor: str,
    reason: str,
) -> TransitionResult:
    """Kill-switch triggered — demote to BACKTEST and mark KILLED."""
    strategy = await session.get(Strategy, strategy_id)
    if strategy is None:
        return TransitionResult(
            allowed=False,
            from_stage=PipelineStage.IDEA,
            to_stage=None,
            event_type=None,
            reason=f"Strategy {strategy_id} not found",
        )

    current = PipelineStage(strategy.current_stage)
    result = kill_switch_demote(current, reason)

    if result.allowed and result.to_stage:
        strategy.current_stage = result.to_stage.value
        strategy.status = StrategyStatus.KILLED.value
        strategy.is_active = False

        await record_demotion(
            session, strategy, current, result.to_stage, actor, result.reason,
            event_type=EventType.STRATEGY_KILLED,
        )

    return result


async def get_latest_metrics(
    session: AsyncSession, strategy_id: uuid.UUID
) -> StrategyMetric | None:
    """Get the most recent metrics row for a strategy."""
    result = await session.execute(
        select(StrategyMetric)
        .where(StrategyMetric.strategy_id == strategy_id)
        .order_by(StrategyMetric.timestamp.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
